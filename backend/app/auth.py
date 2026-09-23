"""Authentication, signed sessions and server-side access rules."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any


PBKDF2_ITERATIONS = 310_000
ACCESS_ROLES = {"employee", "hr"}


class AuthenticationError(ValueError):
    """Credentials are invalid or a session cannot be trusted."""


class AuthorizationError(PermissionError):
    """The authenticated user cannot access the requested resource."""


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    access_role: str
    employee_id: str | None
    is_demo: bool


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """Create a salted PBKDF2-SHA256 password hash; never store raw passwords."""
    if not isinstance(password, str) or len(password) < 10:
        raise AuthenticationError("Password must contain at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(actual, _b64decode(expected))
    except (TypeError, ValueError, UnicodeError):
        return False


def _normalised_username(username: str) -> str:
    if not isinstance(username, str):
        raise AuthenticationError("Username is required")
    value = username.strip().lower()
    if not value or len(value) > 254:
        raise AuthenticationError("Username is invalid")
    return value


def _to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        access_role=row["access_role"],
        employee_id=row["employee_id"],
        is_demo=bool(row["is_demo"]),
    )


def create_user(connection: sqlite3.Connection, username: str, password: str,
                access_role: str, employee_id: str | None = None,
                is_demo: bool = False) -> User:
    """Create a user after enforcing role/profile separation in the database."""
    username = _normalised_username(username)
    if access_role not in ACCESS_ROLES:
        raise AuthenticationError("Unknown access role")
    if access_role == "employee" and not employee_id:
        raise AuthenticationError("An employee account requires employee_id")
    if access_role == "hr" and employee_id is not None:
        raise AuthenticationError("An HR account must not be bound to an employee profile")
    if employee_id and connection.execute(
        "SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone() is None:
        raise AuthenticationError(f"Employee '{employee_id}' does not exist")
    try:
        connection.execute(
            """
            INSERT INTO users(user_id, username, password_hash, access_role, employee_id, is_demo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"usr_{uuid.uuid4().hex}", username, hash_password(password), access_role, employee_id, int(is_demo)),
        )
    except sqlite3.IntegrityError as error:
        raise AuthenticationError("Username or employee account already exists") from error
    row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _to_user(row)


def authenticate(connection: sqlite3.Connection, username: str, password: str) -> User:
    """Authenticate with a generic failure message to avoid account enumeration."""
    try:
        username = _normalised_username(username)
    except AuthenticationError as error:
        raise AuthenticationError("Invalid username or password") from error
    row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise AuthenticationError("Invalid username or password")
    return _to_user(row)


def can_access_employee(user: User, employee_id: str) -> bool:
    """HR can access employee records; employees can access their own record only."""
    return user.access_role == "hr" or (
        user.access_role == "employee" and user.employee_id == employee_id
    )


def require_employee_access(user: User, employee_id: str) -> None:
    if not can_access_employee(user, employee_id):
        raise AuthorizationError("You do not have access to this employee profile")


def issue_session(user: User, secret: str, ttl_seconds: int = 28_800,
                  now: int | None = None) -> str:
    """Issue an HMAC-signed, expiring session token for the future web API."""
    if not secret or len(secret) < 32:
        raise AuthenticationError("Session secret must contain at least 32 characters")
    if ttl_seconds <= 0:
        raise AuthenticationError("Session TTL must be positive")
    issued_at = int(time.time()) if now is None else now
    payload = {
        "sub": user.user_id,
        "role": user.access_role,
        "employee_id": user.employee_id,
        "exp": issued_at + ttl_seconds,
    }
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def read_session(token: str, secret: str, now: int | None = None) -> dict[str, Any]:
    """Validate a signed session token and return claims safe for authorization."""
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise AuthenticationError("Invalid session")
        payload = json.loads(_b64decode(encoded_payload))
        if payload.get("role") not in ACCESS_ROLES or not isinstance(payload.get("sub"), str):
            raise AuthenticationError("Invalid session")
        current_time = int(time.time()) if now is None else now
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
            raise AuthenticationError("Session expired")
        return payload
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
        if isinstance(error, AuthenticationError):
            raise
        raise AuthenticationError("Invalid session") from error
