"""Task list and task detail.

Visibility rule, which is the point of P2: an operator sees only the tasks
they own; an admin sees every task. Asking for a task you cannot see returns
404 rather than 403, so the response does not confirm that the task exists.
"""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.rendering import render
from flowremote.contracts.enums import Role
from flowremote.contracts.models import User
from flowremote.control_plane.db import Database

router = APIRouter()

TASK_STATUS_LABELS = {
    "ready": "Awaiting validation",
    "validating": "Validating",
    "review_required": "Review required",
    "pending_approval": "Pending approval",
    "executing": "Executing",
    "complete": "Complete",
}

EXCEPTION_STATUS_LABELS = {
    "unresolved": "Unresolved",
    "accepted": "Accepted",
    "manual": "Manual",
    "skipped": "Skipped",
}

SUMMARY_SQL = """
SELECT t.id, t.workflow, t.batch_size, t.status, t.source_file, t.source_location,
       t.primary_target, t.secondary_target, t.owner_id, t.updated_at,
       (SELECT COUNT(*) FROM source_records r
         WHERE r.task_id = t.id AND r.outcome = 'passed') AS passed,
       (SELECT COUNT(*) FROM source_records r
         WHERE r.task_id = t.id AND r.outcome = 'flagged') AS flagged,
       (SELECT COUNT(*) FROM exceptions e WHERE e.task_id = t.id) AS exceptions,
       (SELECT COUNT(*) FROM exceptions e
         WHERE e.task_id = t.id AND e.status = 'unresolved') AS unresolved,
       -- Ready to write = records that already passed + flagged records a person
       -- resolved. A skipped record is excluded, so ready + skipped = input.
       ((SELECT COUNT(*) FROM source_records r
          WHERE r.task_id = t.id AND r.outcome = 'passed')
        + (SELECT COUNT(*) FROM exceptions e
            WHERE e.task_id = t.id AND e.status IN ('accepted', 'manual'))) AS ready,
       (SELECT COUNT(*) FROM exceptions e
         WHERE e.task_id = t.id AND e.status = 'skipped') AS skipped
FROM tasks t
"""


def _visibility(user: User, task_id: str | None = None) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if task_id:
        clauses.append("t.id = ?")
        params.append(task_id)
    if user.role is not Role.ADMIN:
        clauses.append("t.owner_id = ?")
        params.append(user.id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _decorate_task(row: dict) -> dict:
    task = dict(row)
    task["status_label"] = TASK_STATUS_LABELS.get(task["status"], task["status"])
    return task


def _decorate_exception(row: dict) -> dict:
    item = dict(row)
    item["status_label"] = EXCEPTION_STATUS_LABELS.get(item["status"], item["status"])
    confidence = item.get("confidence")
    item["confidence_label"] = (
        f"{round(float(confidence) * 100)}%" if confidence is not None else "no suggestion"
    )
    # A fresh idempotency key per rendered row: a double-click sends the same
    # value twice, and the second request is recognised as a replay.
    item["decision_id"] = secrets.token_hex(8) if item["status"] == "unresolved" else ""
    return item


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    where, params = _visibility(user)
    rows = db.query(SUMMARY_SQL + where + " ORDER BY t.updated_at DESC", params)
    return render(
        request,
        "home.html",
        {"user": user, "tasks": [_decorate_task(row) for row in rows]},
    )


def load_task_page(db: Database, user: User, task_id: str, page: int = 1) -> dict | None:
    """Everything the task page needs, or None when the task is not visible."""
    where, params = _visibility(user, task_id)
    rows = db.query(SUMMARY_SQL + where, params)
    if not rows:
        return None
    task = _decorate_task(rows[0])
    total_pages = max(1, (task["exceptions"] + 99) // 100)
    page = min(max(1, page), total_pages)
    exceptions = [
        _decorate_exception(row)
        for row in db.query(
            "SELECT e.record_id, e.issue, e.flagged_fields, e.original_value,"
            " e.suggestion, e.confidence, e.reason, e.status, e.resolved_value,"
            " e.reviewed_at, u.name AS reviewer_name, i.excel_row, i.order_id, i.current_json"
            " FROM exceptions e LEFT JOIN users u ON u.id = e.reviewed_by"
            " LEFT JOIN order_inputs i ON i.task_id = e.task_id AND i.record_id = e.record_id"
            " WHERE e.task_id = ? ORDER BY i.excel_row, e.record_id LIMIT 100 OFFSET ?",
            (task_id, (page - 1) * 100),
        )
    ]
    for item in exceptions:
        item["edit_values"] = json.loads(item["current_json"]) if item["current_json"] else None
    unresolved = task["unresolved"]
    validations = db.query("SELECT * FROM task_validations WHERE task_id = ?", (task_id,))
    validation = validations[0] if validations else None
    if validation:
        validation["summary"] = json.loads(validation["summary_json"])
        validation["issue_count"] = sum(validation["summary"].values())
    approvals = db.query(
        "SELECT a.attempt, a.approved_count, a.skipped_count, a.approved_at,"
        " u.name AS approver_name"
        " FROM approvals a LEFT JOIN users u ON u.id = a.approver_id"
        " WHERE a.task_id = ? ORDER BY a.attempt DESC LIMIT 1",
        (task_id,),
    )
    return {
        "user": user,
        "task": task,
        "exceptions": exceptions,
        "unresolved": unresolved,
        "proceed_enabled": unresolved == 0 and task["status"] == "review_required",
        "upload": next(
            iter(
                db.query(
                    "SELECT worksheet, byte_size FROM task_uploads WHERE task_id = ?", (task_id,)
                )
            ),
            None,
        ),
        "approval": approvals[0] if approvals else None,
        "error": None,
        "validation": validation,
        "page": page,
        "total_pages": total_pages,
    }


def task_visible(db: Database, user: User, task_id: str) -> bool:
    where, params = _visibility(user, task_id)
    return bool(db.query("SELECT 1 FROM tasks t" + where, params))


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(
    task_id: str,
    request: Request,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
    page: int = 1,
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id, page)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    return render(request, "task.html", context)
