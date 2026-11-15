"""User-facing source correction, review recovery and output preview."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Annotated
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from openpyxl import load_workbook

from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import task_visible
from flowremote.contracts.models import User
from flowremote.contracts.normalization import MAPPED_FIELDS
from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import Database, new_id, utc_now
from flowremote.control_plane.normalization import NormalizationError, build_mapping, detect_table
from flowremote.control_plane.normalization_jobs import (
    create_normalization_task,
    get_batch,
    recognize_normalization_task,
)
from flowremote.control_plane.normalization_review import ReviewError, reopen_issue
from flowremote.control_plane.normalization_worker import JOB_LOCK
from flowremote.control_plane.source_options import options_for, prepare_source

router = APIRouter()
SessionUser = Annotated[User | None, Depends(current_user)]
RequestDatabase = Annotated[Database, Depends(get_db)]


@router.post("/tasks/example")
def create_example(request: Request, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", 303)
    from flowremote.devtools.demoday_data import demo_sources
    task_id = create_normalization_task(db, request.app.state.upload_dir, user.id,
                                        "Example: monthly order cleanup", list(demo_sources()), user.name)
    recognize_normalization_task(db, task_id, request.app.state.upload_dir)
    return RedirectResponse(f"/tasks/{task_id}", 303)


@router.get("/examples.zip")
def download_examples(user: SessionUser):
    if user is None:
        return RedirectResponse("/login", 303)
    from flowremote.devtools.demoday_data import demo_sources
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, data in demo_sources():
            archive.writestr(name, data)
    return Response(output.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="FlowRemote_examples.zip"'})


def visible(db, user, task_id):
    if not task_visible(db, user, task_id):
        raise HTTPException(404, "task not found")


def source(db, task_id, file_id):
    rows = db.query("SELECT * FROM normalization_files WHERE task_id = ? AND id = ?",
                    (task_id, file_id))
    if not rows:
        raise HTTPException(404, "source file not found")
    return rows[0]


def source_bytes(request, file):
    root = Path(request.app.state.upload_dir).resolve()
    path = (root / file["storage_name"]).resolve()
    if path.parent != root:
        raise HTTPException(404, "source not found")
    return path.read_bytes()


@router.get("/tasks/{task_id}/files/{file_id}/configure")
def configure_source(task_id: str, file_id: str, request: Request,
                     user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", 303)
    visible(db, user, task_id)
    file = source(db, task_id, file_id)
    options = options_for(file)
    templates = db.query("SELECT id, name FROM normalization_templates WHERE owner_id = ?"
                         " ORDER BY name", (user.id,))
    template_id = request.query_params.get("template")
    if template_id:
        selected = db.query("SELECT options_json FROM normalization_templates"
                            " WHERE id = ? AND owner_id = ?", (template_id, user.id))
        if not selected:
            raise HTTPException(404, "template not found")
        options = json.loads(selected[0]["options_json"])
    options = dict(options)
    for name in ("worksheet", "header_row"):
        if name in request.query_params:
            options[name] = request.query_params[name]
    sheets = ["CSV"]
    table, mapping, error = None, None, None
    try:
        data = source_bytes(request, file)
        if file["filename"].lower().endswith(".xlsx"):
            # Sheet names must still be available when automatic recognition
            # fails, so users can correct unfamiliar headers themselves.
            with ZipFile(BytesIO(data)) as archive:
                if len(archive.infolist()) > 1000 or sum(
                    entry.file_size for entry in archive.infolist()
                ) > 50 * 1024 * 1024:
                    raise NormalizationError("The expanded workbook is too large to inspect.")
            book = load_workbook(BytesIO(data), read_only=True, keep_links=False)
            sheets = book.sheetnames
            book.close()
        table = detect_table(file["filename"], data,
                             worksheet=options.get("worksheet") or None,
                             header_row=options.get("header_row") or None)
        try:
            mapping = build_mapping(table)
        except NormalizationError as exc:
            error = str(exc)
    except (NormalizationError, OSError, BadZipFile, ValueError) as exc:
        error = str(exc)
    columns = options.get("columns", {}) if template_id else {}
    if not columns:
        columns = options.get("columns") or (
            {column.field: str(column.index) if column.index >= 0 else ""
             for column in mapping.columns} if mapping else {})
    batch = get_batch(db, task_id)
    return render(request, "source_config.html", {
        "user": user, "task": {"id": task_id}, "file": file, "options": options,
        "table": table, "sheets": sheets, "columns": columns, "fields": MAPPED_FIELDS,
        "templates": templates, "error": error or request.query_params.get("error"),
        "editable": batch["status"] in ("uploaded", "canceled", "failed"),
    })


@router.post("/tasks/{task_id}/files/{file_id}/configure")
async def save_source(task_id: str, file_id: str, request: Request,
                      user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", 303)
    visible(db, user, task_id)
    form = await read_form(request)
    file = source(db, task_id, file_id)
    options = {name: str(form.get(name) or "") for name in
               ("worksheet", "header_row", "date_order", "price_multiplier", "box_to_piece")}
    options["columns"] = {field: str(form.get("column_" + field) or "") for field in MAPPED_FIELDS}
    template_name = str(form.get("template_name") or "").strip()
    try:
        if len(template_name) > 80:
            raise NormalizationError("Template name must be 80 characters or shorter.")
        with JOB_LOCK:
            table, mapping, _ = prepare_source(file, source_bytes(request, file), options)
            now = utc_now()
            with JOB_LOCK, db.transaction():
                batch = get_batch(db, task_id)
                if batch["status"] not in ("uploaded", "canceled", "failed"):
                    raise NormalizationError("Source settings are locked after processing starts.")
                db.execute(
                    "UPDATE normalization_files SET options_json = ?, worksheet = ?, header_row = ?,"
                    " row_count = ?, field_count = ?, mapping_json = ?, status = 'mapped',"
                    " error = NULL, updated_at = ? WHERE id = ?",
                    (json.dumps(options), table.worksheet, table.header_row, table.row_count,
                     mapping.field_count, json.dumps(mapping.as_dict()), now, file_id),
                )
                db.execute("DELETE FROM normalization_issues WHERE file_id = ? AND issue_type = 'file_error'",
                            (file_id,))
                if template_name:
                    previous = db.query("SELECT id FROM normalization_templates WHERE owner_id = ?"
                                         " AND name = ?", (user.id, template_name))
                    if previous:
                        db.execute("UPDATE normalization_templates SET options_json = ?, updated_at = ?"
                                   " WHERE id = ?", (json.dumps(options), now, previous[0]["id"]))
                    else:
                        db.execute("INSERT INTO normalization_templates VALUES (?, ?, ?, ?, ?)",
                                   (new_id("TPL"), user.id, template_name, json.dumps(options), now))
                log_event(db, task_id=task_id, kind="normalize_source_config", actor=user.name,
                          occurred_at=now, description=f"Updated source mapping and rules: {file['filename']}",
                          payload={"file_id": file_id, "options": options})
            # Recognition metadata/counts are rebuilt before Start; other configured files
            # keep options_json, so their corrections survive cancellation and retry.
            with JOB_LOCK:
                db.execute("UPDATE normalization_files SET status = 'uploaded' WHERE task_id = ?", (task_id,))
                recognize_normalization_task(db, task_id, request.app.state.upload_dir)
    except (NormalizationError, ValueError) as exc:
        from urllib.parse import urlencode
        return RedirectResponse(f"/tasks/{task_id}/files/{file_id}/configure?"
                                + urlencode({"error": str(exc)}), 303)
    return RedirectResponse(f"/tasks/{task_id}?configured=1", 303)


@router.post("/tasks/{task_id}/normalize/issues/{issue_id}/reopen")
def reopen_review(task_id: str, issue_id: str, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", 303)
    visible(db, user, task_id)
    try:
        reopen_issue(db, task_id=task_id, issue_id=issue_id, user=user)
    except ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/tasks/{task_id}#issue-{issue_id}", 303)


@router.get("/tasks/{task_id}/normalize/preview")
def preview_result(task_id: str, request: Request, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", 303)
    visible(db, user, task_id)
    batch = get_batch(db, task_id)
    if not batch or batch["status"] not in ("needs_review", "complete"):
        raise HTTPException(409, "Results are available after processing finishes.")
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        raise HTTPException(400, "Invalid page number") from None
    view = request.query_params.get("view", "records")
    queries = {
        "records": ("normalized_records", "is_primary = 1", ["order_id", "customer_name", "customer_id", "quantity", "unit", "unit_price", "amount", "order_date", "source_file", "source_row"]),
        "changes": ("normalization_changes", "1=1", ["order_id", "field", "original_value", "new_value", "reason", "method", "source_file", "source_row"]),
        "excluded": ("normalization_issues", "status = 'skipped'", ["order_id", "source_file", "source_row", "issue_type", "skip_reason"]),
    }
    if view not in queries:
        raise HTTPException(400, "Unknown preview view")
    table, predicate, headers = queries[view]
    total = db.scalar(f"SELECT COUNT(*) FROM {table} WHERE batch_id = ? AND {predicate}", (batch["id"],), 0)
    pages = max(1, (total + 24) // 25)
    page = min(page, pages)
    rows = db.query(f"SELECT {', '.join(headers)} FROM {table} WHERE batch_id = ?"
                    f" AND {predicate} ORDER BY id LIMIT 25 OFFSET ?", (batch["id"], (page - 1) * 25))
    all_orders = db.scalar("SELECT COUNT(DISTINCT order_id) FROM normalized_records WHERE batch_id = ?", (batch["id"],), 0)
    output = db.scalar("SELECT COUNT(*) FROM normalized_records WHERE batch_id = ? AND is_primary = 1", (batch["id"],), 0)
    return render(request, "result_preview.html", {
        "user": user, "task": {"id": task_id}, "batch": batch, "rows": rows,
        "headers": headers, "page": page, "pages": pages, "total": total, "view": view,
        "output_count": output, "excluded_orders": all_orders - output,
        "merged_duplicates": max(0, batch["raw_records"] - all_orders),
    })
