"""Shared Phase 14 test fixture: mint an authenticated scanner session.

Tests that exercise /api/scan or /api/sync must authenticate like a real
volunteer device. This calls the non-production /api/test-scanner-session
helper (404 on the production DB) which provisions a random synthetic scanner
and returns an active session token — no credential is hardcoded anywhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def scanner_headers(client, gate_ids=None):
    """Return {"X-Scanner-Token": ...} for a scanner authorized on gate_ids.

    Defaults to all seven gates so existing fixtures keep their behavior."""
    if gate_ids is None:
        gate_ids = [1, 2, 3, 4, 5, 6, 7]
    r = client.post("/api/test-scanner-session", json={"gate_ids": gate_ids})
    body = r.get_json() or {}
    assert r.status_code == 200 and body.get("token"), \
        "test-scanner-session failed: %s %s" % (r.status_code, body)
    return {"X-Scanner-Token": body["token"]}