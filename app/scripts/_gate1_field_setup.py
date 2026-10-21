#!/usr/bin/env python
"""Release Gate 1 — Android field-test world builder (DISPOSABLE DB ONLY).

Builds a throwaway database for the on-device field test: a published
convocation, synthetic registrations with real convocation passes (LGU2),
seeded roster students (LGU1) and guests, and two authorised scanner
accounts with PINs the operator can type on the phone.

It refuses to run against the production database and never touches
app/lgu.db. Nothing here is a product feature; it is test infrastructure for
Release Gate 1 and writes only to a temp directory.

Usage (from app/, repo venv) — set the two environment variables first:

    LGU_TESTING=1
    LGU_DB_PATH=<temp dir>\\field.db

then run:

    & (Resolve-Path "..\\.venv\\Scripts\\python.exe").Path scripts\\_gate1_field_setup.py
"""
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

# --- hard boundary: refuse before anything is created ---------------------
DB_PATH = os.environ.get("LGU_DB_PATH", "")
if not DB_PATH:
    sys.exit("refusing to run: set LGU_DB_PATH to a disposable file first.")
if os.environ.get("LGU_TESTING") != "1":
    sys.exit("refusing to run: set LGU_TESTING=1.")
if config.is_production_db(DB_PATH):
    sys.exit("refusing to run: LGU_DB_PATH resolves to the production DB.")

import database  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import ids  # noqa: E402
import qrgen  # noqa: E402
import scanner_auth  # noqa: E402

NOW = "2026-10-20 09:00:00"
CONV_NAME = "Release Gate 1 Field Test"
OUT_DIR = os.path.dirname(DB_PATH)

# Synthetic convocation students — invented identities, never real records.
CONV_STUDENTS = [
    ("FG-001", "zara.ahmed@lgu.edu.pk", "FG-1001", "Zara Ahmed"),
    ("FG-002", "hina.malik@lgu.edu.pk", "FG-1002", "Hina Malik"),
    ("FG-003", "usman.tariq@lgu.edu.pk", "FG-1003", "Usman Tariq"),
]

# Scanner accounts the operator types on the phone. PINs are test-only and
# live only in this disposable world.
SCANNERS = [
    ("gateA-ana", "Ana Cruz", "481902", [1], "PRIMARY — authorized at gate 1 only"),
    ("gateC-bilal", "Bilal Aslam", "735164", [3], "SECONDARY — authorized at gate 3 only"),
]


def conn():
    return database.get_db()


def build_world():
    db = conn()
    try:
        conv = db.execute(
            "SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        if not db.execute(
                "SELECT 1 FROM convocation_publications WHERE convocation_id = ?",
                (conv,)).fetchone():
            db.execute(
                "INSERT INTO convocation_publications (convocation_id, name,"
                " year, venue, published_by, published_at)"
                " VALUES (?, ?, '2026', 'Main Auditorium', 'release-gate-1', ?)",
                (conv, CONV_NAME, NOW))

        passes = []
        for reg_no, email, roll, name in CONV_STUDENTS:
            db.execute(
                "INSERT INTO convocation_registrations (convocation_id,"
                " registration_number, university_email, roll_number,"
                " student_name, department, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'BSCS', 'active', ?, ?)",
                (conv, reg_no, email, roll, name, NOW, NOW))
            reg = db.execute(
                "SELECT id FROM convocation_registrations WHERE"
                " registration_number = ?", (reg_no,)).fetchone()["id"]
            db.execute(
                "INSERT INTO student_accounts (university_email, password_hash,"
                " created_at, updated_at) VALUES (?, 'scrypt$fake', ?, ?)",
                (email, NOW, NOW))
            acc = db.execute(
                "SELECT id FROM student_accounts WHERE university_email = ?",
                (email,)).fetchone()["id"]
            db.execute(
                "INSERT INTO registration_claims (account_id, convocation_id,"
                " registration_id, created_at) VALUES (?, ?, ?, ?)",
                (acc, conv, reg, NOW))
            token = "fg1-" + secrets.token_urlsafe(24)
            db.execute(
                "INSERT INTO convocation_passes (token_hash, convocation_id,"
                " registration_id, account_id, status, issued_at)"
                " VALUES (?, ?, ?, ?, 'active', ?)",
                (cqr.token_hash(token), conv, reg, acc, NOW))
            passes.append({"name": name, "roll": roll, "reg_no": reg_no,
                           "payload": "LGU2:%s" % token})
        db.commit()
    finally:
        db.close()

    # Roster students (LGU1) and one guest — all outside, from the seed.
    db = conn()
    try:
        roster = [dict(r) for r in db.execute(
            "SELECT name, roll_no, qr_id FROM students ORDER BY id LIMIT 3"
        ).fetchall()]
        guest = db.execute(
            "SELECT name, host_roll_no, qr_id FROM guests ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        db.close()

    scanners = []
    for username, display, pin, gates, note in SCANNERS:
        sid = scanner_auth.create_scanner(username, display, pin, gates,
                                          actor="release-gate-1", via="cli")
        scanners.append({"id": sid, "username": username, "name": display,
                         "pin": pin, "gates": gates, "note": note})

    cards = [
        {"group": "A — ROSTER STUDENT (legacy LGU1) — T3 / T4",
         "cards": [{"label": "%s (%s) — OUTSIDE" % (r["name"], r["roll_no"]),
                    "payload": ids.make_payload(r["qr_id"])} for r in roster]},
        {"group": "B — CONVOCATION PASS (LGU2) — T7",
         "cards": [{"label": "%s (%s) — ELIGIBLE, NEVER ADMITTED" % (p["name"], p["roll"]),
                    "payload": p["payload"]} for p in passes]},
        {"group": "C — GUEST PASS (legacy LGU1)",
         "cards": [{"label": "Guest of %s — OUTSIDE" % guest["host_roll_no"],
                    "payload": ids.make_payload(guest["qr_id"])}]},
        {"group": "D — MUST BE REFUSED",
         "cards": [
             {"label": "FORGED ROSTER CODE (bad signature) — INVALID CODE",
              "payload": "LGU1:FORGED0000:deadbeef0000"},
             {"label": "FORGED CONVOCATION CODE — INVALID CODE",
              "payload": "LGU2:FG-forged-not-a-real-token"},
             {"label": "VALID SIGNATURE, NOT IN SYSTEM — UNKNOWN CODE",
              "payload": ids.make_payload(ids.generate_id())},
         ]},
    ]

    handoff = {"db_path": DB_PATH, "convocation": CONV_NAME, "conv_id": conv,
               "scanners": scanners,
               "passes": passes,
               "roster": [{"name": r["name"], "roll_no": r["roll_no"],
                           "payload": ids.make_payload(r["qr_id"])} for r in roster],
               "cards": cards}

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "handoff.json"), "w", encoding="utf-8") as fh:
        json.dump(handoff, fh, indent=2)
    write_sheet(os.path.join(OUT_DIR, "qr-sheet.html"), cards)
    return handoff


def write_sheet(path, cards):
    parts = [
        "<!doctype html><meta charset='utf-8'>"
        "<title>Release Gate 1 — test QR sheet (DISPOSABLE DB)</title>",
        "<style>body{font:14px/1.4 system-ui,sans-serif;margin:24px;"
        "background:#fff}h2{margin:22px 0 8px;font-size:15px}"
        ".g{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}"
        ".c{border:1px solid #ccc;border-radius:8px;padding:10px;"
        "text-align:center;break-inside:avoid}.c img{width:210px;height:210px}"
        ".c p{margin:6px 0 0;font-weight:600}.bad{background:#fff4f4}"
        "</style>",
        "<h1 style='font-size:19px'>Release Gate 1 — synthetic test QRs</h1>",
        "<p><b>DISPOSABLE TEST DATABASE.</b> Not production data. "
        "Point the phone camera at a code below. Keep the browser window at "
        "full size; if a code will not read, zoom in.</p>",
    ]
    for grp in cards:
        parts.append("<h2>%s</h2><div class='g'>" % grp["group"])
        for card in grp["cards"]:
            cls = "c bad" if "REFUSED" in grp["group"] else "c"
            parts.append(
                "<div class='%s'><img src='%s' alt=''><p>%s</p>"
                "<code style='font-size:10px;word-break:break-all'>%s</code>"
                "</div>" % (cls, qrgen.qr_data_uri(card["payload"], box_size=3),
                            card["label"], card["payload"]))
        parts.append("</div>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))


if __name__ == "__main__":
    database.init_db()
    database.seed()
    w = build_world()
    print("disposable DB : %s" % w["db_path"])
    print("convocation   : %s (id=%s, PUBLISHED)" % (w["convocation"], w["conv_id"]))
    print("")
    print("SCANNER ACCOUNTS (type these on the phone)")
    for s in w["scanners"]:
        print("  id=%s  username=%-12s PIN=%s  gates=%s  -- %s"
              % (s["id"], s["username"], s["pin"], ",".join(map(str, s["gates"])),
                 s["note"]))
    print("")
    print("CONVOCATION PASSES (LGU2) for T7")
    for p in w["passes"]:
        print("  %-14s %s" % (p["name"], p["payload"]))
    print("")
    print("QR sheet      : %s" % os.path.join(OUT_DIR, "qr-sheet.html"))
    print("handoff       : %s" % os.path.join(OUT_DIR, "handoff.json"))
