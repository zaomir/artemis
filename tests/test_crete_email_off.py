"""A-13 (QA 2026-10-31 prod-deploy fa39ad0): Crete addresses must not be hidden by Cloudflare Email Obfuscation.

Cloudflare (zone setting stays ON) rewrites mailto links / addresses into /cdn-cgi/l/email-protection#…, which
404s without JS. Every Crete page is rendered through email_off.wrap() (same module as the Tenerife build), so
addresses reach the visitor inside <!--email_off-->…<!--/email_off-->. Checked on the raw HTML of every route."""
import html as _html
import importlib
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))

from email_off import OFF, ON, mailto_form_actions, mailto_targets, unprotected, wrap  # noqa: E402

LANGS = ("en", "ru", "es", "fr")
ROUTES = [f"/{l}/{p}" for l in LANGS for p in ("", "privacy/", "terms/")]
CONTACT = "info@artemisresort.com"
BLOCK = re.compile(re.escape(ON) + r".*?" + re.escape(OFF), re.S)
MAILTO_FORM = r"""(?i)\b(?:form)?action\s*=\s*["']?\s*mailto:"""
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


class CreteEmailOffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as artemis_app
        cls.mod = importlib.reload(artemis_app)
        cls.client = cls.mod.app.test_client()

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.get_data(as_text=True)

    def test_every_route_ok(self):
        for url in ROUTES:
            html = self.get(url)
            # nothing Cloudflare would still rewrite, and nothing already rewritten
            self.assertEqual(unprotected(html), [], url)
            self.assertNotIn("email-protection", html, url)
            self.assertNotIn("__cf_email__", html, url)
            self.assertNotIn("data-cfemail", html, url)
            # markers survive rendering (no minifier / comment stripping) and are balanced
            self.assertEqual(html.count(ON), html.count(OFF), url)
            # every mailto link and every visible address sits inside a marker block
            outside = BLOCK.sub("", html)
            self.assertNotIn("mailto:", outside.lower(), url)
            self.assertEqual(re.findall(r"(?i)<a\b[^>]*mailto:", outside), [], url)
            # only the contact address is linked: path and ?to= / ?cc= / ?bcc=, entities decoded (QA pr21 -40)
            self.assertLessEqual(mailto_targets(html), {CONTACT}, url)
            # forms never submit via mailto (any quoting, entity-encoded too), no external form services
            self.assertIsNone(re.search(MAILTO_FORM, html), url)
            self.assertIsNone(re.search(MAILTO_FORM, _html.unescape(html)), url)
            self.assertEqual(mailto_form_actions(html), [], url)
            self.assertNotRegex(html, r"(?i)formspree")
            # idempotent: the served page is already fully wrapped
            self.assertEqual(wrap(html), html, url)

    def test_contact_link_and_privacy_addresses_wrapped(self):
        for lang in LANGS:
            html = self.get(f"/{lang}/")
            blocks = BLOCK.findall(html)
            self.assertTrue(any(re.search(r'<a href="mailto:' + re.escape(CONTACT) + '"', b, re.I) for b in blocks),
                            lang)
            privacy = self.get(f"/{lang}/privacy/")
            self.assertGreaterEqual(privacy.count(ON), 1, lang)
            # every address visible in the privacy text is inside a block (case-insensitive)
            outside = BLOCK.sub("", privacy)
            texts = re.sub(r"<[^>]*>", " ", re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", outside))
            self.assertEqual(EMAIL.findall(texts), [], lang)

    def test_form_placeholders_not_wrapped(self):
        # addresses in attributes (placeholder="name@company.com") are not rewritten by Cloudflare: left as is
        html = self.get("/en/")
        self.assertRegex(html, r'placeholder="[^"<]*@[^"<]*"')
        self.assertNotRegex(html, r'placeholder="[^"]*<!--')

    def test_only_markers_added(self):
        for lang in LANGS:
            for page, tpl in (("site", "index.html"), ("privacy", "legal/privacy.html")):
                with self.mod.app.test_request_context(f"/{lang}/"):
                    if page == "site":
                        raw = self.mod.render_template(tpl, **self.mod._ctx(lang))
                        served = self.get(f"/{lang}/")
                    else:
                        raw = self.mod.render_template(tpl, page="privacy", legal_i18n=self.mod.legal_i18n.load(
                            "privacy", lang), **self.mod._ctx(lang))
                        served = self.get(f"/{lang}/privacy/")
                self.assertEqual(served.replace(ON, "").replace(OFF, ""), raw, (lang, page))

    def test_legal_drop_in_addresses_wrapped(self):
        # A-06 translations arrive later; an address in a drop-in is protected the same way
        with tempfile.TemporaryDirectory() as d:
            Path(d, "privacy.ru.md").write_text(
                "<!-- @body -->\nПишите на info@artemisresort.com.\n", encoding="utf-8")
            with mock.patch.object(self.mod.legal_i18n, "LEGAL_DIR", Path(d)):
                html = self.get("/ru/privacy/")
        self.assertIn(ON + CONTACT + OFF, html)
        self.assertEqual(unprotected(html), [])

    def test_wrap_failure_does_not_break_page(self):
        with mock.patch.object(self.mod.email_off, "wrap", side_effect=self.mod.email_off.EmailOffError("x")), \
                self.assertLogs(level="ERROR"):
            r = self.client.get("/en/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"mailto:", r.data)

    def test_tenerife_pages_unchanged(self):
        # the Tenerife pages are wrapped at build time; the Crete hook does not touch them
        for url in ("/tenerife/", "/tenerife/privacy/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(unprotected(r.get_data(as_text=True)), [], url)


if __name__ == "__main__":
    unittest.main()
