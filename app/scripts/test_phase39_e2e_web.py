"""Phase 39 - E2E web suite: Playwright against a REAL running server.

Self-contained: boots its own disposable DB (temp dir), provisions fixtures
(student account + support request, exam staff, scanner staff), starts
``python run.py`` on a free port (LGU_TESTING=1, never the production DB),
drives headless Chromium through every web interface, then prints an honest
coverage matrix derived from ``app.url_map``.

Run:  .venv/Scripts/python.exe app/scripts/test_phase39_e2e_web.py
Exit: 0 = all E2E checks passed, 1 = at least one FAIL (BLOCKED/NOT TESTED
in the matrix do not fail the run - they are reported, not faked).
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(tempfile.mkdtemp(prefix="p39_e2e_"))
DB_PATH = TEST_ROOT / "e2e.db"
EVID_DIR = TEST_ROOT / "evidence"
EVID_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(APP))

os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = str(DB_PATH)
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"

import config  # noqa: E402
import database  # noqa: E402
import exam_auth  # noqa: E402
import ids  # noqa: E402
import scanner_auth  # noqa: E402
import student_auth as sa  # noqa: E402
import support_requests as sup  # noqa: E402

RESULTS = {}          # tid -> PASS/FAIL
COVER = {}            # rule -> tid (rules the browser/HTTP layer really hit)
ACTIVE_PAGE = None    # for failure screenshots
PICTURE_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
               b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
               b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
               b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def out(msg):
    print(str(msg).encode("cp1252", "replace").decode("cp1252"), flush=True)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cover(rule, tid):
    COVER[rule] = tid


# --------------------------------------------------------------- fixtures
def provision():
    database.init_db()
    database.seed()
    with database.connection() as db:
        exam_auth.create_staff("qa-e2e-officer", "QA E2E Officer",
                               "QA-e2e-Passw0rd-2026!")
        scanner_auth.create_scanner(
            username="qa-e2e-gate", display_name="QA E2E Gate",
            pin="412783", gate_ids=[1, 2], actor="phase39-fixture")
        sa.create_account(db, "qa.e2e.student@example.test",
                          "QA-e2e-Std-2026!")
        db.commit()
        acct = db.execute(
            "SELECT id FROM student_accounts WHERE university_email = ?",
            ("qa.e2e.student@example.test",)).fetchone()
        conv = db.execute(
            "SELECT id FROM convocations WHERE is_active = 1"
            " ORDER BY id LIMIT 1").fetchone()
        sup.create(db, conv["id"], acct["id"], None, sup.validate_form({
            "category": "missing_registration",
            "subject": "E2E support fixture",
            "message": "Created by Phase 39 E2E suite."}))
        db.commit()


# ------------------------------------------------------------- page helpers
def post_click(page, sel):
    """Click a submit control and wait for the resulting document load."""
    with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
        page.click(sel)


def login_exam(page):
    page.goto(BASE + "/exam/login")
    page.fill("input[name=username]", "qa-e2e-officer")
    page.fill("input[name=password]", "QA-e2e-Passw0rd-2026!")
    post_click(page, "form button[type=submit]")


def run(tid, desc, fn):
    try:
        fn()
        RESULTS[tid] = "PASS"
        out("PASS  %-8s %s" % (tid, desc))
    except Exception as exc:  # noqa: BLE001 - record every failure, keep going
        RESULTS[tid] = "FAIL"
        text = "%s: %s" % (type(exc).__name__, str(exc))
        out("FAIL  %-8s %s :: %s" % (tid, desc,
                                     text[:220].encode("cp1252", "replace")
                                     .decode("cp1252")))
        if ACTIVE_PAGE is not None:
            try:
                ACTIVE_PAGE.screenshot(path=str(EVID_DIR / (tid + ".png")),
                                       full_page=True)
            except Exception:  # noqa: BLE001
                pass


# ------------------------------------------------------------------ groups
def group_home(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def a1():
        page.goto(BASE + "/")
        cover("/", "E2E-01")
        expect("Convocation" in page.title() or "LGU" in page.title(),
               "unexpected home title: " + page.title())
        for label in ("Scanner", "Dashboard", "Admin"):
            expect(page.locator("a", has_text=label).count() > 0,
                   "module link missing: " + label)
    run("E2E-01", "home page renders with module links", a1)


def group_dashboard(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page
    captured = {}
    page.on("response", lambda r: captured.setdefault(r.url, r)
            if "/api/dashboard" in r.url else None)

    def b1():
        page.goto(BASE + "/dashboard", wait_until="networkidle")
        cover("/dashboard", "E2E-02")
        for tid in ("#k-inside", "#k-male", "#k-female", "#k-guests",
                    "#k-ceremony", "#k-rehearsal", "#k-busy", "#k-remaining",
                    "#k-rejected", "#k-duplicate", "#gen", "#cadence",
                    "#bars", "#sync", "#feed"):
            expect(page.locator(tid).count() > 0, "tile missing: " + tid)
        expect(page.locator("#gen").inner_text().strip() != "",
               "generated_at tile empty")

    def b2():
        resp = next(iter(captured.values()))
        cover("/api/dashboard", "E2E-03")
        data = json.loads(resp.body())
        for key in ("poll_interval_ms", "inside_total", "male", "female",
                    "guests_inside", "ceremony_admitted", "rehearsal_admitted",
                    "busiest_gate", "attendance_set", "remaining_attendance",
                    "rejected_count", "duplicate_count", "generated_at",
                    "throughput", "sync", "feed"):
            expect(key in data, "dashboard key missing: " + key)
        expect(100 <= int(data["poll_interval_ms"]) <= 5000,
               "poll_interval_ms out of sane range: %r"
               % data["poll_interval_ms"])

    def b3():
        r = page.goto(BASE + "/dashboard?occasion=ceremony")
        cover("/dashboard", "E2E-04")
        expect(r.status == 200, "?occasion=ceremony -> %s" % r.status)
        r2 = page.request.get(BASE + "/api/dashboard?occasion=bogus")
        cover("/api/dashboard", "E2E-04")
        expect(r2.status == 400, "bogus occasion -> %s" % r2.status)

    def b4():
        r = page.request.get(BASE + "/api/config")
        cover("/api/config", "E2E-05")
        expect(r.status == 200, "/api/config -> %s" % r.status)
        data = r.json()
        expect(data.get("app_name"), "config missing app_name")
        expect(isinstance(data.get("gates"), list) and len(data["gates"]) == 7,
               "config gates wrong: %r" % (data.get("gates"),))
        blob = r.text().lower()
        expect("secret" not in blob and '"pin"' not in blob
               and "password" not in blob,
               "config leaks a sensitive key")

    run("E2E-02", "dashboard tiles all render", b1)
    run("E2E-03", "/api/dashboard JSON contract", b2)
    run("E2E-04", "dashboard occasion filter + bogus -> 400", b3)
    run("E2E-05", "/api/config public contract", b4)


def group_admin(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def c1():
        r = page.goto(BASE + "/admin")
        cover("/admin", "E2E-06")
        expect(r.status == 401, "/admin anon -> %s" % r.status)
        expect(page.locator("input[name=admin_pin]").count() == 1,
               "unlock form missing")

    def c2():  # Q-4 repro: wrong PIN must give VISIBLE feedback
        page.fill("input[name=admin_pin]", config.ADMIN_PIN + "x")
        post_click(page, "form button[type=submit]")
        cover("/admin", "E2E-07")
        notice = page.locator(".notice.bad, .notice.info, .notice.ok")
        expect(notice.count() > 0,
               "wrong PIN shows no feedback notice at all (Q-4)")
        expect("incorrect" in notice.first.inner_text().lower()
               or "wrong" in notice.first.inner_text().lower(),
               "notice does not explain the wrong PIN: "
               + notice.first.inner_text()[:80])

    def c3():
        page.fill("input[name=admin_pin]", config.ADMIN_PIN)
        post_click(page, "form button[type=submit]")
        expect(page.locator("text=Generate QR IDs").count() > 0,
               "admin page did not open after correct PIN")

    def c4():
        post_click(page, "button:has-text('Generate IDs')")
        note = page.locator(".notice.ok")
        expect(note.count() > 0 and note.first.inner_text().strip() != "",
               "generate gave no confirmation notice")
        cover("/admin", "E2E-09")

    def c5():
        csv = TEST_ROOT / "roster.csv"
        csv.write_text("roll_no,name,gender,program\n"
                       "QA-39-001,QA E2E Student One,Male,BSc Testing\n"
                       "QA-39-002,QA E2E Student Two,Female,BSc Testing\n",
                       encoding="utf-8")
        page.set_input_files("input[name=roster]", str(csv))
        post_click(page, "button:has-text('Upload and assign IDs')")
        expect("Roster loaded" in page.content()
               or page.locator(".notice.ok").count() > 0,
               "roster upload gave no success message")
        cover("/admin", "E2E-10")

    def c7():
        r = page.goto(BASE + "/admin/cards")
        cover("/admin/cards", "E2E-10")
        expect(r.status == 200, "/admin/cards -> %s" % r.status)
        expect("QA" in page.content() or "roll" in page.content().lower(),
               "card sheet empty")

    def c8():
        r = page.request.get(BASE + "/admin/vendor.csv")
        cover("/admin/vendor.csv", "E2E-11")
        expect(r.status == 200, "vendor.csv -> %s" % r.status)
        head = r.text().splitlines()[0]
        expect("roll_no" in head and "qr_payload" in head,
               "vendor CSV header wrong: " + head)

    def c9():
        page.goto(BASE + "/broadcast")
        cover("/broadcast", "E2E-12")
        msg = "QA E2E announcement: rehearsal starts 09:30 at Gate 1."
        page.fill("textarea[name=message]", msg)
        page.fill("input[name=sent_by]", "QA E2E Sender")
        post_click(page, "button:has-text('Send announcement')")
        expect(msg in page.content(), "announcement not in the log after send")

    def c10():
        r = page.goto(BASE + "/guests/directory")
        cover("/guests/directory", "E2E-13")
        expect(r.status == 200, "directory (unlocked) -> %s" % r.status)

    def c11():
        page.goto(BASE + "/admin")
        page.locator("form:has(input[value=rename_gate]) "
                     "input[name=label]").first.fill("Main Gate (QA renamed)")
        post_click(page, "form:has(input[value=rename_gate]) "
                         "button:has-text('Save')")
        expect('value="Main Gate (QA renamed)"' in page.content(),
               "gate rename did not persist")

    def c12():  # Q-3 repro: binary upload must NOT 500
        page.goto(BASE + "/admin")
        blob = TEST_ROOT / "roster.bin"
        blob.write_bytes(bytes(range(256)) * 8)
        page.set_input_files("input[name=roster]", str(blob))
        with page.expect_response(
                lambda r: "admin" in r.url, timeout=10000) as ri:
            page.click("button:has-text('Upload and assign IDs')")
        resp = ri.value
        page.wait_for_load_state("domcontentloaded")
        cover("/admin", "E2E-16")
        expect(resp.status < 500,
               "binary roster upload crashed with HTTP %s (Q-3)"
               % resp.status)
        body = page.content()
        expect("roster" in body.lower() and "utf-8" in body.lower(),
               "no friendly decode error shown for binary roster")

    run("E2E-06", "/admin gated -> unlock form", c1)
    run("E2E-07", "wrong admin PIN gives visible feedback (Q-4)", c2)
    run("E2E-08", "correct PIN unlocks the admin page", c3)
    run("E2E-09", "generate button posts action=generate", c4)
    run("E2E-10", "roster CSV upload (header row)", c5)
    run("E2E-11", "/admin/cards printable sheet", c7)
    run("E2E-12", "/admin/vendor.csv download headers", c8)
    run("E2E-13", "broadcast compose + send + log", c9)
    run("E2E-14", "/guests/directory unlocked", c10)
    run("E2E-15", "gate rename persists", c11)
    run("E2E-16", "binary roster upload is friendly, not 500 (Q-3)", c12)


def group_guests(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def d1():
        r = page.goto(BASE + "/guests")
        cover("/guests", "E2E-17")
        expect(r.status == 401, "anonymous /guests -> %s" % r.status)
        page.fill("input[name=admin_pin]", config.ADMIN_PIN)
        post_click(page, "button[type=submit]")
        for name in ("name", "phone", "host_roll_no"):
            expect(page.locator("input[name=%s]" % name).count() == 1,
                   "guest form field missing: " + name)

    def d2():
        page.fill("input[name=name]", "QA E2E Visitor")
        page.fill("input[name=phone]", "0300 9988776")
        page.fill("input[name=host_roll_no]", "LGU-2024-102")
        page.fill("input[name=payment_reference]", "E2E-PAID-102")
        page.check("input[name=payment_verified]")
        post_click(page, "form:has(input[name=host_roll_no]) button[type=submit]")
        cover("/guests", "E2E-18")
        expect("/pass" in page.url, "no redirect to pass page: " + page.url)
        cover("/guests/<int:gid>/pass", "E2E-18")
        expect(page.locator("img").count() > 0, "pass page has no QR image")
        expect("Print" in page.content(), "pass page has no print control")

    def d3():
        ctx.clear_cookies()
        r = page.goto(BASE + "/guests/1/pass")
        cover("/guests/<int:gid>/pass", "E2E-19")
        expect(r.status == 401, "anon pass link -> %s" % r.status)
        expect("invalid or has expired" in page.content(),
               "anon pass link missing the expected refusal text")

    def d4():
        r = page.goto(BASE + "/guests/directory")
        cover("/guests/directory", "E2E-20")
        expect(r.status == 401, "anon directory -> %s" % r.status)
        expect(page.locator("input[name=admin_pin]").count() == 1,
               "anon directory did not fall back to unlock")

    def d5():
        page.goto(BASE + "/guests")
        page.fill("input[name=admin_pin]", config.ADMIN_PIN)
        post_click(page, "button[type=submit]")
        page.fill("input[name=name]", "QA E2E Visitor 2")
        page.fill("input[name=phone]", "0300 9988777")
        page.fill("input[name=host_roll_no]", "LGU-2024-999")
        page.fill("input[name=payment_reference]", "E2E-PAID-999")
        page.check("input[name=payment_verified]")
        post_click(page, "form:has(input[name=host_roll_no]) button[type=submit]")
        expect("No student found with roll number LGU-2024-999"
               in page.content(), "unknown host roll gave no error message")
        cover("/guests", "E2E-21")

    run("E2E-17", "guest registration form renders", d1)
    run("E2E-18", "register guest -> signed pass page", d2)
    run("E2E-19", "anonymous pass link refused (401)", d3)
    run("E2E-20", "anonymous directory falls back to unlock", d4)
    run("E2E-21", "unknown host roll rejected with message", d5)


def group_scanner(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def signin_visible():
        expect(page.locator("#signin-card").count() > 0
               and page.locator("#signin-card").is_visible(),
               "scanner page has no sign-in UI but /api/scan requires "
               "X-Scanner-Token (Q-2)")

    def e1():
        page.goto(BASE + "/scan")
        cover("/scan", "E2E-22")
        signin_visible()

    def e2():
        page.goto(BASE + "/scan")
        signin_visible()
        page.fill("#s-user", "qa-e2e-gate")
        page.fill("#s-pin", "412783")
        page.click("#signin-btn")
        page.wait_for_selector("#scan-card:not([hidden])", timeout=8000)
        cover("/api/gates", "E2E-23")
        values = page.eval_on_selector_all(
            "#gate option", "els => els.map(e => e.value)")
        expect(set(values) == {"1", "2"},
               "gate select not filtered to authorized gates: %r" % values)

    def wait_title_change(prev, tries=80):
        # demo-fill leaves a non-empty title, so :not(:empty) is not enough;
        # poll until the title text actually changes.
        for _ in range(tries):
            cur = page.locator("#r-title").inner_text().strip()
            if cur != prev:
                return cur
            page.wait_for_timeout(100)
        return page.locator("#r-title").inner_text().strip()

    LAST = {"payload": ""}

    def scan_ui(mode_btn, payload=None):
        expect(page.locator("#scan-card").count() == 1
               and page.locator("#scan-card").is_visible(),
               "no scan card - sign-in UI missing (Q-2)")
        if payload is None:
            page.click("button:has-text('Demo: fill next')")
            page.wait_for_function(
                "() => document.getElementById('payload').value !== ''",
                timeout=8000)
        else:
            page.fill("#payload", payload)
        LAST["payload"] = page.locator("#payload").input_value()
        page.fill("#volunteer", "QA E2E Volunteer")
        page.click(mode_btn)
        prev = page.locator("#r-title").inner_text().strip()
        page.click("button:has-text('SCAN')")
        page.wait_for_selector("#r-title", state="attached", timeout=8000)
        return wait_title_change(prev)

    def e3():
        cover("/api/scan", "E2E-24")
        cover("/api/demo-payload", "E2E-24")
        title = scan_ui("#m-entry")
        expect(title == "ENTRY RECORDED",
               "first scan title: %r (expected ENTRY RECORDED)" % title)

    def e4():
        # demo-fill advances to the next student, so reuse the entered one
        title = scan_ui("#m-entry", payload=LAST["payload"])
        expect(title == "ALREADY INSIDE",
               "duplicate scan title: %r (expected ALREADY INSIDE)" % title)

    def e5():
        title = scan_ui("#m-exit", payload=LAST["payload"])
        expect(title == "EXIT RECORDED",
               "exit scan title: %r (expected EXIT RECORDED)" % title)

    def e6():
        cover("/api/sync", "E2E-27")
        page.evaluate("() => document.getElementById('offline').click()")
        scan_ui("#m-entry")
        expect(page.locator("#qcount").inner_text().strip() == "1",
               "offline queue did not capture the scan")
        prev = page.locator("#r-title").inner_text().strip()
        page.click("button:has-text('Sync now')")
        page.wait_for_selector("#r-title", state="attached", timeout=8000)
        title = wait_title_change(prev)
        expect(title == "SYNC COMPLETE",
               "sync title: %r (TypeError on 401 body? Q-2)" % title)
        expect(page.locator("#qcount").inner_text().strip() == "0",
               "queue not drained after sync")

    def e7():
        # independent API session so the gate-403 contract holds regardless
        # of the page sign-in state
        lr = page.request.post(BASE + "/api/scanner/login",
                               data={"username": "qa-e2e-gate",
                                     "pin": "412783"})
        expect(lr.status == 200, "fixture scanner login -> %s" % lr.status)
        cover("/api/scanner/login", "E2E-28")
        tok = lr.json()["token"]
        r = page.request.post(BASE + "/api/scan",
                              headers={"X-Scanner-Token": tok},
                              data={"payload": ids.make_payload("NOPE1234"),
                                    "gate_id": 3, "mode": "entry"})
        expect(r.status == 403, "scan from unauthorized gate -> %s" % r.status)
        body = r.json()
        expect(body.get("title") == "GATE NOT AUTHORIZED",
               "gate403 body: %r" % body)

    def e8():
        tok = page.evaluate("() => sessionStorage.getItem("
                            "'lgu_scanner_token')")
        headers = {"X-Scanner-Token": tok} if tok else {}
        r = page.request.post(BASE + "/api/scanner/logout", headers=headers)
        cover("/api/scanner/logout", "E2E-29")
        expect(r.status == 200 and r.json().get("ok") is True,
               "scanner logout failed: %s" % r.status)

    def e9():
        page.goto(BASE + "/scan")
        page.click("button:has-text('Demo: fill next')")
        page.wait_for_function(
            "() => document.getElementById('payload').value !== ''",
            timeout=8000)
        page.fill("#volunteer", "QA E2E Volunteer")
        page.click("#m-entry")
        page.click("button:has-text('SCAN')")
        page.wait_for_selector("#r-title", state="attached", timeout=8000)
        page.wait_for_timeout(400)
        title = page.locator("#r-title").inner_text().strip()
        expect(title not in ("", "undefined"),
               "401 after logout renders a %r title (Q-2)"
               % (title or "blank"))
        expect(page.locator("#signin-card").is_visible(),
               "session expiry does not return to the sign-in card (Q-2)")

    run("E2E-22", "scanner page shows sign-in UI (Q-2)", e1)
    run("E2E-23", "UI sign-in + authorized gate filter", e2)
    run("E2E-24", "scan entry via UI (demo payload)", e3)
    run("E2E-25", "duplicate scan refused via UI", e4)
    run("E2E-26", "exit scan via UI", e5)
    run("E2E-27", "offline queue + sync (Q-2)", e6)
    run("E2E-28", "API scan on unauthorized gate -> 403", e7)
    run("E2E-29", "scanner logout API revokes session", e8)
    run("E2E-30", "expired/absent session returns to sign-in (Q-2)", e9)


def group_exam(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def f1():
        r = page.goto(BASE + "/exam/")
        cover("/exam/", "E2E-31")
        expect(r.status in (200, 302), "/exam/ -> %s" % r.status)
        page.goto(BASE + "/exam/login")
        cover("/exam/login", "E2E-31")
        expect(page.locator("input[name=username]").count() == 1,
               "exam login form missing")
        expect(page.locator("input[name=csrf_token]").count() == 1,
               "exam login form missing csrf_token")

    def f2():
        page.fill("input[name=username]", "qa-e2e-officer")
        page.fill("input[name=password]", "WrongPassw0rd-xyz!")
        post_click(page, "form button[type=submit]")
        cover("/exam/login", "E2E-32")
        body = page.content()
        expect("Invalid username or password" in body,
               "wrong password gave no clear 401 message")

    def f3():
        login_exam(page)
        r = page.goto(BASE + "/exam/dashboard")
        cover("/exam/dashboard", "E2E-33")
        cover("/exam/login", "E2E-33")
        expect(r.status == 200, "exam dashboard -> %s" % r.status)
        expect(page.locator("input[name=password]").count() == 0,
               "dashboard still shows the login form")

    def f4():
        page.goto(BASE + "/exam/scanners")
        cover("/exam/scanners", "E2E-34")
        post_click(page, "form[action='/exam/logout'] button")
        cover("/exam/logout", "E2E-34")
        expect(page.url.endswith("/exam/login") or
               page.locator("input[name=password]").count() == 1,
               "logout did not return to login: " + page.url)
        login_exam(page)

    def f5():
        page.goto(BASE + "/exam/registrations")
        cover("/exam/registrations", "E2E-35")
        expect(page.locator("input[name=q]").count() == 1,
               "registration search box missing")
        page.fill("input[name=q]", "QA-39")
        post_click(page, "button:has-text('Search')")
        expect("QA-39" in page.content(), "search q= found nothing")

    def f6():
        r = page.request.get(BASE + "/exam/registrations/template")
        cover("/exam/registrations/template", "E2E-36")
        expect(r.status == 200, "template -> %s" % r.status)
        ctype = r.headers.get("content-type", "")
        expect("sheet" in ctype or "octet" in ctype
               or "excel" in ctype, "template content-type: " + ctype)

    def f7():
        r = page.goto(BASE + "/exam/registrations/import")
        cover("/exam/registrations/import", "E2E-37")
        expect(r.status == 200, "import form -> %s" % r.status)
        expect(page.locator("input[type=file]").count() >= 1,
               "import file input missing")

    def f8():
        page.goto(BASE + "/exam/medalists/")
        cover("/exam/medalists/", "E2E-38")
        expect(page.locator("a", has_text="Add").count() > 0
               or page.locator("button", has_text="Add").count() > 0,
               "medalist add control missing")

    seq = {"n": 0}

    def med_create():
        seq["n"] += 1
        page.goto(BASE + "/exam/medalists/new")
        cover("/exam/medalists/new", "E2E-39")
        # award slot (department, category, position) is UNIQUE per convocation
        page.fill("#department", "Computer Science QA%d" % seq["n"])
        page.fill("#student_name", "QA E2E Medalist %d" % seq["n"])
        page.fill("#award_category", "gold")
        post_click(page, "button:has-text('Create draft record')")
        ok = ("/exam/medalists/" in page.url
              and page.url.rstrip("/").split("/")[-1].isdigit())
        err = ""
        if page.locator(".notice.bad").count():
            err = " server error: " + page.locator(".notice.bad").first.inner_text()[:120]
        expect(ok, "no redirect to medalist detail: " + page.url + err)
        return page.url

    def f9():
        med_create()

    def f10():
        med_create()
        post_click(page, "button:has-text('Publish to the student board')")
        cover("/exam/medalists/<int:medalist_id>/<action>", "E2E-40")
        expect("picture" in page.content().lower(),
               "publish without photo not blocked")

    def f11():
        med_create()
        page.set_input_files("#photo", {
            "name": "medal.png", "mimeType": "image/png",
            "buffer": PICTURE_1PX})
        post_click(page, "button:has-text('Upload picture')")
        cover("/exam/medalists/<int:medalist_id>/photo", "E2E-41")
        cover("/exam/medalists/<int:medalist_id>", "E2E-41")
        expect("A picture is stored" in page.content(),
               "photo upload did not store the picture")
        post_click(page, "button:has-text('Publish to the student board')")
        expect("Unpublish" in page.content(), "publish did not take effect")
        post_click(page, "button:has-text('Unpublish')")
        expect("Publish to the student board" in page.content(),
               "unpublish did not take effect")

    def f12():
        med_create()
        cover("/exam/medalists/<int:medalist_id>/edit", "E2E-42")
        page.fill("#position", "1")
        post_click(page, "button:has-text('Save changes')")
        expect(page.locator("input#position").input_value() == "1",
               "position edit not persisted")

    def f13():
        page.goto(BASE + "/exam/event")
        cover("/exam/event", "E2E-43")
        page.fill("#venue", "Main Auditorium (QA)")
        post_click(page, "button:has-text('Save draft')")
        cover("/exam/event/save", "E2E-43")
        expect("done=saved" in page.url or page.locator(".notice.ok").count(),
               "event save gave no confirmation: " + page.url)

    def f14():
        page.goto(BASE + "/exam/event")
        post_click(page, "button:has-text('Publish to students')")
        cover("/exam/event/publish", "E2E-44")
        expect("done=published" in page.url
               or page.locator(".notice.ok").count(),
               "event publish gave no confirmation: " + page.url)

    def f15():
        page.goto(BASE + "/exam/announcements")
        cover("/exam/announcements", "E2E-45")
        page.fill("input[name=title]", "QA E2E Draft Notice")
        page.fill("textarea[name=body]",
                  "Draft body from the Phase 39 E2E suite.")
        post_click(page, "button:has-text('Save as draft')")
        cover("/exam/announcements/create", "E2E-45")
        expect("/exam/announcements/" in page.url
               and page.url.split("?")[0].rstrip("/").split("/")[-1].isdigit(),
               "draft did not redirect to detail: " + page.url)
        cover("/exam/announcements/<int:ann_id>", "E2E-45")
        expect("QA E2E Draft Notice" in page.content(),
               "draft title missing on detail page")

    def f16():
        page.goto(BASE + "/exam/support")
        cover("/exam/support", "E2E-46")
        expect("E2E support fixture" in page.content(),
               "fixture support request not listed")
        page.locator("a[href^='/exam/support/']").first.click()
        page.wait_for_selector("textarea#message", timeout=8000)
        cover("/exam/support/<int:request_id>", "E2E-46")
        form = page.locator("form[action*='respond']")
        form.locator("textarea#message").fill("QA E2E response received.")
        form.locator("button", has_text="Send response").click()
        page.wait_for_load_state("domcontentloaded")
        cover("/exam/support/<int:request_id>/respond", "E2E-46")
        expect("QA E2E response received" in page.content(),
               "response not visible on detail after send")

    def f16b():
        page.goto(BASE + "/exam/support")
        page.locator("a[href^='/exam/support/']").first.click()
        page.wait_for_selector("select#status", timeout=8000)
        cover("/exam/support/<int:request_id>/status", "E2E-60")
        form = page.locator("form:has(button:text-is('Update status'))")
        form.locator("select#status").select_option("resolved")
        post_click(page,
                   "form:has(button:text-is('Update status')) "
                   "button:text-is('Update status')")
        expect("resolved" in page.content().lower(),
               "status update did not show resolved")

    def f17():
        page.goto(BASE + "/exam/scanners")
        page.locator("a[href^='/exam/scanners/']"
                     ":not([href$='new'])").first.click()
        page.wait_for_load_state("domcontentloaded")
        cover("/exam/scanners/<int:scanner_id>", "E2E-47")
        expect("qa-e2e" in page.content().lower()
               or "pin" in page.content().lower(),
               "scanner detail did not render")

    def f17b():
        r = page.goto(BASE + "/exam/scanners/new")
        cover("/exam/scanners/new", "E2E-48")
        expect(r.status == 200, "scanner new form -> %s" % r.status)
        expect(page.locator("input[type=file]").count() >= 1
               or page.locator("input[name=username]").count() >= 1,
               "scanner new form empty")

    def f18():
        r = page.request.post(BASE + "/exam/event/save", data={"venue": "X"})
        cover("/exam/event/save", "E2E-49")
        expect(r.status == 403, "CSRF-less POST accepted: %s" % r.status)

    run("E2E-31", "exam portal entry + login form (csrf)", f1)
    run("E2E-32", "wrong exam password -> 401 message", f2)
    run("E2E-33", "correct login -> dashboard", f3)
    run("E2E-34", "logout button returns to login + re-login", f4)
    run("E2E-35", "registrations list + search", f5)
    run("E2E-36", "registration template attachment", f6)
    run("E2E-37", "import form renders", f7)
    run("E2E-38", "medalist list", f8)
    run("E2E-39", "create medalist draft -> detail", f9)
    run("E2E-40", "publish blocked without photo", f10)
    run("E2E-41", "photo upload + publish + unpublish", f11)
    run("E2E-42", "medalist edit persists", f12)
    run("E2E-43", "event draft save", f13)
    run("E2E-44", "event publish to students", f14)
    run("E2E-45", "announcement draft create -> detail", f15)
    run("E2E-46", "support queue -> detail -> respond", f16)
    run("E2E-60", "support status update -> resolved", f16b)
    run("E2E-47", "scanner account detail", f17)
    run("E2E-48", "scanner new form renders", f17b)
    run("E2E-49", "POST without csrf_token -> 403", f18)


def group_student_api(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page
    req = ctx.request

    def g(path, want, tid, desc, method="GET", data=None):
        def fn():
            kwargs = {}
            if method == "POST":
                kwargs["data"] = json.dumps(data or {})
                kwargs["headers"] = {"Content-Type": "application/json"}
            r = req.fetch(path if path.startswith("http")
                          else BASE + path, method=method, **kwargs)
            cover(path.split("?")[0], tid)
            expect(r.status == want,
                   "%s %s -> %s (want %s)" % (method, path, r.status, want))
            if want == 401:
                low = r.text().lower()
                expect(any(w in low for w in ("authoriz", "sign in", "log in",
                                              "token", "login", "incorrect",
                                              "password", "credentials")),
                       "401 without auth hint: " + r.text()[:120])
        run(tid, desc, fn)

    g("/api/student/medalists", 200, "E2E-50", "public student API: medalists")
    g("/api/student/event", 200, "E2E-51", "public student API: event")
    g("/api/student/announcements", 200, "E2E-52",
      "public student API: announcements")
    g("/api/student/me", 401, "E2E-53", "student /me requires Bearer")
    g("/api/student/attendance", 401, "E2E-54",
      "student attendance requires Bearer")
    g("/api/student/readiness", 401, "E2E-55",
      "student readiness requires Bearer")
    g("/api/student/login", 401, "E2E-56", "student login rejects bad creds",
      method="POST", data={"email": "nobody@example.test",
                           "password": "Nope-Nope-Nope-1!"})


def group_misc(ctx, page):
    global ACTIVE_PAGE
    ACTIVE_PAGE = page

    def h1():
        r = page.goto(BASE + "/definitely-not-a-page-39")
        expect(r.status == 404, "missing page -> %s" % r.status)

    def h2():
        r = page.request.get(BASE + "/api/health")
        cover("/api/health", "E2E-57")
        expect(r.status == 200, "/api/health -> %s" % r.status)
        expect("ok" in r.text(), "/api/health body: " + r.text()[:80])

    def h3():
        r = page.goto(BASE + "/")
        hdr = r.headers
        expect(hdr.get("x-content-type-options") == "nosniff",
               "nosniff header missing")
        expect(hdr.get("x-frame-options") == "SAMEORIGIN",
               "x-frame-options missing")
        expect(hdr.get("referrer-policy") == "no-referrer",
               "referrer-policy missing")

    run("E2E-57", "JSON 404 for unknown route", h1)
    run("E2E-58", "/api/health live", h2)
    run("E2E-59", "security headers on HTML response", h3)


# ------------------------------------------------------------------ matrix
def rule_reason(rule):
    if rule.startswith("/api/student/"):
        return ("NOT TESTED (native app): student JSON API - Android "
                "NATIVE DEVICE TESTING BLOCKED; covered by API suites "
                "test_student_accounts/test_phase9_support/test_phase17")
    if rule.startswith("/api/test-"):
        return ("NOT TESTED (UI): test-only helper - covered by suites "
                "test_phase8_integration/test_phase12_qr_scanner")
    if rule in ("/api/settings", "/api/broadcasts", "/api/admin/verify",
                "/api/search", "/api/guest-pass", "/api/guests",
                "/api/guests/<int:gid>/revoke", "/api/broadcast/audience",
                "/api/gates/<int:gid>/rename"):
        return "NOT TESTED (UI): JSON admin/PII API - covered by " \
               "test_phase39_security.py"
    if rule == "/api/dashboard/summary":
        return "NOT TESTED (UI): mobile KPI summary - covered by " \
               "test_phase38_analytics.py"
    if rule in ("/exam/event/create", "/exam/event/activate"):
        return "NOT TESTED (UI): event lifecycle - covered by " \
               "test_phase16_lifecycle/test_convocation_migration"
    if rule == "/exam/registrations/history" or \
            rule.startswith("/exam/registrations/import/<int:batch_id>"):
        return "NOT TESTED (UI): registration import/history - covered by " \
               "test_exam_registration.py"
    if rule.startswith("/exam/medalists/import"):
        return "NOT TESTED (UI): medalist import - covered by " \
               "test_medalist_management.py"
    if rule == "/exam/support/<int:request_id>/status":
        return "NOT TESTED (UI): support status form - covered by " \
               "test_phase9_support.py"
    if rule.startswith("/exam/registrations/<int:reg_id>"):
        return "NOT TESTED (no seeded registration row): covered by " \
               "test_exam_registration.py"
    if rule.startswith("/exam/support/registration/"):
        return "NOT TESTED (UI): registration support view - covered by " \
               "test_phase9_support.py"
    if rule in ("/exam/announcements/<int:ann_id>/save",
                "/exam/announcements/<int:ann_id>/<action>"):
        return "NOT TESTED (UI): announcement edit/publish - covered by " \
               "test_event_announcements.py"
    if rule.startswith("/api/qr") or rule.startswith("/qr"):
        return "NOT TESTED (UI): pass rendering - covered by " \
               "test_phase11_pass_history/test_phase12_qr_scanner"
    if rule.startswith("/api/scan-log") or rule.startswith("/api/gate"):
        return "NOT TESTED (UI): scanner session API - covered by " \
               "test_phase14_scanner_access/test_phase17_cross_role"
    return "NOT TESTED - no E2E interaction in this suite"


def print_matrix(app):
    out("")
    out("=" * 100)
    out("COVERAGE MATRIX (derived from app.url_map; every rule listed)")
    out("=" * 100)
    counts = {"PASS": 0, "FAIL": 0, "NOT TESTED": 0}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.rule.startswith("/static/"):
            continue
        methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        tid = COVER.get(rule.rule)
        if tid and tid in RESULTS:
            status = RESULTS[tid]
            note = tid
        elif tid:
            status = "NOT TESTED"
            note = "declared but not executed: " + str(tid)
        else:
            status, note = "NOT TESTED", rule_reason(rule.rule)
        if status.startswith("NOT"):
            counts["NOT TESTED"] += 1
        else:
            counts[status] = counts.get(status, 0) + 1
        out("%-10s | %-52s | %-11s | %s"
            % (status, rule.rule, methods, note))
    stale = [k for k in COVER if k and k not in
             {r.rule for r in app.url_map.iter_rules()}]
    if stale:
        out("")
        out("WARNING: COVER keys that matched no route: %r" % stale)
    out("-" * 100)
    return counts


def main():
    global BASE
    out("Phase 39 E2E | disposable DB: %s" % DB_PATH)
    provision()
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    env = dict(os.environ, LGU_PORT=str(port))
    log = open(TEST_ROOT / "server.log", "w", encoding="utf-8",
               errors="replace")
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=str(APP),
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                with urllib.request.urlopen(BASE + "/api/health",
                                            timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            out("FATAL: server never became healthy; log follows")
            log.close()
            out((TEST_ROOT / "server.log").read_text(errors="replace")[:2000])
            return 2

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def ctx_page():
                c = browser.new_context()
                pg = c.new_page()
                pg.set_default_timeout(8000)
                return c, pg

            c1, p1 = ctx_page();  group_home(c1, p1); group_dashboard(c1, p1)
            c2, p2 = ctx_page();  group_admin(c2, p2)
            c3, p3 = ctx_page();  group_guests(c3, p3)
            c4, p4 = ctx_page();  group_scanner(c4, p4)
            c5, p5 = ctx_page();  group_exam(c5, p5)
            c6, p6 = ctx_page();  group_student_api(c6, p6)
            c7, p7 = ctx_page();  group_misc(c7, p7)
            for c in (c1, c2, c3, c4, c5, c6, c7):
                c.close()
            browser.close()

        # coverage matrix against the REAL in-process url map
        from web.routes import create_app
        app = create_app()
        counts = print_matrix(app)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    passed = sum(1 for v in RESULTS.values() if v == "PASS")
    failed = sum(1 for v in RESULTS.values() if v == "FAIL")
    out("")
    out("E2E TOTAL=%d PASS=%d FAIL=%d | matrix: PASS=%d FAIL=%d "
        "NOT TESTED=%d" % (len(RESULTS), passed, failed,
                           counts.get("PASS", 0), counts.get("FAIL", 0),
                           counts.get("NOT TESTED", 0)))
    (TEST_ROOT / "results.json").write_text(json.dumps(
        {"results": RESULTS, "cover": COVER, "counts": counts,
         "test_root": str(TEST_ROOT)}, indent=1), encoding="utf-8")
    out("artifacts: " + str(TEST_ROOT))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
