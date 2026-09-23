"""Enrollment and demo-completion workflow for voluntary development events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date
from typing import Any

from .career import calculate_trajectory
from .recommendations import DEFAULT_AS_OF_DATE, RecommendationError, eligible_candidates


class ActivityError(ValueError):
    """An activity cannot be enrolled or completed in its current state."""


def _valid_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ActivityError("completion_date must be an ISO date") from error
    return value


def _active_enrollment(connection: sqlite3.Connection, employee_id: str,
                       event_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT enrollments.enrollment_id, enrollments.employee_id, enrollments.event_id,
               enrollments.history_record_id, enrollments.status, enrollments.registered_at,
               events.title
        FROM activity_enrollments AS enrollments
        JOIN events ON events.event_id = enrollments.event_id
        WHERE enrollments.employee_id = ? AND enrollments.event_id = ?
          AND enrollments.status = 'registered'
        """,
        (employee_id, event_id),
    ).fetchone()


def active_enrollments(connection: sqlite3.Connection, employee_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT enrollments.enrollment_id, enrollments.event_id, enrollments.registered_at,
               events.title, events.format, events.duration_hours
        FROM activity_enrollments AS enrollments
        JOIN events ON events.event_id = enrollments.event_id
        WHERE enrollments.employee_id = ? AND enrollments.status = 'registered'
        ORDER BY enrollments.registered_at, enrollments.enrollment_id
        """,
        (employee_id,),
    )
    return [dict(row) for row in rows]


def enroll_activity(connection: sqlite3.Connection, employee_id: str, event_id: str,
                    activity_date: str = DEFAULT_AS_OF_DATE) -> dict[str, Any]:
    """Enroll an employee in an eligible event and record an in-progress history row.

    The current recommendation filter is reused as the authority, so a client
    cannot enroll in mandatory, already completed, inaccessible or unhelpful
    activities by calling the endpoint directly.
    """
    activity_date = _valid_date(activity_date)
    existing = _active_enrollment(connection, employee_id, event_id)
    if existing is not None:
        return {"enrollment": dict(existing), "created": False}
    try:
        candidate = next(
            item for item in eligible_candidates(connection, employee_id, activity_date)
            if item.event_id == event_id
        )
    except StopIteration as error:
        raise ActivityError("This activity is not currently available for enrollment") from error
    except RecommendationError as error:
        raise ActivityError(str(error)) from error

    enrollment_id = f"enr_{uuid.uuid4().hex}"
    record_id = f"R_APP_{uuid.uuid4().hex}"
    source = {
        "record_id": record_id,
        "employee_id": employee_id,
        "event_id": event_id,
        "date": activity_date,
        "due_date": "",
        "status": "in_progress",
        "completion_pct": "0",
        "score": "",
        "feedback_rating": "",
        "assigned_by": "self",
        "origin": "career_quest_app",
    }
    with connection:
        # A repeated browser request returns the active enrollment rather than
        # creating a second history record.
        existing = _active_enrollment(connection, employee_id, event_id)
        if existing is not None:
            return {"enrollment": dict(existing), "created": False}
        connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record_id, employee_id, event_id, activity_date, None, "in_progress", 0, None, None, "self", json.dumps(source, sort_keys=True)),
        )
        connection.execute(
            """
            INSERT INTO activity_enrollments(enrollment_id, employee_id, event_id, history_record_id, status, registered_at)
            VALUES (?, ?, ?, ?, 'registered', ?)
            """,
            (enrollment_id, employee_id, event_id, record_id, activity_date),
        )
    return {
        "created": True,
        "enrollment": {
            "enrollment_id": enrollment_id,
            "employee_id": employee_id,
            "event_id": event_id,
            "history_record_id": record_id,
            "title": candidate.title,
            "status": "registered",
            "registered_at": activity_date,
        },
    }


def complete_activity(connection: sqlite3.Connection, employee_id: str, enrollment_id: str,
                      completion_date: str = DEFAULT_AS_OF_DATE) -> dict[str, Any]:
    """Complete an active enrollment exactly once and return its calculated effect."""
    completion_date = _valid_date(completion_date)
    enrollment = connection.execute(
        """
        SELECT enrollment_id, employee_id, event_id, history_record_id, status, registered_at
        FROM activity_enrollments WHERE enrollment_id = ? AND employee_id = ?
        """,
        (enrollment_id, employee_id),
    ).fetchone()
    if enrollment is None:
        raise ActivityError("Active enrollment not found")
    if enrollment["status"] != "registered":
        raise ActivityError("This activity has already been completed")
    if completion_date < enrollment["registered_at"]:
        raise ActivityError("completion_date cannot be before registration")
    before = calculate_trajectory(connection, employee_id)
    source = {
        "record_id": enrollment["history_record_id"],
        "employee_id": employee_id,
        "event_id": enrollment["event_id"],
        "date": completion_date,
        "due_date": "",
        "status": "completed",
        "completion_pct": "100",
        "score": "",
        "feedback_rating": "",
        "assigned_by": "self",
        "origin": "career_quest_app",
    }
    with connection:
        updated = connection.execute(
            """
            UPDATE activity_enrollments SET status = 'completed', completed_at = ?
            WHERE enrollment_id = ? AND employee_id = ? AND status = 'registered'
            """,
            (completion_date, enrollment_id, employee_id),
        ).rowcount
        if updated != 1:
            raise ActivityError("This activity has already been completed")
        connection.execute(
            """
            UPDATE activity_history
            SET activity_date = ?, status = 'completed', completion_pct = 100, source_json = ?
            WHERE record_id = ?
            """,
            (completion_date, json.dumps(source, sort_keys=True), enrollment["history_record_id"]),
        )
    after = calculate_trajectory(connection, employee_id)
    changes = [
        item for item in after["applied_skill_changes"]
        if item["record_id"] == enrollment["history_record_id"]
    ]
    return {
        "enrollment_id": enrollment_id,
        "event_id": enrollment["event_id"],
        "completed_at": completion_date,
        "skill_changes": changes,
        "coverage_before": before["coverage_percent"],
        "coverage_after": after["coverage_percent"],
    }
