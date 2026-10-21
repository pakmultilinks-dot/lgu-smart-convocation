"""Browser-level regression tests using an isolated SQLite DB and real Chromium.

This suite intentionally imports create_app rather than app/run.py so the
repository's app/lgu.db is never opened or initialized.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import review_test_support as review_support  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402
from web.routes import create_app  # noqa: E402


class BrowserUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.production_path = APP_DIR / "lgu.db"
        cls.production_hash_before = (
            hashlib.sha256(cls.production_path.read_bytes()).hexdigest()
            if cls.production_path.exists()
            else None
        )
        cls.sandbox = tempfile.TemporaryDirectory(prefix="lgu-ui-qa-")
        cls.original_path = config.DB_PATH
        config.DB_PATH = os.path.join(cls.sandbox.name, "qa.sqlite")
        database.init_db()
        database.seed()
        cls.fixture_client = create_app().test_client()
        cls.scanner_token = review_support.authenticate(cls.fixture_client)
        cls.httpd = make_server("127.0.0.1", 0, create_app())
        cls.base_url = "http://127.0.0.1:%s" % cls.httpd.server_port
        cls.server_thread = threading.Thread(
            target=cls.httpd.serve_forever, daemon=True
        )
        cls.server_thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.httpd.shutdown()
        cls.server_thread.join(timeout=5)
        config.DB_PATH = cls.original_path
        cls.sandbox.cleanup()
        hash_after = (
            hashlib.sha256(cls.production_path.read_bytes()).hexdigest()
            if cls.production_path.exists()
            else None
        )
        if cls.production_hash_before != hash_after:
            raise AssertionError("Repository app/lgu.db changed during UI tests")

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.context.set_extra_http_headers({"X-Scanner-Token": self.scanner_token})
        self.page.add_init_script("sessionStorage.setItem('lgu_scanner_token', "
                                  + json.dumps(self.scanner_token) + ");"
                                  "sessionStorage.setItem('lgu_scanner_gates', '[1,2,3,4,5,6,7]');")
        serializer = self.fixture_client.application.session_interface.get_signing_serializer(self.fixture_client.application)
        self.page.context.add_cookies([{"name": "session", "value": serializer.dumps({"lgu_admin": True}), "url": self.base_url}])
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(error))

    def tearDown(self):
        self.page.close()
        self.assertEqual([], self.page_errors, "Uncaught browser exception")

    def test_home_navigation_to_all_primary_pages(self):
        page = self.page
        page.goto(self.base_url + "/")
        for path in (
            "/dashboard", "/scan", "/guests", "/broadcast", "/admin"
        ):
            page.goto(self.base_url + path)
            self.assertEqual(page.url, self.base_url + path)
            self.assertTrue(page.locator("h1").count() >= 1)

    def test_dashboard_renders_untrusted_values_as_text(self):
        payload = '<img data-qa-xss src=x onerror="window.__qaInjected=true">'
        data = {
            "inside_total": 1,
            "male": 1,
            "female": 0,
            "guests_inside": 0,
            "busiest_gate": payload,
            "generated_at": "2026-10-21 12:00:00",
            "throughput": [{"gate": {"label": payload}, "count": 1}],
            "sync": [{"gate": {"label": payload}, "last": None, "count": 1}],
            "feed": [{
                "scanned_at": "2026-10-21 12:00:00",
                "gate_label": payload,
                "mode": "entry",
                "person_name": payload,
                "person_type": "student",
                "source": "online",
            }],
        }
        page = self.page
        page.add_init_script("window.__qaInjected = false;")
        page.route(
            "**/api/dashboard",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(data),
            ),
        )
        page.goto(self.base_url + "/dashboard")
        page.wait_for_function(
            "document.getElementById('bars').textContent.includes('data-qa-xss')"
        )
        self.assertEqual(page.locator("#bars img").count(), 0)
        self.assertEqual(page.locator("#sync img").count(), 0)
        self.assertEqual(page.locator("#feed img").count(), 0)
        self.assertFalse(page.evaluate("window.__qaInjected"))
        self.assertEqual(page.locator("#k-inside").inner_text(), "1")
        self.assertIn("data-qa-xss", page.locator("#feed").inner_text())

    def test_scanner_queue_renders_payload_as_text(self):
        page = self.page
        page.add_init_script("window.__qaInjected = false;")
        page.goto(self.base_url + "/scan")
        hostile_value = (
            '<img data-qa-xss src=x onerror="window.__qaInjected=true">'
        )
        page.evaluate(
            """(payload) => localStorage.setItem(
                'lgu_scan_queue', JSON.stringify([{
                    payload: payload,
                    gate_id: 1,
                    mode: 'entry',
                    volunteer: 'Test',
                    scanned_at: '2026-10-21 12:00:00'
                }])
            )""",
            hostile_value,
        )
        page.reload()
        page.wait_for_function(
            "document.getElementById('qcount').textContent === '1'"
        )
        self.assertEqual(page.locator("#queue-list img").count(), 0)
        self.assertFalse(page.evaluate("window.__qaInjected"))
        self.assertIn("data-qa-xss", page.locator("#queue-list").inner_text())

    def test_scanner_button_states_and_offline_queue(self):
        page = self.page
        page.goto(self.base_url + "/scan")
        page.locator("#m-exit").click()
        self.assertIn("green", page.locator("#m-exit").get_attribute("class"))
        page.locator("#m-entry").click()
        self.assertIn("green", page.locator("#m-entry").get_attribute("class"))
        page.get_by_role("button", name="SCAN", exact=True).click()
        self.assertEqual(page.locator("#r-title").inner_text(), "EMPTY CODE")
        page.locator(".switch .slider").click()
        self.assertTrue(page.locator("#offline").is_checked())
        page.locator("#payload").fill("QA-QUEUED-CODE")
        page.get_by_role("button", name="SCAN", exact=True).click()
        self.assertEqual(page.locator("#qcount").inner_text(), "1")
        self.assertEqual(page.locator("#r-title").inner_text(), "QUEUED OFFLINE")
        page.get_by_role("button", name="Clear").click()
        self.assertEqual(page.locator("#payload").input_value(), "")

    def test_admin_roster_button_with_synthetic_data(self):
        page = self.page
        page.goto(self.base_url + "/admin")
        csv_data = (
            b"roll_no,name,gender,program\n"
            b"QA-TEST-0001,QA Test Student,Female,BSCS\n"
        )
        page.locator("#roster").set_input_files({
            "name": "qa-roster.csv",
            "mimeType": "text/csv",
            "buffer": csv_data,
        })
        page.get_by_role("button", name="Upload and assign IDs").click()
        self.assertIn("1 added", page.locator(".notice").inner_text())

    def test_broadcast_button_logs_on_isolated_database(self):
        page = self.page
        page.goto(self.base_url + "/broadcast")
        page.locator("#message").fill("QA browser test announcement")
        page.get_by_role("button", name="Send announcement").click()
        self.assertIn("Broadcast logged", page.locator(".notice").filter(has_text="Broadcast logged").inner_text())
        self.assertIn("QA browser test announcement", page.locator("main").inner_text())


    def _scanner_with_queue(self, payloads):
        """Use a fresh browser context with a synthetic offline scan queue."""
        page = self.page
        page.goto(self.base_url + "/scan")
        items = [
            {
                "payload": payload,
                "gate_id": 1,
                "mode": "entry",
                "volunteer": "QA",
                "scanned_at": "2026-10-21 12:00:00",
            }
            for payload in payloads
        ]
        page.evaluate(
            "(items) => localStorage.setItem('lgu_scan_queue', JSON.stringify(items))",
            items,
        )
        page.reload()
        self.assertEqual(page.locator("#qcount").inner_text(), str(len(items)))
        return page

    def test_sync_transport_error_does_not_discard_pending_scans(self):
        page = self._scanner_with_queue(["PENDING-A"])
        page.route("**/api/sync", lambda route: route.abort("failed"))
        page.get_by_role("button", name="Sync now").click()
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'SYNC FAILED'"
        )
        self.assertEqual(page.locator("#qcount").inner_text(), "1")
        self.assertEqual(
            page.evaluate("getQueue().map(item => item.payload)"), ["PENDING-A"]
        )

    def test_sync_http_error_does_not_discard_pending_scans(self):
        page = self._scanner_with_queue(["PENDING-A"])
        page.route(
            "**/api/sync",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "Server busy"}),
            ),
        )
        page.get_by_role("button", name="Sync now").click()
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'SYNC FAILED'"
        )
        self.assertEqual(page.locator("#qcount").inner_text(), "1")

    def test_sync_incomplete_verdicts_are_kept_for_retry(self):
        page = self._scanner_with_queue(["ACCEPTED", "RETRY", "NO-VERDICT"])
        response = {
            "synced": 1,
            "results": [
                {"payload": "ACCEPTED", "result": {
                    "status": "ok", "title": "ENTRY RECORDED"}},
                {"payload": "RETRY", "result": {
                    "status": "error", "title": "SERVER BUSY"}},
            ],
        }
        page.route(
            "**/api/sync",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(response),
            ),
        )
        page.get_by_role("button", name="Sync now").click()
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'SYNC PARTIAL'"
        )
        self.assertEqual(page.locator("#qcount").inner_text(), "2")
        self.assertEqual(
            page.evaluate("getQueue().map(item => item.payload)"),
            ["RETRY", "NO-VERDICT"],
        )

    def test_sync_terminal_rejections_are_reported_and_reconciled(self):
        page = self._scanner_with_queue(["DUPLICATE", "ACCEPTED"])
        response = {
            "synced": 1,
            "results": [
                {"payload": "DUPLICATE", "result": {
                    "status": "error", "title": "ALREADY INSIDE"}},
                {"payload": "ACCEPTED", "result": {
                    "status": "ok", "title": "ENTRY RECORDED"}},
            ],
        }
        page.route(
            "**/api/sync",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(response),
            ),
        )
        page.get_by_role("button", name="Sync now").click()
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'SYNC COMPLETE'"
        )
        self.assertEqual(page.locator("#qcount").inner_text(), "0")
        self.assertIn("1 rejected", page.locator("#r-sub").inner_text())

    def test_sync_does_not_erase_new_scan_queued_during_request(self):
        page = self._scanner_with_queue(["BEFORE-SYNC"])
        page.evaluate(
            """() => {
                const realFetch = window.fetch.bind(window);
                window.fetch = (url, init) => {
                    if (String(url).includes('/api/sync')) {
                        return new Promise(resolve => { window.__finishSync = resolve; });
                    }
                    return realFetch(url, init);
                };
            }"""
        )
        page.get_by_role("button", name="Sync now").click()
        page.wait_for_function("typeof window.__finishSync === 'function'")
        page.evaluate(
            """() => setQueue([...getQueue(), {
                payload: 'ARRIVED-LATER', gate_id: 1, mode: 'entry',
                volunteer: 'QA', scanned_at: '2026-10-21 12:00:02'
            }])"""
        )
        page.evaluate(
            """() => window.__finishSync({
                ok: true,
                json: async () => ({
                    synced: 1,
                    results: [{payload:'BEFORE-SYNC', result:{
                        status:'ok',title:'ENTRY RECORDED'
                    }}]
                })
            })"""
        )
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'SYNC PARTIAL'"
        )
        self.assertEqual(
            page.evaluate("getQueue().map(item => item.payload)"),
            ["ARRIVED-LATER"],
        )

    def test_scan_network_error_autoqueues_for_later_confirmation(self):
        page = self.page
        page.goto(self.base_url + "/scan")
        page.route("**/api/scan", lambda route: route.abort("failed"))
        page.locator("#payload").fill("UNKNOWN-DURING-OFFLINE")
        page.get_by_role("button", name="SCAN", exact=True).click()
        page.wait_for_function(
            "document.getElementById('r-title').textContent === 'QUEUED OFFLINE'"
        )
        self.assertEqual(page.locator("#qcount").inner_text(), "1")
        self.assertEqual(
            page.evaluate("getQueue()[0].payload"),
            "UNKNOWN-DURING-OFFLINE",
        )


if __name__ == "__main__":
    unittest.main()
