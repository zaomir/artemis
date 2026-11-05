#!/usr/bin/env python3
"""Stage a generated Artemis illustration for review; never publish or remap frames.

Example:
  python3 scripts/tenerife_site_build/intake_watercolour.py \
    --source /path/to/approved-download.png \
    --stem artemis-watercolour-norte-20261105 \
    --category ART-04 --truth-level C1 --page norte --frame F21 \
    --provider ElevenLabs --generation-id wBYf7vERpRPDQRSzObyC \
    --rights-basis "Original artwork generated for Artemis; verify prior to release" --write

To provide a separate mobile composition, add --mobile-source /path/to/portrait.png.
All outputs stay REVIEW and are not assigned to production without a second,
verified step in frames.json, alts.json, and the five-locale caption manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required: python3 -m pip install Pillow") from exc

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "static" / "tenerife" / "site" / "img"
MANIFESTS = ROOT / "docs" / "visual" / "candidates"
WIDTHS = (640, 800, 1024, 1600)
MOBILE_WIDTHS = (640, 800)
STEM_RE = re.compile(r"^artemis-watercolour-[a-z0-9-]+$")
FRAME_RE = re.compile(r"^F[0-9]{2}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_rgb(path: Path, *, min_width: int = 1024, min_height: int = 512) -> Image.Image:
    if not path.is_file():
        raise ValueError(f"source image missing: {path}")
    with Image.open(path) as inp:
        inp.load()
        if inp.width < min_width or inp.height < min_height:
            raise ValueError(f"source image too small: {inp.width}x{inp.height}")
        return inp.convert("RGB")


def resize_width(img: Image.Image, width: int) -> Image.Image:
    h = round(img.height * width / img.width)
    return img.resize((width, h), Image.Resampling.LANCZOS)


def encoded(img: Image.Image, fmt: str) -> bytes:
    stream = io.BytesIO()
    if fmt == "JPEG":
        img.save(stream, format=fmt, quality=91, progressive=True, optimize=True)
    else:
        img.save(stream, format=fmt, quality=80, method=6)
    return stream.getvalue()


def build_assets(master: Image.Image, stem: str, mobile: Image.Image | None) -> list[dict]:
    files = [{"name": f"{stem}.jpg", "data": encoded(resize_width(master, 1600), "JPEG"), "size": [1600, round(master.height * 1600 / master.width)]}]
    for w in WIDTHS:
        files.append({"name": f"{stem}-{w}.webp",
                      "data": encoded(resize_width(master, w), "WEBP"),
                      "size": [w, round(master.height * w / master.width)]})
    if mobile is not None:
        ratio = mobile.width / mobile.height
        if not 0.79 <= ratio <= 0.81:
            raise ValueError(f"mobile input must be an original 4:5 composition (got {ratio:.3f})")
        for w in MOBILE_WIDTHS:
            files.append({"name": f"{stem}-mobile-{w}.webp",
                          "data": encoded(resize_width(mobile, w), "WEBP"),
                          "size": [w, round(mobile.height * w / mobile.width)]})
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--mobile-source", type=Path)
    ap.add_argument("--stem", required=True)
    ap.add_argument("--category", required=True, choices=[f"ART-0{i}" for i in range(1, 7)])
    ap.add_argument("--truth-level", required=True, choices=("C1", "C2"))
    ap.add_argument("--page", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--generation-id", required=True)
    ap.add_argument("--rights-basis", required=True)
    ap.add_argument("--write", action="store_true", help="Write image variants and REVIEW manifest")
    args = ap.parse_args(argv)
    if not STEM_RE.fullmatch(args.stem):
        ap.error("stem must be artemis-watercolour-[a-z0-9-]+")
    if not FRAME_RE.fullmatch(args.frame):
        ap.error("frame must be Fxx")
    if not re.fullmatch(r"[a-z0-9-]+", args.page):
        ap.error("page must be a canonical slug")
    master = load_rgb(args.source)
    mobile = load_rgb(args.mobile_source, min_width=640, min_height=800) if args.mobile_source else None
    raw_sha = digest(args.source.read_bytes())
    files = build_assets(master, args.stem, mobile)
    manifest_path = MANIFESTS / f"{args.stem}.json"
    outputs = [OUT / e["name"] for e in files] + [manifest_path]
    already = [str(p) for p in outputs if p.exists()]
    if already:
        raise SystemExit(f"Refusing to overwrite pre-existing assets: {already}")
    manifest = {
        "schema": "artemis-watercolour-asset/1",
        "status": "REVIEW_NEEDS_VISUAL_APPROVAL",
        "approved": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "stem": args.stem,
        "category": args.category,
        "truth_level": args.truth_level,
        "target": {"page": args.page, "frame": args.frame},
        "source": {"name": args.source.name, "sha256": raw_sha,
                   "dimensions": [master.width, master.height],
                   "provider": args.provider, "generation_id": args.generation_id},
        "rights_basis": args.rights_basis,
        "caption_and_alt": "REQUIRED in all EN/ES/DE/FR/RU before assignment",
        "mobile_composition_verified": mobile is not None,
        "architectural_status": "concept only, not a verified property",
        "no_auto_page_assignment": True,
        "variants": [{"name": e["name"], "dimensions": e["size"],
                      "sha256": digest(e["data"]), "bytes": len(e["data"])} for e in files],
    }
    if not args.write:
        print(json.dumps({"would_write": [str(p) for p in outputs],
                          "manifest": manifest}, indent=2, ensure_ascii=False))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for e in files:
            dest = OUT / e["name"]
            with dest.open("xb") as stream:
                stream.write(e["data"])
            written.append(dest)
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        written.append(manifest_path)
    except Exception:
        for p in reversed(written):
            p.unlink(missing_ok=True)
        raise
    print(json.dumps({"status": "REVIEW_ONLY", "manifest": str(manifest_path),
                      "files": len(files), "source_sha256": raw_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
