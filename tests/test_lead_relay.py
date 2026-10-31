"""Lead relay (deploy/artemis-lead-relay.py): baseline, e-mail once per new lead, TG backlog once."""
import contextlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import time
import types
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
        self.m.send_email = lambda kind, tbl, d, key="": self.mails.append((tbl, d["id"])) or f"<m{len(self.mails)}@x>"
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
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def queued(self):
        s = sqlite3.connect(os.path.join(self.d, "s.db"))
        done = {r[0] for r in s.execute("SELECT lead_id FROM sent WHERE tbl='tenerife_waitlist' AND channel='email'")}
        c = sqlite3.connect(self.db)
        return [r[0] for r in c.execute("SELECT id FROM tenerife_waitlist") if r[0] not in done]

    def clock(self):
        c = [self.m.utcnow()]
        self.m.utcnow = lambda: c[0]
        return c

    def tick(self, c, minutes=1):
        c[0] += self.m.dt.timedelta(minutes=minutes)

    def test_no_mx_defers_keeps_queue_then_sends_when_mx_appears(self):
        c = self.clock()
        self.m.run()
        self.mx = []                                   # artemisresort.com today: no MX
        self.add("Lead A", "2026-10-31T18:00:00")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for _ in range(5):
                self.m.run()
                self.tick(c)
        self.assertEqual(self.mails, [])               # nothing sent, no bounce
        self.assertEqual(self.queued(), [1])           # still queued for the copy
        self.assertEqual(out.getvalue().count("email deferred: no MX for artemisresort.com"), 1)  # logged once
        self.mx = None                                 # DNS error -> also deferred
        self.tick(c, 60)
        self.m.run()
        self.assertEqual(self.mails, [])
        self.mx = ["mx.artemisresort.com"]             # mail on the domain -> queued copy goes out once
        self.tick(c, 60)
        self.m.run()
        self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1)])
        self.assertEqual(self.queued(), [])

    def test_send_errors_backoff_and_cap_lead_kept(self):
        self.m.run()
        self.add("Lead B", "2026-10-31T18:00:00")
        calls = []

        def boom(kind, tbl, d, key=""):
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
        self.m.send_email = lambda kind, tbl, d, key="": self.mails.append((tbl, d["id"])) or "<ok@x>"
        self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1)])

    def test_mx_check_can_be_disabled(self):
        self.m.REQUIRE_MX = False
        self.m.mx_hosts = lambda d: self.fail("mx lookup must not run")
        self.assertTrue(self.m.mail_route("info@artemisresort.com")[0])


    # --- A-11: MX lookups back off while deferred; parked leads never trigger lookups ---------
    def test_deferred_route_lookup_backs_off(self):
        c = self.clock()
        self.m.run()
        lookups = []
        self.m.mx_hosts = lambda domain: lookups.append(domain) or []
        self.add("Lead C", "2026-10-31T18:00:00")
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(60):                        # one hour of timer runs, 1 min apart
                self.m.run()
                self.tick(c)
        self.assertLessEqual(len(lookups), 7)          # 1,2,4,8,16,32 min … not 60
        self.assertGreaterEqual(len(lookups), 5)
        self.assertEqual(self.mails, [])

    def test_parked_leads_do_not_trigger_mx_lookup(self):
        self.m.run()
        self.add("Lead D", "2026-10-31T18:00:00")
        s = self.m.state_db()
        s.execute("INSERT INTO attempts VALUES('tenerife_waitlist', 1, 'email', ?, '', 'x')", (self.m.MAX_ATTEMPTS,))
        s.commit()
        self.m.mx_hosts = lambda d: self.fail("no MX lookup for parked-only queue")
        self.m.run()
        self.assertEqual(self.mails, [])

    # --- A-11: --requeue per channel ---------------------------------------------------------
    def _attempts(self):
        s = self.m.state_db()
        for ch in ("email", "tg"):
            s.execute("INSERT OR REPLACE INTO attempts VALUES('leads', 1, ?, 8, '', 'x')", (ch,))
        s.commit()
        return s

    def test_requeue_only_given_channel(self):
        s = self._attempts()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.requeue(["--channel", "email"]), 0)
        self.assertEqual([r[0] for r in s.execute("SELECT channel FROM attempts")], ["tg"])
        self._attempts()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.requeue(["--channel=telegram"]), 0)
        self.assertEqual([r[0] for r in s.execute("SELECT channel FROM attempts")], ["email"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.requeue([]), 0)
        self.assertEqual(s.execute("SELECT count(*) FROM attempts").fetchone()[0], 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.m.requeue(["--channel", "fax"]), 2)

    # --- A-11: idempotency marker ------------------------------------------------------------
    def _interrupted_send(self):
        c = self.clock()
        self.m.run()
        self.add("Lead E", "2026-10-31T18:00:00")

        def killed(kind, tbl, d, key=""):
            raise KeyboardInterrupt                    # stands in for SIGKILL mid-send
        self.m.send_email = killed
        with self.assertRaises(KeyboardInterrupt):
            self.m.run()
        s = self.m.state_db()
        self.assertEqual(s.execute("SELECT count(*) FROM sending").fetchone()[0], 1)  # marker survived
        self.m.send_email = lambda kind, tbl, d, key="": self.mails.append((tbl, d["id"], key)) or "<ok@x>"
        return c, s

    def test_interrupted_send_found_in_sent_is_not_resent(self):
        c, s = self._interrupted_send()
        keys = []
        self.m.find_sent_email = lambda key, since: keys.append(key) or "gmail123"
        self.m.run()                                   # inside grace period: nothing happens
        self.assertEqual((self.mails, keys), ([], []))
        self.tick(c, 10)
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.run()
        self.assertEqual(self.mails, [])               # no duplicate
        self.assertEqual(keys, ["tenerife_waitlist:1:2026-10-31T18:00:00"])
        self.assertEqual(self.queued(), [])
        self.assertEqual(s.execute("SELECT count(*) FROM sending").fetchone()[0], 0)

    def test_interrupted_send_not_in_sent_is_sent_once(self):
        c, s = self._interrupted_send()
        self.m.find_sent_email = lambda key, since: ""
        self.tick(c, 10)
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.run()
            self.m.run()
        self.assertEqual(self.mails, [("tenerife_waitlist", 1, "tenerife_waitlist:1:2026-10-31T18:00:00")])
        self.assertEqual(s.execute("SELECT count(*) FROM sending").fetchone()[0], 0)

    def test_send_exception_clears_marker(self):
        self.m.run()
        self.add("Lead F", "2026-10-31T18:00:00")
        self.m.send_email = lambda kind, tbl, d, key="": (_ for _ in ()).throw(RuntimeError("down"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.run()
        self.assertEqual(self.m.state_db().execute("SELECT count(*) FROM sending").fetchone()[0], 0)

    def test_reply_to_only_for_email_contacts(self):
        self.assertEqual(self.m.reply_to({"contact": "a.b@example.com"}), "a.b@example.com")
        self.assertEqual(self.m.reply_to({"contact": "+440000000000"}), "")
        self.assertEqual(self.m.reply_to({"contact": "@telegram_user"}), "")
        self.assertEqual(self.m.reply_to({"contact": "a@b.com, c@d.com"}), "")


class MaxAttemptsEnvTest(unittest.TestCase):
    def _load(self, value):
        os.environ["ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS"] = value
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                m = load({})
            return m, out.getvalue()
        finally:
            del os.environ["ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS"]

    def test_invalid_value_falls_back_with_warning(self):
        for bad in ("abc", "0", "-3", "8.5"):
            m, out = self._load(bad)
            self.assertEqual(m.MAX_ATTEMPTS, 8, bad)
            self.assertIn("warning: ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS", out)

    def test_valid_and_empty(self):
        self.assertEqual(self._load("3")[0].MAX_ATTEMPTS, 3)
        m, out = self._load("")
        self.assertEqual((m.MAX_ATTEMPTS, out), (8, ""))


# --- A-12: the MX check itself (dig fallback and dnspython path) -------------------------------
DIG_HDR = ";; Got answer:\n;; ->>HEADER<<- opcode: QUERY, status: {st}, id: 1\n;; flags: qr rd ra; QUERY: 1\n"


class MxCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load({})

    def dig(self, st, answer="", rc=0):
        return self.m.parse_dig_mx(rc, DIG_HDR.format(st=st) + answer)

    def test_dig_mx_rows(self):
        a = "example.org.\t300\tIN\tMX\t10 mx1.example.org.\nexample.org.\t300\tIN\tMX\t20 mx2.example.org.\n"
        self.assertEqual(self.dig("NOERROR", a), ["mx1.example.org", "mx2.example.org"])

    def test_dig_cname_is_not_mx(self):
        a = "alias.example.org.\t300\tIN\tCNAME\ttarget.example.net.\n"
        self.assertEqual(self.dig("NOERROR", a), [])
        a += "target.example.net.\t300\tIN\tMX\t5 mx.example.net.\n"     # MX of the CNAME target counts
        self.assertEqual(self.dig("NOERROR", a), ["mx.example.net"])

    def test_dig_null_mx_and_nxdomain_and_nodata(self):
        self.assertEqual(self.dig("NOERROR", "example.org.\t300\tIN\tMX\t0 .\n"), [])
        self.assertEqual(self.dig("NXDOMAIN"), [])
        self.assertEqual(self.dig("NOERROR"), [])

    def test_dig_errors_are_unknown_not_no_mx(self):
        self.assertIsNone(self.dig("SERVFAIL"))
        self.assertIsNone(self.dig("REFUSED"))
        self.assertIsNone(self.m.parse_dig_mx(9, ";; connection timed out; no servers could be reached\n"))
        self.assertIsNone(self.m.parse_dig_mx(0, ""))                   # no header at all

    def test_dig_fallback_used_without_dnspython(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout=DIG_HDR.format(st="SERVFAIL"))
        orig = self.m.subprocess.run
        self.m.subprocess.run = fake_run
        saved = {k: sys.modules.get(k) for k in ("dns", "dns.resolver", "dns.exception")}
        try:
            for k in saved:
                sys.modules[k] = None                   # import dns.* -> ImportError
            self.assertIsNone(self.m.mx_hosts("example.org"))
        finally:
            self.m.subprocess.run = orig
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertIn("+comments", calls[0])

    def test_dnspython_path(self):
        exc = types.ModuleType("dns.exception")

        class DNSException(Exception):
            pass
        exc.DNSException = DNSException
        res = types.ModuleType("dns.resolver")
        res.NXDOMAIN = type("NXDOMAIN", (DNSException,), {})
        res.NoAnswer = type("NoAnswer", (DNSException,), {})
        res.Timeout = type("Timeout", (DNSException,), {})
        answers = {}

        def resolve(domain, rtype, lifetime=None):
            a = answers[domain]
            if isinstance(a, type):
                raise a()
            return [types.SimpleNamespace(exchange=h) for h in a]
        res.resolve = resolve
        pkg = types.ModuleType("dns")
        pkg.exception, pkg.resolver = exc, res
        saved = {k: sys.modules.get(k) for k in ("dns", "dns.resolver", "dns.exception")}
        sys.modules.update({"dns": pkg, "dns.resolver": res, "dns.exception": exc})
        try:
            answers.update({"ok.org": ["mx.ok.org."], "null.org": ["."], "nx.org": res.NXDOMAIN,
                            "none.org": res.NoAnswer, "slow.org": res.Timeout})
            self.assertEqual(self.m.mx_hosts("ok.org"), ["mx.ok.org"])
            self.assertEqual(self.m.mx_hosts("null.org"), [])
            self.assertEqual(self.m.mx_hosts("nx.org"), [])
            self.assertEqual(self.m.mx_hosts("none.org"), [])
            self.assertIsNone(self.m.mx_hosts("slow.org"))
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_mail_route_reasons(self):
        m = load({})
        m.REQUIRE_MX = True
        m.mx_hosts = lambda d: None
        self.assertEqual(m.mail_route("info@artemisresort.com"),
                         (False, "MX lookup for artemisresort.com failed (DNS error)"))
        m.mx_hosts = lambda d: []
        self.assertEqual(m.mail_route("info@artemisresort.com"), (False, "no MX for artemisresort.com"))


if __name__ == "__main__":
    sys.exit(unittest.main())
