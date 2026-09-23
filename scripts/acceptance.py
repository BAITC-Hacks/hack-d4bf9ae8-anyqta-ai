#!/usr/bin/env python3
"""Repeatable local acceptance check for the Career Quest jury demo."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.activities import ActivityError  # noqa: E402
from backend.app.auth import authenticate  # noqa: E402
from backend.app.bootstrap import bootstrap  # noqa: E402
from backend.app.db import connect  # noqa: E402
from backend.app.demo_seed import DEMO_USERS, EMPLOYEE_PASSWORD, HR_PASSWORD  # noqa: E402
from backend.app.web import WebApplication  # noqa: E402


DATASET = ROOT / "data" / "career_quest_dataset"
SESSION_SECRET = "acceptance-session-secret-that-is-longer-than-32-characters"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_acceptance() -> dict[str, object]:
    """Run the essential jury scenario against a fresh temporary database."""
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "career_quest.db"
        imported = bootstrap(database, DATASET)
        require(imported, "A clean database must import the starter kit")
        connection = connect(database)
        try:
            counts = {
                "employees": connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
                "skills": connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
                "events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "history_records": connection.execute("SELECT COUNT(*) FROM activity_history").fetchone()[0],
                "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            }
            require(counts == {"employees": 200, "skills": 60, "events": 40, "history_records": 2743, "users": 5}, "Unexpected starter-kit counts")
            for username, role, employee_id in DEMO_USERS:
                password = EMPLOYEE_PASSWORD if role == "employee" else HR_PASSWORD
                user = authenticate(connection, username, password)
                require(user.access_role == role and user.employee_id == employee_id, f"Demo account failed: {username}")
        finally:
            connection.close()

        application = WebApplication(database, SESSION_SECRET, demo_mode=True)
        employee, _ = application.login("junior@careerquest.demo", EMPLOYEE_PASSWORD)
        start = time.perf_counter()
        dashboard = application.employee_dashboard(employee)
        dashboard_seconds = time.perf_counter() - start
        require(dashboard_seconds < 2, f"Employee dashboard exceeded 2 seconds: {dashboard_seconds:.3f}")
        require(dashboard["trajectory"]["employee"]["employee_id"] == "E0001", "Employee isolation failed")
        require(dashboard["recommendations"], "Junior demo user needs recommendations")

        enrollment = application.enroll(employee, "EV_005")["enrollment"]
        completion = application.complete_demo_enrollment(employee, enrollment["enrollment_id"])
        require(completion["coverage_after"] > completion["coverage_before"], "Completion must improve coverage")
        try:
            application.complete_demo_enrollment(employee, enrollment["enrollment_id"])
        except ActivityError:
            pass
        else:
            raise AssertionError("Repeated completion must be rejected")

        hr, _ = application.login("hr@careerquest.demo", HR_PASSWORD)
        start = time.perf_counter()
        overview = application.hr_overview(hr, {"grade": "Junior"})
        hr_seconds = time.perf_counter() - start
        require(hr_seconds < 2, f"HR dashboard exceeded 2 seconds: {hr_seconds:.3f}")
        require(overview["summary"]["employees"] > 0, "HR filter returned no Junior employees")
        require(overview["competency_gaps"], "HR dashboard lacks competency gaps")

        return {
            "result": "passed",
            "dataset_counts": counts,
            "employee_dashboard_seconds": round(dashboard_seconds, 4),
            "hr_dashboard_seconds": round(hr_seconds, 4),
            "recommendation_mode": dashboard["recommendation_mode"],
            "checked": [
                "bootstrap", "five_demo_accounts", "employee_isolation",
                "recommendations", "activity_completion_idempotency", "hr_dashboard",
            ],
        }


if __name__ == "__main__":
    try:
        print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
    except (AssertionError, Exception) as error:
        print(f"Acceptance failed: {error}", file=sys.stderr)
        raise SystemExit(1)
