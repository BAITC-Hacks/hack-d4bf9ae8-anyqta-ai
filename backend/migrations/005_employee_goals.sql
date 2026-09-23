-- Keep user choices separate from immutable imported profile JSON.
CREATE TABLE employee_goals (
    employee_id TEXT PRIMARY KEY REFERENCES employees(employee_id),
    target_role TEXT NOT NULL,
    target_grade TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_role, target_grade) REFERENCES role_profiles(role, grade)
);
