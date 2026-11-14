-- FlowRemote 0010: human review for normalization issues
--
-- Additive migration for Phase D: editable confirmation queue.
-- Adds decision tracking, revision control, and human action audit.

-- Decision log: append-only record of human confirm/skip actions
CREATE TABLE IF NOT EXISTS normalization_decisions (
    id           TEXT PRIMARY KEY,
    batch_id     TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id      TEXT NOT NULL REFERENCES tasks(id),
    issue_id     TEXT NOT NULL REFERENCES normalization_issues(id),
    decision_id  TEXT NOT NULL UNIQUE,  -- client idempotency key
    action       TEXT NOT NULL CHECK (action IN ('confirm', 'skip')),
    changes_json TEXT NOT NULL DEFAULT '{}',  -- edited field values
    reason       TEXT,  -- required for skip
    by_user      TEXT NOT NULL,
    decided_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalization_decisions_batch
    ON normalization_decisions (batch_id, decided_at);

CREATE INDEX IF NOT EXISTS idx_normalization_decisions_issue
    ON normalization_decisions (issue_id);

-- Add resolution tracking columns to normalization_issues
-- (migration is safe: columns nullable and have defaults)
ALTER TABLE normalization_issues ADD COLUMN resolved_by TEXT;
ALTER TABLE normalization_issues ADD COLUMN resolved_fields_json TEXT;
ALTER TABLE normalization_issues ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1);

-- Add revision tracking to normalized_records for conflict detection
ALTER TABLE normalized_records ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1);
