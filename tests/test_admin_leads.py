"""Admin /admin/leads must be fail-closed (no env token -> 403) and escape HTML."""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def load_app():
    import app as artemis_app  # noqa: E402
    return importlib.reload(artemis_app)


class AdminLeadsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mod = load_app()
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        self._old = os.environ.pop("ARTEMIS_ADMIN_TOKEN", None)

    def tearDown(self):
        os.environ.pop("ARTEMIS_ADMIN_TOKEN", None)
        if self._old is not None:
            os.environ["ARTEMIS_ADMIN_TOKEN"] = self._old
        self.tmp.cleanup()

    def test_no_env_token_is_forbidden(self):
        self.assertEqual(self.client.get("/admin/leads").status_code, 403)
        self.assertEqual(self.client.get("/admin/leads?t=").status_code, 403)
        self.assertEqual(self.client.get("/admin/leads?t=rovlex2025").status_code, 403)

    def test_short_env_token_is_forbidden(self):
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "short"
        self.assertEqual(self.client.get("/admin/leads?t=short").status_code, 403)

    def test_wrong_and_correct_token(self):
        tok = "x" * 40
        os.environ["ARTEMIS_ADMIN_TOKEN"] = tok
        self.assertEqual(self.client.get("/admin/leads?t=rovlex2025").status_code, 403)
        r = self.client.get(f"/admin/leads?t={tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""))

    def test_rows_are_escaped(self):
        tok = "y" * 40
        os.environ["ARTEMIS_ADMIN_TOKEN"] = tok
        self.mod.init_db()
        c = sqlite3.connect(self.mod.DB)
        c.execute("INSERT INTO leads(name,email,created_at) VALUES(?,?,?)",
                  ("<script>alert(1)</script>", "a@b.c", "2026-10-31"))
        c.commit(); c.close()
        body = self.client.get(f"/admin/leads?t={tok}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()
