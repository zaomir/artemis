"""EN r2: public Tenerife has no calculator; model.json stays server-side only."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "app" / "tenerife_site"
STATIC = ROOT / "app" / "static" / "tenerife" / "site"


class CashExitModelTest(unittest.TestCase):
    def test_model_server_side_only(self):
        self.assertTrue((SITE / "data" / "model.json").is_file())
        self.assertFalse((STATIC / "model.json").exists())
        self.assertFalse((STATIC / "calc.js").exists())

    def test_public_html_has_no_calc_or_model(self):
        for html in SITE.glob("*.html"):
            text = html.read_text(encoding="utf-8")
            self.assertNotIn("calc.js", text, html.name)
            self.assertNotIn("model.json", text, html.name)
            self.assertNotIn('name="calc_', text, html.name)


if __name__ == "__main__":
    unittest.main()
