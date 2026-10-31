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

# founder 31.10.2026 01:44 UTC: no disclaimer block, no «Визуализация»/AI captions (supersedes PR #4/#5 rule)
REMOVED_DISCLAIMERS = [
    r"визуализац", r"\(AI\)", r"(?<![А-Яа-яЁё])ИИ(?![А-Яа-яЁё])", r"не фотограф", r"иллюстрация этапа",
    r"Важная информация", r"ценных бумаг", r"Vermögensanlage", r"оферт", r"не гарантирован",
    r"общая информация", r"до разрешения",
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
                                headers={"CF-Connecting-IP": ip})

    # --- pages ---------------------------------------------------------
    def test_pages_200_and_noindex(self):
        for path in ("/tenerife-preview/",):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""), path)
            self.assertIn('<meta name="robots" content="noindex', r.get_data(as_text=True), path)
        # legal pages moved to /tenerife/<name>/ (31.10.2026): old preview URLs answer 301
        for name in ("impressum", "privacy"):
            r = self.client.get(f"/tenerife-preview/{name}/")
            self.assertEqual(r.status_code, 301, name)
            self.assertTrue(r.headers["Location"].endswith(f"/tenerife/{name}/"), r.headers["Location"])
            self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""), name)
        r = self.client.get("/tenerife-preview")
        self.assertIn(r.status_code, (301, 308))

    def test_preview_content_rules(self):
        body = self.client.get("/tenerife-preview/").get_data(as_text=True)
        for must in ("лист ожидания",
                     "Simon Subic", "Lana Evans", "Boris Ribaut", "6/2025",
                     "Посуточная аренда — только как опция", 'name="website"', 'name="consent"'):
            self.assertIn(must, body)
        for pat in FORBIDDEN:
            self.assertIsNone(re.search(pat, body, re.I), pat)

    def test_no_disclaimers_or_ai_captions(self):
        for path in ("/tenerife-preview/", "/tenerife/impressum/", "/tenerife/privacy/"):
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
        for must in ("OXFORD FRAME REAL ASSETS LTD", "09153936", "England and Wales", "Германии"):
            self.assertIn(must, body)
        self.assertNotIn("Oxford Frame Ltd", body)

    def test_preview_footer_uses_registered_name(self):
        body = self.client.get("/tenerife-preview/").get_data(as_text=True)
        self.assertIn("OXFORD FRAME REAL ASSETS LTD", body)
        self.assertNotIn("Oxford Frame Ltd", body)
        for name in ("impressum", "privacy"):  # links go straight to the canonical legal pages
            self.assertIn(f'href="/tenerife/{name}/"', body)
            self.assertNotIn(f'href="/tenerife-preview/{name}/"', body)

    def test_not_linked_from_crete(self):
        for lang in ("en", "ru", "es", "fr"):
            for path in (f"/{lang}/", f"/{lang}/privacy/", f"/{lang}/terms/"):
                body = self.client.get(path).get_data(as_text=True)
                self.assertNotIn("tenerife-preview", body, path)
                self.assertNotIn("noindex", self.client.get(path).headers.get("X-Robots-Tag", ""), path)

    def test_images_exist(self):
        body = self.client.get("/tenerife-preview/").get_data(as_text=True)
        for src in set(re.findall(r'/static/tenerife/([\w.-]+\.jpg)', body)):
            self.assertTrue((ROOT / "app" / "static" / "tenerife" / src).is_file(), src)

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
        self.assertIn("/tenerife-preview/?ok=1", r.headers["Location"])

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
