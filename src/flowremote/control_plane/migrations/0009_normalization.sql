-- FlowRemote 0009: multi-source normalization, progress and output provenance.
--
-- Additive only. Legacy tasks keep task_mode='orders' and every orders-v1 table
-- and rule is untouched. A normalize task owns one batch; the batch owns its
-- uploaded file metadata, source rows, change log and unresolved issues.

ALTER TABLE tasks ADD COLUMN task_mode TEXT NOT NULL DEFAULT 'orders';

CREATE TABLE IF NOT EXISTS normalization_batches (
    id                TEXT PRIMARY KEY,
    task_id           TEXT NOT NULL UNIQUE REFERENCES tasks(id),
    status            TEXT NOT NULL CHECK (status IN (
                          'uploaded', 'running', 'needs_review', 'complete',
                          'canceled', 'failed')),
    stage             TEXT NOT NULL DEFAULT 'detect' CHECK (stage IN (
                          'detect', 'map', 'normalize', 'merge', 'complete')),
    cursor            INTEGER NOT NULL DEFAULT 0 CHECK (cursor >= 0),
    current_file      TEXT,
    total_files       INTEGER NOT NULL CHECK (total_files > 0),
    processed_files   INTEGER NOT NULL DEFAULT 0 CHECK (processed_files >= 0),
    raw_records       INTEGER NOT NULL DEFAULT 0 CHECK (raw_records >= 0),
    normalized_records INTEGER NOT NULL DEFAULT 0 CHECK (normalized_records >= 0),
    auto_fixed        INTEGER NOT NULL DEFAULT 0 CHECK (auto_fixed >= 0),
    issue_count       INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
    rule_version      TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    duration_ms       INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalization_files (
    id               TEXT PRIMARY KEY,
    batch_id         TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id          TEXT NOT NULL REFERENCES tasks(id),
    ordinal          INTEGER NOT NULL CHECK (ordinal >= 0),
    filename         TEXT NOT NULL,
    storage_name     TEXT NOT NULL UNIQUE,
    byte_size        INTEGER NOT NULL CHECK (byte_size > 0),
    file_type        TEXT,
    worksheet        TEXT,
    header_row       INTEGER,
    row_count        INTEGER,
    field_count      INTEGER,
    detected_columns INTEGER,
    status           TEXT NOT NULL DEFAULT 'uploaded' CHECK (status IN (
                         'uploaded', 'detected', 'mapped', 'normalized', 'attention')),
    error            TEXT,
    mapping_json     TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (batch_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_normalization_files_task
    ON normalization_files (task_id, ordinal);

CREATE TABLE IF NOT EXISTS normalized_records (
    id              TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    file_id         TEXT NOT NULL REFERENCES normalization_files(id),
    source_file     TEXT NOT NULL,
    source_row      INTEGER NOT NULL,
    order_id        TEXT NOT NULL,
    customer_name   TEXT,
    customer_id     TEXT,
    quantity        INTEGER,
    unit            TEXT,
    unit_price      REAL,
    amount          REAL,
    order_date      TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
    duplicate_count INTEGER NOT NULL DEFAULT 1 CHECK (duplicate_count >= 1),
    has_conflict    INTEGER NOT NULL DEFAULT 0 CHECK (has_conflict IN (0, 1)),
    issue_count     INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
    created_at      TEXT NOT NULL,
    UNIQUE (batch_id, file_id, source_row)
);

CREATE INDEX IF NOT EXISTS idx_normalized_records_order
    ON normalized_records (batch_id, order_id);

CREATE TABLE IF NOT EXISTS normalization_changes (
    id             TEXT PRIMARY KEY,
    batch_id       TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    file_id        TEXT NOT NULL REFERENCES normalization_files(id),
    order_id       TEXT NOT NULL,
    source_file    TEXT NOT NULL,
    source_row     INTEGER NOT NULL,
    field          TEXT NOT NULL,
    original_value TEXT,
    new_value      TEXT,
    reason         TEXT NOT NULL,
    method         TEXT NOT NULL CHECK (method IN ('rule', 'ai', 'human')),
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalization_changes_batch
    ON normalization_changes (batch_id, source_file, source_row);

CREATE TABLE IF NOT EXISTS normalization_issues (
    id              TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL REFERENCES normalization_batches(id),
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    file_id         TEXT REFERENCES normalization_files(id),
    issue_type      TEXT NOT NULL CHECK (issue_type IN (
                        'missing_value', 'unit_conflict', 'cross_file_conflict',
                        'file_error', 'invalid_value', 'amount_mismatch')),
    field           TEXT NOT NULL DEFAULT '',
    order_id        TEXT,
    source_file     TEXT,
    source_row      INTEGER,
    original_value  TEXT,
    suggested_value TEXT,
    confidence      REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unresolved' CHECK (status IN (
                        'unresolved', 'resolved', 'skipped')),
    resolved_value  TEXT,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_normalization_issues_batch
    ON normalization_issues (batch_id, status, issue_type);
