CREATE TABLE IF NOT EXISTS task_uploads (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id),
    storage_name TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    worksheet TEXT NOT NULL,
    created_at TEXT NOT NULL
);
