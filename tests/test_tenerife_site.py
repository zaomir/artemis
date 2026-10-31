"""Tenerife RU prod site (/tenerife/): clean URLs, local assets only, no guaranteed
return / payments, no disclaimer block / AI captions (founder 31.10 01:44 UTC), legal links,
waitlist form wired to our handler."""
import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from test_tenerife_preview import REMOVED_DISCLAIMERS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
SITE = ROOT / "app" / "tenerife_site"
STATIC = ROOT / "app" / "static"
PAGES = {"index": "/tenerife/", "norte": "/tenerife/norte/", "producto": "/tenerife/producto/",
         "construccion": "/tenerife/construccion/", "proceso": "/tenerife/proceso/", "faq": "/tenerife/faq/"}
SHIPPED = {k: v for k, v in PAGES.items() if (SITE / f"{k}.html").is_file()}
FORM_HOST = "proceso" if "proceso" in SHIPPED else "index"  # until proceso.html arrives the form lives on /tenerife/

FORBIDDEN = [
    # founder 31.10.2026 16:28 UTC: share mechanics with a calculation may be shown («дивиденд», «акция» allowed);
    # a guaranteed / promised return stays forbidden.
    r"\d\s*[–-]\s*\d\s*%", r"\d+\s*% годовых", r"доходност\w* \d",
    r"(?i)гарантир\w*\s+(?:\w+\s+)?(?:доход|доходност|дивиденд)", r"(?i)гарантированн\w* доходност",
    r"(?i)rendimiento", r"(?i)\byield\b", r"name=\"amount\"", r"Сумма", r"(?i)купить сейчас",
    r"(?i)оплат\w+ сейчас", r"(?i)iban", r"(?i)stripe", r"(?i)paypal", r"не для деплоя",
    r"(?i)TODO", r"(?i)\bTZ\b", r"(?i)бриф", r"нельзя", r"в наших файлах", r"Лица не генерируем",
    r"(?i)googletagmanager|google-analytics|gtag\(|fbq\(|yandex|metrika|hotjar|clarity",
    r"fonts\.googleapis|fonts\.gstatic", r"cdn\.leonardo\.ai", r"(?i)formspree|mailto:",
    r"\+\d[\d\s()-]{7,}",  # phone numbers
]


# founder 31.10.2026: no public disclaimers on the live Tenerife pages
LIVE_DISCLAIMERS = [r"не зафиксирован", r"не наш прайс", r"не выбираем одну цифру", r"Точную точку не называем",
                    r"не прайс-лист", r"не обязательство", r"\[уточнить", r"(?i)\bTBD\b"]


class TenerifeSiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")}
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def page(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.get_data(as_text=True), r

    def test_shipped_pages_and_unshipped_404(self):
        self.assertIn("index", SHIPPED)
        for name, url in PAGES.items():
            code = self.client.get(url).status_code
            self.assertEqual(code, 200 if name in SHIPPED else 404, url)
            if name not in SHIPPED:  # never linked while missing
                for other in SHIPPED.values():
                    self.assertNotIn(f'href="{url}', self.client.get(other).get_data(as_text=True), (other, url))

    def test_pages_200_indexable_with_h1(self):
        for name, url in SHIPPED.items():
            html, r = self.page(url)
            self.assertIn("text/html", r.headers["Content-Type"])
            self.assertNotIn("X-Robots-Tag", r.headers, url)
            self.assertNotIn("noindex", html, url)
            self.assertEqual(len(re.findall(r"<h1[ >]", html)), 1, url)
            self.assertIn('lang="ru"', html)
            self.assertIn('name="viewport"', html)

    def test_redirects(self):
        r = self.client.get("/tenerife")
        self.assertEqual((r.status_code, r.headers["Location"].rsplit("/tenerife", 1)[1]), (301, "/"))
        for name, url in SHIPPED.items():
            r = self.client.get(f"/tenerife/{name}.html")
            self.assertEqual(r.status_code, 301, name)
            self.assertTrue(r.headers["Location"].endswith(url), (name, r.headers["Location"]))
        self.assertEqual(self.client.get("/tenerife/nope/").status_code, 404)
        self.assertEqual(self.client.get("/tenerife/../app.py").status_code, 404)

    def test_no_forbidden_content(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            for rx in FORBIDDEN:
                self.assertIsNone(re.search(rx, html), f"{name}: {rx}")

    def test_forbidden_list_allows_shares_but_not_guaranteed_return(self):
        # founder 31.10.2026 16:28 UTC: «дивиденд» / «акция» are allowed, a guaranteed return is not
        hit = lambda t: [rx for rx in FORBIDDEN if re.search(rx, t)]
        for ok in ("Дивиденд по акции зависит от чистой аренды.", "Акции компании-застройщика",
                   "дивиденд на акцию в €/год"):
            self.assertEqual(hit(ok), [], ok)
        for bad in ("гарантированная доходность", "Гарантированный доход", "гарантируем дивиденд",
                    "4–6 % годовых"):
            self.assertTrue(hit(bad), bad)

    def test_no_live_disclaimers(self):
        for url in list(SHIPPED.values()) + ["/tenerife-preview/", "/tenerife-preview/impressum/",
                                             "/tenerife-preview/privacy/"]:
            html = self.client.get(url).get_data(as_text=True)
            for rx in LIVE_DISCLAIMERS:
                self.assertIsNone(re.search(rx, html), f"{url}: {rx}")

    def test_legal_pages_only_known_data(self):
        imp = self.client.get("/tenerife-preview/impressum/").get_data(as_text=True)
        for must in ("OXFORD FRAME REAL ASSETS LTD", "09153936", "info@artemisresort.com"):
            self.assertIn(must, imp)
        for gone in ("Телефон", "VAT", "MStV", 'class="todo"'):
            self.assertNotIn(gone, imp)
        prv = self.client.get("/tenerife-preview/privacy/").get_data(as_text=True)
        self.assertIn("info@artemisresort.com", prv)
        self.assertNotIn('class="todo"', prv)

    def test_seo_meta_og_canonical(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            full = "https://artemisresort.com" + url
            self.assertIn(f'<link rel="canonical" href="{full}">', html, name)
            desc = re.search(r'<meta name="description" content="([^"]+)">', html)
            self.assertTrue(desc and 50 <= len(desc.group(1)) <= 170, name)
            for prop in ("og:title", "og:description", "og:image", "og:type", "og:locale"):
                self.assertRegex(html, rf'<meta property="{prop}" content="[^"]+">', f"{name}: {prop}")
            self.assertIn(f'<meta property="og:url" content="{full}">', html, name)
            img = re.search(r'<meta property="og:image" content="https://artemisresort.com/static/([^"]+)">', html)
            self.assertTrue(img and (STATIC / img.group(1)).is_file(), name)

    def test_no_inline_script_for_csp(self):
        # nginx CSP on /tenerife/: script-src 'self' (no 'unsafe-inline')
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            self.assertIsNone(re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), name)
            self.assertNotRegex(html, r"\son[a-z]+=", name)
            self.assertNotIn("style=", html, name)

    def test_sitemap_and_robots(self):
        r = self.client.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/xml", r.headers["Content-Type"])
        locs = re.findall(r"<loc>([^<]+)</loc>", r.get_data(as_text=True))
        self.assertIn("https://artemisresort.com/tenerife/", locs)
        for url in SHIPPED.values():
            self.assertIn("https://artemisresort.com" + url, locs)
        for loc in locs:
            self.assertTrue(loc.startswith("https://artemisresort.com/"), loc)
            self.assertNotIn("preview", loc)
            path = loc[len("https://artemisresort.com"):]
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(len(locs), len(set(locs)))
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Sitemap: https://artemisresort.com/sitemap.xml", r.get_data(as_text=True))

    def test_no_disclaimers_and_legal_links(self):
        # founder 31.10.2026 01:44 UTC: no disclaimer block / AI captions; legal pages linked in the footer
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            for pat in REMOVED_DISCLAIMERS:
                self.assertIsNone(re.search(pat, html, re.I), f"{name}: {pat}")
            for s in ("/tenerife-preview/impressum/", "/tenerife-preview/privacy/",
                      "OXFORD FRAME REAL ASSETS LTD", "09153936"):
                self.assertIn(s, html, f"{name}: {s}")

    def test_internal_links_and_assets_resolve(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            for ref in re.findall(r'(?:href|src)="([^"#?]+)', html):
                if ref.startswith(("http://", "https://")):
                    self.assertTrue(ref.startswith("https://artemisresort.com/tenerife/"), f"{name}: external {ref}")
                    continue
                self.assertTrue(ref.startswith("/"), f"{name}: relative link {ref}")
                if ref.startswith("/static/"):
                    self.assertTrue((STATIC / ref[len('/static/'):]).is_file(), f"{name}: missing {ref}")
                else:
                    self.assertEqual(self.client.get(ref).status_code, 200, f"{name}: {ref}")

    def test_images_local_with_alt(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            for tag in re.findall(r"<img[^>]+>", html):
                src = re.search(r'src="([^"]+)"', tag).group(1)
                self.assertTrue(src.startswith("/static/tenerife/site/"), f"{name}: {src}")
                alt = re.search(r'alt="([^"]*)"', tag)
                self.assertTrue(alt and alt.group(1).strip(), f"{name}: alt missing {src}")
                for pat in REMOVED_DISCLAIMERS:
                    self.assertIsNone(re.search(pat, alt.group(1), re.I), f"{name}: alt {pat}")

    def test_images_responsive_webp_sized_lazy(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            imgs = re.findall(r"<img[^>]+>", html)
            self.assertTrue(imgs, name)
            for i, tag in enumerate(imgs):
                self.assertRegex(tag, r'width="\d+" height="\d+"', f"{name}: no size {tag}")
                if i == 0:
                    self.assertIn('fetchpriority="high"', tag, name)
                    self.assertNotIn('loading="lazy"', tag, name)
                else:
                    self.assertIn('loading="lazy"', tag, f"{name}: {tag}")
            self.assertEqual(len(re.findall(r'<source type="image/webp"', html)), len(imgs), name)
            self.assertIn('<link rel="preload" as="image" type="image/webp" imagesrcset=', html, name)
            for srcset in re.findall(r'(?:imagesrcset|srcset)="([^"]+)"', html):
                widths = []
                for part in srcset.split(", "):
                    ref, w = part.split(" ")
                    widths.append(w)
                    self.assertTrue(ref.endswith(".webp"), ref)
                    self.assertTrue((STATIC / ref[len("/static/"):]).is_file(), f"{name}: missing {ref}")
                self.assertEqual(widths, ["640w", "1024w", "1600w"], name)

    def test_css_local_with_fonts(self):
        css = (STATIC / "tenerife/site/style.css").read_text(encoding="utf-8")
        self.assertNotIn("googleapis", css)
        for font in re.findall(r"url\((fonts/[^)]+)\)", css):
            self.assertTrue((STATIC / "tenerife/site" / font).is_file(), font)

    def test_waitlist_form_on_form_host(self):
        html, _ = self.page(PAGES[FORM_HOST])
        form = re.search(r"<form.*?</form>", html, re.S).group(0)
        self.assertIn('action="/api/tenerife/waitlist"', form)
        self.assertIn('name="consent"', form)
        self.assertIn('name="website"', form)
        self.assertIn(f'value="{PAGES[FORM_HOST]}"', form)
        self.assertIn('id="waitlist"', html)
        self.assertNotIn("amount", form)
        for name, url in SHIPPED.items():
            h, _ = self.page(url)
            for f in re.findall(r"<form[^>]*>", h):
                self.assertIn('action="/api/tenerife/waitlist"', f, name)

    def test_waitlist_submit_from_site_and_no_js_redirect(self):
        r = self.client.post("/api/tenerife/waitlist", data={
            "name": "Anna", "contact": "anna@example.de", "language": "ru", "consent": "1",
            "page": "/tenerife/proceso/"}, headers={"CF-Connecting-IP": "9.9.9.9"})
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["Location"].endswith("/tenerife/proceso/?ok=1#waitlist"))
        r = self.client.post("/api/tenerife/waitlist", data={
            "name": "Bob", "contact": "bob@example.de", "language": "ru", "consent": "1",
            "page": "//evil.example/x"}, headers={"CF-Connecting-IP": "9.9.9.8"})
        self.assertEqual(r.status_code, 303)
        self.assertNotIn("evil", r.headers["Location"])

    def test_not_linked_from_crete(self):
        for lang in ("en", "ru", "es", "fr"):
            html = self.client.get(f"/{lang}/").get_data(as_text=True)
            self.assertNotIn("/tenerife/", html, lang)

    def test_preview_still_there(self):
        self.assertEqual(self.client.get("/tenerife-preview/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
