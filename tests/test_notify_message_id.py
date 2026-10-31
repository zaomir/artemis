"""QA prod-smoke 2026-10-31 P10: a successful Telegram send is logged with the message_id only."""
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")


class NotifyLogTest(unittest.TestCase):
    """P10: a successful Telegram send is logged with the message_id only."""

    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        import notify
        self.notify = importlib.reload(notify)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def _send(self, reply: bytes):
        resp = mock.MagicMock()
        resp.read.return_value = reply
        with mock.patch.object(self.notify.urllib.request, "urlopen", return_value=resp), \
                self.assertLogs("artemis.notify", level="INFO") as cm:
            self.notify._send("123:secret-token", "-100", "Имя: Секретная Анна\nКонтакт: anna@example.org")
        return "\n".join(cm.output)

    def test_success_logs_message_id_only(self):
        out = self._send(json.dumps({"ok": True, "result": {"message_id": 4242, "text": "Секретная Анна"}}).encode())
        self.assertIn("message_id=4242", out)
        for secret in ("Секретная", "anna@example.org", "secret-token", "-100", "Имя"):
            self.assertNotIn(secret, out)

    def test_unexpected_reply_logs_no_text(self):
        out = self._send(b'{"ok": false, "description": "Bad Request: Anna"}')
        self.assertIn("unexpected Telegram reply", out)
        self.assertNotIn("Anna", out)


if __name__ == "__main__":
    unittest.main()
