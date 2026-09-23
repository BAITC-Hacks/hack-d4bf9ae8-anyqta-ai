CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    access_role TEXT NOT NULL CHECK (access_role IN ('employee', 'hr')),
    employee_id TEXT UNIQUE REFERENCES employees(employee_id),
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (access_role = 'employee' AND employee_id IS NOT NULL)
        OR (access_role = 'hr' AND employee_id IS NULL)
    )
);

CREATE INDEX users_employee_idx ON users(employee_id);
