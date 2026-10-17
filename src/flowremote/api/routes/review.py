"""Record one review decision on one exception.

The endpoint is the only place that changes an exception's status. It applies
three rules in order: the task must be visible to the signed-in user, a replayed
decision id is a no-op, and the action itself must be legal (see
``review.decide``). The decision row and the exception update happen in one
transaction, so a failure cannot leave them out of step.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page
from flowremote.contracts.models import ExceptionItem, User
from flowremote.control_plane.db import Database, new_id, utc_now
from flowremote.control_plane.review import DecisionRejected, decide

router = APIRouter()


@router.post("/tasks/{task_id}/exceptions/{record_id}/decisions")
async def record_decision(
    task_id: str,
    record_id: str,
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    if context["task"]["status"] != "review_required":
        context["error"] = "This task has already moved past review."
        return render(request, "task.html", context, status_code=400)

    rows = db.query(
        "SELECT * FROM exceptions WHERE task_id = ? AND record_id = ?", (task_id, record_id)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="exception not found")
    exception = ExceptionItem.from_row(rows[0])

    form = await read_form(request)
    action = (form.get("action") or "").strip()
    value = form.get("value")
    decision_id = (form.get("decision_id") or "").strip()

    # A repeated submit (double click, back button) must not count twice.
    if decision_id and db.query("SELECT id FROM decisions WHERE decision_id = ?", (decision_id,)):
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    try:
        result = decide(exception, action, value)
    except DecisionRejected as exc:
        context = load_task_page(db, user, task_id) or context
        context["error"] = str(exc)
        return render(request, "task.html", context, status_code=400)

    now = utc_now()
    with db.transaction():
        db.execute(
            "INSERT INTO decisions (id, exception_id, decision_id, action, new_value,"
            " by_user, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("DEC"),
                exception.id,
                decision_id or new_id("K"),
                result.action.value,
                result.resolved_value,
                user.id,
                now,
            ),
        )
        db.execute(
            "UPDATE exceptions SET status = ?, resolved_value = ?, reviewed_by = ?,"
            " reviewed_at = ? WHERE id = ?",
            (result.status.value, result.resolved_value, user.id, now, exception.id),
        )
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)
