-- FlowRemote 0001: the tables behind the Week 5 demonstration task.
--
-- Portable subset only: TEXT / INTEGER / REAL, CHECK and UNIQUE constraints.
-- Every timestamp is UTC ISO-8601 text, for example 2026-09-30T14:31:00Z.
-- Values in CHECK (...) match the Select values on the paper data model.

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL CHECK (role IN ('operator', 'admin')),
    device        TEXT,
    password_hash TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT PRIMARY KEY,
    workflow         TEXT NOT NULL,
    batch_size       INTEGER NOT NULL CHECK (batch_size > 0),
    status           TEXT NOT NULL CHECK (status IN (
                         'ready', 'validating', 'review_required',
                         'pending_approval', 'executing', 'complete')),
    source_file      TEXT NOT NULL,
    source_location  TEXT NOT NULL,
    primary_target   TEXT NOT NULL,
    secondary_target TEXT NOT NULL,
    owner_id         TEXT REFERENCES users(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- The raw input batch. The suggestion step reads it, and it is what makes
-- "100 input, 88 passed, 12 flagged" checkable with one query.
CREATE TABLE IF NOT EXISTS source_records (
    task_id       TEXT NOT NULL REFERENCES tasks(id),
    record_id     TEXT NOT NULL,
    customer_name TEXT,
    customer_id   TEXT,
    quantity      INTEGER,
    unit_price    REAL,
    amount        REAL,
    order_date    TEXT,
    outcome       TEXT NOT NULL CHECK (outcome IN ('passed', 'flagged')),
    PRIMARY KEY (task_id, record_id)
);

CREATE TABLE IF NOT EXISTS exceptions (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    record_id      TEXT NOT NULL,
    issue          TEXT NOT NULL,
    flagged_fields TEXT NOT NULL,
    original_value TEXT,
    suggestion     TEXT,
    confidence     REAL,
    reason         TEXT,
    status         TEXT NOT NULL CHECK (status IN (
                       'unresolved', 'accepted', 'manual', 'skipped')),
    resolved_value TEXT,
    reviewed_by    TEXT REFERENCES users(id),
    reviewed_at    TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (task_id, record_id)
);

-- Append only: a re-opened decision adds a row, it never edits the old one.
CREATE TABLE IF NOT EXISTS decisions (
    id           TEXT PRIMARY KEY,
    exception_id TEXT NOT NULL REFERENCES exceptions(id),
    decision_id  TEXT NOT NULL UNIQUE,
    action       TEXT NOT NULL CHECK (action IN ('accept', 'edit', 'skip')),
    new_value    TEXT,
    by_user      TEXT NOT NULL REFERENCES users(id),
    decided_at   TEXT NOT NULL
);

-- One row per authorisation. UNIQUE (task_id, attempt) is what makes
-- "a task can be approved only once" true in the database, not only in the UI.
CREATE TABLE IF NOT EXISTS approvals (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    attempt        INTEGER NOT NULL CHECK (attempt > 0),
    approver_id    TEXT NOT NULL REFERENCES users(id),
    approved_count INTEGER NOT NULL CHECK (approved_count > 0),
    skipped_count  INTEGER NOT NULL CHECK (skipped_count >= 0),
    approved_at    TEXT NOT NULL,
    UNIQUE (task_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_exceptions_task_status
    ON exceptions (task_id, status);
CREATE INDEX IF NOT EXISTS idx_source_records_outcome
    ON source_records (task_id, outcome);
CREATE INDEX IF NOT EXISTS idx_decisions_exception
    ON decisions (exception_id);
