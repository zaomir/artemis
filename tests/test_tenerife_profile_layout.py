"""EN r2: profile pages (simon/boris) are EN long-text; no embedded calculator."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "app" / "tenerife_site"


class ProfileLayoutTest(unittest.TestCase):
    def test_profiles_are_en_without_calculator(self):
        for name in ("simon", "boris"):
            html = (SITE / f"{name}.html").read_text(encoding="utf-8")
            self.assertIn('<html lang="en">', html)
            self.assertNotIn("calc.js", html)
            self.assertNotIn('data-variant="calculadora"', html)
            self.assertNotIn("hreflang=", html)


if __name__ == "__main__":
    unittest.main()
