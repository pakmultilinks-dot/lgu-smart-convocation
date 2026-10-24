"""Start the persistent local backend used by Expo Go on the same Wi-Fi."""
import os
from pathlib import Path
import runpy
import subprocess
import sys

root = Path.home() / "LGU-Local-Mobile"
if not root.exists():
    subprocess.run([
        sys.executable, str(Path(__file__).with_name("create_preview_demo.py")),
        "--output-dir", str(root),
    ], check=True)
runtime = root / "PRIVATE-BACKEND-ENV.txt"
if not runtime.is_file():
    raise SystemExit(f"Missing local configuration: {runtime}")
for line in runtime.read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key] = value
os.environ.update({
    "LGU_APP_ENV": "development",
    "LGU_COOKIE_SECURE": "0",
    "LGU_STUDENT_PHOTO_DIR": str(root / "photos"),
    "LGU_MEDALIST_PHOTO_DIR": str(root / "medalist-photos"),
})
print(f"Local test accounts: {root / 'TEST-LOGIN-DETAILS.txt'}", flush=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_path(str(Path(__file__).resolve().parents[1] / "run.py"), run_name="__main__")
