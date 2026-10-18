"""New task form, bounded workbook upload, and owner-scoped downloads."""

from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from openpyxl import Workbook
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from flowremote.api.deps import current_user, get_db
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page, task_visible
from flowremote.contracts.models import User
from flowremote.control_plane.db import Database
from flowremote.control_plane.order_validation import FIELDS, ValidationError
from flowremote.control_plane.uploads import (
    MAX_FILE_BYTES,
    UploadError,
    create_uploaded_task,
    validate_saved_upload,
)

router = APIRouter()
SessionUser = Annotated[User | None, Depends(current_user)]
RequestDatabase = Annotated[Database, Depends(get_db)]


def form_page(request, user, name="", error=None, status_code=200):
    return render(
        request,
        "new_task.html",
        {"user": user, "name": name, "error": error},
        status_code=status_code,
    )


@router.get("/tasks/new")
def new_task(request: Request, user: SessionUser):
    if user is None:
        return RedirectResponse("/login?next=/tasks/new", status_code=303)
    return form_page(request, user)


@router.post("/tasks")
async def upload_task(request: Request, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login?next=/tasks/new", status_code=303)
    name = ""
    too_large = False

    async def bounded_stream():
        nonlocal too_large
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_FILE_BYTES + 64 * 1024:
                too_large = True
                raise MultiPartException("The upload must be 10 MB or smaller.")
            yield chunk

    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        return form_page(request, user, error="Choose an Excel file to upload.", status_code=400)
    try:
        parser = MultiPartParser(
            request.headers, bounded_stream(), max_files=1, max_fields=3, max_part_size=4096
        )
        form = await parser.parse()
        try:
            value = form.get("name", "")
            name = value.strip() if isinstance(value, str) else ""
            if not 1 <= len(name) <= 120:
                raise UploadError("Enter a task name between 1 and 120 characters.")
            upload = form.get("file")
            if not isinstance(upload, UploadFile) or not upload.filename:
                raise UploadError("Choose an Excel .xlsx file.")
            filename = Path(upload.filename.replace("\\", "/")).name
            if len(filename) > 200 or Path(filename).suffix.lower() != ".xlsx":
                raise UploadError("Choose an .xlsx file with a filename of at most 200 characters.")
            data = await upload.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                too_large = True
                raise UploadError("The upload must be 10 MB or smaller.")
            # Owner comes only from the signed session, never from a form field.
            task_id = await run_in_threadpool(
                create_uploaded_task,
                db,
                request.app.state.upload_dir,
                user.id,
                name,
                filename,
                data,
            )
        finally:
            await form.close()
    except (UploadError, ValidationError, MultiPartException, MultipartParseError) as exc:
        return form_page(request, user, name, str(exc), 413 if too_large else 400)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.get("/orders-template.xlsx")
def order_template(user: SessionUser):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(FIELDS)
    sheet.append(["EXAMPLE-001", "Example customer", "C-001", 2, 10.5, 21, "2026-10-18"])
    for cells in sheet.columns:
        sheet.column_dimensions[cells[0].column_letter].width = 22
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    return Response(
        content.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="orders-template.xlsx"'},
    )


@router.post("/tasks/{task_id}/validate")
def validate_existing(task_id: str, request: Request, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(404, "task not found")
    if context["task"]["status"] == "ready":
        try:
            validate_saved_upload(db, request.app.state.upload_dir, task_id)
        except (UploadError, ValidationError) as exc:
            context["error"] = str(exc)
            return render(request, "task.html", context, status_code=400)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.get("/tasks/{task_id}/source")
def download_source(task_id: str, request: Request, user: SessionUser, db: RequestDatabase):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not task_visible(db, user, task_id):
        raise HTTPException(404, "task not found")
    rows = db.query(
        "SELECT u.storage_name, t.source_file FROM task_uploads u"
        " JOIN tasks t ON t.id = u.task_id WHERE u.task_id = ?",
        (task_id,),
    )
    if not rows:
        raise HTTPException(404, "source file not found")
    path = request.app.state.upload_dir / rows[0]["storage_name"]
    if not path.is_file():
        raise HTTPException(404, "source file not found")
    return FileResponse(
        path,
        filename=rows[0]["source_file"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
