"""Validated, atomic importer for the Career Quest starter-kit schema."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .db import connect, migrate

GRADES = {"Junior", "Middle", "Senior", "Lead"}
STATUSES = {"completed", "in_progress", "dropped", "no_show", "declined", "overdue"}


class ImportValidationError(ValueError):
    """A source package is structurally valid JSON/CSV but violates its contract."""


@dataclass(frozen=True)
class Package:
    employees: list[dict[str, Any]]
    history: list[dict[str, str]]
    skills: list[dict[str, Any]] | None = None
    role_profiles: list[dict[str, Any]] | None = None
    events: list[dict[str, Any]] | None = None


def _read_json_list(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportValidationError(f"Cannot read {path}: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ImportValidationError(f"{path} must contain an array named '{key}'")
    if not all(isinstance(item, dict) for item in payload[key]):
        raise ImportValidationError(f"{path}:{key} must contain objects")
    return payload[key]


def _read_history(path: Path) -> list[dict[str, str]]:
    try:
        return _parse_history(path.read_text(encoding="utf-8-sig"), str(path))
    except OSError as error:
        raise ImportValidationError(f"Cannot read {path}: {error}") from error


def _parse_history(text: str, source: str) -> list[dict[str, str]]:
    required = {
        "record_id", "employee_id", "event_id", "date", "due_date", "status",
        "completion_pct", "score", "feedback_rating", "assigned_by",
    }
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    try:
        if reader.fieldnames is None or set(reader.fieldnames) != required or len(reader.fieldnames) != len(required):
            raise ImportValidationError(f"{source}: invalid CSV header; expected {', '.join(sorted(required))}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ImportValidationError(f"{source}: CSV line {reader.line_num}: incorrect number of columns")
            rows.append(row)
        return rows
    except csv.Error as error:
        raise ImportValidationError(f"{source}: CSV line {reader.line_num}: {error}") from error


def load_full_package(dataset_dir: str | Path) -> Package:
    directory = Path(dataset_dir)
    return Package(
        employees=_read_json_list(directory / "employees.json", "employees"),
        history=_read_history(directory / "activity_history.csv"),
        skills=_read_json_list(directory / "skills.json", "skills"),
        role_profiles=_read_json_list(directory / "skills.json", "role_profiles"),
        events=_read_json_list(directory / "events.json", "events"),
    )


def load_profile_package(employees: str | Path, history: str | Path) -> Package:
    return Package(
        employees=_read_json_list(Path(employees), "employees"),
        history=_read_history(Path(history)),
    )


def load_profile_package_from_text(employees_json: str, history_csv: str,
                                   source_name: str = "uploaded package") -> Package:
    """Parse a jury upload without writing its JSON/CSV files to disk."""
    try:
        payload = json.loads(employees_json.lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise ImportValidationError(f"{source_name}: employees JSON is invalid: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("employees"), list):
        raise ImportValidationError(f"{source_name}: employees JSON must contain an 'employees' array")
    if not all(isinstance(item, dict) for item in payload["employees"]):
        raise ImportValidationError(f"{source_name}: employees array must contain objects")
    return Package(employees=payload["employees"], history=_parse_history(history_csv, source_name))


def _require(item: dict[str, Any], field: str, context: str) -> Any:
    value = item.get(field)
    if value is None or value == "":
        raise ImportValidationError(f"{context}: missing '{field}'")
    return value


def _date(value: str, context: str, optional: bool = False) -> None:
    if not value and optional:
        return
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ImportValidationError(f"{context}: invalid ISO date '{value}'") from error


def _integer(value: Any, context: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ImportValidationError(f"{context}: must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ImportValidationError(f"{context}: must be an integer") from error
    if parsed < minimum or parsed > maximum:
        raise ImportValidationError(f"{context}: must be between {minimum} and {maximum}")
    return parsed


def _ids(items: Iterable[dict[str, Any]], field: str, label: str) -> set[str]:
    values: set[str] = set()
    for index, item in enumerate(items, start=1):
        value = _require(item, field, f"{label}[{index}]")
        if not isinstance(value, str) or value in values:
            raise ImportValidationError(f"{label}[{index}]: duplicate or invalid '{field}'")
        values.add(value)
    return values


def validate(package: Package, known_skill_ids: set[str] | None = None,
             known_event_ids: set[str] | None = None,
             known_employee_ids: set[str] | None = None,
             known_role_profiles: set[tuple[str, str]] | None = None) -> None:
    """Validate all cross references before a transaction changes the database."""
    employee_ids = _ids(package.employees, "employee_id", "employees")
    history_ids = _ids(package.history, "record_id", "activity_history")
    del history_ids
    skill_ids = known_skill_ids or set()
    event_ids = known_event_ids or set()
    combinations = known_role_profiles or set()

    if package.skills is not None:
        skill_ids = _ids(package.skills, "skill_id", "skills")
        for item in package.skills:
            context = f"skill {item['skill_id']}"
            if item.get("type") not in {"hard", "soft"}:
                raise ImportValidationError(f"{context}: invalid type")
            for field in ("name", "category", "description"):
                _require(item, field, context)
    if package.events is not None:
        event_ids = _ids(package.events, "event_id", "events")
        for event in package.events:
            context = f"event {event['event_id']}"
            if event.get("format") not in {"online", "offline", "self_paced"}:
                raise ImportValidationError(f"{context}: invalid format")
            if not isinstance(event.get("mandatory"), bool):
                raise ImportValidationError(f"{context}: mandatory must be boolean")
            if not isinstance(event.get("duration_hours"), (int, float)) or event["duration_hours"] <= 0:
                raise ImportValidationError(f"{context}: duration_hours must be positive")
            for skill in event.get("develops_skills", []):
                identifier = _require(skill, "skill_id", context)
                if identifier not in skill_ids:
                    raise ImportValidationError(f"{context}: unknown skill '{identifier}'")
                gain = _integer(skill.get("gain"), context, 1, 5)
                maximum = _integer(skill.get("max_level"), context, 0, 5)
                if gain > maximum:
                    raise ImportValidationError(f"{context}: gain cannot exceed max_level")
            for identifier, level in event.get("prerequisites", {}).items():
                if identifier not in skill_ids:
                    raise ImportValidationError(f"{context}: unknown prerequisite '{identifier}'")
                _integer(level, context, 0, 5)
            for session in event.get("upcoming_sessions", []):
                _date(session, context)
    if package.role_profiles is not None:
        combinations = set()
        for profile in package.role_profiles:
            role = _require(profile, "role", "role profile")
            grade = _require(profile, "grade", f"role profile {role}")
            if grade not in GRADES or (role, grade) in combinations:
                raise ImportValidationError(f"role profile {role}: duplicate or invalid grade")
            combinations.add((role, grade))
            required = profile.get("required_skills")
            if not isinstance(required, dict) or not required:
                raise ImportValidationError(f"role profile {role}/{grade}: required_skills must be an object")
            for identifier, level in required.items():
                if identifier not in skill_ids:
                    raise ImportValidationError(f"role profile {role}/{grade}: unknown skill '{identifier}'")
                _integer(level, f"role profile {role}/{grade}", 0, 5)
            for identifier in profile.get("critical_skills", []):
                if identifier not in required:
                    raise ImportValidationError(f"role profile {role}/{grade}: critical skill must be required")

    for index, employee in enumerate(package.employees, start=1):
        context = f"employees[{index}] ({employee['employee_id']})"
        for field in ("full_name", "department", "role", "hire_date", "work_format", "preferred_language", "last_review_date"):
            if not isinstance(_require(employee, field, context), str):
                raise ImportValidationError(f"{context}: {field} must be a string")
        if not isinstance(employee.get("grade"), str) or employee["grade"] not in GRADES:
            raise ImportValidationError(f"{context}: invalid grade")
        if employee.get("work_format") not in {"office", "hybrid", "remote"}:
            raise ImportValidationError(f"{context}: invalid work_format")
        if employee.get("preferred_language") not in {"kk", "ru", "en"}:
            raise ImportValidationError(f"{context}: invalid preferred_language")
        _date(employee["hire_date"], context)
        _date(employee["last_review_date"], context)
        _integer(employee.get("tenure_months"), context, 0, 1000)
        manager_id = employee.get("manager_id")
        if manager_id is not None and (not isinstance(manager_id, str) or manager_id not in employee_ids | (known_employee_ids or set())):
            raise ImportValidationError(f"{context}: unknown manager '{manager_id}'")
        goal = employee.get("career_goal")
        if goal is not None and (not isinstance(goal, dict) or not isinstance(goal.get("target_grade"), str) or goal["target_grade"] not in GRADES or not isinstance(goal.get("target_role"), str) or not goal.get("target_role")):
            raise ImportValidationError(f"{context}: invalid career_goal")
        if (employee["role"], employee["grade"]) not in combinations:
            raise ImportValidationError(f"{context}: unknown role/grade '{employee['role']}/{employee['grade']}'")
        grades = ("Junior", "Middle", "Senior", "Lead")
        target = (goal["target_role"], goal["target_grade"]) if goal else (
            (employee["role"], grades[grades.index(employee["grade"]) + 1]) if employee["grade"] != "Lead" else None
        )
        if target and target not in combinations:
            raise ImportValidationError(f"{context}: career_goal has no requirements for '{target[0]}/{target[1]}'")
        if not isinstance(employee.get("skills"), dict):
            raise ImportValidationError(f"{context}: skills must be an object")
        for identifier, level in employee["skills"].items():
            if identifier not in skill_ids:
                raise ImportValidationError(f"{context}: unknown skill '{identifier}'")
            _integer(level, f"{context}: skills.{identifier}", 0, 5)

    all_employees = employee_ids | (known_employee_ids or set())
    for index, record in enumerate(package.history, start=2):
        context = f"history row {index} ({record['record_id']})"
        if record.get("employee_id") not in all_employees:
            raise ImportValidationError(f"{context}: unknown employee '{record.get('employee_id')}'")
        if record.get("event_id") not in event_ids:
            raise ImportValidationError(f"{context}: unknown event '{record.get('event_id')}'")
        _date(record.get("date", ""), context)
        _date(record.get("due_date", ""), context, optional=True)
        if record.get("status") not in STATUSES:
            raise ImportValidationError(f"{context}: invalid status")
        completion = _integer(record.get("completion_pct"), f"{context}: completion_pct", 0, 100)
        if record["status"] == "completed" and completion != 100:
            raise ImportValidationError(f"{context}: completed requires completion_pct=100")
        if record.get("score"):
            _integer(record["score"], context, 0, 100)
        if record.get("feedback_rating"):
            _integer(record["feedback_rating"], context, 1, 5)
        if record.get("assigned_by") not in {"self", "manager", "hr"}:
            raise ImportValidationError(f"{context}: invalid assigned_by")


def _existing_ids(connection: sqlite3.Connection, table: str, field: str) -> set[str]:
    return {row[0] for row in connection.execute(f"SELECT {field} FROM {table}")}


def _new_records(connection: sqlite3.Connection, table: str, key: str,
                 items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return new records; reject an ID whose original source differs.

    This makes retries idempotent but prevents an import from silently changing
    a profile or participation record already stored in the database.
    """
    result: list[dict[str, Any]] = []
    for item in items:
        stored = connection.execute(
            f"SELECT source_json FROM {table} WHERE {key} = ?", (item[key],)
        ).fetchone()
        serialized = json.dumps(item, sort_keys=True)
        if stored is None:
            result.append(item)
        elif stored["source_json"] != serialized:
            raise ImportValidationError(
                f"{table} already contains {key} '{item[key]}' with different data"
            )
    return result


def _assert_catalog_matches(connection: sqlite3.Connection, package: Package) -> bool:
    """Check whether a full package is a safe retry and return catalog presence."""
    assert package.skills is not None and package.events is not None
    has_catalog = bool(_existing_ids(connection, "skills", "skill_id"))
    if not has_catalog:
        return False
    for table, key, items in (
        ("skills", "skill_id", package.skills),
        ("events", "event_id", package.events),
    ):
        stored = {
            row[key]: row["source_json"]
            for row in connection.execute(f"SELECT {key}, source_json FROM {table}")
        }
        incoming = {item[key]: json.dumps(item, sort_keys=True) for item in items}
        if stored != incoming:
            raise ImportValidationError(
                f"Existing {table} catalog differs from the supplied starter kit"
            )
    assert package.role_profiles is not None
    incoming_profiles = {
        (profile["role"], profile["grade"]): profile for profile in package.role_profiles
    }
    stored_profiles = {
        (row["role"], row["grade"])
        for row in connection.execute("SELECT role, grade FROM role_profiles")
    }
    if set(incoming_profiles) != stored_profiles:
        raise ImportValidationError("Existing role profile catalog differs from the supplied starter kit")
    for identity, profile in incoming_profiles.items():
        required = {
            row["skill_id"]: row["required_level"]
            for row in connection.execute(
                "SELECT skill_id, required_level FROM role_requirements WHERE role = ? AND grade = ?",
                identity,
            )
        }
        critical = {
            row["skill_id"]
            for row in connection.execute(
                "SELECT skill_id FROM role_critical_skills WHERE role = ? AND grade = ?",
                identity,
            )
        }
        if required != profile["required_skills"] or critical != set(profile.get("critical_skills", [])):
            raise ImportValidationError("Existing role profile catalog differs from the supplied starter kit")
    return True


def _insert_catalog(connection: sqlite3.Connection, package: Package) -> None:
    assert package.skills is not None and package.role_profiles is not None and package.events is not None
    for skill in package.skills:
        connection.execute(
            "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?)",
            (skill["skill_id"], skill["name"], skill["type"], skill["category"], skill["description"], json.dumps(skill, sort_keys=True)),
        )
    for profile in package.role_profiles:
        connection.execute("INSERT INTO role_profiles VALUES (?, ?)", (profile["role"], profile["grade"]))
        for skill_id, level in profile["required_skills"].items():
            connection.execute("INSERT INTO role_requirements VALUES (?, ?, ?, ?)", (profile["role"], profile["grade"], skill_id, level))
        for skill_id in profile.get("critical_skills", []):
            connection.execute("INSERT INTO role_critical_skills VALUES (?, ?, ?)", (profile["role"], profile["grade"], skill_id))
    for event in package.events:
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event["event_id"], event["title"], event["description"], event["type"], event["format"], event["duration_hours"], int(event["mandatory"]), json.dumps(event, sort_keys=True)),
        )
        connection.executemany("INSERT INTO event_target_roles VALUES (?, ?)", [(event["event_id"], role) for role in event["target_roles"]])
        connection.executemany("INSERT INTO event_target_grades VALUES (?, ?)", [(event["event_id"], grade) for grade in event["target_grades"]])
        connection.executemany("INSERT INTO event_develops_skills VALUES (?, ?, ?, ?)", [(event["event_id"], item["skill_id"], item["gain"], item["max_level"]) for item in event["develops_skills"]])
        connection.executemany("INSERT INTO event_prerequisites VALUES (?, ?, ?)", [(event["event_id"], skill_id, level) for skill_id, level in event["prerequisites"].items()])
        connection.executemany("INSERT INTO event_sessions VALUES (?, ?)", [(event["event_id"], session) for session in event["upcoming_sessions"]])


def _insert_employees(connection: sqlite3.Connection, employees: list[dict[str, Any]]) -> None:
    # Insert managers in a second pass because the relationship is self-referential.
    for employee in employees:
        goal = employee.get("career_goal") or {}
        connection.execute(
            "INSERT INTO employees VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
            (employee["employee_id"], employee["full_name"], employee["department"], employee["role"], employee["grade"], employee["hire_date"], employee["tenure_months"], employee["work_format"], employee["preferred_language"], goal.get("target_role"), goal.get("target_grade"), employee["last_review_date"], json.dumps(employee, sort_keys=True)),
        )
        connection.executemany("INSERT INTO employee_skills VALUES (?, ?, ?)", [(employee["employee_id"], skill_id, level) for skill_id, level in employee["skills"].items()])
    for employee in employees:
        if employee.get("manager_id") is not None:
            connection.execute("UPDATE employees SET manager_id = ? WHERE employee_id = ?", (employee["manager_id"], employee["employee_id"]))


def _insert_history(connection: sqlite3.Connection, history: list[dict[str, str]]) -> None:
    for record in history:
        connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["record_id"], record["employee_id"], record["event_id"], record["date"], record["due_date"] or None, record["status"], int(record["completion_pct"]), int(record["score"]) if record["score"] else None, int(record["feedback_rating"]) if record["feedback_rating"] else None, record["assigned_by"], json.dumps(record, sort_keys=True)),
        )


def preview_package(connection: sqlite3.Connection, package: Package, kind: str = "profiles") -> dict[str, Any]:
    """Validate conflicts and references without changing the database."""
    known_skills = _existing_ids(connection, "skills", "skill_id") or None
    known_events = _existing_ids(connection, "events", "event_id") or None
    known_employees = _existing_ids(connection, "employees", "employee_id") or None
    if kind == "profiles" and (not known_skills or not known_events):
        raise ImportValidationError("Import the starter-kit catalog before importing profiles")
    known_roles = {tuple(row) for row in connection.execute("SELECT role, grade FROM role_profiles")}
    validate(package, known_skills, known_events, known_employees, known_roles)
    if kind == "full":
        _assert_catalog_matches(connection, package)
    new_employees = _new_records(connection, "employees", "employee_id", package.employees)
    new_history = _new_records(connection, "activity_history", "record_id", package.history)
    new_ids = {item["employee_id"] for item in new_employees}
    return {
        "employees_imported": len(new_employees),
        "history_records_imported": len(new_history),
        "employees_skipped": len(package.employees) - len(new_employees),
        "history_records_skipped": len(package.history) - len(new_history),
        "profiles": [{"employee_id": item["employee_id"], "full_name": item["full_name"],
                      "role": item["role"], "grade": item["grade"], "is_new": item["employee_id"] in new_ids}
                     for item in package.employees],
    }


def import_package(connection: sqlite3.Connection, package: Package, kind: str, source_description: str) -> dict[str, Any]:
    """Validate and recheck conflicts inside the transaction used for the import."""
    migrate(connection)
    with connection:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        summary = preview_package(connection, package, kind)
        if kind == "full":
            catalog_exists = _assert_catalog_matches(connection, package)
            if not catalog_exists:
                _insert_catalog(connection, package)
        new_employees = _new_records(connection, "employees", "employee_id", package.employees)
        new_history = _new_records(connection, "activity_history", "record_id", package.history)
        _insert_employees(connection, new_employees)
        _insert_history(connection, new_history)
        connection.execute("INSERT INTO import_batches(kind, source_description) VALUES (?, ?)", (kind, source_description))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Career Quest data")
    subcommands = parser.add_subparsers(dest="command", required=True)
    full = subcommands.add_parser("full", help="Import the four starter-kit files")
    full.add_argument("--dataset-dir", required=True)
    profiles = subcommands.add_parser("profiles", help="Import jury employees and history")
    profiles.add_argument("--employees", required=True)
    profiles.add_argument("--history", required=True)
    for command in (full, profiles):
        command.add_argument("--database", required=True)
    args = parser.parse_args()
    package = load_full_package(args.dataset_dir) if args.command == "full" else load_profile_package(args.employees, args.history)
    connection = connect(args.database)
    try:
        import_package(connection, package, args.command, args.dataset_dir if args.command == "full" else f"{args.employees}, {args.history}")
    except ImportValidationError as error:
        parser.exit(2, f"Import failed: {error}\n")
    finally:
        connection.close()
    print(f"Imported {len(package.employees)} employees and {len(package.history)} history records.")


if __name__ == "__main__":
    main()
