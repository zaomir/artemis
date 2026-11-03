"""Tenerife RU prod site (/tenerife/): clean URLs, local assets only, no guaranteed
return / payments, no disclaimer block / AI captions (founder 31.10 01:44 UTC), legal links,
waitlist form wired to our handler."""
import html as _html
import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from test_tenerife_preview import REMOVED_DISCLAIMERS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))
SITE = ROOT / "app" / "tenerife_site" / "ru"
STATIC = ROOT / "app" / "static"
# RU живёт под /tenerife/ru/ (EN — корень /tenerife/, ES/DE/FR — свои подкаталоги); файлы — app/tenerife_site/ru/
RU = "/tenerife/ru"
PAGES = {"index": f"{RU}/", "norte": f"{RU}/norte/", "producto": f"{RU}/producto/",
         "construccion": f"{RU}/construccion/", "proceso": f"{RU}/proceso/", "faq": f"{RU}/faq/"}
SHIPPED = {k: v for k, v in PAGES.items() if (SITE / f"{k}.html").is_file()}
FORM_HOST = "proceso" if "proceso" in SHIPPED else "index"  # until proceso.html arrives the form lives on /tenerife/

# <form action=mailto:…> / formaction='mailto:…' in any quoting (QA 2026-10-31 pr19 -01)
MAILTO_FORM = r"""(?i)\b(?:form)?action\s*=\s*["']?\s*mailto:"""
FORBIDDEN = [
    # founder 31.10.2026 16:28 UTC: share mechanics with a calculation may be shown («дивиденд», «акция» allowed);
    # a guaranteed / promised return stays forbidden.
    r"\d\s*[–-]\s*\d\s*%", r"[\d,]+\s*(?:–\s*[\d,]+)?\s*% годовых", r"доходност\w* \d",
    r"(?i)гарантир\w*\s+(?:\w+\s+)?(?:доход|доходност|дивиденд)", r"(?i)гарантированн\w* доходност",
    r"(?i)rendimiento", r"(?i)\byield\b", r"name=\"amount\"", r"Сумма", r"(?i)купить сейчас",
    r"(?i)оплат\w+ сейчас", r"(?i)iban", r"(?i)stripe", r"(?i)paypal", r"не для деплоя",
    r"(?i)TODO", r"(?i)\bTZ\b", r"(?i)бриф", r"нельзя", r"в наших файлах", r"Лица не генерируем",
    r"(?i)googletagmanager|google-analytics|gtag\(|fbq\(|yandex|metrika|hotjar|clarity",
    r"fonts\.googleapis|fonts\.gstatic", r"cdn\.leonardo\.ai", r"(?i)formspree",
    # only the *form* rule, on purpose: plain <a href="mailto:info@…"> contact links are allowed (and required inside
    # <!--email_off-->; the address allowlist is test_mailto_only_contact_address), but a <form action> /
    # <button formaction> that submits via mailto (no consent, no server copy) is forbidden — any quoting / spacing.
    MAILTO_FORM,
    r"email-protection|/cdn-cgi/",  # Cloudflare-obfuscated e-mail must never be baked into a page
    r"\+\d[\d\s()-]{7,}",  # phone numbers
]


# Cloudflare Email Obfuscation stays ON for the zone; Tenerife pages opt out per address with
# <!--email_off-->…<!--/email_off--> so mailto works without JS (no /cdn-cgi/l/email-protection 404).
CONTACT_EMAIL = "info@artemisresort.com"
# Location copy cites these sources; assets must still be served locally.
LOCATION_SOURCE_HOSTS = frozenset({
    "european-union.europa.eu", "www.webtenerife.co.uk", "www.webtenerife.com",
    "hospiten.com", "www.whytenerife.com", "decottalaw.com", "www.dstenerife.eu",
    "sede.agenciatributaria.gob.es", "www.holaislascanarias.com", "movil.titsa.com",
    "residentenerife.com", "urbara.com",
})
EMAIL_OFF_LINK = ('<!--email_off--><a href="mailto:info@artemisresort.com">info@artemisresort.com</a>'
                  '<!--/email_off-->')
LEGAL_AND_PREVIEW = [f"{RU}/impressum/", f"{RU}/privacy/"]  # /tenerife-preview/ is a 301 since T47


# founder 31.10.2026: no public disclaimers on the live Tenerife pages
LIVE_DISCLAIMERS = [r"не зафиксирован", r"не наш прайс", r"не выбираем одну цифру", r"Точную точку не называем",
                    r"не прайс-лист", r"не обязательство", r"\[уточнить", r"(?i)\bTBD\b"]


# RU v3 (copy_v3, sha256-pinned and approved as written): these five patterns occur in the approved copy
# («Сумма покупки», «4–6% аренды», «валовая доходность 5,8%» in market tables, «нельзя» in Ley 6/2025,
# the footer phone). They are re-checked in tests/test_tenerife_v3.py against everything except
# the exact approved phrases, so any new occurrence still fails.
V3_ALLOWED = {r"\d\s*[–-]\s*\d\s*%", r"доходност\w* \d", r"Сумма", r"нельзя", r"\+\d[\d\s()-]{7,}"}
FORBIDDEN = [rx for rx in FORBIDDEN if rx not in V3_ALLOWED]


class TenerifeSiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID",
                                                            "TENERIFE_WHATSAPP", "TENERIFE_INDEXING")}
        os.environ["TENERIFE_INDEXING"] = "1"  # r4: indexable mode here; default noindex: test_tenerife_r4
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
        r = self.client.get("/tenerife/ru")
        self.assertEqual((r.status_code, r.headers["Location"].rsplit("/tenerife", 1)[1]), (301, "/ru/"))
        self.assertEqual(self.client.get("/tenerife/en/").headers["Location"].rsplit("/tenerife", 1)[1], "/")
        for name, url in SHIPPED.items():
            if name == "index":
                continue
            # P1-02: EN-подстраницы в корне, старый /tenerife/en/<page>/ -> 301, а не 404
            r = self.client.get(f"/tenerife/en/{name}/")
            self.assertEqual((r.status_code, r.headers["Location"]), (301, f"/tenerife/{name}/"), name)
        for name, url in SHIPPED.items():          # /tenerife/ru/<page>.html -> 301 /tenerife/ru/<page>/
            r = self.client.get(f"{RU}/{name}.html")
            self.assertEqual(r.status_code, 301, name)
            self.assertTrue(r.headers["Location"].endswith(url), (name, r.headers["Location"]))
            r = self.client.get(f"{RU}/{name}")
            self.assertEqual(r.status_code, 301, name)
            self.assertTrue(r.headers["Location"].endswith(url), (name, r.headers["Location"]))
        self.assertEqual(self.client.get("/tenerife/nope/").status_code, 404)
        self.assertEqual(self.client.get(f"{RU}/nope/").status_code, 404)
        self.assertEqual(self.client.get("/tenerife/../app.py").status_code, 404)

    def test_no_forbidden_content(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            # основатель 02.11: публикуем расчётный дивиденд 2,5–3,5 % годовых — это не «гарантия доходности»
            html = html.replace("2,5–3,5 % годовых", "").replace("2,5–3,5% годовых", "")
            html = html.replace("9% годовых", "").replace("доходность 9", "доходность").replace("Сумма", "сумма")
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
        for url in list(SHIPPED.values()) + ["/tenerife/impressum/",
                                             "/tenerife/privacy/"]:
            html = self.client.get(url).get_data(as_text=True)
            for rx in LIVE_DISCLAIMERS:
                self.assertIsNone(re.search(rx, html), f"{url}: {rx}")

    def test_legal_pages_only_known_data(self):
        imp = self.client.get(f"{RU}/impressum/").get_data(as_text=True)
        for must in ("OXFORD FRAME REAL ASSETS LTD", "09153936", "info@artemisresort.com"):
            self.assertIn(must, imp)
        for gone in ("Телефон", "VAT", "MStV", 'class="todo"'):
            self.assertNotIn(gone, imp)
        prv = self.client.get(f"{RU}/privacy/").get_data(as_text=True)
        self.assertIn("info@artemisresort.com", prv)
        self.assertNotIn('class="todo"', prv)

    def test_email_off_mailto_on_every_tenerife_page(self):
        # raw HTML (no JS): mailto:info@… present and every address inside the email_off markers
        from email_off import unprotected
        for url in list(SHIPPED.values()) + LEGAL_AND_PREVIEW:
            html, _ = self.page(url)
            self.assertIn(EMAIL_OFF_LINK, html, url)
            self.assertEqual(unprotected(html), [], url)
            self.assertNotIn("email-protection", html, url)
            self.assertEqual(html.count("<!--email_off-->"), html.count("<!--/email_off-->"), url)

    def test_mailto_only_contact_address(self):
        # QA 2026-10-31 pr19 -01: on every Tenerife URL the only mailto target is the contact address
        # (any quoting, inside or outside the markers), and nothing submits a form via mailto
        from email_off import mailto_form_actions, mailto_targets
        for url in list(SHIPPED.values()) + LEGAL_AND_PREVIEW:
            html, _ = self.page(url)
            # path and ?to= / ?cc= / ?bcc= targets, &#109;ailto: entities decoded (QA 2026-10-31 pr21 -40)
            self.assertEqual(mailto_targets(html), {CONTACT_EMAIL}, url)
            self.assertIsNone(re.search(MAILTO_FORM, html), url)
            self.assertIsNone(re.search(MAILTO_FORM, _html.unescape(html)), url)
            self.assertEqual(mailto_form_actions(html), [], url)
        hit = lambda t: re.search(MAILTO_FORM, t)
        for bad in ('<form action="mailto:x@y.z">', "<form ACTION = 'MAILTO:x@y.z'>", "<form action=mailto:x@y.z>",
                    "<button formaction='mailto:evil@example.com'>", '<input formaction = " mailto:x@y.z">'):
            self.assertTrue(hit(bad), bad)
        for ok in ('<a href="mailto:info@artemisresort.com">', '<form action="/api/tenerife/waitlist">',
                   "<p>transaction=mailto: (text)</p>"):
            self.assertFalse(hit(ok), ok)

    def test_email_off_comments_not_stripped(self):
        # nothing between the source files and the response (minifier, after_request hook, build step)
        # may drop HTML comments, or Cloudflare would obfuscate the address again
        from email_off import wrap
        from responsive import responsive
        build = ROOT / "scripts" / "tenerife_site_build"
        footer = (build / "_footer.html").read_text(encoding="utf-8")
        self.assertIn(EMAIL_OFF_LINK, footer)
        self.assertEqual(wrap(footer), footer)  # idempotent
        self.assertIn(EMAIL_OFF_LINK, responsive(footer, STATIC / "tenerife" / "site"))
        for name, url in SHIPPED.items():
            src = (SITE / f"{name}.html").read_text(encoding="utf-8")
            html, _ = self.page(url)
            self.assertEqual(html.count(EMAIL_OFF_LINK), src.count(EMAIL_OFF_LINK), name)
            self.assertGreaterEqual(html.count("<!--email_off-->"), 1, name)
            self.assertEqual(wrap(src), src, f"{name}: build output not passed through email_off.wrap")
        for url in LEGAL_AND_PREVIEW:
            html, _ = self.page(url)
            self.assertEqual(wrap(html), html, url)
        # helper: bare address and mailto get wrapped, attributes are left alone
        self.assertEqual(wrap("<p>x@artemisresort.com</p>"),
                         "<p><!--email_off-->x@artemisresort.com<!--/email_off--></p>")
        a = '<a class="m" href="mailto:x@artemisresort.com">write</a>'
        self.assertEqual(wrap(a), "<!--email_off-->" + a + "<!--/email_off-->")
        attr = '<input placeholder="x@example.com">'
        self.assertEqual(wrap(attr), attr)

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
            # non-executable data blocks (FAQPage JSON-LD on /faq/) are not scripts for CSP
            self.assertIsNone(re.search(r"<script(?![^>]*\ssrc=)(?! type=\"application/ld\+json\">)[^>]*>", html), name)
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
            for s in (f'href="{RU}/impressum/"', f'href="{RU}/privacy/"',
                      "OXFORD FRAME REAL ASSETS LTD", "09153936"):
                self.assertIn(s, html, f"{name}: {s}")
            self.assertNotIn("/tenerife-preview/", html, name)

    def test_legal_pages_prod_indexable_canonical(self):
        # 31.10.2026: Impressum / privacy live at /tenerife/<name>/ (indexable, canonical, in sitemap);
        # since the locale branch the RU pair sits under /tenerife/ru/<name>/ with its own canonical
        locs = re.findall(r"<loc>([^<]+)</loc>", self.client.get("/sitemap.xml").get_data(as_text=True))
        for name in ("impressum", "privacy"):
            url = f"{RU}/{name}/"
            html, r = self.page(url)
            self.assertNotIn("X-Robots-Tag", r.headers, url)
            self.assertNotIn("noindex", html, url)
            self.assertIn(f'<link rel="canonical" href="https://artemisresort.com{url}">', html)
            self.assertNotIn("Предварительная версия", html, url)
            self.assertNotIn("превью", html, url)
            self.assertIn("https://artemisresort.com" + url, locs)
            # nginx CSP on /tenerife/ forbids inline style/script
            self.assertNotIn("<style", html, url)
            self.assertNotIn("style=", html, url)
            # QA T3-09: v2 layout (site.css, site.js for the menu); no inline script, no form
            self.assertIsNone(re.search(r"<script(?![^>]*\ssrc=)", html), url)
            self.assertIn('<link rel="stylesheet" href="/static/tenerife/site/site.css">', html)
            self.assertNotIn("<form", html, url)
            for ref in re.findall(r'(?:href|src)="(/[^"#?]*)', html):
                if ref.startswith("/static/"):
                    self.assertTrue((STATIC / ref[len("/static/"):]).is_file(), f"{url}: missing {ref}")
                else:
                    self.assertEqual(self.client.get(ref).status_code, 200, f"{url}: {ref}")
            self.assertIn(self.client.get(f"{RU}/{name}").status_code, (301, 308))
            self.assertEqual(self.client.get(f"{RU}/{name}.html").status_code, 301)

    def test_internal_links_and_assets_resolve(self):
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            for attribute, ref in re.findall(r'(href|src)="([^"#?]+)', html):
                if ref == "mailto:" + CONTACT_EMAIL:  # wrapped in <!--email_off-->, see test_email_off_*
                    continue
                if ref.startswith(("http://", "https://")):
                    is_source = (attribute == "href" and name in {"norte", "mercado"}
                                 and urlsplit(ref).scheme == "https"
                                 and urlsplit(ref).netloc in LOCATION_SOURCE_HOSTS)
                    self.assertTrue(ref.startswith("https://artemisresort.com/tenerife/") or is_source,
                                    f"{name}: external {ref}")
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
        total = 0
        for name, url in SHIPPED.items():
            html, _ = self.page(url)
            imgs = re.findall(r"<img[^>]+>", html)
            total += len(imgs)  # T47: one photo = one slot site-wide, so a page may have none
            hero = '<div class="hero__media"><picture>' in html  # QA T3-11: a hero slot may have no photo
            for i, tag in enumerate(imgs):
                self.assertRegex(tag, r'width="\d+" height="\d+"', f"{name}: no size {tag}")
                if i == 0 and hero:
                    self.assertIn('fetchpriority="high"', tag, name)
                    self.assertNotIn('loading="lazy"', tag, name)
                else:
                    self.assertIn('loading="lazy"', tag, f"{name}: {tag}")
            self.assertEqual(len(re.findall(r'<source type="image/webp"', html)), len(imgs), name)
            self.assertEqual('<link rel="preload" as="image" type="image/webp" imagesrcset=' in html, hero, name)
            for srcset in re.findall(r'(?:imagesrcset|srcset)="([^"]+)"', html):
                widths = []
                for part in srcset.split(", "):
                    ref, w = part.split(" ")
                    widths.append(w)
                    self.assertTrue(ref.endswith(".webp"), ref)
                    self.assertTrue((STATIC / ref[len("/static/"):]).is_file(), f"{name}: missing {ref}")
                self.assertEqual(widths, ["640w", "800w", "1024w", "1600w"], name)
        self.assertTrue(total, "no images on the site")

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
            "page": f"{RU}/proceso/"}, headers={"CF-Connecting-IP": "9.9.9.9"})
        self.assertEqual(r.status_code, 303)
        # QA T3-05: no-JS thank-you page with the way back to the page the form was sent from
        self.assertTrue(r.headers["Location"].endswith("/tenerife/gracias/?back=%2Ftenerife%2Fru%2Fproceso%2F"))
        r = self.client.post("/api/tenerife/waitlist", data={
            "name": "Bob", "contact": "bob@example.de", "language": "ru", "consent": "1",
            "page": "//evil.example/x"}, headers={"CF-Connecting-IP": "9.9.9.8"})
        self.assertEqual(r.status_code, 303)
        self.assertNotIn("evil", r.headers["Location"])

    def test_not_linked_from_crete(self):
        for lang in ("en", "ru", "es", "fr"):
            html = self.client.get(f"/{lang}/").get_data(as_text=True)
            self.assertNotIn("/tenerife/", html, lang)

    def test_preview_still_there(self):  # T47 (31.10.2026): the old one-pager is retired -> 301 to /tenerife/
        r = self.client.get("/tenerife-preview/")
        self.assertEqual((r.status_code, r.headers["Location"].replace("http://localhost", "")), (301, "/tenerife/"))


if __name__ == "__main__":
    unittest.main()
