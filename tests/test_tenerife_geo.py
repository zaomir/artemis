"""EN r2: site root `/` always opens English /tenerife/; geo never sends users to ES/DE/FR/RU.

t122u / Lead GO 05.11.2026: public Tenerife is English only. CF-IPCountry is ignored for locale choice.
"""
import importlib
import os
import sys
import tempfile
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))


class GeoRedirectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ("TENERIFE_WHATSAPP", "TENERIFE_INDEXING")}
        os.environ["TENERIFE_INDEXING"] = "1"
        os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TENERIFE_INDEXING", None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def client(self):
        return self.mod.app.test_client()

    def test_every_country_lands_on_english_home(self):
        for country in ("ES", "DE", "AT", "CH", "FR", "BE", "LU", "MC", "US", "GB", "RU", ""):
            with self.subTest(country=country):
                r = self.client().get("/", headers={"CF-IPCountry": country})
                self.assertEqual(r.status_code, 302, country)
                self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, "/tenerife/", country)

    def test_tenerife_root_is_english_200_for_every_country(self):
        for country in ("ES", "DE", "AT", "FR", "US", "GB", "RU", ""):
            with self.subTest(country=country):
                r = self.client().get("/tenerife/", headers={"CF-IPCountry": country})
                self.assertEqual(r.status_code, 200, country)
                self.assertIn(b'<html lang="en">', r.data, country)

    def test_lang_param_does_not_open_non_en_locale(self):
        r = self.client().get("/tenerife/?lang=de", headers={"CF-IPCountry": "US"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<html lang="en">', r.data)

    def test_lang_param_on_site_root_still_opens_en(self):
        r = self.client().get("/?lang=de", headers={"CF-IPCountry": "US"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, "/tenerife/")

    def test_query_kept_on_root_redirect(self):
        r = self.client().get("/?utm=1", headers={"CF-IPCountry": "FR"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].startswith("/tenerife/"))
        self.assertIn("utm=1", r.headers["Location"])

    def test_non_en_locale_prefix_301_to_en(self):
        cases = (
            ("/tenerife/es/", "/tenerife/"),
            ("/tenerife/de/norte/", "/tenerife/norte/"),
            ("/tenerife/fr/condiciones/", "/tenerife/condiciones/"),
            ("/tenerife/ru/inversores/", "/tenerife/inversores/"),
            ("/tenerife/en/", "/tenerife/"),
        )
        for src, dest in cases:
            with self.subTest(src=src):
                r = self.client().get(src)
                self.assertEqual(r.status_code, 301, src)
                self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, dest, src)


if __name__ == "__main__":
    unittest.main()
