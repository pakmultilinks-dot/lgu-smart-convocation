"""Exercise persistent dashboard switches against an isolated database."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = tempfile.TemporaryDirectory(prefix="lgu-dashboard-access-")
os.environ.update(LGU_TESTING="1", LGU_DB_PATH=str(Path(root.name) / "test.db"),
                  LGU_EMAIL_MODE="fake")
import config
import database
import student_auth
import emailer
import exam_registrations
from web.routes import create_app

database.init_db()
database.seed()
client = create_app().test_client()
admin = {"X-Admin-Pin": config.ADMIN_PIN}

def access():
    result = client.get("/api/dashboard-access")
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json == client.get("/api/config").json["dashboard_access"]
    return result.json

def save(**values):
    response = client.put("/api/settings", json=values, headers=admin)
    assert response.status_code == 200, response.json

assert access() == {"student": True, "volunteer": True, "liveboard": True}
preflight = client.options("/api/scan", headers={
    "Origin": "http://localhost:8081", "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "Content-Type,X-Scanner-Token"})
assert preflight.status_code == 200
assert "X-Scanner-Token" in preflight.headers["Access-Control-Allow-Headers"]
assert preflight.headers["Access-Control-Allow-Origin"] == "http://localhost:8081"
assert client.put("/api/settings", json={"volunteer_enabled": "false"}).status_code == 401
for value in [True, False, None, 1, "yes", "TRUE", {}, []]:
    assert client.put("/api/settings", json={"volunteer_enabled": value}, headers=admin).status_code == 400
assert client.put("/api/settings", json={"student_enabled": "false"}, headers=admin).status_code == 400
assert access()["student"] is True
save(volunteer_enabled="false")
for route in ["/api/scan", "/api/sync", "/api/scanner/login", "/api/guests"]:
    body = {"username": "operator", "pin": "ABCDEFGH"} if route == "/api/scanner/login" else {}
    result = client.post(route, json=body)
    assert result.status_code == 403, (route, result.status_code)
    assert result.json["code"] == "dashboard_disabled"
for route in ["/scan", "/guests", "/api/guests", "/api/search", "/api/guest-pass/1", "/api/dashboard/summary"]:
    assert client.get(route).status_code == 403, route
assert client.get("/api/dashboard").status_code == 200
save(liveboard_enabled="false")
for route in ["/dashboard", "/api/dashboard"]:
    assert client.get(route).status_code == 403
assert client.get("/api/settings", headers=admin).status_code == 200
assert client.post("/api/admin/verify", json={"pin": config.ADMIN_PIN}).status_code == 200
assert client.get("/api/health").status_code == 200
# New app instance reads saved state, rather than process-local defaults.
assert create_app().test_client().get("/api/config").json["dashboard_access"] == {
    "student": True, "volunteer": False, "liveboard": False}
with database.connection() as db:
    student_auth.create_account(db, "switch.test@example.invalid", "StrongPassword123!")
    db.commit()
login = client.post("/api/student/login", json={
    "email": "switch.test@example.invalid", "password": "StrongPassword123!"})
assert login.status_code == 200, login.json
token = login.json["token"]
assert client.get("/api/student/me", headers={"Authorization": "Bearer " + token}).status_code == 200
invalid = client.post("/api/student/verify", json={
    "registration_number": "UNREGISTERED", "university_email": "other@example.invalid",
    "roll_number": "UNREGISTERED", "student_name": "Unknown Student"})
assert invalid.status_code == 404 and invalid.json["code"] == "unmatched"
with database.connection() as db:
    conv = exam_registrations.active_convocation(db)
    now = exam_registrations.utc_now()
    db.execute("INSERT INTO convocation_registrations "
               "(convocation_id, registration_number, university_email, roll_number, "
               "student_name, department, status, created_at, updated_at) "
               "VALUES (?,?,?,?,?,?,?,?,?)",
               (conv["id"], "SWITCH-001", "eligible@example.invalid", "ROLL-001",
                "Eligible Student", "Test", "active", now, now))
    db.commit()
verified = client.post("/api/student/verify", json={
    "registration_number": "SWITCH-001", "university_email": "eligible@example.invalid",
    "roll_number": "ROLL-001", "student_name": "Eligible Student"})
assert verified.status_code == 200, verified.json
completed = client.post("/api/student/complete", json={
    "challenge_id": verified.json["challenge_id"], "code": emailer.OUTBOX[-1][1],
    "password": "StrongPassword123!"})
assert completed.status_code == 200, completed.json
save(volunteer_enabled="true")
assert client.get("/api/dashboard").status_code == 403
assert client.get("/api/search").status_code == 401  # normal scanner authentication restored
save(liveboard_enabled="true")
assert client.get("/api/dashboard").status_code == 200
print("PASS: authentication, strict switches, independent access, persistence, student login, eligible signup, registration restrictions and reopening")
root.cleanup()
