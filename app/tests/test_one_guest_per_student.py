"""One-guest-per-student checks using only temporary SQLite data."""
import sys
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database
import models
import ids
from web.routes import create_app


class GuestLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = config.DB_PATH
        config.DB_PATH = str(Path(self.temp.name) / "qa.sqlite")
        database.init_db()
        database.seed()
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        config.DB_PATH = self.original_path
        self.temp.cleanup()

    def test_duplicate_guest_is_rejected(self):
        gid, error = models.register_guest(
            "QA", "000", "LGU-2024-101", ids.generate_id
        )
        self.assertIsNone(gid)
        self.assertIn("already", error.lower())

    def test_api_refuses_second_guest(self):
        response = self.client.post("/api/guests", json={
            "name": "QA", "phone": "000", "host_roll_no": "LGU-2024-101"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.get_json()["error"].lower())

    def test_simultaneous_requests_create_one_guest(self):
        def register(_):
            return models.register_guest(
                "QA", "000", "LGU-2024-102", ids.generate_id
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, range(2)))
        self.assertEqual(sum(gid is not None for gid, _ in results), 1)


if __name__ == "__main__":
    unittest.main()
