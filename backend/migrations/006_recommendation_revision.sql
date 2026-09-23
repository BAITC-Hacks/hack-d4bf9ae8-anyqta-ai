-- Invalidate cached recommendations for committed changes, including CLI imports.
CREATE TABLE recommendation_revision (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL);
INSERT INTO recommendation_revision VALUES (1, 0);

CREATE TRIGGER rec_employees_insert AFTER INSERT ON employees
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employees_update AFTER UPDATE ON employees
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employees_delete AFTER DELETE ON employees
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_skills_insert AFTER INSERT ON employee_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_skills_update AFTER UPDATE ON employee_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_skills_delete AFTER DELETE ON employee_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_goals_insert AFTER INSERT ON employee_goals
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_goals_update AFTER UPDATE ON employee_goals
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_employee_goals_delete AFTER DELETE ON employee_goals
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_activity_history_insert AFTER INSERT ON activity_history
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_activity_history_update AFTER UPDATE ON activity_history
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_activity_history_delete AFTER DELETE ON activity_history
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_events_insert AFTER INSERT ON events
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_events_update AFTER UPDATE ON events
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_events_delete AFTER DELETE ON events
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_roles_insert AFTER INSERT ON event_target_roles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_roles_update AFTER UPDATE ON event_target_roles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_roles_delete AFTER DELETE ON event_target_roles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_grades_insert AFTER INSERT ON event_target_grades
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_grades_update AFTER UPDATE ON event_target_grades
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_target_grades_delete AFTER DELETE ON event_target_grades
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_prerequisites_insert AFTER INSERT ON event_prerequisites
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_prerequisites_update AFTER UPDATE ON event_prerequisites
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_prerequisites_delete AFTER DELETE ON event_prerequisites
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_sessions_insert AFTER INSERT ON event_sessions
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_sessions_update AFTER UPDATE ON event_sessions
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_sessions_delete AFTER DELETE ON event_sessions
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_develops_skills_insert AFTER INSERT ON event_develops_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_develops_skills_update AFTER UPDATE ON event_develops_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_event_develops_skills_delete AFTER DELETE ON event_develops_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_skills_insert AFTER INSERT ON skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_skills_update AFTER UPDATE ON skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_skills_delete AFTER DELETE ON skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_profiles_insert AFTER INSERT ON role_profiles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_profiles_update AFTER UPDATE ON role_profiles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_profiles_delete AFTER DELETE ON role_profiles
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_requirements_insert AFTER INSERT ON role_requirements
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_requirements_update AFTER UPDATE ON role_requirements
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_requirements_delete AFTER DELETE ON role_requirements
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_critical_skills_insert AFTER INSERT ON role_critical_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_critical_skills_update AFTER UPDATE ON role_critical_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;

CREATE TRIGGER rec_role_critical_skills_delete AFTER DELETE ON role_critical_skills
BEGIN
    UPDATE recommendation_revision SET revision = revision + 1 WHERE singleton = 1;
END;
