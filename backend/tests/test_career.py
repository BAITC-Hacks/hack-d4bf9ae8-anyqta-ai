import tempfile
import unittest
from pathlib import Path

from backend.app.career import CareerCalculationError, calculate_trajectory
from backend.app.db import connect
from backend.app.importer import import_package, load_full_package


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"


class CareerCalculationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "career_quest.db")
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_goal_is_used_and_gaps_match_target_requirements(self):
        result = calculate_trajectory(self.connection, "E0001")
        self.assertEqual(result["target"], {"role": "Backend Engineer", "grade": "Middle"})
        self.assertEqual(len(result["skill_gaps"]), 15)
        self.assertTrue(any(item["is_critical"] for item in result["skill_gaps"]))
        self.assertGreaterEqual(result["coverage_percent"], 0)
        self.assertLessEqual(result["coverage_percent"], 100)

    def test_completed_activity_after_review_updates_effective_skill(self):
        self.connection.execute(
            "UPDATE employees SET last_review_date = '2026-01-01' WHERE employee_id = 'E0001'"
        )
        self.connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("R_TEST_1", "E0001", "EV_005", "2026-02-01", None, "completed", 100, None, None, "self", "{}"),
        )
        result = calculate_trajectory(self.connection, "E0001")
        change = next(item for item in result["applied_skill_changes"] if item["record_id"] == "R_TEST_1" and item["skill_id"] == "SK_SYSTEM_DESIGN")
        self.assertEqual(change["before_level"], 1)
        self.assertEqual(change["after_level"], 2)

    def test_activity_on_review_date_is_not_applied_again(self):
        self.connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("R_TEST_2", "E0001", "EV_005", "2026-09-11", None, "completed", 100, None, None, "self", "{}"),
        )
        result = calculate_trajectory(self.connection, "E0001")
        self.assertFalse(any(item["record_id"] == "R_TEST_2" for item in result["applied_skill_changes"]))

    def test_lead_without_goal_requires_goal_selection(self):
        result = calculate_trajectory(self.connection, "E0006")
        self.assertEqual(result["trajectory_status"], "goal_required")
        self.assertIsNone(result["target"])
        self.assertEqual(result["skill_gaps"], [])

    def test_unknown_employee_is_rejected(self):
        with self.assertRaises(CareerCalculationError):
            calculate_trajectory(self.connection, "E9999")


if __name__ == "__main__":
    unittest.main()
