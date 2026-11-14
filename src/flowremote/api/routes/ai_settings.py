"""Read and save the signed-in user's AI connection settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.contracts.models import User
from flowremote.control_plane.ai_settings import (
    AISettingsError,
    public_settings,
    check_connection,
    save_settings,
)
from flowremote.control_plane.db import Database

router = APIRouter()


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.get("/settings/ai", response_class=HTMLResponse)
def ai_settings_page(
    request: Request,
    saved: int = 0,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
    db: Database = Depends(get_db),  # noqa: B008 - FastAPI dependency idiom.
):
    if user is None:
        if _wants_json(request):
            raise HTTPException(status_code=401, detail="sign in required")
        return RedirectResponse("/login?next=/settings/ai", status_code=303)
    settings = public_settings(db, user.id)
    if _wants_json(request):
        return JSONResponse(settings.as_dict())
    return render(
        request,
        "ai_settings.html",
        {"user": user, "settings": settings, "saved": bool(saved), "error": None},
    )


@router.post("/settings/ai", response_class=HTMLResponse)
async def save_ai_settings(
    request: Request,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
    db: Database = Depends(get_db),  # noqa: B008 - FastAPI dependency idiom.
):
    if user is None:
        if _wants_json(request):
            raise HTTPException(status_code=401, detail="sign in required")
        return RedirectResponse("/login?next=/settings/ai", status_code=303)
    form = await read_form(request)
    try:
        settings = save_settings(
            db,
            request.app.state.ai_settings_cipher,
            user_id=user.id,
            provider=form.get("provider", ""),
            model=form.get("model", ""),
            base_url=form.get("base_url", ""),
            api_key=form.get("api_key", ""),
            clear_key=form.get("clear_key") in {"1", "true", "on", "yes"},
        )
    except AISettingsError as exc:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return render(
            request,
            "ai_settings.html",
            {
                "user": user,
                "settings": public_settings(db, user.id),
                "saved": False,
                "error": str(exc),
            },
            status_code=400,
        )
    if _wants_json(request):
        return JSONResponse({"ok": True, "settings": settings.as_dict()})
    return RedirectResponse("/settings/ai?saved=1", status_code=303)


@router.post("/settings/ai/test", response_class=JSONResponse)
async def test_ai_connection(
    request: Request,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
):
    """Test AI provider connection with 3s timeout.
    
    Accepts both JSON and form-encoded requests. Returns connection status,
    model name, latency and actionable error messages. Never stores credentials
    unless explicitly saved via /settings/ai.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    
    # Read request body - support both JSON and form
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    
    if content_type == "application/json":
        try:
            data = await request.json()
        except Exception:
            return JSONResponse(
                {
                    "ok": False,
                    "provider": "unknown",
                    "model": None,
                    "latency_ms": 0,
                    "message": "Invalid JSON request.",
                },
                status_code=400,
            )
    else:
        # Form-encoded
        data = await read_form(request)
    
    provider = data.get("provider", "").strip().lower()
    base_url = data.get("base_url", "").strip()
    model = data.get("model", "").strip()
    api_key = data.get("api_key", "").strip()
    
    # Test the connection (never raises, always returns result)
    result = check_connection(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    
    return JSONResponse(result.as_dict())
