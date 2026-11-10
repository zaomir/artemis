"""EN r2+ investor surface (t15u): /inversores/ live; acciones/alquiler 301; no public share maths."""
import importlib
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
os.environ.setdefault("TENERIFE_WHATSAPP", "+440000000000")


class InvestorArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TENERIFE_INDEXING"] = "1"
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.c = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TENERIFE_INDEXING", None)

    def test_inversores_and_condiciones_live_en(self):
        for path in ("/tenerife/inversores/", "/tenerife/condiciones/"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(b'<html lang="en">', r.data)
            self.assertNotIn(b"hreflang=", r.data)

    def test_retired_slugs_301(self):
        r = self.c.get("/tenerife/acciones/?ref=1")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers["Location"], "/tenerife/inversores/?ref=1")
        r = self.c.get("/tenerife/alquiler/")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, "/tenerife/")

    def test_calculadora_301_to_condiciones(self):
        r = self.c.get("/tenerife/calculadora/?ref=1")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers["Location"], "/tenerife/condiciones/?ref=1")

    def test_locale_investor_urls_301_to_en(self):
        for src in ("/tenerife/es/inversores/", "/tenerife/de/acciones/", "/tenerife/ru/condiciones/"):
            r = self.c.get(src)
            self.assertEqual(r.status_code, 301, src)
            path = urllib.parse.urlsplit(r.headers["Location"]).path
            self.assertFalse(any(f"/{loc}/" in path for loc in ("es", "de", "fr", "ru")), path)

    def test_no_share_offer_language_on_investor_routes(self):
        for path in ("/tenerife/inversores/", "/tenerife/condiciones/"):
            body = self.c.get(path).data.decode()
            self.assertNotIn("dividend", body.lower())
            self.assertNotIn("developer company shares", body.lower())
            self.assertNotIn("calculadora", body)
            self.assertNotIn("calc.js", body)
        body = self.c.get("/tenerife/inversores/").data.decode()
        self.assertIn("€200,000", body)

    def test_no_calc_assets_public(self):
        for path in ("/static/tenerife/site/calc.js", "/static/tenerife/site/model.json"):
            self.assertEqual(self.c.get(path).status_code, 404, path)

    def test_sitemap_en_only_when_indexing(self):
        locs = self.c.get("/sitemap.xml").data.decode()
        self.assertIn("/tenerife/inversores/", locs)
        self.assertIn("/tenerife/condiciones/", locs)
        for bad in ("/tenerife/acciones/", "/tenerife/alquiler/", "/tenerife/es/", "/tenerife/de/",
                    "/tenerife/fr/", "/tenerife/ru/", "/tenerife/calculadora"):
            self.assertNotIn(bad, locs)


if __name__ == "__main__":
    unittest.main()
