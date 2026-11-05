"""Build the EN Tenerife site (14 pages, Spanish slugs) from the verbatim copy in copy_en/.

  python3 scripts/tenerife_site_build/build_v3.py     # copy_en/*.md -> app/tenerife_site/*.html

EN r2 (founder t122u / Lead GO 05.11.2026, BLK-20261031-20; onto main 3df77a4): the public /tenerife/ site is English only. The copy
(copy_en/, Kimi/web-designer, 01.11.2026) already carries ONLY the approved ranges (price per metre ≈2,900–3,100 €/m²
from the queue → ≈3,700–3,900 €/m² by completion, expected dividend 2.5–3.5% a year before tax), so the pages show the
copy as written: no model.json token substitution, no figure hiding, no calculator (page 05 is «Terms»,
/tenerife/condiciones/). model.json stays in app/tenerife_site/data/ (server side only, never served).
Texts are taken as written (no edits). The only transformations:
  * [FRAME Fxx] (or the RU [КАДР Fxx]) markers -> <picture> of an existing Canary Stone photo (frames.json);
  * markdown (# ## ### | - 1. ** [](...)) -> HTML through Jinja components in
    app/templates/tenerife/site/ (hero, facts, section, frame, table, cta, footer).
The build fails if a marker, '{{', '{%', any HTML comment other than <!--email_off--> markers, Cyrillic text, a
forbidden figure (FORBIDDEN_FIGURES) or a calculator link / script reaches the output. email_off.wrap() is the last step.
"""
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from email_off import unprotected, wrap  # noqa: E402

COPY = HERE / "copy_en"
SITE = ROOT / "app" / "tenerife_site"
STATIC = ROOT / "app" / "static"
IMG = STATIC / "tenerife" / "site" / "img"
TEMPLATES = ROOT / "app" / "templates" / "tenerife" / "site"
MODEL = ROOT / "app" / "tenerife_site" / "data" / "model.json"   # server side only (never under static, never served)
BASE_URL = "https://artemisresort.com"
# Approved EN copy (Kimi, 01.11.2026; 16+17 privacy «Telegram + email» 05.11.2026, QA PASS; sha256 per file confirmed by the Lead 05.11.2026): each file pinned, and the
# combined sha256 of copy_files() (01-18 joined like the RU build). TENERIFE_COPY_SHA256=<sha> overrides the combined
# value for a build / test run; a changed file fails the build until it is re-approved and re-pinned here.
COPY_FILE_SHA256 = {
    "01_glavnaya.md": "15ed52b2f6341a9cd904ee2a255d0095ec1691762467b5b7a8ff4b858e80c4e5",
    "02_sever.md": "db210e3988551c98b55c1de0b2a2f7441662056d00f7eea6653abf0a0e02d8a0",
    "03_rezidencii.md": "e7becf1dde0980943b62d90c68dce8c99a64aa76aa8031a431c7559cb5b14138",
    "04_akcii.md": "87f925bcef7c7c44180e555f8bf7129e60120fc2ebe53171ff66c457f200c080",
    "05_kalkulyator.md": "07ee58b6e5116ef118b59470f213c96adb24e8243128fc18dc14657f5062ec0c",
    "06_arenda.md": "9cf1a56a7183aa7bf832fada043f1150ccb6e44def4d5028bdfa35687194f5f5",
    "07_energiya.md": "4008843ceda4adf2d3d1822720af082b997d82644ce008bbb0864e84a85615a8",
    "08_stroyka.md": "1065050afe778e786b0bc20607cd4dbdffd54e694df9654f6c1880da1329aeb7",
    "09_sdelka.md": "cc8617081fa85dfc8a7857b79c1a40fd19adc59a2bd8e1a90a481951de99994d",
    "10_voprosy.md": "2ec743163125175e8627ed57f129eab2b62533d36814642f90467426083dbbbf",
    "11_simon.md": "6ec1fcf18e1a58c73133744ce813810dcc9fe07f46a2114a8bbbabc4a5637a14",
    "12_rynok.md": "32bbb83feae3fe222bc1c6c415a018bbc6fe0c339d18bc86aa07ecbc45865a39",
    "13_boris.md": "a11c59a265cbd83afb7f9e418c8e24add147db88795aaaa53cc2916379cc10cb",
    "14_podval.md": "2ab7720e8770e4fd02e17f9c8615aaa4b7f6befa248bd5cf2eeff6b9762a669f",
    "15_impressum.md": "690680b4885b9ca44fcace1383e3825c5935d64b2773e0569d65e2532edf28a1",
    "16_privacy.md": "dbfd963514853f2de4b33b97459bbfd89f0dad2523719f304a2f0a38b457ad91",
    "17_forma.md": "32bb8774313318ea43ba682ee002fc11cbb2be2120f6794833391f8baf2bb7f5",
    "18_investoram.md": "88e4840ecbeb68b3cc347f5728a6691bef33a2b41ab0ebd28e9dbedddb8a2229",
}
COPY_SHA256_DEFAULT = "5c5b5d783cce14a9656c95a781e86d762a861eb81a8176821b86f27d5d55fb68"
COPY_SHA256 = os.environ.get("TENERIFE_COPY_SHA256", "").strip().lower() or COPY_SHA256_DEFAULT
WIDTHS = (640, 800, 1024, 1600)

# copy file -> output name (app/tenerife_site/<name>.html); URL comes from the copy's own «Slug» (Spanish slugs kept)
PAGES = [("01_glavnaya.md", "index"), ("02_sever.md", "norte"), ("03_rezidencii.md", "producto"),
         ("04_akcii.md", "acciones"), ("05_kalkulyator.md", "condiciones"), ("06_arenda.md", "alquiler"),
         ("07_energiya.md", "energia"), ("08_stroyka.md", "construccion"), ("09_sdelka.md", "proceso"),
         ("10_voprosy.md", "faq"), ("11_simon.md", "simon"), ("12_rynok.md", "mercado"), ("13_boris.md", "boris"),
         ("18_investoram.md", "inversores")]
FOOTER = "14_podval.md"
WA_RX = re.compile(r"\+[1-9]\d{7,14}")  # E.164, same rule as app/tenerife.py whatsapp_number()
# phone-like literal (not a CSS unicode-range U+…): + or 00, then ≥ 8 digits (spaces . - ( ) nbsp between)
PHONE_RX = re.compile(r"(?:(?<![Uu])\+|\b00)\d(?:[\s\u00a0.()\-]*\d){7,}")


def check_whatsapp_env():
    """Kimi r16: the build fails when TENERIFE_WHATSAPP is empty or invalid. The value is never printed and never
    written into the output (runtime slot <li data-tenerife-whatsapp hidden>, filled by app/tenerife.py)."""
    v = os.environ.get("TENERIFE_WHATSAPP", "").strip()
    if not v:
        raise BuildError("TENERIFE_WHATSAPP is empty: set it (E.164, e.g. +440000000000) before building")
    if not WA_RX.fullmatch(v):
        raise BuildError("TENERIFE_WHATSAPP is invalid (expected E.164: + then 8–15 digits); value not shown")


# footer «Pages.» names -> output name (names and order are the copy's)
NAV = {"Home": "index", "The North": "norte", "Residences": "producto", "Shares": "acciones",
       "Terms": "condiciones", "Rental": "alquiler", "Energy": "energia", "Construction": "construccion",
       "Process": "proceso", "For investors": "inversores", "FAQ": "faq", "Market and price per metre": "mercado",
       "Simon Subic": "simon", "Boris Ribaut": "boris"}
FORM_HOST_PAGE = "/tenerife/proceso/"

# DESIGN.md §5: pages 11 and 13 are long text (solid header, 760 px column); 05 and 10 have a short hero
LONG_PAGES = {"simon", "boris"}
SHORT_HERO = {"condiciones", "faq"}
# DESIGN.md C1: 7 links + «More»; labels are the footer's («Pages.»). Terms takes the calculator's place.
NAV_PRIMARY = ["norte", "producto", "acciones", "condiciones", "construccion", "proceso", "faq"]
NAV_MORE = ["alquiler", "energia", "inversores", "mercado", "simon", "boris"]

SIZES = {
    # must match site.css (DESIGN.md C2, C15): hero full-bleed (4:5 crop of a 16:9 photo below 768 px),
    # wide frame = container (max 1360), split = 6 of 12 columns, gallery = 2 columns, long text = 760 px.
    # Mobile hero: the 4:5 box shows the middle of a 16:9 photo (cover ≈ 2.2 × viewport width). sizes stays
    # 100vw on purpose: asking for the real 2.2× pulls the 1600w file and mobile LCP goes over 2.5 s
    # (Lighthouse). Proper fix = 4:5 mobile masters per hero (design gap, see README).
    "hero": "100vw",
    "wide": "(min-width: 1472px) 1360px, calc(100vw - 40px)",
    "split": "(min-width: 1024px) 50vw, 100vw",
    "half": "(min-width: 1472px) 668px, (min-width: 768px) 50vw, 100vw",
    "long": "(min-width: 800px) 760px, calc(100vw - 40px)",
}


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- EN r1 guards (BLK-20261031-20)
# The approved ranges must be visible; figures that were never approved must never appear (any separator).
_S = r"[\s\u00a0\u202f,.]?"
FORBIDDEN_FIGURES = re.compile(
    rf"(?<![\d,.])87{_S}€|€{_S}87(?![\d,.])|(?<![\d,.])2{_S}950(?!\d)|(?<![\d,.])3{_S}850(?!\d)"
    rf"|(?<![\d,.])3{_S}800{_S}[–-]{_S}4{_S}600(?!\d)|\bRIC\b|\bZEC\b")
APPROVED_RANGES = ("≈2,900–3,100", "≈3,700–3,900", "2.5–3.5%")
CYRILLIC_RX = re.compile(r"[\u0400-\u04FF]")
# the only Cyrillic allowed in a page: the endonym of one contact language in the waitlist <select>
CYRILLIC_ALLOWED = ('<option value="ru">Русский</option>',)
OLD_CALC_URL = "/tenerife/calculadora"


def check_en(name, out):
    """EN r1: no Cyrillic UI/copy, no forbidden figure, no calculator link / script / form field, no model.json."""
    probe = out
    for ok in CYRILLIC_ALLOWED:
        probe = probe.replace(ok, "")
    m = CYRILLIC_RX.search(probe)
    if m:
        raise BuildError(f"{name}: Cyrillic left in the EN page: …{probe[max(0, m.start() - 30):m.start() + 30]}…")
    m = FORBIDDEN_FIGURES.search(html.unescape(out))
    if m:
        raise BuildError(f"{name}: forbidden figure «{m.group(0)}»")
    for bad in (OLD_CALC_URL, "calc.js", "model.json", 'name="calc_', 'hreflang='):
        if bad in out:
            raise BuildError(f"{name}: «{bad}» in output (EN r1: no calculator, no model, no hreflang)")


# ---------------------------------------------------------------- copy
def copy_files():
    """The copy the build uses: 14 pages (01-13 + 18 investors), footer, legal, form."""
    names = sorted({f for f, _ in PAGES} | {FOOTER, "15_impressum.md", "16_privacy.md", FORMA})
    return [COPY / n for n in names]


def combined_sha():
    files = copy_files()
    s = "\n---\n\n".join(f.read_text(encoding="utf-8").rstrip("\n") + "\n" for f in files)
    return hashlib.sha256(s.encode()).hexdigest()


def check_copy():
    for f in copy_files():
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if got != COPY_FILE_SHA256.get(f.name):
            raise BuildError(f"copy_en/{f.name} sha256 {got} is not the approved one (copy changed: re-approve)")
    if combined_sha() != COPY_SHA256:
        raise BuildError(f"copy_en sha256 {combined_sha()} != {COPY_SHA256} (copy changed: re-approve)")


def load_model(path=MODEL):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- markdown subset
META_RX = re.compile(r"<!-- META\n(.*?)-->", re.S)
FRAME_RX = re.compile(r"^\[(?:FRAME|КАДР) (F\d\d)\]\s*(?:<!--.*?-->)?\s*$")   # EN copy: [FRAME Fxx]; RU: [КАДР Fxx]
BUTTON_RX = re.compile(r'^\*\*Button: "(.+)"\*\*$')
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def inline(s):
    """Escape + **bold** + [text](/url) + e-mail -> mailto. Nothing else is interpreted."""
    out, pos = [], 0
    for m in re.finditer(r"\[([^\]]+)\]\((/[^)\s]*)\)", s):
        out.append(_inline_text(s[pos:m.start()]))
        out.append(f'<a href="{html.escape(m.group(2))}">{_inline_text(m.group(1))}</a>')
        pos = m.end()
    out.append(_inline_text(s[pos:]))
    return "".join(out)


def _inline_text(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = EMAIL_RX.sub(lambda m: f'<a href="mailto:{m.group(0)}">{m.group(0)}</a>', s)
    if "*" in s:
        raise BuildError(f"unparsed markdown emphasis: {s[:80]}")
    return s


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_page(md):
    """-> (meta dict, blocks list). Blocks: dict(kind=...)."""
    meta = {}
    m = META_RX.search(md)
    if m:
        for line in m.group(1).splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                meta[k.strip()] = v.strip()
    body = META_RX.sub("", md)
    lines = body.splitlines()
    blocks, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("<!--"):                       # service comment (possibly multi-line)
            while "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        fm = FRAME_RX.match(s)
        if fm:
            blocks.append({"kind": "frame", "id": fm.group(1)})
            i += 1
            continue
        if "<!--" in s or "[КАДР" in s or "[FRAME" in s:
            raise BuildError(f"comment/marker inside text line: {s[:80]}")
        bm = BUTTON_RX.match(s)
        if bm:
            micro = lines[i + 1].strip() if i + 1 < n else ""
            blocks.append({"kind": "button", "text": bm.group(1), "micro": micro})
            i += 2
            continue
        hm = re.match(r"^(#{1,3}) (.+)$", s)
        if hm:
            blocks.append({"kind": "h", "level": len(hm.group(1)), "text": hm.group(2)})
            i += 1
            continue
        if s == "---":
            blocks.append({"kind": "hr"})
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            if len(rows) < 2 or not re.match(r"^\|(\s*:?-+:?\s*\|)+$", rows[1]):
                raise BuildError(f"bad table: {rows[:2]}")
            blocks.append({"kind": "table", "head": split_row(rows[0]), "rows": [split_row(r) for r in rows[2:]]})
            continue
        if re.match(r"^- ", s) or re.match(r"^\d+\. ", s):
            ordered = bool(re.match(r"^\d+\. ", s))
            items = []
            while i < n and (re.match(r"^\d+\. ", lines[i].strip()) if ordered else lines[i].strip().startswith("- ")):
                items.append(re.sub(r"^(?:\d+\.|-) ", "", lines[i].strip()))
                i += 1
            blocks.append({"kind": "ol" if ordered else "ul", "items": items})
            continue
        para = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,3} |\||- |\d+\. |---$|\[КАДР|\[FRAME|<!--|\*\*Button:)",
                                                          lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        blocks.append({"kind": "p", "text": " ".join(para)})
    return meta, blocks


# ---------------------------------------------------------------- images
def image_variant(stem):
    jpg = IMG / f"{stem}.jpg"
    if not jpg.is_file():
        raise BuildError(f"missing image {jpg}")
    for w in WIDTHS:
        if not (IMG / f"{stem}-{w}.webp").is_file():
            raise BuildError(f"missing {stem}-{w}.webp")
    from responsive import jpeg_size
    width, height = jpeg_size(jpg)
    srcset = ", ".join(f"/static/tenerife/site/img/{stem}-{w}.webp {w}w" for w in WIDTHS)
    return {"stem": stem, "src": f"/static/tenerife/site/img/{stem}.jpg", "srcset": srcset,
            "width": width, "height": height}


def assign_frames(frame_ids, frames_cfg):
    """Per page (designer r2): each F-id gets its first preferred photo not used yet on this page, hero
    included — a photo at most once per page. No suitable free photo -> None (text block + basalt bar)."""
    used, out = set(), {}
    for fid in frame_ids:
        if fid in out:
            raise BuildError(f"{fid} twice on one page")
        pick = next((stem for stem in frames_cfg["prefer"].get(fid, []) if stem not in used), None)
        if pick is not None:
            used.add(pick)
        out[fid] = pick
    return out


def assign_site_frames(page_frames, frames_cfg):
    """Founder / designer T47 (31.10.2026): one photo fills ONE slot on the whole site. Pass 1 gives each page's first
    slot (the hero, or the first frame of a text hero) its first preferred photo still free, pages in PAGES order;
    pass 2 fills the remaining slots the same way. No free photo -> None (text block + basalt bar, DESIGN.md)."""
    used, out = set(), {}
    for name, fids in page_frames.items():
        if len(set(fids)) != len(fids):
            raise BuildError(f"{name}: a frame id twice on one page")
        out[name] = dict.fromkeys(fids)
    for rest in (False, True):
        for name, fids in page_frames.items():
            for fid in (fids[1:] if rest else fids[:1]):
                pick = next((st for st in frames_cfg["prefer"].get(fid, []) if st not in used), None)
                if pick is not None:
                    used.add(pick)
                out[name][fid] = pick
    return out


DHASH_MAX = 10  # Hamming distance (of 64 bits) at or below which two pictures count as the same photo


def dhash(path):
    """64-bit difference hash (9x8 grey, left < right). Needs Pillow; None without it."""
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as im:
        g = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = list(g.tobytes())
    return sum(1 << i for i, (a, b) in enumerate((px[r * 9 + c], px[r * 9 + c + 1])
                                                  for r in range(8) for c in range(8)) if a < b)


IMG_SRC_RX = re.compile(r'<img [^>]*src="/static/tenerife/site/img/([^"/]+)\.jpg"')


def check_unique_images(outputs, img_dir=None):
    """Fail the build when any picture appears in two slots anywhere on the site: same file, or a different file
    whose dHash is within DHASH_MAX (a re-export / crop of the same photo). og:image is not a slot."""
    img_dir = Path(img_dir or IMG)
    slots = [(name, stem) for name, out in sorted(outputs.items()) for stem in IMG_SRC_RX.findall(out)]
    seen = {}
    for name, stem in slots:
        if stem in seen:
            raise BuildError(f"image {stem} repeats: {seen[stem]} and {name} (one photo = one slot site-wide)")
        seen[stem] = name
    hashes = {}
    for stem in seen:
        h = dhash(img_dir / f"{stem}.jpg")
        if h is None:  # no Pillow: the exact checks above and below still run
            print("note: Pillow missing, perceptual image check skipped (file name + sha256 only)")
            h = hashlib.sha256((img_dir / f"{stem}.jpg").read_bytes()).hexdigest()
        for other, oh in hashes.items():
            same = (h == oh) if isinstance(h, str) else bin(h ^ oh).count("1") <= DHASH_MAX
            if same:
                raise BuildError(f"images {other} ({seen[other]}) and {stem} ({seen[stem]}) are the same picture")
        hashes[stem] = h
    return len(slots)


def slot_alt(alts, page, fid, stem):
    """alts.json: per-slot override {file, alt} (must still be that slot's photo) or the photo's default."""
    o = alts["slots"].get(f"{page}/{fid}")
    if o is not None:
        if o.get("file") != stem:
            raise BuildError(f"alts.json: {page}/{fid} is for {o.get('file')}, the slot now shows {stem}")
        return o["alt"]
    if stem not in alts["images"]:
        raise BuildError(f"alts.json: no alt for {stem}")
    return alts["images"][stem]


# ---------------------------------------------------------------- page structure
def is_facts(block):
    return (block["kind"] == "p" and re.fullmatch(r"\*\*[^*]+\*\*", block["text"])
            and block["text"].count(" · ") >= 2)


LEAD_RX = re.compile(r"^\*\*([^*]+)\*\*\s*(.*)$")
QA_RX = re.compile(r"^<strong>([^<]+\?)</strong>\s+(.+)$")
NUM_CELL_RX = re.compile(r"^(?:<strong>)?(?:about |from |≈|\+)?[\d][\d  .,–×÷=+%€²m/-]*(?:</strong>)?$|^—$")
FIG_RX = re.compile(r"^([\d][\d  –]*?)\s+(\D.*)$")


def facts_items(text):
    """C3: «20 резиденций» -> value 20 + label; items without a leading figure stay text; the last one
    links to the waitlist (#ochered). Text and order exactly as in the copy line."""
    parts = text[2:-2].split(" · ")
    out = []
    for i, p in enumerate(parts):
        m = FIG_RX.match(p)
        last = i == len(parts) - 1
        if m and "=" not in p and not last:
            out.append({"value": html.escape(m.group(1)), "label": html.escape(m.group(2)), "text": None, "link": None})
        else:
            out.append({"value": None, "label": None, "text": html.escape(p), "link": "#ochered" if last else None})
    return out


HEAD_NUM_SPACE_RX = re.compile(r"(?<=\d) (?=\d{3}(?!\d))|(?<=\d) (?=[€%])")


def table_item(b):
    # T47: column heads may wrap now; NBSP keeps «2 950 €» in one piece (same characters, typography only)
    head = [HEAD_NUM_SPACE_RX.sub(NBSP, inline(x)) for x in b["head"]]
    rows = [[inline(x) for x in r] for r in b["rows"]]
    ncol = len(head)
    num = [j > 0 and all(NUM_CELL_RX.match(r[j]) for r in rows) for j in range(ncol)]
    return {"kind": "table", "head": head, "rows": rows, "num": num, "stack": ncol > 3,
            "plain_head": [re.sub(r"<[^>]+>", "", h) for h in head]}


def ladder_from(table):
    """C8 from the copy's own «Шесть ступеней цены» table (Ступень | событие | цена | рост)."""
    if table["plain_head"][0] != "Stage" or len(table["head"]) != 4 or "Rise" not in table["plain_head"][3]:
        return None
    return [{"name": r[0], "event": r[1], "price": r[2], "grow": r[3]} for r in table["rows"]]


def body_item(b):
    if b["kind"] == "p":
        return {"kind": "p", "html": inline(b["text"])}
    if b["kind"] in ("ul", "ol"):
        leads = [LEAD_RX.match(x) for x in b["items"]]
        if all(leads):
            pairs = [{"lead": inline(m.group(1)), "rest": inline(m.group(2))} for m in leads]
            return {"kind": "steps" if b["kind"] == "ol" else "ledger", "items": pairs}
        return {"kind": b["kind"], "items": [inline(x) for x in b["items"]]}
    if b["kind"] == "table":
        return table_item(b)
    raise BuildError(f"unexpected block {b['kind']}")


# ---------------------------------------------------------------- DESIGN.md §5 components (QA T3-07)
# Every component below only re-presents the copy's own words (or model.json, which the copy's figures come from);
# nothing is added or reworded. Sections are matched by their ### title.
STEP_P_RX = re.compile(r"^<strong>(\d+)\. ([^<]+)</strong>\s+(.+)$")   # 09 «Шесть шагов»: **1. Запись.** текст
C7_SENTENCE_TITLES = {"How you enter", "How entry works", "How it works"}  # EN titles of the RU sections  # one paragraph -> one step per sentence
SENTENCE_RX = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
MINI_LADDER = set()   # EN r1: the C8 mini ladder showed model.json stage prices (not approved): off
# C10 log: OFF until copy_v3 has confirmed entries «дата → стадия → что сделано» (DESIGN C10: concrete dates).
# The sections keep their copy (text + planned-dates table). To enable: put
# {("index", "Стройка"), ("construccion", "Журнал стройки")} back.
LOG_SECTIONS = set()  # C10
# C11 OFF (designer r3 item 4, 31.10.2026): kept only if every name, role and photo has a documented source (who
# confirmed it, when) in the repo, /workspace/web-designer/tenerife/ or FOUNDER_SITE_REQUIREMENTS.md. Names: founder
# t266u 31.10 00:32 (FOUNDER:54, :172). Roles: only [КАНОН] (copy_v3/sources_v3.md:17-19), no who/when -> the whole
# section is not rendered (no empty section). Back: TEAM_SECTIONS = {("index", "Команда и компания")}, HIDDEN = set().
TEAM_SECTIONS = set()                                                       # C11
HIDDEN_SECTIONS = {("index", "Team and company")}
PEOPLE = {"Simon Subic": "/tenerife/simon/", "Boris Ribaut": "/tenerife/boris/"}
CALC_SHORT = set()   # EN r1: no calculator (C9 short off)


def plain(fragment):
    return re.sub(r"<[^>]+>", "", fragment)


def c7_steps(body, title):
    """C7 from paragraphs: numbered bold leads (09) or the sentences of a single «Порядок входа» paragraph."""
    m = [STEP_P_RX.match(i["html"]) if i["kind"] == "p" else None for i in body]
    if len(body) >= 3 and all(m) and [int(x.group(1)) for x in m] == list(range(1, len(m) + 1)):
        return [{"kind": "steps", "items": [{"lead": x.group(2), "rest": x.group(3), "n_copy": True} for x in m]}]
    if title in C7_SENTENCE_TITLES and len(body) == 1 and body[0]["kind"] == "p":
        parts = SENTENCE_RX.split(body[0]["html"])
        if 3 <= len(parts) <= 6 and all("<" not in x or x.count("<") % 2 == 0 for x in parts):
            return [{"kind": "steps", "items": [{"lead": None, "rest": x} for x in parts]}]
    return body


def c10_log(body):
    out = []
    for i in body:
        if i["kind"] == "table" and len(i["head"]) in (2, 3):
            out.append({"kind": "log", "head": i["plain_head"], "rows": i["rows"]})
        else:
            out.append(i)
    if not any(i["kind"] == "log" for i in out):
        raise BuildError("C10: no table to show as the construction log")
    return out


def c11_people(body):
    out = []
    for i in body:
        if i["kind"] == "ledger":     # «**Simon Subic**, девелопер — …» arrives as lead + rest
            ms = [re.match(r"^<strong>([^<]+)</strong>, (.+)$", f"<strong>{plain(x['lead'])}</strong>{x['rest']}")
                  for x in i["items"]]
        else:
            items = i.get("items", []) if i["kind"] == "ul" else []
            ms = [re.match(r"^<strong>([^<]+)</strong>, (.+)$", x) for x in items]
        if ms and all(m and m.group(1) in PEOPLE for m in ms):
            out.append({"kind": "people", "items": [{"name": m.group(1), "href": PEOPLE[m.group(1)], "role": m.group(2)}
                                                    for m in ms]})
        else:
            out.append(i)
    if not any(i["kind"] == "people" for i in out):
        raise BuildError("C11: no team list")
    return out


# Designer r3 (31.10.2026): F17 («отделка») never shows a finished-house photo. On construccion the slot is a
# text block with the basalt bar (like F14-F16); on other pages it is hidden when the page already shows another
# photo, otherwise it renders the same text block + bar.
NO_PHOTO_SLOTS = {"F17"}
NO_PHOTO_BAR_PAGES = {"construccion"}


def hide_no_photo_slots(frames, name):
    """Slots of NO_PHOTO_SLOTS to drop entirely on this page (no image, no bar)."""
    if name in NO_PHOTO_BAR_PAGES or not any(stem for stem in frames.values()):
        return set()
    return {f for f in NO_PHOTO_SLOTS if f in frames}


def drop_hidden_sections(blocks, name):
    """Remove a ### section of HIDDEN_SECTIONS (heading .. next heading / --- / end) before frames are assigned."""
    out, skip = [], False
    for b in blocks:
        if b["kind"] == "h":
            skip = (name, plain(inline(b["text"]))) in HIDDEN_SECTIONS
        elif b["kind"] == "hr":
            skip = False
        if not skip:
            out.append(b)
    return out


def structure(blocks, frames, alts, name, model=None):
    """Group blocks into hero / sections / cta and choose the DESIGN.md component per section.
    Text order inside a section never changes; pictures ([КАДР]) of a section are placed after its text.
    A slot without a photo (frames[fid] is None) renders no image: its text block gets the basalt bar."""
    long_page = name in LONG_PAGES
    for fid in NO_PHOTO_SLOTS:
        if frames.get(fid) is not None:
            raise BuildError(f"{fid} must not get a photo (designer r3)")
    hidden = hide_no_photo_slots(frames, name)

    def img(fid, role):
        if frames[fid] is None:
            return None
        d = dict(image_variant(frames[fid]))
        d.update(alt=html.escape(slot_alt(alts, name, fid, frames[fid]), quote=True), frame=fid, sizes=SIZES[role])
        return d

    h1 = [b for b in blocks if b["kind"] == "h" and b["level"] == 1]
    if len(h1) != 1:
        raise BuildError("exactly one # H1 expected")
    k = blocks.index(h1[0])
    if blocks[:k]:
        raise BuildError("content before H1")
    rest = blocks[k + 1:]
    j = next(i for i, b in enumerate(rest) if b["kind"] == "frame")
    if any(b["kind"] != "p" for b in rest[:j]):
        raise BuildError("hero intro must be paragraphs")
    hero_img = img(rest[j]["id"], "long" if long_page else "hero")
    hero = {"h1": inline(h1[0]["text"]), "h1_text": h1[0]["text"],
            "intro": [inline(b["text"]) for b in rest[:j]], "img": hero_img, "bar": hero_img is None,
            "kind": "text" if long_page or hero_img is None else ("short" if name in SHORT_HERO else "full")}
    rest = rest[j + 1:]
    facts = None
    if rest and is_facts(rest[0]):
        facts = facts_items(rest[0]["text"])
        rest = rest[1:]
    if not rest or rest[-1]["kind"] != "button" or sum(b["kind"] == "button" for b in rest) != 1:
        raise BuildError("exactly one **Button** expected, as the last block")
    button = rest[-1]
    rest = rest[:-1]
    sections, cur = [], None
    for b in rest:
        if b["kind"] == "h":
            cur = {"title": inline(b["text"]), "level": b["level"], "body": [], "frames": []}
            sections.append(cur)
        elif b["kind"] == "hr":
            cur = None
        else:
            if cur is None:
                raise BuildError("text without a heading after the hero")
            if b["kind"] == "frame":
                cur["frames"].append(b["id"])
            else:
                cur["body"].append(body_item(b))
    # the last section is the waitlist text (C13) when it is plain text (01 «The queue»)
    cta_section = None
    last = sections[-1] if sections else None
    if last and not last["frames"] and all(i["kind"] in ("p", "ul") for i in last["body"]) \
            and not all(i["kind"] == "p" and QA_RX.match(i["html"]) for i in last["body"]):
        cta_section = sections.pop()
        cta_section["id"] = f"s{len(sections) + 1}"
    for s in sections:
        key = (name, plain(s["title"]))
        s["body"] = c7_steps(s["body"], key[1])
        if key in LOG_SECTIONS:
            s["body"] = c10_log(s["body"])
        if key in TEAM_SECTIONS:
            s["body"] = c11_people(s["body"])
        s["mini_ladder"] = None
        s["calc_short"] = key in CALC_SHORT
    split_n = 0
    for n, s in enumerate(sections, 1):
        s["id"] = f"s{n}"
        s["rev"], s["qa"] = False, []
        s["frames"] = [f for f in s["frames"] if f not in hidden]
        s["bar"] = bool(s["frames"]) and all(frames[f] is None for f in s["frames"])
        s["frames"] = [f for f in s["frames"] if frames[f] is not None]
        body = s["body"]
        qa = [QA_RX.match(i["html"]) if i["kind"] == "p" else None for i in body]
        s["ladder"] = next((ladder_from(i) for i in body if i["kind"] == "table" and ladder_from(i)), None)
        if body and all(qa):
            s["layout"] = "faq"
            s["qa"] = [{"q": m.group(1), "a": m.group(2)} for m in qa]
        elif long_page:
            s["layout"] = "long"
        elif s["ladder"] or any(i["kind"] in ("steps", "log") for i in body):
            s["layout"] = "stack"
        elif len(s["frames"]) == 1 and not any(i["kind"] == "table" for i in body):
            s["layout"] = "split"
            s["rev"] = split_n % 2 == 1
            split_n += 1
        else:
            s["layout"] = "head"
        if s["layout"] == "split":
            s["imgs"] = [dict(img(s["frames"][0], "split"), ratio="3x2")]
        elif s["layout"] == "long":
            s["imgs"] = [dict(img(f, "long"), ratio="3x2") for f in s["frames"]]
        elif len(s["frames"]) == 1:
            s["imgs"] = [dict(img(s["frames"][0], "wide"), ratio="21x9")]
        else:
            s["imgs"] = [dict(img(f, "half"), ratio="3x2") for f in s["frames"]]
    return {"hero": hero, "facts": facts, "sections": sections, "cta_section": cta_section,
            "button": {"text": html.escape(button["text"]), "micro": html.escape(button["micro"])}}


def parse_footer(md):
    meta, blocks = parse_page(md)
    title = next(b for b in blocks if b["kind"] == "h")["text"]
    paras = [b["text"] for b in blocks if b["kind"] == "p"]
    out = {"title": html.escape(title), "about": None, "pages": [], "contacts": [], "company": None, "docs": []}
    for p in paras:
        lab = re.match(r"^\*\*(.+?)\*\* ?(.*)$", p)
        label, rest = lab.group(1), lab.group(2)
        if label == "Pages.":
            names = rest.split(" · ")
            if set(names) != set(NAV) or len(names) != len(NAV):
                raise BuildError(f"footer pages differ from NAV: {names}")
            out["pages"] = names
        elif label == "Contact.":
            # EN copy: e-mail only. The WhatsApp contact stays a runtime slot (app/tenerife.py fills it from
            # TENERIFE_WHATSAPP on every request, never written into the files); a number in the copy fails the build.
            contacts = []
            for c in rest.split(" · "):
                if "{" in c or "}" in c or re.search(r"\+?\d[\d ]{7,}", c):
                    raise BuildError(f"footer «Contact»: unexpected token or hard-coded number: {c[:12]}…")
                contacts.append(c)
            out["contacts"] = contacts + ["whatsapp"]
        elif label == "Company.":
            out["company"] = inline(rest)
        elif label == "Documents.":
            out["docs"] = [re.match(r"\[(.+)\]\((/[^)]+)\)", d).groups() for d in rest.split(" · ")]
        elif out["about"] is None:
            out["about"] = inline(p)   # «**Artemis Tenerife**: …» as written
        else:
            raise BuildError(f"unknown footer line {p[:40]}")
    return out


# ---------------------------------------------------------------- form (copy_en/17_forma.md)
FORMA = "17_forma.md"
# label in 17_forma.md «Form messages» -> key (data-msg-<key> on the form; app/tenerife.py FORM_MSG)
FORM_MESSAGES = {
    "Button while sending.": "sending", "Success, heading.": "ok-title", "Success, what happens next.": "ok-next",
    "Server error.": "server", "No connection to the server.": "network", "Too many requests.": "rate",
    "\"Name\" field empty.": "name", "\"Contact\" field empty or shorter than 5 characters.": "contact",
    "No language selected.": "language", "No consent.": "consent",
}


def form_messages(md=None):
    """{key: text} from the «## Form messages» section of 17_forma.md, verbatim; every label required."""
    md = md if md is not None else (COPY / FORMA).read_text(encoding="utf-8")
    sec = re.search(r"^## Form messages\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not sec:
        raise BuildError(f"{FORMA}: no «Form messages» section")
    found = dict(re.findall(r"^\*\*(.+?)\*\* (.+)$", sec.group(1), re.M))
    missing = [lbl for lbl in FORM_MESSAGES if lbl not in found]
    if missing or len(found) != len(FORM_MESSAGES):
        unknown = sorted(set(found) - set(FORM_MESSAGES))
        raise BuildError(f"{FORMA}: form messages missing {missing} / unknown {unknown}")
    return {FORM_MESSAGES[lbl]: found[lbl].strip() for lbl in FORM_MESSAGES}


def consent_html(md=None):
    """The consent line next to the checkbox: «**Consent.** …» of 17_forma.md, verbatim (link kept)."""
    md = md if md is not None else (COPY / FORMA).read_text(encoding="utf-8")
    m = re.search(r"^\*\*Consent\.\*\* (.+)$", md, re.M)
    if not m:
        raise BuildError(f"{FORMA}: no «Consent.» line")
    return inline(m.group(1))


NBSP = "\u00a0"


DESIGN = HERE / "design"   # verbatim copies of web-designer/tenerife/design/{fonts.css,tokens.css}


def focal_css(frames_cfg):
    """Focal point of each photo in the mobile 4:5 hero crop (frames.json focal); classes: CSP forbids style=."""
    rx = re.compile(r"^\d{1,3}% \d{1,3}%$")
    rules = []
    for stem, pos in sorted(frames_cfg["focal"].items()):
        if not rx.match(pos) or not (STATIC / "tenerife" / "site" / "img" / f"{stem}.jpg").exists():
            raise BuildError(f"frames.json focal: bad entry {stem}: {pos}")
        rules.append(f"  .hero__media .fp-{stem}{{object-position:{pos}}}")
    return ("/* mobile 4:5 hero crop focal points: generated by build_v3.py from frames.json */\n"
            "@media (max-width:767px){\n" + "\n".join(rules) + "\n}\n")


def site_css(model, frames_cfg=None):
    """site.css = designer fonts.css + tokens.css (both as is) + components (site.src.css) + C8 ladder
    + photo focal points."""
    frames_cfg = frames_cfg or json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    parts = [(DESIGN / "fonts.css").read_text(encoding="utf-8"), (DESIGN / "tokens.css").read_text(encoding="utf-8"),
             (HERE / "site.src.css").read_text(encoding="utf-8"), ladder_css(model), focal_css(frames_cfg)]
    return "\n".join(parts)


def ladder_css(model):
    """C8 bar heights ∝ price / max price (from zero), generated from model.json: CSP forbids style=""."""
    steps = model["steps"]
    top = max(st["price_eur_m2"] for st in steps)
    rules = [f".ladder li:nth-child({i}){{--p:{st['price_eur_m2'] / top:.4f};--i:{i - 1}}}"
             for i, st in enumerate(steps, 1)]
    return "/* C8 ladder: generated by build_v3.py from model.json */\n" + "\n".join(rules) + "\n"


# ---------------------------------------------------------------- FAQPage JSON-LD (designer r2, item 5)
FAQ_LD_PAGE = "faq"


def visible_text(fragment):
    """What a reader sees of an HTML fragment: tags dropped, entities decoded, whitespace collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def faq_ld(page):
    """FAQPage built only from the visible questions/answers (<summary> / <p> of the C12 sections), word
    for word; '<' escaped so the data block can never close the <script>."""
    qa = [x for s in page["sections"] if s["layout"] == "faq" for x in s["qa"]]
    if not qa:
        raise BuildError("faq: no visible questions for FAQPage")
    data = {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": visible_text(x["q"]),
                            "acceptedAnswer": {"@type": "Answer", "text": visible_text(x["a"])}} for x in qa]}
    return ld_json(data)


def ld_json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


COMPANY_RX = re.compile(r"^(?P<name>[A-Z][A-Z ]+ LTD)\. .*Companies House No\. (?P<num>\d{8})\. Registered office: "
                        r"(?P<street>[^,]+, [^,]+), (?P<city>[^,]+), (?P<zip>[A-Z0-9]{2,4} [A-Z0-9]{3}), "
                        r"(?P<country>[^.]+)\.")


def org_ld(footer):
    """QA T3-08: Organization only from the copy (14 «Company.»). No telephone: the number is not confirmed yet
    (T3-01); no e-mail: addresses on the site stay inside email_off (Cloudflare obfuscation), not in data blocks."""
    m = COMPANY_RX.match(plain(footer["company"]))
    if not m:
        raise BuildError("footer «Company.»: Organization facts not found")
    return ld_json({"@context": "https://schema.org", "@type": "Organization",
                    "name": m["name"], "legalName": m["name"],
                    "url": BASE_URL + "/tenerife/",
                    "identifier": {"@type": "PropertyValue", "propertyID": "Companies House", "value": m["num"]},
                    "address": {"@type": "PostalAddress", "streetAddress": m["street"], "addressLocality": m["city"],
                                "postalCode": m["zip"], "addressCountry": m["country"]}})


def breadcrumb_ld(nav, name):
    """QA T3-08: Home → page; names = the copy's «Pages.» labels."""
    by = {x["name"]: x for x in nav}
    items = [by["index"]] + ([by[name]] if name != "index" else [])
    return ld_json({"@context": "https://schema.org", "@type": "BreadcrumbList",
                    "itemListElement": [{"@type": "ListItem", "position": i, "name": html.unescape(x["label"]),
                                         "item": BASE_URL + x["url"]} for i, x in enumerate(items, 1)]})


# ---------------------------------------------------------------- checks
ALLOWED_COMMENTS = ("<!--email_off-->", "<!--/email_off-->")


LD_RX = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def check_output(name, out):
    errs = []
    for ld in LD_RX.findall(out):           # JSON-LD data block: must parse; then skipped by the text checks
        try:
            json.loads(ld)
        except ValueError:
            errs.append(f"{name}: invalid JSON-LD")
    out = LD_RX.sub('<script type="application/ld+json"></script>', out)
    for bad in ("[КАДР", "[FRAME", "{{", "{%", "%}", "}}", "**", "Кнопка:", "Button:"):
        if bad in out:
            errs.append(f"{name}: «{bad}» in output")
    # Kimi r16: no copy token may survive, not even a lone brace (the calculator's JSON model is a data block)
    text = re.sub(r'<script type="application/json" id="cs-model">.*?</script>', "", out, flags=re.S)
    if "{" in text or "}" in text:
        errs.append(f"{name}: «{{» or «}}» in output")
    if "TENERIFE_WHATSAPP" in out:
        errs.append(f"{name}: «TENERIFE_WHATSAPP» in output")
    # QA r16: no phone number may be built into a page; the only one is TENERIFE_WHATSAPP, added at runtime
    if PHONE_RX.search(re.sub(r"<[^>]+>", " ", text)) or re.search(r'href="(tel:|https://wa\.me/)', out):
        errs.append(f"{name}: phone-like literal in output (contact numbers come only from TENERIFE_WHATSAPP)")
    for c in re.findall(r"<!--.*?-->", out, re.S):
        if c not in ALLOWED_COMMENTS:
            errs.append(f"{name}: HTML comment in output: {c[:60]}")
    if "<!--" in re.sub(r"<!--/?email_off-->", "", out):
        errs.append(f"{name}: stray '<!--'")
    if unprotected(out):
        errs.append(f"{name}: e-mail outside email_off: {unprotected(out)}")
    n_cta = len(re.findall(r'class="[^"]*\bcta-primary\b', out))
    if n_cta != 1:
        errs.append(f"{name}: {n_cta} .cta-primary")
    inline_script = (r'<script(?![^>]*\ssrc=)(?! type="application/json" id="cs-model")'
                     r'(?! type="application/ld\+json">)[^>]*>')
    if re.search(inline_script, out) or re.search(r"\son[a-z]+=", out) or "style=" in out:
        errs.append(f"{name}: inline script/style (CSP)")
    if errs:
        raise BuildError("\n".join(errs))


# ---------------------------------------------------------------- main
def build(model_path=MODEL, out_dir=SITE, write=True, alts_path=None):
    check_whatsapp_env()
    check_copy()
    model = load_model(model_path)   # only for the C8 ladder CSS (bar heights); no figure reaches a page from it
    frames_cfg = json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    alts = json.loads(Path(alts_path or HERE / "alts.json").read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=False, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    footer = parse_footer((COPY / FOOTER).read_text(encoding="utf-8"))
    # «@» as &#64; in the attributes: Cloudflare e-mail obfuscation never sees an address there (dataset decodes it)
    env.globals["form_msg"] = {k: html.escape(v, quote=True).replace("@", "&#64;") for k, v in form_messages().items()}
    env.globals["consent"] = consent_html()
    slugs, metas, parsed = {}, {}, {}
    for fname, name in PAGES:
        meta, blocks = parse_page((COPY / fname).read_text(encoding="utf-8"))
        slug = meta["Slug"]
        expected = "/tenerife/" if name == "index" else f"/tenerife/{name}/"
        if slug != expected:
            raise BuildError(f"{fname}: Slug {slug} != {expected}")
        slugs[name], metas[name], parsed[name] = slug, meta, blocks
    nav = [{"label": html.escape(lbl), "url": slugs[NAV[lbl]], "name": NAV[lbl]} for lbl in footer["pages"]]
    by_name = {x["name"]: x for x in nav}
    if set(NAV_PRIMARY) | set(NAV_MORE) | {"index"} != set(by_name):
        raise BuildError("header nav (NAV_PRIMARY + NAV_MORE) must cover the footer pages")
    menu = {"primary": [by_name[n] for n in NAV_PRIMARY], "more": [by_name[n] for n in NAV_MORE]}
    report, outputs = {}, {}
    tpl = env.get_template("page.html")
    pblocks = {name: drop_hidden_sections(parsed[name], name) for _f, name in PAGES}
    site_frames = assign_site_frames({n: [b["id"] for b in pblocks[n] if b["kind"] == "frame"] for n in pblocks},
                                     frames_cfg)
    for fname, name in PAGES:
        meta, blocks = metas[name], pblocks[name]
        frames = site_frames[name]
        page = structure(blocks, frames, alts, name)
        url = slugs[name]
        out = tpl.render(
            name=name, url=url, canonical=BASE_URL + url,
            title=html.escape(meta["Meta title"], quote=True),
            description=html.escape(meta["Meta description"], quote=True),
            og_title=html.escape(meta["OG title"], quote=True),
            og_image=BASE_URL + "/static/tenerife/site/img/og-tenerife-1200x630.jpg",
            nav=nav, menu=menu, footer=footer, page=page,
            lds=[x for x in (faq_ld(page) if name == FAQ_LD_PAGE else None,
                             org_ld(footer) if name == "index" else breadcrumb_ld(nav, name)) if x],
        )
        out = wrap(out)
        check_output(name, out)
        check_en(name, out)
        outputs[name] = out
        report[name] = {"url": url, "file": fname, "frames": frames,
                        "hidden": sorted(hide_no_photo_slots(frames, name)),
                        "alts": {fid: slot_alt(alts, name, fid, stem) for fid, stem in frames.items() if stem},
                        "title": meta["Meta title"], "h1": page["hero"]["h1_text"]}
    outputs.update(simple_pages(env, nav, menu, footer))
    for name in ("impressum", "privacy", "_notice"):
        check_en(name, outputs[name])

    # Project diary (main plumbing kept): EN-only pages, no locale alternates.
    from news import build_pages, UI as NEWS_UI, locale_url as news_locale_url

    def render_news(title, description, body, news_url, available):
        # footer.about is a single HTML string (parse_footer); append diary blurb.
        base_about = footer.get("about") or ""
        blurb = html.escape(NEWS_UI["en"][1] + ". " + NEWS_UI["en"][8])
        news_footer = dict(footer, about=(base_about + " " + blurb).strip())
        return wrap(env.get_template("simple.html").render(
            title=html.escape(title + " — Artemis Tenerife", quote=True),
            description=html.escape(description, quote=True),
            body=body, canonical=BASE_URL + news_url, url=news_url, kind="news",
            nav=nav, menu=menu, footer=news_footer))

    news_out = build_pages(render_news, "en")
    for name, out in news_out.items():
        check_en(name, out)
        outputs[name] = out

    # Soft 404 shell (EN).
    outputs["_404"] = wrap(env.get_template("simple.html").render(
        title="Page not found — Artemis Tenerife",
        description="Check the address or return to the Artemis Tenerife project.",
        body=('<h1 id="h1">Page not found</h1>'
              '<p class="hero__lead">Check the address or return to the Artemis Tenerife project.</p>'
              '<p class="back"><a href="/tenerife/">Back to the project</a></p>'),
        canonical=None, url="", kind="notice", nav=nav, menu=menu, footer=footer))
    check_en("_404", outputs["_404"])

    check_unique_images(outputs)
    css = site_css(model, frames_cfg)
    if write:
        out_root = Path(out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        (STATIC / "tenerife" / "site" / "site.css").write_text(css, encoding="utf-8")
        for name, out in outputs.items():
            target = out_root / f"{name}.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(out, encoding="utf-8")
        # Remove pre-EN leftovers that must not stay public on disk.
        for stale in ("calculadora.html", "equipo.html"):
            (out_root / stale).unlink(missing_ok=True)
        for loc in ("ru", "es", "de", "fr"):
            d = out_root / loc
            if d.is_dir():
                import shutil
                shutil.rmtree(d)
        # model.json / calc.js must never be under public static.
        static_site = STATIC / "tenerife" / "site"
        (static_site / "model.json").unlink(missing_ok=True)
        (static_site / "calc.js").unlink(missing_ok=True)
        data_dir = SITE / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        if not (data_dir / "model.json").is_file() and Path(model_path).is_file():
            (data_dir / "model.json").write_bytes(Path(model_path).read_bytes())
    return outputs, report


LEGAL_TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "templates" / "tenerife"
LEGAL_FILES = {"impressum": "15_impressum.md", "privacy": "16_privacy.md"}
NOTICE_SLOTS = ('<h1 id="h1">{{NOTICE_TITLE}}</h1>\n<p class="hero__lead">{{NOTICE_TEXT}}</p>\n'
                '<p class="back"><a href="{{NOTICE_BACK}}">{{NOTICE_BACK_LABEL}}</a></p>')


def legal_title(name):
    """«Meta title» of copy_en/15|16 (e.g. «Legal notice — Artemis Tenerife»)."""
    return parse_page((COPY / LEGAL_FILES[name]).read_text(encoding="utf-8"))[0]["Meta title"]


def legal_body(name):
    """The legal text, verbatim: the {% block body %} of app/templates/tenerife/<name>.html (generated from copy_en by
    legal_from_copy.py) without its old wrapper (<section class="legal"><div class="wrap"> … </div></section>);
    only the h1 gets id="h1"."""
    src = (LEGAL_TEMPLATES / f"{name}.html").read_text(encoding="utf-8")
    m = re.search(r"\{% block body %\}\s*<section class=\"legal\"><div class=\"wrap\">\n(.*?)\n</div></section>\s*"
                  r"\{% endblock %\}", src, re.S)
    if not m or "{%" in m.group(1) or "{{" in m.group(1) or m.group(1).count("<h1>") != 1:
        raise BuildError(f"{name}.html: legal body block not found / not plain HTML")
    return m.group(1).replace("<h1>", '<h1 id="h1">', 1)


def legal_meta(name):
    """Meta description of a legal page: the copy gives none, so its own first line under the H1, verbatim
    (impressum: «Impressum (§ 5 DDG) / Aviso legal …»; privacy: «For the Artemis Tenerife website …»)."""
    md = re.sub(r"<!--.*?-->", "", (COPY / LEGAL_FILES[name]).read_text(encoding="utf-8"), flags=re.S)
    after = md.split("\n# ", 1)[1].split("\n", 1)[1]
    first = next(ln.strip() for ln in after.splitlines() if ln.strip())
    if first.startswith("#") or "**" in first or len(first) > 160:
        raise BuildError(f"{name}: no plain first line for the meta description")
    return first


def simple_pages(env, nav, menu, footer):
    """QA T3-09: Impressum / privacy in the v2 layout; QA T3-05: shell of the no-JS form answers."""
    tpl = env.get_template("simple.html")
    out = {}
    for name in LEGAL_FILES:
        url = f"/tenerife/{name}/"
        out[name] = wrap(tpl.render(title=html.escape(legal_title(name), quote=True), canonical=BASE_URL + url,
                                    url=url, kind="legal", description=html.escape(legal_meta(name), quote=True),
                                    body=legal_body(name), nav=nav, menu=menu, footer=footer))
    out["_notice"] = wrap(tpl.render(title="{{NOTICE_TITLE}} — Artemis Tenerife", canonical=None, url="",
                                     kind="notice", body=NOTICE_SLOTS, nav=nav, menu=menu, footer=footer))
    return out


def main():
    try:
        outputs, report = build()
    except BuildError as e:
        print("BUILD FAILED:\n" + str(e), file=sys.stderr)
        sys.exit(1)
    for name, r in report.items():
        fr = " ".join(f"{k}->{'-'.join(v.split('-')[:2]) if v else ('(hidden)' if k in r['hidden'] else '(text)')}"
                      for k, v in r["frames"].items())
        print(f"{r['url']:28} {len(outputs[name]):6d} B  {fr}")
    (HERE / "frames_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
