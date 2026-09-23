import tempfile
import unittest
from pathlib import Path

from backend.app.auth import AuthenticationError
from backend.app.db import connect
from backend.app.demo_seed import seed_demo_users
from backend.app.importer import import_package, load_full_package
from backend.app.web import WebApplication


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"
SESSION_SECRET = "web-test-session-secret-at-least-32-characters"


class EmployeeCabinetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "career_quest.db"
        connection = connect(self.database)
        try:
            import_package(connection, load_full_package(DATASET), "full", str(DATASET))
            seed_demo_users(connection)
        finally:
            connection.close()
        self.application = WebApplication(self.database, SESSION_SECRET)

    def tearDown(self):
        self.temp.cleanup()

    def test_employee_dashboard_contains_owned_trajectory_without_waiting_for_recommendations(self):
        user, token = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        restored_user = self.application.user_from_token(token)
        dashboard = self.application.employee_dashboard(restored_user)
        self.assertEqual(user.employee_id, "E0001")
        self.assertEqual(dashboard["trajectory"]["employee"]["employee_id"], "E0001")
        self.assertNotIn("recommendations", dashboard)
        self.assertTrue(dashboard["goal_options"])

    def test_hr_cannot_open_employee_dashboard_endpoint(self):
        user, _ = self.application.login("hr@careerquest.demo", "DemoHR2026!")
        with self.assertRaises(PermissionError):
            self.application.employee_dashboard(user)

    def test_tampered_session_is_rejected(self):
        _, token = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        with self.assertRaises(AuthenticationError):
            self.application.user_from_token(token + "tampered")

    def test_employee_can_complete_only_in_demo_mode(self):
        user, _ = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        enrollment = self.application.enroll(user, "EV_005")["enrollment"]
        result = self.application.complete_demo_enrollment(user, enrollment["enrollment_id"])
        self.assertEqual(result["event_id"], "EV_005")
        non_demo = WebApplication(self.database, SESSION_SECRET, demo_mode=False)
        with self.assertRaises(PermissionError):
            non_demo.complete_demo_enrollment(user, enrollment["enrollment_id"])

    def test_demo_user_can_reset_own_app_progress(self):
        user, _ = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        enrollment = self.application.enroll(user, "EV_005")["enrollment"]
        self.application.complete_demo_enrollment(user, enrollment["enrollment_id"])
        reset = self.application.reset_demo_progress(user)
        self.assertEqual(reset["removed_activity_records"], 1)


if __name__ == "__main__":
    unittest.main()
