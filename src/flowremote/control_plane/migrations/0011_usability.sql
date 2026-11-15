ALTER TABLE normalization_files ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS normalization_templates (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    options_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, name)
);
CREATE TABLE IF NOT EXISTS normalization_reopens (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES normalization_issues(id),
    by_user TEXT NOT NULL REFERENCES users(id),
    reopened_at TEXT NOT NULL,
    previous_status TEXT NOT NULL
);
