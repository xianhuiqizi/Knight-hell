"""Signed session cookies, standard library only.

The cookie carries ``{"uid": ..., "exp": ...}`` as base64url JSON plus an
HMAC-SHA256 signature over that payload. Nothing is stored on the server, so
there is no session table and no cleanup job.

Trade-off, stated plainly: a session cannot be revoked server-side before it
expires; logging out clears the cookie in the browser. For this stage that is
accepted, and the report notes it as a known limitation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

COOKIE_NAME = "flowremote_session"
DEFAULT_MAX_AGE_SECONDS = 8 * 60 * 60


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class SessionSigner:
    def __init__(self, secret: str, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> None:
        if not secret:
            raise ValueError("a session secret is required")
        self._key = secret.encode("utf-8")
        self.max_age_seconds = max_age_seconds

    def _signature(self, payload: str) -> str:
        digest = hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()
        return _b64(digest)

    def sign(self, user_id: str, *, now: datetime | None = None) -> str:
        moment = now or datetime.now(timezone.utc)
        body = {
            "uid": user_id,
            "exp": int((moment + timedelta(seconds=self.max_age_seconds)).timestamp()),
        }
        payload = _b64(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        return f"{payload}.{self._signature(payload)}"

    def verify(self, token: str | None, *, now: datetime | None = None) -> str | None:
        """Return the user id for a valid token, otherwise None."""
        if not token or "." not in token:
            return None
        payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._signature(payload)):
            return None
        try:
            body = json.loads(_unb64(payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        moment = now or datetime.now(timezone.utc)
        if int(body.get("exp", 0)) <= int(moment.timestamp()):
            return None
        user_id = body.get("uid")
        return user_id if isinstance(user_id, str) and user_id else None


def load_or_create_secret(path: Path) -> str:
    """Read a persistent development secret, creating it on first use.

    Keeping it in data/runtime means restarts do not log everyone out, and the
    file is already git-ignored.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    secret = secrets.token_urlsafe(48)
    path.write_text(secret, encoding="utf-8")
    return secret
