import tempfile
import unittest
from pathlib import Path

from backend.app.auth import AuthenticationError
from backend.app.db import connect
from backend.app.demo_seed import seed_demo_users
from backend.app.importer import import_package, load_full_package
from backend.app.web import WebApplication


DATASET = Path("/Users/IZinekenov/Downloads/case_1/career_quest_dataset")
SESSION_SECRET = "web-test-session-secret-at-least-32-characters"


@unittest.skipUnless(DATASET.exists(), "starter dataset is not available")
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

    def test_employee_dashboard_contains_owned_trajectory_and_recommendations(self):
        user, token = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        restored_user = self.application.user_from_token(token)
        dashboard = self.application.employee_dashboard(restored_user)
        self.assertEqual(user.employee_id, "E0001")
        self.assertEqual(dashboard["trajectory"]["employee"]["employee_id"], "E0001")
        self.assertTrue(dashboard["recommendations"])

    def test_hr_cannot_open_employee_dashboard_endpoint(self):
        user, _ = self.application.login("hr@careerquest.demo", "DemoHR2026!")
        with self.assertRaises(PermissionError):
            self.application.employee_dashboard(user)

    def test_tampered_session_is_rejected(self):
        _, token = self.application.login("junior@careerquest.demo", "DemoEmployee2026!")
        with self.assertRaises(AuthenticationError):
            self.application.user_from_token(token + "tampered")


if __name__ == "__main__":
    unittest.main()
