"""Per-user AI connection settings and encrypted API-key storage."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from flowremote.control_plane.db import Database, utc_now

PROVIDERS = {"offline", "openai"}
DEFAULT_MODEL = "gpt-6-astra"


class AISettingsError(ValueError):
    """A submitted AI connection setting is invalid."""


@dataclass(frozen=True)
class PublicAISettings:
    provider: str
    model: str
    base_url: str
    key_configured: bool
    key_hint: str
    key_source: str

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "key_configured": self.key_configured,
            "key_hint": self.key_hint,
            "key_source": self.key_source,
        }


class AISettingCipher:
    """Encrypt API keys with a key derived from the application session secret."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("an application secret is required")
        raw = hashlib.sha256(("flowremote-ai-settings:" + secret).encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise AISettingsError(
                "The saved API key cannot be decrypted with the current application secret."
            ) from exc


def _clean_base_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AISettingsError("The API base URL cannot contain credentials, a query or a fragment.")
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    raise AISettingsError(
        "Use an HTTPS API base URL, or HTTP only for localhost during development."
    )


def _row(db: Database, user_id: str) -> dict | None:
    rows = db.query("SELECT * FROM ai_settings WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None


def public_settings(db: Database, user_id: str) -> PublicAISettings:
    row = _row(db, user_id)
    if not row:
        env_key = bool(os.environ.get("OPENAI_API_KEY"))
        return PublicAISettings(
            provider="offline",
            model=DEFAULT_MODEL,
            base_url="",
            key_configured=env_key,
            key_hint="",
            key_source="environment" if env_key else "none",
        )
    hint = row.get("api_key_hint") or ""
    env_key = bool(os.environ.get("OPENAI_API_KEY"))
    saved_key = bool(row.get("api_key_encrypted"))
    return PublicAISettings(
        provider=row["provider"],
        model=row.get("model") or DEFAULT_MODEL,
        base_url=row.get("base_url") or "",
        key_configured=saved_key or env_key,
        key_hint=f"••••{hint}" if hint else "",
        key_source="saved" if saved_key else ("environment" if env_key else "none"),
    )


def save_settings(
    db: Database,
    cipher: AISettingCipher,
    *,
    user_id: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    clear_key: bool,
) -> PublicAISettings:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise AISettingsError("Choose either the offline provider or the OpenAI Responses API.")
    model = model.strip() or (DEFAULT_MODEL if provider == "openai" else "")
    if provider == "openai" and not model:
        raise AISettingsError("Enter the model name exposed by your API.")
    if len(model) > 160:
        raise AISettingsError("The model name is too long.")
    base_url = _clean_base_url(base_url)
    api_key = api_key.strip()
    if api_key and clear_key:
        raise AISettingsError("Enter a new API key or clear the saved key, not both.")
    if len(api_key) > 4096:
        raise AISettingsError("The API key is too long.")

    existing = _row(db, user_id)
    encrypted = existing.get("api_key_encrypted") if existing else None
    hint = existing.get("api_key_hint") if existing else None
    if clear_key:
        encrypted = None
        hint = None
    elif api_key:
        encrypted = cipher.encrypt(api_key)
        hint = api_key[-4:]

    now = utc_now()
    with db.transaction():
        if existing:
            db.execute(
                "UPDATE ai_settings SET provider = ?, model = ?, base_url = ?,"
                " api_key_encrypted = ?, api_key_hint = ?, updated_at = ?"
                " WHERE user_id = ?",
                (provider, model or None, base_url or None, encrypted, hint, now, user_id),
            )
        else:
            db.execute(
                "INSERT INTO ai_settings (user_id, provider, model, base_url,"
                " api_key_encrypted, api_key_hint, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, provider, model or None, base_url or None, encrypted, hint, now),
            )
    return public_settings(db, user_id)


def configured_api_key(db: Database, cipher: AISettingCipher, user_id: str) -> str | None:
    row = _row(db, user_id)
    return cipher.decrypt(row.get("api_key_encrypted")) if row else None
