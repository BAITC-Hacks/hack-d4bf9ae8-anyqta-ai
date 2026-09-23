"""Deterministic career-trajectory calculations for Career Quest."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from .db import connect, migrate


GRADE_ORDER = ("Junior", "Middle", "Senior", "Lead")
DEFAULT_AS_OF_DATE = "2026-10-01"


class CareerCalculationError(ValueError):
    """The stored profile cannot be used to calculate a trajectory."""


@dataclass(frozen=True)
class SkillChange:
    record_id: str
    event_id: str
    event_title: str
    activity_date: str
    skill_id: str
    before_level: int
    after_level: int
    gain: int
    max_level: int


def _next_grade(grade: str) -> str | None:
    try:
        index = GRADE_ORDER.index(grade)
    except ValueError as error:
        raise CareerCalculationError(f"Unknown employee grade '{grade}'") from error
    return GRADE_ORDER[index + 1] if index < len(GRADE_ORDER) - 1 else None


def _employee(connection: sqlite3.Connection, employee_id: str) -> sqlite3.Row:
    employee = connection.execute(
        """
        SELECT e.employee_id, e.full_name, e.role, e.grade, e.tenure_months,
               e.work_format, e.preferred_language, e.last_review_date,
               COALESCE(g.target_role, e.target_role) AS target_role,
               COALESCE(g.target_grade, e.target_grade) AS target_grade
        FROM employees e LEFT JOIN employee_goals g USING(employee_id)
        WHERE e.employee_id = ?
        """,
        (employee_id,),
    ).fetchone()
    if employee is None:
        raise CareerCalculationError(f"Employee '{employee_id}' does not exist")
    return employee


def _target(employee: sqlite3.Row) -> tuple[str, str] | None:
    """Use the declared goal, otherwise advance one grade in the current role."""
    if employee["target_role"] and employee["target_grade"]:
        return employee["target_role"], employee["target_grade"]
    next_grade = _next_grade(employee["grade"])
    return (employee["role"], next_grade) if next_grade is not None else None


def _effective_skills(connection: sqlite3.Connection, employee: sqlite3.Row,
                      as_of_date: str) -> tuple[dict[str, int], list[SkillChange]]:
    levels = {
        row["skill_id"]: row["level"]
        for row in connection.execute(
            "SELECT skill_id, level FROM employee_skills WHERE employee_id = ?",
            (employee["employee_id"],),
        )
    }
    changes: list[SkillChange] = []
    completed = connection.execute(
        """
        SELECT history.record_id, history.event_id, history.activity_date, events.title
        FROM activity_history AS history
        JOIN events ON events.event_id = history.event_id
        WHERE history.employee_id = ?
          AND history.status = 'completed'
          AND history.activity_date > ?
          AND history.activity_date <= ?
        ORDER BY history.activity_date, history.record_id
        """,
        (employee["employee_id"], employee["last_review_date"], as_of_date),
    )
    for activity in completed:
        developments = connection.execute(
            """
            SELECT skill_id, gain, max_level
            FROM event_develops_skills WHERE event_id = ? ORDER BY skill_id
            """,
            (activity["event_id"],),
        )
        for development in developments:
            before = levels.get(development["skill_id"], 0)
            after = max(before, min(5, development["max_level"], before + development["gain"]))
            levels[development["skill_id"]] = after
            changes.append(
                SkillChange(
                    record_id=activity["record_id"],
                    event_id=activity["event_id"],
                    event_title=activity["title"],
                    activity_date=activity["activity_date"],
                    skill_id=development["skill_id"],
                    before_level=before,
                    after_level=after,
                    gain=development["gain"],
                    max_level=development["max_level"],
                )
            )
    return levels, changes


def calculate_trajectory(connection: sqlite3.Connection, employee_id: str,
                         as_of_date: str = DEFAULT_AS_OF_DATE) -> dict[str, Any]:
    """Return a transparent snapshot of skills, target requirements and gaps.

    The function does not write to the database. Missing skills are represented
    as level zero. It intentionally does not call an LLM: this is the factual
    input that the recommendation layer will use in the next implementation
    step.
    """
    employee = _employee(connection, employee_id)
    target = _target(employee)
    effective_skills, changes = _effective_skills(connection, employee, as_of_date)

    result: dict[str, Any] = {
        "employee": {
            "employee_id": employee["employee_id"],
            "full_name": employee["full_name"],
            "role": employee["role"],
            "grade": employee["grade"],
            "last_review_date": employee["last_review_date"],
            "tenure_months": employee["tenure_months"],
            "work_format": employee["work_format"],
            "preferred_language": employee["preferred_language"],
        },
        "effective_skills": dict(sorted(effective_skills.items())),
        "applied_skill_changes": [asdict(change) for change in changes],
        "as_of_date": as_of_date,
    }
    if target is None:
        result.update(
            {
                "target": None,
                "trajectory_status": "goal_required",
                "message": "Lead without a declared career goal; choose a target role and grade.",
                "skill_gaps": [],
                "coverage_percent": None,
                "critical_gaps_remaining": 0,
            }
        )
        return result

    target_role, target_grade = target
    requirements = connection.execute(
        """
        SELECT requirements.skill_id, requirements.required_level, skills.name,
               CASE WHEN critical.skill_id IS NULL THEN 0 ELSE 1 END AS is_critical
        FROM role_requirements AS requirements
        JOIN skills ON skills.skill_id = requirements.skill_id
        LEFT JOIN role_critical_skills AS critical
          ON critical.role = requirements.role
         AND critical.grade = requirements.grade
         AND critical.skill_id = requirements.skill_id
        WHERE requirements.role = ? AND requirements.grade = ?
        ORDER BY is_critical DESC, skills.name, requirements.skill_id
        """,
        (target_role, target_grade),
    ).fetchall()
    if not requirements:
        raise CareerCalculationError(
            f"No requirements found for target '{target_role}' / '{target_grade}'"
        )

    gaps = []
    covered_levels = 0
    required_levels = 0
    for requirement in requirements:
        current_level = effective_skills.get(requirement["skill_id"], 0)
        required_level = requirement["required_level"]
        covered_levels += min(current_level, required_level)
        required_levels += required_level
        gaps.append(
            {
                "skill_id": requirement["skill_id"],
                "skill_name": requirement["name"],
                "current_level": current_level,
                "required_level": required_level,
                "gap": max(0, required_level - current_level),
                "is_critical": bool(requirement["is_critical"]),
            }
        )
    result.update(
        {
            "target": {"role": target_role, "grade": target_grade},
            "trajectory_status": "ready",
            "skill_gaps": gaps,
            "coverage_percent": round(100 * covered_levels / required_levels, 2) if required_levels else None,
            "critical_gaps_remaining": sum(item["is_critical"] and item["gap"] > 0 for item in gaps),
        }
    )
    return result


def goal_options(connection: sqlite3.Connection) -> list[dict[str, str]]:
    return [dict(row) for row in connection.execute(
        "SELECT role, grade FROM role_profiles ORDER BY role, "
        "CASE grade WHEN 'Junior' THEN 1 WHEN 'Middle' THEN 2 WHEN 'Senior' THEN 3 ELSE 4 END"
    )]


def set_goal(connection: sqlite3.Connection, employee_id: str, role: str, grade: str) -> None:
    _employee(connection, employee_id)
    if not isinstance(role, str) or not isinstance(grade, str) or not connection.execute(
        "SELECT 1 FROM role_requirements WHERE role = ? AND grade = ?", (role, grade)
    ).fetchone():
        raise CareerCalculationError("Выберите роль и грейд из доступных карьерных целей.")
    with connection:
        connection.execute(
            "INSERT INTO employee_goals(employee_id, target_role, target_grade) VALUES (?, ?, ?) "
            "ON CONFLICT(employee_id) DO UPDATE SET target_role = excluded.target_role, "
            "target_grade = excluded.target_grade, updated_at = CURRENT_TIMESTAMP",
            (employee_id, role, grade),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate a Career Quest employee trajectory")
    parser.add_argument("--database", required=True)
    parser.add_argument("--employee-id", required=True)
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        result = calculate_trajectory(connection, args.employee_id)
    except CareerCalculationError as error:
        parser.exit(2, f"Calculation failed: {error}\n")
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
