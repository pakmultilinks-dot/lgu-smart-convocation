"""Entry point. Run with:  python run.py   ->  http://localhost:5000"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, seed  # noqa: E402
from web.routes import create_app  # noqa: E402

init_db()
seed()

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
