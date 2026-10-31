"""PR #21, 4th commit: QA protocol 2026-10-31_pr21-crete-fixes, defects -40 … -44.

-40 mailto allowlist sees ?to= / ?cc= / ?bcc= and entity-encoded schemes (&#109;ailto:)
-41 planned amount: one rule on client and server (0, negatives, non-ASCII digits, NaN rejected)
-42 stricter server-side e-mail format; lists / objects / numbers in text fields rejected, consent must be true
-43 email_off: any exception in wrap() -> page served unwrapped + logged; missing / broken module -> app still starts
-44 header CTA: accessible name = visible text at every width (no aria-label), WCAG 2.5.3
axe (label-content-name-mismatch at 320/390/768/1280 x 4 languages) runs with Playwright outside pytest."""
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))

from email_off import ON, OFF, mailto_form_actions, mailto_targets, unprotected, wrap  # noqa: E402

LANGS = ("en", "ru", "es", "fr")
T = {l: json.loads((ROOT / "app" / "translations" / f"{l}.json").read_text(encoding="utf-8")) for l in LANGS}
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")
CONTACT = "info@artemisresort.com"
NODE = shutil.which("node")

# QA mutations M21-M27 (scripts/mut.py), as snippets
M21 = '<p><!--email_off--><a href="mailto:info@artemisresort.com?cc=evil@example.com">info@artemisresort.com</a><!--/email_off--></p>'
M22 = '<p><!--email_off--><a href="mailto:?to=evil@example.com">write</a><!--/email_off--></p>'
M23 = '<p><a href="&#109;ailto:evil@example.com">write</a></p>'
M24 = '<p><!--email_off--><a href="mailto:info@artemisresort.com?bcc=evil@example.com">info@artemisresort.com</a><!--/email_off--></p>'
M25 = '<form action="&#109;ailto:evil@example.com"><button>x</button></form>'


class Base(unittest.TestCase):
    def setUp(self):
        # many valid leads from one test client: the per-client limit (QA P09) is tested in test_enquiry_antispam
        _rl = mock.patch("ratelimit.ENQUIRY_LIMITS", ())
        _rl.start()
        self.addCleanup(_rl.stop)
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

    def post(self, **kw):
        body = {"name": "Bob", "email": "bob@x.io", "consent": True, "enquiry_type": "investor",
                "lang": "en", "page": "/en/"}
        body.update(kw)
        with mock.patch.object(self.mod, "notify_lead") as nl:
            r = self.client.post("/api/enquiry", json=body)
        return r, nl

    def rows(self):
        if not os.path.exists(self.mod.DB):
            return []
        import sqlite3
        with sqlite3.connect(self.mod.DB) as c:
            return c.execute("SELECT name, email, amount FROM leads").fetchall()


# --- -40 ------------------------------------------------------------------------------------------
class MailtoAllowlistTest(unittest.TestCase):
    def test_query_recipients_counted(self):
        self.assertEqual(mailto_targets(M21), {CONTACT, "evil@example.com"})
        self.assertEqual(mailto_targets(M22), {"evil@example.com"})
        self.assertEqual(mailto_targets(M24), {CONTACT, "evil@example.com"})
        self.assertEqual(mailto_targets('<a href="mailto:info@artemisresort.com?subject=Hi&amp;Cc=a%40b.io,c@d.io">'),
                         {CONTACT, "a@b.io", "c@d.io"})
        self.assertEqual(mailto_targets('<a href="MAILTO:INFO@ARTEMISRESORT.COM?subject=x&body=y">'), {CONTACT})
        self.assertEqual(mailto_targets('<a href="mailto:info@artemisresort.com,evil@example.com">'),
                         {CONTACT, "evil@example.com"})
        self.assertEqual(mailto_targets('<a href="mailto:?subject=no-address">'), {""})   # visible to the caller

    def test_entity_and_whitespace_encoded_scheme(self):
        self.assertEqual(mailto_targets(M23), {"evil@example.com"})
        for href in ("&#x6D;ailto:e@x.io", "&#109;&#97;&#105;&#108;&#116;&#111;&#58;e@x.io", "mailto&colon;e@x.io",
                     "ma&#9;ilto:e@x.io", "mai\nlto:e@x.io", "mailto:e&#64;x.io"):
            self.assertEqual(mailto_targets(f'<a href="{href}">w</a>'), {"e@x.io"}, href)
        # unprotected() and wrap() treat the entity form as a mailto link too (Cloudflare / the browser do)
        self.assertEqual(unprotected(M23), ["&#109;ailto:evil@example.com"])
        self.assertEqual(wrap(M23), "<p>" + ON + M23[3:-4] + OFF + "</p>")

    def test_mailto_form_actions(self):
        self.assertEqual(mailto_form_actions(M25), ["&#109;ailto:evil@example.com"])
        for bad in ('<form action="mailto:x@y.z">', "<form ACTION = 'MAILTO:x@y.z'>", "<form action=mailto:x@y.z>",
                    "<button formaction='mailto:evil@example.com'>", '<input formaction = " mailto:x@y.z">',
                    '<form action="ma&#x09;ilto:x@y.z">'):
            self.assertEqual(len(mailto_form_actions(bad)), 1, bad)
        for ok in ('<a href="mailto:info@artemisresort.com">', '<form action="/api/tenerife/waitlist">',
                   "<p>transaction=mailto: (text)</p>", '<form data-action="mailto:x@y.z">'):
            self.assertEqual(mailto_form_actions(ok), [], ok)

    def test_served_pages_pass(self):
        # every Crete and Tenerife route: only the contact address, no mailto form (also checked in the route tests)
        import app as artemis_app
        client = importlib.reload(artemis_app).app.test_client()
        urls = [f"/{l}/{p}" for l in LANGS for p in ("", "privacy/", "terms/")] + [
            "/tenerife/", "/tenerife/impressum/", "/tenerife/privacy/"]
        for url in urls:
            r = client.get(url)
            self.assertEqual(r.status_code, 200, url)
            page = r.get_data(as_text=True)
            self.assertLessEqual(mailto_targets(page), {CONTACT}, url)
            self.assertEqual(mailto_form_actions(page), [], url)


# --- -41 ------------------------------------------------------------------------------------------
AMOUNT_OK = ("3000000", "€3,000,000", "3 000 000 €", "3\u202f000\xa0000 €", "3-5 M EUR", "от 3 млн €",
             "3.000.000 €", "3.000.000,00 €", "3.5", "3,5", "1\n2", "0.5", "10", "£250,000", "$5M", "~3 M (EUR)",
             "3–5 M EUR", "+3000000", "3'000'000 CHF", "1e6", "9" * 64)
AMOUNT_BAD = ("0", "00", "0,00 €", "-5", "-€3,000,000", "–3", "€ -3", "NaN1", "nan", "Infinity", "inf 3", "²", "٣",
              "１", "3²", "abc", "€€€", "9" * 65, "3_000", "5%", "<b>1</b>", "1<script>", "1;DROP", "1 💰", "x" * 70)
AMOUNT_PARITY_EXTRA = ("", "   ", "\xa0", " 3 ", "3\t000", "3\u2009000", "M3", "3\u2028", "3\u0663", "3 млн € ",
                       "3 Infinityx", "−5", "0x10", "3.000,–", "(3)")


class AmountRuleTest(Base):
    def test_server_accepts(self):
        for ok in AMOUNT_OK + (3000000, 3.5, 1):
            r, _ = self.post(amount=ok)
            self.assertEqual(r.status_code, 200, ok)

    def test_server_rejects(self):
        for bad in AMOUNT_BAD + (0, -1, -5.5, 0.0, float("nan"), float("inf")):
            r, nl = self.post(amount=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual((r.get_json()["code"], r.get_json()["field"]), ("amount", "amount"), bad)
            nl.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_normalised_value_stored(self):
        self.post(amount="3\u202f000\xa0000 €")
        self.assertEqual(self.rows(), [("Bob", "bob@x.io", "3 000 000 €")])

    @unittest.skipUnless(NODE, "node not installed")
    def test_client_rule_is_the_server_rule(self):
        page = self.client.get("/en/").get_data(as_text=True)
        js = "\n".join((re.search(r"^const EMAIL_RE = .*$", page, re.M).group(0),
                        re.search(r"^const AMOUNT_WS = .*$", page, re.M).group(0),
                        re.search(r"^function amountClean\(raw\)\{.*?^\}$", page, re.M | re.S).group(0)))
        amounts = [a for a in AMOUNT_OK + AMOUNT_BAD + AMOUNT_PARITY_EXTRA]
        emails = list(EMAIL_OK + EMAIL_BAD_FORMAT)
        script = js + """
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({amounts: data.amounts.map(amountClean), emails: data.emails.map(e => EMAIL_RE.test(e))}));
"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(script)
        try:
            out = subprocess.run([NODE, f.name], input=json.dumps({"amounts": amounts, "emails": emails}),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30, check=True).stdout
        finally:
            os.unlink(f.name)
        res = json.loads(out)
        for raw, client in zip(amounts, res["amounts"]):
            self.assertEqual(client, self.mod._clean_amount(raw), repr(raw))
        for raw, client in zip(emails, res["emails"]):
            self.assertEqual(client, self.mod.email_ok(raw), repr(raw))
        self.assertTrue(all(res["emails"][:len(EMAIL_OK)]))


# --- -42 ------------------------------------------------------------------------------------------
EMAIL_OK = ("bob@x.io", "first.last+tag@sub.example.co.uk", "o'neil@example.ie", "ü@exämple.de", "a@xn--p1ai.xn--p1ai",
            "x_y-z@b-c.example", "A@B.CO", "a" * 64 + "@example.com")
EMAIL_BAD_FORMAT = ("a@b..com", "a@b.c.", "<x>@y.zz", '"q"@y.zz', "a@b.c", "a@-b.com", "a@b-.com", ".a@b.com",
                    "a.@b.com", "a..b@c.com", "a@b", "@b.com", "a@.com", "a b@c.com", "a@@b.com", "a@b.com,c@d.com",
                    "a@b.com\nBcc: x@y.z", "a@b.1com", "a@b.co1", "a;b@c.com", "a@b_c.com",
                    "a" * 65 + "@example.com", "a@" + "b" * 64 + ".com", "x" * 243 + "@b.co")


class EmailAndTypesTest(Base):
    def test_email_format(self):
        for ok in EMAIL_OK + ("  bob@x.io ",):
            r, _ = self.post(email=ok)
            self.assertEqual(r.status_code, 200, ok)
        for bad in EMAIL_BAD_FORMAT + ("b@x.io" + "o" * 260,):
            r, _ = self.post(email=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.get_json()["code"], "email", bad)
        self.assertFalse(self.mod.email_ok("a@b.com\n"))   # fullmatch: "$" does not accept a trailing newline
        self.assertEqual(self.rows(), [(("Bob", ok.strip(), "")) for ok in EMAIL_OK + ("  bob@x.io ",)])

    def test_non_string_fields_rejected_not_coerced(self):
        for key in ("email",):
            for bad in (["a@b.io"], {"a": "b@c.io"}, 123, True):
                r, nl = self.post(**{key: bad})
                self.assertEqual((r.status_code, r.get_json()["code"], r.get_json()["field"]), (400, "email", "email"),
                                 (key, bad))
        for key in ("name", "organisation", "role", "enquiry_type", "message", "lang", "page"):
            for bad in ({"a": 1}, ["Bob"], 5, False):
                r, nl = self.post(**{key: bad})
                self.assertEqual(r.status_code, 400, (key, bad))
                self.assertEqual(r.get_json()["field"], key, (key, bad))
                nl.assert_not_called()
        self.assertEqual(self.rows(), [])  # nothing stored as "['a@b.io']" / "{'a': 1}"

    def test_absent_or_null_optional_fields_ok(self):
        r, _ = self.post(organisation=None, role=None, message=None, amount=None)
        self.assertEqual(r.status_code, 200)

    def test_consent_must_be_true(self):
        for bad in ("false", "true", "yes", 1, "1", [True], {"v": True}, None, False):
            r, nl = self.post(consent=bad)
            self.assertEqual((r.status_code, r.get_json()["code"]), (400, "consent"), bad)
            nl.assert_not_called()
        self.assertEqual(self.post(consent=True)[0].status_code, 200)

    def test_register_alias_same_rules(self):
        with mock.patch.object(self.mod, "notify_lead"):
            r = self.client.post("/api/register", json={"name": "Bob", "email": ["bob@x.io"], "consent": True,
                                                        "enquiry_type": "investor"})
        self.assertEqual(r.status_code, 400)


# --- -43 ------------------------------------------------------------------------------------------
class EmailOffResilienceTest(Base):
    def test_load_failure_returns_none_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            broken = Path(d, "email_off.py")
            broken.write_text("def wrap(:\n", encoding="utf-8")
            raising = Path(d, "raising.py")
            raising.write_text("raise RuntimeError('boom at import')\n", encoding="utf-8")
            for path in (os.path.join(d, "missing.py"), str(broken), str(raising)):
                with self.assertLogs(level="ERROR") as cm:
                    self.assertIsNone(self.mod._load_email_off(path), path)
                self.assertTrue(any("email_off: cannot load" in m for m in cm.output), path)
        self.assertIsNotNone(self.mod._load_email_off())

    def test_pages_served_without_module(self):
        with mock.patch.object(self.mod, "email_off", None):
            for url in ("/en/", "/ru/privacy/", "/fr/terms/"):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)
                body = r.get_data(as_text=True)
                self.assertNotIn(ON, body, url)
        self.assertIn("mailto:", self.client.get("/en/").get_data(as_text=True).lower())

    def test_any_wrap_exception_serves_page_unwrapped(self):
        for exc in (self.mod.email_off.EmailOffError("x"), ValueError("x"), RuntimeError("x"), RecursionError("x"),
                    KeyError("x"), TypeError("x")):
            with mock.patch.object(self.mod.email_off, "wrap", side_effect=exc):
                for url in ("/en/", "/ru/privacy/"):
                    with self.assertLogs(level="ERROR") as cm:
                        r = self.client.get(url)
                    self.assertEqual(r.status_code, 200, (type(exc).__name__, url))
                    self.assertNotIn(ON, r.get_data(as_text=True))
                    self.assertTrue(any("email_off: page left unwrapped" in m for m in cm.output))

    def test_app_starts_without_email_off_file(self):
        # gunicorn imports app.py: a deploy without scripts/tenerife_site_build/ must still start and serve
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / "app", Path(d, "app"), ignore=shutil.ignore_patterns("__pycache__", "*.jpg",
                                                                                         "*.webp", "*.woff2"))
            code = ("import logging, app\n"
                    "assert app.email_off is None\n"
                    "c = app.app.test_client()\n"
                    "for u in ('/en/', '/ru/privacy/', '/tenerife/'):\n"
                    "    r = c.get(u); assert r.status_code == 200, (u, r.status_code)\n"
                    "for u in ('/en/', '/ru/privacy/'):  # Crete pages are wrapped at render time (Tenerife at build)\n"
                    "    assert '<!--email_off-->' not in c.get(u).get_data(as_text=True), u\n"
                    "print('OK')\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith("ARTEMIS_")}
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            r = subprocess.run([sys.executable, "-c", code], cwd=Path(d, "app"), env=env, capture_output=True,
                               text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("OK", r.stdout)
        self.assertIn("email_off: cannot load", r.stderr)


# --- -44 ------------------------------------------------------------------------------------------
class HeaderCtaNameTest(Base):
    def test_cta_name_is_visible_text(self):
        for lang in LANGS:
            h = self.client.get(f"/{lang}/").get_data(as_text=True)
            nav = h[h.index("<nav"):h.index("</nav>")]
            cta = re.search(r'<a class="btn" href="#enquiry"([^>]*)>(.*?)</a>', nav, re.S)
            self.assertIsNotNone(cta, lang)
            self.assertNotRegex(cta.group(1), r"aria-label|aria-labelledby|title=", lang)
            self.assertEqual(re.findall(r'<span class="cta-(long|short)">([^<]+)</span>', cta.group(2)),
                             [("long", T[lang]["cta_request"]), ("short", T[lang]["nav_enquiry"])], lang)
            # no link or button on the page names itself differently from its text
            self.assertEqual(re.findall(r"<(?:a|button)\b[^>]*\baria-label=", h), [], lang)


if __name__ == "__main__":
    unittest.main()
