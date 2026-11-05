"""EN r2: no public price-curve calculator; approved ranges live in copy."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PriceCurveTest(unittest.TestCase):
    def test_no_public_calculator_page(self):
        self.assertFalse((ROOT / "app/tenerife_site/calculadora.html").exists())
        self.assertTrue((ROOT / "app/tenerife_site/condiciones.html").exists())
        html = (ROOT / "app/tenerife_site/acciones.html").read_text(encoding="utf-8")
        self.assertIn("≈2,900–3,100", html)
        self.assertIn("≈3,700–3,900", html)


if __name__ == "__main__":
    unittest.main()
