"""Review-gated ARTEMIS watercolour rollout tests; no production deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
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
                            ("inversores", "F14"), ("construccion", "F15")):
            self.assertEqual(mapping[page][frame], f"artemis-watercolour-{page}-20261105")
        self.assertIsNone(mapping["equipo"]["F22"])
        self.assertEqual(set(FRAMES["preview_hidden"]), {"norte/F23", "equipo/F22"})
        assigned = [v for p in mapping.values() for v in p.values() if v]
        self.assertEqual(len(assigned), len(set(assigned)))

    def test_hidden_and_replaced_renders_cannot_migrate_to_other_pages(self):
        pages = dict(self.pages, energia=["F11", "F16"], proceso=["F02", "F15"],
                     simon=["F19", "F21"], mercado=["F24"])
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "1"}):
            mapping = site_builder.assign_site_frames(pages, FRAMES)
        assigned = {v for page in mapping.values() for v in page.values() if v}
        rejected = set(FRAMES["preview_excluded_stems"])
        for key in set(FRAMES["preview_hidden"]) | set(FRAMES["preview_overrides"]):
            rejected.update(FRAMES["prefer"][key.partition("/")[2]])
        self.assertFalse(assigned & rejected, assigned & rejected)
        self.assertIsNone(mapping["norte"]["F23"])
        self.assertIn(STEM, assigned)

    def test_override_validation_is_independent_of_hidden_slots(self):
        cfg = dict(FRAMES, preview_hidden=[], preview_overrides={"index/F01": "bad"})
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "1"}):
            with self.assertRaisesRegex(site_builder.BuildError, "invalid candidates"):
                site_builder.assign_site_frames(self.pages, cfg)

    def test_draft_cannot_be_production_override(self):
        self.assertEqual(MANIFEST["status"], "APPROVED_FOR_PREVIEW")
        self.assertTrue(MANIFEST["approved"])
        self.assertFalse(MANIFEST["approval"]["production_release"])
        self.assertEqual(FRAMES.get("page_overrides"), {})
        self.assertEqual(FRAMES["preview_overrides"]["index/F01"], [STEM])

    def test_preview_approval_does_not_authorize_production_assignment(self):
        cfg = dict(FRAMES, page_overrides={"index/F01": [STEM]})
        with patch.dict(os.environ, {"ARTEMIS_VISUAL_PREVIEW": "0"}):
            with self.assertRaisesRegex(site_builder.BuildError, "release not authorized"):
                site_builder.assign_site_frames(self.pages, cfg)

    def test_each_approved_image_has_its_own_caption_and_original_mobile_source(self):
        from PIL import Image
        registry = json.loads((SCRIPTS / "visual_assets.json").read_text(encoding="utf-8"))
        sources = set()
        for stem, entry in registry["assets"].items():
            manifest = site_builder.visual_manifest(stem)
            mobile = manifest["mobile"]
            self.assertEqual(mobile["composition"], "independent_portrait_recomposition")
            self.assertNotIn(mobile["sha256"], sources)
            sources.add(mobile["sha256"])
            with Image.open(ROOT / mobile["source"]) as im:
                self.assertAlmostEqual(im.width / im.height, .8, delta=.001)
            for lang in ("en", "es", "de", "fr", "ru"):
                with patch.object(site_builder, "LOCALE", lang):
                    variant = site_builder.image_variant(stem)
                self.assertEqual(variant["caption"], manifest["captions"][lang])
                self.assertIn("mobile-20261105", variant["mobile_srcset"])
        self.assertEqual(len(sources), 5)

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

    def test_mobile_locator_is_reproducible_and_preserves_point_coordinates(self):
        from location_locator import mobile_svg, project, POINTS
        path = ROOT / "app/static/tenerife/site/img/la-quinta-context-locator-mobile-20261105.svg"
        self.assertEqual(path.read_text(encoding="utf-8"), mobile_svg())
        root = ET.fromstring(mobile_svg())
        points = {el.attrib["id"]: el for el in root.findall("{http://www.w3.org/2000/svg}circle")}
        for key, coordinate in POINTS.items():
            x, y = project(*coordinate)
            self.assertAlmostEqual(float(points[key].attrib["cx"]), x, places=2)
            self.assertAlmostEqual(float(points[key].attrib["cy"]), y, places=2)
        self.assertLess(float(points["puerto"].attrib["cx"]), float(points["la_quinta"].attrib["cx"]))
        self.assertGreater(float(points["titsa"].attrib["cy"]), float(points["la_quinta"].attrib["cy"]))

    def test_mobile_picture_contract(self):
        variant = site_builder.image_variant(STEM)
        self.assertEqual(variant["width"], 1600)
        self.assertEqual(variant["height"], 900)
        self.assertIn("mobile-20261105-640.webp", variant["mobile_srcset"])
        self.assertIn("mobile-20261105-800.webp", variant["mobile_srcset"])
        self.assertTrue(variant["caption"])

    def test_future_stages_use_the_nine_source_rows_in_every_language(self):
        for lang in ("en", "es", "de", "fr", "ru"):
            copy_dir = SCRIPTS / ("copy_v3" if lang == "ru" else "copy_" + lang)
            _, blocks = site_builder.parse_page((copy_dir / "08_stroyka.md").read_text(encoding="utf-8"))
            table = site_builder.table_item(next(b for b in blocks if b["kind"] == "table"))
            stages = site_builder.prospective_stages(table)
            self.assertEqual(len(stages), 9, lang)
            self.assertEqual([s["result"] for s in stages], [r[1] for r in table["rows"]])
            self.assertTrue(I18N[lang]["visual"]["future_stages"]["disclosure"])

    def test_future_stages_reject_missing_or_reordered_source_numbers(self):
        table = {"kind": "table", "head": ["Stage", "Result"],
                 "rows": [[f"{n}. Phase", "Future result"] for n in range(1, 10)]}
        table["rows"][3][0] = "6. Skipped stage"
        self.assertIsNone(site_builder.prospective_stages(table))


if __name__ == "__main__":
    unittest.main()
