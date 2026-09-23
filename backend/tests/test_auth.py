import tempfile
import unittest
from pathlib import Path

from backend.app.auth import (
    AuthenticationError,
    AuthorizationError,
    authenticate,
    can_access_employee,
    create_user,
    issue_session,
    read_session,
    require_employee_access,
)
from backend.app.db import connect
from backend.app.demo_seed import DEMO_USERS, EMPLOYEE_PASSWORD, HR_PASSWORD, seed_demo_users
from backend.app.importer import import_package, load_full_package


DATASET = Path("/Users/IZinekenov/Downloads/case_1/career_quest_dataset")
SESSION_SECRET = "demo-session-secret-that-is-at-least-32-characters"


@unittest.skipUnless(DATASET.exists(), "starter dataset is not available")
class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "career_quest.db")
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_employee_can_sign_in_and_access_only_own_profile(self):
        create_user(self.connection, "employee@example.test", "safe-password-123", "employee", "E0001")
        user = authenticate(self.connection, "EMPLOYEE@example.test", "safe-password-123")
        self.assertEqual(user.employee_id, "E0001")
        self.assertTrue(can_access_employee(user, "E0001"))
        self.assertFalse(can_access_employee(user, "E0002"))
        with self.assertRaises(AuthorizationError):
            require_employee_access(user, "E0002")

    def test_hr_has_profile_access_without_an_employee_binding(self):
        user = create_user(self.connection, "hr@example.test", "safe-password-123", "hr")
        self.assertIsNone(user.employee_id)
        self.assertTrue(can_access_employee(user, "E0001"))
        self.assertTrue(can_access_employee(user, "E0002"))

    def test_bad_password_does_not_authenticate(self):
        create_user(self.connection, "employee@example.test", "safe-password-123", "employee", "E0001")
        with self.assertRaises(AuthenticationError):
            authenticate(self.connection, "employee@example.test", "incorrect-password")

    def test_session_is_signed_and_expires(self):
        user = create_user(self.connection, "employee@example.test", "safe-password-123", "employee", "E0001")
        token = issue_session(user, SESSION_SECRET, ttl_seconds=60, now=1_000)
        claims = read_session(token, SESSION_SECRET, now=1_030)
        self.assertEqual(claims["employee_id"], "E0001")
        with self.assertRaises(AuthenticationError):
            read_session(token, SESSION_SECRET, now=1_060)

    def test_demo_seed_creates_five_idempotent_accounts(self):
        seed_demo_users(self.connection)
        seed_demo_users(self.connection)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 5)
        for username, role, employee_id in DEMO_USERS:
            password = EMPLOYEE_PASSWORD if role == "employee" else HR_PASSWORD
            user = authenticate(self.connection, username, password)
            self.assertEqual(user.access_role, role)
            self.assertEqual(user.employee_id, employee_id)


if __name__ == "__main__":
    unittest.main()
