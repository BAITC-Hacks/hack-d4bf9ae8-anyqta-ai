CREATE TABLE import_batches (
    batch_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('full', 'profiles')),
    source_description TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('hard', 'soft')),
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    source_json TEXT NOT NULL
);

CREATE TABLE role_profiles (
    role TEXT NOT NULL,
    grade TEXT NOT NULL CHECK (grade IN ('Junior', 'Middle', 'Senior', 'Lead')),
    PRIMARY KEY (role, grade)
);

CREATE TABLE role_requirements (
    role TEXT NOT NULL,
    grade TEXT NOT NULL,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    required_level INTEGER NOT NULL CHECK (required_level BETWEEN 0 AND 5),
    PRIMARY KEY (role, grade, skill_id),
    FOREIGN KEY (role, grade) REFERENCES role_profiles(role, grade)
);

CREATE TABLE role_critical_skills (
    role TEXT NOT NULL,
    grade TEXT NOT NULL,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    PRIMARY KEY (role, grade, skill_id),
    FOREIGN KEY (role, grade) REFERENCES role_profiles(role, grade)
);

CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL,
    role TEXT NOT NULL,
    grade TEXT NOT NULL CHECK (grade IN ('Junior', 'Middle', 'Senior', 'Lead')),
    manager_id TEXT REFERENCES employees(employee_id),
    hire_date TEXT NOT NULL,
    tenure_months INTEGER NOT NULL CHECK (tenure_months >= 0),
    work_format TEXT NOT NULL CHECK (work_format IN ('office', 'hybrid', 'remote')),
    preferred_language TEXT NOT NULL CHECK (preferred_language IN ('kk', 'ru', 'en')),
    target_role TEXT,
    target_grade TEXT CHECK (target_grade IN ('Junior', 'Middle', 'Senior', 'Lead')),
    last_review_date TEXT NOT NULL,
    source_json TEXT NOT NULL
);

CREATE TABLE employee_skills (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 5),
    PRIMARY KEY (employee_id, skill_id)
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    type TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('online', 'offline', 'self_paced')),
    duration_hours REAL NOT NULL CHECK (duration_hours > 0),
    mandatory INTEGER NOT NULL CHECK (mandatory IN (0, 1)),
    source_json TEXT NOT NULL
);

CREATE TABLE event_target_roles (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    role TEXT NOT NULL,
    PRIMARY KEY (event_id, role)
);

CREATE TABLE event_target_grades (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    grade TEXT NOT NULL CHECK (grade IN ('Junior', 'Middle', 'Senior', 'Lead')),
    PRIMARY KEY (event_id, grade)
);

CREATE TABLE event_develops_skills (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    gain INTEGER NOT NULL CHECK (gain BETWEEN 1 AND 5),
    max_level INTEGER NOT NULL CHECK (max_level BETWEEN 0 AND 5),
    PRIMARY KEY (event_id, skill_id),
    CHECK (gain <= max_level)
);

CREATE TABLE event_prerequisites (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    minimum_level INTEGER NOT NULL CHECK (minimum_level BETWEEN 0 AND 5),
    PRIMARY KEY (event_id, skill_id)
);

CREATE TABLE event_sessions (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    session_date TEXT NOT NULL,
    PRIMARY KEY (event_id, session_date)
);

CREATE TABLE activity_history (
    record_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    activity_date TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('completed', 'in_progress', 'dropped', 'no_show', 'declined', 'overdue')),
    completion_pct INTEGER NOT NULL CHECK (completion_pct BETWEEN 0 AND 100),
    score INTEGER CHECK (score BETWEEN 0 AND 100),
    feedback_rating INTEGER CHECK (feedback_rating BETWEEN 1 AND 5),
    assigned_by TEXT NOT NULL CHECK (assigned_by IN ('self', 'manager', 'hr')),
    source_json TEXT NOT NULL
);

CREATE INDEX activity_history_employee_date_idx ON activity_history(employee_id, activity_date);
CREATE INDEX activity_history_event_idx ON activity_history(event_id);
