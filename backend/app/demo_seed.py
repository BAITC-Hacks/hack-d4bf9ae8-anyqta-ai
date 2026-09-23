"""Idempotently create five documented accounts for the Career Quest demo."""

from __future__ import annotations

import argparse
import sqlite3

from .auth import AuthenticationError, authenticate, create_user
from .db import connect, migrate


EMPLOYEE_PASSWORD = "DemoEmployee2026!"
HR_PASSWORD = "DemoHR2026!"

DEMO_USERS = (
    ("junior@careerquest.demo", "employee", "E0001"),
    ("middle@careerquest.demo", "employee", "E0002"),
    ("senior@careerquest.demo", "employee", "E0007"),
    ("lead@careerquest.demo", "employee", "E0014"),
    ("hr@careerquest.demo", "hr", None),
)


def _ensure_user(connection: sqlite3.Connection, username: str, role: str,
                 employee_id: str | None, password: str) -> None:
    row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        create_user(connection, username, password, role, employee_id, is_demo=True)
        return
    if (
        row["access_role"] != role
        or row["employee_id"] != employee_id
        or not row["is_demo"]
        or not authenticate(connection, username, password)
    ):
        raise AuthenticationError(f"Existing account '{username}' conflicts with the demo seed")


def seed_demo_users(connection: sqlite3.Connection) -> None:
    """Create demo users once; never overwrite an existing user or password."""
    migrate(connection)
    employee_count = connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if employee_count == 0:
        raise AuthenticationError("Import the starter kit before creating demo users")
    with connection:
        for username, role, employee_id in DEMO_USERS:
            password = EMPLOYEE_PASSWORD if role == "employee" else HR_PASSWORD
            _ensure_user(connection, username, role, employee_id, password)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Career Quest demo users")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        seed_demo_users(connection)
    except AuthenticationError as error:
        parser.exit(2, f"Demo seed failed: {error}\n")
    finally:
        connection.close()
    print("Created or verified 4 employee accounts and 1 HR account.")


if __name__ == "__main__":
    main()
