"""The approval stage: proceed, approve, and go back to review.

Three transitions, each with its own guard:

    review_required --proceed (unresolved = 0)--> pending_approval
    pending_approval --approve--> executing        (writes the approvals row)
    pending_approval --back--> review_required

Every guard is checked here as well as in the database, so a hand-made request
cannot skip a step.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page
from flowremote.contracts.models import User
from flowremote.control_plane.db import Database, utc_now

router = APIRouter()


def _forbidden(
    request: Request, context: dict, message: str, template: str = "task.html"
) -> HTMLResponse:
    context["error"] = message
    return render(request, template, context, status_code=400)


@router.get("/tasks/{task_id}/approval", response_class=HTMLResponse)
def approval_page(
    task_id: str,
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    if context["task"]["status"] not in ("pending_approval", "executing", "complete"):
        # The batch is still in review; the task page is the right place.
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    return render(request, "approval.html", context)


@router.post("/tasks/{task_id}/proceed")
def proceed(
    task_id: str,
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
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    if context["unresolved"]:
        return _forbidden(
            request,
            context,
            f"{context['unresolved']} exception(s) are still unresolved; "
            "approval unlocks only at zero.",
        )
    db.execute(
        "UPDATE tasks SET status = 'pending_approval', updated_at = ? WHERE id = ?",
        (utc_now(), task_id),
    )
    return RedirectResponse(f"/tasks/{task_id}/approval", status_code=303)


@router.post("/tasks/{task_id}/approval")
def approve(
    task_id: str,
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    if context["approval"]:
        # A repeated submit must not authorise the write twice.
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    if context["task"]["status"] != "pending_approval":
        return _forbidden(request, context, "This batch is not waiting for approval.")
    if context["unresolved"]:
        return _forbidden(request, context, "Unresolved exceptions block approval.")

    ready = int(context["task"]["ready"])
    skipped = int(context["task"]["skipped"])
    if ready == 0:
        return _forbidden(request, context, "There is nothing approved to write.")

    now = utc_now()
    with db.transaction():
        db.execute(
            "INSERT INTO approvals (id, task_id, attempt, approver_id, approved_count,"
            " skipped_count, approved_at) VALUES (?, ?, 1, ?, ?, ?, ?)",
            (f"APR-{task_id}-1", task_id, user.id, ready, skipped, now),
        )
        db.execute(
            "UPDATE tasks SET status = 'executing', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/back-to-review")
def back_to_review(
    task_id: str,
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    if context["approval"]:
        return _forbidden(request, context, "This batch is already approved.")
    if context["task"]["status"] != "pending_approval":
        return _forbidden(request, context, "This batch is not waiting for approval.")
    db.execute(
        "UPDATE tasks SET status = 'review_required', updated_at = ? WHERE id = ?",
        (utc_now(), task_id),
    )
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)
