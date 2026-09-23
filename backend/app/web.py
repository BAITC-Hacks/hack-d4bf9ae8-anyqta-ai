"""Local web server for the Career Quest employee cabinet."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sqlite3
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .activities import ActivityError, active_enrollments, complete_activity, enroll_activity, reset_demo_employee
from .auth import AuthenticationError, User, authenticate, issue_session, read_session
from .career import CareerCalculationError, calculate_trajectory, goal_options, set_goal
from .db import connect, migrate
from .hr import HrError, hr_dashboard, hr_employee_detail, import_hr_profile_package
from .recommendations import RecommendationError
from .recommendation_service import RecommendationService


STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 10_000


class WebApplication:
    """Request-independent operations used by HTTP handlers and tests."""

    def __init__(self, database_path: str | Path, session_secret: str, demo_mode: bool = True,
                 recommendation_service: RecommendationService | None = None):
        if len(session_secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        self.database_path = str(database_path)
        self.session_secret = session_secret
        self.demo_mode = demo_mode
        self.recommendation_service = recommendation_service or RecommendationService()
        connection = connect(self.database_path)
        try:
            migrate(connection)
        finally:
            connection.close()

    def _connection(self) -> sqlite3.Connection:
        return connect(self.database_path)

    def login(self, username: str, password: str) -> tuple[User, str]:
        connection = self._connection()
        try:
            user = authenticate(connection, username, password)
            return user, issue_session(user, self.session_secret)
        finally:
            connection.close()

    def user_from_token(self, token: str) -> User:
        claims = read_session(token, self.session_secret)
        connection = self._connection()
        try:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (claims["sub"],)).fetchone()
            if row is None:
                raise AuthenticationError("Invalid session")
            user = User(
                user_id=row["user_id"], username=row["username"], access_role=row["access_role"],
                employee_id=row["employee_id"], is_demo=bool(row["is_demo"]),
            )
            if user.access_role != claims["role"] or user.employee_id != claims["employee_id"]:
                raise AuthenticationError("Invalid session")
            return user
        finally:
            connection.close()

    def employee_dashboard(self, user: User) -> dict[str, Any]:
        if user.access_role != "employee" or user.employee_id is None:
            raise PermissionError("The employee cabinet is available to employee accounts only")
        connection = self._connection()
        try:
            trajectory = calculate_trajectory(connection, user.employee_id)
            return {
                "user": {"username": user.username, "access_role": user.access_role},
                "is_demo_user": user.is_demo,
                "trajectory": trajectory,
                "goal_options": goal_options(connection),
                "active_enrollments": active_enrollments(connection, user.employee_id),
                "demo_mode": self.demo_mode,
            }
        finally:
            connection.close()

    def employee_recommendations(self, user: User) -> dict[str, Any]:
        if user.access_role != "employee" or user.employee_id is None:
            raise PermissionError("Employee access required")
        return self._recommendations(user.employee_id)

    def hr_recommendations(self, user: User, employee_id: str) -> dict[str, Any]:
        if user.access_role != "hr":
            raise PermissionError("HR access required")
        return self._recommendations(employee_id)

    def _recommendations(self, employee_id: str) -> dict[str, Any]:
        connection = self._connection()
        try:
            return self.recommendation_service.get(connection, employee_id)
        finally:
            connection.close()

    def change_goal(self, user: User, role: str, grade: str) -> dict[str, Any]:
        if user.access_role != "employee" or user.employee_id is None:
            raise PermissionError("Employee access required")
        connection = self._connection()
        try:
            set_goal(connection, user.employee_id, role, grade)
            return {"target": {"role": role, "grade": grade}}
        finally:
            connection.close()

    def health(self) -> dict[str, Any]:
        connection = self._connection()
        try:
            ready = all(connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        for table in ("skills", "events", "employees", "users", "recommendation_revision"))
            return {"ready": ready}
        finally:
            connection.close()

    def enroll(self, user: User, event_id: str) -> dict[str, Any]:
        if user.access_role != "employee" or user.employee_id is None:
            raise PermissionError("Employee access required")
        connection = self._connection()
        try:
            return enroll_activity(connection, user.employee_id, event_id)
        finally:
            connection.close()

    def complete_demo_enrollment(self, user: User, enrollment_id: str,
                                 completion_date: str = "2026-10-01") -> dict[str, Any]:
        if not self.demo_mode:
            raise PermissionError("Demo completion is disabled")
        if user.access_role != "employee" or user.employee_id is None or not user.is_demo:
            raise PermissionError("Employee access required")
        connection = self._connection()
        try:
            return complete_activity(connection, user.employee_id, enrollment_id, completion_date)
        finally:
            connection.close()

    def reset_demo_progress(self, user: User) -> dict[str, int]:
        if not self.demo_mode:
            raise PermissionError("Demo reset is disabled")
        if user.access_role != "employee" or user.employee_id is None or not user.is_demo:
            raise PermissionError("Demo employee access required")
        connection = self._connection()
        try:
            return reset_demo_employee(connection, user.employee_id)
        finally:
            connection.close()

    def hr_overview(self, user: User, filters: dict[str, str]) -> dict[str, Any]:
        if user.access_role != "hr":
            raise PermissionError("HR access required")
        connection = self._connection()
        try:
            return hr_dashboard(connection, filters)
        finally:
            connection.close()

    def hr_employee(self, user: User, employee_id: str) -> dict[str, Any]:
        if user.access_role != "hr":
            raise PermissionError("HR access required")
        connection = self._connection()
        try:
            return hr_employee_detail(connection, employee_id)
        finally:
            connection.close()

    def import_hr_profiles(self, user: User, employees_json: str, history_csv: str,
                           preview: bool = False) -> dict[str, Any]:
        if user.access_role != "hr":
            raise PermissionError("HR access required")
        connection = self._connection()
        try:
            return import_hr_profile_package(connection, employees_json, history_csv, preview=preview)
        finally:
            connection.close()


class CareerQuestHandler(BaseHTTPRequestHandler):
    """Minimal same-origin JSON API and static file handler."""

    application: WebApplication
    server_version = "CareerQuest/0.1"

    def log_message(self, format: str, *args: object) -> None:
        # Keep development output concise and avoid logging request bodies.
        print(f"{self.address_string()} - {format % args}")

    def _json(self, status: HTTPStatus, payload: dict[str, Any], cookie: str | None = None) -> None:
        body = b"" if status == HTTPStatus.NO_CONTENT else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        return self._read_json_with_limit(MAX_BODY_BYTES)

    def _read_json_with_limit(self, max_body_bytes: int) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request body") from error
        if length <= 0 or length > max_body_bytes:
            raise ValueError("Invalid request body")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("Request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object")
        return payload

    def _session_user(self) -> User:
        cookies = SimpleCookie(self.headers.get("Cookie"))
        session = cookies.get("cq_session")
        if session is None:
            raise AuthenticationError("Authentication required")
        return self.application.user_from_token(session.value)

    def _serve_static(self, filename: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
        path = urlparse(self.path).path
        if path == "/":
            self._serve_static("index.html")
        elif path == "/app.js":
            self._serve_static("app.js")
        elif path == "/styles.css":
            self._serve_static("styles.css")
        elif path == "/api/health":
            try:
                result = self.application.health()
                self._json(HTTPStatus.OK if result["ready"] else HTTPStatus.SERVICE_UNAVAILABLE, result)
            except sqlite3.Error:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"ready": False})
        elif path == "/api/me":
            try:
                user = self._session_user()
                self._json(HTTPStatus.OK, {"username": user.username, "access_role": user.access_role})
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
        elif path in {"/api/employee/dashboard", "/api/employee/recommendations"}:
            try:
                operation = self.application.employee_recommendations if path.endswith("/recommendations") else self.application.employee_dashboard
                self._json(HTTPStatus.OK, operation(self._session_user()))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "Employee access required"})
            except (CareerCalculationError, RecommendationError, ActivityError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path == "/api/hr/dashboard":
            try:
                query = urlparse(self.path).query
                filters = {key: values[-1] for key, values in parse_qs(query).items() if values}
                self._json(HTTPStatus.OK, self.application.hr_overview(self._session_user(), filters))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "HR access required"})
            except HrError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path.startswith("/api/hr/employees/"):
            try:
                parts = path.split("/")
                if len(parts) not in (5, 6) or not parts[4] or (len(parts) == 6 and parts[5] != "recommendations"):
                    raise HrError("Employee not found")
                employee_id = unquote(parts[4])
                operation = self.application.hr_recommendations if len(parts) == 6 else self.application.hr_employee
                self._json(HTTPStatus.OK, operation(self._session_user(), employee_id))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "HR access required"})
            except (HrError, CareerCalculationError, RecommendationError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
        path = urlparse(self.path).path
        if path == "/api/login":
            try:
                payload = self._read_json()
                username = payload.get("username")
                password = payload.get("password")
                if not isinstance(username, str) or not isinstance(password, str):
                    raise ValueError("Username and password are required")
                user, token = self.application.login(username, password)
                cookie = f"cq_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800"
                self._json(HTTPStatus.OK, {"username": user.username, "access_role": user.access_role}, cookie)
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid username or password"})
            except ValueError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path == "/api/logout":
            self._json(HTTPStatus.NO_CONTENT, {}, "cq_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        elif path == "/api/employee/goal":
            try:
                payload = self._read_json()
                self._json(HTTPStatus.OK, self.application.change_goal(self._session_user(), payload.get("role"), payload.get("grade")))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "Employee access required"})
            except ValueError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path.startswith("/api/employee/activities/") and path.endswith("/enroll"):
            try:
                self._read_json()
                parts = path.split("/")
                if len(parts) != 6 or not parts[4]:
                    raise ValueError("Invalid activity path")
                result = self.application.enroll(self._session_user(), parts[4])
                self._json(HTTPStatus.CREATED if result["created"] else HTTPStatus.OK, result)
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "Employee access required"})
            except (ValueError, ActivityError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path.startswith("/api/employee/enrollments/") and path.endswith("/complete"):
            try:
                payload = self._read_json()
                parts = path.split("/")
                if len(parts) != 6 or not parts[4]:
                    raise ValueError("Invalid enrollment path")
                completion_date = payload.get("completion_date", "2026-10-01")
                if not isinstance(completion_date, str):
                    raise ValueError("completion_date must be an ISO date")
                result = self.application.complete_demo_enrollment(
                    self._session_user(), parts[4], completion_date
                )
                self._json(HTTPStatus.OK, result)
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError as error:
                self._json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except (ValueError, ActivityError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path in {"/api/hr/import", "/api/hr/import/preview"}:
            try:
                payload = self._read_json_with_limit(2_000_000)
                employees_json = payload.get("employees_json")
                history_csv = payload.get("history_csv")
                if not isinstance(employees_json, str) or not isinstance(history_csv, str):
                    raise ValueError("employees_json and history_csv are required")
                preview = path.endswith("/preview")
                self._json(HTTPStatus.OK if preview else HTTPStatus.CREATED,
                           self.application.import_hr_profiles(self._session_user(), employees_json, history_csv, preview=preview))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError:
                self._json(HTTPStatus.FORBIDDEN, {"error": "HR access required"})
            except (ValueError, HrError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        elif path == "/api/employee/demo-reset":
            try:
                self._read_json()
                self._json(HTTPStatus.OK, self.application.reset_demo_progress(self._session_user()))
            except AuthenticationError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            except PermissionError as error:
                self._json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except ValueError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})


def serve(database_path: str | Path, host: str = "127.0.0.1", port: int = 8000,
          session_secret: str | None = None, demo_mode: bool | None = None) -> ThreadingHTTPServer:
    """Build a local server. `serve_forever` is intentionally called by `main`."""
    secret = session_secret or os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48)
    is_demo = demo_mode if demo_mode is not None else os.getenv("DEMO_MODE", "true").lower() == "true"
    handler = type("BoundCareerQuestHandler", (CareerQuestHandler,),
                   {"application": WebApplication(database_path, secret, is_demo)})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Career Quest employee cabinet")
    parser.add_argument("--database", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = serve(args.database, args.host, args.port)
    print(f"Career Quest is available at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
