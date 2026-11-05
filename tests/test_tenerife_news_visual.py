"""Project diary must reuse provenanced artwork in accessible five-language teasers."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "tenerife_site_build" / "news.py"

spec = importlib.util.spec_from_file_location("artemis_news", SRC)
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)


class NewsTeaserTests(unittest.TestCase):
    def test_five_languages_have_article_and_thumbnail(self):
        for loc in ("en", "ru", "es", "de", "fr"):
            output = news.build_pages(lambda title, description, body, url, locales: body, loc)
            self.assertIn("actualizaciones", output)
            self.assertIn("actualizaciones/concept-search", output)
            listing = output["actualizaciones"]
            article = output["actualizaciones/concept-search"]
            self.assertIn("diary-atlantic-20261104.webp", listing)
            self.assertIn("news-teaser__media", listing)
            self.assertIn("diary-atlantic-20261104.webp", article)
            self.assertIn('loading="lazy"', listing)
            self.assertIn('<figcaption', listing)
            self.assertNotIn("construction-completed", listing)


if __name__ == "__main__":
    unittest.main()
