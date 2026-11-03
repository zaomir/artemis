"""Public Tenerife navigation and investor journey (founder plan, 2026-11-03).

These checks exercise served HTML, redirect destinations and a locally saved form
submission. The notification function is mocked; nothing leaves the test process.
The offer snapshot freezes the pre-change calculations so an information-
architecture change cannot silently change the economics.
"""
import importlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts/tenerife_site_build"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
LOCALES = ("en", "es", "de", "fr", "ru")
PRIMARY = ("producto", "inversores", "norte", "construccion", "equipo")
BASE = "https://artemisresort.com"


def route(locale, name):
    prefix = "/tenerife/" + ("" if locale == "en" else locale + "/")
    return prefix if name == "index" else prefix + name + "/"


class Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def nodes(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.nodes(tag)

    def by_id(self, value):
        return next((n for n in self.nodes() if n.attrs.get("id") == value), None)

    def text(self):
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        current = self.current
        while current is not self.root:
            if current.tag == tag:
                self.current = current.parent
                return
            current = current.parent

    def handle_data(self, data):
        self.current.children.append(data)


def links(node):
    return [n.attrs.get("href", "") for n in node.nodes("a")]


def has_class(node, name):
    return name in node.attrs.get("class", "").split()


class InvestorArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TENERIFE_INDEXING": "1", "TENERIFE_WHATSAPP": "+440000000000"})
        self.env.start()
        import app as artemis_app
        self.app = importlib.reload(artemis_app)
        self.app.DB = str(Path(self.tmp.name) / "leads.db")
        self.client = self.app.app.test_client()
        self.tenerife = sys.modules["tenerife"]

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def page(self, locale, name):
        url = route(locale, name)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return Document(response.get_data(as_text=True)).root

    def test_new_routes_have_matching_canonical_hreflang_and_conditional_sitemap(self):
        from build_v3 import PAGES
        names = {name for _, name in PAGES}
        self.assertIn("inversores", names)
        self.assertIn("equipo", names)
        self.assertNotIn("acciones", names)
        for enabled in ("1", "0"):
            with mock.patch.dict(os.environ, {"TENERIFE_INDEXING": enabled}):
                sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
                locations = re.findall(r"<loc>(.*?)</loc>", sitemap)
                for locale in LOCALES:
                    for name in ("inversores", "equipo"):
                        url = route(locale, name)
                        response = self.client.get(url)
                        self.assertEqual(response.status_code, 200, url)
                        body = response.get_data(as_text=True)
                        doc = Document(body).root
                        headlinks = [n.attrs for n in doc.nodes("link")]
                        canonical = [n.get("href") for n in headlinks if n.get("rel") == "canonical"]
                        self.assertEqual(canonical, [BASE + url], url)
                        alternates = {n["hreflang"]: n["href"] for n in headlinks if "hreflang" in n}
                        self.assertEqual(alternates, {**{loc: BASE + route(loc, name) for loc in LOCALES},
                                                      "x-default": BASE + route("en", name)}, url)
                        self.assertEqual(BASE + url in locations, enabled == "1", url)
                        self.assertEqual("noindex" in response.headers.get("X-Robots-Tag", ""), enabled != "1", url)
                        self.assertEqual("noindex" in body, enabled != "1", url)
                self.assertFalse(any("/acciones" in loc for loc in locations))

    def test_legacy_payment_urls_redirect_once_to_final_route_and_keep_query(self):
        query = "utm_source=qa&view=72%20m2"
        for locale in LOCALES:
            prefixes = ["/tenerife/" + ("" if locale == "en" else locale + "/"),
                        "/tenerife-preview/" + ("" if locale == "en" else locale + "/")]
            if locale == "en":
                prefixes.extend(["/tenerife/en/", "/tenerife-preview/en/"])
            for prefix in prefixes:
                for ending in ("acciones/", "acciones", "acciones.html"):
                    source = prefix + ending + "?" + query
                    response = self.client.get(source)
                    self.assertEqual(response.status_code, 301, source)
                    dest = urlsplit(response.headers["Location"])
                    self.assertEqual((dest.path, dest.query), (route(locale, "inversores"), query), source)
                    final = self.client.get(response.headers["Location"])
                    self.assertEqual(final.status_code, 200, source)
                    self.assertNotIn("Location", final.headers, source)

    def test_primary_and_mobile_menus_have_same_five_destinations_and_calculation_cta(self):
        for locale in LOCALES:
            for name in ("index", "inversores", "equipo"):
                doc = self.page(locale, name)
                header = next(doc.nodes("header"))
                desktop = next(n for n in header.nodes("nav") if has_class(n, "nav"))
                mobile = header.by_id("sheet")
                want = [route(locale, slug) for slug in PRIMARY] + ["#ochered"]
                for menu in (desktop, mobile):
                    got = [href for href in links(menu) if not href.startswith(BASE)]
                    self.assertEqual(got, want, (locale, name))
                languages = next(n for n in header.nodes("nav") if has_class(n, "langs"))
                self.assertEqual([n.text().strip() for n in languages.nodes("a")], ["EN", "ES", "DE", "FR"])
                self.assertFalse(any(n.text().strip() == "RU" for n in header.nodes("a")))
                footer = next(doc.nodes("footer"))
                russian = [n for n in footer.nodes() if has_class(n, "lang-ru")]
                self.assertEqual(len(russian), 1)
                self.assertEqual([n.text().strip() for n in russian[0].nodes("a")], ["RU"])

    def test_grouped_footer_keeps_all_secondary_pages_without_old_payment_links(self):
        from build_v3 import PAGES
        for locale in LOCALES:
            doc = self.page(locale, "index")
            footer = next(doc.nodes("footer"))
            pages = footer.by_id("footer-pages")
            groups = [n for n in pages.nodes() if has_class(n, "f-pages__group")]
            self.assertEqual(len(groups), 4, locale)
            self.assertTrue(all(any(n.nodes("h3")) and any(n.nodes("ul")) for n in groups), locale)
            actual = links(pages)
            self.assertCountEqual(actual, [route(locale, name) for _, name in PAGES] +
                                  [route(locale, name) for name in ("impressum", "privacy")], locale)
            for _, name in PAGES:
                for href in links(self.page(locale, name)):
                    self.assertNotRegex(urlsplit(href).path, r"/acciones(?:/|\.html)?$", (locale, name, href))

    def test_investor_deep_links_and_old_fragment_destinations_survive(self):
        required = {"overview", "comparison", "price-stages", "outcomes", "calculate", "control", "documents", "ochered"}
        for locale in LOCALES:
            doc = self.page(locale, "inversores")
            allids = [n.attrs["id"] for n in doc.nodes() if "id" in n.attrs]
            self.assertEqual(len(allids), len(set(allids)), locale)
            self.assertTrue(required <= set(allids), (locale, required - set(allids)))
            aliases = {"s1": "comparison", "s2": "overview", "s10": "overview",
                       "s3": "price-stages", "s4": "price-stages", "s5": "outcomes",
                       "s6": "outcomes", "s7": "outcomes", "s8": "outcomes", "s11": "outcomes",
                       "s9": "documents", "s12": "documents", "s13": "documents"}
            for old, target in aliases.items():
                alias = doc.by_id(old)
                self.assertIsNotNone(alias, (locale, old))
                self.assertNotIn("hidden", alias.attrs, (locale, old))
                while alias.tag != "section":
                    alias = alias.parent
                self.assertEqual(alias.attrs.get("aria-labelledby"), target, (locale, old))
            calculation_section = doc.by_id("calculate")
            while calculation_section.tag != "section":
                calculation_section = calculation_section.parent
            self.assertIsNotNone(calculation_section.by_id("calc-form"), locale)

    def test_full_calculator_choices_model_results_and_payload_match_standalone(self):
        for locale in LOCALES:
            pages = [self.page(locale, slug) for slug in ("inversores", "calculadora")]
            signatures = []
            for doc in pages:
                controls = doc.by_id("calc-form")
                self.assertIsNotNone(controls)
                signature = [(n.tag, n.attrs) for n in controls.nodes() if n.tag in {"input", "select", "option"}]
                self.assertEqual({n.attrs.get("name") for n in controls.nodes("input")}, {"type", "m2"})
                model = json.loads(doc.by_id("cs-model").text())
                results = [(n.attrs["data-k"], n.text().strip()) for n in doc.by_id("calc-res").nodes() if "data-k" in n.attrs]
                form = doc.by_id("wl-form")
                hidden = {n.attrs["name"]: n.attrs.get("value", "") for n in form.nodes("input") if n.attrs.get("type") == "hidden"}
                self.assertEqual(set(hidden), {"page", "calc_m2", "calc_step", "calc_pay"})
                self.assertEqual(form.attrs["action"], "/api/tenerife/waitlist")
                signatures.append((signature, model, results, {k: v for k, v in hidden.items() if k != "page"}))
            self.assertEqual(*signatures, locale)

    def test_investor_form_saves_the_selected_calculation_with_local_notification_mock(self):
        import tenerife_calc
        for number, locale in enumerate(LOCALES):
            doc = self.page(locale, "inversores")
            form = doc.by_id("wl-form")
            data = {n.attrs["name"]: n.attrs.get("value", "") for n in form.nodes("input") if n.attrs.get("type") == "hidden"}
            data.update(name="QA Local", contact="qa@example.com", language=locale, consent=True,
                        calc_m2="72", calc_step="early", calc_pay="now", website="")
            self.assertEqual(data["page"], route(locale, "inversores"))
            with mock.patch.object(self.tenerife, "notify_lead") as notify:
                response = self.client.post(form.attrs["action"], json=data,
                                            environ_base={"REMOTE_ADDR": f"203.0.113.{number + 1}"})
            self.assertEqual(response.get_json(), {"ok": True}, locale)
            with sqlite3.connect(self.app.DB) as conn:
                conn.row_factory = sqlite3.Row
                row = dict(conn.execute("SELECT * FROM tenerife_waitlist ORDER BY id DESC LIMIT 1").fetchone())
            self.assertEqual((row["page"], row["calc_status"], row["calc_m2"], row["calc_step"], row["calc_pay"],
                              row["calc_amount"], row["calc_month_eur"]),
                             (route(locale, "inversores"), "ok", 72, "early", "now", 169344, None), locale)
            self.assertEqual(row["calc_model_version"], tenerife_calc.load_model()["version"])
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["calc"]["calc_amount"], 169344)

    def test_contact_validation_rejects_garbage_and_accepts_supported_reply_channels(self):
        base = {"name": "QA Local", "language": "en", "consent": True, "page": route("en", "inversores")}
        with mock.patch.object(self.tenerife, "notify_lead") as notify:
            for contact in ("abcde", "@@@@@", "not a contact", "bad@@example.com"):
                response = self.client.post("/api/tenerife/waitlist", json={**base, "contact": contact})
                self.assertEqual(response.status_code, 400, contact)
                self.assertEqual(response.get_json()["field"], "contact", contact)
            notify.assert_not_called()
            for number, contact in enumerate(("qa@example.com", "+44 0000 000000", "@artemis_qa",
                                               "https://t.me/artemis_qa", "t.me/artemis_qa")):
                response = self.client.post("/api/tenerife/waitlist", json={**base, "contact": contact},
                                            environ_base={"REMOTE_ADDR": f"203.0.113.{number + 20}"})
                self.assertEqual(response.get_json(), {"ok": True}, contact)
            self.assertEqual(notify.call_count, 5)
        with sqlite3.connect(self.app.DB) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tenerife_waitlist").fetchone()[0], 5)

    def test_missing_tenerife_pages_keep_404_status_with_localized_recovery(self):
        for locale in LOCALES:
            url = route(locale, "qa-unknown-page")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            body = response.get_data(as_text=True)
            self.assertIn(f'<html lang="{locale}">', body, url)
            self.assertIn("Artemis", body, url)
            self.assertIn("noindex", response.headers.get("X-Robots-Tag", ""), url)
            self.assertIn(route(locale, "index"), links(Document(body).root), url)

    def test_shortened_pages_do_not_repeat_long_paragraphs_or_keep_old_generated_html(self):
        for locale in LOCALES:
            for name in ("index", "inversores", "equipo"):
                main = next(self.page(locale, name).nodes("main"))
                paragraphs = [re.sub(r"\s+", " ", n.text()).strip() for n in main.nodes("p")]
                substantial = [p for p in paragraphs if len(p) >= 140]
                self.assertEqual(len(substantial), len(set(substantial)), (locale, name))
        self.assertEqual(list((ROOT / "app/tenerife_site").rglob("acciones.html")), [])


class ApprovedExitModelTest(unittest.TestCase):
    def test_approved_cash_exit_examples_match_financial_model(self):
        import tenerife_calc
        model = tenerife_calc.load_model()
        for shares, capital, proceeds, income in [(48, 112896, 146204, 33308),
                                                  (72, 169344, 219305, 49961),
                                                  (100, 235200, 304591, 69391)]:
            calc = tenerife_calc.compute(shares, "early", "now", model)
            self.assertEqual((calc["calc_amount"], calc["calc_exit_amount"], calc["calc_income"]),
                             (capital, proceeds, income))
            self.assertEqual((calc["calc_exit_months"], calc["calc_target_pct"], calc["calc_month_eur"]),
                             (36, 9, None))


if __name__ == "__main__":
    unittest.main()
