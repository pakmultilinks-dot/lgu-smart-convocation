"""Malformed auth JSON and independent client budgets; disposable data only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review_test_support  # noqa: E402,F401
import config  # noqa: E402
from web import routes, student_routes  # noqa: E402


class AuthShapeTests(unittest.TestCase):
    def setUp(self):
        self.app = routes.create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        student_routes._HITS.clear()
        student_routes._HITS.update({k: {} for k in student_routes._BUCKET_WINDOWS})
        routes._PIN_FAILS.clear()
        routes._SCAN_LOGIN_FAILS.clear()

    def test_auth_endpoints_reject_non_object_json_without_database_access(self):
        paths = ['/api/scanner/login', '/api/admin/verify'] + [
            '/api/student/' + p for p in ['verify', 'resend', 'complete', 'login',
                                          'recovery/request', 'recovery/complete']]
        with (
            patch.object(routes.database, 'get_db', side_effect=AssertionError('DB access on invalid auth input')),
            patch.object(student_routes.emailer, 'available', return_value=True),
        ):
            for path in paths:
                for payload in [[], ['bad'], 'bad', 42, True, None]:
                    with self.subTest(path=path, payload=payload):
                        for hits in student_routes._HITS.values():
                            hits.clear()
                        response = self.client.post(path, json=payload)
                        self.assertEqual(response.status_code, 400)
                        self.assertTrue(response.is_json)

    def test_admin_pin_must_be_text(self):
        for value in [[], {}, True, 42]:
            with self.subTest(value=value):
                self.assertEqual(self.client.post('/api/admin/verify', json={'pin': value}).status_code, 400)

    def test_untrusted_forwarded_headers_cannot_reset_a_client_budget(self):
        for index in range(3):
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.1'}, headers={'X-Forwarded-For': f'198.51.100.{index}'}):
                self.assertEqual(student_routes._limited('login', 2), index == 2)

    def test_one_client_cannot_exhaust_another_client_budget(self):
        for bucket in student_routes._BUCKET_WINDOWS:
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.1'}):
                self.assertFalse(student_routes._limited(bucket, 1))
                self.assertTrue(student_routes._limited(bucket, 1))
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.2'}):
                self.assertFalse(student_routes._limited(bucket, 1))

    def test_expired_clients_are_removed_and_budget_recovers(self):
        with patch.object(student_routes.time, 'time', return_value=1000):
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.1'}):
                self.assertFalse(student_routes._limited('login', 1))
        with patch.object(student_routes.time, 'time', return_value=1000 + config.STUDENT_RATE_WINDOW_SECONDS + 1):
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.2'}):
                self.assertFalse(student_routes._limited('login', 1))
            self.assertNotIn('192.0.2.1', student_routes._HITS['login'])

    def test_parallel_requests_cannot_overrun_one_client_budget(self):
        def hit(_):
            with self.app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.0.2.3'}):
                return student_routes._limited('login', 3)
        with ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = list(pool.map(hit, range(20)))
        self.assertEqual(verdicts.count(False), 3)


if __name__ == '__main__':
    unittest.main()
