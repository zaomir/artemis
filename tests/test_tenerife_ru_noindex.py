"""ru-noindex (founder 01.11: no Russian on public sites, RU Tenerife only for the founder's review).
With TENERIFE_INDEXING unset every /tenerife/ page is noindex (meta + X-Robots-Tag), none is in sitemap.xml,
no hreflang points at /tenerife/ (from Tenerife or Crete pages) and no Crete page links to /tenerife/."""
import re
import unittest

from test_tenerife_r4_1 import URLS, Case

CRETE = [f"/{l}/{p}" for l in ("en", "ru", "es", "fr") for p in ("", "privacy/", "terms/")]


class RuNoindexTest(Case):
    def test_every_tenerife_page_noindex(self):
        self.assertEqual(len(URLS), 16)
        for url in URLS:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow", url)
            page = r.get_data(as_text=True)
            self.assertIn('<meta name="robots" content="noindex, nofollow">', page, url)
            self.assertEqual(re.findall(r'hreflang="([^"]*)"', page), [], url)

    def test_sitemap_has_no_tenerife(self):
        body = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertNotIn("/tenerife", body)

    def test_crete_pages_neither_link_nor_hreflang_to_tenerife(self):
        for url in CRETE:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            page = r.get_data(as_text=True)
            self.assertNotIn("/tenerife", page, url)


class RuIndexingOnTest(Case):
    env = {"TENERIFE_WHATSAPP": "+440000000000", "TENERIFE_INDEXING": "1"}

    def test_indexing_on_still_no_hreflang(self):
        for url in URLS[:-1]:
            page = self.client.get(url).get_data(as_text=True)
            self.assertEqual(re.findall(r'hreflang="([^"]*)"', page), [], url)


if __name__ == "__main__":
    unittest.main()
