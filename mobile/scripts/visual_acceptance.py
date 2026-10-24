"""Visual acceptance of the real Expo web app; synthetic local accounts only."""
import json
import os
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
    launch([sys.executable, str(ROOT / "app/scripts/run_local_mobile.py")], ROOT, "backend.log")
    wait_url("http://localhost:5000/api/health")
    launch([shutil.which("node"), "node_modules/expo/bin/cli", "start", "--web", "--port", "8081"], ROOT / "mobile", "metro.log")
    wait_url("http://localhost:8081/status")
    credentials = {}
    for line in (Path.home() / "LGU-Local-Mobile/TEST-LOGIN-DETAILS.txt").read_text().splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            credentials[key] = value
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in [(360, 800), (390, 844)]:
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            page = context.new_page()
            page.goto("http://localhost:8081/mode-picker", wait_until="domcontentloaded", timeout=240000)
            signin = page.get_by_role("button", name="Sign in", exact=True)
            expect(signin).to_be_visible(timeout=120000)
            create = page.get_by_role("button", name="Create student account", exact=True)
            expect(create).to_be_visible(timeout=30000)
            expect(page.get_by_role("button", name="Home", exact=True)).to_have_count(0)
            page.screenshot(path=str(OUT / ("welcome-%d.png" % width)), full_page=True)
            assert create.bounding_box()["y"] < height - 48
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
            response = context.request.put("http://localhost:5000/api/settings",
                headers={"X-Admin-Pin": credentials["Admin PIN"]},
                data={"volunteer_enabled": "false", "liveboard_enabled": "false"})
            assert response.ok
            expect(page.get_by_role("button", name="Volunteer Operations", exact=True)).to_be_disabled(timeout=20000)
            page.screenshot(path=str(OUT / ("event-tools-disabled-%d.png" % width)), full_page=True)
            context.request.put("http://localhost:5000/api/settings",
                headers={"X-Admin-Pin": credentials["Admin PIN"]},
                data={"volunteer_enabled": "true", "liveboard_enabled": "true"})
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
