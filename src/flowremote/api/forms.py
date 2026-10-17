"""Read URL-encoded HTML forms without python-multipart.

FastAPI's ``Form(...)`` needs the python-multipart package. Our forms are plain
``application/x-www-form-urlencoded`` bodies, so the standard library parser is
enough. Multipart uploads are not supported here and are rejected with 415.
"""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import HTTPException, Request


async def read_form(request: Request) -> dict[str, str]:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in ("", "application/x-www-form-urlencoded"):
        raise HTTPException(status_code=415, detail="expected a urlencoded form")
    raw = (await request.body()).decode("utf-8")
    if not raw:
        return {}
    parsed = parse_qs(raw, keep_blank_values=True, strict_parsing=False)
    return {key: values[0] for key, values in parsed.items()}
