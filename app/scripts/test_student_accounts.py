"""Phase 5 regression: student accounts, verification, sessions, profile.

Run from app/:  .venv\\Scripts\\python.exe scripts\\test_student_accounts.py
Temp databases only — the production DB is never opened.
"""

import base64
import os
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p5-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")
os.environ["LGU_EMAIL_MODE"] = "fake"  # test-only provider (gated in emailer)
# photos must never land in the repo — keep them inside the temp workspace
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "photos")

from io import BytesIO  # noqa: E402

from PIL import Image  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import migrations  # noqa: E402
import student_auth as sa  # noqa: E402
from web import student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
CONV = 1
PHASE5_TABLES = {"student_accounts", "student_profiles", "registration_claims",
                 "verification_challenges", "student_sessions", "audit_log"}


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    try:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def sql_exec(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def tables():
    return [r["name"] for r in raw(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def dump_all():
    out = {}
    for t in tables():
        out[t] = raw("SELECT * FROM %s" % t)
    return out


def reset_limits():
    for bucket in sr._HITS:
        sr._HITS[bucket].clear()


def conv_id():
    return raw("SELECT id FROM convocations WHERE is_active = 1")[0]["id"]


def add_reg(reg_no, email, roll, name, status="active", dept="BSCS"):
    now = "2026-10-01T00:00:00+00:00"
    sql_exec(
        "INSERT INTO convocation_registrations"
        " (convocation_id, registration_number, university_email, roll_number,"
        "  student_name, department, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (CONV, reg_no, email, roll, name, dept, status, now, now))


def post(path, body=None, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.post(path, json=body or {}, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def get(path, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.get(path, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def signup(reg_no, email, roll, name, password="correct-horse-batt"):
    """verify -> outbox code -> complete; returns (status, body)."""
    emailer.OUTBOX.clear()
    st, body = post("/api/student/verify", {"registration_number": reg_no,
                                            "university_email": email,
                                            "roll_number": roll,
                                            "student_name": name})
    if st != 200:
        return st, body
    code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else ""
    return post("/api/student/complete",
                {"challenge_id": body["challenge_id"], "code": code,
                 "password": password})


database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()

# ----------------------------------------------------- A. migration v4+6
# Phase 6 appends migration 5 (medalist tables), Phase 7 migration 6
# (event publications + announcements), and later phases append further
# migrations on top; the schema version is the latest migration, applied
# exactly once.
check("migration: user_version is the latest",
      sqlite3.connect(config.DB_PATH).execute(
          "PRAGMA user_version").fetchone()[0] == migrations.MIGRATIONS[-1][0])
for table in ("student_accounts", "student_profiles", "registration_claims",
              "verification_challenges", "student_sessions"):
    check("migration: table %s exists" % table,
          table in tables())

legacy = os.path.join(TMP, "legacy.db")
lc = sqlite3.connect(legacy)
# A real "old" database always has the base schema; later migrations
# (v13 on) ALTER tables SCHEMA creates, so seed it before replaying.
lc.executescript(database.SCHEMA)
for version, script in migrations.MIGRATIONS[:-1]:
    lc.executescript(script + "\nPRAGMA user_version = %d;" % version)
lc.close()
old_path = config.DB_PATH
config.DB_PATH = legacy
database.init_db()
check("migration: legacy schema upgrades to the latest",
      sqlite3.connect(legacy).execute(
          "PRAGMA user_version").fetchone()[0] == migrations.MIGRATIONS[-1][0])
database.init_db()  # idempotent re-run
check("migration: re-run stays at the latest",
      sqlite3.connect(legacy).execute(
          "PRAGMA user_version").fetchone()[0] == migrations.MIGRATIONS[-1][0])
config.DB_PATH = old_path

# ------------------------------------------------- B. delivery fail-closed
reset_limits()
add_reg("REG-9001", "silent1@uni.edu.pk", "09001", "Silent One")
email_sent = len(emailer.OUTBOX)
st, body = post("/api/student/verify", {"registration_number": "REG-9001",
                                        "university_email": "silent1@uni.edu.pk",
                                        "roll_number": "09001",
                                        "student_name": "Silent One"})
check("verify works in fake mode (baseline)", st == 200, (st, body))
check("verify sent exactly one code", len(emailer.OUTBOX) == email_sent + 1)
code = emailer.OUTBOX[-1][1]
row = raw("SELECT * FROM verification_challenges ORDER BY id DESC LIMIT 1")[0]
check("code stored only as digest", code not in str(row) and
      row["code_hash"] != code)
check("verify response never carries the code", code not in str(body))

saved = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
reset_limits()
add_reg("REG-9006", "disabled1@uni.edu.pk", "09006", "Disabled One")
st, body = post("/api/student/verify", {"registration_number": "REG-9006",
                                        "university_email":
                                        "disabled1@uni.edu.pk",
                                        "roll_number": "09006",
                                        "student_name": "Disabled One"})
check("disabled mode: verify fails closed 503",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
st, body = post("/api/student/recovery/request",
                {"email": "disabled1@uni.edu.pk"})
check("disabled mode: recovery 503 before any lookup",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
st, body = post("/api/student/recovery/request",
                {"email": "nobody-at-all@uni.edu.pk"})
check("disabled mode: unknown email also 503 (no oracle)",
      st == 503, (st, body))
st, body = post("/api/student/verify", {"registration_number": "REG-9006",
                                        "university_email":
                                        "disabled1@uni.edu.pk",
                                        "roll_number": "09006",
                                        "student_name": "Disabled One"})
check("disabled mode: verify fails again (still no send)",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
check("failed send creates no challenge",
      not raw("SELECT 1 FROM verification_challenges WHERE university_email"
              " = 'disabled1@uni.edu.pk'"), "challenge row exists")
config.EMAIL_MODE = saved

# ------------------------------------------- C. verify matching + states
reset_limits()
add_reg("04550", "Case.Variation@Uni.EDU.PK", "0004550",
        "Ahmad  Ali  Khan")
st, body = post("/api/student/verify", {
    "registration_number": "  04550 ", "university_email":
    "case.variation@uni.edu.pk", "roll_number": " 0004550",
    "student_name": "  ahmad   ali   khan "})
check("verify: whitespace/case normalisation + leading zeros", st == 200,
      (st, body))
check("verify: masked email keeps domain",
      body.get("masked_email", "").startswith("c") and
      "•••" in body["masked_email"] and
      body["masked_email"].endswith("@uni.edu.pk"),
      body.get("masked_email"))
check("verify: pending false + resend budget on first send",
      body.get("pending") is False and body.get("resend_remaining") == 2)
check("verify: expiry about 600s", 550 <= body.get("expires_in", 0) <= 600)
challenge_1 = body["challenge_id"]
emails_before = len(emailer.OUTBOX)
st, body2 = post("/api/student/verify", {
    "registration_number": "04550", "university_email":
    "CASE.VARIATION@uni.edu.pk", "roll_number": "0004550",
    "student_name": "Ahmad Ali Khan"})
check("verify: active challenge reused (pending, no second email)",
      st == 200 and body2.get("pending") is True and
      body2["challenge_id"] == challenge_1 and
      len(emailer.OUTBOX) == emails_before, (st, body2))

st, body = post("/api/student/verify", {"registration_number": "04550",
                                        "university_email":
                                        "case.variation@uni.edu.pk",
                                        "roll_number": "0004550",
                                        "student_name": "Someone Else"})
check("verify: name mismatch -> 404 unmatched",
      st == 404 and body.get("code") == "unmatched", (st, body))
st, body = post("/api/student/verify", {"registration_number": "4550",
                                        "university_email":
                                        "case.variation@uni.edu.pk",
                                        "roll_number": "0004550",
                                        "student_name": "Ahmad Ali Khan"})
check("verify: leading zeros are significant -> unmatched", st == 404)
st, body = post("/api/student/verify", {"registration_number": "04550",
                                        "roll_number": "0004550",
                                        "student_name": "Ahmad Ali Khan"})
check("verify: missing field -> 400 missing_field",
      st == 400 and body.get("code") == "missing_field", (st, body))
st, body = post("/api/student/verify", {"registration_number": "04550",
                                        "university_email": "not-an-email",
                                        "roll_number": "0004550",
                                        "student_name": "Ahmad Ali Khan"})
check("verify: malformed email -> 400 email", st == 400 and
      body.get("code") == "email", (st, body))

add_reg("REG-9002", "canceled1@uni.edu.pk", "09002", "Cancelled One",
        status="cancelled")
add_reg("REG-9003", "revoked1@uni.edu.pk", "09003", "Revoked One",
        status="revoked")
reset_limits()
for reg_no, mail, roll, name, want in (
        ("REG-9002", "canceled1@uni.edu.pk", "09002", "Cancelled One",
         "cancelled"),
        ("REG-9003", "revoked1@uni.edu.pk", "09003", "Revoked One",
         "revoked")):
    st, body = post("/api/student/verify", {"registration_number": reg_no,
                                            "university_email": mail,
                                            "roll_number": roll,
                                            "student_name": name})
    check("verify: %s registration -> 410" % want,
          st == 410 and body.get("code") == want, (st, body))

saved_conv = conv_id()
sql_exec("UPDATE convocations SET is_active = 0 WHERE id = ?", (saved_conv,))
reset_limits()
st, body = post("/api/student/verify", {"registration_number": "REG-9001",
                                        "university_email": "silent1@uni.edu.pk",
                                        "roll_number": "09001",
                                        "student_name": "Silent One"})
check("verify: no active convocation -> 409", st == 409 and
      body.get("code") == "no_convocation", (st, body))
sql_exec("UPDATE convocations SET is_active = 1 WHERE id = ?", (saved_conv,))

# ------------------------------------------- D. challenge life cycle
# drop the pending baseline challenge so this verify sends a fresh email
sql_exec("UPDATE verification_challenges SET consumed_at ="
         " '2026-10-01T00:00:00+00:00' WHERE university_email ="
         " 'silent1@uni.edu.pk'")
reset_limits()
emailer.OUTBOX.clear()
st, body = post("/api/student/verify", {"registration_number": "REG-9001",
                                        "university_email": "silent1@uni.edu.pk",
                                        "roll_number": "09001",
                                        "student_name": "Silent One"})
cid, code = body["challenge_id"], emailer.OUTBOX[-1][1]
st, b = post("/api/student/complete", {"challenge_id": cid, "code": "000000"
                                       if code != "000000" else "111111",
                                       "password": "correct-horse-batt"})
check("complete: wrong code -> 400", st == 400 and
      b.get("code") == "code", (st, b))
st, b = post("/api/student/complete", {"challenge_id": cid, "code": ""})
check("complete: empty code -> 400 missing_field", st == 400 and
      b.get("code") == "missing_field", (st, b))
st, b = post("/api/student/complete", {"challenge_id": cid})
check("complete: absent code -> 400 missing_field", st == 400 and
      b.get("code") == "missing_field")
st, b = post("/api/student/complete", {"challenge_id": 999999, "code": code})
check("complete: unknown challenge -> 404", st == 404 and
      b.get("code") == "challenge", (st, b))
st, b = post("/api/student/complete", {"challenge_id": cid, "code": code})
check("complete: without password on new account -> 400", st == 400 and
      b.get("code") == "password", (st, b))
st, b = post("/api/student/complete", {"challenge_id": cid, "code": code,
                                       "password": "short"})
check("complete: weak password -> 400 (code NOT consumed)",
      st == 400 and b.get("code") == "password", (st, b))
st, b = post("/api/student/complete", {"challenge_id": cid, "code": code,
                                       "password": "correct-horse-batt"})
check("complete: success after rejected attempts", st == 200 and
      b.get("token") and b.get("registration", {}).get(
          "registration_number") == "REG-9001", (st, list(b)))
token_1 = b.get("token", "")
check("complete: profile + completion payload",
      b.get("profile") is not None and b["completion"]["done"] == 2 and
      b["completion"]["total"] == 3, b.get("completion"))
check("complete: password not stored plaintext",
      all(p["password_hash"] != "correct-horse-batt" and
          p["password_hash"].startswith("scrypt:")
          for p in raw("SELECT password_hash FROM student_accounts")))
check("complete: session token stored as digest",
      token_1 not in str(raw("SELECT * FROM student_sessions")))
st, b = post("/api/student/complete", {"challenge_id": cid, "code": code,
                                       "password": "correct-horse-batt"})
check("complete: replayed code rejected (single use)", st == 410, (st, b))
st, b = post("/api/student/resend", {"challenge_id": cid})
check("resend: consumed challenge -> 410", st == 410, (st, b))

# expired challenge
add_reg("REG-9010", "expire1@uni.edu.pk", "09010", "Expire One")
reset_limits()
emailer.OUTBOX.clear()
st, b = post("/api/student/verify", {"registration_number": "REG-9010",
                                     "university_email": "expire1@uni.edu.pk",
                                     "roll_number": "09010",
                                     "student_name": "Expire One"})
cid2 = b["challenge_id"]
sql_exec("UPDATE verification_challenges SET expires_at = '2000-01-01T00:00:00"
         "+00:00' WHERE id = ?", (cid2,))
st, b = post("/api/student/complete", {"challenge_id": cid2,
                                       "code": emailer.OUTBOX[-1][1],
                                       "password": "correct-horse-batt"})
check("complete: expired code -> 410 expired", st == 410 and
      b.get("code") == "expired", (st, b))
st, b = post("/api/student/resend", {"challenge_id": cid2})
check("resend: after expiry still allowed -> 200", st == 200, (st, b))

# attempts cap (attempt_count survives resend by design)
sql_exec("UPDATE verification_challenges SET attempt_count = 5,"
         " expires_at = '2099-01-01T00:00:00+00:00' WHERE id = ?", (cid2,))
st, b = post("/api/student/complete", {"challenge_id": cid2,
                                       "code": emailer.OUTBOX[-1][1],
                                       "password": "correct-horse-batt"})
check("complete: attempt cap -> 429 attempts", st == 429 and
      b.get("code") == "attempts", (st, b))
sql_exec("UPDATE verification_challenges SET sent_count = 3,"
         " attempt_count = 0 WHERE id = ?", (cid2,))
st, b = post("/api/student/resend", {"challenge_id": cid2})
check("resend: send cap -> 429 send_limit", st == 429 and
      b.get("code") == "send_limit", (st, b))

# claimed registration refuses a second verify
st, b = post("/api/student/verify", {"registration_number": "REG-9001",
                                     "university_email": "silent1@uni.edu.pk",
                                     "roll_number": "09001",
                                     "student_name": "Silent One"})
check("verify: claimed registration -> 409 claimed", st == 409 and
      b.get("code") == "claimed", (st, b))

# ---------------------------------------------- E. rate limits (per IP)
reset_limits()
saved_max = config.STUDENT_RATE_MAX_VERIFY
config.STUDENT_RATE_MAX_VERIFY = 1
add_reg("REG-9020", "ratelimit@uni.edu.pk", "09020", "Rate Limit")
emailer.OUTBOX.clear()
st, b = post("/api/student/verify", {"registration_number": "REG-9020",
                                     "university_email": "ratelimit@uni.edu.pk",
                                     "roll_number": "09020",
                                     "student_name": "Rate Limit"})
st2, b2 = post("/api/student/verify", {"registration_number": "REG-9020",
                                       "university_email":
                                       "ratelimit@uni.edu.pk",
                                       "roll_number": "09020",
                                       "student_name": "Rate Limit"})
check("verify: per-IP send limit -> 429 rate_limited",
      st == 200 and st2 == 429 and b2.get("code") == "rate_limited",
      (st, st2, b2))
config.STUDENT_RATE_MAX_VERIFY = saved_max
reset_limits()

# ------------------------------------------------------- F. login/sessions
reset_limits()
st, b = post("/api/student/login", {"email": "SILENT1@uni.edu.pk",
                                    "password": "correct-horse-batt"})
check("login: success (case-insensitive email)", st == 200 and
      b.get("token") and b["account"]["email"] == "silent1@uni.edu.pk",
      (st, b.get("account")))
token_login = b.get("token", "")
st, b = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "wrong-password-x"})
check("login: wrong password -> 401 credentials", st == 401 and
      b.get("code") == "credentials", (st, b))
for _ in range(4):
    reset_limits()
    post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                "password": "wrong-password-x"})
reset_limits()
st, b = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "correct-horse-batt"})
check("login: lockout after 5 failures -> 429 locked", st == 429 and
      b.get("code") == "locked", (st, b))
sql_exec("UPDATE student_accounts SET failed_attempts = 0,"
         " locked_until = NULL WHERE university_email = 'silent1@uni.edu.pk'")
st, b = get("/api/student/me", token_login)
check("me: authorised payload with official record",
      st == 200 and b["registration"]["registration_number"] == "REG-9001" and
      b["registration"]["roll_number"] == "09001" and
      b["registration"]["status"] == "active" and
      b["account"]["email"] == "silent1@uni.edu.pk", (st, b.get("registration")))
check("me: completion complete after claim (2/3)",
      b["completion"]["done"] == 2 and not b["completion"]["complete"],
      b["completion"])
st, b = get("/api/student/me")
check("me: missing token -> 401 auth", st == 401 and
      b.get("code") == "auth", (st, b))
st, b = get("/api/student/me", "forged-token-value")
check("me: forged token -> 401", st == 401, (st, b))
st, b = post("/api/student/logout", {}, token_login)
check("logout: 200", st == 200 and b.get("ok") is True)
st, b = get("/api/student/me", token_login)
check("logout: token revoked -> 401", st == 401, (st, b))
st, b = post("/api/student/logout", {}, "forged-token")
check("logout: idempotent for unknown tokens", st == 200, (st, b))

# expired session
reset_limits()
st, b = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "correct-horse-batt"})
old_token = b["token"]
sql_exec("UPDATE student_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"
         " WHERE token_hash = ?",
         (sa._token_hash(old_token),))
st2, _ = get("/api/student/me", old_token)
check("session: expired token -> 401", st2 == 401, st2)

# cross-account isolation
add_reg("REG-9030", "second@uni.edu.pk", "09030", "Second Student")
st, b1 = signup("REG-9030", "second@uni.edu.pk", "09030", "Second Student")
check("signup: second account works", st == 200, (st, b1))
st, b = get("/api/student/me", b1.get("token", ""))
check("isolation: account B sees only its own registration",
      st == 200 and b["registration"]["registration_number"] == "REG-9030" and
      b["account"]["email"] == "second@uni.edu.pk", (st, b.get("registration")))

# ---------------------------------------------------------- G. profile
st, b = post("/api/student/profile", {"phone": "+92 300 1234567"},
             b1["token"])
check("profile: phone saved", st == 200 and
      b["profile"]["phone"] == "+92 300 1234567", (st, b))
st, b = post("/api/student/profile", {}, b1["token"])
check("profile: phone required -> 400", st == 400 and
      b.get("code") == "missing_field", (st, b))
st, b = post("/api/student/profile", {"phone": "x" * 33}, b1["token"])
check("profile: phone length cap -> 400", st == 400 and
      b.get("code") == "profile", (st, b))
st, b = post("/api/student/profile", {"phone": "12345",
                                      "registration_number": "HACKED"},
             b1["token"])
reg_row = raw("SELECT * FROM convocation_registrations WHERE id ="
              " (SELECT registration_id FROM registration_claims WHERE"
              " account_id = (SELECT id FROM student_accounts WHERE"
              " university_email = 'second@uni.edu.pk'))")[0]
check("profile: official fields read-only",
      st == 200 and reg_row["registration_number"] == "REG-9030",
      (st, reg_row["registration_number"]))

# photo: valid png
png = BytesIO()
Image.new("RGB", (40, 40), (10, 120, 60)).save(png, "PNG")
st, b = post("/api/student/profile/photo",
             {"data": base64.b64encode(png.getvalue()).decode()},
             b1["token"])
check("photo: valid upload -> 200 + completion",
      st == 200 and b["profile"]["photo"] and
      b["completion"]["done"] == 3 and b["completion"]["complete"],
      (st, b))
files_after = os.listdir(config.STUDENT_PHOTO_DIR)
check("photo: random filename on disk", len(files_after) == 1 and
      files_after[0] != "x.png", files_after)
r = client.get("/api/student/profile/photo",
               headers={"Authorization": "Bearer %s" % b1["token"]})
check("photo: owner fetch -> bytes with no-store header",
      r.status_code == 200 and
      r.data.startswith(b"\x89PNG") and
      r.headers.get("Cache-Control") == "private, no-store",
      r.status_code)
st, _ = get("/api/student/profile/photo")
check("photo: no token -> 401", st == 401, st)
reset_limits()
st, lb = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "correct-horse-batt"})
live_a_token = lb.get("token", "")
st, _ = get("/api/student/profile/photo", live_a_token)
check("photo: other account -> 404 (never another student's photo)",
      st == 404, (st, lb.get("ok")))
static_dir = os.path.join(APP_DIR, "web", "static")
leaked = [f for f in os.listdir(static_dir)
          if os.path.isfile(os.path.join(static_dir, f))
          and open(os.path.join(static_dir, f), "rb").read(4) == b"\x89PNG"]
check("photo: never placed in public static", not leaked, leaked)
st, b = post("/api/student/profile/photo", {"data": "not-base64!!"},
             b1["token"])
check("photo: invalid base64 -> 400", st == 400 and
      b.get("code") == "photo", (st, b))
st, b = post("/api/student/profile/photo",
             {"data": base64.b64encode(b"GIF89a" + b"\x00" * 30).decode()},
             b1["token"])
check("photo: gif (wrong type) -> 400", st == 400 and
      b.get("code") == "photo", (st, b))
st, b = post("/api/student/profile/photo",
             {"data": base64.b64encode(
                 b"\x89PNG\r\n\x1a\n" + b"garbage-not-a-real-image").decode()},
             b1["token"])
check("photo: corrupt png -> 400", st == 400 and b.get("code") == "photo",
      (st, b))
big = base64.b64encode(b"\xff\xd8\xff" + b"\x00" *
                       (config.PHOTO_MAX_BYTES + 10)).decode()
st, b = post("/api/student/profile/photo", {"data": big}, b1["token"])
check("photo: oversize -> 400", st == 400 and b.get("code") == "photo",
      (st, b))
check("photo: failed uploads do not add files",
      len(os.listdir(config.STUDENT_PHOTO_DIR)) == 1)

# ------------------------------------------------------ H. recovery
saved = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
st, b = post("/api/student/recovery/request", {"email": "silent1@uni.edu.pk"})
check("recovery: disabled delivery fails closed", st == 503, (st, b))
config.EMAIL_MODE = saved
reset_limits()
emails_before = len(emailer.OUTBOX)
st, b = post("/api/student/recovery/request", {"email": "ghost@uni.edu.pk"})
check("recovery: unknown email -> 200, nothing sent",
      st == 200 and len(emailer.OUTBOX) == emails_before, (st, b))
emailer.OUTBOX.clear()
st, b = post("/api/student/recovery/request", {"email": "silent1@uni.edu.pk"})
check("recovery: known email -> 200 + code sent",
      st == 200 and len(emailer.OUTBOX) == 1, (st, b))
rcid, rcode = raw("SELECT * FROM verification_challenges WHERE purpose ="
                  " 'recovery' ORDER BY id DESC LIMIT 1")[0]["id"], \
    emailer.OUTBOX[-1][1]
st, b = post("/api/student/recovery/complete",
             {"code": rcode, "password": "new-password-99"})
check("recovery: complete without id or email -> 400",
      st == 400 and b.get("code") == "missing_field", (st, b))
st, b = post("/api/student/recovery/complete",
             {"email": "SILENT1@uni.edu.pk", "code": rcode,
              "password": "new-password-99"})
check("recovery: complete by email -> 200", st == 200 and
      b.get("ok") is True, (st, b))
reset_limits()
st, b = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "new-password-99"})
check("recovery: new password logs in", st == 200, (st, b))
reset_limits()
st, b = post("/api/student/login", {"email": "silent1@uni.edu.pk",
                                    "password": "correct-horse-batt"})
check("recovery: old password rejected", st == 401, (st, b))
check("recovery: all sessions revoked",
      raw("SELECT revoked_at FROM student_sessions WHERE token_hash = ?",
          (sa._token_hash(live_a_token),))[0]["revoked_at"] is not None)
st, b = post("/api/student/recovery/complete", {"challenge_id": rcid,
                                                "code": rcode,
                                                "password": "newer-pass-100"})
check("recovery: code single-use -> 410", st == 410, (st, b))
saved_max = config.STUDENT_RATE_MAX_RECOVERY
config.STUDENT_RATE_MAX_RECOVERY = 1
reset_limits()
post("/api/student/recovery/request", {"email": "second@uni.edu.pk"})
st, b = post("/api/student/recovery/request", {"email": "second@uni.edu.pk"})
check("recovery: per-IP limit -> 429", st == 429 and
      b.get("code") == "rate_limited", (st, b))
config.STUDENT_RATE_MAX_RECOVERY = saved_max
reset_limits()

# ------------------------------------ I. duplicate claims are impossible
dup = raw("SELECT id FROM student_accounts WHERE university_email ="
          " 'second@uni.edu.pk'")[0]["id"]
try:
    sql_exec("INSERT INTO registration_claims (account_id, convocation_id,"
             " registration_id, created_at) VALUES (?, 1, 1, 'now')",
             (dup,))
    check("claims: UNIQUE(account, convocation) enforced", False)
except sqlite3.IntegrityError:
    check("claims: UNIQUE(account, convocation) enforced", True)
sql_exec("INSERT INTO student_accounts (university_email, created_at,"
         " updated_at) VALUES ('claimtest@uni.edu.pk', 'x', 'x')")
fresh = raw("SELECT id FROM student_accounts WHERE university_email ="
            " 'claimtest@uni.edu.pk'")[0]["id"]
try:
    sql_exec("INSERT INTO registration_claims (account_id, convocation_id,"
             " registration_id, created_at) VALUES (?, 1, 1, 'now')",
             (fresh,))
    check("claims: UNIQUE(convocation, registration) enforced", False)
except sqlite3.IntegrityError:
    check("claims: UNIQUE(convocation, registration) enforced", True)
try:
    sql_exec("INSERT INTO student_accounts (university_email, created_at,"
             " updated_at) VALUES ('SECOND@uni.edu.pk', 'x', 'x')")
    check("accounts: email UNIQUE case-insensitive", False)
except sqlite3.IntegrityError:
    check("accounts: email UNIQUE case-insensitive", True)

# -------------------------------------- J. operational data preserved
add_reg("REG-9040", "preserved@uni.edu.pk", "09040", "Preserved One")
before = {t: rows for t, rows in dump_all().items()
          if t not in PHASE5_TABLES}
# one full flow proves signup touches nothing operational
reset_limits()
signup("REG-9040", "preserved@uni.edu.pk", "09040", "Preserved One")
after = {t: rows for t, rows in dump_all().items()
         if t not in PHASE5_TABLES}
changed = [t for t in sorted(set(before) | set(after))
           if before.get(t) != after.get(t)]
check("preservation: volunteer/operational tables byte-identical",
      not changed, changed)
check("preservation: student tables all populated",
      all(raw("SELECT COUNT(*) AS n FROM %s" % t)[0]["n"] > 0
          for t in ("student_accounts", "student_profiles",
                    "registration_claims", "verification_challenges",
                    "student_sessions")))
check("audit: registration_claimed recorded",
      raw("SELECT COUNT(*) AS n FROM audit_log WHERE action ="
          " 'registration_claimed'")[0]["n"] >= 3)
check("audit: password_reset recorded",
      raw("SELECT COUNT(*) AS n FROM audit_log WHERE action ="
          " 'password_reset'")[0]["n"] >= 1)

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
