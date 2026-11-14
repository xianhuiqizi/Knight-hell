"""Read and save the signed-in user's AI connection settings."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from flowremote.agent.connection import (
    DEFAULT_BASE_URL,
    OFFLINE_MODEL,
    ConnectionResult,
    probe_connection,
)
from flowremote.api.deps import current_user, get_db
from flowremote.api.forms import read_form
from flowremote.api.rendering import render
from flowremote.contracts.models import User
from flowremote.control_plane.ai_settings import (
    AISettingsError,
    activate_offline,
    clean_base_url,
    connection_api_key,
    demo_mode_active,
    public_settings,
    save_settings,
)
from flowremote.control_plane.db import Database

router = APIRouter()


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


async def _connection_payload(request: Request) -> dict[str, str]:
    """Read a form or JSON connection payload without accepting a key anywhere else."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type == "application/json":
        try:
            payload: Any = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON request.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object.")
        return {
            str(key): "" if value is None else str(value)
            for key, value in payload.items()
        }
    form = await read_form(request)
    return {str(key): str(value) for key, value in form.items()}


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


def _connection_payload_for_json(
    *,
    provider: str,
    model: str | None,
    latency_ms: int,
    ok: bool,
    connected: bool,
    fallback: bool,
    message: str,
    action: str,
    settings: dict,
    error_code: str | None = None,
    attempted_model: str | None = None,
    key_source: str = "none",
) -> dict:
    return {
        "ok": ok,
        "connected": connected,
        "fallback": fallback,
        "provider": provider,
        "model": model,
        "latency_ms": latency_ms,
        "error_code": error_code,
        "message": message,
        "action": action,
        "attempted_model": attempted_model,
        "key_source": key_source,
        "demo_mode": demo_mode_active(),
        "settings": settings,
    }


@router.post("/settings/ai/test", response_class=JSONResponse)
async def test_ai_connection(
    request: Request,
    user: User | None = Depends(current_user),  # noqa: B008 - FastAPI dependency idiom.
    db: Database = Depends(get_db),  # noqa: B008 - FastAPI dependency idiom.
):
    """Test and, on success, save the selected AI connection.

    A failed or unkeyed online test auto-switches the user to Offline Demo AI so
    the Demo Day cleanup can always continue. The submitted key is never echoed,
    logged, or written unless the probe succeeds.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    payload = await _connection_payload(request)
    provider = payload.get("provider", "").strip().lower()
    model = payload.get("model", "").strip()
    base_url = payload.get("base_url", "").strip()
    submitted_key = payload.get("api_key", "").strip()
    cipher = request.app.state.ai_settings_cipher

    if provider not in {"offline", "openai"}:
        return JSONResponse(
            _connection_payload_for_json(
                provider="offline",
                model=OFFLINE_MODEL,
                latency_ms=0,
                ok=False,
                connected=False,
                fallback=False,
                error_code="config",
                message="Choose OpenAI-compatible or Offline Demo AI.",
                action="Select a provider and try again.",
                settings=public_settings(db, user.id).as_dict(),
            ),
            status_code=400,
        )

    if provider == "offline":
        settings = save_settings(
            db,
            cipher,
            user_id=user.id,
            provider="offline",
            model="",
            base_url="",
            api_key="",
            clear_key=False,
        )
        return JSONResponse(
            _connection_payload_for_json(
                provider="offline",
                model=OFFLINE_MODEL,
                latency_ms=0,
                ok=True,
                connected=True,
                fallback=False,
                message="Offline Demo AI is active. Rules only; no network is used.",
                action="",
                settings=settings.as_dict(),
            )
        )

    try:
        api_key, key_source = connection_api_key(
            db,
            cipher,
            user_id=user.id,
            submitted_key=submitted_key,
        )
    except AISettingsError as exc:
        settings = activate_offline(db, cipher, user_id=user.id)
        return JSONResponse(
            _connection_payload_for_json(
                provider="offline",
                model=OFFLINE_MODEL,
                latency_ms=0,
                ok=False,
                connected=False,
                fallback=True,
                error_code="config",
                message=str(exc),
                action="Paste a new key or use Offline Demo AI.",
                settings=settings.as_dict(),
            )
        )

    if not api_key:
        settings = activate_offline(db, cipher, user_id=user.id)
        return JSONResponse(
            _connection_payload_for_json(
                provider="offline",
                model=OFFLINE_MODEL,
                latency_ms=0,
                ok=True,
                connected=True,
                fallback=True,
                error_code="no_key",
                message=(
                    "No API key was supplied. Offline Demo AI is active; "
                    "the cleanup can continue without a network."
                ),
                action="Paste a key later if you want to test the online provider.",
                settings=settings.as_dict(),
                attempted_model=model or None,
            )
        )

    try:
        cleaned_base_url = clean_base_url(base_url)
    except AISettingsError as exc:
        settings = activate_offline(db, cipher, user_id=user.id)
        return JSONResponse(
            _connection_payload_for_json(
                provider="offline",
                model=OFFLINE_MODEL,
                latency_ms=0,
                ok=False,
                connected=False,
                fallback=True,
                error_code="config",
                message=str(exc),
                action="Fix the base URL, or continue with Offline Demo AI.",
                settings=settings.as_dict(),
                attempted_model=model or None,
                key_source=key_source,
            )
        )

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(
                probe_connection,
                "openai",
                cleaned_base_url or DEFAULT_BASE_URL,
                model,
                api_key,
                timeout_seconds=5.0,
            ),
            timeout=5.2,
        )
    except TimeoutError:
        # Hard ceiling for the browser promise: a slow transport must not hold
        # the dialog past five seconds. The probe itself only reads.
        result = ConnectionResult(
            ok=False,
            provider="openai",
            model=None,
            latency_ms=5200,
            error_code="network",
            message="The AI provider did not answer within the 5-second window.",
            action="Check the network or base URL, or switch to Offline Demo AI.",
        )
    if result.ok:
        try:
            settings = save_settings(
                db,
                cipher,
                user_id=user.id,
                provider="openai",
                model=model,
                base_url=cleaned_base_url,
                api_key=submitted_key,
                clear_key=False,
            )
        except AISettingsError as exc:
            settings = activate_offline(db, cipher, user_id=user.id)
            return JSONResponse(
                _connection_payload_for_json(
                    provider="offline",
                    model=OFFLINE_MODEL,
                    latency_ms=result.latency_ms,
                    ok=False,
                    connected=False,
                    fallback=True,
                    error_code="config",
                    message=str(exc),
                    action="Fix the connection fields, or continue with Offline Demo AI.",
                    settings=settings.as_dict(),
                    attempted_model=model,
                    key_source=key_source,
                )
            )
        return JSONResponse(
            _connection_payload_for_json(
                provider="openai",
                model=result.model or model,
                latency_ms=result.latency_ms,
                ok=True,
                connected=True,
                fallback=False,
                message=result.message,
                action=result.action,
                settings=settings.as_dict(),
                key_source=key_source,
            )
        )

    settings = activate_offline(db, cipher, user_id=user.id)
    message = result.message
    if "Offline Demo AI" not in message:
        message += " Offline Demo AI is active; the cleanup can continue."
    return JSONResponse(
        _connection_payload_for_json(
            provider="offline",
            model=OFFLINE_MODEL,
            latency_ms=result.latency_ms,
            ok=False,
            connected=False,
            fallback=True,
            error_code=result.error_code,
            message=message,
            action=result.action,
            settings=settings.as_dict(),
            attempted_model=model,
            key_source=key_source,
        )
    )
