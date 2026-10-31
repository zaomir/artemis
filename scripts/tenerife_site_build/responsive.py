"""Responsive images for /tenerife/ pages (task 3, speed).

<img src="/static/tenerife/site/img/X.jpg" alt="..."> becomes
<picture><source type="image/webp" srcset="X-640.webp 640w, X-800.webp 800w, X-1024.webp 1024w, X-1600.webp 1600w" sizes="...">
<img src="X.jpg" width=".." height=".." ...></picture>
First image in <main> = hero: fetchpriority=high, eager, plus <link rel=preload> in <head>.
Others: loading=lazy decoding=async. JPEG stays as fallback. Idempotent.
"""
import re
import struct
from pathlib import Path

WIDTHS = (640, 800, 1024, 1600)  # 800w: phones at DPR ~1.75 (372 css px) get ~55 KB instead of 1024w ~90 KB
SIZES_HERO = "(min-width: 1080px) 560px, (min-width: 800px) 52vw, calc(100vw - 40px)"
SIZES_TWO = "(min-width: 1080px) 512px, (min-width: 800px) 48vw, calc(100vw - 40px)"
SIZES_FULL = "(min-width: 1080px) 1040px, calc(100vw - 40px)"


def jpeg_size(path):
    b = Path(path).read_bytes()
    i = 2
    while i < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    raise ValueError(f"no SOF in {path}")


def ensure_webp(jpg):
    """Create X-640/800/1024/1600.webp next to X.jpg if missing (needs Pillow; committed files otherwise)."""
    jpg = Path(jpg)
    missing = [w for w in WIDTHS if not jpg.with_name(f"{jpg.stem}-{w}.webp").exists()]
    if not missing:
        return True
    try:
        from PIL import Image
    except ImportError:
        return False
    im = Image.open(jpg).convert("RGB")
    for w in missing:
        h = round(im.height * w / im.width)
        im.resize((w, h), Image.LANCZOS).save(jpg.with_name(f"{jpg.stem}-{w}.webp"), "WEBP", quality=78, method=6)
    return True


def _sizes(html, pos):
    before = html[:pos]
    if before.rfind('<section class="hero">') > before.rfind("</section>"):
        return SIZES_HERO
    if before.rfind('<div class="grid two">') > before.rfind("</div>"):
        return SIZES_TWO
    return SIZES_FULL


def responsive(html, static_site_dir):
    static_site_dir = Path(static_site_dir)
    main_at = html.find("<main")
    out, last, hero_done, preload = [], 0, False, None
    for m in re.finditer(r'<img src="/static/tenerife/site/img/([a-z0-9-]+)\.jpg" alt="([^"]*)">', html):
        stem, alt = m.group(1), m.group(2)
        jpg = static_site_dir / "img" / f"{stem}.jpg"
        if not jpg.exists() or not ensure_webp(jpg):
            continue
        w, h = jpeg_size(jpg)
        base = f"/static/tenerife/site/img/{stem}"
        srcset = ", ".join(f"{base}-{x}.webp {x}w" for x in WIDTHS)
        sizes = _sizes(html, m.start())
        hero = not hero_done and m.start() > main_at
        if hero:
            hero_done = True
            attrs = 'fetchpriority="high" decoding="async"'
            preload = (f'<link rel="preload" as="image" type="image/webp" imagesrcset="{srcset}" '
                       f'imagesizes="{sizes}" fetchpriority="high">')
        else:
            attrs = 'loading="lazy" decoding="async"'
        out.append(html[last:m.start()])
        out.append(f'<picture><source type="image/webp" srcset="{srcset}" sizes="{sizes}">'
                   f'<img src="{base}.jpg" alt="{alt}" width="{w}" height="{h}" {attrs}></picture>')
        last = m.end()
    out.append(html[last:])
    html = "".join(out)
    if preload and 'rel="preload" as="image"' not in html:
        html = html.replace('<link rel="stylesheet" href="/static/tenerife/site/style.css">',
                            preload + '\n<link rel="stylesheet" href="/static/tenerife/site/style.css">', 1)
    return html
