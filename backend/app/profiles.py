"""Complete employee skill/history views and employee-owned career goals."""

from __future__ import annotations

import sqlite3
from typing import Any

from .career import calculate_trajectory


class ProfileError(ValueError):
    """A profile or career goal is invalid."""


def employee_profile(connection: sqlite3.Connection, employee_id: str) -> dict[str, Any]:
    employee = connection.execute(
        """
        SELECT employee_id, full_name, department, role, grade, hire_date,
               tenure_months, work_format, preferred_language, last_review_date,
               target_role, target_grade
        FROM employees WHERE employee_id = ?
        """,
        (employee_id,),
    ).fetchone()
    if employee is None:
        raise ProfileError("Employee not found")
    trajectory = calculate_trajectory(connection, employee_id)
    requirements = {item["skill_id"]: item for item in trajectory["skill_gaps"]}
    assessed = {
        row["skill_id"]: row["level"] for row in connection.execute(
            "SELECT skill_id, level FROM employee_skills WHERE employee_id = ?", (employee_id,)
        )
    }
    catalog = connection.execute("SELECT skill_id, name, type, category, description FROM skills ORDER BY name, skill_id").fetchall()
    skills = []
    names = {row["skill_id"]: row["name"] for row in catalog}
    for skill in catalog:
        requirement = requirements.get(skill["skill_id"])
        skills.append({
            **dict(skill),
            "assessed_level": assessed.get(skill["skill_id"], 0),
            "assessed": skill["skill_id"] in assessed,
            "current_level": trajectory["effective_skills"].get(skill["skill_id"], 0),
            "required_level": requirement["required_level"] if requirement else None,
            "gap": requirement["gap"] if requirement else None,
            "is_critical": bool(requirement and requirement["is_critical"]),
        })
    changes: dict[str, list[dict[str, Any]]] = {}
    for change in trajectory["applied_skill_changes"]:
        changes.setdefault(change["record_id"], []).append({
            **change, "skill_name": names[change["skill_id"]],
        })
    history = []
    for row in connection.execute(
        """
        SELECT history.record_id, history.event_id, events.title, events.type,
               events.format, events.mandatory, history.activity_date, history.due_date,
               history.status, history.completion_pct, history.score,
               history.feedback_rating, history.assigned_by, enrollments.completed_at,
               EXISTS (SELECT 1 FROM event_develops_skills WHERE event_id = events.event_id) AS has_skill_gain
        FROM activity_history AS history
        JOIN events ON events.event_id = history.event_id
        LEFT JOIN activity_enrollments AS enrollments
          ON enrollments.history_record_id = history.record_id
        WHERE history.employee_id = ?
        ORDER BY history.activity_date DESC, history.record_id DESC
        """,
        (employee_id,),
    ):
        if row["status"] != "completed":
            effect = "not_completed"
        elif not row["has_skill_gain"]:
            effect = "no_skill_change"
        elif row["activity_date"] <= employee["last_review_date"]:
            effect = "included_in_assessment"
        elif changes.get(row["record_id"]):
            effect = "calculated"
        else:
            effect = "no_skill_change"
        history.append({
            **dict(row), "mandatory": bool(row["mandatory"]),
            "skill_effect": effect, "skill_changes": changes.get(row["record_id"], []),
        })
    return {
        "employee": dict(employee), "skills": skills, "history": history,
        "goal_options": [dict(row) for row in connection.execute(
            """
            SELECT role, grade FROM role_profiles
            WHERE EXISTS (
                SELECT 1 FROM role_requirements
                WHERE role_requirements.role = role_profiles.role
                  AND role_requirements.grade = role_profiles.grade
            )
            ORDER BY role, CASE grade WHEN 'Junior' THEN 1 WHEN 'Middle' THEN 2 WHEN 'Senior' THEN 3 ELSE 4 END
            """
        )],
    }


def update_career_goal(connection: sqlite3.Connection, employee_id: str,
                       target_role: str | None, target_grade: str | None) -> dict[str, Any]:
    """Persist a supported goal, or clear it to use the default next-grade policy."""
    if target_role is not None or target_grade is not None:
        if not isinstance(target_role, str) or not isinstance(target_grade, str):
            raise ProfileError("Choose both a target role and grade")
        target_role, target_grade = target_role.strip(), target_grade.strip()
        valid = connection.execute(
            "SELECT 1 FROM role_requirements WHERE role = ? AND grade = ? LIMIT 1",
            (target_role, target_grade),
        ).fetchone()
        if valid is None:
            raise ProfileError("Choose a target role and grade from the available options")
    with connection:
        # source_json remains the immutable import snapshot, preserving import
        # retries and allowing demo reset to restore the original goal.
        updated = connection.execute(
            "UPDATE employees SET target_role = ?, target_grade = ? WHERE employee_id = ?",
            (target_role, target_grade, employee_id),
        ).rowcount
        if updated != 1:
            raise ProfileError("Employee not found")
        trajectory = calculate_trajectory(connection, employee_id)
    return {"trajectory": trajectory}
