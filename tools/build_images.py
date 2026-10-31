#!/usr/bin/env python3
"""Responsive image variants for the Crete pages (QA ARTEMIS-QA-20261031-P02 / P05).

Reads the original JPEGs in app/static/img/ (never modified) and writes
app/static/img/opt/<name>-<width>.{avif,webp,jpg} plus app/static/img/opt/manifest.json,
which app.py loads to render <picture> with srcset/sizes/width/height (templates/index.html).
Also writes the Open Graph image app/static/img/og-crete-1200x630.jpg (1200x630, <= 300 KB).

nginx serves /static/ straight from the checkout, so the outputs are committed.
Re-run after replacing or adding an original:

    python3 tools/build_images.py            # (re)build all variants + manifest
    python3 tools/build_images.py --check    # verify committed outputs match the manifest (no writes)

Needs Pillow >= 11.3 with AVIF + WebP support (pip install "Pillow>=11.3").
Output is deterministic for a given Pillow/libavif/libwebp/libjpeg build: no EXIF/ICC/timestamps
are written, encoder settings are fixed below. The versions used are recorded in manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_DIR = REPO / "app" / "static" / "img"
OUT_DIR = SRC_DIR / "opt"
MANIFEST = OUT_DIR / "manifest.json"
OG_OUT = SRC_DIR / "og-crete-1200x630.jpg"
OG_SIZE = (1200, 630)
OG_MAX_BYTES = 300 * 1024

# name -> target widths (px). Widths above the original width are dropped.
IMAGES = {
    "hero": [640, 960, 1280, 1600, 2400],  # full-bleed, object-fit:cover (also 100vh tall on portrait)
    "siteplan": [480, 800, 1200],
    "map_island": [480, 800, 1200],
    "double_room": [480, 800],
    "attic_room": [480, 800],
    "suite": [480, 800],
    "villa_ext": [480, 800],
    "spa": [480, 800, 1200],
    "restaurant_main": [480, 800, 1200],
}
# fixed encoder settings (changing them changes every output byte)
AVIF = {"quality": 50, "speed": 4, "subsampling": "4:2:0"}
WEBP = {"quality": 72, "method": 6}
JPEG = {"quality": 76, "optimize": True, "progressive": True, "subsampling": "4:2:0"}
OG_JPEG = {"quality": 82, "optimize": True, "progressive": True, "subsampling": "4:2:0"}


def _pil():
    try:
        from PIL import Image, features
    except ImportError:  # pragma: no cover
        sys.exit('Pillow is required: pip install "Pillow>=11.3"')
    for codec in ("avif", "webp", "jpg"):
        if not features.check(codec):
            sys.exit(f"this Pillow build has no {codec} support")
    return Image, features


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _resize(im, width):
    from PIL import Image

    if width >= im.width:
        return im.copy()
    h = round(im.height * width / im.width)
    return im.resize((width, h), Image.Resampling.LANCZOS)


def build() -> dict:
    Image, features = _pil()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "_generated_by": "tools/build_images.py",
        "_encoders": {
            "pillow": __import__("PIL").__version__,
            "avif": features.version("avif"),
            "webp": features.version("webp"),
            "jpg": features.version("jpg"),
            "settings": {"avif": AVIF, "webp": WEBP, "jpeg": JPEG, "og_jpeg": OG_JPEG},
        },
        "images": {},
        "files": {},
    }
    for name, widths in IMAGES.items():
        src = SRC_DIR / f"{name}.jpg"
        with Image.open(src) as im0:
            im = im0.convert("RGB")
        ws = sorted({w for w in widths if w < im.width} | ({im.width} if max(widths) >= im.width else set()))
        entry = {"src": f"{name}.jpg", "width": im.width, "height": im.height, "widths": ws}
        for w in ws:
            v = _resize(im, w)
            for ext, kw, fmt in (("avif", AVIF, "AVIF"), ("webp", WEBP, "WEBP"), ("jpg", JPEG, "JPEG")):
                p = OUT_DIR / f"{name}-{w}.{ext}"
                v.save(p, fmt, **kw)
                out["files"][p.name] = {"bytes": p.stat().st_size, "sha256": _sha(p)}
        out["images"][name] = entry
    # Open Graph: centre crop to 1200x630 from the hero original
    with Image.open(SRC_DIR / "hero.jpg") as im0:
        im = im0.convert("RGB")
    tw, th = OG_SIZE
    scale = max(tw / im.width, th / im.height)
    rs = im.resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)
    left, top = (rs.width - tw) // 2, (rs.height - th) // 2
    og = rs.crop((left, top, left + tw, top + th))
    og.save(OG_OUT, "JPEG", **OG_JPEG)
    if OG_OUT.stat().st_size > OG_MAX_BYTES:
        sys.exit(f"{OG_OUT.name} is {OG_OUT.stat().st_size} B > {OG_MAX_BYTES} B")
    out["og"] = {"file": OG_OUT.name, "width": tw, "height": th, "type": "image/jpeg",
                 "bytes": OG_OUT.stat().st_size, "sha256": _sha(OG_OUT)}
    MANIFEST.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    stale = sorted(p.name for p in OUT_DIR.iterdir() if p.name != MANIFEST.name and p.name not in out["files"])
    for n in stale:
        (OUT_DIR / n).unlink()
    return out


def check() -> int:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = []
    for n, meta in m["files"].items():
        p = OUT_DIR / n
        if not p.is_file() or _sha(p) != meta["sha256"]:
            bad.append(n)
    if _sha(OG_OUT) != m["og"]["sha256"]:
        bad.append(OG_OUT.name)
    for name, e in m["images"].items():
        for w in e["widths"]:
            for ext in ("avif", "webp", "jpg"):
                if f"{name}-{w}.{ext}" not in m["files"]:
                    bad.append(f"{name}-{w}.{ext} (not in manifest)")
    print("OK" if not bad else "MISMATCH: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify outputs against manifest.json, write nothing")
    a = ap.parse_args()
    if a.check:
        sys.exit(check())
    res = build()
    total = sum(f["bytes"] for f in res["files"].values())
    print(f"{len(res['files'])} files, {total} B; og {res['og']['bytes']} B")
