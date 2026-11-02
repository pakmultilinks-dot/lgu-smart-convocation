"""Focused API test for authenticated manual attendance and event context."""

import os
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-manual-attendance-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "manual.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import ids  # noqa: E402
import models  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402


database.init_db()
with database.connection() as db:
    db.executemany("INSERT INTO gates (code, label) VALUES (?, ?)", database.GATE_LABELS)
    db.commit()
models.add_students([("MAN-001", "Manual Student", "Male", "BSc")])
models.assign_ids(models.all_students(), ids.generate_id)
guest_id, error = models.register_guest(
    "Manual Guest", "03001112233", "MAN-001", ids.generate_id)
if error:
    raise AssertionError(error)

app = create_app()
client = app.test_client()
headers = scanner_headers(client, gate_ids=[1])

unauthorized = client.post("/api/manual-attendance", json={
    "type": "student", "roll_no": "MAN-001", "gate_id": 1,
    "mode": "entry", "occasion": "ceremony",
})
assert unauthorized.status_code == 401

student_body = {
    "type": "student", "roll_no": "MAN-001", "gate_id": 1,
    "mode": "entry", "occasion": "rehearsal",
}
student_entry = client.post(
    "/api/manual-attendance", json=student_body, headers=headers)
assert student_entry.status_code == 200
assert student_entry.get_json()["status"] == "ok"
student_qr = models.all_students()[0]["qr_id"]
student_scan = models.last_scan(student_qr)
assert student_scan["source"] == "manual"
assert student_scan["occasion"] == "rehearsal"
assert student_scan["volunteer"]

duplicate = client.post(
    "/api/manual-attendance", json=student_body, headers=headers)
assert duplicate.get_json()["title"] == "ALREADY INSIDE"
student_exit = client.post(
    "/api/manual-attendance",
    json={**student_body, "mode": "exit", "occasion": "ceremony"},
    headers=headers,
)
assert student_exit.status_code == 200
assert student_exit.get_json()["title"] == "EXIT RECORDED"
assert models.last_scan(student_qr)["occasion"] == "ceremony"

guest_entry = client.post(
    "/api/manual-attendance",
    json={"type": "guest", "gid": guest_id, "gate_id": 1,
          "mode": "entry", "occasion": "ceremony"},
    headers=headers,
)
assert guest_entry.status_code == 200
assert guest_entry.get_json()["title"] == "GUEST ENTRY RECORDED"
guest = models.guest_by_id(guest_id)
guest_exit = client.post(
    "/api/manual-attendance",
    json={"type": "guest", "gid": guest_id, "gate_id": 1,
          "mode": "exit", "occasion": "ceremony"},
    headers=headers,
)
assert guest_exit.status_code == 200
assert guest_exit.get_json()["title"] == "GUEST EXIT RECORDED"
search = client.get("/api/search?q=Manual%20Guest", headers=headers).get_json()
match = next(row for row in search["results"] if row["type"] == "guest")
assert match["used"] is True and match["inside"] is False
assert "qr_id" not in match
assert models.last_scan(guest["qr_id"])["source"] == "manual"

reentry = client.post(
    "/api/manual-attendance",
    json={"type": "guest", "gid": guest_id, "gate_id": 1,
          "mode": "entry", "occasion": "ceremony"},
    headers=headers,
)
assert reentry.get_json()["title"] == "ALREADY USED"

wrong_gate = client.post(
    "/api/manual-attendance",
    json={**student_body, "gate_id": 2},
    headers=headers,
)
assert wrong_gate.status_code == 403

print("PASS: authenticated manual attendance preserves gate, movement, event and volunteer")
