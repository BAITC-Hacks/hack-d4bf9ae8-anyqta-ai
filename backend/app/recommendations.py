"""Explainable development-event recommendations with an optional LLM selector."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from .career import CareerCalculationError, calculate_trajectory
from .db import connect, migrate


DEFAULT_AS_OF_DATE = "2026-10-01"


class RecommendationError(ValueError):
    """The database or an optional model response cannot yield recommendations."""


class LlmSelector(Protocol):
    def select(self, facts: dict[str, Any]) -> dict[str, Any]:
        """Return {'recommendations': [{'event_id': 'EV_001'}, ...]} only."""


@dataclass(frozen=True)
class Candidate:
    event_id: str
    title: str
    event_type: str
    event_format: str
    duration_hours: float
    next_session: str | None
    score: float
    critical_gap_reduction: int
    total_gap_reduction: int
    skill_changes: list[dict[str, Any]]
    completed_similar: int
    negative_similar: int
    negative_same_format: int


class OpenAICompatibleSelector:
    """Small standard-library client for an OpenAI-compatible chat endpoint.

    It receives only pseudonymous calculation facts and may select event IDs from
    the provided candidates. The server validates every returned ID before use.
    """

    def __init__(self, url: str, api_key: str, model: str, timeout_seconds: float = 8.0):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def select(self, facts: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Choose up to three development events only from candidates. Prioritize "
            "critical skill gaps, expected gap reduction and engagement history. "
            "Return JSON only: {\"recommendations\":[{\"event_id\":\"EV_001\"}]}.\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        request = urllib.request.Request(
            self.url,
            data=json.dumps(
                {
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "You are a careful career-development event selector."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                }
            ).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RecommendationError(f"LLM request failed: {error}") from error


def _as_of(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise RecommendationError(f"Invalid as-of date '{value}'") from error
    return value


def _history_signals(connection: sqlite3.Connection, employee_id: str, event_type: str,
                     event_format: str) -> tuple[int, int, int]:
    row = connection.execute(
        """
        SELECT
          SUM(CASE WHEN history.status = 'completed' THEN 1 ELSE 0 END) AS completed_similar,
          SUM(CASE WHEN history.status IN ('dropped', 'no_show', 'declined') THEN 1 ELSE 0 END) AS negative_similar,
          SUM(CASE WHEN history.status IN ('dropped', 'no_show', 'declined')
                    AND events.format = ? THEN 1 ELSE 0 END) AS negative_same_format
        FROM activity_history AS history
        JOIN events ON events.event_id = history.event_id
        WHERE history.employee_id = ? AND events.type = ?
        """,
        (event_format, employee_id, event_type),
    ).fetchone()
    return tuple(int(row[key] or 0) for key in ("completed_similar", "negative_similar", "negative_same_format"))


def _has_history_status(connection: sqlite3.Connection, employee_id: str, event_id: str,
                        statuses: tuple[str, ...]) -> bool:
    placeholders = ", ".join("?" for _ in statuses)
    row = connection.execute(
        f"SELECT 1 FROM activity_history WHERE employee_id = ? AND event_id = ? AND status IN ({placeholders}) LIMIT 1",
        (employee_id, event_id, *statuses),
    ).fetchone()
    return row is not None


def _is_targeted(connection: sqlite3.Connection, event_id: str, role: str, grade: str) -> bool:
    return connection.execute(
        """
        SELECT 1
        FROM event_target_roles AS roles
        JOIN event_target_grades AS grades ON grades.event_id = roles.event_id
        WHERE roles.event_id = ? AND roles.role = ? AND grades.grade = ?
        """,
        (event_id, role, grade),
    ).fetchone() is not None


def _prerequisites_met(connection: sqlite3.Connection, event_id: str,
                       skills: dict[str, int]) -> bool:
    requirements = connection.execute(
        "SELECT skill_id, minimum_level FROM event_prerequisites WHERE event_id = ?",
        (event_id,),
    )
    return all(skills.get(item["skill_id"], 0) >= item["minimum_level"] for item in requirements)


def _event_changes(connection: sqlite3.Connection, event_id: str, skills: dict[str, int],
                   gaps: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    changes: list[dict[str, Any]] = []
    critical_reduction = 0
    total_reduction = 0
    for development in connection.execute(
        """
        SELECT develops.skill_id, develops.gain, develops.max_level, skills.name
        FROM event_develops_skills AS develops
        JOIN skills ON skills.skill_id = develops.skill_id
        WHERE develops.event_id = ? ORDER BY develops.skill_id
        """,
        (event_id,),
    ):
        before = skills.get(development["skill_id"], 0)
        after = max(before, min(5, development["max_level"], before + development["gain"]))
        gap = gaps.get(development["skill_id"])
        reduction = min(max(0, (gap["required_level"] if gap else 0) - before), after - before)
        if reduction:
            total_reduction += reduction
            if gap and gap["is_critical"]:
                critical_reduction += reduction
        changes.append(
            {
                "skill_id": development["skill_id"],
                "skill_name": development["name"],
                "before_level": before,
                "after_level": after,
                "gain": development["gain"],
                "max_level": development["max_level"],
                "target_gap_reduction": reduction,
                "is_critical": bool(gap and gap["is_critical"]),
                "required_level": gap["required_level"] if gap else None,
            }
        )
    return changes, critical_reduction, total_reduction


def eligible_candidates(connection: sqlite3.Connection, employee_id: str,
                        as_of_date: str = DEFAULT_AS_OF_DATE) -> list[Candidate]:
    """Filter unsafe events and score only useful, accessible voluntary actions."""
    as_of_date = _as_of(as_of_date)
    trajectory = calculate_trajectory(connection, employee_id)
    if trajectory["trajectory_status"] != "ready":
        return []
    employee = trajectory["employee"]
    gaps = {item["skill_id"]: item for item in trajectory["skill_gaps"]}
    skills = trajectory["effective_skills"]
    candidates: list[Candidate] = []
    for event in connection.execute(
        "SELECT event_id, title, type, format AS event_format, duration_hours, mandatory FROM events ORDER BY event_id"
    ):
        if event["mandatory"]:
            continue
        if not _is_targeted(connection, event["event_id"], employee["role"], employee["grade"]):
            continue
        if not _prerequisites_met(connection, event["event_id"], skills):
            continue
        # The starter-kit README explicitly allows the regular EV_036 club to
        # repeat after completion. An active enrollment always remains blocked.
        blocked_statuses = ("in_progress",) if event["event_id"] == "EV_036" else ("completed", "in_progress")
        if _has_history_status(connection, employee_id, event["event_id"], blocked_statuses):
            continue
        next_session = connection.execute(
            "SELECT MIN(session_date) FROM event_sessions WHERE event_id = ? AND session_date >= ?",
            (event["event_id"], as_of_date),
        ).fetchone()[0]
        has_self_paced = event["event_format"] == "self_paced"
        if not has_self_paced and next_session is None:
            continue
        changes, critical_reduction, total_reduction = _event_changes(
            connection, event["event_id"], skills, gaps
        )
        if total_reduction == 0:
            continue
        completed, negative, negative_format = _history_signals(
            connection, employee_id, event["type"], event["event_format"]
        )
        # The score ranks candidates only. The UI receives the factors below,
        # not an opaque claim that a score predicts a person's motivation.
        score = (
            critical_reduction * 10
            + total_reduction * 4
            + min(completed, 3) * 0.5
            - negative * 1.5
            - negative_format * 0.5
            - event["duration_hours"] * 0.03
        )
        candidates.append(
            Candidate(
                event_id=event["event_id"],
                title=event["title"],
                event_type=event["type"],
                event_format=event["event_format"],
                duration_hours=event["duration_hours"],
                next_session=next_session,
                score=round(score, 3),
                critical_gap_reduction=critical_reduction,
                total_gap_reduction=total_reduction,
                skill_changes=changes,
                completed_similar=completed,
                negative_similar=negative,
                negative_same_format=negative_format,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.duration_hours, item.event_id))


def _facts_for_selector(trajectory: dict[str, Any], candidates: list[Candidate]) -> dict[str, Any]:
    return {
        "target": trajectory["target"],
        "skill_gaps": [item for item in trajectory["skill_gaps"] if item["gap"] > 0],
        "candidates": [
            {
                "event_id": item.event_id,
                "critical_gap_reduction": item.critical_gap_reduction,
                "total_gap_reduction": item.total_gap_reduction,
                "duration_hours": item.duration_hours,
                "completed_similar": item.completed_similar,
                "negative_similar": item.negative_similar,
                "negative_same_format": item.negative_same_format,
            }
            for item in candidates
        ],
    }


def _validated_selection(payload: dict[str, Any], candidates: list[Candidate], limit: int) -> list[Candidate]:
    selected = payload.get("recommendations") if isinstance(payload, dict) else None
    if not isinstance(selected, list) or not 1 <= len(selected) <= limit:
        raise RecommendationError("LLM response must contain between one and three recommendations")
    by_id = {item.event_id: item for item in candidates}
    result: list[Candidate] = []
    for item in selected:
        event_id = item.get("event_id") if isinstance(item, dict) else None
        if not isinstance(event_id, str) or event_id not in by_id or any(existing.event_id == event_id for existing in result):
            raise RecommendationError("LLM response selected an unknown or duplicate event")
        result.append(by_id[event_id])
    return result


def _explanation(candidate: Candidate) -> list[str]:
    evidence: list[str] = []
    for change in candidate.skill_changes:
        if change["target_gap_reduction"]:
            critical = "критический " if change["is_critical"] else ""
            evidence.append(
                f"Развивает {critical}навык {change['skill_name']}: "
                f"{change['before_level']} → {change['after_level']} "
                f"при требовании {change['required_level']}."
            )
    if candidate.negative_similar:
        evidence.append(
            f"В истории есть {candidate.negative_similar} незавершённых или пропущенных "
            f"активностей этого типа; это учтено при подборе формата."
        )
    elif candidate.completed_similar:
        evidence.append(
            f"В истории есть {candidate.completed_similar} завершённых активностей этого типа."
        )
    else:
        evidence.append("Подходит по аудитории и prerequisites, и ещё не завершено.")
    return evidence


def recommend_employee(connection: sqlite3.Connection, employee_id: str, limit: int = 3,
                       as_of_date: str = DEFAULT_AS_OF_DATE,
                       selector: LlmSelector | None = None,
                       timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Return one to three recommendations or an explainable no-result state."""
    if not 1 <= limit <= 3:
        raise RecommendationError("limit must be between 1 and 3")
    trajectory = calculate_trajectory(connection, employee_id)
    candidates = eligible_candidates(connection, employee_id, as_of_date)
    if not candidates:
        return {
            "employee_id": employee_id,
            "mode": "rules_fallback",
            "fallback_reason": "No eligible voluntary events can reduce the current target gaps.",
            "recommendations": [],
        }
    rules_selection = candidates[:limit]
    selected = rules_selection
    mode = "rules_fallback"
    fallback_reason = "LLM selector is not configured."
    if selector is not None:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(selector.select, _facts_for_selector(trajectory, candidates))
            selected = _validated_selection(future.result(timeout=timeout_seconds), candidates, limit)
            mode = "llm"
            fallback_reason = None
        except Exception as error:
            # The broad catch protects the employee journey from provider-specific
            # failures. It deliberately returns only verified rule candidates.
            selected = rules_selection
            fallback_reason = f"LLM selector unavailable or invalid: {error}"
        finally:
            # Do not wait for a provider that ignored the deadline. HTTP clients
            # used here also enforce their own timeout; this protects callers of
            # custom selectors in tests and future integrations.
            executor.shutdown(wait=False, cancel_futures=True)
    return {
        "employee_id": employee_id,
        "mode": mode,
        "fallback_reason": fallback_reason,
        "recommendations": [
            {
                "event_id": candidate.event_id,
                "title": candidate.title,
                "type": candidate.event_type,
                "format": candidate.event_format,
                "duration_hours": candidate.duration_hours,
                "next_session": candidate.next_session,
                "expected_skill_changes": candidate.skill_changes,
                "evidence": _explanation(candidate),
            }
            for candidate in selected
        ],
    }


def selector_from_environment() -> LlmSelector | None:
    url = os.getenv("LLM_API_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not any((url, api_key, model)):
        return None
    if not all((url, api_key, model)):
        raise RecommendationError("Set LLM_API_URL, LLM_API_KEY and LLM_MODEL together")
    return OpenAICompatibleSelector(url, api_key, model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend Career Quest development events")
    parser.add_argument("--database", required=True)
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--as-of-date", default=DEFAULT_AS_OF_DATE)
    parser.add_argument("--limit", default=3, type=int)
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        result = recommend_employee(
            connection, args.employee_id, args.limit, args.as_of_date, selector_from_environment()
        )
    except (CareerCalculationError, RecommendationError) as error:
        parser.exit(2, f"Recommendation failed: {error}\n")
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
