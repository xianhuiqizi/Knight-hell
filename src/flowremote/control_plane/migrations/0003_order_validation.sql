CREATE TABLE IF NOT EXISTS order_inputs (
    task_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    excel_row INTEGER NOT NULL,
    order_id TEXT,
    original_json TEXT NOT NULL,
    current_json TEXT NOT NULL,
    issues_json TEXT NOT NULL,
    PRIMARY KEY (task_id, record_id),
    FOREIGN KEY (task_id, record_id) REFERENCES source_records(task_id, record_id)
);

CREATE TABLE IF NOT EXISTS task_validations (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id),
    header_row INTEGER NOT NULL,
    rule_version TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    validated_at TEXT NOT NULL
);
