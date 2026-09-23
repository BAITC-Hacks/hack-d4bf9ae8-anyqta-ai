import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.db import connect
from backend.app.demo_seed import seed_demo_users
from backend.app.hr import HrError, hr_dashboard, hr_employee_detail, import_hr_profile_package
from backend.app.importer import import_package, load_full_package
from backend.app.web import WebApplication


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"
SESSION_SECRET = "hr-test-session-secret-that-is-at-least-32-characters"
HISTORY_FIELDS = ["record_id", "employee_id", "event_id", "date", "due_date", "status", "completion_pct", "score", "feedback_rating", "assigned_by"]
LLM_SETTINGS = {
    "LLM_API_URL": "https://model.example/v1/chat/completions",
    "LLM_API_KEY": "test-only-key",
    "LLM_MODEL": "test-model",
}


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

    def test_hr_detail_contains_trajectory_and_recommendations(self):
        result = hr_employee_detail(self.connection, "E0001")
        self.assertEqual(result["employee"]["employee_id"], "E0001")
        self.assertEqual(result["trajectory"]["target"]["grade"], "Middle")
        self.assertTrue(result["recommendations"])

    def test_hr_import_adds_jury_profile_without_filesystem_write(self):
        source = json.loads((DATASET / "employees.json").read_text(encoding="utf-8"))["employees"][0]
        source["employee_id"] = "E9999"
        source["full_name"] = "Jury Candidate"
        source["manager_id"] = "E0050"
        employee_json = json.dumps({"employees": [source]})
        stream = io.StringIO()
        csv.DictWriter(stream, fieldnames=HISTORY_FIELDS).writeheader()
        result = import_hr_profile_package(self.connection, employee_json, stream.getvalue(), "test upload")
        self.assertEqual(result, {"employees_imported": 1, "history_records_imported": 0})
        self.assertEqual(hr_employee_detail(self.connection, "E9999")["employee"]["full_name"], "Jury Candidate")

    def test_web_application_blocks_employee_from_hr_operations(self):
        application = WebApplication(self.database, SESSION_SECRET)
        employee, _ = application.login("junior@careerquest.demo", "DemoEmployee2026!")
        with self.assertRaises(PermissionError):
            application.hr_overview(employee, {})

    def _import_jury_profile(self):
        application = WebApplication(self.database, SESSION_SECRET)
        hr, _ = application.login("hr@careerquest.demo", "DemoHR2026!")
        profile = json.loads((DATASET / "employees.json").read_text(encoding="utf-8"))["employees"][0]
        profile.update(employee_id="E9999", full_name="Jury Candidate")
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerow({
            "record_id": "R_JURY_001", "employee_id": "E9999", "event_id": "EV_036",
            "date": "2026-09-20", "status": "no_show", "completion_pct": 0,
            "assigned_by": "self",
        })
        application.import_hr_profiles(hr, json.dumps({"employees": [profile]}), stream.getvalue())
        return application, hr

    def test_imported_jury_profile_uses_configured_ai_and_returns_evidence(self):
        application, hr = self._import_jury_profile()
        response = {"choices": [{"message": {"content": json.dumps({
            "recommendations": [{"event_id": "EV_036"}],
        })}}]}
        with patch.dict("os.environ", LLM_SETTINGS), patch("backend.app.recommendations.urllib.request.urlopen") as provider:
            provider.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            result = application.hr_employee(hr, "E9999")

        provider.assert_called_once()
        self.assertEqual(result["employee"]["employee_id"], "E9999")
        self.assertEqual(result["recommendation_mode"], "llm")
        self.assertIsNone(result["recommendation_notice"])
        self.assertEqual([item["event_id"] for item in result["recommendations"]], ["EV_036"])
        recommendation = result["recommendations"][0]
        self.assertTrue(recommendation["expected_skill_changes"])
        self.assertTrue(any("истории" in reason for reason in recommendation["evidence"]))
        request = provider.call_args.args[0]
        self.assertEqual(request.full_url, LLM_SETTINGS["LLM_API_URL"])
        prompt = json.loads(request.data)
        self.assertEqual(prompt["model"], LLM_SETTINGS["LLM_MODEL"])
        facts = json.loads(prompt["messages"][-1]["content"].split("\n", 1)[1])
        club = next(item for item in facts["candidates"] if item["event_id"] == "EV_036")
        self.assertEqual(club["negative_similar"], 1)

    def test_imported_jury_profile_works_without_model_configuration(self):
        application, hr = self._import_jury_profile()
        with patch.dict("os.environ", {key: "" for key in LLM_SETTINGS}), patch("backend.app.recommendations.urllib.request.urlopen") as provider:
            result = application.hr_employee(hr, "E9999")
        provider.assert_not_called()
        self.assertEqual(result["recommendation_mode"], "rules_fallback")
        self.assertTrue(result["recommendation_notice"])
        self.assertTrue(result["recommendations"])
        self.assertTrue(all(item["evidence"] for item in result["recommendations"]))

    def test_imported_jury_profile_falls_back_after_invalid_or_failed_ai(self):
        application, hr = self._import_jury_profile()
        expected = hr_employee_detail(self.connection, "E9999")["recommendations"]
        for failure in ("unknown_event", "timeout"):
            with self.subTest(failure=failure), patch.dict("os.environ", LLM_SETTINGS), patch("backend.app.recommendations.urllib.request.urlopen") as provider:
                if failure == "timeout":
                    provider.side_effect = TimeoutError("Model request timed out")
                else:
                    response = {"choices": [{"message": {"content": json.dumps({
                        "recommendations": [{"event_id": "EV_NOT_REAL"}],
                    })}}]}
                    provider.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
                result = application.hr_employee(hr, "E9999")
                provider.assert_called_once()
                self.assertEqual(result["recommendation_mode"], "rules_fallback")
                self.assertTrue(result["recommendation_notice"])
                self.assertEqual(result["recommendations"], expected)

    def test_employee_cannot_request_jury_profile_or_trigger_its_ai(self):
        application, _ = self._import_jury_profile()
        employee, _ = application.login("junior@careerquest.demo", "DemoEmployee2026!")
        with patch("backend.app.web.selector_from_environment") as selector:
            with self.assertRaises(PermissionError):
                application.hr_employee(employee, "E9999")
        selector.assert_not_called()

    def test_hr_overview_does_not_request_ai_for_every_employee(self):
        application = WebApplication(self.database, SESSION_SECRET)
        hr, _ = application.login("hr@careerquest.demo", "DemoHR2026!")
        with patch("backend.app.web.selector_from_environment") as selector:
            result = application.hr_overview(hr, {})
        selector.assert_not_called()
        self.assertEqual(result["summary"]["employees"], 200)


if __name__ == "__main__":
    unittest.main()
