"""Calculator fields of a Tenerife waitlist lead (designer r2 item 7 + design v2 C13, 31.10.2026).
The /tenerife/calculadora/ form sends exactly page, calc_m2, calc_step, calc_pay. The server recomputes the
calculation with the CURRENT model.json, records its version, and stores/sends status ok, mismatch
(«расчёт не совпадает», submitted + recomputed values) or invalid — the lead is never rejected for it.
Covered: validation (types, ranges, tolerance), storage (idempotent migration), Telegram text from the app
(app/notify.py) and from the lead relay (deploy/artemis-lead-relay.py). Telegram is always mocked."""
import importlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
MODEL = ROOT / "app" / "tenerife_site" / "data" / "model.json"
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")

import tenerife_calc  # noqa: E402
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt


def model():
    return json.loads(MODEL.read_text(encoding="utf-8"))


def good(**kw):
    d = {"calc_m2": "72", "calc_step": "queue", "calc_pay": "m12"}
    d.update(kw)
    return d


STALE = {"calc_m2": "120", "calc_step": "handover", "calc_pay": "m24"}   # a page built from another model


class CheckCalcTest(unittest.TestCase):
    def setUp(self):
        self.m = model()

    def check(self, data):
        return tenerife_calc.check_calc(data, self.m)

    def test_no_calc_fields_is_a_plain_lead(self):
        self.assertEqual(self.check({"name": "A", "contact": "a@b.cd"}), (None, []))
        self.assertEqual(self.check({"calc_m2": "", "calc_step": None}), (None, []))

    def test_matching_lead(self):
        for d in (good(), good(calc_m2=72), good(calc_m2="72.0"), good(calc_m2="72,00"), good(calc_m2="72.004")):
            calc, problems = self.check(d)
            self.assertEqual(problems, [], d)
            self.assertEqual(calc, {
                "calc_status": "ok", "calc_note": None, "calc_m2": 72, "calc_step": "queue", "calc_pay": "m12",
                "calc_m2_server": 72, "calc_step_server": "queue", "calc_pay_server": "m12",
                "calc_type": "two_bed", "calc_shares": 72, "calc_price_eur_m2": 2950, "calc_amount": 212400,
                "calc_month_eur": 17700, "calc_model_version": self.m["version"]})

    def test_recomputed_from_model_half_up(self):
        # copy_v3 rounding example: 57 m² × 2 950 ÷ 12 = 14 012,5 -> 14 013 €
        calc, _ = self.check(good(calc_m2="57"))
        self.assertEqual((calc["calc_amount"], calc["calc_month_eur"], calc["calc_type"]), (168150, 14013, None))
        calc, _ = self.check(good(calc_m2="52", calc_step="permit", calc_pay="now"))
        self.assertEqual((calc["calc_type"], calc["calc_price_eur_m2"], calc["calc_amount"], calc["calc_month_eur"]),
                         ("one_bed", 3100, 161200, None))
        lo, hi = self.m["area_m2"]["min"], self.m["area_m2"]["max"]
        for m2 in (lo, hi):
            self.assertEqual(self.check(good(calc_m2=str(m2)))[0]["calc_status"], "ok")

    def test_stale_page_mismatch_keeps_both_values(self):
        calc, problems = self.check(STALE)
        self.assertEqual(calc["calc_status"], "mismatch")
        self.assertEqual((calc["calc_m2"], calc["calc_step"], calc["calc_pay"]), (120, "handover", "m24"))
        self.assertEqual((calc["calc_m2_server"], calc["calc_step_server"], calc["calc_pay_server"]),
                         (100, "queue", "now"))
        self.assertEqual(calc["calc_note"], "calc_m2: 120 → 100; calc_step: handover → queue; calc_pay: m24 → now")
        self.assertEqual((calc["calc_amount"], calc["calc_month_eur"]), (295000, None))
        self.assertEqual(problems, ["расчёт не совпадает: " + calc["calc_note"]])
        calc, _ = self.check(good(calc_m2="47"))
        self.assertEqual((calc["calc_status"], calc["calc_m2_server"]), ("mismatch", 48))

    def test_model_change_is_a_mismatch(self):
        m = model()
        m["area_m2"]["max"] = 70
        m["installments"] = {"months": 0}
        calc, _ = tenerife_calc.check_calc(good(), m)
        self.assertEqual((calc["calc_status"], calc["calc_m2_server"], calc["calc_pay_server"]),
                         ("mismatch", 70, "now"))

    def test_invalid_types_and_bounds(self):
        cases = {
            "calc_m2": ["72.5", "72.02", "abc", "-72", True, 72.5, "0", "10001", "7" * 12, "1e2", [72]],
            "calc_step": ["QUEUE", "<b>x</b>", "queue\nX", "x" * 40, 5, ["queue"]],
            "calc_pay": ["M12", "m 12", "now;", {"a": 1}],
        }
        for field, values in cases.items():
            for v in values:
                calc, problems = self.check(good(**{field: v}))
                self.assertEqual(calc["calc_status"], "invalid", f"{field}={v!r}")
                self.assertEqual(calc["calc_note"], f"{field}: неверный формат")
                self.assertEqual(set(calc), {"calc_status", "calc_note", "calc_model_version"})  # no garbage kept
                for p in problems:
                    self.assertNotIn("\n", p)
        self.assertEqual(self.check(good(calc_m2=" 72 "))[0]["calc_status"], "ok")   # whitespace stripped

    def test_missing_fields_invalid(self):
        for field in tenerife_calc.FIELDS:
            d = good()
            del d[field]
            calc, problems = self.check(d)
            self.assertEqual((calc["calc_status"], calc["calc_note"]), ("invalid", f"{field}: нет"))
            self.assertIn(f"{field}: нет", problems)
        calc, _ = self.check({"calc_pay": "m12"})
        self.assertEqual(calc["calc_note"], "calc_m2: нет; calc_step: нет")


class WaitlistCalcApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        self.tenerife = sys.modules["tenerife"]

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def post(self, extra, json_body=True, n=0):
        d = {"name": "Анна", "contact": "anna@example.de", "language": "ru", "consent": True,
             "page": "/tenerife/calculadora/", **extra}
        env = {"REMOTE_ADDR": f"10.0.0.{n + 1}"}
        with mock.patch.object(self.tenerife, "notify_lead") as nl:
            if json_body:
                r = self.client.post("/api/tenerife/waitlist", json=d, environ_base=env)
            else:
                r = self.client.post("/api/tenerife/waitlist", data={**d, "consent": "1"}, environ_base=env)
        return r, nl

    def rows(self):
        c = sqlite3.connect(self.mod.DB)
        c.row_factory = sqlite3.Row
        out = [dict(r) for r in c.execute("SELECT * FROM tenerife_waitlist ORDER BY id")]
        c.close()
        return out

    def test_matching_lead_stored_and_notified(self):
        r, nl = self.post(good())
        self.assertEqual(r.get_json(), {"ok": True})
        row = self.rows()[0]
        self.assertEqual((row["calc_status"], row["calc_m2"], row["calc_step"], row["calc_pay"], row["calc_type"],
                          row["calc_shares"], row["calc_amount"], row["calc_month_eur"], row["calc_model_version"]),
                         ("ok", 72, "queue", "m12", "two_bed", 72, 212400, 17700, model()["version"]))
        kw = nl.call_args.kwargs
        self.assertEqual((kw["calc"]["calc_status"], kw["calc"]["calc_amount"]), ("ok", 212400))
        self.assertEqual(kw["model"]["version"], model()["version"])

    def test_no_js_form_post_with_calc(self):
        r, nl = self.post(good(), json_body=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.rows()[0]["calc_status"], "ok")

    def test_stale_page_lead_accepted_flagged_logged(self):
        with self.assertLogs(self.mod.app.logger, level="WARNING") as cm:
            r, nl = self.post(dict(STALE))
        self.assertEqual(r.get_json(), {"ok": True})
        row = self.rows()[0]
        self.assertEqual((row["calc_status"], row["calc_m2"], row["calc_m2_server"], row["calc_step"],
                          row["calc_step_server"], row["calc_pay"], row["calc_pay_server"], row["calc_amount"]),
                         ("mismatch", 120, 100, "handover", "queue", "m24", "now", 295000))
        self.assertIn("calc mismatch: расчёт не совпадает: calc_m2: 120 → 100", "\n".join(cm.output))
        self.assertEqual(nl.call_args.kwargs["calc"]["calc_status"], "mismatch")

    def test_invalid_calc_lead_kept_block_marked_invalid(self):
        with self.assertLogs(self.mod.app.logger, level="WARNING") as cm:
            r, nl = self.post(good(calc_m2="<b>72</b>", calc_step="queue\nТелефон: fake"))
        self.assertEqual(r.get_json(), {"ok": True})
        row = self.rows()[0]
        self.assertEqual(row["name"], "Анна")
        self.assertEqual((row["calc_status"], row["calc_note"]),
                         ("invalid", "calc_m2: неверный формат; calc_step: неверный формат"))
        for col, _t in tenerife_calc.COLUMNS:
            if col not in ("calc_status", "calc_note", "calc_model_version"):
                self.assertIsNone(row[col], col)            # nothing submitted is stored
        log = "\n".join(cm.output)
        self.assertIn("calc invalid", log)
        self.assertNotIn("anna@example.de", log)
        self.assertNotIn("\nТелефон", log)                  # repr in the log: no injected line

    def test_missing_calc_field_lead_kept(self):
        with self.assertLogs(self.mod.app.logger, level="WARNING"):
            r, _ = self.post({"calc_m2": "72", "calc_pay": "m12"})
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual((self.rows()[0]["calc_status"], self.rows()[0]["calc_note"]), ("invalid", "calc_step: нет"))

    def test_lead_without_calc_unchanged(self):
        r, nl = self.post({}, n=1)
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertIsNone(self.rows()[0]["calc_status"])
        self.assertEqual(nl.call_args.args, ("Tenerife waitlist", "Анна", "anna@example.de", "ru",
                                             "/tenerife/calculadora/"))
        self.assertEqual(nl.call_args.kwargs, {})

    def test_model_unreadable_does_not_block_lead(self):
        with mock.patch.object(self.tenerife, "load_model", side_effect=OSError("x")), \
                self.assertLogs(self.mod.app.logger, level="WARNING") as cm:
            r, _ = self.post(good())
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual((self.rows()[0]["calc_status"], self.rows()[0]["calc_m2"]), ("invalid", None))
        self.assertIn("model.json unavailable", "\n".join(cm.output))

    def test_migration_of_existing_table_is_idempotent(self):
        c = sqlite3.connect(self.mod.DB)
        c.execute("""CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL,
                     language TEXT NOT NULL, page TEXT, consent INTEGER NOT NULL, client_hash TEXT,
                     created_at TEXT NOT NULL)""")
        c.execute("INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)"
                  " VALUES('Old','old@example.com','ru','/tenerife/',1,'h','2026-10-30T10:00:00')")
        c.commit()
        c.close()
        self.post(good())
        self.post(good(), n=2)
        rows = self.rows()
        self.assertEqual([r["name"] for r in rows], ["Old", "Анна", "Анна"])
        self.assertIsNone(rows[0]["calc_status"])
        self.assertEqual(rows[2]["calc_amount"], 212400)
        c = sqlite3.connect(self.mod.DB)
        cols = [r[1] for r in c.execute("PRAGMA table_info(tenerife_waitlist)")]
        c.close()
        self.assertEqual(cols[-len(tenerife_calc.COLUMNS):], [x for x, _ in tenerife_calc.COLUMNS])

    def test_admin_rows_still_work(self):
        self.post(good())
        c = sqlite3.connect(self.mod.DB)
        rows = self.tenerife.waitlist_rows(c)
        c.close()
        self.assertEqual(rows[0][1], "Анна")


def calc_row(data=None):
    calc, _ = tenerife_calc.check_calc(data or good(), model())
    return calc


class TelegramTextTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        import notify
        self.notify = importlib.reload(notify)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def lines(self, calc):
        return self.notify.format_lead("Tenerife waitlist", "Анна", "+34 600", "ru", "/tenerife/calculadora/",
                                       calc=calc, model=model()).splitlines()[5:]

    def test_matching_lead_lines(self):
        self.assertEqual(self.lines(calc_row()), [
            "Калькулятор: 72 м², акций: 72, тип: Две спальни",
            "Ступень: Очередь — 2 950 €/м²",
            "Сумма: 212 400 €",
            "Оплата: рассрочка 12 мес. — 17 700 €/мес.",
            f"Модель: {model()['version']}",
        ])

    def test_stale_page_lines_show_flag_and_both_values(self):
        self.assertEqual(self.lines(calc_row(STALE)), [
            "Калькулятор: расчёт не совпадает с текущей моделью",
            "Прислано: 120 м², ступень handover, оплата рассрочка 24 мес.",
            "Пересчёт: 100 м², ступень queue, оплата сразу",
            "Калькулятор: 100 м², акций: 100, тип: Большой дом",
            "Ступень: Очередь — 2 950 €/м²",
            "Сумма: 295 000 €",
            "Оплата: сразу",
            f"Модель: {model()['version']}",
        ])

    def test_invalid_lines(self):
        self.assertEqual(self.lines(calc_row(good(calc_m2="abc"))), [
            "Калькулятор: данные неверны, расчёт не сохранён (calc_m2: неверный формат)",
            f"Модель: {model()['version']}",
        ])
        self.assertEqual(self.lines(None), [])

    def test_plain_text_no_parse_mode_no_secrets_no_injected_lines(self):
        os.environ["ARTEMIS_TG_BOT_TOKEN"] = "123456:SECRET-token"
        os.environ["ARTEMIS_TG_CHAT_ID"] = "-100123"
        sent = []

        class Resp:
            def read(self):
                return b'{"ok":true}'

        def fake_urlopen(url, data=None, timeout=None):
            sent.append((url, urllib.parse.parse_qs(data.decode())))
            return Resp()

        with mock.patch.object(self.notify.urllib.request, "urlopen", fake_urlopen):
            self.notify.notify_lead("Tenerife waitlist", "<b>Ann</b>_*[x](http://e.vil)\nКонтакт: fake", "a@b.cd",
                                    "ru", "/tenerife/calculadora/", background=False, calc=calc_row(), model=model())
        self.assertEqual(len(sent), 1)                       # mocked: nothing leaves the test
        url, q = sent[0]
        self.assertNotIn("parse_mode", q)                    # plain text: no Markdown/HTML interpretation
        text = q["text"][0]
        self.assertIn("Имя: <b>Ann</b>_*[x](http://e.vil) Контакт: fake", text)   # literal, one line
        self.assertEqual(sum(line.startswith("Контакт:") for line in text.splitlines()), 1)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("123456", text)
        self.assertEqual(len(text.splitlines()), 10)

    def test_send_failure_logs_no_token(self):
        os.environ["ARTEMIS_TG_BOT_TOKEN"] = "123456:SECRET-token"
        os.environ["ARTEMIS_TG_CHAT_ID"] = "-100123"
        leak = OSError("https://api.telegram.org/bot123456:SECRET-token")
        with mock.patch.object(self.notify.urllib.request, "urlopen", side_effect=leak), \
                self.assertLogs("artemis.notify", level="WARNING") as cm:
            self.notify.notify_lead("k", "A", "a@b.cd", "ru", "/x/", background=False, calc=calc_row(), model=model())
        self.assertNotIn("SECRET", "\n".join(cm.output))


def load_relay(env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location("relay_calc", ROOT / "deploy" / "artemis-lead-relay.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RELAY = Path(__file__).resolve().parent.parent / "deploy" / "artemis-lead-relay.py"


# deploy/artemis-lead-relay.py is main/#26's version (PR #22 r4 does not touch deploy/); it has no calc lines yet.
# These checks switch on by themselves once the relay gets calc_lines().
@unittest.skipUnless("def calc_lines" in RELAY.read_text(encoding="utf-8"),
                     "relay (main/#26) has no calc_lines(); calculator lines come from app/notify.py only")
class RelayCalcTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.d.name, "leads.db")
        self.env_file = os.path.join(self.d.name, "artemis.env")
        Path(self.env_file).write_text("ARTEMIS_TG_BOT_TOKEN=123456:SECRET-token\nARTEMIS_TG_CHAT_ID=-100123\n")
        self.m = load_relay({"ARTEMIS_DB": self.db, "ARTEMIS_RELAY_STATE": os.path.join(self.d.name, "s.db"),
                             "ARTEMIS_ENV_FILE": self.env_file, "ARTEMIS_MODEL_JSON": str(MODEL),
                             "ARTEMIS_LEAD_EMAIL_TO": "info@artemisresort.com",
                             "ARTEMIS_LEAD_EMAIL_FROM": "info@oxfordframe.com"})
        import notify
        self.notify = notify

    def tearDown(self):
        self.d.cleanup()

    def make_db(self, with_calc):
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY, name, contact, language, page, consent,"
                  " client_hash, created_at)")
        if with_calc:
            tenerife_calc.migrate(c)
            calc = calc_row()
            cols = ",".join(x for x, _ in tenerife_calc.COLUMNS)
            c.execute(f"INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at,{cols})"
                      f" VALUES('Анна','a@b.cd','ru','/tenerife/calculadora/',1,'h','2026-10-31T19:00:00',"
                      f"{','.join('?' * len(tenerife_calc.COLUMNS))})", [calc[x] for x, _ in tenerife_calc.COLUMNS])
        c.execute("INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)"
                  " VALUES('Без','b@b.cd','ru','/tenerife/',1,'h','2026-10-31T19:01:00')")
        c.commit()
        c.close()

    def test_old_db_without_calc_columns(self):
        self.make_db(False)
        (tbl, kind, d), = self.m.leads()
        self.assertNotIn("calc_status", d)
        self.assertNotIn("Калькулятор", self.m.lead_text(kind, d))

    def test_calc_columns_read_and_formatted_like_the_app(self):
        self.make_db(True)
        rows = self.m.leads()
        (_, kind, d), (_, _, plain) = rows
        text = self.m.lead_text(kind, d)
        self.assertEqual(self.m.calc_lines(d), self.notify.format_calc(calc_row(), model()))
        for line in self.notify.format_calc(calc_row(), model()):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("Калькулятор", self.m.lead_text(kind, plain))

    def test_same_lines_as_app_for_every_status(self):
        for data in (good(), STALE, good(calc_m2="57", calc_pay="now"), good(calc_step="x" * 40), {"calc_m2": "72"}):
            c = calc_row(data)
            self.assertEqual(self.m.calc_lines(c), self.notify.format_calc(c, model()), data)

    def test_model_unreadable_falls_back_to_ids(self):
        self.m.MODEL_JSON = os.path.join(self.d.name, "missing.json")
        lines = self.m.calc_lines(calc_row())
        self.assertIn("Калькулятор: 72 м², акций: 72, тип: two_bed", lines)
        self.assertIn("Ступень: queue — 2 950 €/м²", lines)

    def test_malformed_row_never_blocks(self):
        t = self.m.lead_text("k", {"name": "A", "contact": "a@b.cd", "calc_status": "ok", "calc_m2_server": 72,
                                   "calc_shares": "x"})
        self.assertIn("Калькулятор: данные не прочитаны", t)

    def test_tg_send_plain_text_and_no_token_in_errors(self):
        sent = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok":true,"result":{"message_id":7,"date":1}}'

        def fake_urlopen(url, data=None, timeout=None):
            sent.append(urllib.parse.parse_qs(data.decode()))
            return Resp()

        text = self.m.lead_text("Tenerife waitlist", dict(calc_row(), name="<i>x</i>", contact="a@b.cd"))
        with mock.patch.object(self.m.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(self.m.tg_send(text), "tg:7@1")
        self.assertNotIn("parse_mode", sent[0])
        self.assertEqual(sent[0]["text"][0], text)
        self.assertNotIn("SECRET", text)
        with mock.patch.object(self.m.urllib.request, "urlopen", side_effect=OSError("bot123456:SECRET-token")):
            with self.assertRaises(RuntimeError) as cm:
                self.m.tg_send(text)
        self.assertNotIn("SECRET", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class NotifyAmountAndCalcTest(unittest.TestCase):
    """40da553 merge: main's Crete «Сумма (план)» (amount=) and the Tenerife calculator lines live side by side."""

    def setUp(self):
        import notify
        self.notify = notify

    def test_crete_amount_only(self):
        t = self.notify.format_lead("Crete enquiry", "Bob", "b@x.io", "en", "/en/", amount="5 M €")
        self.assertIn("\nСумма (план): 5 M €", t)
        self.assertNotIn("Калькулятор", t)

    def test_tenerife_calc_without_amount(self):
        t = self.notify.format_lead("Tenerife waitlist", "A", "+34 600", "ru", "/tenerife/calculadora/",
                                    calc=calc_row(), model=model())
        self.assertNotIn("Сумма (план)", t)
        self.assertIn("Калькулятор:", t)

    def test_notify_passes_both_through(self):
        sent = []
        with mock.patch.dict(os.environ, {"ARTEMIS_TG_BOT_TOKEN": "t", "ARTEMIS_TG_CHAT_ID": "c"}), \
                mock.patch.object(self.notify, "_send", lambda tok, chat, text: sent.append(text)):
            self.notify.notify_lead("Crete enquiry", "Bob", "b@x.io", "en", "/en/", background=False, amount="3 M €")
            self.notify.notify_lead("Tenerife waitlist", "A", "a@b.cd", "ru", "/t/", background=False,
                                    calc=calc_row(), model=model())
        self.assertIn("Сумма (план): 3 M €", sent[0])
        self.assertIn("Калькулятор:", sent[1])
        self.assertNotIn("Сумма (план)", sent[1])
