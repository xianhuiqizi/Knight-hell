"""Multi-source normalization: upload, progress, review queue and download."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from flowremote.api.deps import current_user, get_db
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import task_visible
from flowremote.contracts.models import User
from flowremote.contracts.normalization import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES
from flowremote.control_plane.activity import recent_events
from flowremote.control_plane.db import Database
from flowremote.control_plane.normalization_jobs import (
    NormalizationJobError,
    cancel_normalization,
    create_normalization_task,
    download_filename,
    download_workbook,
    get_batch,
    normalization_snapshot,
    recognize_normalization_task,
    start_normalization,
    tick_normalization,
)
from flowremote.control_plane.normalization_review import (
    ReviewError,
    confirm_issue,
    skip_issue,
)

router = APIRouter()
SessionUser = Annotated[User | None, Depends(current_user)]
RequestDatabase = Annotated[Database, Depends(get_db)]

STAGE_ORDER = ("upload", "detect", "map", "ai", "human", "complete")
EVENT_LABELS = {
    "normalize_upload": ("Upload", "upload"),
    "normalize_started": ("Start", "upload"),
    "normalize_detect": ("Detect", "detect"),
    "normalize_map": ("Map", "map"),
    "normalize_normalize": ("Normalize", "normalize"),
    "normalize_ai": ("AI", "ai"),
    "normalize_human": ("Human", "human"),
    "normalize_complete": ("Complete", "complete"),
    "normalize_canceled": ("Canceled", "upload"),
}
EVENT_ORDER = {
    "normalize_upload": 0,
    "normalize_detect": 1,
    "normalize_map": 2,
    "normalize_started": 3,
    "normalize_normalize": 4,
    "normalize_ai": 5,
    "normalize_human": 6,
    "normalize_complete": 7,
    "normalize_canceled": 8,
}
ISSUE_LABELS = {
    "missing_value": "Missing value",
    "unit_conflict": "Unit conflict",
    "cross_file_conflict": "Cross-file conflict",
    "file_error": "File could not be read",
    "invalid_value": "Invalid value",
    "amount_mismatch": "Amount mismatch",
}
FILE_STATUS_LABELS = {
    "uploaded": "Uploaded",
    "detected": "Detected",
    "mapped": "Mapped",
    "normalized": "Normalized",
    "attention": "Needs attention",
}


def _form_page(request, user, name="", error=None, status_code=200):
    return render(
        request,
        "new_task.html",
        {"user": user, "name": name, "error": error, "max_files": MAX_FILES},
        status_code=status_code,
    )


def _human_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _format_duration(ms: int | None) -> str:
    if not ms:
        return "0.0 s"
    return f"{ms / 1000:.1f} s"


def _task_row(db: Database, user: User, task_id: str) -> dict | None:
    if user.role.value == "admin":
        where, params = "t.id = ?", (task_id,)
    else:
        where, params = "t.id = ? AND t.owner_id = ?", (task_id, user.id)
    rows = db.query(
        "SELECT t.id, t.workflow, t.status, t.task_mode, t.source_file, t.source_location,"
        " t.batch_size, t.created_at, t.updated_at FROM tasks t WHERE " + where,
        params,
    )
    return dict(rows[0]) if rows else None


def normalize_page_context(
    db: Database,
    user: User,
    task_id: str,
    error: str | None = None,
) -> dict | None:
    task = _task_row(db, user, task_id)
    if task is None:
        return None
    batch = get_batch(db, task_id)
    if batch is None:
        return None
    snapshot = normalization_snapshot(db, task_id) or {}
    issues = [
        dict(row)
        for row in db.query(
            "SELECT id, issue_type, field, order_id, source_file, source_row, original_value,"
            " suggested_value, confidence, reason, status FROM normalization_issues"
            " WHERE batch_id = ? AND status IN ('unresolved', 'skipped')"
            " ORDER BY CASE issue_type WHEN 'missing_value' THEN 1"
            " WHEN 'unit_conflict' THEN 2 WHEN 'cross_file_conflict' THEN 3 ELSE 4 END,"
            " source_file, source_row",
            (batch["id"],),
        )
    ]
    for issue in issues:
        issue["type_label"] = ISSUE_LABELS.get(issue["issue_type"], issue["issue_type"])
    files = snapshot.get("files", [])
    for entry in files:
        entry["size_label"] = _human_bytes(entry["byte_size"])
        entry["status_label"] = FILE_STATUS_LABELS.get(entry["status"], entry["status"])
    events = []
    for row in recent_events(db, task_id, limit=500):
        event = dict(row)
        label, stage = EVENT_LABELS.get(event["kind"], (event["kind"], "other"))
        event["stage_label"] = label
        event["stage"] = stage
        events.append(event)
    # Recognition runs in one upload request, so several events share the same
    # second. Order those deterministically by stage instead of random event id.
    events.sort(
        key=lambda event: (
            event["occurred_at"],
            EVENT_ORDER.get(event["kind"], 50),
            event["id"],
        )
    )
    started = snapshot.get("started_at")
    elapsed_ms = snapshot.get("duration_ms")
    if snapshot.get("status") == "running" and started:
        try:
            start_time = datetime.fromisoformat(started)
            elapsed_ms = max(
                0,
                int(
                    (datetime.now(start_time.tzinfo) - start_time).total_seconds() * 1000
                ),
            )
        except (TypeError, ValueError):
            elapsed_ms = 0
    snapshot["elapsed_label"] = _format_duration(elapsed_ms)
    snapshot["remaining"] = max(0, int(snapshot.get("unresolved") or 0))
    return {
        "user": user,
        "task": task,
        "batch": batch,
        "state": snapshot,
        "files": files,
        "issues": issues,
        "events": events,
        "error": error,
        "can_download": snapshot.get("status") in ("needs_review", "complete"),
        "can_start": snapshot.get("status") in ("uploaded", "canceled", "failed"),
        "running": snapshot.get("status") == "running",
    }


def _visible_or_404(db: Database, user: User, task_id: str) -> None:
    if not task_visible(db, user, task_id):
        raise HTTPException(status_code=404, detail="task not found")


@router.post("/tasks/normalize")
async def upload_normalization_sources(
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        return RedirectResponse("/login?next=/tasks/new", status_code=303)
    name = ""
    too_large = False
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        return _form_page(request, user, error="Choose 1–6 .xlsx or .csv files.", status_code=400)

    async def bounded_stream():
        nonlocal too_large
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_TOTAL_BYTES + 512 * 1024:
                too_large = True
                raise MultiPartException("The combined upload must be 20 MB or smaller.")
            yield chunk

    try:
        parser = MultiPartParser(
            request.headers,
            bounded_stream(),
            max_files=MAX_FILES,
            max_fields=2,
            max_part_size=4096,
        )
        form = await parser.parse()
        try:
            value = form.get("name", "")
            name = value.strip() if isinstance(value, str) else ""
            if not 1 <= len(name) <= 120:
                raise NormalizationJobError("Enter a task name between 1 and 120 characters.")
            uploads = [
                item
                for item in form.getlist("files")
                if isinstance(item, UploadFile)
            ]
            if not uploads:
                raise NormalizationJobError("Choose between 1 and 6 source files.")
            if len(uploads) > MAX_FILES:
                raise NormalizationJobError("Choose up to 6 files per run.")
            files: list[tuple[str, bytes]] = []
            total = 0
            for upload in uploads:
                filename = Path((upload.filename or "").replace("\\", "/")).name
                suffix = Path(filename).suffix.lower()
                if (
                    not filename
                    or len(filename) > 200
                    or suffix not in (".xlsx", ".csv")
                ):
                    raise NormalizationJobError(
                        f"{filename or 'A file'} is not an .xlsx or .csv file."
                    )
                data = await upload.read(MAX_FILE_BYTES + 1)
                if not data:
                    raise NormalizationJobError(f"{filename} is empty.")
                if len(data) > MAX_FILE_BYTES:
                    too_large = True
                    raise NormalizationJobError(f"{filename} is larger than 10 MB.")
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    too_large = True
                    raise NormalizationJobError("The combined upload must be 20 MB or smaller.")
                files.append((filename, data))
            # Stable file order makes repeated uploads of the same set produce
            # the same merge precedence and the same normalized values.
            files.sort(key=lambda entry: entry[0].casefold())
            task_id = await run_in_threadpool(
                create_normalization_task,
                db,
                request.app.state.upload_dir,
                user.id,
                name,
                files,
                user.name,
            )
            await run_in_threadpool(
                recognize_normalization_task,
                db,
                task_id,
                request.app.state.upload_dir,
            )
        finally:
            await form.close()
    except (
        NormalizationJobError,
        MultiPartException,
        MultipartParseError,
    ) as exc:
        return _form_page(
            request,
            user,
            name,
            str(exc) + " Your other files were not saved; choose them again.",
            413 if too_large else 400,
        )
    except Exception:  # noqa: BLE001 - readable recovery instead of a 500 page.
        return _form_page(
            request,
            user,
            name,
            "The upload could not be saved. Check the file names and try again; "
            "no task was created.",
            400,
        )
    return RedirectResponse(f"/tasks/{task_id}?uploaded=1", status_code=303)


@router.post("/tasks/{task_id}/normalize/start")
def start_normalization_run(
    task_id: str,
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    _visible_or_404(db, user, task_id)
    batch = get_batch(db, task_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="normalization batch not found")
    try:
        start_normalization(db, task_id, actor=user.name)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, NormalizationJobError)
            else "The run could not start. Refresh the page and try again."
        )
        context = normalize_page_context(db, user, task_id, message)
        if context is None:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return render(request, "normalize_task.html", context, status_code=400)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/normalize/tick")
def tick_normalization_run(
    task_id: str,
    user: SessionUser,
    request: Request,
    db: RequestDatabase,
):
    wants_json = "application/json" in request.headers.get("accept", "")
    if user is None:
        if wants_json:
            return JSONResponse({"error": "Sign in to continue."}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    _visible_or_404(db, user, task_id)
    try:
        snapshot = tick_normalization(db, task_id, request.app.state.upload_dir)
    except NormalizationJobError as exc:
        if wants_json:
            return JSONResponse({"error": str(exc)}, status_code=400)
        context = normalize_page_context(db, user, task_id, str(exc))
        if context is None:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return render(request, "normalize_task.html", context, status_code=400)
    except Exception:  # noqa: BLE001 - never leave the demo on a blank 500 page.
        message = (
            "The normalization step could not finish. "
            "Cancel and start again; uploaded files are kept."
        )
        if wants_json:
            return JSONResponse({"error": message}, status_code=400)
        context = normalize_page_context(db, user, task_id, message)
        if context is None:
            raise HTTPException(status_code=404, detail="task not found") from None
        return render(request, "normalize_task.html", context, status_code=400)
    if wants_json:
        return JSONResponse(snapshot)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.get("/tasks/{task_id}/normalize/status")
def normalization_status(
    task_id: str,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        return JSONResponse({"error": "Sign in to continue."}, status_code=401)
    _visible_or_404(db, user, task_id)
    snapshot = normalization_snapshot(db, task_id)
    if snapshot is None:
        return JSONResponse({"error": "normalization batch not found"}, status_code=404)
    return JSONResponse(snapshot)


@router.post("/tasks/{task_id}/normalize/cancel")
def cancel_normalization_run(
    task_id: str,
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    _visible_or_404(db, user, task_id)
    try:
        cancel_normalization(db, task_id, actor=user.name)
    except NormalizationJobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.get("/tasks/{task_id}/normalize/download")
def download_normalized_workbook(
    task_id: str,
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    _visible_or_404(db, user, task_id)
    try:
        content = download_workbook(db, task_id)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, NormalizationJobError)
            else "The workbook could not be built. Refresh the page and try again."
        )
        context = normalize_page_context(db, user, task_id, message)
        if context is None:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return render(
            request,
            "normalize_task.html",
            context,
            status_code=409 if isinstance(exc, NormalizationJobError) else 400,
        )
    filename = download_filename()
    return Response(
        content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tasks/{task_id}/normalize.json")
def normalization_json(
    task_id: str,
    user: SessionUser,
    db: RequestDatabase,
):
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    _visible_or_404(db, user, task_id)
    snapshot = normalization_snapshot(db, task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="normalization batch not found")
    return JSONResponse(snapshot)


@router.post("/tasks/{task_id}/normalize/issues/{issue_id}/confirm")
async def confirm_normalization_issue(
    task_id: str,
    issue_id: str,
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    """Confirm an issue with optional field edits and revalidation."""
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    _visible_or_404(db, user, task_id)
    
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    
    decision_id = data.get("decision_id", "")
    changes = data.get("changes", {})
    
    if not decision_id:
        raise HTTPException(status_code=400, detail="decision_id is required")
    
    if not isinstance(changes, dict):
        raise HTTPException(status_code=400, detail="changes must be an object")
    
    try:
        result = confirm_issue(
            db,
            task_id=task_id,
            issue_id=issue_id,
            decision_id=decision_id,
            changes=changes,
            user_id=user.id,
            user_name=user.name,
        )
        
        return JSONResponse({
            "ok": True,
            "issue_id": result.issue_id,
            "action": result.action,
            "resolved": result.resolved,
            "message": result.message,
        })
    
    except ReviewError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "issue_id": issue_id,
            },
            status_code=400,
        )


@router.post("/tasks/{task_id}/normalize/issues/{issue_id}/skip")
async def skip_normalization_issue(
    task_id: str,
    issue_id: str,
    request: Request,
    user: SessionUser,
    db: RequestDatabase,
):
    """Skip an issue with a required reason."""
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    _visible_or_404(db, user, task_id)
    
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    
    decision_id = data.get("decision_id", "")
    reason = data.get("reason", "")
    
    if not decision_id:
        raise HTTPException(status_code=400, detail="decision_id is required")
    
    if not reason or len(reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="reason is required (at least 3 characters)")
    
    try:
        result = skip_issue(
            db,
            task_id=task_id,
            issue_id=issue_id,
            decision_id=decision_id,
            reason=reason,
            user_id=user.id,
            user_name=user.name,
        )
        
        return JSONResponse({
            "ok": True,
            "issue_id": result.issue_id,
            "action": result.action,
            "resolved": result.resolved,
            "message": result.message,
        })
    
    except ReviewError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "issue_id": issue_id,
            },
            status_code=400,
        )
