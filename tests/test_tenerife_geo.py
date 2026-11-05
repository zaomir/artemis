"""Гео-открытие Тенерифе: страну встречает корень сайта `/`, а /tenerife/ — всегда английская главная 200.

02.11.2026, решение основателя: ES/DE/FR по CF-IPCountry, EN по умолчанию; cookie сайт не пишет.
P1-02 (06.11.2026): гео-редирект перенесён с /tenerife/ на `/`. Причина: /tenerife/ — canonical и hreflang
en/x-default всех страниц Tenerife, он обязан отвечать 200 EN, иначе Google получает «английская и
default-версия — это немецкая страница». ?lang= по-прежнему сильнее страны.
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

    def test_spanish_visitor_goes_to_spanish(self):
        r = self.client().get("/", headers={"CF-IPCountry": "ES"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/tenerife/es/"))

    def test_german_and_french_visitors(self):
        for country, loc in (("DE", "de"), ("AT", "de"), ("CH", "de"),
                             ("FR", "fr"), ("BE", "fr"), ("LU", "fr"), ("MC", "fr")):
            with self.subTest(country=country):
                r = self.client().get("/", headers={"CF-IPCountry": country})
                self.assertEqual(r.status_code, 302, country)
                self.assertTrue(r.headers["Location"].endswith(f"/tenerife/{loc}/"))

    def test_unknown_country_goes_to_english_home(self):
        for country in ("US", "GB", "RU", ""):
            with self.subTest(country=country):
                r = self.client().get("/", headers={"CF-IPCountry": country})
                self.assertEqual((r.status_code, r.headers["Location"]), (302, "/tenerife/"), country)

    def test_tenerife_root_is_english_200_for_every_country(self):
        """P1-02: /tenerife/ не редиректит ни по гео, ни на DE — это 200 английская главная."""
        for country in ("ES", "DE", "AT", "FR", "US", "GB", "RU", ""):
            with self.subTest(country=country):
                r = self.client().get("/tenerife/", headers={"CF-IPCountry": country})
                self.assertEqual(r.status_code, 200, country)
                self.assertIn(b'<html lang="en">', r.data, country)

    def test_lang_param_beats_geo_on_tenerife_root(self):
        r = self.client().get("/tenerife/?lang=en", headers={"CF-IPCountry": "ES"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<html lang="en">', r.data)

    def test_lang_param_goes_to_that_locale(self):
        r = self.client().get("/tenerife/?lang=de", headers={"CF-IPCountry": "US"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, "/tenerife/de/")

    def test_lang_param_beats_geo_on_site_root(self):
        r = self.client().get("/?lang=en", headers={"CF-IPCountry": "ES"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/tenerife/?lang=en")
        r = self.client().get("/?lang=de", headers={"CF-IPCountry": "US"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/tenerife/de/?lang=de")

    def test_geo_redirect_sets_no_cookie(self):
        r = self.client().get("/", headers={"CF-IPCountry": "ES"})
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(r.headers.get("Set-Cookie"))
        r = self.client().get("/tenerife/", headers={"CF-IPCountry": "ES"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("Set-Cookie"))

    def test_query_kept_on_geo_redirect(self):
        r = self.client().get("/?utm_source=x", headers={"CF-IPCountry": "FR"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].startswith("/tenerife/fr/"))
        self.assertIn("utm_source=x", r.headers["Location"])

    def test_tenerife_root_keeps_query_and_is_not_a_redirect(self):
        r = self.client().get("/tenerife/?utm_source=x", headers={"CF-IPCountry": "DE"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<html lang="en">', r.data)


if __name__ == "__main__":
    unittest.main()
