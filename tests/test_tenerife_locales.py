"""EN r2: public Tenerife is English only at /tenerife/.

Old /tenerife/{ru,es,de,fr}/… URLs permanently redirect to the EN equivalent.
Built pages: lang=en, no multi-locale hreflang, approved ranges present, calculator absent.
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "tenerife_site_build"
SITE = ROOT / "app" / "tenerife_site"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(BUILD))

from build_v3 import PAGES, APPROVED_RANGES  # noqa: E402

os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
os.environ.setdefault("TENERIFE_WHATSAPP", "+440000000000")


class EnOnlySiteTest(unittest.TestCase):
    def page(self, name):
        return (SITE / f"{name}.html").read_text(encoding="utf-8")

    def test_built_pages_exist(self):
        want = {f"{name}.html" for _f, name in PAGES} | {
            "impressum.html", "privacy.html", "_notice.html", "_404.html", "actualizaciones.html"}
        got = {p.name for p in SITE.glob("*.html")}
        self.assertTrue(want <= got, f"missing {want - got}")
        for loc in ("ru", "es", "de", "fr"):
            self.assertFalse((SITE / loc).exists(), loc)

    def test_lang_en_no_hreflang_alternates(self):
        for _f, name in list(PAGES) + [("", "impressum"), ("", "privacy")]:
            page = self.page(name)
            self.assertIn('<html lang="en">', page, name)
            self.assertEqual(re.findall(r'hreflang="([^"]+)"', page), [], name)

    def test_approved_ranges_present_on_key_pages(self):
        for name in ("index", "acciones", "condiciones"):
            page = self.page(name)
            for token in APPROVED_RANGES:
                self.assertIn(token, page, (name, token))
        # alquiler carries the dividend range, not the €/m² bands
        self.assertIn("2.5–3.5%", self.page("alquiler"))

    def test_no_calculadora_page_file(self):
        self.assertFalse((SITE / "calculadora.html").exists())
        self.assertTrue((SITE / "condiciones.html").exists())
        self.assertTrue((SITE / "acciones.html").exists())
        self.assertTrue((SITE / "inversores.html").exists())


class EnOnlyRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        import app as artemis_app
        os.environ["TENERIFE_INDEXING"] = "1"
        cls.mod = importlib.reload(artemis_app)
        cls.client = cls.mod.app.test_client()

    def test_locale_prefixes_301_to_en(self):
        for src, dest in (
            ("/tenerife/es/producto/", "/tenerife/producto/"),
            ("/tenerife/de/", "/tenerife/"),
            ("/tenerife/fr/privacy/", "/tenerife/privacy/"),
            ("/tenerife/ru/faq/", "/tenerife/faq/"),
            ("/tenerife/en/norte/", "/tenerife/norte/"),
        ):
            r = self.client.get(src)
            self.assertEqual((r.status_code, r.headers.get("Location")), (301, dest), src)

    def test_calculadora_301_condiciones(self):
        r = self.client.get("/tenerife/calculadora/?x=1")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers["Location"], "/tenerife/condiciones/?x=1")


if __name__ == "__main__":
    unittest.main()
