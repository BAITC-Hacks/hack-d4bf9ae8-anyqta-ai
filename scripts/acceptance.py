#!/usr/bin/env python3
"""Offline HTTP acceptance against a fresh, isolated Career Quest database."""
import http.cookiejar
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.bootstrap import bootstrap
from backend.app.db import connect
from backend.app.demo_seed import DEMO_USERS, EMPLOYEE_PASSWORD, HR_PASSWORD
from backend.app.recommendation_service import RecommendationService
from backend.app.web import serve


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, payload=None, expected=200):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            response = self.opener.open(request, timeout=12)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            result = json.loads(body) if body else {}
            require(response.status == expected, f'{path}: expected {expected}, got {response.status}: {result}')
            return result


def run_acceptance():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'acceptance.db'
        require(bootstrap(database, ROOT / 'data/career_quest_dataset'), 'Fresh bootstrap failed')
        connection = connect(database)
        try:
            counts = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('employees', 'skills', 'events', 'activity_history', 'users')}
        finally:
            connection.close()
        require(counts == {'employees': 200, 'skills': 60, 'events': 40, 'activity_history': 2743, 'users': 5}, 'Wrong seed counts')
        server = serve(database, port=0, session_secret='acceptance-secret-longer-than-32-characters', demo_mode=True)
        server.RequestHandlerClass.application.recommendation_service = RecommendationService(lambda: None)
        server.RequestHandlerClass.log_message = lambda *args: None
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        try:
            anonymous = Client(base)
            require(anonymous.call('/api/health')['ready'], 'Service not ready')
            anonymous.call('/api/employee/recommendations', expected=401)
            clients = {}
            for username, role, employee_id in DEMO_USERS:
                client = Client(base)
                result = client.call('/api/login', {'username': username, 'password': EMPLOYEE_PASSWORD if role == 'employee' else HR_PASSWORD})
                require(result['access_role'] == role, f'Login failed for {username}')
                clients[username] = client
                if role == 'employee':
                    profile = client.call('/api/employee/dashboard')['trajectory']['employee']['employee_id']
                    require(profile == employee_id, 'Employee binding failed')
            employee = clients['junior@careerquest.demo']
            hr = clients['hr@careerquest.demo']
            start = time.perf_counter()
            dashboard = employee.call('/api/employee/dashboard?employee_id=E0002')
            employee_seconds = time.perf_counter() - start
            require(employee_seconds < 2 and dashboard['trajectory']['employee']['employee_id'] == 'E0001', 'Dashboard latency or isolation failed')
            employee.call('/api/hr/employees/E0002/recommendations', expected=403)
            employee.call('/api/hr/import/preview', {'employees_json': '{}', 'history_csv': ''}, expected=403)
            hr.call('/api/employee/goal', {'role': 'Backend Engineer', 'grade': 'Senior'}, expected=403)
            start = time.perf_counter()
            recommendation = employee.call('/api/employee/recommendations')
            recommendation_seconds = time.perf_counter() - start
            require(recommendation['mode'] == 'rules_fallback' and recommendation['recommendations'], 'Offline recommendations failed')
            employee.call('/api/employee/goal', {'role': 'Backend Engineer', 'grade': 'Senior'})
            require(employee.call('/api/employee/dashboard')['trajectory']['target']['grade'] == 'Senior', 'Goal change failed')
            employee.call('/api/employee/demo-reset', {})
            enrollment = employee.call('/api/employee/activities/EV_005/enroll', {}, expected=201)['enrollment']
            completion_path = f"/api/employee/enrollments/{enrollment['enrollment_id']}/complete"
            clients['middle@careerquest.demo'].call(completion_path, {}, expected=400)
            completed = employee.call(completion_path, {})
            require(completed['coverage_after'] > completed['coverage_before'], 'No progress after completion')
            employee.call(completion_path, {}, expected=400)
            employee.call('/api/employee/demo-reset', {})
            require(employee.call('/api/employee/dashboard')['trajectory']['coverage_percent'] == dashboard['trajectory']['coverage_percent'], 'Reset did not restore progress')
            package = {'employees_json': (ROOT / 'examples/jury/employees.json').read_text(), 'history_csv': (ROOT / 'examples/jury/activity_history.csv').read_text()}
            preview = hr.call('/api/hr/import/preview', package)
            require(preview['employees_imported'] == 3, 'Preview failed')
            require(hr.call('/api/hr/dashboard')['summary']['employees'] == 200, 'Preview mutated DB')
            imported = hr.call('/api/hr/import', package, expected=201)
            require(imported['employees_imported'] == 3, 'Jury import failed')
            for profile in imported['profiles']:
                identifier = profile['employee_id']
                require(hr.call(f'/api/hr/employees/{identifier}')['history'], 'Imported history missing')
                require(hr.call(f'/api/hr/employees/{identifier}/recommendations')['recommendations'], 'Imported recommendations missing')
            retry = hr.call('/api/hr/import', package, expected=201)
            require(retry['employees_imported'] == 0 and retry['employees_skipped'] == 3, 'Import is not idempotent')
            bad = json.loads(package['employees_json'])
            bad['employees'][0]['career_goal']['target_role'] = 'Missing Role'
            hr.call('/api/hr/import', {**package, 'employees_json': json.dumps(bad)}, expected=400)
            start = time.perf_counter()
            overview = hr.call('/api/hr/dashboard')
            hr_seconds = time.perf_counter() - start
            require(hr_seconds < 2 and overview['summary']['employees'] == 203, 'HR overview failed')
            require(overview['department_gaps'] and len(overview['participation_trend']) == 12, 'HR analytics missing')
            require(not bootstrap(database, ROOT / 'data/career_quest_dataset'), 'Restart reimported source data')
            require(hr.call('/api/hr/dashboard')['summary']['employees'] == 203, 'Restart lost jury profiles')
            employee.call('/api/logout', {}, expected=204)
            employee.call('/api/employee/dashboard', expected=401)
            return {'result': 'passed', 'transport': 'localhost HTTP', 'live_ai_tested': False,
                    'dataset_counts': counts, 'employee_dashboard_seconds': round(employee_seconds, 4),
                    'hr_dashboard_seconds': round(hr_seconds, 4), 'offline_recommendations_seconds': round(recommendation_seconds, 4),
                    'checked': ['readiness', 'five_logins', 'role_and_employee_isolation', 'goal_change',
                                'completion_once', 'personal_reset', 'jury_preview_import_retry',
                                'imported_profile_recommendations', 'invalid_import_rollback', 'hr_analytics',
                                'restart_preserves_data', 'logout']}
        finally:
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()


if __name__ == '__main__':
    try:
        print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
    except Exception as error:
        print(f'Acceptance failed: {error}', file=sys.stderr)
        raise SystemExit(1)
