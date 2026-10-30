"""Resolve the AI provider selected by one signed-in user."""

from __future__ import annotations

from flowremote.agent.providers import (
    OfflineSuggestionProvider,
    OpenAISuggestionProvider,
    SuggestionProvider,
)
from flowremote.control_plane.ai_settings import AISettingCipher
from flowremote.control_plane.db import Database


def provider_for_user(
    db: Database,
    cipher: AISettingCipher,
    *,
    user_id: str,
    fallback: SuggestionProvider,
) -> SuggestionProvider:
    rows = db.query("SELECT * FROM ai_settings WHERE user_id = ?", (user_id,))
    if not rows:
        return fallback
    row = rows[0]
    if row["provider"] == "offline":
        return OfflineSuggestionProvider()
    api_key = cipher.decrypt(row.get("api_key_encrypted"))
    return OpenAISuggestionProvider(
        model=row.get("model") or "gpt-6-astra",
        api_key=api_key,
        base_url=row.get("base_url"),
    )
