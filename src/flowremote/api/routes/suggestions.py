"""Request and persist a validated AI suggestion for one exception."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from flowremote.agent.config import provider_for_user
from flowremote.agent.service import SuggestionError, run_suggestion
from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.api.routes.tasks import load_task_page
from flowremote.contracts.models import User
from flowremote.control_plane.db import Database

router = APIRouter()


@router.post("/tasks/{task_id}/exceptions/{record_id}/suggestions")
async def generate_suggestion(
    task_id: str,
    record_id: str,
    request: Request,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
    db: Database = Depends(get_db),  # noqa: B008 - FastAPI dependency idiom.
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    context = load_task_page(db, user, task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="task not found")
    form = await read_form(request)
    if request.app.state.suggestion_provider_override is not None:
        # Tests and embedding callers can inject a provider explicitly.
        provider = request.app.state.suggestion_provider
    else:
        provider = provider_for_user(
            db,
            request.app.state.ai_settings_cipher,
            user_id=user.id,
            fallback=request.app.state.suggestion_provider,
        )
    try:
        await run_in_threadpool(
            run_suggestion,
            db,
            task_id=task_id,
            record_id=record_id,
            request_id=(form.get("request_id") or "").strip(),
            provider=provider,
            registry_path=request.app.state.customer_registry,
        )
    except SuggestionError as exc:
        context = load_task_page(db, user, task_id) or context
        context["error"] = str(exc)
        return render(request, "task.html", context, status_code=400)
    return RedirectResponse(f"/tasks/{task_id}#exc-{record_id}", status_code=303)
