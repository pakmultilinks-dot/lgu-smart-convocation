"""Run a disposable synthetic Flask backend for CI/mobile API smoke tests.

Never import app/run.py or open the default app/lgu.db.
"""
import os
from pathlib import Path
import sys
import tempfile

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402
import database  # noqa: E402
from web.routes import create_app  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="lgu-api-smoke-") as folder:
        config.DB_PATH = os.path.join(folder, "synthetic.sqlite")
        database.init_db()
        database.seed()
        port = int(os.environ.get("LGU_QA_PORT", "5055"))
        server = make_server("127.0.0.1", port, create_app())
        print("Synthetic API smoke server ready", flush=True)
        server.serve_forever()
