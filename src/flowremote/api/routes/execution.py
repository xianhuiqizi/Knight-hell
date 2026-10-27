"""Execution progress, results and the activity export (Feature 2).

Three guards repeat on every route here:

* the task must be visible to the signed-in user, otherwise 404 (never 403, so
  the response cannot confirm that someone else's task exists);
* the task must be past approval, otherwise the task page is the right place;
* before the run exists there is nothing to show.

The step endpoint is the only place that moves a run forward, and it re-checks
the run's state itself, so a hand-made request cannot finish a run twice.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page
from flowremote.contracts.enums import ActorKind, RunState
from flowremote.contracts.models import ExecutionRun, ModelError, User
from flowremote.control_plane.activity import ENGINE_NAME, log_event, recent_events
from flowremote.control_plane.db import Database, utc_now
from flowremote.rpa.execution import (
    STEP_SIZE,
    ExecutionError,
    format_duration,
    next_step,
    success_rate,
)

router = APIRouter()


def _run_model(db: Database, task_id: str) -> ExecutionRun | None:
    rows = db.query(
        "SELECT * FROM execution_runs WHERE task_id = ? ORDER BY attempt DESC LIMIT 1", (task_id,)
    )
    if not rows:
        return None
    try:
        return ExecutionRun.from_row(rows[0])
    except ModelError:
        return None


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept


def _snapshot(run: ExecutionRun, failure: str | None = None) -> dict:
    return {
        "status": str(run.status),
        "approved": run.approved_count,
        "written": run.written_count,
        "synced": run.synced_count,
        "progress_pct": run.progress_percent,
        "duration_ms": run.duration_ms,
        "failure": failure,
    }


def _elapsed_ms(started_at: str, finished_at: str) -> int:
    """Milliseconds between two second-precision UTC timestamps."""
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(finished_at)
    return max(0, int((end - start).total_seconds() * 1000))


def _fail_at() -> int | None:
    """Optional demonstration switch: make record N fail, once, from the env."""
    raw = os.environ.get("FLOWREMOTE_EXECUTION_FAIL_AT", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.get("/tasks/{task_id}/execution", response_class=HTMLResponse)
def execution_page(
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
    run = _run_model(db, task_id)
    if run is None:
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    if run.status is not RunState.EXECUTING:
        return RedirectResponse(f"/tasks/{task_id}/results", status_code=303)
    return render(
        request,
        "execution.html",
        {
            "user": user,
            "task": context["task"],
            "approval": context["approval"],
            "run": run,
            "step_size": STEP_SIZE,
            "progress": run.progress_percent,
        },
    )


@router.post("/tasks/{task_id}/execution/step")
def execution_step(
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
    run = _run_model(db, task_id)
    if run is None:
        if _wants_json(request):
            return JSONResponse({"error": "this task has no execution run"}, status_code=400)
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    if run.status is not RunState.EXECUTING:
        if _wants_json(request):
            return JSONResponse(_snapshot(run), status_code=200)
        return RedirectResponse(f"/tasks/{task_id}/results", status_code=303)

    try:
        outcome = next_step(
            approved=run.approved_count,
            written=run.written_count,
            status=run.status,
            step=STEP_SIZE,
            fail_at=_fail_at(),
        )
    except (ExecutionError, ValueError) as exc:
        if _wants_json(request):
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    now = utc_now()
    finished = outcome.status is not RunState.EXECUTING
    # The clock starts with the first step, not with the approval: a run that sat
    # waiting for the operator to open the page must not report that wait as
    # execution time.
    started_at = run.started_at if run.written_count else now
    duration_ms = _elapsed_ms(started_at, now) if finished else None
    with db.transaction():
        db.execute(
            "UPDATE execution_runs SET written_count = ?, synced_count = ?, status = ?,"
            " started_at = ?, finished_at = ?, duration_ms = ? WHERE id = ?",
            (
                outcome.written,
                outcome.written,
                str(outcome.status),
                started_at,
                now if finished else None,
                duration_ms,
                run.id,
            ),
        )
        if outcome.status is RunState.COMPLETE:
            db.execute(
                "UPDATE tasks SET status = 'complete', updated_at = ? WHERE id = ?", (now, task_id)
            )
            log_event(
                db,
                task_id=task_id,
                run_id=run.id,
                kind="execution_completed",
                actor=ENGINE_NAME,
                actor_kind=ActorKind.ENGINE,
                occurred_at=now,
                description=(
                    f"Simulated RPA wrote {outcome.written} records to"
                    f" {context['task']['primary_target']} and synced"
                    f" {outcome.written} to {context['task']['secondary_target']}"
                ),
                payload={
                    "written": outcome.written,
                    "synced": outcome.written,
                    "approved": run.approved_count,
                },
            )
        elif outcome.status is RunState.PARTIAL:
            log_event(
                db,
                task_id=task_id,
                run_id=run.id,
                kind="execution_failed",
                actor=ENGINE_NAME,
                actor_kind=ActorKind.ENGINE,
                occurred_at=now,
                description=outcome.failure or "The simulated write stopped early",
                payload={
                    "written": outcome.written,
                    "approved": run.approved_count,
                    "failure": outcome.failure,
                },
            )

    updated = _run_model(db, task_id) or run
    if _wants_json(request):
        return JSONResponse(_snapshot(updated, outcome.failure), status_code=200)
    if updated.status is RunState.EXECUTING:
        return RedirectResponse(f"/tasks/{task_id}/execution", status_code=303)
    return RedirectResponse(f"/tasks/{task_id}/results", status_code=303)


@router.get("/tasks/{task_id}/execution.json")
def execution_state(
    task_id: str,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    """The polling endpoint the progress page uses."""
    if user is None:
        raise HTTPException(status_code=303, detail="/login")
    if load_task_page(db, user, task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    run = _run_model(db, task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no execution run")
    return JSONResponse(_snapshot(run))


@router.get("/tasks/{task_id}/results", response_class=HTMLResponse)
def results_page(
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
    run = _run_model(db, task_id)
    if run is None:
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    if run.status is RunState.EXECUTING:
        return RedirectResponse(f"/tasks/{task_id}/execution", status_code=303)
    approval = context["approval"]
    return render(
        request,
        "results.html",
        {
            "user": user,
            "task": context["task"],
            "run": run,
            "approval": approval,
            "success": f"{run.written_count}/{context['task']['batch_size']}",
            "success_rate": f"{success_rate(run.written_count, context['task']['batch_size']):.1f}%",
            "duration": format_duration(run.duration_ms),
            "events": recent_events(db, task_id),
            "partial": run.status is RunState.PARTIAL,
        },
    )


@router.get("/tasks/{task_id}/activity.json")
def activity_export(
    task_id: str,
    user: User | None = Depends(current_user),
    db: Database = Depends(get_db),
):
    """The audit trail as JSON, so it can be kept outside the demo database."""
    if user is None:
        raise HTTPException(status_code=303, detail="/login")
    if load_task_page(db, user, task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    events = []
    for row in recent_events(db, task_id, limit=500):
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except (TypeError, ValueError):
            item["payload"] = {}
        events.append(item)
    return JSONResponse({"task_id": task_id, "events": events})
