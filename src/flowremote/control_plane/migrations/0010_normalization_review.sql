-- FlowRemote 0010: editable confirmation queue and AI-assisted review.
--
-- Additive only. The existing normalization schema and orders-v1 tables stay
-- intact; these columns/tables record a human decision and its validation.

ALTER TABLE normalization_issues ADD COLUMN resolved_by TEXT;
ALTER TABLE normalization_issues ADD COLUMN resolution_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE normalization_issues ADD COLUMN skip_reason TEXT;
ALTER TABLE normalization_issues ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE normalization_issues ADD COLUMN ai_suggestion_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE normalization_issues ADD COLUMN ai_source TEXT;
ALTER TABLE normalization_issues ADD COLUMN ai_suggested_at TEXT;

ALTER TABLE normalization_batches ADD COLUMN review_completed_at TEXT;

CREATE TABLE IF NOT EXISTS normalization_decisions (
    id            TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id       TEXT NOT NULL REFERENCES tasks(id),
    issue_id      TEXT NOT NULL REFERENCES normalization_issues(id),
    decision_id   TEXT NOT NULL UNIQUE,
    action        TEXT NOT NULL CHECK (action IN ('confirm', 'skip')),
    changes_json  TEXT NOT NULL DEFAULT '{}',
    reason        TEXT,
    by_user       TEXT NOT NULL REFERENCES users(id),
    decided_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalization_decisions_batch
    ON normalization_decisions (batch_id, decided_at);

CREATE INDEX IF NOT EXISTS idx_normalization_decisions_issue
    ON normalization_decisions (issue_id);
