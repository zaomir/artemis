"""Six-stage price curve: numerical shape, explicit cropped scale and all public placements."""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/tenerife_site_build"))
from price_curve import build_curve, monotone_segments, reduction_percent  # noqa: E402
import locale_cfg  # noqa: E402
from test_tenerife_investors_architecture import Document  # noqa: E402

MODEL = json.loads((ROOT / "app/static/tenerife/site/model.json").read_text())


def bezier(segment, t):
    return tuple(sum(weight * p[axis] for weight, p in zip(
        ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3), segment)) for axis in (0, 1))


class PriceCurveTest(unittest.TestCase):
    def test_interpolation_has_no_invented_peaks_or_overshoot(self):
        # Unequal slopes, plateaus and turning points also guard the tangent limiter.
        for values in ([2950, 3100, 3250, 3450, 3650, 3850],
                       [0, 0, 10, 10, 11, 50], [5, 1, 1, 9, 4, 0]):
            points = list(zip([0, 1, 3, 4, 8, 10], values))
            for index, segment in enumerate(monotone_segments(points)):
                self.assertEqual(bezier(segment, 0), points[index])
                self.assertEqual(bezier(segment, 1), points[index+1])
                samples = [bezier(segment, t/200) for t in range(201)]
                low, high = sorted(values[index:index+2])
                self.assertTrue(all(low-1e-9 <= y <= high+1e-9 for x, y in samples))
                self.assertTrue(all(b[0] > a[0] for a, b in zip(samples, samples[1:])))
                sign = 1 if values[index+1] >= values[index] else -1
                self.assertTrue(all(sign*(b[1]-a[1]) >= -1e-9 for a, b in zip(samples, samples[1:])))

    def test_reduction_uses_handover_denominator(self):
        self.assertEqual(reduction_percent(2950, 3850), Decimal("23.4"))
        self.assertNotEqual(reduction_percent(2950, 3850), Decimal("30.5"))
        self.assertEqual([reduction_percent(s["price_eur_m2"], 3850) for s in MODEL["steps"]],
                         list(map(Decimal, ["23.4", "19.5", "15.6", "10.4", "5.2", "0.0"])))

    def test_fixed_scale_and_square_variants(self):
        curve = build_curve(MODEL["steps"], locale_cfg.STAGE_NAMES["ru"], "ru")
        self.assertEqual((curve["min"], curve["max"], curve["grid_step"]), (2900, 3900, 100))
        self.assertEqual(curve["difference"], "−900\u00a0€ / −23,4%")
        for variant in curve["variants"]:
            self.assertEqual([t["value"] for t in variant["ticks"]], list(range(2900, 3901, 100)))
            self.assertEqual(variant["line"].count(" C "), 5)
            self.assertEqual(variant["area"].count(" Z"), 1)
            self.assertEqual([p["value"] for p in variant["marks"]], [2950, 3100, 3250, 3450, 3650, 3850])

    def test_out_of_scale_price_fails_instead_of_silent_clipping(self):
        steps = [dict(s) for s in MODEL["steps"]]
        steps[-1]["price_eur_m2"] = 4000
        with self.assertRaises(ValueError):
            build_curve(steps, locale_cfg.STAGE_NAMES["ru"], "ru")

    def test_all_fifteen_localized_placements(self):
        for locale in ("ru", "en", "es", "de", "fr"):
            folder = ROOT / "app/tenerife_site" / ("" if locale == "en" else locale)
            for page in ("inversores", "mercado", "construccion"):
                with self.subTest(locale=locale, page=page):
                    source = (folder / (page+".html")).read_text()
                    doc = Document(source)
                    curves = [n for n in doc.root.nodes("figure") if n.attrs.get("class") == "price-curve"]
                    self.assertEqual(len(curves), 1)
                    curve = curves[0]
                    self.assertEqual([curve.attrs[k] for k in ("data-y-min", "data-y-max", "data-grid-step")],
                                     ["2900", "3900", "100"])
                    svgs = list(curve.nodes("svg"))
                    self.assertEqual(len(svgs), 2)
                    for svg in svgs:
                        self.assertEqual(svg.attrs["width"], svg.attrs["height"])
                        self.assertEqual(svg.attrs["role"], "img")
                        self.assertEqual([n.attrs["data-price"] for n in svg.nodes("line")],
                                         list(map(str, range(2900, 3901, 100))))
                        points = list(svg.nodes("circle"))
                        self.assertEqual([p.attrs["data-stage"] for p in points], [s["id"] for s in MODEL["steps"]])
                        self.assertEqual([p.attrs["data-price"] for p in points], [str(s["price_eur_m2"]) for s in MODEL["steps"]])
                        self.assertIn("--min", points[0].attrs["class"])
                        self.assertIn("--max", points[-1].attrs["class"])
                    self.assertIn(locale_cfg.STAGE_NAMES[locale][0], curve.text())
                    self.assertNotIn('class="ladder', source)
                    self.assertNotIn('class="mini-ladder', source)
                    ids = [n.attrs["id"] for n in doc.root.nodes() if "id" in n.attrs]
                    self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
