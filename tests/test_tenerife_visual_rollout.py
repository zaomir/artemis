"""Review-gated ARTEMIS watercolour rollout tests; no production deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "tenerife_site_build"
sys.path.insert(0, str(SCRIPTS))
import build_v3 as site_builder  # noqa: E402

FRAMES = json.loads((SCRIPTS / "frames.json").read_text(encoding="utf-8"))
ALTS = json.loads((SCRIPTS / "alts.json").read_text(encoding="utf-8"))
I18N = json.loads((SCRIPTS / "i18n_strings.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "docs" / "visual" / "candidates" / "manifest.json").read_text(encoding="utf-8"))

STEM = "artemis-watercolour-art01-20261104"


class WatercolourPreviewTests(unittest.TestCase):
    def setUp(self):
        self.pages = {
            "index": ["F01", "F04"],
            "norte": ["F21", "F23"],
            "producto": ["F05"],
            "inversores": ["F14"],
            "construccion": ["F15"],
            "equipo": ["F22"],
        }

    def test_production_build_retains_existing_photo(self):
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "0"}):
            mapping = site_builder.assign_site_frames(self.pages, FRAMES)
        self.assertEqual(mapping["index"]["F01"], "modern-low-6e9d80")
        self.assertNotEqual(mapping["index"]["F01"], STEM)
        self.assertEqual(mapping["norte"]["F21"], "hillside-row-71c3ab")
        self.assertEqual(mapping["producto"]["F05"], "interior-o-74f891")

    def test_explicit_review_build_uses_new_visual(self):
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "1"}):
            mapping = site_builder.assign_site_frames(self.pages, FRAMES)
        self.assertEqual(mapping["index"]["F01"], STEM)
        for page, frame in (("norte", "F21"), ("producto", "F05"),
                            ("inversores", "F14"), ("construccion", "F15"),
                            ("equipo", "F22")):
            self.assertIsNone(mapping[page][frame], (page, frame))
        self.assertEqual(set(FRAMES["preview_hidden"]),
                         {"norte/F21", "producto/F05", "inversores/F14",
                          "construccion/F15", "equipo/F22"})
        assigned = [v for p in mapping.values() for v in p.values() if v]
        self.assertEqual(len(assigned), len(set(assigned)))

    def test_draft_cannot_be_production_override(self):
        self.assertEqual(MANIFEST["status"], "REVIEW")
        self.assertEqual(FRAMES.get("page_overrides"), {})
        self.assertEqual(FRAMES["preview_overrides"]["index/F01"], [STEM])

    def test_all_five_languages_have_alts_and_disclosure(self):
        self.assertIn(STEM, ALTS["images"])
        for lang in ("ru", "en", "es", "de", "fr"):
            self.assertTrue(I18N[lang]["visual"]["concept_caption"])
            if lang != "ru":
                self.assertIn(STEM, I18N[lang]["alts"])

    def test_preview_concept_stage_is_current_not_fake_construction_progress(self):
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "1"}):
            # The semantic hook attaches to the reserved F17 homepage section only.
            for lang in ("ru", "en", "es", "de", "fr"):
                cfg = I18N[lang]["visual"]["concept_stages"]
                self.assertEqual(len(cfg["steps"]), 4)
                self.assertTrue(cfg["current"])
                self.assertTrue(cfg["next"])
                self.assertNotEqual(cfg["current"], cfg["next"])
        components = (ROOT / "app" / "templates" / "tenerife" / "site" / "_components.html").read_text(encoding="utf-8")
        self.assertIn('s.concept_progress|default(false)', components)
        self.assertIn('class="is-current"', components)
        builder_src = (SCRIPTS / "build_v3.py").read_text(encoding="utf-8")
        self.assertIn('name == "index" and "F17" in s["frames"]', builder_src)
        self.assertIn('os.environ.get("ARTEMIS_VISUAL_PREVIEW") == "1"', builder_src)

    def test_source_master_and_responsive_variants_exist(self):
        img_dir = ROOT / "app" / "static" / "tenerife" / "site" / "img"
        for suffix in (".jpg", "-640.webp", "-800.webp", "-1024.webp",
                       "-1600.webp", "-mobile-640.webp", "-mobile-800.webp"):
            self.assertTrue((img_dir / (STEM + suffix)).is_file(), suffix)

    def test_location_locator_uses_verified_points_and_no_parcel_claim(self):
        svg_path = ROOT / "app" / "static" / "tenerife" / "site" / "img" / "la-quinta-context-locator-20261105.svg"
        svg = svg_path.read_text(encoding="utf-8")
        self.assertIn("La Quinta", svg)
        self.assertIn("Puerto de la Cruz", svg)
        self.assertIn("TITSA 4004", svg)
        self.assertIn("no selected parcel", svg)
        self.assertIn("OpenStreetMap contributors", svg)
        # Check that the landmark IDs are not silently repurposed as a development plot.
        self.assertNotIn("artemis-plot", svg)
        self.assertNotIn("construction-site-boundary", svg)

    def test_location_map_replaces_false_render_only_in_preview(self):
        builder_src = (SCRIPTS / "build_v3.py").read_text(encoding="utf-8")
        self.assertIn('name == "norte" and "F23" in s["frames"]', builder_src)
        self.assertIn('s["location_context"] = i18n_strings()[LOCALE]["visual"]["location_context"]', builder_src)
        self.assertIn('s["frames"] = [fid for fid in s["frames"] if fid != "F23"]', builder_src)
        templates = (ROOT / "app" / "templates" / "tenerife" / "site" / "_components.html").read_text(encoding="utf-8")
        self.assertIn('s.location_context|default(false)', templates)
        self.assertIn('la-quinta-context-locator-20261105.svg', templates)
        self.assertIn('www.openstreetmap.org/?mlat=28.43187', templates)

    def test_location_locator_warning_localized(self):
        for lang in ("ru", "en", "es", "de", "fr"):
            v = I18N[lang]["visual"]["location_context"]
            for key in ("alt", "caption", "open_map"):
                self.assertTrue(v[key].strip(), (lang, key))
            self.assertGreater(len(v["caption"]), 75, lang)

    def test_mobile_picture_contract(self):
        variant = site_builder.image_variant(STEM)
        self.assertEqual(variant["width"], 1600)
        self.assertEqual(variant["height"], 900)
        self.assertIn("mobile-640.webp", variant["mobile_srcset"])
        self.assertIn("mobile-800.webp", variant["mobile_srcset"])
        self.assertTrue(variant["caption"])


if __name__ == "__main__":
    unittest.main()
