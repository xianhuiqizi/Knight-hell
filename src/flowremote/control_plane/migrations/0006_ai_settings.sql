-- FlowRemote 0006: per-user AI connection settings.
--
-- API keys are encrypted by the application before insertion. The key hint is
-- only the final four characters and is used to show that a secret exists.

CREATE TABLE IF NOT EXISTS ai_settings (
    user_id            TEXT PRIMARY KEY REFERENCES users(id),
    provider           TEXT NOT NULL CHECK (provider IN ('offline', 'openai')),
    model              TEXT,
    base_url           TEXT,
    api_key_encrypted  TEXT,
    api_key_hint       TEXT,
    updated_at         TEXT NOT NULL
);
