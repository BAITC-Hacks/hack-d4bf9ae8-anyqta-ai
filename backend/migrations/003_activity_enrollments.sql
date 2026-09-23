CREATE TABLE activity_enrollments (
    enrollment_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    history_record_id TEXT NOT NULL UNIQUE REFERENCES activity_history(record_id),
    status TEXT NOT NULL CHECK (status IN ('registered', 'completed')),
    registered_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (
        (status = 'registered' AND completed_at IS NULL)
        OR (status = 'completed' AND completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX active_activity_enrollment_idx
    ON activity_enrollments(employee_id, event_id)
    WHERE status = 'registered';

CREATE INDEX activity_enrollments_employee_idx
    ON activity_enrollments(employee_id, status);
