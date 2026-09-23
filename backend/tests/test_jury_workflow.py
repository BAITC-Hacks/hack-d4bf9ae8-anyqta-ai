"""Regression checks for the jury path, factual context, caching and goal changes."""
import csv
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.bootstrap import bootstrap
from backend.app.career import calculate_trajectory
from backend.app.db import connect
from backend.app.hr import HrError, hr_dashboard
from backend.app.importer import import_package, load_profile_package
from backend.app.recommendation_service import RecommendationService, data_revision
from backend.app.recommendations import eligible_candidates, recommend_employee, selector_from_environment
from backend.app.web import WebApplication
from scripts.evaluate_recommendations import evaluate

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'data/career_quest_dataset'
JURY = ROOT / 'examples/jury'
SECRET = 'jury-tests-secret-with-more-than-32-characters'


class RecordingSelector:
    def __init__(self):
        self.calls = []

    def select(self, facts):
        self.calls.append(facts)
        choice = facts['candidates'][0]
        return {'recommendations': [{'event_id': choice['event_id'],
                 'reason_ids': [item['id'] for item in choice['decision_factors'][:2]]}]}


class JuryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_directory = tempfile.TemporaryDirectory()
        cls.seed_path = Path(cls.seed_directory.name) / 'seed.db'
        bootstrap(cls.seed_path, DATASET)

    @classmethod
    def tearDownClass(cls):
        cls.seed_directory.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'test.db'
        self.connection = connect(self.path)
        source = connect(self.seed_path)
        source.backup(self.connection)
        source.close()
        self.selector = RecordingSelector()
        self.service = RecommendationService(lambda: self.selector)
        self.app = WebApplication(self.path, SECRET, recommendation_service=self.service)
        self.employee, _ = self.app.login('junior@careerquest.demo', 'DemoEmployee2026!')
        self.hr, _ = self.app.login('hr@careerquest.demo', 'DemoHR2026!')

    def tearDown(self):
        self.connection.close()
        self.directory.cleanup()

    def upload(self, preview=False, employees=None, history=None):
        return self.app.import_hr_profiles(self.hr,
            employees if employees is not None else (JURY / 'employees.json').read_text(),
            history if history is not None else (JURY / 'activity_history.csv').read_text(), preview)

    def test_employee_hr_use_same_ai_and_cached_explanations(self):
        employee = self.app.employee_recommendations(self.employee)
        hr = self.app.hr_recommendations(self.hr, self.employee.employee_id)
        self.assertEqual(employee['mode'], 'llm')
        self.assertEqual(employee['recommendations'], hr['recommendations'])
        self.assertTrue(hr['cached'])
        self.assertEqual(len(self.selector.calls), 1)
        self.assertGreaterEqual(len(hr['recommendations'][0]['selected_reasons']), 2)

    def test_preview_is_read_only_and_retry_reports_actual_new_counts(self):
        before = data_revision(self.connection)
        preview = self.upload(preview=True)
        self.assertEqual(preview['employees_imported'], 3)
        self.assertEqual(data_revision(self.connection), before)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 200)
        imported = self.upload()
        retry = self.upload()
        self.assertEqual(imported['employees_imported'], 3)
        self.assertEqual(retry['employees_imported'], 0)
        self.assertEqual(retry['history_records_imported'], 0)
        self.assertEqual(retry['employees_skipped'], 3)
        self.assertEqual(retry['history_records_skipped'], 9)
        for profile in imported['profiles']:
            result = self.app.hr_recommendations(self.hr, profile['employee_id'])
            self.assertEqual(result['mode'], 'llm')
            self.assertTrue(result['recommendations'])

    def test_invalid_goal_and_fractional_skill_leave_whole_package_unchanged(self):
        for field in ('goal', 'role', 'skill', 'completed'):
            profiles = json.loads((JURY / 'employees.json').read_text())
            history = (JURY / 'activity_history.csv').read_text()
            if field == 'goal': profiles['employees'][-1]['career_goal']['target_role'] = 'Missing Role'
            if field == 'role': profiles['employees'][-1]['role'] = 'Missing Role'
            if field == 'skill': profiles['employees'][-1]['skills']['SK_SYSTEM_DESIGN'] = 1.7
            if field == 'completed': history = history.replace('completed,100', 'completed,0')
            for preview in (True, False):
                with self.subTest(field=field, preview=preview), self.assertRaises(HrError):
                    self.upload(preview, json.dumps(profiles), history)
            self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 200)
            self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM activity_history').fetchone()[0], 2743)
            self.assertEqual(self.app.hr_overview(self.hr, {})['summary']['employees'], 200)

    def test_csv_wrong_column_count_reports_line(self):
        history = (JURY / 'activity_history.csv').read_text().splitlines()
        history[1] += ',unexpected'
        with self.assertRaisesRegex(HrError, 'CSV line 2'):
            self.upload(True, history='\n'.join(history))

    def test_wrong_json_field_types_report_validation_error(self):
        for field in ('grade', 'manager_id', 'career_goal'):
            profiles = json.loads((JURY / 'employees.json').read_text())
            profiles['employees'][0][field] = [] if field != 'career_goal' else {'target_role': 'Backend Engineer', 'target_grade': []}
            with self.subTest(field=field), self.assertRaises(HrError):
                self.upload(True, employees=json.dumps(profiles))

    def test_import_rechecks_conflict_after_preview(self):
        self.upload(True)
        self.upload()
        changed = json.loads((JURY / 'employees.json').read_text())
        changed['employees'][0]['full_name'] = 'Different synthetic profile'
        with self.assertRaises(HrError): self.upload(employees=json.dumps(changed))
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 203)

    def test_model_context_contains_topics_history_and_no_name(self):
        self.upload()
        self.app.hr_recommendations(self.hr, 'JURY_CONTEXT_1')
        facts = self.selector.calls[-1]
        self.assertEqual(facts['profile']['grade'], 'Middle')
        self.assertNotIn('full_name', facts['profile'])
        candidates = {item['event_id']: item for item in facts['candidates']}
        self.assertIn('SK_SYSTEM_DESIGN', {item['skill_id'] for item in candidates['EV_006']['expected_skill_changes']})
        self.assertEqual(candidates['EV_036']['negative_similar'], 3)
        self.assertEqual(candidates['EV_006']['negative_similar'], 0)
        self.assertEqual(candidates['EV_036']['recent_related_history'][0]['status'], 'no_show')
        self.assertTrue(candidates['EV_006']['description'])

    def test_unrelated_workshop_history_does_not_penalize_architecture(self):
        self.upload()
        before = next(item for item in eligible_candidates(self.connection, 'JURY_CONTEXT_1') if item.event_id == 'EV_006')
        with self.connection:
            self.connection.execute("INSERT INTO activity_history VALUES ('UNRELATED', 'JURY_CONTEXT_1', 'EV_040', '2026-09-20', NULL, 'no_show', 0, NULL, NULL, 'self', '{}')")
        after = next(item for item in eligible_candidates(self.connection, 'JURY_CONTEXT_1') if item.event_id == 'EV_006')
        self.assertEqual(before.negative_similar, after.negative_similar)
        self.assertEqual(before.score, after.score)

    def test_goal_choice_preserves_imported_source_and_reset_restores_goal(self):
        before = self.app.employee_dashboard(self.employee)['trajectory']
        source = self.connection.execute("SELECT source_json FROM employees WHERE employee_id='E0001'").fetchone()[0]
        self.app.employee_recommendations(self.employee)
        self.app.change_goal(self.employee, 'Backend Engineer', 'Senior')
        changed = self.app.employee_dashboard(self.employee)['trajectory']
        self.assertEqual(changed['target']['grade'], 'Senior')
        self.assertEqual(self.connection.execute("SELECT source_json FROM employees WHERE employee_id='E0001'").fetchone()[0], source)
        self.assertFalse(self.app.employee_recommendations(self.employee)['cached'])
        self.app.reset_demo_progress(self.employee)
        self.assertEqual(self.app.employee_dashboard(self.employee)['trajectory']['target'], before['target'])
        with self.assertRaises(ValueError): self.app.change_goal(self.employee, 'Unknown', 'Senior')
        self.assertEqual(self.app.employee_dashboard(self.employee)['trajectory']['target'], before['target'])

    def test_completion_reset_and_catalog_change_invalidate_cache(self):
        self.app.employee_recommendations(self.employee)
        self.assertTrue(self.app.employee_recommendations(self.employee)['cached'])
        enrollment = self.app.enroll(self.employee, 'EV_005')['enrollment']
        self.assertFalse(self.app.employee_recommendations(self.employee)['cached'])
        self.app.complete_demo_enrollment(self.employee, enrollment['enrollment_id'])
        self.assertFalse(self.app.employee_recommendations(self.employee)['cached'])
        self.app.reset_demo_progress(self.employee)
        self.assertFalse(self.app.employee_recommendations(self.employee)['cached'])
        with self.connection: self.connection.execute("UPDATE events SET duration_hours=17 WHERE event_id='EV_005'")
        self.assertFalse(self.app.employee_recommendations(self.employee)['cached'])

    def test_dashboard_does_not_wait_for_ai_and_stale_result_is_discarded(self):
        entered, release = threading.Event(), threading.Event()
        selector = self.selector
        class BlockedSelector:
            def select(self, facts):
                entered.set()
                release.wait(3)
                return selector.select(facts)
        self.app.recommendation_service = RecommendationService(lambda: BlockedSelector())
        result = []
        worker = threading.Thread(target=lambda: result.append(self.app.employee_recommendations(self.employee)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            start = time.perf_counter()
            self.app.employee_dashboard(self.employee)
            self.app.hr_employee(self.hr, self.employee.employee_id)
            self.assertLess(time.perf_counter() - start, 2)
            self.app.change_goal(self.employee, 'Backend Engineer', 'Senior')
        finally:
            release.set()
            worker.join(4)
        self.assertEqual(result[0]['mode'], 'stale')
        self.assertEqual(result[0]['recommendations'], [])

    def test_timeout_invalid_evidence_and_partial_configuration_fall_back(self):
        class SlowSelector:
            def select(self, facts):
                time.sleep(.08)
                return {'recommendations': []}
        result = recommend_employee(self.connection, 'E0001', selector=SlowSelector(), timeout_seconds=.01)
        self.assertEqual(result['mode'], 'rules_fallback')
        self.assertTrue(result['fallback_reason'])
        class InventedEvidence:
            def select(self, facts):
                return {'recommendations': [{'event_id': facts['candidates'][0]['event_id'], 'reason_ids': ['target', 'invented']}]}
        self.assertEqual(recommend_employee(self.connection, 'E0001', selector=InventedEvidence())['mode'], 'rules_fallback')
        with patch.dict(os.environ, {'LLM_API_URL': 'https://example.invalid', 'LLM_API_KEY': '', 'LLM_MODEL': ''}):
            result = RecommendationService(selector_from_environment).get(self.connection, 'E0001')
            self.assertEqual(result['mode'], 'rules_fallback')
            self.assertIn('не полностью', result['fallback_reason'])

    def test_forecast_does_not_double_count_capped_gain(self):
        self.upload()
        result = recommend_employee(self.connection, 'JURY_CONTEXT_1')
        self.assertEqual(result['plan']['steps'][-1]['coverage_after'], result['plan']['coverage_after'])
        system_levels = [change['after_level'] for step in result['plan']['steps'] for change in step['skill_changes'] if change['skill_id'] == 'SK_SYSTEM_DESIGN']
        self.assertEqual(system_levels, [3, 4])
        self.assertTrue(all(step['additional_gap_reduction'] > 0 for step in result['plan']['steps']))
        self.assertLessEqual(result['plan']['coverage_after'], 100)
        self.assertEqual(calculate_trajectory(self.connection, 'JURY_CONTEXT_1')['effective_skills']['SK_SYSTEM_DESIGN'], 2)

    def test_new_endpoints_enforce_roles(self):
        for action in (lambda: self.app.hr_recommendations(self.employee, 'E0002'),
                       lambda: self.app.import_hr_profiles(self.employee, '{}', '', True),
                       lambda: self.app.change_goal(self.hr, 'Backend Engineer', 'Senior'),
                       lambda: self.app.employee_recommendations(self.hr)):
            with self.assertRaises(PermissionError): action()

    def test_hr_metrics_filter_and_legacy_bad_profile_is_isolated(self):
        overview = self.app.hr_overview(self.hr, {'department': 'Backend Development'})
        self.assertTrue(overview['department_gaps'])
        self.assertTrue(all(item['department'] == 'Backend Development' for item in overview['department_gaps']))
        self.assertEqual(sum(item['employees'] for item in overview['department_gaps']), overview['summary']['employees'])
        expected = self.connection.execute("SELECT COUNT(*) FROM activity_history h JOIN employees p USING(employee_id) JOIN events e USING(event_id) WHERE p.department='Backend Development' AND e.mandatory=0 AND h.status='completed' AND h.activity_date BETWEEN '2025-11-01' AND '2026-10-01'").fetchone()[0]
        self.assertEqual(sum(item['completed'] for item in overview['participation_trend']), expected)
        self.assertEqual(len(overview['participation_trend']), 12)
        with self.connection:
            self.connection.execute("UPDATE employees SET target_role='Legacy Unknown', target_grade='Senior' WHERE employee_id='E0001'")
        overview = self.app.hr_overview(self.hr, {})
        self.assertEqual(overview['invalid_profiles'][0]['employee_id'], 'E0001')
        self.assertEqual(overview['summary']['employees'], 199)

    def test_authored_quality_cases_outperform_minimum_skill_rule(self):
        report = evaluate()
        self.assertEqual(report['summary']['rules']['acceptable_first'], 3)
        self.assertEqual(report['summary']['minimum_skill']['acceptable_first'], 1)
        self.assertFalse(report['live_ai_tested'])
