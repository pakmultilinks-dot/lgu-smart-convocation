"""Admin publication and real QR admission, against disposable synthetic data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class NativeAdminRecordsTests(unittest.TestCase):
    def test_native_record_management(self):
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
import database
v=json.load(sys.stdin); c=application.test_client(); admin={"X-Admin-Pin":v["Admin PIN"]}
scanner_token=c.post("/api/scanner/login",json={"username":v["Scanner username"],"pin":v["Scanner PIN"]}).json["token"]
student_token=c.post("/api/student/login",json={"email":v["Student email"],"password":v["Student password"]}).json["token"]
for kind in ("registrations","roster"):
 path="/api/admin/records/"+kind
 for headers in ({},{"X-Scanner-Token":scanner_token},{"Authorization":"Bearer "+student_token}):
  for method,suffix in (("get",""),("post",""),("put","/1")):
   assert getattr(c,method)(path+suffix,headers=headers).status_code==401
assert c.put("/api/settings",json={"volunteer_enabled":"false"},headers=admin).status_code==200
samples={"registrations":{"registration_number":"NATIVE-001","university_email":"native@example.invalid","roll_number":"000123","student_name":"Native Student","department":"Test"},"roster":{"roll_no":"000123","name":"Native Host","gender":"Male","program":"Test"}}
for kind,body in samples.items():
 path="/api/admin/records/"+kind
 for bad in ([],{},dict(body,unexpected="x"),dict(body,**{list(body)[0]:123})):
  assert c.post(path,json=bad,headers=admin).status_code==400
 result=c.post(path,json=body,headers=admin)
 assert result.status_code==200,(kind,result.json)
 rid=result.json["id"]
 assert c.post(path,json=body,headers=admin).status_code==409
 result=c.get(path+"?q=000123",headers=admin)
 assert result.status_code==200 and len(result.json["records"])==1
 assert "qr_id" not in result.json["records"][0]
 key="student_name" if kind=="registrations" else "name"
 changed=dict(body,**{key:"Corrected Student"})
 assert c.put(path+"/"+str(rid),json=changed,headers=admin).status_code==200
 identity="registration_number" if kind=="registrations" else "roll_no"
 assert c.put(path+"/"+str(rid),json=dict(changed,**{identity:"OTHER"}),headers=admin).status_code==400
 assert c.get(path+"?q=000123",headers=admin).json["records"][0][identity]==body[identity]
 assert c.put(path+"/999999",json=changed,headers=admin).status_code==404
with database.connection() as db:
 assert db.execute("SELECT COUNT(*) FROM registration_audit WHERE actor='mobile-administrator'").fetchone()[0]==2
 assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('roster_added','roster_corrected') AND actor='mobile-administrator'").fetchone()[0]==2
 assert db.execute("SELECT qr_id FROM students WHERE roll_no='000123'").fetchone()[0]
print("PASS: native admin records, student/scanner denial, intake/correction/audit/duplicates/immutable identities and paused tools")
'''
            result = subprocess.run([sys.executable, "-c", code, str(repo / "app")],
                                    input=json.dumps(creds), env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("PASS:", result.stdout)



if __name__ == "__main__":
    unittest.main()
