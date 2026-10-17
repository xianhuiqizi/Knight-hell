"""User accounts: password hashing, creation, and sign-in checks.

Standard library only. Passwords are stored as PBKDF2-HMAC-SHA256 with a
per-user random salt, in the format
``pbkdf2_sha256$<iterations>$<salt-b64>$<hash-b64>``. Verification uses a
constant-time comparison, so a wrong password does not leak how much of the
hash matched.

Why not argon2/bcrypt: those need a compiled package. PBKDF2 is in hashlib and
is accepted practice; the iteration count here is 200,000.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from typing import Any

from flowremote.contracts.enums import Role
from flowremote.contracts.models import User
from flowremote.contracts.timeutil import utc_now
from flowremote.control_plane.db import Database

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 8


class AccountError(ValueError):
    """A sign-up or sign-in request cannot be accepted."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def get_user_row(db: Database, user_id: str) -> dict[str, Any] | None:
    rows = db.query("SELECT * FROM users WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def get_user_row_by_email(db: Database, email: str) -> dict[str, Any] | None:
    rows = db.query("SELECT * FROM users WHERE lower(email) = lower(?)", (email.strip(),))
    return rows[0] if rows else None


def to_user(row: dict[str, Any]) -> User:
    return User.from_row(row)


def create_user(
    db: Database,
    *,
    name: str,
    email: str,
    password: str,
    role: Role | str = Role.OPERATOR,
    device: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create an account and return its row. Raises AccountError on bad input."""
    clean_name = (name or "").strip()
    clean_email = (email or "").strip().lower()
    if not clean_name:
        raise AccountError("name is required")
    if "@" not in clean_email or not clean_email.split("@")[0]:
        raise AccountError("a valid email address is required")
    if get_user_row_by_email(db, clean_email):
        raise AccountError("an account with that email already exists")

    identifier = user_id or f"USR-{uuid.uuid4().hex[:8].upper()}"
    db.execute(
        "INSERT INTO users (id, name, email, role, device, password_hash, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            clean_name,
            clean_email,
            role.value if isinstance(role, Role) else str(role),
            device,
            hash_password(password),
            utc_now(),
        ),
    )
    row = get_user_row(db, identifier)
    if row is None:  # pragma: no cover - the insert above would have raised
        raise AccountError("the account could not be created")
    return row


def authenticate(db: Database, email: str, password: str) -> dict[str, Any] | None:
    """Return the user row when the credentials match, otherwise None."""
    row = get_user_row_by_email(db, email)
    if row is None:
        return None
    if not verify_password(password, row.get("password_hash")):
        return None
    return row
