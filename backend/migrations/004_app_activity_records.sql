CREATE TABLE app_activity_records (
    record_id TEXT PRIMARY KEY REFERENCES activity_history(record_id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX app_activity_records_employee_idx ON app_activity_records(employee_id);
