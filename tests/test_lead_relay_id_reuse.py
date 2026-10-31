"""Lead relay: a lead that reuses a deleted lead's id is still relayed; already-sent leads are not resent
after the upgrade (legacy state rows without lead_key); new lead tables use AUTOINCREMENT."""
import contextlib
import importlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from test_lead_relay import ROOT, load

sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt

# the state schema of the relay before the id-reuse fix (what prod state.db looks like at upgrade time)
OLD_STATE = (
    "CREATE TABLE sent(tbl TEXT, lead_id INTEGER, channel TEXT, ref TEXT, at TEXT, PRIMARY KEY(tbl, lead_id, channel))",
    "CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT)",
    "CREATE TABLE attempts(tbl TEXT, lead_id INTEGER, channel TEXT, n INTEGER, next_at TEXT, last_error TEXT,"
    " PRIMARY KEY(tbl, lead_id, channel))",
    "CREATE TABLE sending(tbl TEXT, lead_id INTEGER, channel TEXT, lead_key TEXT, started_at TEXT,"
    " PRIMARY KEY(tbl, lead_id, channel))",
)


class LeadIdReuseTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "leads.db")
        self.state = os.path.join(self.d, "s.db")
        c = sqlite3.connect(self.db)
        # prod schema of the existing tables: INTEGER PRIMARY KEY without AUTOINCREMENT -> ids get reused
        c.execute("CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY, name, contact, language, page, consent,"
                  " client_hash, created_at)")
        c.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, name, email, amount, created_at)")
        c.commit()
        c.close()
        env_file = os.path.join(self.d, "artemis.env")
        Path(env_file).write_text("ARTEMIS_TG_BOT_TOKEN=x\n")
        self.m = load({"ARTEMIS_DB": self.db, "ARTEMIS_RELAY_STATE": self.state, "ARTEMIS_ENV_FILE": env_file,
                       "ARTEMIS_LEAD_EMAIL_TO": "info@artemisresort.com",
                       "ARTEMIS_LEAD_EMAIL_FROM": "info@oxfordframe.com"})
        self.mails = []
        self.m.send_email = lambda kind, tbl, d, key="": self.mails.append((tbl, d["id"], d["name"])) or "<ok@x>"
        self.m.mx_hosts = lambda domain: ["smtp.google.com"]

    def sql(self, q, args=()):
        c = sqlite3.connect(self.db)
        cur = c.execute(q, args)
        c.commit()
        rid = cur.lastrowid
        c.close()
        return rid

    def add_tf(self, name, created):
        return self.sql("INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)"
                        " VALUES(?,?,?,?,?,?,?)", (name, "t@example.com", "ru", "/tenerife/", 1, "h", created))

    def add_crete(self, name, created):
        return self.sql("INSERT INTO leads(name,email,created_at) VALUES(?,?,?)", (name, "c@example.com", created))

    def run_quiet(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.m.run()

    # --- the bug: delete a lead, the next lead gets the same id ---------------------------------
    def test_reused_id_tenerife_is_relayed(self):
        self.run_quiet()                                           # baseline (empty)
        self.assertEqual(self.add_tf("Lead A", "2026-10-31T17:00:00+00:00"), 1)
        self.run_quiet()
        self.sql("DELETE FROM tenerife_waitlist WHERE id=1")
        self.assertEqual(self.add_tf("Lead B", "2026-10-31T18:00:00+00:00"), 1)   # SQLite reuses id 1
        self.run_quiet()
        self.run_quiet()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1, "Lead A"), ("tenerife_waitlist", 1, "Lead B")])

    def test_reused_id_crete_is_relayed(self):
        self.assertEqual(self.add_crete("Old", "2026-10-01T10:00:00"), 1)
        self.run_quiet()                                           # baseline: "Old" is never e-mailed
        self.sql("DELETE FROM leads WHERE id=1")
        self.assertEqual(self.add_crete("New", "2026-10-31T18:00:00"), 1)
        self.run_quiet()
        self.run_quiet()
        self.assertEqual(self.mails, [("leads", 1, "New")])

    def test_parked_counter_of_deleted_lead_does_not_block_new_lead(self):
        self.run_quiet()
        self.add_tf("Bad", "2026-10-31T17:00:00+00:00")
        self.m.send_email = lambda kind, tbl, d, key="": (_ for _ in ()).throw(RuntimeError("down"))
        clock = [self.m.utcnow()]
        self.m.utcnow = lambda: clock[0]
        for _ in range(400):
            self.run_quiet()
            clock[0] += self.m.dt.timedelta(minutes=5)
        self.assertEqual(self.m.attempt_state(self.m.state_db(), "tenerife_waitlist",
                                              {"id": 1, "created_at": "2026-10-31T17:00:00+00:00"}, "email")[0],
                         self.m.MAX_ATTEMPTS)                      # parked
        self.sql("DELETE FROM tenerife_waitlist WHERE id=1")
        self.add_tf("Good", "2026-11-05T09:00:00+00:00")
        self.m.send_email = lambda kind, tbl, d, key="": self.mails.append((tbl, d["id"], d["name"])) or "<ok@x>"
        self.run_quiet()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1, "Good")])

    # --- upgrade from the old state format ----------------------------------------------------
    def old_state(self, sent=(), attempts=(), kv=(("email_baseline_at", "2026-10-30T12:00:00Z"),)):
        s = sqlite3.connect(self.state)
        for q in OLD_STATE:
            s.execute(q)
        s.executemany("INSERT INTO sent VALUES(?,?,?,?,?)", sent)
        s.executemany("INSERT INTO attempts VALUES(?,?,?,?,?,?)", attempts)
        s.executemany("INSERT INTO kv VALUES(?,?)", kv)
        s.commit()
        s.close()

    def test_upgrade_does_not_resend_already_sent_or_baselined_leads(self):
        self.add_crete("Baselined", "2026-10-01T10:00:00")             # crete id 1
        self.add_tf("Baselined TF", "2026-10-02T10:00:00+00:00")       # tenerife id 1
        self.add_tf("Sent TF", "2026-10-31T17:00:00+00:00")            # tenerife id 2
        self.add_crete("Sent Crete", "2026-10-31T17:30:00")            # crete id 2
        self.add_tf("Sent TG", "2026-10-29T08:00:00+00:00")            # tenerife id 3
        self.old_state(sent=[
            ("leads", 1, "email", "baseline-not-emailed", "2026-10-30T12:00:00Z"),
            ("tenerife_waitlist", 1, "email", "baseline-not-emailed", "2026-10-30T12:00:00Z"),
            ("tenerife_waitlist", 2, "email", "<a@x> gmail:1", "2026-11-01T17:01:00Z"),
            ("leads", 2, "email", "<b@x> gmail:2", "2026-11-01T17:31:00Z"),
            ("tenerife_waitlist", 3, "email", "baseline-not-emailed", "2026-10-30T12:00:00Z"),
        ])
        for _ in range(3):
            self.assertEqual(self.run_quiet(), 0)
        self.assertEqual(self.mails, [])                                # no resend storm
        st = self.m.status()
        self.assertEqual(st["email_queued"], 0)
        # old rows are kept as they were (no rewrite of the old tables)
        s = sqlite3.connect(self.state)
        self.assertEqual(s.execute("SELECT count(*) FROM sent").fetchone()[0], 5)
        self.assertEqual(s.execute("SELECT count(*) FROM sent_key").fetchone()[0], 0)
        # ... and after the upgrade a reused id is relayed once, then not again
        self.sql("DELETE FROM tenerife_waitlist WHERE id=3")
        self.assertEqual(self.add_tf("Reuser", "2026-11-03T09:00:00+00:00"), 3)
        self.run_quiet()
        self.run_quiet()
        self.assertEqual(self.mails, [("tenerife_waitlist", 3, "Reuser")])

    def test_legacy_row_does_not_block_lead_that_reused_the_id_before_the_upgrade(self):
        # id 1 was sent on 30.10, deleted, and a new lead got id 1 on 31.10 -> it was silently skipped
        self.add_crete("Skipped by the old relay", "2026-11-02T09:00:00")
        self.old_state(sent=[("leads", 1, "email", "<old@x> gmail:9", "2026-10-30T09:00:00Z")])
        self.run_quiet()
        self.run_quiet()
        self.assertEqual(self.mails, [("leads", 1, "Skipped by the old relay")])

    def test_legacy_parked_attempts_still_apply_to_the_same_lead_but_not_to_a_newer_one(self):
        self.add_tf("Parked", "2026-10-30T09:00:00+00:00")
        n = self.m.MAX_ATTEMPTS
        self.old_state(attempts=[("tenerife_waitlist", 1, "email", n, "2026-10-31T10:00:00Z", "RuntimeError")])
        self.run_quiet()
        self.assertEqual(self.mails, [])                                # same lead: stays parked
        self.sql("DELETE FROM tenerife_waitlist WHERE id=1")
        self.add_tf("Newer", "2026-11-02T09:00:00+00:00")              # created after the last attempt
        self.run_quiet()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1, "Newer")])

    def test_old_tables_keep_their_columns_for_rollback(self):
        self.old_state()
        self.run_quiet()
        s = sqlite3.connect(self.state)
        cols = {t: [r[1] for r in s.execute(f"PRAGMA table_info({t})")] for t in ("sent", "attempts")}
        self.assertEqual(cols["sent"], ["tbl", "lead_id", "channel", "ref", "at"])
        self.assertEqual(cols["attempts"], ["tbl", "lead_id", "channel", "n", "next_at", "last_error"])
        s.execute("INSERT INTO sent VALUES('leads', 99, 'email', 'old-code', '2026-11-01T00:00:00Z')")  # old writer

    def test_created_utc(self):
        u = self.m.created_utc
        self.assertEqual(u("2026-10-31T18:00:00.123456+00:00"), self.m.dt.datetime(2026, 10, 31, 18, 0, 0,
                                                                                  tzinfo=self.m.dt.timezone.utc))
        self.assertIsNone(u(None))
        self.assertIsNone(u("not a date"))


class AutoincrementSchemaTest(unittest.TestCase):
    """New databases: ids of deleted leads are not handed out again."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app  # noqa: E402
        self.app = importlib.reload(artemis_app)
        self.app.DB = os.path.join(self.tmp.name, "leads.db")

    def tearDown(self):
        self.tmp.cleanup()

    def reused(self, table, insert):
        c = sqlite3.connect(self.app.DB)
        first = c.execute(insert).lastrowid
        c.execute(f"DELETE FROM {table} WHERE id=?", (first,))
        second = c.execute(insert).lastrowid
        c.commit()
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        c.close()
        self.assertIn("AUTOINCREMENT", sql)
        return first, second

    def test_crete_leads_autoincrement(self):
        self.app.init_db()
        first, second = self.reused("leads", "INSERT INTO leads(name,email,created_at) VALUES('a','a@b.c','x')")
        self.assertGreater(second, first)

    def test_tenerife_waitlist_autoincrement(self):
        import tenerife  # noqa: E402
        c = sqlite3.connect(self.app.DB)
        tenerife.init_waitlist_db(c)
        c.commit()
        c.close()
        first, second = self.reused("tenerife_waitlist", "INSERT INTO tenerife_waitlist(name,contact,language,"
                                    "consent,created_at) VALUES('a','b','ru',1,'x')")
        self.assertGreater(second, first)

    def test_existing_table_is_left_alone(self):
        c = sqlite3.connect(self.app.DB)
        c.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT)")
        c.execute("INSERT INTO leads(name,email,created_at) VALUES('kept','k@b.c','2026-10-01')")
        c.commit()
        c.close()
        self.app.init_db()
        c = sqlite3.connect(self.app.DB)
        self.assertEqual(c.execute("SELECT name FROM leads").fetchall(), [("kept",)])
        self.assertNotIn("AUTOINCREMENT", c.execute("SELECT sql FROM sqlite_master WHERE name='leads'").fetchone()[0])
        c.close()


if __name__ == "__main__":
    sys.exit(unittest.main())
