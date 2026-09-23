import tempfile
import unittest
from pathlib import Path

from backend.app.db import connect
from backend.app.hr import HrError, hr_dashboard, hr_employee_detail
from backend.app.importer import import_package, load_full_package
from backend.app.recommendations import eligible_candidates, recommendation_availability


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"


class HrAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "analytics.db")
        import_package(self.connection, load_full_package(DATASET), "full", str(DATASET))

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def _record(self, record_id, employee_id, event_id, status, day):
        completion = 100 if status == "completed" else 0
        self.connection.execute(
            "INSERT INTO activity_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record_id, employee_id, event_id, day, None, status, completion, None, None, "self", "{}"),
        )

    def _participation_fixture(self):
        self.connection.execute("DELETE FROM activity_history")
        for record_id, employee_id, event_id, status, day in (
            ("A1", "E0001", "EV_036", "completed", "2026-04-01"),
            ("A2", "E0001", "EV_036", "completed", "2026-05-01"),
            ("A3", "E0002", "EV_036", "no_show", "2026-09-01"),
            ("A4", "E0002", "EV_036", "dropped", "2026-09-02"),
            ("A5", "E0001", "EV_036", "declined", "2026-09-03"),
            ("A6", "E0001", "EV_036", "in_progress", "2026-09-04"),
            ("A7", "E0002", "EV_036", "completed", "2026-10-01"),
            ("OLD", "E0001", "EV_036", "completed", "2026-03-31"),
            ("FUTURE", "E0002", "EV_036", "completed", "2026-10-02"),
            ("MANDATORY", "E0002", "EV_001", "overdue", "2026-09-10"),
        ):
            self._record(record_id, employee_id, event_id, status, day)

    def test_activity_counts_include_each_status_and_distinct_people_within_period(self):
        self._participation_fixture()
        result = hr_dashboard(self.connection)
        events = {item["event_id"]: item for item in result["activity_participation"]}
        club = events["EV_036"]
        self.assertEqual(club["total_records"], 7)
        self.assertEqual(club["unique_participants"], 2)
        self.assertEqual(club["status_counts"], {
            "completed": 3, "in_progress": 1, "dropped": 1,
            "no_show": 1, "declined": 1, "overdue": 0,
        })
        self.assertEqual(club["completion_rate_percent"], 42.86)
        self.assertFalse(club["mandatory"])
        self.assertTrue(events["EV_001"]["mandatory"])
        self.assertEqual(events["EV_001"]["status_counts"]["overdue"], 1)
        self.assertEqual(sum(item["total_records"] for item in events.values()), 8)
        self.assertEqual(events["EV_005"]["total_records"], 0)
        self.assertIsNone(events["EV_005"]["completion_rate_percent"])
        people = {item["employee_id"]: item for item in result["employees"]}
        self.assertEqual(people["E0002"]["voluntary_completed_since"], 1)
        self.assertEqual(people["E0002"]["voluntary_noncompletion_since"], 2)
        detail = hr_employee_detail(self.connection, "E0002")
        self.assertEqual(detail["participation"], {"voluntary_completed": 1, "voluntary_noncompletion": 2})

    def test_activity_counts_follow_all_cohort_filters(self):
        self._participation_fixture()
        department = self.connection.execute("SELECT department FROM employees WHERE employee_id = 'E0001'").fetchone()[0]
        result = hr_dashboard(self.connection, {"grade": "Junior", "role": "Backend Engineer", "department": department})
        club = next(item for item in result["activity_participation"] if item["event_id"] == "EV_036")
        self.assertEqual(club["total_records"], 4)
        self.assertEqual(club["unique_participants"], 1)
        self.assertEqual(club["completion_rate_percent"], 50)
        self.assertEqual(club["status_counts"]["no_show"], 0)
        self.assertEqual(sum(item["total_records"] for item in result["activity_participation"]), 4)

    def test_next_step_filters_cover_all_people_and_explain_missing_steps(self):
        missing = hr_dashboard(self.connection, {"next_step": "missing"})
        available = hr_dashboard(self.connection, {"next_step": "available"})
        self.assertEqual(missing["summary"]["employees"], 41)
        self.assertEqual(missing["summary"]["without_next_step"], 41)
        self.assertEqual(available["summary"]["employees"], 159)
        self.assertEqual(available["summary"]["without_next_step"], 0)
        missing_ids = {person["employee_id"] for person in missing["employees"]}
        available_ids = {person["employee_id"] for person in available["employees"]}
        self.assertFalse(missing_ids & available_ids)
        self.assertEqual(len(missing_ids | available_ids), 200)
        for person in missing["employees"]:
            self.assertFalse(person["next_step"]["has_next_step"])
            self.assertTrue(person["next_step"]["reasons"])
            self.assertTrue(all(reason["message"] for reason in person["next_step"]["reasons"]))
        for person in available["employees"]:
            self.assertGreater(person["next_step"]["eligible_event_count"], 0)

    def test_missing_step_filter_also_filters_participation_and_gaps(self):
        self._participation_fixture()
        # With a Lead's goal unset, only E0001 should remain in this department slice.
        self.connection.execute("UPDATE employees SET department = 'Analytics fixture' WHERE employee_id IN ('E0001', 'E0002')")
        self.connection.execute("UPDATE employees SET grade = 'Lead', target_role = NULL, target_grade = NULL WHERE employee_id = 'E0001'")
        result = hr_dashboard(self.connection, {"department": "Analytics fixture", "next_step": "missing"})
        self.assertEqual([person["employee_id"] for person in result["employees"]], ["E0001"])
        self.assertEqual(result["competency_gaps"], [])
        self.assertEqual(result["summary"]["without_next_step"], 1)
        club = next(item for item in result["activity_participation"] if item["event_id"] == "EV_036")
        self.assertEqual((club["total_records"], club["unique_participants"]), (4, 1))

    def test_no_goal_and_covered_target_have_distinct_reasons(self):
        self.assertEqual(recommendation_availability(self.connection, "E0006")["status"], "goal_required")
        self.connection.execute("DELETE FROM activity_history WHERE employee_id = 'E0001'")
        self.connection.execute("DELETE FROM employee_skills WHERE employee_id = 'E0001'")
        self.connection.execute("INSERT INTO employee_skills SELECT 'E0001', skill_id, 5 FROM skills")
        result = recommendation_availability(self.connection, "E0001")
        self.assertEqual(result["status"], "target_covered")
        self.assertFalse(result["has_next_step"])
        self.assertEqual(result["reasons"][0]["code"], "target_covered")

    def test_missing_step_reasons_match_eligibility_blockers(self):
        self.connection.execute("DELETE FROM activity_history WHERE employee_id = 'E0001'")
        self.connection.execute("UPDATE events SET mandatory = (event_id != 'EV_005')")
        self.assertEqual([item.event_id for item in eligible_candidates(self.connection, "E0001")], ["EV_005"])
        for blocker in ("audience_mismatch", "prerequisites_unmet", "in_progress", "already_completed", "no_upcoming_session", "catalog_gap"):
            with self.subTest(blocker=blocker):
                self.connection.execute("SAVEPOINT blocker")
                try:
                    if blocker == "audience_mismatch":
                        self.connection.execute("DELETE FROM event_target_roles WHERE event_id = 'EV_005'")
                    elif blocker == "prerequisites_unmet":
                        self.connection.execute("INSERT OR REPLACE INTO event_prerequisites VALUES ('EV_005', 'SK_SYSTEM_DESIGN', 5)")
                    elif blocker in {"in_progress", "already_completed"}:
                        self._record("BLOCKER", "E0001", "EV_005", "completed" if blocker == "already_completed" else "in_progress", "2026-01-01")
                    elif blocker == "no_upcoming_session":
                        self.connection.execute("UPDATE events SET format = 'online' WHERE event_id = 'EV_005'")
                        self.connection.execute("DELETE FROM event_sessions WHERE event_id = 'EV_005'")
                    else:
                        self.connection.execute("UPDATE events SET mandatory = 1")
                    result = recommendation_availability(self.connection, "E0001")
                    self.assertEqual(result["status"], "no_eligible_events")
                    self.assertEqual([reason["code"] for reason in result["reasons"]], [blocker])
                    self.assertEqual(eligible_candidates(self.connection, "E0001"), [])
                finally:
                    self.connection.execute("ROLLBACK TO blocker")
                    self.connection.execute("RELEASE blocker")

    def test_recurring_club_remains_available_after_completion(self):
        self.connection.execute("DELETE FROM activity_history WHERE employee_id = 'E0001'")
        self.connection.execute("UPDATE events SET mandatory = (event_id != 'EV_036')")
        self._record("CLUB", "E0001", "EV_036", "completed", "2026-01-01")
        result = recommendation_availability(self.connection, "E0001")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["eligible_event_count"], 1)
        self._record("ACTIVE_CLUB", "E0001", "EV_036", "in_progress", "2026-10-01")
        result = recommendation_availability(self.connection, "E0001")
        self.assertEqual(result["reasons"][0]["code"], "in_progress")

    def test_empty_cohort_and_invalid_next_step_filter(self):
        result = hr_dashboard(self.connection, {"department": "No such department", "next_step": "missing"})
        self.assertEqual(result["summary"], {"employees": 0, "needs_support": 0, "competencies_with_gaps": 0, "without_next_step": 0})
        self.assertEqual(result["employees"], [])
        self.assertEqual(result["activity_participation"], [])
        with self.assertRaises(HrError):
            hr_dashboard(self.connection, {"next_step": "invalid"})

    def test_six_month_period_clamps_to_end_of_month(self):
        result = hr_dashboard(self.connection, {"department": "No such department"}, as_of_date="2026-08-31")
        self.assertEqual(result["support_period_start"], "2026-02-28")
        self.assertEqual(result["as_of_date"], "2026-08-31")


if __name__ == "__main__":
    unittest.main()
