"""Tenerife RU preview: noindex, not linked from Crete, waitlist validation, anti-spam."""
import importlib
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt

# founder 31.10.2026 01:44 UTC: no disclaimer block, no «Визуализация»/AI captions (supersedes PR #4/#5 rule)
REMOVED_DISCLAIMERS = [
    r"визуализац", r"\(AI\)", r"(?<![А-Яа-яЁё])ИИ(?![А-Яа-яЁё])", r"не фотограф", r"иллюстрация этапа",
    r"Важная информация", r"ценных бумаг", r"Vermögensanlage", r"оферт", r"не гарантирован",
    r"общая информация", r"до разрешения",
    # EN r1: the same captions / disclaimer blocks in English
    r"visuali[sz]ation", r"not a photograph", r"Important information", r"\bsecurities\b", r"general information",
]

FORBIDDEN = [
    r"\d\s*[–-]\s*\d\s*%",          # yield ranges like 4–6 %
    r"доходност\w* \d",              # numeric yield
    r"дивиденд",
    r"пул запросов инвесторов",
    r"Инвестор в долю",
    r"пирамид",
    r"Exact plot", r"Investment framing", r"Financiación", r"Calculadora", r"Construcción", r"Proceso",
    r"name=\"amount\"", r"Сумма",
]


class TenerifePreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None)
                      for k in ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")}
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def rows(self):
        c = sqlite3.connect(self.mod.DB)
        try:
            return c.execute("select name,contact,language,page,consent from tenerife_waitlist").fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            c.close()

    def post(self, ip="1.2.3.4", **kw):
        data = {"name": "Anna", "contact": "anna@example.de", "language": "de",
                "consent": True, "page": "/tenerife-preview/"}
        data.update(kw)
        return self.client.post("/api/tenerife/waitlist", json=data,
                                headers={"X-Real-IP": ip})  # set by nginx (QA T3-04)

    # --- pages ---------------------------------------------------------
    def test_pages_200_and_noindex(self):
        # designer T47 (31.10.2026): the old one-pager is retired -> /tenerife-preview[/] answers ONE 301 to /tenerife/
        for path in ("/tenerife-preview", "/tenerife-preview/"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 301, path)
            self.assertEqual(r.headers["Location"].replace("http://localhost", ""), "/tenerife/", path)
            self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""), path)
        # legal pages moved to /tenerife/<name>/ (31.10.2026): old preview URLs answer 301
        for name in ("impressum", "privacy"):
            r = self.client.get(f"/tenerife-preview/{name}/")
            self.assertEqual(r.status_code, 301, name)
            self.assertTrue(r.headers["Location"].endswith(f"/tenerife/{name}/"), r.headers["Location"])
            self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""), name)

    def test_preview_subpaths_301_keep_page_and_query(self):
        # T47: a sub-path that is a /tenerife/ page keeps it; anything else lands on /tenerife/; query kept; one hop
        for path, want in (("/tenerife-preview/?utm_source=x", "/tenerife/?utm_source=x"),
                           ("/tenerife-preview/norte", "/tenerife/norte/"),
                           ("/tenerife-preview/faq/?a=1", "/tenerife/faq/?a=1"),
                           ("/tenerife-preview/boris/x/y", "/tenerife/boris/"),
                           ("/tenerife-preview/gracias/", "/tenerife/"),
                           ("/tenerife-preview/no-such-page", "/tenerife/"),
                           ("/tenerife-preview/index.html", "/tenerife/")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 301, path)
            loc = r.headers["Location"].replace("http://localhost", "")
            self.assertEqual(loc, want, path)
            self.assertEqual(self.client.get(loc).status_code, 200, loc)

    def test_preview_legal_without_slash_one_hop_301_keeps_query(self):
        # QA B-01 (31.10.2026): no 308 -> 301 chain; straight to the canonical URL, query string kept
        for name in ("impressum", "privacy"):
            for suffix, qs in (("", ""), ("", "?utm_source=x&a=1"), ("/", "?utm_source=x")):
                r = self.client.get(f"/tenerife-preview/{name}{suffix}{qs}")
                self.assertEqual(r.status_code, 301, (name, suffix, qs))
                self.assertEqual(r.headers["Location"].split("artemisresort.com")[-1].replace("http://localhost", ""),
                                 f"/tenerife/{name}/{qs}")
                final = self.client.get(f"/tenerife/{name}/")
                self.assertEqual(final.status_code, 200)

    def test_no_disclaimers_or_ai_captions(self):
        for path in ("/tenerife/impressum/", "/tenerife/privacy/"):
            body = self.client.get(path).get_data(as_text=True)
            for pat in REMOVED_DISCLAIMERS:
                self.assertIsNone(re.search(pat, body, re.I), f"{path}: {pat}")

    def test_impressum_has_operator_no_placeholders(self):
        body = self.client.get("/tenerife/impressum/").get_data(as_text=True)
        # founder 31.10.2026 01:11 UTC: publish OXFORD FRAME REAL ASSETS LTD / 09153936 (Companies House facts only)
        for must in ("OXFORD FRAME REAL ASSETS LTD", "09153936", "England and Wales",
                     "Drovers, Preston Candover, Basingstoke, RG25 2EE", "Szabolcs Szaniszlo"):
            self.assertIn(must, body)
        self.assertNotIn("[уточнить", body)  # placeholders removed; only known data (founder 31.10)
        self.assertIn("info@artemisresort.com", body)
        for forbidden in ("Oxford Frame Ltd", "dormant", "Dormant", "активн", "торгу"):
            self.assertNotIn(forbidden, body)

    def test_privacy_names_controller_and_hosting_country(self):
        body = self.client.get("/tenerife/privacy/").get_data(as_text=True)
        for must in ("OXFORD FRAME REAL ASSETS LTD", "09153936", "England and Wales", "the server is located in Germany"):
            self.assertIn(must, body)
        self.assertNotIn("Oxford Frame Ltd", body)

    def test_not_linked_from_crete(self):
        for lang in ("en", "ru", "es", "fr"):
            for path in (f"/{lang}/", f"/{lang}/privacy/", f"/{lang}/terms/"):
                body = self.client.get(path).get_data(as_text=True)
                self.assertNotIn("tenerife-preview", body, path)
                self.assertNotIn("noindex", self.client.get(path).headers.get("X-Robots-Tag", ""), path)

    # --- waitlist ------------------------------------------------------
    def test_waitlist_ok_stores_and_notifies_four_fields(self):
        with mock.patch("tenerife.notify_lead") as nl:
            r = self.post()
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""))
        self.assertEqual(self.rows(), [("Anna", "anna@example.de", "de", "/tenerife-preview/", 1)])
        nl.assert_called_once_with("Tenerife waitlist", "Anna", "anna@example.de", "de", "/tenerife-preview/")

    def test_waitlist_without_tg_config_stores_and_warns(self):
        with self.assertLogs("artemis.notify", level="WARNING"):
            self.assertEqual(self.post().status_code, 200)
        self.assertEqual(len(self.rows()), 1)

    def test_waitlist_validation(self):
        self.assertEqual(self.post(consent=False).status_code, 400)
        self.assertEqual(self.post(name="").status_code, 400)
        self.assertEqual(self.post(contact="x").status_code, 400)
        self.assertEqual(self.post(language="xx").status_code, 400)
        self.assertEqual(self.rows(), [])

    def test_waitlist_ignores_amount_field(self):
        with mock.patch("tenerife.notify_lead"):
            self.post(amount="100000")
        c = sqlite3.connect(self.mod.DB)
        cols = [r[1] for r in c.execute("PRAGMA table_info(tenerife_waitlist)")]
        c.close()
        self.assertNotIn("amount", cols)

    def test_honeypot_drops_silently(self):
        with mock.patch("tenerife.notify_lead") as nl:
            r = self.post(website="http://spam.example")
        self.assertEqual(r.get_json(), {"ok": True})
        nl.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_rate_limit_per_client(self):
        with mock.patch("tenerife.notify_lead"):
            codes = [self.post(ip="9.9.9.9").status_code for _ in range(4)]
            other = self.post(ip="8.8.8.8").status_code
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(other, 200)

    def test_form_post_without_js_redirects(self):
        with mock.patch("tenerife.notify_lead"):
            r = self.client.post("/api/tenerife/waitlist", data={
                "name": "Ivan", "contact": "@ivan_tg", "language": "ru", "consent": "1", "website": ""})
        self.assertEqual(r.status_code, 303)
        # QA T3-05: no-JS thank-you page; without a page field the way back is /tenerife/, never the preview
        self.assertTrue(r.headers["Location"].endswith("/tenerife/gracias/?back=%2Ftenerife%2F"), r.headers["Location"])

    def test_admin_lists_waitlist_escaped(self):
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "z" * 40
        try:
            with mock.patch("tenerife.notify_lead"):
                self.post(name="<b>x</b>")
            body = self.client.get("/admin/leads?t=" + "z" * 40).get_data(as_text=True)
            self.assertIn("Tenerife waitlist (1)", body)
            self.assertIn("&lt;b&gt;x&lt;/b&gt;", body)
        finally:
            os.environ.pop("ARTEMIS_ADMIN_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
