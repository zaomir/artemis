"""r4.1: no price / dividend figures and no investor page on the published /tenerife/ pages until the founder approves
them (preview rule). The figures come back only with TENERIFE_SHOW_FIGURES=1 at build time. Fake WhatsApp only."""
import html as htmllib
import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
os.environ.setdefault("TENERIFE_WHATSAPP", "+440000000000")

import build_v3  # noqa: E402

SITE = ROOT / "app" / "tenerife_site"
URLS = ([("/tenerife/" if n == "index" else f"/tenerife/{n}/") for _f, n in build_v3.PAGES
         if n not in build_v3.FIGURE_ONLY_PAGES]   # r4.1 c2: calculadora -> 302, see test_tenerife_r4_1_c2.py
        + ["/tenerife/impressum/", "/tenerife/privacy/", "/tenerife/gracias/"])
SP = "[ \u00a0\u202f]?"
FORBIDDEN = [rf"87{SP}€", "€/м²", "€/m²", r"%\s*годовых", rf"2{SP}950", rf"3{SP}850",
             rf"\d{SP}€", rf"€{SP}\d", rf"\d{SP}евро\b",
             r"(?i)дивиденд[^.<]{0,40}\d+(?:[,.]\d+)?\s*%", r"(?i)\d+(?:[,.]\d+)?\s*%[^.<]{0,40}(?:дивиденд|доходн)",
             r"(?i)дивиденд[^.<]{0,25}\d{2,}", r"(?i)доходност\w*[^.<]{0,25}\d"]
INVESTOR = re.compile(r"/tenerife/(?:inversores|investors|inversiones|invest)\b|>\s*Инвесторам\s*<")
KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID", "TENERIFE_WHATSAPP", "TENERIFE_INDEXING")


def text_of(page):
    """Visible text + attribute values + JSON-LD, entities resolved, NBSP kept (the grep runs on both forms)."""
    attrs = " ".join(re.findall(r'(?:content|alt|title|aria-label|value)="([^"]*)"', page))
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", page) + " " + attrs)


class Case(unittest.TestCase):
    env = {"TENERIFE_WHATSAPP": "+440000000000"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        clean = {k: v for k, v in os.environ.items() if k not in KEYS}
        p = mock.patch.dict(os.environ, {**clean, **self.env}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        n = mock.patch.object(sys.modules["tenerife"], "notify_lead")
        n.start()
        self.addCleanup(n.stop)


class NoFiguresServedTest(Case):
    def test_sixteen_pages_have_no_figures(self):
        self.assertEqual(len(URLS), 15)   # r4.1 c2: calculadora -> 302 (not served)
        for url in URLS:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            t = text_of(r.get_data(as_text=True))
            for rx in FORBIDDEN:
                for form in (t, t.replace("\u00a0", " ").replace("\u202f", " ")):
                    self.assertIsNone(re.search(rx, form), f"{url}: {rx}")

    def test_committed_files_have_no_figures_or_calculator(self):
        files = sorted(SITE.glob("*.html"))
        self.assertEqual(len(files), 16)
        for f in files:
            page = f.read_text(encoding="utf-8")
            for rx in FORBIDDEN:
                self.assertIsNone(re.search(rx, text_of(page)), f"{f.name}: {rx}")
            for marker in ('class="ladder', 'id="calc"', "cs-model", "calc.js", 'name="calc_'):
                self.assertNotIn(marker, page, f"{f.name}: {marker}")
            build_v3.check_no_figures(f.stem, page)   # the build's own guard agrees

    def test_bonus_and_tax_percent_stay(self):
        # not figures of the preview rule: payment bonuses and taxes are kept as written
        self.assertIn("бонус 10%", self.client.get("/tenerife/").get_data(as_text=True))
        self.assertIn("IGIC 7%", self.client.get("/tenerife/proceso/").get_data(as_text=True))


class InvestorPageTest(Case):
    def test_not_served(self):
        for url in ("/tenerife/inversores/", "/tenerife/inversores", "/tenerife/inversores.html",
                    "/tenerife/investors/", "/tenerife/inversiones/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 404, url)
        self.assertFalse(set(sys.modules["tenerife"].UNPUBLISHED_PAGES) & set(sys.modules["tenerife"].SITE_PAGES))
        self.assertFalse((SITE / "inversores.html").exists())

    def test_guard_holds_even_if_listed(self):
        t = sys.modules["tenerife"]
        with mock.patch.object(t, "SITE_PAGES", t.SITE_PAGES + ("inversores",)):
            self.assertEqual(self.client.get("/tenerife/inversores/").status_code, 404)
            self.assertEqual(self.client.get("/tenerife/inversores").status_code, 404)
            self.assertNotIn("inversores", "".join(self.mod.sitemap_paths()))

    def test_not_linked(self):
        for url in URLS:
            page = self.client.get(url).get_data(as_text=True)
            self.assertIsNone(INVESTOR.search(page), url)


class InvestorSitemapTest(Case):
    env = {"TENERIFE_WHATSAPP": "+440000000000", "TENERIFE_INDEXING": "1"}

    def test_not_in_sitemap(self):
        xml = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/tenerife/proceso/", xml)
        self.assertNotIn("invers", xml)


class FigureDataNotServedTest(Case):
    STATIC = ROOT / "app" / "static"

    def test_model_json_404_with_flag_off(self):
        for url in ("/static/tenerife/site/model.json", "/static/tenerife/site/MODEL.JSON",
                    "/static/tenerife/model.json", "/static/tenerife/site/model.json.gz"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_guard_runs_before_static_even_if_file_is_back(self):
        # a model.json put back under static (nginx would serve it from disk: deploy/nginx-…origin.conf location
        # /static/) must still be 404 from Flask with the flag off; the repo test below keeps it off the disk
        target = self.STATIC / "tenerife" / "site" / "model.json"
        self.assertFalse(target.exists())
        target.write_text("{}", encoding="utf-8")
        self.addCleanup(target.unlink)
        self.assertEqual(self.client.get("/static/tenerife/site/model.json").status_code, 404)
        with mock.patch.dict(os.environ, {"TENERIFE_SHOW_FIGURES": "1"}):
            self.assertEqual(self.client.get("/static/tenerife/site/model.json").status_code, 200)

    def test_no_figure_file_under_static_and_none_referenced(self):
        self.assertEqual(sorted(p.name for p in (self.STATIC / "tenerife").rglob("*.json")), [])
        self.assertTrue(build_v3.MODEL.is_file())
        self.assertNotIn("static", build_v3.MODEL.relative_to(ROOT).parts)
        for f in SITE.glob("*.html"):
            self.assertNotIn("model.json", f.read_text(encoding="utf-8"), f.name)

    def test_served_static_tree_has_no_figures(self):
        rx = re.compile(rf"87{SP}€|2{SP}950|3{SP}850|€/м²|€/m²|\b2950\b|\b3850\b")
        checked = 0
        for f in sorted(self.STATIC.rglob("*")):
            if not f.is_file() or f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".ico",
                                                         ".woff", ".woff2", ".ttf", ".pdf"):
                continue
            url = "/static/" + f.relative_to(self.STATIC).as_posix()
            r = self.client.get(url)
            body = r.get_data(as_text=True) if r.status_code == 200 else ""
            r.close()
            disk = f.read_text(encoding="utf-8", errors="ignore")   # what nginx would serve
            for src in (body, disk):
                self.assertIsNone(rx.search(htmllib.unescape(src)), url)
            checked += 1
        self.assertGreater(checked, 5)


class StructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {f.stem: f.read_text(encoding="utf-8") for f in SITE.glob("*.html")}

    def test_no_empty_sections_or_dangling_headings(self):
        for name, page in self.pages.items():
            main = re.search(r"<main.*?</main>", page, re.S).group(0)
            for sec in re.findall(r"<section\b[^>]*>(.*?)</section>", main, re.S):
                rest = re.sub(r"<h[1-3][^>]*>.*?</h[1-3]>", "", sec, flags=re.S)
                self.assertTrue(re.sub(r"<(?!img|h1)[^>]+>|\s", "", rest) or "<h1" in sec, f"{name}: {sec[:120]}")
            # a heading followed directly by the next heading = dangling
            self.assertIsNone(re.search(r"</h[23]>\s*(?:</div>\s*)*(?:</section>\s*)*<section[^>]*>\s*<div[^>]*>\s*<h[23]",
                                        main), name)
            self.assertIsNone(re.search(r"<(p|li|ul|ol|table|tbody)(?![^>]*\s(?:id|hidden)\b)[^>]*>\s*</\1>", main), name)

    def test_anchors_resolve(self):
        for name, page in self.pages.items():
            ids = set(re.findall(r'\sid="([^"]+)"', page))
            for ref in re.findall(r'href="#([^"]+)"', page):
                self.assertIn(ref, ids, f"{name}: #{ref}")
            for ref in re.findall(r'aria-(?:labelledby|controls|describedby)="([^"]+)"', page):
                for i in ref.split():
                    self.assertIn(i, ids, f"{name}: {i}")

    def test_internal_links_resolve(self):
        published = {"index"} | set(n for _f, n in build_v3.PAGES) | {"impressum", "privacy"}
        for name, page in self.pages.items():
            for ref in re.findall(r'href="/tenerife/([a-z]*)/?(?:[#?][^"]*)?"', page):
                self.assertIn(ref or "index", published, f"{name}: /tenerife/{ref}/")


class FlagTest(unittest.TestCase):
    def test_default_off_and_flag_on_restores_the_figures(self):
        with mock.patch.dict(os.environ, {"TENERIFE_WHATSAPP": "+440000000000"}):
            os.environ.pop("TENERIFE_SHOW_FIGURES", None)
            self.assertFalse(build_v3.show_figures_env())
            hidden, rep = build_v3.build(write=False)
            for name, out in hidden.items():
                self.assertEqual(out, (SITE / f"{name}.html").read_text(encoding="utf-8"), name)
            self.assertTrue(rep["acciones"]["figures_hidden"])
            with mock.patch.dict(os.environ, {"TENERIFE_SHOW_FIGURES": "1"}):
                self.assertTrue(build_v3.show_figures_env())
                shown, rep_on = build_v3.build(write=False)
        self.assertIn("2\u00a0950", shown["acciones"].replace("2 950", "2\u00a0950"))
        self.assertIn("87", shown["alquiler"])
        self.assertIn('id="calc"', shown["calculadora"])
        self.assertEqual(rep_on["acciones"]["figures_hidden"], [])

    def test_copy_sources_untouched(self):
        self.assertEqual(build_v3.combined_sha(), build_v3.COPY_SHA256)
        self.assertIn("87 €", (build_v3.COPY / "06_arenda.md").read_text(encoding="utf-8").replace("\u00a0", " "))

    def test_filter_units(self):
        md = ("# Тест: от 2 950 € за м²\n\nПервое предложение. Цена — 3 100 €.\n\n## Пустая\n\n"
              "Дивиденд — 2,9% к вложенному.\n\n## Таблица\n\nСмотрите:\n\n| Ступень | € за м² |\n|---|---|\n"
              "| Очередь | 2 950 |\n\nКонец.\n")
        out = build_v3.hide_figures_md(md)
        self.assertIn("# Тест\n", out)
        self.assertIn("Первое предложение.", out)
        for gone in ("3 100", "## Пустая", "2,9", "2 950", "Смотрите:", "| Ступень"):
            self.assertNotIn(gone, out, gone)
        self.assertIn("Конец.", out)
        self.assertIsNone(build_v3.check_no_figures("x", "<main><p>бонус 10%</p></main>"))
        with self.assertRaises(build_v3.BuildError):
            build_v3.check_no_figures("x", "<main><p>87 € на акцию</p></main>")
        with self.assertRaises(build_v3.BuildError):
            build_v3.check_no_figures("x", '<main><a href="/tenerife/inversores/">x</a></main>')


if __name__ == "__main__":
    unittest.main()
