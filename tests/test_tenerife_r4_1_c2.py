"""r4.1 c2 (Lead 01.11 00:58 UTC): while TENERIFE_SHOW_FIGURES is off the calculator page answers a TEMPORARY 302 to
/tenerife/ and nothing served links it; calc.js is not served (404); the unused preview.html is gone; the consent line
and the privacy page say «расчёт по вашему запросу» instead of the calculator wording. Fake WhatsApp only."""
import os
import re
import sys
from unittest import mock

from test_tenerife_r4_1 import ROOT, SITE, URLS, Case, build_v3

CALC_URLS = ("/tenerife/calculadora/", "/tenerife/calculadora", "/tenerife/calculadora.html",
             "/tenerife/calculadora/?m2=72&step=queue", "/tenerife/calculadora?x=1", "/tenerife/calculadora.html?a=1",
             "/tenerife-preview/calculadora/", "/tenerife-preview/calculadora/?a=1")
CALC_JS = ("/static/tenerife/site/calc.js", "/static/tenerife/site/calc.js?v=1", "/static/tenerife/site/CALC.JS",
           "/static/tenerife/site/calc.js.gz", "/static/tenerife/calc.js")
CALC_LINK = re.compile(r"calculadora", re.I)


class FlagOff(Case):
    def setUp(self):
        super().setUp()
        os.environ.pop("TENERIFE_SHOW_FIGURES", None)   # Case clears only its KEYS


class CalculadoraRedirectTest(FlagOff):
    def test_temporary_302_to_tenerife(self):
        for url in CALC_URLS:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)          # temporary, never 301 (comes back with the figures)
            self.assertEqual(r.headers["Location"].replace("http://localhost", ""), "/tenerife/", url)

    def test_no_served_page_links_it(self):
        for url in URLS + ["/tenerife/no-such-page/", "/sitemap.xml"]:
            body = self.client.get(url).get_data(as_text=True)
            self.assertIsNone(CALC_LINK.search(body), url)       # menu, CTAs, footer, canonical, OG, JSON-LD

    def test_built_pages_have_no_link(self):
        for f in SITE.glob("*.html"):
            if f.stem not in build_v3.FIGURE_ONLY_PAGES:
                self.assertNotIn("/tenerife/calculadora", f.read_text(encoding="utf-8"), f.name)
        self.assertTrue((SITE / "calculadora.html").is_file())   # kept in the repo, not served

    def test_calc_js_404_and_not_in_static(self):
        for url in CALC_JS:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertFalse((ROOT / "app/static/tenerife/site/calc.js").exists())
        self.assertTrue(build_v3.CALC_JS.is_file())
        for url in URLS:
            self.assertNotIn("calc.js", self.client.get(url).get_data(as_text=True), url)

    def test_guard_404_even_if_calc_js_is_put_back(self):
        t = sys.modules["tenerife"]
        self.assertTrue(t.figures_blocked("/static/tenerife/site/calc.js"))
        self.assertFalse(t.figures_blocked("/static/tenerife/site/site.js"))


class CalculadoraIndexingOnTest(FlagOff):
    env = {"TENERIFE_WHATSAPP": "+440000000000", "TENERIFE_INDEXING": "1"}

    def test_not_in_sitemap(self):
        xml = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/tenerife/proceso/", xml)
        self.assertNotIn("calculadora", xml)
        for url in URLS:
            self.assertIsNone(CALC_LINK.search(self.client.get(url).get_data(as_text=True)), url)


class CalculadoraFlagOnTest(Case):
    env = {"TENERIFE_WHATSAPP": "+440000000000", "TENERIFE_SHOW_FIGURES": "1"}

    def test_served_again_with_flag(self):
        self.assertEqual(self.client.get("/tenerife/calculadora/").status_code, 200)
        self.assertEqual(self.client.get("/tenerife/calculadora").status_code, 301)
        self.assertFalse(sys.modules["tenerife"].figures_blocked("/static/tenerife/site/calc.js"))


class PreviewTemplateGoneTest(FlagOff):
    def test_deleted_and_unused(self):
        self.assertFalse((ROOT / "app/templates/tenerife/preview.html").exists())
        for f in (ROOT / "app").rglob("*.py"):
            self.assertNotIn("preview.html", f.read_text(encoding="utf-8"), f.name)
        self.assertEqual(self.client.get("/tenerife-preview/").status_code, 301)


class ConsentWordingTest(FlagOff):
    def test_consent_lead_wording_on_every_form(self):
        n = 0
        for url in URLS:
            body = self.client.get(url).get_data(as_text=True)
            for span in re.findall(r'id="wl-consent"[^>]*><span>(.*?)</span>', body):
                n += 1
                self.assertIn(build_v3.CONSENT_NEW, span, url)
                self.assertNotIn("калькулятор", span, url)
        self.assertEqual(n, 12)

    def test_privacy_has_no_calculator_wording(self):
        body = self.client.get("/tenerife/privacy/").get_data(as_text=True)
        self.assertNotIn("калькулятор", body.lower())
        for _old, new in build_v3.PRIVACY_WORDING:
            self.assertEqual(body.count(new), 1, new)
        self.assertEqual(body.count("расчёт по вашему запросу"), 2)
        self.assertEqual(body.count("Расчёт по вашему запросу"), 1)

    def test_no_get_my_calculation_button_served(self):
        for url in URLS:
            self.assertNotIn("Получить мой расчёт", self.client.get(url).get_data(as_text=True), url)

    def test_flag_on_build_keeps_the_copy(self):
        with mock.patch.dict(os.environ, {"TENERIFE_WHATSAPP": "+440000000000"}):
            shown = build_v3.build(write=False, show_figures=True)[0]
        self.assertIn(build_v3.CONSENT_OLD, shown["index"])
        self.assertIn('href="/tenerife/calculadora/"', shown["index"])
