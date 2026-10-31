"""Fixes from QA protocol 2026-10-31 prod-smoke be0676b (ARTEMIS-QA-20261031-P02..P08).

P02 responsive images (tools/build_images.py outputs, <picture> with avif/webp/jpg, srcset/sizes,
width/height, lazy below the fold, fetchpriority=high hero) · P03 contrast / link / target-size CSS ·
P04 GET /health · P05 og:image 1200x630 <= 300 KB with width/height/type · P07 one `User-agent: *`
group after Cloudflare's managed block · P08 /favicon.ico. Browser checks (axe, weight, Lighthouse)
run outside the unit tests."""
import hashlib
import importlib
import json
import os
import re
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
STATIC = ROOT / "app" / "static"
OPT = STATIC / "img" / "opt"
MANIFEST = json.loads((OPT / "manifest.json").read_text(encoding="utf-8"))
LANGS = ("en", "ru", "es", "fr")


def _jpeg_size(path: Path):
    """(width, height) from the first SOFn marker, no Pillow needed on the server venv."""
    data = path.read_bytes()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ValueError("no SOF marker")


def _lum(hexcol):
    c = [int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, path)
        return r.get_data(as_text=True)


class HealthTest(Base):
    """P04: /health was 308 -> /health/ -> 404."""

    def test_health_ok_json(self):
        r = self.client.get("/health", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "application/json")
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertNotIn("Set-Cookie", r.headers)

    def test_health_no_db_and_no_secrets(self):
        secrets = {"ARTEMIS_ADMIN_TOKEN": "adm-SECRET-123", "ARTEMIS_TG_BOT_TOKEN": "123:SECRET-tg"}
        with mock.patch.dict(os.environ, secrets), mock.patch("sqlite3.connect", side_effect=AssertionError("DB")):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        for v in secrets.values():
            self.assertNotIn(v, body)
        self.assertFalse(os.path.exists(self.mod.DB))

    def test_health_get_only(self):
        self.assertEqual(self.client.post("/health").status_code, 405)


class RobotsTest(Base):
    """P07: Cloudflare prepends its managed block with `User-agent: *`; the origin must not add a second one."""

    def test_origin_has_no_user_agent_group(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["Content-Type"])
        body = r.get_data(as_text=True)
        self.assertNotRegex(body, r"(?im)^\s*user-agent\s*:")
        self.assertNotRegex(body, r"(?im)^\s*disallow\s*:")
        self.assertIn("Sitemap: https://artemisresort.com/sitemap.xml", body)

    def test_one_star_group_behind_cloudflare(self):
        cf = ("# BEGIN Cloudflare Managed content\n\nUser-agent: *\nContent-Signal: search=yes,ai-train=no,"
              "use=reference\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\n# END Cloudflare Managed Content\n\n")
        served = cf + self.client.get("/robots.txt").get_data(as_text=True)
        self.assertEqual(len(re.findall(r"(?im)^user-agent:\s*\*\s*$", served)), 1)


class FaviconTest(Base):
    """P08: /favicon.ico was 308 -> /favicon.ico/ -> 404; serve the existing static asset."""

    def test_favicon_root(self):
        r = self.client.get("/favicon.ico", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "image/x-icon")
        self.assertEqual(r.data, (STATIC / "favicon.ico").read_bytes())
        self.assertNotIn("Set-Cookie", r.headers)
        r.close()


class ImagesTest(Base):
    """P02 / P05."""

    def test_manifest_files_exist_and_match(self):
        self.assertTrue(MANIFEST["files"])
        for name, meta in MANIFEST["files"].items():
            p = OPT / name
            self.assertTrue(p.is_file(), name)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), meta["sha256"], name)
        on_disk = {p.name for p in OPT.iterdir()} - {"manifest.json"}
        self.assertEqual(on_disk, set(MANIFEST["files"]))
        for name, e in MANIFEST["images"].items():
            self.assertTrue((STATIC / "img" / e["src"]).is_file(), name)
            for w in e["widths"]:
                self.assertEqual(_jpeg_size(OPT / f"{name}-{w}.jpg")[0], w, (name, w))

    def test_budget_hero_and_page(self):
        files = MANIFEST["files"]
        self.assertLessEqual(files["hero-2400.avif"]["bytes"], 250 * 1024)
        self.assertLessEqual(files["hero-1600.webp"]["bytes"], 250 * 1024)
        # worst case = biggest avif of every image on one page (real pages pick smaller ones)
        worst = sum(max(files[f"{n}-{w}.avif"]["bytes"] for w in e["widths"]) for n, e in MANIFEST["images"].items())
        self.assertLess(worst, 1024 * 1024)

    def test_page_markup(self):
        for lang in LANGS:
            h = self.page(f"/{lang}/")
            self.assertNotIn("/static/img/hero.jpg", h)
            self.assertNotRegex(h, r'src="/static/img/[a-z_]+\.jpg"')
            pics = re.findall(r"<picture>.*?</picture>", h, re.S)
            self.assertEqual(len(pics), len(MANIFEST["images"]), lang)
            for i, pic in enumerate(pics):
                self.assertIn('type="image/avif"', pic)
                self.assertIn('type="image/webp"', pic)
                img = re.search(r"<img [^>]+>", pic).group(0)
                for attr in ("srcset=", "sizes=", "width=", "height=", 'decoding="async"'):
                    self.assertIn(attr, img)
                if i == 0:  # hero
                    self.assertIn('fetchpriority="high"', img)
                    self.assertNotIn('loading="lazy"', img)
                    self.assertIn("hero-", img)
                else:
                    self.assertIn('loading="lazy"', img)
                    self.assertNotIn("fetchpriority", img)
            self.assertEqual(h.count('fetchpriority="high"'), 1)
            self.assertIn('<div class="hero-bg" role="img" aria-label="', h)

    def test_og_image(self):
        og = MANIFEST["og"]
        p = STATIC / "img" / og["file"]
        self.assertEqual(_jpeg_size(p), (1200, 630))
        self.assertLessEqual(p.stat().st_size, 300 * 1024)
        for lang in LANGS:
            h = self.page(f"/{lang}/")
            self.assertIn(f'<meta property="og:image" content="https://artemisresort.com/static/img/{og["file"]}">', h)
            self.assertIn('<meta property="og:image:width" content="1200">', h)
            self.assertIn('<meta property="og:image:height" content="630">', h)
            self.assertIn('<meta property="og:image:type" content="image/jpeg">', h)
            self.assertEqual(self.client.get(f"/static/img/{og['file']}").status_code, 200)

    def test_build_script_present(self):
        src = (ROOT / "tools" / "build_images.py").read_text(encoding="utf-8")
        self.assertIn("--check", src)
        self.assertEqual(MANIFEST["_generated_by"], "tools/build_images.py")


class A11yCssTest(Base):
    """P03 (axe on prod be0676b): contrast, link-in-text-block, footer target size."""

    def test_crete_footer_version_contrast(self):
        h = self.page("/en/")
        footer = h[h.index("<footer>"):h.index("</footer>")]
        ver = re.findall(r"<p style=\"([^\"]*)\">v", footer)
        self.assertTrue(ver)
        self.assertNotIn("opacity", ver[0])
        self.assertIn("color:var(--muted)", ver[0])
        self.assertGreaterEqual(contrast("#8a9bb0", "#0d1b2a"), 4.5)  # --muted on --dark

    def test_crete_footer_link_target(self):
        h = self.page("/en/")
        self.assertRegex(h, r"\.footer-links a\{[^}]*min-height:44px")

    def test_tenerife_form_link_and_mailto(self):
        css = (STATIC / "tenerife" / "site" / "style.css").read_text(encoding="utf-8")
        rule = re.search(r'form\.wl \.check a, footer a\[href\^="mailto:"\] \{([^}]*)\}', css)
        self.assertTrue(rule)
        self.assertIn("color: var(--ink)", rule.group(1))
        self.assertIn("text-decoration: underline", rule.group(1))
        self.assertIn("min-height: 44px", css)
        self.assertGreaterEqual(contrast("#1C1A17", "#F4F1EA"), 4.5)  # --ink on --stone
        self.assertLess(contrast("#8A6A45", "#F4F1EA"), 4.5)  # why: --bronze on --stone is 4.40
        # generated file = fonts.css + author CSS + extra.css: the fix must also be in the build source
        extra = (ROOT / "scripts" / "tenerife_site_build" / "extra.css").read_text(encoding="utf-8")
        self.assertTrue(css.endswith(extra))

    def test_tenerife_legal_footer_target(self):
        css = (STATIC / "tenerife" / "base.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"footer\.site a\{[^}]*min-height:44px")


if __name__ == "__main__":
    unittest.main()
