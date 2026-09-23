import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from backend.app.db import connect
from backend.app.demo_seed import seed_demo_users
from backend.app.hr import HrError, hr_dashboard, hr_employee_detail, import_hr_profile_package
from backend.app.importer import import_package, load_full_package
from backend.app.web import WebApplication


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"
SESSION_SECRET = "hr-test-session-secret-that-is-at-least-32-characters"
HISTORY_FIELDS = ["record_id", "employee_id", "event_id", "date", "due_date", "status", "completion_pct", "score", "feedback_rating", "assigned_by"]


class HrOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "career_quest.db"
        self.connection = connect(self.database)
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))
        seed_demo_users(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_dashboard_aggregates_gaps_and_support_signals(self):
        result = hr_dashboard(self.connection)
        self.assertEqual(result["summary"]["employees"], 200)
        self.assertTrue(result["competency_gaps"])
        self.assertTrue(any(person["support_signals"] for person in result["employees"]))

    def test_dashboard_filter_limits_people(self):
        result = hr_dashboard(self.connection, {"grade": "Junior"})
        self.assertTrue(result["employees"])
        self.assertTrue(all(person["grade"] == "Junior" for person in result["employees"]))

    def test_hr_detail_contains_trajectory_and_history(self):
        result = hr_employee_detail(self.connection, "E0001")
        self.assertEqual(result["employee"]["employee_id"], "E0001")
        self.assertEqual(result["trajectory"]["target"]["grade"], "Middle")
        self.assertTrue(result["history"])

    def test_hr_import_adds_jury_profile_without_filesystem_write(self):
        source = json.loads((DATASET / "employees.json").read_text(encoding="utf-8"))["employees"][0]
        source["employee_id"] = "E9999"
        source["full_name"] = "Jury Candidate"
        source["manager_id"] = "E0050"
        employee_json = json.dumps({"employees": [source]})
        stream = io.StringIO()
        csv.DictWriter(stream, fieldnames=HISTORY_FIELDS).writeheader()
        result = import_hr_profile_package(self.connection, employee_json, stream.getvalue(), "test upload")
        self.assertEqual(result["employees_imported"], 1)
        self.assertEqual(result["history_records_imported"], 0)
        self.assertEqual(result["profiles"][0]["employee_id"], "E9999")
        self.assertEqual(hr_employee_detail(self.connection, "E9999")["employee"]["full_name"], "Jury Candidate")

    def test_web_application_blocks_employee_from_hr_operations(self):
        application = WebApplication(self.database, SESSION_SECRET)
        employee, _ = application.login("junior@careerquest.demo", "DemoEmployee2026!")
        with self.assertRaises(PermissionError):
            application.hr_overview(employee, {})


if __name__ == "__main__":
    unittest.main()
