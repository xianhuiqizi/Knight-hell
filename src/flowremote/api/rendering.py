"""One helper for rendering a Jinja template with the request in context."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse


def render(
    request: Request, template: str, context: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    payload: dict = {"request": request}
    if context:
        payload.update(context)
    return request.app.state.templates.TemplateResponse(
        request, template, payload, status_code=status_code
    )
