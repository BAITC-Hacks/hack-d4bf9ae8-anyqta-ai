import tempfile
import unittest
from pathlib import Path

from backend.app.db import connect
from backend.app.importer import import_package, load_full_package
from backend.app.recommendations import (
    RecommendationError,
    eligible_candidates,
    recommend_employee,
)


DATASET = Path("/Users/IZinekenov/Downloads/case_1/career_quest_dataset")


class ValidSelector:
    def select(self, facts):
        return {"recommendations": [{"event_id": facts["candidates"][-1]["event_id"]}]}


class InvalidSelector:
    def select(self, facts):
        return {"recommendations": [{"event_id": "EV_NOT_REAL"}]}


@unittest.skipUnless(DATASET.exists(), "starter dataset is not available")
class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "career_quest.db")
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_candidates_are_voluntary_useful_and_not_completed(self):
        candidates = eligible_candidates(self.connection, "E0001")
        self.assertTrue(candidates)
        for candidate in candidates:
            mandatory = self.connection.execute("SELECT mandatory FROM events WHERE event_id = ?", (candidate.event_id,)).fetchone()[0]
            completed = self.connection.execute(
                "SELECT 1 FROM activity_history WHERE employee_id = ? AND event_id = ? AND status IN ('completed', 'in_progress')",
                ("E0001", candidate.event_id),
            ).fetchone()
            self.assertEqual(mandatory, 0)
            self.assertIsNone(completed)
            self.assertGreater(candidate.total_gap_reduction, 0)

    def test_rules_fallback_returns_fact_based_explanations(self):
        result = recommend_employee(self.connection, "E0001")
        self.assertEqual(result["mode"], "rules_fallback")
        self.assertGreaterEqual(len(result["recommendations"]), 1)
        self.assertLessEqual(len(result["recommendations"]), 3)
        self.assertTrue(result["recommendations"][0]["evidence"])

    def test_valid_llm_selection_is_limited_to_verified_candidates(self):
        result = recommend_employee(self.connection, "E0001", selector=ValidSelector())
        self.assertEqual(result["mode"], "llm")
        candidates = {candidate.event_id for candidate in eligible_candidates(self.connection, "E0001")}
        self.assertIn(result["recommendations"][0]["event_id"], candidates)

    def test_invalid_llm_selection_falls_back_to_rules(self):
        result = recommend_employee(self.connection, "E0001", selector=InvalidSelector())
        self.assertEqual(result["mode"], "rules_fallback")
        self.assertIn("invalid", result["fallback_reason"])

    def test_limit_is_constrained(self):
        with self.assertRaises(RecommendationError):
            recommend_employee(self.connection, "E0001", limit=4)

    def test_regular_club_may_repeat_after_completion(self):
        self.connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("R_TEST_CLUB", "E0001", "EV_036", "2026-09-01", None, "completed", 100, None, None, "self", "{}"),
        )
        event_ids = {candidate.event_id for candidate in eligible_candidates(self.connection, "E0001")}
        self.assertIn("EV_036", event_ids)


if __name__ == "__main__":
    unittest.main()
