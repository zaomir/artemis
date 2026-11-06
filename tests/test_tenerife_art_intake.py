"""Unit tests for REVIEW-only generated watercolour asset ingestion."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tenerife_site_build" / "intake_watercolour.py"


@unittest.skipIf(Image is None, "Pillow not available")
class WatercolourAssetIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("intake_watercolour", SCRIPT)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.png"
        self.mobile = self.root / "mobile.png"
        Image.new("RGB", (1280, 720), "#e8d8b9").save(self.source)
        Image.new("RGB", (800, 1000), "#819da8").save(self.mobile)

    def args(self, *extra):
        return ["--source", str(self.source),
                "--stem", "artemis-watercolour-test-20261105",
                "--category", "ART-04", "--truth-level", "C1",
                "--page", "norte", "--frame", "F21",
                "--provider", "UnitTest", "--generation-id", "test-generation",
                "--rights-basis", "Test-only source", *extra]

    def test_variants_are_complete_and_hashable(self):
        master = self.mod.load_rgb(self.source)
        mobile = self.mod.load_rgb(self.mobile, min_width=640, min_height=800)
        files = self.mod.build_assets(master, "artemis-watercolour-test-20261105", mobile)
        self.assertEqual(len(files), 7)
        self.assertEqual(len({f["name"] for f in files}), len(files))
        self.assertTrue(all(len(self.mod.digest(f["data"])) == 64 for f in files))
        self.assertEqual(files[-1]["size"], [800, 1000])

    def test_dry_run_writes_nothing(self):
        out = self.root / "assets"
        manifests = self.root / "manifests"
        with patch.object(self.mod, "OUT", out), patch.object(self.mod, "MANIFESTS", manifests):
            with redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(self.mod.main(self.args()), 0)
        self.assertIn("would_write", stdout.getvalue())
        self.assertFalse(out.exists())
        self.assertFalse(manifests.exists())

    def test_review_manifest_has_no_auto_assignment(self):
        out = self.root / "assets"
        manifests = self.root / "manifests"
        with patch.object(self.mod, "OUT", out), patch.object(self.mod, "MANIFESTS", manifests):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(self.mod.main(self.args("--mobile-source", str(self.mobile), "--write")), 0)
            doc = json.loads((manifests / "artemis-watercolour-test-20261105.json").read_text())
            self.assertEqual(doc["status"], "REVIEW_NEEDS_VISUAL_APPROVAL")
            self.assertFalse(doc["approved"])
            self.assertTrue(doc["no_auto_page_assignment"])
            self.assertEqual(len(doc["variants"]), 7)
            self.assertTrue(all((out / f["name"]).exists() for f in doc["variants"]))
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    self.mod.main(self.args("--mobile-source", str(self.mobile), "--write"))

    def test_mobile_crop_cannot_be_fake_landscape(self):
        with self.assertRaisesRegex(ValueError, "4:5"):
            self.mod.build_assets(self.mod.load_rgb(self.source),
                                      "artemis-watercolour-test-20261105",
                                      self.mod.load_rgb(self.source))


if __name__ == "__main__":
    unittest.main()
