"""Admin publication and real QR admission, against disposable synthetic data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class MobilePublicationTests(unittest.TestCase):
    def test_publish_boundaries_and_qr_admission(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="lgu-publish-") as directory:
            home = Path(directory)
            private = home / "lgu-preview-private"
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), LGU_APP_ENV="development")
            create = subprocess.run([sys.executable, str(repo / "app/scripts/create_preview_demo.py"),
                                     "--output-dir", str(private)], env=env, capture_output=True, text=True)
            self.assertEqual(create.returncode, 0, create.stderr)
            creds = dict(line.split(": ", 1) for line in
                         (private / "TEST-LOGIN-DETAILS.txt").read_text().splitlines() if ": " in line)
            code = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from scripts.pythonanywhere_preview_wsgi import application
v = json.load(sys.stdin)
c = application.test_client()
admin = {"X-Admin-Pin": v["Admin PIN"]}
assert c.get("/api/admin/student-event").status_code == 401
assert c.post("/api/admin/student-event/publish").status_code == 401
assert c.post("/api/admin/student-announcements", json={"title":"x","body":"x"}).status_code == 401
assert c.put("/api/admin/student-event", json={"name": []}, headers=admin).status_code == 400
assert c.put("/api/admin/student-event", json={"id": "1"}, headers=admin).status_code == 400
before = c.get("/api/student/event").json
assert before["event"] is None
save = c.put("/api/admin/student-event", json={"name":"LGU Convocation 2026", "expected_date":"2026-12-12", "confirmed_date":"", "ceremony_time":"09:00", "venue":"Synthetic test venue", "instructions":"Test schedule only."}, headers=admin)
assert save.status_code == 200, save.json
assert save.json["published"] is None
assert c.get("/api/student/event").json["event"] is None
published = c.post("/api/admin/student-event/publish", headers=admin)
assert published.status_code == 200, published.json
assert not published.json["has_changes"]
public = c.get("/api/student/event").json
assert public["convocation"]["name"] == "LGU Convocation 2026"
assert public["event"]["date_state"] == "expected"
assert public["event"]["confirmed_date"] is None
assert c.put("/api/admin/student-event", json={"name":"Unpublished draft"}, headers=admin).status_code == 200
assert c.get("/api/student/event").json["convocation"]["name"] == "LGU Convocation 2026"
assert c.post("/api/admin/student-announcements", json={"title":[],"body":"x"}, headers=admin).status_code == 400
update = c.post("/api/admin/student-announcements", json={"title":"Test update","body":"Synthetic acceptance message."}, headers=admin)
assert update.status_code == 200, update.json
feed = c.get("/api/student/announcements").json
assert any(a["id"] == update.json["id"] for a in feed["announcements"])
student = c.post("/api/student/login", json={"email":v["Student email"],"password":v["Student password"]}).json
student_headers = {"Authorization":"Bearer " + student["token"]}
assert c.get("/api/student/pass", headers=student_headers).json["pass"]["state"] == "eligible"
issued = c.post("/api/student/pass/issue", headers=student_headers)
assert issued.status_code == 200, issued.json
scanner = c.post("/api/scanner/login", json={"username":v["Scanner username"],"pin":v["Scanner PIN"]}).json
scan_headers = {"X-Scanner-Token": scanner["token"]}
scan = {"payload":issued.json["pass"]["payload"], "gate_id":1, "mode":"entry", "occasion":"ceremony", "volunteer":"ignored-client-identity"}
first = c.post("/api/scan", json=scan, headers=scan_headers)
assert first.status_code == 200 and first.json["level"] == "green", first.json
second = c.post("/api/scan", json=scan, headers=scan_headers)
assert second.status_code == 200 and second.json["level"] != "green", second.json
print("PASS: admin-only draft/publication, provisional dates, student feed, real QR admission and duplicate refusal")
'''
            result = subprocess.run([sys.executable, "-c", code, str(repo / "app")],
                                    input=json.dumps(creds), env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("PASS:", result.stdout)
            fixture = subprocess.run([sys.executable,
                str(repo / "app/scripts/prepare_hosted_demo_content.py"),
                "--publish-synthetic-demo"], env=env, capture_output=True, text=True)
            self.assertEqual(fixture.returncode, 0, fixture.stderr)
            self.assertIn("DEMO-HOST-001", fixture.stdout)


if __name__ == "__main__":
    unittest.main()
