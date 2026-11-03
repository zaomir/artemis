"""Локали сайта Тенерифе (2026-11-02): EN в корне /tenerife/, RU/ES/DE/FR — под своим префиксом.

Проверяет то, чего не видит русский набор: каждая локаль собирается в свой каталог, даёт 13 страниц + legal,
ставит свой `<html lang>`, canonical и полный набор hreflang на пять языков, а меню ведёт внутрь своей локали.
Плюс маршруты Flask: корень = EN, /tenerife/en/ → 301, неизвестная локаль → 404.
"""
import importlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
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
    """Каждая локаль собирается отдельной командой в свой каталог: 13 страниц + impressum + privacy + _notice."""

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

    def test_thirteen_pages_and_legal(self):
        want = {f"{name}.html" for _f, name in PAGES} | {f"{n}.html" for n in LEGAL} | {"_notice.html"}
        for locale in LOCALES:
            got = {p.name for p in self.out[locale].glob("*.html")}
            self.assertEqual(got, want, locale)
            self.assertEqual(len([n for n in got if not n.startswith("_") and n not in {f"{x}.html" for x in LEGAL}]),
                             13, locale)

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
            for _f, name in PAGES:                       # меню и лист ведут внутрь своей локали
                self.assertIn(f'href="{url_of(locale, name)}"', nav, (locale, name))
            self.assertIn(f'<a href="{BASE}/tenerife/"', nav, locale)
            self.assertRegex(nav, r'<a href="https://artemisresort\.com/tenerife/"[^>]*>EN</a>', locale)
            for other in ("es", "de", "fr"):
                self.assertRegex(nav, rf'<a href="{BASE}/tenerife/{other}/"( aria-current="true")?>', (locale, other))
            self.assertIn('class="lang-ru"', page, locale)   # русская версия — тихо в подвале
            self.assertTrue(head)

    def test_no_cyrillic_left_except_the_form(self):
        """Видимый текст перевода без русских слов. Остаются русскими (известный долг, не этой ветки): форма
        записи (copy_v3/17_forma.md + FORM_MSG), калькулятор и alt-тексты фото (alts.json) — общие для всех языков."""
        for locale in ("en", "es", "de", "fr"):
            for _f, name in PAGES:
                body = self.page(locale, name).split("<body>", 1)[1]
                body = body.split('<section class="section section--sand"', 1)[0]  # без блока формы
                body = re.sub(r'<section class="section calc-sec" id="calc".*?</section>', " ", body, flags=re.S)
                body = re.sub(r'<div class="wrap grid calc[^"]*" id="calc">.*?</section>', " ", body, flags=re.S)
                text = re.sub(r"<[^>]+>", " ", body)   # только текстовые узлы, без alt/title
                cyr = re.findall(r"[А-Яа-яЁё]{2,}", text)
                self.assertEqual(cyr, [], (locale, name, cyr[:5]))

    def test_interface_strings_are_localised(self):
        from locale_cfg import UI
        for locale in LOCALES:
            ui = UI[locale]
            page = self.page(locale, "index")
            self.assertIn(f'<a class="skip" href="#main">{ui["skip"]}</a>', page, locale)
            self.assertIn(f'<span class="burger__icon" aria-hidden="true"></span>{ui["menu"]}</a>', page, locale)
            self.assertIn(f'<p><strong>{ui["pages"]}</strong></p>', page, locale)
            self.assertIn(f'<p><strong>{ui["docs"]}</strong>', page, locale)


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
