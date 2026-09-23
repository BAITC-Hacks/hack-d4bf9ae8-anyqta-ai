import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.activities import complete_activity, enroll_activity
from backend.app.auth import User
from backend.app.career import calculate_trajectory
from backend.app.db import connect
from backend.app.hr import hr_employee_detail
from backend.app.importer import import_package, load_full_package
from backend.app.profiles import ProfileError, employee_profile, update_career_goal
from backend.app.web import WebApplication


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"
SESSION_SECRET = "profile-tests-session-key-at-least-thirty-two-characters"


class ProfileExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "profile.db"
        self.connection = connect(self.database)
        self.package = load_full_package(DATASET)
        import_package(self.connection, self.package, "full", str(DATASET))
        self.application = WebApplication(self.database, SESSION_SECRET)
        self.employee = User("test-user", "employee@test.example", "employee", "E0001", True)
        self.hr = User("test-hr", "hr@test.example", "hr", None, False)
        environment = patch.dict("os.environ", {"LLM_API_URL": "", "LLM_API_KEY": "", "LLM_MODEL": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_profile_contains_current_role_all_skills_and_only_own_full_history(self):
        dashboard = self.application.employee_dashboard(self.employee)
        profile = dashboard["profile"]
        self.assertEqual(profile["employee"]["role"], "Backend Engineer")
        self.assertEqual(profile["employee"]["grade"], "Junior")
        self.assertTrue(profile["employee"]["department"])
        self.assertEqual(len(profile["skills"]), 60)
        self.assertTrue(any(not skill["assessed"] and skill["current_level"] == 0 for skill in profile["skills"]))
        self.assertEqual(sum(skill["required_level"] is not None for skill in profile["skills"]), 15)
        expected = {row[0] for row in self.connection.execute("SELECT record_id FROM activity_history WHERE employee_id = 'E0001'")}
        self.assertEqual({record["record_id"] for record in profile["history"]}, expected)
        self.assertEqual([record["activity_date"] for record in profile["history"]], sorted([record["activity_date"] for record in profile["history"]], reverse=True))
        self.assertTrue(all(record["completed_at"] is None for record in profile["history"]))

    def test_completion_updates_skill_table_and_one_history_record_with_named_evidence(self):
        original = employee_profile(self.connection, "E0001")
        enrollment = enroll_activity(self.connection, "E0001", "EV_005")["enrollment"]
        active = employee_profile(self.connection, "E0001")
        record = next(item for item in active["history"] if item["record_id"] == enrollment["history_record_id"])
        self.assertEqual(record["status"], "in_progress")
        self.assertEqual(record["skill_effect"], "not_completed")
        self.assertEqual(record["skill_changes"], [])
        complete_activity(self.connection, "E0001", enrollment["enrollment_id"])
        profile = employee_profile(self.connection, "E0001")
        self.assertEqual(len(profile["history"]), len(original["history"]) + 1)
        skill = next(item for item in profile["skills"] if item["skill_id"] == "SK_SYSTEM_DESIGN")
        self.assertEqual((skill["assessed_level"], skill["current_level"]), (1, 2))
        record = next(item for item in profile["history"] if item["record_id"] == enrollment["history_record_id"])
        self.assertEqual((record["status"], record["completion_pct"]), ("completed", 100))
        self.assertEqual(record["completed_at"], "2026-10-01")
        self.assertEqual(record["skill_effect"], "calculated")
        change = next(item for item in record["skill_changes"] if item["skill_id"] == "SK_SYSTEM_DESIGN")
        self.assertEqual(change["skill_name"], "System Design")
        self.assertEqual((change["before_level"], change["after_level"]), (1, 2))

    def test_history_keeps_every_status_and_distinguishes_assessed_completions(self):
        self.connection.execute("DELETE FROM activity_history WHERE employee_id = 'E0001'")
        statuses = {"completed", "in_progress", "dropped", "no_show", "declined", "overdue"}
        for index, status in enumerate(sorted(statuses)):
            self.connection.execute(
                "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"PROFILE_{index}", "E0001", "EV_001" if status == "overdue" else "EV_005" if status == "completed" else "EV_036", "2026-01-01", "2026-02-01" if status == "overdue" else None, status, 100 if status == "completed" else 0, 0 if status == "completed" else None, 1, "hr" if status == "overdue" else "self", "{}"),
            )
        profile = employee_profile(self.connection, "E0001")
        self.assertEqual({record["status"] for record in profile["history"]}, statuses)
        completed = next(record for record in profile["history"] if record["status"] == "completed")
        self.assertEqual(completed["score"], 0)
        self.assertEqual(completed["skill_effect"], "included_in_assessment")
        self.assertEqual(completed["skill_changes"], [])
        self.assertIsNone(completed["completed_at"])

    def test_compliance_completion_does_not_claim_skill_growth_or_assessment_credit(self):
        self.connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("PROFILE_COMPLIANCE", "E0001", "EV_001", "2026-01-01", "2026-02-01", "completed", 100, 90, None, "hr", "{}"),
        )
        record = next(item for item in employee_profile(self.connection, "E0001")["history"] if item["record_id"] == "PROFILE_COMPLIANCE")
        self.assertEqual(record["skill_effect"], "no_skill_change")
        self.assertEqual(record["skill_changes"], [])

    def test_lead_without_goal_keeps_profile_and_can_choose_a_supported_goal(self):
        lead = User("test-lead", "lead@test.example", "employee", "E0006", False)
        before = self.application.employee_dashboard(lead)
        self.assertEqual(before["trajectory"]["trajectory_status"], "goal_required")
        self.assertEqual(len(before["profile"]["skills"]), 60)
        self.assertTrue(before["profile"]["history"])
        self.assertEqual(len(before["profile"]["goal_options"]), 32)
        option = next(item for item in before["profile"]["goal_options"] if item["role"] != before["profile"]["employee"]["role"])
        self.application.update_employee_goal(lead, option["role"], option["grade"])
        after = self.application.employee_dashboard(lead)
        self.assertEqual(after["trajectory"]["trajectory_status"], "ready")
        self.assertEqual(after["trajectory"]["target"], option)
        self.assertEqual(after["profile"]["history"], before["profile"]["history"])

    def test_goal_change_persists_and_refreshes_employee_and_hr_targets(self):
        original = employee_profile(self.connection, "E0001")
        self.application.update_employee_goal(self.employee, "Backend Engineer", "Senior")
        restarted = WebApplication(self.database, SESSION_SECRET)
        dashboard = restarted.employee_dashboard(self.employee)
        self.assertEqual(dashboard["trajectory"]["target"], {"role": "Backend Engineer", "grade": "Senior"})
        self.assertEqual(dashboard["profile"]["employee"]["grade"], "Junior")
        self.assertEqual(dashboard["profile"]["history"], original["history"])
        detail = hr_employee_detail(self.connection, "E0001")
        self.assertEqual(detail["trajectory"]["target"], dashboard["trajectory"]["target"])
        self.assertEqual(detail["profile"], dashboard["profile"])

    def test_invalid_goals_leave_existing_goal_unchanged(self):
        original = calculate_trajectory(self.connection, "E0001")["target"]
        for role, grade in (("Unknown Role", "Lead"), ("Backend Engineer", "Unknown"), (None, "Senior"), ("Backend Engineer", None), ([], "Middle"), ("Backend Engineer", 3), (False, False), ("", "")):
            with self.subTest(role=role, grade=grade):
                with self.assertRaises(ProfileError):
                    self.application.update_employee_goal(self.employee, role, grade)
                self.assertEqual(calculate_trajectory(self.connection, "E0001")["target"], original)

    def test_clearing_goal_restores_default_and_lead_no_goal_state(self):
        update_career_goal(self.connection, "E0001", "Backend Engineer", "Senior")
        result = update_career_goal(self.connection, "E0001", None, None)
        self.assertEqual(result["trajectory"]["target"], {"role": "Backend Engineer", "grade": "Middle"})
        update_career_goal(self.connection, "E0006", "Backend Engineer", "Lead")
        result = update_career_goal(self.connection, "E0006", None, None)
        self.assertEqual(result["trajectory"]["trajectory_status"], "goal_required")
        self.assertEqual(len(employee_profile(self.connection, "E0006")["skills"]), 60)

    def test_goal_update_preserves_import_snapshot_and_survives_import_retry(self):
        source = self.connection.execute("SELECT source_json FROM employees WHERE employee_id = 'E0001'").fetchone()[0]
        update_career_goal(self.connection, "E0001", "Backend Engineer", "Senior")
        import_package(self.connection, self.package, "full", str(DATASET))
        self.assertEqual(self.connection.execute("SELECT source_json FROM employees WHERE employee_id = 'E0001'").fetchone()[0], source)
        self.assertEqual(calculate_trajectory(self.connection, "E0001")["target"]["grade"], "Senior")

    def test_demo_reset_restores_only_own_original_goal_and_activity_history(self):
        original = employee_profile(self.connection, "E0001")
        other = employee_profile(self.connection, "E0002")
        enrollment = enroll_activity(self.connection, "E0001", "EV_005")["enrollment"]
        complete_activity(self.connection, "E0001", enrollment["enrollment_id"])
        self.application.update_employee_goal(self.employee, "Backend Engineer", "Lead")
        self.application.reset_demo_progress(self.employee)
        self.assertEqual(employee_profile(self.connection, "E0001"), original)
        self.assertEqual(employee_profile(self.connection, "E0002"), other)

    def test_hr_cannot_edit_employee_goal_through_employee_endpoint(self):
        with self.assertRaises(PermissionError):
            self.application.update_employee_goal(self.hr, "Backend Engineer", "Senior")


if __name__ == "__main__":
    unittest.main()
