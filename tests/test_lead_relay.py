"""Lead relay (deploy/artemis-lead-relay.py): baseline, e-mail once per new lead, TG backlog once."""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location("relay", ROOT / "deploy" / "artemis-lead-relay.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class LeadRelayTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "leads.db")
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY, name, contact, language, page, consent,"
                  " client_hash, created_at)")
        c.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, name, email, phone, amount, created_at)")
        c.execute("INSERT INTO leads(name,email,created_at) VALUES('Old','old@example.com','2026-10-01T10:00:00')")
        c.commit()
        c.close()
        self.env_file = os.path.join(self.d, "artemis.env")
        Path(self.env_file).write_text("ARTEMIS_TG_BOT_TOKEN=x\n#ARTEMIS_TG_CHAT_ID=\n")
        self.m = load({"ARTEMIS_DB": self.db, "ARTEMIS_RELAY_STATE": os.path.join(self.d, "s.db"),
                       "ARTEMIS_ENV_FILE": self.env_file, "ARTEMIS_LEAD_EMAIL_TO": "info@artemisresort.com",
                       "ARTEMIS_LEAD_EMAIL_FROM": "info@oxfordframe.com"})
        self.mails, self.tgs = [], []
        self.m.send_email = lambda kind, tbl, d: self.mails.append((tbl, d["id"])) or f"<m{len(self.mails)}@x>"
        self.m.tg_send = lambda text: self.tgs.append(text) or f"tg:{len(self.tgs)}"

    def add(self, name, created):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)"
                  " VALUES(?,?,?,?,?,?,?)", (name, "t@example.com", "ru", "/tenerife/", 1, "h", created))
        c.commit()
        c.close()

    def test_baseline_then_new_leads_emailed_once(self):
        self.m.run()                       # baseline: old lead never e-mailed
        self.assertEqual(self.mails, [])
        self.add("TEST lead", "2026-10-31T17:00:00+00:00")
        self.m.run()
        self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1)])
        self.assertEqual(self.tgs, [])     # no chat id → nothing to Telegram

    def test_tg_backlog_once_only_for_old_leads(self):
        self.m.run()
        Path(self.env_file).write_text("ARTEMIS_TG_BOT_TOKEN=x\nARTEMIS_TG_CHAT_ID=-100\n")
        os.utime(self.env_file, (time.time(), time.time()))
        self.add("New after chat", "2999-01-01T00:00:00")
        self.m.run()
        self.m.run()
        self.assertEqual(len(self.tgs), 1)
        self.assertIn("переслано из базы", self.tgs[0])
        self.assertIn("Crete enquiry", self.tgs[0])

    def test_text_has_no_message_body(self):
        t = self.m.lead_text("Tenerife waitlist", {"id": 1, "name": "A", "contact": "B", "language": "ru",
                                                   "page": "/tenerife/", "created_at": "x", "message": "secret"})
        self.assertNotIn("secret", t)


if __name__ == "__main__":
    sys.exit(unittest.main())
