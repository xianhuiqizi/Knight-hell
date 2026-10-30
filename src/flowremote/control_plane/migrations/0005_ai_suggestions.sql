-- FlowRemote 0005: append-only AI suggestion runs and field-level suggestions.
--
-- The provider is never allowed to change an exception directly. A run starts
-- as pending, the provider is called outside the transaction, and a second
-- transaction records the result. request_id makes a double-click idempotent.

CREATE TABLE IF NOT EXISTS ai_suggestion_runs (
    id                TEXT PRIMARY KEY,
    task_id           TEXT NOT NULL REFERENCES tasks(id),
    exception_id      TEXT NOT NULL REFERENCES exceptions(id),
    request_id        TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (
                          status IN ('pending', 'completed', 'invalid', 'failed')),
    provider          TEXT NOT NULL,
    model             TEXT,
    prompt_version    TEXT NOT NULL,
    input_hash        TEXT NOT NULL,
    message           TEXT,
    raw_response_json TEXT NOT NULL DEFAULT '{}',
    error_code        TEXT,
    created_at        TEXT NOT NULL,
    completed_at      TEXT,
    duration_ms       INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    UNIQUE (exception_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_suggestion_runs_exception
    ON ai_suggestion_runs (exception_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_suggestion_runs_task
    ON ai_suggestion_runs (task_id, created_at);

CREATE TABLE IF NOT EXISTS ai_suggestion_items (
    run_id          TEXT NOT NULL REFERENCES ai_suggestion_runs(id),
    field           TEXT NOT NULL,
    value           TEXT NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason          TEXT NOT NULL,
    evidence_json   TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, field)
);
