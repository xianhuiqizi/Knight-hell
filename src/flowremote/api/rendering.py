"""One helper for rendering a Jinja template with the request in context."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from flowremote.ui.i18n import (
    client_dictionary_json,
    client_patterns_json,
    get_lang,
    translate_html,
)


def render(
    request: Request, template: str, context: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    lang = get_lang(request)
    payload: dict = {
        "request": request,
        "lang": lang,
        "is_zh": lang == "zh",
        "i18n_dictionary": client_dictionary_json(),
        "i18n_patterns": client_patterns_json(),
    }
    if context:
        payload.update(context)
    response = request.app.state.templates.TemplateResponse(
        request, template, payload, status_code=status_code
    )
    response.headers["Content-Language"] = "zh-CN" if lang == "zh" else "en"
    if lang == "zh":
        body = response.body.decode("utf-8")
        return HTMLResponse(
            translate_html(body, lang),
            status_code=status_code,
            headers={"Content-Language": "zh-CN"},
        )
    return response
