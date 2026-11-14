"""Language selection: English by default, Chinese is opt-in per browser."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from flowremote.ui.i18n import COOKIE_MAX_AGE, COOKIE_NAME, SUPPORTED

router = APIRouter()


def _next_path(value: str | None) -> str:
    target = unquote(value or "/")
    if (
        not target.startswith("/")
        or target.startswith("//")
        or "\\" in target
        or any(char in target for char in ("\r", "\n", "\x00"))
    ):
        return "/"
    return target


def _set_language(lang: str, next_path: str) -> RedirectResponse:
    if lang not in SUPPORTED:
        raise HTTPException(status_code=404, detail="unsupported language")
    response = RedirectResponse(_next_path(next_path), status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        lang,
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/language/{lang}")
def choose_language(lang: str, request: Request):
    return _set_language(lang, request.query_params.get("next", "/"))


@router.post("/language/{lang}")
async def choose_language_form(lang: str, request: Request):
    form = await request.form()
    return _set_language(lang, str(form.get("next", "/")))
