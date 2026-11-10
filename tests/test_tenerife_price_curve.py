"""EN r2+ (t15u): no public price-curve calculator; no share-price page on disk."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PriceCurveTest(unittest.TestCase):
    def test_no_public_calculator_or_share_page(self):
        site = ROOT / "app/tenerife_site"
        self.assertFalse((site / "calculadora.html").exists())
        self.assertFalse((site / "acciones.html").exists())
        self.assertTrue((site / "condiciones.html").exists())
        html = (site / "condiciones.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("2.5–3.5%", html)
        self.assertNotIn("developer company shares", html)


if __name__ == "__main__":
    unittest.main()
