"""Phase 7 regression: convocation event management + smart announcements.

Covers: event CRUD/save/publish/activate lifecycle, expected vs confirmed
date states, confirmed-date change audit attribution, announcement draft/
publish/unpublish/archive/restore flow, drafts/staff-only/archived rows
never leaking through public student APIs, active vs historical convocation
filtering, server-side authz + CSRF rejection, dashboard indicators from
known records, student feed empty/loading/server-failure states, and
preservation of registrations, medalists, QR identities, gate and
attendance data.

Run:  python scripts/test_event_announcements.py   (from app/)
Disposable temp databases only - never touches app/lgu.db.
"""

import json
import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p7ev-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "photos")

import config  # noqa: E402
config.require_test_db()
import announcements as ann  # noqa: E402
import convocation_events as ev  # noqa: E402
import database  # noqa: E402
import exam_auth  # noqa: E402
from web.exam_routes import dashboard_metrics  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
PW = "correct-horse-battery"
STAFF = "eventofficer"
SECOND = "secondofficer"
PRESERVE = ["students", "guests", "gates", "scans", "broadcasts",
            "settings", "convocation_registrations", "medalists"]


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def run(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def dump(names):
    out = {}
    for t in names:
        out[t] = raw("SELECT * FROM %s ORDER BY rowid" % t)
    return out


def csrf_of(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def html(resp):
    return resp.get_data(as_text=True)


def metrics_of():
    db = database.get_db()
    try:
        with app.test_request_context():
            return dashboard_metrics(db)
    finally:
        db.close()


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
exam_auth.create_staff(STAFF, "Event Officer", PW)
exam_auth.create_staff(SECOND, "Second Officer", PW)
CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]

# One registration + one QR identity + one guest + one medalist so the
# preserve checks have real rows to compare against.
NOW = "2026-10-01T00:00:00+00:00"
run("INSERT INTO convocation_registrations"
    " (convocation_id, registration_number, university_email, roll_number,"
    "  student_name, department, status, created_at, updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?)",
    (CONV, "REG-7001", "p7@uni.edu.pk", "07001", "Preserve Student",
     "BSCS", "active", NOW, NOW))
run("INSERT INTO students (roll_no, name, gender, program, qr_id,"
    " created_at) VALUES (?,?,?,?,?,?)",
    ("07001", "Preserve Student", "Male", "BSCS", "qr-p7-0001", NOW))
run("INSERT INTO guests (name, phone, host_roll_no, qr_id, created_at)"
    " VALUES (?,?,?,?,?)",
    ("Preserve Guest", "0300 0000000", "07001", "qr-p7-g001", NOW))
run("INSERT INTO gates (code, label) VALUES ('P7', 'Preserve Gate')")
run("INSERT INTO medalists (convocation_id, department, student_name,"
    " award_category, position, publication, created_at, updated_at)"
    " VALUES (?,?,?,?,?,?,?,?)",
    (CONV, "BSCS", "Medal Student", "gold", "1st", "draft", NOW, NOW))

PRE = dump(PRESERVE)

# 1. Authorisation: unauth + volunteer + CSRF.
fresh = app.test_client()
check("authz: event page redirects to login when unauth",
      fresh.get("/exam/event").status_code == 302)
check("authz: announcements page redirects to login when unauth",
      fresh.get("/exam/announcements").status_code == 302)
check("authz: student event API is public (no redirect)",
      fresh.get("/api/student/event").status_code == 200)
check("authz: student announcements API is public (no redirect)",
      fresh.get("/api/student/announcements").status_code == 200)
with fresh.session_transaction() as s:
    s["lgu_admin"] = "1"
check("authz: volunteer session cannot open event page",
      fresh.get("/exam/event").status_code == 302)
check("authz: POST without CSRF token is rejected 403",
      client.post("/exam/event/save", data={"name": "x"}).status_code == 403)
check("authz: announcement POST without CSRF is rejected 403",
      client.post("/exam/announcements/create",
                  data={"title": "x"}).status_code == 403)

# Staff login (CSRF on the login form).
r = client.get("/exam/login")
ltok = csrf_of(html(r))
r = client.post("/exam/login",
                data={"username": STAFF, "password": PW, "csrf_token": ltok})
check("authz: staff login succeeds", r.status_code == 302, r.status_code)
TOKEN = csrf_of(html(client.get("/exam/event")))
check("authz: event page yields a CSRF token", bool(TOKEN))

# 2. Event date states: not_announced / expected / confirmed, never
#    expected reading as confirmed.
db = database.get_db()
check("state: seeded convocation with legacy expected date is 'expected'",
      ev.date_state(ev.active(db)) == "expected")
ev.save_details(db, ev.active(db),
                ev.clean_details({"name": "Convocation 2026", "year": "2026",
                                  "expected_date": "2026-12-12",
                                  "confirmed_date": "", "rehearsal_date": "",
                                  "rehearsal_time": "", "venue": "Main Hall",
                                  "instructions": "Bring your ID card."}),
                STAFF)
db.commit()
state = ev.date_state(ev.active(db))
check("state: expected stays 'expected' until confirmed date is saved",
      state == "expected")
pre_pub = ev.student_payload(db)
check("state: nothing served to students before the first publish",
      pre_pub["convocation"] is None and pre_pub["event"] is None, pre_pub)
db.close()

# 3. Save a confirmed date; audit attributes the change to the actor.
db = database.get_db()
conv = ev.active(db)
ev.save_details(db, conv,
                ev.clean_details({"name": "Convocation 2026", "year": "2026",
                                  "expected_date": "2026-12-12",
                                  "confirmed_date": "2026-12-18",
                                  "rehearsal_date": "2026-12-17",
                                  "rehearsal_time": "10:30",
                                  "venue": "Main Hall",
                                  "instructions": "Bring your ID card."}),
                SECOND)
db.commit()
conv = ev.active(db)
check("state: saving confirmed date moves state to 'confirmed'",
      ev.date_state(conv) == "confirmed")
trail = ev.audit_trail(db, CONV)
change = [t for t in trail
          if t["action"] == "save" and "confirmed_date" in t["after_json"]]
check("audit: confirmed-date change recorded with actor attribution",
      bool(change) and change[0]["actor"] == SECOND and
      json.loads(change[0]["after_json"])["confirmed_date"] == "2026-12-18",
      [dict(t) for t in trail])
check("audit: publish of snapshot attributes to actor",
      ev.publish(db, conv, STAFF) is not None and
      ev.publication(db, CONV)["published_by"] == STAFF)
pub = ev.publication(db, CONV)
check("publish: snapshot carries confirmed date, rehearsal and instructions",
      pub["confirmed_date"] == "2026-12-18" and
      pub["rehearsal_time"] == "10:30" and pub["venue"] == "Main Hall" and
      "ID card" in pub["instructions"])
check("dirty: no unpublished changes right after publish",
      not ev.is_dirty(db, conv))
ev.save_details(db, conv, {**ev.details_of(conv),
                           "venue": "New Block Hall"}, STAFF)
db.commit()
check("dirty: draft edit marks the event unpublished-changes",
      ev.is_dirty(db, ev.active(db)))
db.close()

# 4. Event page renders state + change history.
page = html(client.get("/exam/event"))
check("event page: shows confirmed badge and rehearsal details",
      "Officially confirmed" in page and "10:30" in page and
      "New Block Hall" in page)
check("event page: history lists publish + save actions",
      "publish" in page and "save" in page and SECOND in page)

# 5. Publish again so students see the latest snapshot.
db = database.get_db()
ev.publish(db, ev.active(db), STAFF)
db.commit()
db.close()
db = database.get_db()
payload = ev.student_payload(db)
db.close()
db = database.get_db()
check("student: event payload exposes confirmed date + rehearsal time",
      payload["event"]["confirmed_date"] == "2026-12-18" and
      payload["event"]["rehearsal"]["time"] == "10:30")
check("student: date state label distinguishes confirmed from expected",
      payload["event"]["date_state"] == "confirmed" and
      "confirmed" in payload["event"]["date_state_label"].lower())

# 6. Announcement lifecycle: draft -> publish -> unpublish -> archive ->
#    restore, with attribution + timestamps.
db = database.get_db()
draft = ann.create(db, CONV, ann.clean(
    {"title": "Reach the venue by 9 AM", "body": "Gate opening time.",
     "audience": "students"}, STAFF))
db.commit()
check("announcement: created as draft with attribution",
      draft["status"] == "draft" and draft["created_by"] == STAFF and
      draft["created_at"])
ann.update(db, draft, ann.clean({"title": "Reach the venue by 9:30 AM",
                                 "body": "Updated gate opening time.",
                                 "audience": "students"}, SECOND))
db.commit()
row = ann.get(db, draft["id"])
check("announcement: edit keeps draft status and updates attribution",
      row["status"] == "draft" and row["updated_by"] == SECOND)
ann.publish(db, row, STAFF)
db.commit()
row = ann.get(db, draft["id"])
check("announcement: publish sets timestamp + actor",
      row["status"] == "published" and row["published_by"] == STAFF and
      row["published_at"])
try:
    ann.publish(db, row, STAFF)
    check("announcement: double publish is rejected", False)
except ann.AnnouncementError:
    check("announcement: double publish is rejected", True)
ann.unpublish(db, row, SECOND)
db.commit()
row = ann.get(db, draft["id"])
check("announcement: unpublish returns to draft and clears timestamp",
      row["status"] == "draft" and row["published_at"] is None)
ann.publish(db, row, STAFF)
db.commit()
ann.archive(db, ann.get(db, draft["id"]), STAFF)
db.commit()
row = ann.get(db, draft["id"])
check("announcement: archive sets archived state + timestamp",
      row["status"] == "archived" and row["archived_at"])
ann.restore(db, row, SECOND)
db.commit()
row = ann.get(db, draft["id"])
check("announcement: restore returns archived row to draft",
      row["status"] == "draft" and row["archived_at"] is None)
atrail = ann.audit_trail(db, draft["id"])
actions = [t["action"] for t in reversed(atrail)]  # trail is newest-first
check("audit: full announcement history create/update/publish/unpublish/"
      "archive/restore",
      actions == ["create", "update", "publish", "unpublish", "publish",
                  "archive", "restore"], actions)

# 7. Public student APIs never leak drafts / staff-only / archived rows.
ann.publish(db, ann.get(db, draft["id"]), STAFF)
db.commit()
staff_row = ann.create(db, CONV, ann.clean(
    {"title": "Staff briefing", "body": "Internal note.",
     "audience": "staff"}, STAFF))
ann.publish(db, staff_row, STAFF)
db.commit()
archived = ann.create(db, CONV, ann.clean(
    {"title": "Old notice", "body": "Superseded.", "audience": "students"},
    STAFF))
ann.publish(db, archived, STAFF)
db.commit()
ann.archive(db, ann.get(db, archived["id"]), STAFF)
db.commit()
hidden = ann.create(db, CONV, ann.clean(
    {"title": "Hidden draft", "body": "Not visible.", "audience": "students"},
    STAFF))
db.commit()
db.close()
body = client.get("/api/student/announcements").get_json()
titles = [a["title"] for a in body["announcements"]]
check("feed: published student announcement appears exactly once",
      titles.count("Reach the venue by 9:30 AM") == 1, titles)
check("feed: staff-audience row never leaks",
      "Staff briefing" not in titles, titles)
check("feed: archived row never leaks", "Old notice" not in titles, titles)
check("feed: draft row never leaks", "Hidden draft" not in titles, titles)
check("feed: counts only the published student rows",
      body["total"] == 1, body["total"])

# 8. Event API serves only the publication snapshot.
db = database.get_db()
ev.save_details(db, ev.active(db), {**ev.details_of(ev.active(db)),
                                    "instructions": "SECRET-DRAFT-TEXT"},
                STAFF)
db.commit()
db.close()
ev_payload = client.get("/api/student/event").get_json()
check("event api: unpublished working change does not leak",
      "SECRET-DRAFT-TEXT" not in json.dumps(ev_payload))
check("event api: published snapshot text still served",
      ev_payload["event"]["instructions"] == "Bring your ID card.")
# Re-publish to clear the draft-only state for later checks.
db = database.get_db()
ev.publish(db, ev.active(db), STAFF)
db.commit()
db.close()

# 9. Active vs historical convocation filtering.
db = database.get_db()
old_id = ev.create_event(db, {
    "name": "Convocation 2024", "year": "2024",
    "expected_date": "2024-12-10", "confirmed_date": "2024-12-10",
    "ceremony_time": "", "rehearsal_date": "", "rehearsal_time": "",
    "rehearsal_venue": "", "venue": "Old Hall",
    "instructions": "Archived event."}, STAFF)
old = ev.get(db, old_id)
old_ann = ann.create(db, old_id, ann.clean(
    {"title": "Old convocation notice", "body": "From 2024.",
     "audience": "students"}, STAFF))
ann.publish(db, old_ann, STAFF)
ev.publish(db, old, STAFF)
db.commit()
db.close()
check("history: inactive convocation's announcement not in active feed",
      "Old convocation notice" not in
      [a["title"] for a in
       client.get("/api/student/announcements").get_json()["announcements"]])
check("history: inactive convocation event info not served",
      client.get("/api/student/event").get_json()["convocation"]["year"]
      != "2024")
# Switching active changes which event students see; only one is active.
db = database.get_db()
ev.set_active(db, old_id, STAFF)
db.commit()
actives = db.execute("SELECT COUNT(*) FROM convocations WHERE is_active = 1"
                     ).fetchone()[0]
db.close()
check("history: activating historical event keeps exactly one active",
      actives == 1)
check("history: students now see the 2024 event as active",
      client.get("/api/student/event").get_json()["convocation"]["year"]
      == "2024")
check("history: feed now scoped to the 2024 convocation",
      [a["title"] for a in
       client.get("/api/student/announcements").get_json()["announcements"]]
      == ["Old convocation notice"])
db = database.get_db()
ev.set_active(db, CONV, STAFF)
db.commit()
db.close()

# 10. Dashboard indicators from known records. Clear the confirmed date so
#     the working draft is back to a provisional (expected) state, and drop
#     venue + rehearsal time to surface those two warnings.
run("UPDATE convocations SET venue = '', rehearsal_time = NULL,"
    " confirmed_date = NULL WHERE id = ?", (CONV,))
m = metrics_of()
labels = [i["label"] for i in m["issues"]]
check("dashboard: missing venue warning links to event page",
      "Set the venue" in labels and
      any("event" in i["href"] for i in m["issues"]
          if i["label"] == "Set the venue"), labels)
check("dashboard: rehearsal date without time warns",
      "Complete rehearsal details" in labels, labels)
check("dashboard: announcement draft warning appears when drafts exist",
      "Review announcement drafts" in labels, labels)
check("dashboard: every issue carries a real link",
      all(i.get("href") and i.get("label") for i in m["issues"]),
      m["issues"])
check("dashboard: expected state reported separately from published flag",
      m["event"]["state"] == "expected" and m["event"]["published"] is True)
db = database.get_db()
draft_rows = ann.list_for(db, CONV, "draft")
db.close()
check("dashboard: draft announcement count is real",
      m["event"]["announcements"]["draft"] == len(draft_rows),
      (m["event"]["announcements"], len(draft_rows)))
run("UPDATE convocations SET venue = 'Main Hall' WHERE id = ?", (CONV,))
m = metrics_of()
check("dashboard: filling the venue clears that warning",
      "Set the venue" not in [i["label"] for i in m["issues"]])

# 11. Student feed empty + error states via the API.
empty_client = app.test_client()
run("UPDATE convocations SET is_active = 0 WHERE id = ?", (CONV,))
body = empty_client.get("/api/student/announcements").get_json()
check("feed: no active convocation returns empty list, not an error",
      body == {"convocation": None, "total": 0, "announcements": []}, body)
ev_payload = empty_client.get("/api/student/event").get_json()
check("event api: no active convocation returns null event, not an error",
      ev_payload == {"convocation": None, "event": None}, ev_payload)
run("UPDATE convocations SET is_active = 1 WHERE id = ?", (CONV,))
body = client.get("/api/student/announcements").get_json()
check("feed: restoring active convocation repopulates the feed",
      body["total"] == 1 and body["convocation"]["year"] is not None)

# 12. Preservation: registrations, medalists, QR identities, gates and
#     attendance are untouched by every Phase 7 operation.
check("preserve: registrations/medalists/QR/gate tables unchanged",
      dump(PRESERVE) == PRE)
gate_rows = raw("SELECT * FROM gates WHERE code = 'P7'")
check("preserve: gate record intact",
      len(gate_rows) == 1 and gate_rows[0]["label"] == "Preserve Gate")
qr_rows = raw("SELECT * FROM students WHERE qr_id = 'qr-p7-0001'")
check("preserve: QR identity intact",
      len(qr_rows) == 1 and qr_rows[0]["name"] == "Preserve Student")
guest_rows = raw("SELECT * FROM guests WHERE qr_id = 'qr-p7-g001'")
check("preserve: guest QR intact", len(guest_rows) == 1)

# 13. Schema version reflects the latest migration and is idempotent.
import migrations  # noqa: E402
database.init_db()
check("migration: user_version is the latest after re-run",
      sqlite3.connect(config.DB_PATH).execute(
          "PRAGMA user_version").fetchone()[0] == migrations.MIGRATIONS[-1][0])
check("migration: Phase 7 tables exist",
      all(t in [r["name"] for r in raw(
          "SELECT name FROM sqlite_master WHERE type='table'")] for t in
          ("convocation_publications", "convocation_audit", "announcements",
           "announcement_audit")))

print()
print("%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
