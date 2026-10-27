-- FlowRemote 0004: execution runs and the activity log (Week 6, Feature 2).
--
-- One execution run belongs to one approval attempt: UNIQUE (task_id, attempt)
-- is the database's way of saying "a released write cannot be duplicated".
-- Counts only move forward; written_count never exceeds approved_count and the
-- secondary target syncs the same records, so synced_count never exceeds
-- written_count either (BR-3, BR-5).
--
-- activity_events is append only, like decisions: a state change adds a row and
-- nothing updates an old one (BR-10). actor_kind separates a person from the
-- simulated execution engine so the log never implies a human did engine work.

CREATE TABLE IF NOT EXISTS execution_runs (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    attempt        INTEGER NOT NULL CHECK (attempt > 0),
    approved_count INTEGER NOT NULL CHECK (approved_count > 0),
    written_count  INTEGER NOT NULL DEFAULT 0 CHECK (written_count >= 0),
    synced_count   INTEGER NOT NULL DEFAULT 0 CHECK (synced_count >= 0),
    status         TEXT NOT NULL CHECK (status IN ('executing', 'complete', 'partial')),
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    duration_ms    INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    UNIQUE (task_id, attempt),
    CHECK (written_count <= approved_count),
    CHECK (synced_count <= written_count)
);

CREATE INDEX IF NOT EXISTS idx_execution_runs_task
    ON execution_runs (task_id, attempt);

CREATE TABLE IF NOT EXISTS activity_events (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES tasks(id),
    run_id       TEXT,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('user', 'engine')),
    kind         TEXT NOT NULL,
    description  TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_activity_events_task
    ON activity_events (task_id, occurred_at);
