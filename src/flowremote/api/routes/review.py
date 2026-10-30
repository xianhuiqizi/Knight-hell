"""Record one review decision on one exception.

The endpoint is the only place that changes an exception's status. It applies
three rules in order: the task must be visible to the signed-in user, a replayed
decision id is a no-op, and the action itself must be legal (see
``review.decide``). The decision row and the exception update happen in one
transaction, so a failure cannot leave them out of step.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from flowremote.agent.service import accepted_changes
from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page
from flowremote.contracts.models import ExceptionItem, User
from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import Database, new_id, utc_now
from flowremote.control_plane.order_validation import FIELDS, ValidationError, apply_correction
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
    form = await read_form(request)
    action = (form.get("action") or "").strip()
    value = form.get("value")
    decision_id = (form.get("decision_id") or "").strip()

    try:
        with db.transaction():
            if decision_id and db.query(
                "SELECT id FROM decisions WHERE decision_id = ?", (decision_id,)
            ):
                return RedirectResponse(f"/tasks/{task_id}#exc-{record_id}", status_code=303)
            if db.scalar("SELECT status FROM tasks WHERE id = ?", (task_id,)) != "review_required":
                raise DecisionRejected("This task has already moved past review.")
            exception = ExceptionItem.from_row(
                db.query(
                    "SELECT * FROM exceptions WHERE task_id = ? AND record_id = ?",
                    (task_id, record_id),
                )[0]
            )
            real_order = db.scalar(
                "SELECT 1 FROM order_inputs WHERE task_id = ? AND record_id = ?",
                (task_id, record_id),
            )
            changes = {}
            if real_order and action == "edit":
                changes = {
                    field: form["field_" + field] for field in FIELDS if "field_" + field in form
                }
                if not changes:
                    fields = exception.flagged_fields.split(", ")
                    if len(fields) != 1:
                        raise DecisionRejected("Use Edit order to correct all flagged fields.")
                    changes = {fields[0]: value or ""}
                value = json.dumps(changes, ensure_ascii=False)
            result = decide(exception, action, value)
            if real_order and action != "skip":
                if action == "accept":
                    suggested = accepted_changes(db, exception)
                    if not suggested:
                        raise DecisionRejected(
                            "this AI suggestion cannot be verified as a complete correction"
                        )
                    changes = suggested
                apply_correction(db, task_id, record_id, changes)
            now = utc_now()
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
            log_event(
                db,
                task_id=task_id,
                kind="exception_decided",
                actor=user.name,
                occurred_at=now,
                description={
                    "accept": f"Accepted the suggestion for {record_id}",
                    "edit": f"Corrected {record_id} by hand",
                    "skip": f"Skipped {record_id}",
                }[result.action.value],
                payload={
                    "record_id": record_id,
                    "action": result.action.value,
                    "value": result.resolved_value,
                },
            )
    except (DecisionRejected, ValidationError) as exc:
        context = load_task_page(db, user, task_id) or context
        context["error"] = str(exc)
        return render(request, "task.html", context, status_code=400)
    # Jump back to the row just decided, so the reviewer does not lose their place.
    return RedirectResponse(f"/tasks/{task_id}#exc-{record_id}", status_code=303)
