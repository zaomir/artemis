"""Локали сайта Тенерифе (2026-11-02): EN в корне /tenerife/, RU/ES/DE/FR — под своим префиксом.

Проверяет то, чего не видит русский набор: каждая локаль собирается в свой каталог, даёт страницы из PAGES + legal,
ставит свой `<html lang>`, canonical и полный набор hreflang на пять языков, а меню ведёт внутрь своей локали.
Плюс маршруты Flask: корень = EN 200, /tenerife/en/ и /tenerife/en/<page>/ → 301 в корень (P1-02),
canonical и hreflang en/x-default указывают на 200 EN-URL (не на редирект в DE), неизвестная локаль → 404.
"""
import importlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "tenerife_site_build"
SITE = ROOT / "app" / "tenerife_site"
LOCALES = ("ru", "en", "es", "de", "fr")
LEGAL = ("impressum", "privacy")
BASE = "https://artemisresort.com"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(BUILD))

from build_v3 import PAGES  # noqa: E402


def prefix(locale):
    return "" if locale == "en" else f"{locale}/"


def url_of(locale, name):
    p = prefix(locale)
    return f"/tenerife/{p}" if name == "index" else f"/tenerife/{p}{name}/"


class FiveBuildsTest(unittest.TestCase):
    """Каждая локаль собирается отдельной командой в свой каталог: страницы PAGES + impressum + privacy + _notice."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = {}
        for locale in LOCALES:
            out = Path(cls.tmp.name) / locale
            r = subprocess.run(
                [sys.executable, str(BUILD / "build_v3.py")],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "TENERIFE_WHATSAPP": "+440000000000",
                     "TENERIFE_LOCALE": locale, "TENERIFE_OUT_DIR": str(out)},
            )
            if r.returncode != 0:
                raise AssertionError(f"build {locale} failed:\n{r.stdout}\n{r.stderr}")
            cls.out[locale] = out

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, locale, name):
        return (self.out[locale] / f"{name}.html").read_text(encoding="utf-8")

    def test_all_content_pages_and_legal(self):
        want = {f"{name}.html" for _f, name in PAGES} | {f"{n}.html" for n in LEGAL} | {"_notice.html", "_404.html", "actualizaciones.html"}
        for locale in LOCALES:
            got = {p.name for p in self.out[locale].glob("*.html")}
            self.assertEqual(got, want, locale)
            self.assertEqual(len([n for n in got if not n.startswith("_") and n not in {f"{x}.html" for x in LEGAL}]),
                             len(PAGES)+1, locale)
            self.assertTrue((self.out[locale]/'actualizaciones'/'concept-search.html').is_file(), locale)

    def test_lang_oglocale_canonical_hreflang(self):
        for locale in LOCALES:
            for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
                page = self.page(locale, name)
                url = url_of(locale, name)
                self.assertIn(f'<html lang="{locale}">', page, (locale, name))
                self.assertIn(f'<link rel="canonical" href="{BASE}{url}">', page, (locale, name))
                head = page[:page.index("</head>")]
                alts = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', head))
                self.assertEqual(list(alts), ["en", "es", "de", "fr", "ru", "x-default"], (locale, name))
                for other in LOCALES:
                    self.assertEqual(alts[other], BASE + url_of(other, name), (locale, name, other))
                self.assertEqual(alts["x-default"], alts["en"], (locale, name))

    def test_menu_and_switcher(self):
        for locale in LOCALES:
            page = self.page(locale, "index")
            head = page[:page.index("</head>")]
            nav = page[page.index('<header'):page.index("</header>")]
            for name in ("producto", "inversores", "norte", "construccion", "equipo"):
                self.assertIn(f'href="{url_of(locale, name)}"', nav, (locale, name))
            self.assertIn('href="#ochered"', nav, locale)
            footer = page[page.index("<footer"):page.index("</footer>")]
            for _f, name in PAGES:
                self.assertIn(f'href="{url_of(locale, name)}"', footer, (locale, name))
            # EN-ссылка несёт ?lang=en: она сильнее гео-редиректа по стране (см. tests/test_tenerife_geo.py)
            self.assertIn(f'<a href="{BASE}/tenerife/?lang=en"', nav, locale)
            self.assertRegex(nav, r'<a href="https://artemisresort\.com/tenerife/\?lang=en"[^>]*>EN</a>', locale)
            for other in ("es", "de", "fr"):
                self.assertRegex(nav, rf'<a href="{BASE}/tenerife/{other}/"( aria-current="true")?>', (locale, other))
            self.assertIn('class="lang-ru"', page, locale)   # русская версия — тихо в подвале
            self.assertTrue(head)

    def test_no_cyrillic_left_except_the_russian_link(self):
        """Перевод без русских слов — включая форму записи, калькулятор и alt-тексты (03.11.2026).
        Ссылка на русскую версию подписана «RU» (решение основателя 03.11.2026), поэтому кириллица
        в разметке не остаётся вовсе; исключение — название языка в списке языка общения."""
        for locale in ("en", "es", "de", "fr"):
            for _f, name in PAGES:
                body = self.page(locale, name).split("<body>", 1)[1]
                body = re.sub(r'<option[^>]*>.*?</option>', " ", body, flags=re.S)   # названия языков в списке
                text = re.sub(r"<[^>]+>", " ", body)   # только текстовые узлы, без alt/title
                cyr = re.findall(r"[А-Яа-яЁё]{2,}", text)
                self.assertEqual(cyr, [], (locale, name, cyr[:5]))

    def test_alts_and_team_photos_are_translated(self):
        """alt-тексты кадров и фото команды — на языке страницы, не русские."""
        for locale in ("en", "es", "de", "fr"):
            for _f, name in PAGES:
                page = self.page(locale, name)
                alts = re.findall(r'aria-label="([^"]*)"', page)
                cyr = [a for a in alts if re.search(r"[А-Яа-яЁё]{2,}", a)]
                self.assertEqual(cyr, [], (locale, name, cyr[:3]))

    def test_interface_strings_are_localised(self):
        from locale_cfg import UI, NAV_UI
        for locale in LOCALES:
            ui = UI[locale]
            page = self.page(locale, "index")
            self.assertIn(f'<a class="skip" href="#main">{ui["skip"]}</a>', page, locale)
            self.assertIn(f'<span class="burger__icon" aria-hidden="true"></span>{ui["menu"]}</a>', page, locale)
            self.assertIn('id="footer-pages"', page, locale)
            self.assertIn(f'<h3>{NAV_UI[locale]["documents"]}</h3>', page, locale)


class LocaleRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ("TENERIFE_WHATSAPP", "TENERIFE_INDEXING")}
        os.environ["TENERIFE_INDEXING"] = "1"
        os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TENERIFE_INDEXING", None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def test_every_locale_answers_200(self):
        for locale in LOCALES:
            for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
                url = url_of(locale, name)
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)
                self.assertIn(f'<html lang="{locale}">', r.get_data(as_text=True), url)

    def test_root_is_english_and_en_prefix_redirects(self):
        r = self.client.get("/tenerife/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<html lang="en">', r.get_data(as_text=True))
        r = self.client.get("/tenerife/en/")
        self.assertEqual((r.status_code, r.headers["Location"].rsplit("/tenerife", 1)[1]), (301, "/"))

    def test_en_prefixed_pages_redirect_to_unprefixed(self):
        """P1-02: 14 URL /tenerife/en/* больше не 404 — один 301 на рабочий unprefixed URL (в т.ч. без слэша/.html)."""
        for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
            if name == "index":
                continue   # /tenerife/en/ проверяется ниже
            target = url_of("en", name)
            for src in (f"/tenerife/en/{name}/", f"/tenerife/en/{name}", f"/tenerife/en/{name}.html"):
                r = self.client.get(src)
                self.assertEqual(r.status_code, 301, src)
                self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, target, src)
            self.assertEqual(self.client.get(target).status_code, 200, target)
        for src in ("/tenerife/en/", "/tenerife/en"):
            r = self.client.get(src)
            self.assertEqual(r.status_code, 301, src)
            self.assertEqual(urllib.parse.urlsplit(r.headers["Location"]).path, "/tenerife/", src)
        # query string сохраняется, как и у остальных 301
        r = self.client.get("/tenerife/en/simon/?utm_source=x")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers["Location"], "/tenerife/simon/?utm_source=x")

    def test_en_unknown_page_is_404_not_a_redirect_into_404(self):
        for src in ("/tenerife/en/nope/", "/tenerife/en/nope", "/tenerife/en/nope.html"):
            self.assertEqual(self.client.get(src).status_code, 404, src)

    def test_en_hreflang_and_canonical_resolve_to_200_english_urls(self):
        """P1-02: canonical ведёт на 200-версию своей локали, hreflang en/x-default — на 200 EN-URL в корне,
        а не на 302 в DE. Раньше /tenerife/ уводил в /tenerife/de/, и весь hreflang en указывал на редирект."""
        for locale in ("en",) + LOCALES:
            for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
                url = url_of(locale, name)
                page = self.client.get(url).get_data(as_text=True)
                head = page[:page.index("</head>")]
                canonical = re.search(r'<link rel="canonical" href="([^"]+)">', head)
                self.assertIsNotNone(canonical, (locale, name))
                self.assertEqual(canonical.group(1), BASE + url, (locale, name))
                r = self.client.get(urllib.parse.urlsplit(canonical.group(1)).path)
                self.assertEqual(r.status_code, 200, (locale, name))
                self.assertIn(f'<html lang="{locale}">', r.get_data(as_text=True), (locale, name))
                alts = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', head))
                en_url = BASE + url_of("en", name)
                self.assertEqual(alts["en"], en_url, (locale, name))
                self.assertEqual(alts["x-default"], en_url, (locale, name))
                for target in (alts["en"], alts["x-default"]):
                    path = urllib.parse.urlsplit(target).path
                    r = self.client.get(path)
                    self.assertEqual(r.status_code, 200, (locale, name, path))
                    self.assertIn('<html lang="en">', r.get_data(as_text=True), (locale, name, path))

    def test_english_internal_links_are_unprefixed(self):
        """P1-02: логотип, Home, Back и меню EN ведут на /tenerife/..., ни одной ссылки /tenerife/en/."""
        for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
            page = self.client.get(url_of("en", name)).get_data(as_text=True)
            hrefs = re.findall(r'href="(/tenerife/[^"#?]*)"', page)
            self.assertTrue(hrefs, name)
            for href in hrefs:
                self.assertFalse(href.startswith("/tenerife/en/"), (name, href))
            self.assertIn('class="brand" href="/tenerife/"', page, name)
            self.assertIn('href="/tenerife/impressum/"', page, name)
            self.assertIn('href="/tenerife/privacy/"', page, name)
            for _f2, other in PAGES:
                self.assertIn(f'href="{url_of("en", other)}"', page, (name, other))

    def test_unknown_locale_is_404(self):
        for url in ("/tenerife/xx/", "/tenerife/xx/norte/", "/tenerife/xx/norte"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_sitemap_lists_every_locale(self):
        locs = re.findall(r"<loc>([^<]+)</loc>", self.client.get("/sitemap.xml").get_data(as_text=True))
        for locale in LOCALES:
            for _f, name in list(PAGES) + [("", n) for n in LEGAL]:
                self.assertIn(BASE + url_of(locale, name), locs, (locale, name))
        self.assertEqual(len(locs), len(set(locs)))


if __name__ == "__main__":
    unittest.main()
