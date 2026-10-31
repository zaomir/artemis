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
        self.mx = ["aspmx.l.google.com"]
        self.m.mx_hosts = lambda domain: self.mx

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

    def _out(self, fn):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def queued(self):
        s = sqlite3.connect(os.path.join(self.d, "s.db"))
        done = {r[0] for r in s.execute("SELECT lead_id FROM sent WHERE tbl='tenerife_waitlist' AND channel='email'")}
        c = sqlite3.connect(self.db)
        return [r[0] for r in c.execute("SELECT id FROM tenerife_waitlist") if r[0] not in done]

    def test_no_mx_defers_keeps_queue_then_sends_when_mx_appears(self):
        self.m.run()
        self.mx = []                                   # artemisresort.com today: no MX
        self.add("Lead A", "2026-10-31T18:00:00")
        out = self._out(lambda: [self.m.run() for _ in range(5)])
        self.assertEqual(self.mails, [])               # nothing sent, no bounce
        self.assertEqual(self.queued(), [1])           # still queued for the copy
        self.assertEqual(out.count("email deferred: no MX for artemisresort.com"), 1)  # logged once, not every minute
        self.mx = None                                 # DNS error -> also deferred
        self.m.run()
        self.assertEqual(self.mails, [])
        self.mx = ["mx.artemisresort.com"]             # mail on the domain -> queued copy goes out once
        self.m.run()
        self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1)])
        self.assertEqual(self.queued(), [])

    def test_send_errors_backoff_and_cap_lead_kept(self):
        self.m.run()
        self.add("Lead B", "2026-10-31T18:00:00")
        calls = []

        def boom(kind, tbl, d):
            calls.append(d["id"])
            raise RuntimeError("smtp down")
        self.m.send_email = boom
        clock = [self.m.utcnow()]
        self.m.utcnow = lambda: clock[0]
        for _ in range(200):                           # 200 timer runs, 1 min apart
            self.m.run()
            clock[0] += self.m.dt.timedelta(minutes=1)
        self.assertEqual(len(calls), self.m.MAX_ATTEMPTS)  # capped, not 200
        clock[0] += self.m.dt.timedelta(days=7)
        self.m.run()
        self.assertEqual(len(calls), self.m.MAX_ATTEMPTS)  # parked stays parked
        c = sqlite3.connect(self.db)                   # lead itself never touched
        self.assertEqual(c.execute("SELECT count(*) FROM tenerife_waitlist").fetchone()[0], 1)
        self.assertEqual(self.queued(), [1])
        s = self.m.state_db()                          # --requeue path: counters cleared -> retried
        s.execute("DELETE FROM attempts")
        s.commit()
        self.m.send_email = lambda kind, tbl, d: self.mails.append((tbl, d["id"])) or "<ok@x>"
        self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1)])

    def test_mx_check_can_be_disabled(self):
        self.m.REQUIRE_MX = False
        self.m.mx_hosts = lambda d: self.fail("mx lookup must not run")
        self.assertTrue(self.m.mail_route("info@artemisresort.com")[0])


if __name__ == "__main__":
    sys.exit(unittest.main())
