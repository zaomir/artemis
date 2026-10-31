"""QA prod-smoke 2026-10-31 P09: anti-spam on /api/enquiry (per-client rate limit + honeypot)."""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID", "ARTEMIS_ADMIN_TOKEN", "RATE_LIMIT_SALT")
TEST_SALT = "unit-tests-only-not-a-secret"
LANGS = ("en", "ru", "es", "fr")


class EnquiryBase(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        os.environ["RATE_LIMIT_SALT"] = TEST_SALT  # restored in tearDown
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app
        import ratelimit
        self.rl = importlib.reload(ratelimit)
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        nl = mock.patch.object(self.mod, "notify_lead")
        self.notify = nl.start()
        self.addCleanup(nl.stop)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def post(self, ip="203.0.113.7", headers=None, remote="127.0.0.1", **kw):
        body = {"name": "Bob", "email": "bob@x.io", "consent": True, "enquiry_type": "investor",
                "lang": "en", "page": "/en/"}
        body.update(kw)
        h = {"X-Real-IP": ip} if ip else {}
        h.update(headers or {})
        return self.client.post("/api/enquiry", json=body, headers=h, environ_base={"REMOTE_ADDR": remote})

    def leads(self):
        if not os.path.exists(self.mod.DB):
            return 0
        conn = sqlite3.connect(self.mod.DB)
        try:
            return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        finally:
            conn.close()


class RateLimitTest(EnquiryBase):
    def test_valid_lead_is_stored_and_notified(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual(self.leads(), 1)
        self.notify.assert_called_once()

    def test_429_after_three_in_ten_minutes(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 200)
        r = self.post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json(), {"ok": False, "code": "rate_limited", "error": "rate_limited"})
        retry = int(r.headers["Retry-After"])
        self.assertTrue(1 <= retry <= 600, retry)
        self.assertEqual(self.leads(), 3)
        self.assertEqual(self.notify.call_count, 3)
        # another client is not affected
        self.assertEqual(self.post(ip="198.51.100.9").status_code, 200)

    def test_day_limit_ten(self):
        client = "c" * 32
        t0 = 1_800_000_000 - 1_800_000_000 % 86400 + 60  # one minute into a UTC day
        allowed = 0
        for i in range(12):
            if self.rl.hit(self.mod.DB, "crete_enquiry", client, now=t0 + i * 601) == 0:
                allowed += 1
        self.assertEqual(allowed, 10)
        retry = self.rl.hit(self.mod.DB, "crete_enquiry", client, now=t0 + 12 * 601)
        self.assertEqual(retry, 86400 - (60 + 12 * 601) + 1)

    def test_window_reopens(self):
        client = "d" * 32
        t0 = 1_800_000_000 - 1_800_000_000 % 600
        for _ in range(3):
            self.assertEqual(self.rl.hit(self.mod.DB, "s", client, now=t0 + 5), 0)
        self.assertEqual(self.rl.hit(self.mod.DB, "s", client, now=t0 + 5), 596)
        self.assertEqual(self.rl.hit(self.mod.DB, "s", client, now=t0 + 600), 0)

    def test_spoofed_cf_and_xff_do_not_change_the_key(self):
        for i in range(3):
            spoof = {"CF-Connecting-IP": f"192.0.2.{i}", "X-Forwarded-For": f"192.0.2.{100 + i}"}
            self.assertEqual(self.post(headers=spoof).status_code, 200)
        r = self.post(headers={"CF-Connecting-IP": "192.0.2.250", "X-Forwarded-For": "192.0.2.251"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.leads(), 3)

    def test_without_x_real_ip_uses_remote_addr(self):
        for _ in range(3):
            self.assertEqual(self.post(ip=None, remote="10.0.0.5",
                                       headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 200)
        self.assertEqual(self.post(ip=None, remote="10.0.0.5").status_code, 429)
        self.assertEqual(self.post(ip=None, remote="10.0.0.6").status_code, 200)

    def test_only_the_hash_is_stored(self):
        self.post(ip="203.0.113.77")
        conn = sqlite3.connect(self.mod.DB)
        dump = "\n".join(conn.iterdump())
        conn.close()
        self.assertNotIn("203.0.113.77", dump)
        self.assertIn("rate_limit", dump)

    def test_invalid_submissions_do_not_use_the_quota(self):
        for _ in range(5):
            self.assertEqual(self.post(email="nope").status_code, 400)
        self.assertEqual(self.post().status_code, 200)


class HoneypotTest(EnquiryBase):
    def test_filled_honeypot_is_dropped_silently(self):
        r = self.post(website="http://spam.example")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual(self.leads(), 0)
        self.notify.assert_not_called()

    def test_honeypot_does_not_use_the_quota(self):
        for _ in range(5):
            self.post(website="x")
        self.assertEqual(self.post(website="").status_code, 200)
        self.assertEqual(self.leads(), 1)

    def test_honeypot_markup_all_languages(self):
        for lang in LANGS:
            html = self.client.get(f"/{lang}/").get_data(as_text=True)
            self.assertRegex(html, r'<div class="hp" aria-hidden="true"><input type="text" id="f-website" '
                                   r'name="website" tabindex="-1" autocomplete="off"></div>', lang)
            self.assertIn("website: document.getElementById('f-website').value", html, lang)
            self.assertIn(".hp{position:absolute!important;left:-10000px!important", html, lang)


if __name__ == "__main__":
    unittest.main()
