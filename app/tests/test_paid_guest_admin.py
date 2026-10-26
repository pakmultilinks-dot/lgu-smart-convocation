"""Admin publication and real QR admission, against disposable synthetic data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PaidGuestAdminTests(unittest.TestCase):
    def test_paid_guest_authorization_and_payment_evidence(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="lgu-publish-") as directory:
            home = Path(directory)
            private = home / "lgu-preview-private"
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), LGU_APP_ENV="development", LGU_PIN_MAX_FAILS="100")
            create = subprocess.run([sys.executable, str(repo / "app/scripts/create_preview_demo.py"),
                                     "--output-dir", str(private)], env=env, capture_output=True, text=True)
            self.assertEqual(create.returncode, 0, create.stderr)
            creds = dict(line.split(": ", 1) for line in
                         (private / "TEST-LOGIN-DETAILS.txt").read_text().splitlines() if ": " in line)
            code = '''
import json,sys
sys.path.insert(0,sys.argv[1])
from scripts.pythonanywhere_preview_wsgi import application
import database, models, ids
v=json.load(sys.stdin); c=application.test_client(); admin={"X-Admin-Pin":v["Admin PIN"]}
models.add_students([("PAID-HOST-A","Host A","Male","Test"),("PAID-HOST-B","Host B","Female","Test")])
s=c.post("/api/scanner/login",json={"username":v["Scanner username"],"pin":v["Scanner PIN"]}).json
scanner={"X-Scanner-Token":s["token"]}
st=c.post("/api/student/login",json={"email":v["Student email"],"password":v["Student password"]}).json
student={"Authorization":"Bearer "+st["token"]}
body={"name":"Paid Guest A","phone":"03001234567","host_roll_no":"PAID-HOST-A","payment_reference":" RECEIPT-123 ","payment_verified":True}
for headers in ({},scanner,student):
 for path in ("/api/guests","/api/admin/guests"):
  assert c.post(path,json=body,headers=headers).status_code==401
 assert c.post("/api/guests/1/revoke",headers=headers).status_code==401
assert b'Guest full name' not in c.get("/guests").data
for bad in ({},[],{**body,"payment_verified":False},{**body,"payment_verified":"true"},{**body,"payment_reference":""}):
 assert c.post("/api/admin/guests",json=bad,headers=admin).status_code==400
# Administrative issuance remains possible while scanning is paused.
assert c.put("/api/settings",json={"volunteer_enabled":"false"},headers=admin).status_code==200
issued=c.post("/api/admin/guests",json=body,headers=admin)
assert issued.status_code==200,issued.json
gid=issued.json["gid"]
assert "payload" not in issued.json
assert c.get("/api/admin/guest-pass/"+str(gid),headers=admin).status_code==200
assert c.get("/api/admin/guest-pass/"+str(gid),headers=scanner).status_code==401
assert c.get("/api/admin/guests",headers=admin).status_code==200
again={**body,"name":"Paid Guest B","host_roll_no":"PAID-HOST-B","payment_reference":"receipt-123"}
assert c.post("/api/admin/guests",json=again,headers=admin).status_code==400
with database.connection() as db:
 rows=db.execute("SELECT actor,detail FROM audit_log WHERE action='paid_guest_issued'").fetchall()
 assert len(rows)==1 and rows[0]["actor"]=="mobile-administrator"
 detail=json.loads(rows[0]["detail"])
 assert detail["guest_id"]==gid and detail["payment_reference"]=="RECEIPT-123"
 assert detail["verification"]=="administrator_attested"
assert c.post("/api/admin/guests/"+str(gid)+"/revoke",headers=admin).status_code==200
with database.connection() as db:
 assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='guest_pass_revoked'").fetchone()[0]==1
print("PASS: anonymous/student/scanner denial, admin paid issuance while paused, receipt audit/reuse refusal and admin-only revocation")
'''
            result = subprocess.run([sys.executable, "-c", code, str(repo / "app")],
                                    input=json.dumps(creds), env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("PASS:", result.stdout)



if __name__ == "__main__":
    unittest.main()
