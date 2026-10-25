"""Visual acceptance of the real Expo web app; synthetic local accounts only."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "mobile" / "visual-evidence"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:" + os.environ.get("LGU_VISUAL_PORT", "8081")
env = dict(os.environ, CI="1", EXPO_OFFLINE="1", EXPO_NO_TELEMETRY="1")
processes = []
logs = []
def launch(command, cwd, name):
    log = (OUT / name).open("w", encoding="utf-8")
    logs.append(log)
    processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))
def wait_url(url, seconds=150):
    for _ in range(seconds):
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200: return
        except OSError: pass
        time.sleep(1)
    raise RuntimeError("Service failed to start: " + url)

try:
    if not os.environ.get("LGU_VISUAL_USE_RUNNING"):
        launch([sys.executable, str(ROOT / "app/scripts/run_local_mobile.py")], ROOT, "backend.log")
    wait_url("http://localhost:5000/api/health")
    if not os.environ.get("LGU_VISUAL_USE_RUNNING"):
        launch([shutil.which("node"), "node_modules/expo/bin/cli", "start", "--web", "--port", "8081"], ROOT / "mobile", "metro.log")
    wait_url(WEB + "/status")
    credentials = {}
    for line in (Path.home() / "LGU-Local-Mobile/TEST-LOGIN-DETAILS.txt").read_text().splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            credentials[key] = value
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        for width, height in [(360, 700), (390, 744)]:
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, permissions=["camera"])
            page = context.new_page()
            try:
                page.goto(WEB + "/mode-picker", wait_until="domcontentloaded", timeout=240000)
                signin = page.get_by_role("button", name="Sign in", exact=True)
                expect(signin).to_be_visible(timeout=120000)
                page.evaluate("async () => { await document.fonts.ready; await Promise.all(Array.from(document.images).map(i => i.decode().catch(() => {}))); }")
                create = page.get_by_role("button", name="Create student account", exact=True)
                expect(create).to_be_visible(timeout=30000)
                expect(page.get_by_role("button", name="Home", exact=True)).to_have_count(0)
                page.screenshot(path=str(OUT / ("welcome-%d.png" % width)), full_page=True)
                assert create.bounding_box()["y"] < height - 48
                staff = page.get_by_role("button", name="Staff & event access", exact=True)
                assert staff.bounding_box()["y"] + staff.bounding_box()["height"] <= height
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.get_by_role("button", name="Connection settings", exact=True).click()
                page.get_by_label("Server address", exact=True).fill("http://localhost:5000")
                page.get_by_role("button", name="Test and save connection", exact=True).click()
                expect(page.get_by_text("Connected to LGU Convocation. You can now sign in.", exact=True)).to_be_visible()
                page.get_by_role("button", name="Continue", exact=True).click()
                signin.click()
                expect(page.get_by_label("University email", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Home", exact=True)).to_have_count(0)
                page.screenshot(path=str(OUT / ("signin-%d.png" % width)), full_page=True)
                page.get_by_label("University email", exact=True).fill(credentials["Student email"])
                page.get_by_label("Password", exact=True).fill(credentials["Student password"])
                page.get_by_role("button", name="Sign in", exact=True).click()
                account = page.get_by_role("button", name="Account", exact=True)
                account.wait_for(state="visible", timeout=30000)
                account.click()
                expect(page.get_by_role("button", name="Profile & contact details", exact=True)).to_be_visible()
                page.screenshot(path=str(OUT / ("account-%d.png" % width)), full_page=True)
                page.get_by_role("button", name="Staff & event access", exact=True).click()
                expect(page.get_by_role("button", name="Volunteer Operations", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Volunteer Operations", exact=True)).to_be_enabled(timeout=20000)
                page.screenshot(path=str(OUT / ("event-tools-%d.png" % width)), full_page=True)
                # Exercise the actual admin UI, not just HTTP status checks.
                page.goto(WEB + "/administration")
                page.get_by_label("Administrator PIN", exact=True).fill(credentials["Admin PIN"])
                page.get_by_role("button", name="Unlock", exact=True).click()
                page.get_by_role("button", name="Edit student event", exact=True).click(timeout=30000)
                case_id = str(time.time_ns())
                page.get_by_label("Student event name", exact=True).fill("LGU Convocation 2026")
                page.get_by_label("Provisional ceremony date", exact=True).fill("2026-12-12")
                page.get_by_label("Confirmed ceremony date", exact=True).fill("")
                page.get_by_label("Student instructions", exact=True).fill("Synthetic UI acceptance schedule, not an official event notice. " + case_id)
                page.get_by_role("button", name="Save student event draft", exact=True).click()
                review = page.get_by_role("button", name="Review event publication", exact=True)
                expect(review).to_be_enabled(timeout=30000)
                review.click()
                page.get_by_role("button", name="Publish saved event", exact=True).click()
                expect(page.get_by_text("Event published. Eligible students can now issue their entry QR.", exact=True)).to_be_visible(timeout=30000)
                page.get_by_role("button", name="Write student update", exact=True).click()
                update_title = "Phone UI acceptance %dx%d %s" % (width, height, case_id)
                page.get_by_label("Student update title", exact=True).fill(update_title)
                page.get_by_label("Student update message", exact=True).fill("Synthetic acceptance message. No external delivery.")
                page.get_by_role("button", name="Review student update", exact=True).click()
                page.get_by_role("button", name="Publish student update", exact=True).click()
                expect(page.get_by_text("Published in student Updates. No SMS or email was sent.", exact=True)).to_be_visible(timeout=30000)
                page.goto(WEB + "/announcements")
                expect(page.get_by_text(update_title, exact=True)).to_be_visible(timeout=30000)
                page.screenshot(path=str(OUT / ("published-updates-%d.png" % width)), full_page=True)
                # Login must precede gate selection and camera use.
                page.goto(WEB + "/scanner")
                page.get_by_label("Username", exact=True).fill(credentials["Scanner username"])
                page.get_by_label("PIN", exact=True).fill(credentials["Scanner PIN"])
                expect(page.get_by_role("button", name="Done", exact=True)).to_have_count(0)
                page.get_by_role("button", name="Sign in", exact=True).click()
                main_gate = page.get_by_role("button", name="Main Gate", exact=True)
                main_gate.wait_for(state="visible", timeout=30000)
                expect(page.get_by_role("button", name="East Gate", exact=True)).to_have_count(0)
                main_gate.click()
                page.get_by_role("button", name="Done", exact=True).click()
                expect(page.get_by_role("button", name="Done", exact=True)).to_be_hidden(timeout=10000)
                manual = page.get_by_role("button", name="Find manually", exact=True)
                expect(manual).to_be_visible(timeout=30000)
                box = manual.bounding_box()
                assert box["y"] + box["height"] < height - 40, box
                page.screenshot(path=str(OUT / ("scanner-controls-%d.png" % width)), full_page=True)
                page.get_by_role("button", name="Guests", exact=True).click()
                page.get_by_role("button", name="+ Add guest", exact=True).click()
                expect(page.get_by_label("Guest name", exact=True)).to_be_visible()
                assert page.get_by_label("Guest name", exact=True).bounding_box()["y"] < page.get_by_text(re.compile("^Guest list")).first.bounding_box()["y"]
                page.screenshot(path=str(OUT / ("guest-form-%d.png" % width)), full_page=True)
                page.get_by_role("button", name="More", exact=True).click()
                page.get_by_role("button", name="Administrator access", exact=True).click()
                page.get_by_label("Administrator PIN", exact=True).fill(credentials["Admin PIN"])
                page.get_by_role("button", name="Unlock", exact=True).click()
                volunteers = page.get_by_role("button", name="Volunteers", exact=True)
                expect(volunteers).to_be_visible(timeout=30000)
                volunteers.click()
                page.screenshot(path=str(OUT / ("broadcast-audience-%d.png" % width)), full_page=True)
                page.goto(WEB + "/event-tools")
                response = context.request.put("http://localhost:5000/api/settings",
                    headers={"X-Admin-Pin": credentials["Admin PIN"]},
                    data={"volunteer_enabled": "false", "liveboard_enabled": "false"})
                assert response.ok
                expect(page.get_by_role("button", name="Volunteer Operations", exact=True)).to_be_disabled(timeout=20000)
                page.screenshot(path=str(OUT / ("event-tools-disabled-%d.png" % width)), full_page=True)
                context.request.put("http://localhost:5000/api/settings",
                    headers={"X-Admin-Pin": credentials["Admin PIN"]},
                    data={"volunteer_enabled": "true", "liveboard_enabled": "true"})
            except Exception:
                page.screenshot(path=str(OUT / ("failure-%dx%d.png" % (width, height))), full_page=True)
                print("Failed page:", page.url)
                raise
            context.close()
        browser.close()
    print("PASS: phone-size layout, auth navigation, real student login and account/event tools")
except Exception:
    try:
        page.screenshot(path=str(OUT / "failure.png"), full_page=True)
        print("Failed page:", page.url)
    except Exception:
        pass
    raise
finally:
    for child in reversed(processes):
        child.terminate()
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: child.kill()
    for log in logs: log.close()
