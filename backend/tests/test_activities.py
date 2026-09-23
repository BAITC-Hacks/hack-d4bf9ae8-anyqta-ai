import tempfile
import unittest
from pathlib import Path

from backend.app.activities import ActivityError, active_enrollments, complete_activity, enroll_activity, reset_demo_employee
from backend.app.career import calculate_trajectory
from backend.app.db import connect
from backend.app.importer import import_package, load_full_package
from backend.app.recommendations import eligible_candidates


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"


class ActivityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "career_quest.db")
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_enrollment_creates_one_in_progress_record_and_is_idempotent(self):
        first = enroll_activity(self.connection, "E0001", "EV_005")
        second = enroll_activity(self.connection, "E0001", "EV_005")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["enrollment"]["enrollment_id"], second["enrollment"]["enrollment_id"])
        status = self.connection.execute(
            "SELECT status FROM activity_history WHERE record_id = ?", (first["enrollment"]["history_record_id"],)
        ).fetchone()[0]
        self.assertEqual(status, "in_progress")
        self.assertNotIn("EV_005", {item.event_id for item in eligible_candidates(self.connection, "E0001")})

    def test_completion_updates_history_skills_and_coverage_once(self):
        enrollment = enroll_activity(self.connection, "E0001", "EV_005")["enrollment"]
        result = complete_activity(self.connection, "E0001", enrollment["enrollment_id"])
        self.assertGreaterEqual(result["coverage_after"], result["coverage_before"])
        system_design = next(item for item in result["skill_changes"] if item["skill_id"] == "SK_SYSTEM_DESIGN")
        self.assertEqual((system_design["before_level"], system_design["after_level"]), (1, 2))
        self.assertEqual(active_enrollments(self.connection, "E0001"), [])
        self.assertEqual(
            self.connection.execute("SELECT status FROM activity_history WHERE record_id = ?", (enrollment["history_record_id"],)).fetchone()[0],
            "completed",
        )
        with self.assertRaises(ActivityError):
            complete_activity(self.connection, "E0001", enrollment["enrollment_id"])
        trajectory = calculate_trajectory(self.connection, "E0001")
        self.assertEqual(trajectory["effective_skills"]["SK_SYSTEM_DESIGN"], 2)

    def test_direct_enrollment_in_mandatory_event_is_rejected(self):
        with self.assertRaises(ActivityError):
            enroll_activity(self.connection, "E0001", "EV_001")

    def test_demo_reset_removes_only_app_created_progress(self):
        before = calculate_trajectory(self.connection, "E0001")
        enrollment = enroll_activity(self.connection, "E0001", "EV_005")["enrollment"]
        complete_activity(self.connection, "E0001", enrollment["enrollment_id"])
        reset = reset_demo_employee(self.connection, "E0001")
        after = calculate_trajectory(self.connection, "E0001")
        self.assertEqual(reset, {"removed_enrollments": 1, "removed_activity_records": 1})
        self.assertEqual(before["effective_skills"], after["effective_skills"])
        self.assertEqual(active_enrollments(self.connection, "E0001"), [])


if __name__ == "__main__":
    unittest.main()
