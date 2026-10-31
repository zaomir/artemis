"""Lead notifications: env-only config, DB-only + warning without chat id."""
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

ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        import notify
        self.notify = importlib.reload(notify)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_no_chat_id_logs_warning_and_does_not_send(self):
        os.environ["ARTEMIS_TG_BOT_TOKEN"] = "123:abc"
        with mock.patch.object(self.notify, "_send") as send, \
                self.assertLogs("artemis.notify", level="WARNING") as cm:
            self.assertFalse(self.notify.notify_lead("t", "A", "a@b.c", "ru", "/x/"))
        send.assert_not_called()
        self.assertIn("CHAT_ID", "\n".join(cm.output))
        self.assertNotIn("123:abc", "\n".join(cm.output))

    def test_sends_only_four_fields(self):
        os.environ["ARTEMIS_TG_BOT_TOKEN"] = "123:abc"
        os.environ["ARTEMIS_TG_CHAT_ID"] = "-100123"
        with mock.patch.object(self.notify, "_send") as send:
            self.assertTrue(self.notify.notify_lead("Tenerife waitlist", "Ann", "+34 600", "ru",
                                                    "/tenerife-preview/", background=False))
        token, chat, text = send.call_args[0]
        self.assertEqual(chat, "-100123")
        for s in ("Ann", "+34 600", "ru", "/tenerife-preview/"):
            self.assertIn(s, text)
        self.assertEqual(len(text.splitlines()), 5)


class CreteEnquiryTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_enquiry_stored_and_notified(self):
        with mock.patch.object(self.mod, "notify_lead") as nl:
            r = self.client.post("/api/enquiry", json={
                "name": "Bob", "email": "bob@x.io", "consent": True,
                "enquiry_type": "other", "message": "secret text", "lang": "es", "page": "/es/"})
        self.assertEqual(r.get_json(), {"ok": True})
        nl.assert_called_once_with("Crete enquiry", "Bob", "bob@x.io", "es", "/es/")
        c = sqlite3.connect(self.mod.DB)
        self.assertEqual(c.execute("select name,email from leads").fetchall(), [("Bob", "bob@x.io")])
        c.close()

    def test_enquiry_without_tg_config_still_ok(self):
        r = self.client.post("/api/enquiry", json={"name": "B", "email": "b@x.io", "consent": True})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
