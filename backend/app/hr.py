"""Private HR analytics and jury-profile import operations."""

from __future__ import annotations

import sqlite3
from calendar import monthrange
from datetime import date
from typing import Any

from .career import calculate_trajectory
from .importer import ImportValidationError, import_package, load_profile_package_from_text
from .profiles import employee_profile
from .recommendations import DEFAULT_AS_OF_DATE, LlmSelector, recommend_employee, recommendation_availability


class HrError(ValueError):
    """HR filter, employee detail or import request is invalid."""


def _six_months_before(as_of_date: str) -> str:
    try:
        point = date.fromisoformat(as_of_date)
    except ValueError as error:
        raise HrError("as_of_date must be an ISO date") from error
    month = point.month - 6
    year = point.year
    if month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(point.day, monthrange(year, month)[1])).isoformat()


def filter_options(connection: sqlite3.Connection) -> dict[str, list[str]]:
    return {
        "departments": [row[0] for row in connection.execute("SELECT DISTINCT department FROM employees ORDER BY department")],
        "roles": [row[0] for row in connection.execute("SELECT DISTINCT role FROM employees ORDER BY role")],
        "grades": [row[0] for row in connection.execute("SELECT DISTINCT grade FROM employees ORDER BY CASE grade WHEN 'Junior' THEN 1 WHEN 'Middle' THEN 2 WHEN 'Senior' THEN 3 ELSE 4 END")],
    }


def _employees(connection: sqlite3.Connection, filters: dict[str, str]) -> list[sqlite3.Row]:
    allowed = {"department", "role", "grade", "next_step"}
    unexpected = set(filters) - allowed
    if unexpected:
        raise HrError(f"Unknown filter: {sorted(unexpected)[0]}")
    if filters.get("next_step", "") not in {"", "available", "missing"}:
        raise HrError("next_step must be 'available' or 'missing'")
    clauses: list[str] = []
    values: list[str] = []
    for field in ("department", "role", "grade"):
        value = filters.get(field, "").strip()
        if value:
            clauses.append(f"{field} = ?")
            values.append(value)
    statement = "SELECT employee_id, full_name, department, role, grade FROM employees"
    if clauses:
        statement += " WHERE " + " AND ".join(clauses)
    statement += " ORDER BY full_name, employee_id"
    return connection.execute(statement, values).fetchall()


def _participation(connection: sqlite3.Connection, employee_id: str, since: str,
                   as_of_date: str) -> tuple[int, int]:
    row = connection.execute(
        """
        SELECT
          SUM(CASE WHEN events.mandatory = 0 AND history.status = 'completed'
                    AND history.activity_date BETWEEN ? AND ? THEN 1 ELSE 0 END) AS voluntary_completed,
          SUM(CASE WHEN events.mandatory = 0
                    AND history.status IN ('dropped', 'no_show', 'declined')
                    AND history.activity_date BETWEEN ? AND ? THEN 1 ELSE 0 END) AS voluntary_noncompletion
        FROM activity_history AS history
        JOIN events ON events.event_id = history.event_id
        WHERE history.employee_id = ?
        """,
        (since, as_of_date, since, as_of_date, employee_id),
    ).fetchone()
    return int(row["voluntary_completed"] or 0), int(row["voluntary_noncompletion"] or 0)


def _activity_participation(connection: sqlite3.Connection, employee_ids: list[str],
                            since: str, as_of_date: str) -> list[dict[str, Any]]:
    """Count participation records and unique people for the displayed cohort and period."""
    if not employee_ids:
        return []
    placeholders = ", ".join("?" for _ in employee_ids)
    statuses = ("completed", "in_progress", "dropped", "no_show", "declined", "overdue")
    status_columns = ", ".join(
        f"SUM(CASE WHEN history.status = '{status}' THEN 1 ELSE 0 END) AS {status}"
        for status in statuses
    )
    rows = connection.execute(
        f"""
        SELECT events.event_id, events.title, events.type, events.mandatory,
               COUNT(history.record_id) AS total_records,
               COUNT(DISTINCT history.employee_id) AS unique_participants,
               {status_columns}
        FROM events
        LEFT JOIN activity_history AS history
          ON history.event_id = events.event_id
         AND history.activity_date BETWEEN ? AND ?
         AND history.employee_id IN ({placeholders})
        GROUP BY events.event_id
        ORDER BY events.title, events.event_id
        """,
        (since, as_of_date, *employee_ids),
    )
    return [
        {
            "event_id": row["event_id"], "title": row["title"], "type": row["type"],
            "mandatory": bool(row["mandatory"]), "total_records": row["total_records"],
            "unique_participants": row["unique_participants"],
            "status_counts": {status: row[status] for status in statuses},
            "completion_rate_percent": round(100 * row["completed"] / row["total_records"], 2) if row["total_records"] else None,
        }
        for row in rows
    ]


def _support_signals(completed: int, noncompletion: int, since: str) -> list[str]:
    signals: list[str] = []
    if completed == 0:
        signals.append(f"Нет завершённых добровольных активностей с {since}.")
    if noncompletion >= 2:
        signals.append(f"{noncompletion} незавершённых, пропущенных или отклонённых добровольных активностей с {since}.")
    return signals


def hr_dashboard(connection: sqlite3.Connection, filters: dict[str, str] | None = None,
                 as_of_date: str = DEFAULT_AS_OF_DATE) -> dict[str, Any]:
    """Aggregate needs for HR without publishing a performance ranking."""
    filters = filters or {}
    since = _six_months_before(as_of_date)
    rows = _employees(connection, filters)
    gaps: dict[str, dict[str, Any]] = {}
    people: list[dict[str, Any]] = []
    needs_support = 0
    for employee in rows:
        next_step = recommendation_availability(connection, employee["employee_id"], as_of_date)
        if filters.get("next_step") == "missing" and next_step["has_next_step"]:
            continue
        if filters.get("next_step") == "available" and not next_step["has_next_step"]:
            continue
        trajectory = calculate_trajectory(connection, employee["employee_id"])
        completed, noncompletion = _participation(connection, employee["employee_id"], since, as_of_date)
        signals = _support_signals(completed, noncompletion, since)
        if signals:
            needs_support += 1
        for gap in trajectory["skill_gaps"]:
            if gap["gap"] <= 0:
                continue
            summary = gaps.setdefault(
                gap["skill_id"],
                {
                    "skill_id": gap["skill_id"], "skill_name": gap["skill_name"],
                    "employees_affected": 0, "total_gap": 0, "critical_gap_count": 0,
                },
            )
            summary["employees_affected"] += 1
            summary["total_gap"] += gap["gap"]
            summary["critical_gap_count"] += int(gap["is_critical"])
        people.append(
            {
                "employee_id": employee["employee_id"], "full_name": employee["full_name"],
                "department": employee["department"], "role": employee["role"], "grade": employee["grade"],
                "target": trajectory["target"], "coverage_percent": trajectory["coverage_percent"],
                "support_signals": signals, "voluntary_completed_since": completed,
                "voluntary_noncompletion_since": noncompletion,
                "next_step": next_step,
            }
        )
    return {
        "filters": filters,
        "filter_options": filter_options(connection),
        "as_of_date": as_of_date,
        "support_period_start": since,
        "summary": {
            "employees": len(people), "needs_support": needs_support, "competencies_with_gaps": len(gaps),
            "without_next_step": sum(not person["next_step"]["has_next_step"] for person in people),
        },
        "competency_gaps": sorted(gaps.values(), key=lambda item: (-item["critical_gap_count"], -item["employees_affected"], -item["total_gap"], item["skill_name"])),
        "employees": people,
        "activity_participation": _activity_participation(
            connection, [person["employee_id"] for person in people], since, as_of_date
        ),
    }


def hr_employee_detail(connection: sqlite3.Connection, employee_id: str,
                       as_of_date: str = DEFAULT_AS_OF_DATE,
                       selector: LlmSelector | None = None) -> dict[str, Any]:
    employee = connection.execute(
        "SELECT employee_id, full_name, department, role, grade, work_format, preferred_language FROM employees WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()
    if employee is None:
        raise HrError("Employee not found")
    trajectory = calculate_trajectory(connection, employee_id)
    recommendations = recommend_employee(
        connection, employee_id, as_of_date=as_of_date, selector=selector
    )
    completed, noncompletion = _participation(connection, employee_id, _six_months_before(as_of_date), as_of_date)
    return {
        "employee": dict(employee), "trajectory": trajectory,
        "profile": employee_profile(connection, employee_id),
        "recommendations": recommendations["recommendations"],
        "recommendation_mode": recommendations["mode"],
        "recommendation_notice": recommendations["fallback_reason"],
        "participation": {"voluntary_completed": completed, "voluntary_noncompletion": noncompletion},
    }


def import_hr_profile_package(connection: sqlite3.Connection, employees_json: str,
                              history_csv: str, source_name: str = "HR upload") -> dict[str, int]:
    """Atomically import a jury package in the original JSON/CSV schema."""
    try:
        package = load_profile_package_from_text(employees_json, history_csv, source_name)
        import_package(connection, package, "profiles", source_name)
    except ImportValidationError as error:
        raise HrError(str(error)) from error
    return {"employees_imported": len(package.employees), "history_records_imported": len(package.history)}
