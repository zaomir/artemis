"""Build the RU v3 Tenerife site (13 pages) from the verbatim copy in copy_v3/.

  python3 scripts/tenerife_site_build/make_model.py   # numbers.md + model_inputs.json -> model.json
  python3 scripts/tenerife_site_build/build_v3.py     # copy_v3/*.md + model.json -> app/tenerife_site/*.html

Texts are taken as written (no edits). The only transformations:
  * figures: every model token is replaced copy -> value from model.json (identity while the
    inputs equal the copywriter's baseline), so a price change is one edit in model_inputs.json;
  * [КАДР Fxx] markers -> <picture> of an existing Canary Stone photo (frames.json);
  * markdown (# ## ### | - 1. ** [](...)) -> HTML through Jinja components in
    app/templates/tenerife/site/ (hero, facts, units, section, frame/gallery, table, cta, footer).
The build fails if '[КАДР', '{{', '{%' or any HTML comment other than <!--email_off--> markers
reaches the output. build.py (old pages) and email_off.py are not touched; wrap() is the last step.
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

LOCALE = os.environ.get("TENERIFE_LOCALE", "ru").strip().lower() or "ru"
COPY = Path(os.environ.get("TENERIFE_COPY_DIR", str(HERE / "copy_v3")))
SITE = Path(os.environ.get("TENERIFE_OUT_DIR", str(ROOT / "app" / "tenerife_site")))
STATIC = ROOT / "app" / "static"
IMG = STATIC / "tenerife" / "site" / "img"
TEMPLATES = ROOT / "app" / "templates" / "tenerife" / "site"
MODEL = STATIC / "tenerife" / "site" / "model.json"
BASE_URL = "https://artemisresort.com"
# Approved copy: sha256 of copy_v3 01-17 combined (= Artemis_Tenerife_RU_copy_v3.md; final copy, 31.10.2026 20:48).
# Configurable until the final value: TENERIFE_COPY_SHA256=<sha> overrides the default for a build / test run.
# Kimi r16: 01–17 only (explicit list, copy_files(); draft 18_investoram.md not built) = Artemis_Tenerife_RU_copy_v3.md
COPY_SHA256_DEFAULT = "46aa1056e5fd9f44f1e65240d9463d6e5ca5cf59925e1ee6937530846113c94b"
COPY_SHA256 = os.environ.get("TENERIFE_COPY_SHA256", "").strip().lower() or COPY_SHA256_DEFAULT
WIDTHS = (640, 800, 1024, 1600)

# copy file -> output name (app/tenerife_site/<name>.html); URL comes from the copy's own «Слаг»
PAGES = [("01_glavnaya.md", "index"), ("02_sever.md", "norte"), ("03_rezidencii.md", "producto"),
         ("04_akcii.md", "acciones"), ("05_kalkulyator.md", "calculadora"), ("06_arenda.md", "alquiler"),
         ("07_energiya.md", "energia"), ("08_stroyka.md", "construccion"), ("09_sdelka.md", "proceso"),
         ("10_voprosy.md", "faq"), ("11_simon.md", "simon"), ("12_rynok.md", "mercado"), ("13_boris.md", "boris")]
FOOTER = "14_podval.md"
WA_TOKEN = "WhatsApp: {номер из TENERIFE_WHATSAPP}"  # 14_podval.md «Контакты.»
WA_RX = re.compile(r"\+[1-9]\d{7,14}")  # E.164, same rule as app/tenerife.py whatsapp_number()
# phone-like literal (not a CSS unicode-range U+…): + or 00, then ≥ 8 digits (spaces . - ( ) nbsp between)
PHONE_RX = re.compile(r"(?:(?<![Uu])\+|\b00)\d(?:[\s\u00a0.()\-]*\d){7,}")


def check_whatsapp_env():
    """Kimi r16: the build fails when TENERIFE_WHATSAPP is empty or invalid. The value is never printed and never
    written into the output (runtime slot, see parse_footer)."""
    v = os.environ.get("TENERIFE_WHATSAPP", "").strip()
    if not v:
        raise BuildError("TENERIFE_WHATSAPP is empty: set it (E.164, e.g. +440000000000) before building")
    if not WA_RX.fullmatch(v):
        raise BuildError("TENERIFE_WHATSAPP is invalid (expected E.164: + then 8–15 digits); value not shown")
# footer «Страницы.» names -> output name (names are the copy's; order is the copy's)
NAV = {"Главная": "index", "Локация": "norte", "Резиденция": "producto", "Оплата": "acciones",
       "Калькулятор": "calculadora", "Аренда": "alquiler", "Энергия": "energia", "Стройка": "construccion",
       "Сделка": "proceso", "Вопросы": "faq", "Рынок и цена метра": "mercado", "Developer": "simon",
       "Supervisor": "boris"}
CALC_PAGE = "calculadora"
FORM_HOST_PAGE = "/tenerife/proceso/"

# DESIGN.md §5: pages 11 and 13 are long text (solid header, 760 px column); 05 and 10 have a short hero
LONG_PAGES = {"simon", "boris"}
SHORT_HERO = {"calculadora", "faq"}
# DESIGN.md C1: 7 links + «Ещё»; labels are the footer's («Страницы.»)
# Kimi r18: footer items for pages that are not built yet. Shown only once the page is in PAGES (page 18
# «Инвесторам» -> /tenerife/inversores/ is a draft, not built), so the footer never links to a 404.
NAV_FUTURE = {"Инвесторам": "inversores"}
NAV_PRIMARY = ["producto", "norte", "acciones", "proceso"]
NAV_MORE = ["calculadora", "construccion", "faq", "alquiler", "energia", "mercado", "simon", "boris"]

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


# ---------------------------------------------------------------- copy + figures
def copy_files():
    """The copy the build actually uses: the 13 pages + footer, legal, form. Anything else in copy_v3 (e.g. Kimi's
    draft 18_investoram.md) is not built and not hashed."""
    names = sorted({f for f, _ in PAGES} | {FOOTER, "15_impressum.md", "16_privacy.md", FORMA})
    return [COPY / n for n in names]


def combined_sha():
    files = copy_files()
    s = "\n---\n\n".join(f.read_text(encoding="utf-8").rstrip("\n") + "\n" for f in files)
    return hashlib.sha256(s.encode()).hexdigest()


def load_model(path=MODEL):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def figure_map(model):
    """copy figure -> site figure. Raises if one copy string would need two different values."""
    out, owners = {}, {}
    for t in model["tokens"] + model["extra"]:
        c, v = t["copy"], t["value"]
        if c in out and out[c] != v:
            raise BuildError(f"ambiguous figure «{c}»: {owners[c]} -> «{out[c]}» but {t['label']} -> «{v}»; "
                             "the copy uses one string for two model values — split it in the copy first")
        out[c] = v
        owners[c] = t["label"]
    return out


def figure_regex(fmap):
    alts = []
    for tok in sorted(fmap, key=len, reverse=True):
        tail = r"(?![\d,]\d)" if tok[-1].isdigit() else ""
        alts.append(r"(?<![\d,–])(?<!\d[ \u00a0])" + re.escape(tok) + tail)
    return re.compile("|".join(alts))


def apply_figures(text, fmap, rx):
    return rx.sub(lambda m: fmap[m.group(0)], text)


# ---------------------------------------------------------------- markdown subset
META_RX = re.compile(r"<!-- META\n(.*?)-->", re.S)
FRAME_RX = re.compile(r"^\[КАДР (F\d\d)\]\s*(?:<!--.*?-->)?\s*$")
BUTTON_RX = re.compile(r"^\*\*Кнопка: «(.+)»\*\*$")
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
        if "<!--" in s or "[КАДР" in s:
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
        while i < n and lines[i].strip() and not re.match(r"^(#{1,3} |\||- |\d+\. |---$|\[КАДР|<!--|\*\*Кнопка:)",
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
NUM_CELL_RX = re.compile(r"^(?:<strong>)?(?:около |от |\+)?[\d][\d  .,–×÷=+%€²м/-]*(?:</strong>)?$|^—$")
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
    if table["plain_head"][0] != "Ступень" or len(table["head"]) != 4 or "Рост" not in table["plain_head"][3]:
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
C7_SENTENCE_TITLES = {"Порядок входа", "Как устроен вход", "Как это работает"}  # one paragraph -> one step per sentence
SENTENCE_RX = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])")
MINI_LADDER = {("index", "Как это работает"), ("construccion", "Девять стадий и ступени цены"),
               ("mercado", "Ступени Artemis рядом с рынком")}          # C8 mini (01, 08, 12)
# C10 log: OFF until copy_v3 has confirmed entries «дата → стадия → что сделано» (DESIGN C10: concrete dates).
# The sections keep their copy (text + planned-dates table). To enable: put
# {("index", "Стройка"), ("construccion", "Журнал стройки")} back.
LOG_SECTIONS = set()  # C10
# C11 OFF (designer r3 item 4, 31.10.2026): kept only if every name, role and photo has a documented source (who
# confirmed it, when) in the repo, /workspace/web-designer/tenerife/ or FOUNDER_SITE_REQUIREMENTS.md. Names: founder
# t266u 31.10 00:32 (FOUNDER:54, :172). Roles: only [КАНОН] (copy_v3/sources_v3.md:17-19), no who/when -> the whole
# section is not rendered (no empty section). Back: TEAM_SECTIONS = {("index", "Команда и компания")}, HIDDEN = set().
TEAM_SECTIONS = set()                                                       # C11
HIDDEN_SECTIONS = {("index", "Команда и компания")}
PEOPLE = {"Simon Subic": "/tenerife/simon/", "Boris Ribaut": "/tenerife/boris/"}
CALC_SHORT = {("acciones", "Пример на 72 метрах")}                       # C9 short (04)


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


SHORT_RX = re.compile(r"^<strong>([^<]+):</strong> [\d\u00a0 ]+\u00a0?€ (.+?) [\d\u00a0 ]+\u00a0?€ (.+)\.$")


def short_labels(page):
    """C9 short (04): words of the section's own sentence «Покупка из очереди: 212 400 € сразу или 17 700 € в месяц
    двенадцать месяцев.» — the two amounts become the computed values (no word from another page)."""
    s = next((x for x in page["sections"] if x["calc_short"]), None)
    if s is None:
        return None
    for i in s["body"]:
        m = SHORT_RX.match(i["html"]) if i["kind"] == "p" else None
        if m:
            return {"lead": m.group(1), "mid": m.group(2), "tail": m.group(3)}
    raise BuildError("C9 short: «Покупка из очереди: … € сразу или … € в месяц …» not found")


def mini_ladder(model):
    """C8 mini: names and prices from model.json (= the copy's figures); visual only, the text is next to it."""
    def eur(v):
        return fmt_int(v) + NBSP + "€"
    return [{"name": st["name"], "price": eur(st["price_eur_m2"]), "current": bool(st.get("current"))}
            for st in model["steps"]]


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
        raise BuildError("exactly one **Кнопка** expected, as the last block")
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
    # the last section is the waitlist text (C13) when it is plain text (01 «Очередь»)
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
        s["mini_ladder"] = mini_ladder(model) if key in MINI_LADDER and model else None
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


def parse_footer(md, fmap, rx):
    meta, blocks = parse_page(apply_figures(md, fmap, rx))
    title = next(b for b in blocks if b["kind"] == "h")["text"]
    paras = [b["text"] for b in blocks if b["kind"] == "p"]
    out = {"title": html.escape(title), "about": None, "pages": [], "contacts": [], "company": None, "docs": []}
    for p in paras:
        lab = re.match(r"^\*\*(.+?)\*\* ?(.*)$", p)
        label, rest = lab.group(1), lab.group(2)
        if label == "Страницы.":
            names = rest.split(" · ")
            built = {n for _f, n in PAGES}
            out["hidden"] = [x for x in names if x in NAV_FUTURE and NAV_FUTURE[x] not in built]
            names = [x for x in names if x not in out["hidden"]]
            if set(names) != set(NAV) or len(names) != len(NAV):
                raise BuildError(f"footer pages differ from NAV: {names}")
            out["pages"] = names
        elif label == "Контакты.":
            # Kimi r16: «WhatsApp: {номер из TENERIFE_WHATSAPP}». The token becomes the WhatsApp slot; app/tenerife.py
            # fills it with the TENERIFE_WHATSAPP value on every request, so the number never lands in the built
            # files / git. A number written into the copy, or any other {…}, fails the build.
            contacts = []
            for c in rest.split(" · "):
                if c == WA_TOKEN:
                    contacts.append("whatsapp")
                elif "{" in c or "}" in c or re.search(r"\+?\d[\d ]{7,}", c):
                    raise BuildError(f"footer «Контакты»: unexpected token or hard-coded number: {c[:12]}…")
                else:
                    contacts.append(c)
            out["contacts"] = contacts
        elif label == "Компания.":
            out["company"] = inline(rest)
        elif label == "Документы.":
            out["docs"] = [re.match(r"\[(.+)\]\((/[^)]+)\)", d).groups() for d in rest.split(" · ")]
        elif out["about"] is None:
            out["about"] = (label, inline(rest))
        else:
            raise BuildError(f"unknown footer line {p[:40]}")
    return out


# ---------------------------------------------------------------- form messages (copy_v3/17_forma.md, Kimi r4)
FORMA = "17_forma.md"
# label in 17_forma.md «Сообщения формы» -> key (data-msg-<key> on the form; app/tenerife.py FORM_MSG)
FORM_MESSAGES = {
    "Кнопка во время отправки.": "sending", "Успех, заголовок.": "ok-title", "Успех, что дальше.": "ok-next",
    "Ошибка сервера.": "server", "Нет связи с сервером.": "network", "Слишком много заявок.": "rate",
    "Поле «Имя» пустое.": "name", "Поле «Контакт» пустое или короче 5 символов.": "contact",
    "Язык не выбран.": "language", "Нет согласия.": "consent",
}


def form_messages(md=None):
    """{key: text} from the «## Сообщения формы» section of 17_forma.md, verbatim; every label required."""
    md = md if md is not None else (COPY / FORMA).read_text(encoding="utf-8")
    sec = re.search(r"^## Сообщения формы\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not sec:
        raise BuildError(f"{FORMA}: no «Сообщения формы» section")
    found = dict(re.findall(r"^\*\*(.+?)\*\* (.+)$", sec.group(1), re.M))
    missing = [lbl for lbl in FORM_MESSAGES if lbl not in found]
    if missing or len(found) != len(FORM_MESSAGES):
        unknown = sorted(set(found) - set(FORM_MESSAGES))
        raise BuildError(f"{FORMA}: form messages missing {missing} / unknown {unknown}")
    return {FORM_MESSAGES[lbl]: found[lbl].strip() for lbl in FORM_MESSAGES}


# ---------------------------------------------------------------- calculator defaults (server-rendered, no CLS)
NBSP = "\u00a0"


def fmt_int(x):
    """= calc.js eur(): Intl.NumberFormat('ru-RU') groups with U+00A0; half-up like Math.round for positives."""
    return f"{int(x + 0.5):,}".replace(",", NBSP)


def fmt_pct(x):
    """half-up to 1 decimal (= calc.js roundingMode halfExpand)."""
    t = int(x * 10 + 0.5)
    return f"{t // 10},{t % 10}%"


def calc_view(model):
    """C9 defaults rendered into the HTML (no CLS, correct without JS) + the inline #cs-model island data."""
    steps = model["steps"]
    m2 = model["area_m2"]["default"]
    cur = next(st for st in steps if st.get("current"))
    hand = next(st for st in steps if not st["entry"])
    total = m2 * cur["price_eur_m2"]
    d = model["dividend_eur_per_share_year"]
    months = model["installments"]["months"]
    def eur(v):
        return fmt_int(v) + NBSP + "€"
    island = {"steps": [{k: st[k] for k in ("id", "price_eur_m2", "entry") if k in st}
                        | ({"current": True} if st.get("current") else {}) for st in steps],
              "installments": {"months": months}, "dividend_eur_per_share_year": d,
              "area_m2": model["area_m2"], "types": [{k: t[k] for k in ("id", "min", "max")} for t in model["types"]]}
    return {"m2": m2, "min": model["area_m2"]["min"], "max": model["area_m2"]["max"], "months": months,
            "types": [dict(t, checked=t["min"] <= m2 <= t["max"]) for t in model["types"]],
            "steps": [dict(st, label=st["name"] + " — " + eur(st["price_eur_m2"])) for st in steps if st["entry"]],
            "current": cur["id"],
            "sum": eur(total), "month": eur(total / months), "handover": eur(m2 * hand["price_eur_m2"]),
            "div": eur(m2 * d), "pct": fmt_pct(d / cur["price_eur_m2"] * 100),
            "m2_out": f"{m2} м²",
            "island": json.dumps(island, ensure_ascii=False, separators=(",", ":"))}


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


def case_css():
    """Фоны карточек портфеля: один файл на объект (CSP запрещает style=)."""
    cfg = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    rules = [f".case__media--{it['img']}{{background-image:url('/static/tenerife/site/cases/{it['img']}-1200.webp')}}"
             for it in cfg["items"]]
    people = json.loads((HERE / "people.json").read_text(encoding="utf-8"))
    for items in people.values():
        if isinstance(items, list):
            for it in items:
                rules.append(f".tperson__ph--{it['img']}{{background-image:url('/static/tenerife/site/img/{it['img']}-1024.webp')}}")
    return "\n".join(rules) + "\n"


def site_css(model, frames_cfg=None):
    """site.css = designer fonts.css + tokens.css (both as is) + components (site.src.css) + C8 ladder
    + photo focal points."""
    frames_cfg = frames_cfg or json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    parts = [(DESIGN / "fonts.css").read_text(encoding="utf-8"), (DESIGN / "tokens.css").read_text(encoding="utf-8"),
             (HERE / "site.src.css").read_text(encoding="utf-8"), ladder_css(model), focal_css(frames_cfg),
             case_css()]
    return "\n".join(parts)


def calc_labels(page):
    """C9 labels are the copy's own words: «Что вы видите» (result names) and «Способ оплаты.» (options)."""
    seen = next(s for s in page["sections"] if s["title"] == "Что вы видите")
    led = next(i for i in seen["body"] if i["kind"] == "ledger")["items"]
    leads = [re.sub(r"<[^>]+>", "", x["lead"]) for x in led]
    rests = [x["rest"] for x in led]
    if len(leads) != 6:
        raise BuildError("calculator: «Что вы видите» must list 6 results")
    pay = next(re.sub(r"^<strong>Способ оплаты\.</strong> ", "", i["html"]) for s in page["sections"] for i in s["body"]
               if i["kind"] == "p" and i["html"].startswith("<strong>Способ оплаты.</strong>"))
    now, parts = pay.rstrip(".").split(" или ", 1)
    return {"sum": leads[0], "month": leads[1], "handover": leads[2],
            "div": leads[3] + "," + rests[3].rsplit(",", 1)[1].rstrip("."), "pct": leads[4],
            "paths": leads[5], "paths_dd": re.sub(r"^— ", "", rests[5]).rstrip("."),
            "pay_now": now, "pay_parts": parts[:1].upper() + parts[1:]}


def ladder_css(model):
    """C8 bar heights ∝ price / max price (from zero), generated from model.json: CSP forbids style=""."""
    steps = model["steps"]
    top = max(st["price_eur_m2"] for st in steps)
    rules = [f".ladder li:nth-child({i}){{--p:{st['price_eur_m2'] / top:.4f};--i:{i - 1}}}"
             for i, st in enumerate(steps, 1)]
    return "/* C8 ladder: generated by build_v3.py from model.json */\n" + "\n".join(rules) + "\n"



def team_gallery(page_name):
    """Фотогалерея страницы человека (Simon / Boris): картинки CSS-фоном, некликабельны."""
    cfg = json.loads((HERE / "people.json").read_text(encoding="utf-8"))
    items = cfg.get(page_name, [])
    if not items:
        return ""
    cards = "".join(
        f'<div class="tperson__ph tperson__ph--{it["img"]}" role="img" aria-label="{html.escape(it["alt"], quote=True)}"></div>'
        for it in items)
    return ('<section class="section rule-top s--person" aria-labelledby="s-person">'
            '<div class="wrap"><div class="tperson">' + cards + '</div></div></section>')


def portfolio_html():
    """Портфель команды: семь объектов одной бесконечной лентой (CSS-анимация, без ручного скролла).
    Карточки дублируются, чтобы шов был незаметен; картинки — CSS-фон (.case__media--<stem>)."""
    cfg = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))

    def cards():
        out = []
        for it in cfg["items"]:
            name = html.escape(it["name"], quote=True)
            out.append(
                '<div class="case">'
                f'<div class="case__media case__media--{it["img"]}" role="img" aria-label="{name}"></div>'
                f'<span class="case__badge">{it["status"]}</span>'
                f'<div class="case__cap"><b>{it["name"]}</b><span>{it["place"]}</span></div>'
                '</div>')
        return "".join(out)

    group = '<div class="cases__group">' + cards() + '</div>'
    return ('<section class="section rule-top s--cases" aria-labelledby="s-cases">'
            '<div class="wrap">'
            '<h2 id="s-cases">Портфель команды</h2>'
            '<p class="cases__lead">Семь объектов, на которых мы девелопер и строительный надзор.</p>'
            '</div>'
            '<div class="cases__viewport">'
            '<div class="cases__track">' + group + group + '</div>'
            '</div>'
            '</section>')

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


COMPANY_RX = re.compile(r"^(?P<name>[A-Z][A-Z ]+ LTD)\. .*Companies House № (?P<num>\d{8})\. Юридический адрес: "
                        r"(?P<street>[^,]+, [^,]+), (?P<city>[^,]+), (?P<zip>[A-Z0-9]{2,4} [A-Z0-9]{3}), "
                        r"(?P<country>[^.]+)\.")


def org_ld(footer):
    """QA T3-08: Organization only from the copy (14 «Компания.»). No telephone: the number is not confirmed yet
    (T3-01); no e-mail: addresses on the site stay inside email_off (Cloudflare obfuscation), not in data blocks."""
    m = COMPANY_RX.match(plain(footer["company"]))
    if not m:
        raise BuildError("footer «Компания.»: Organization facts not found")
    return ld_json({"@context": "https://schema.org", "@type": "Organization",
                    "name": m["name"], "legalName": m["name"],
                    "url": BASE_URL + "/tenerife/",
                    "identifier": {"@type": "PropertyValue", "propertyID": "Companies House", "value": m["num"]},
                    "address": {"@type": "PostalAddress", "streetAddress": m["street"], "addressLocality": m["city"],
                                "postalCode": m["zip"], "addressCountry": m["country"]}})


def breadcrumb_ld(nav, name):
    """QA T3-08: Главная → page; names = the copy's «Страницы.» labels."""
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
    for bad in ("[КАДР", "{{", "{%", "%}", "}}", "**", "Кнопка:"):
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
    if LOCALE == "ru" and combined_sha() != COPY_SHA256:
        raise BuildError(f"copy_v3 sha256 {combined_sha()} != {COPY_SHA256} (copy changed: re-approve)")
    model = load_model(model_path)
    fmap = figure_map(model)
    rx = figure_regex(fmap)
    frames_cfg = json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    alts = json.loads(Path(alts_path or HERE / "alts.json").read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=False, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    footer = parse_footer((COPY / FOOTER).read_text(encoding="utf-8"), fmap, rx)
    # «@» as &#64; in the attributes: Cloudflare e-mail obfuscation never sees an address there (dataset decodes it)
    env.globals["form_msg"] = {k: html.escape(v, quote=True).replace("@", "&#64;") for k, v in form_messages().items()}
    slugs, metas, parsed = {}, {}, {}
    for fname, name in PAGES:
        md = apply_figures((COPY / fname).read_text(encoding="utf-8"), fmap, rx)
        meta, blocks = parse_page(md)
        slug = meta["Слаг"]
        expected = "/tenerife/" if name == "index" else f"/tenerife/{name}/"
        if slug != expected:
            raise BuildError(f"{fname}: Слаг {slug} != {expected}")
        slugs[name], metas[name], parsed[name] = slug, meta, blocks
    nav = [{"label": html.escape(lbl), "url": slugs[NAV[lbl]], "name": NAV[lbl]} for lbl in footer["pages"]]
    by_name = {x["name"]: x for x in nav}
    if set(NAV_PRIMARY) | set(NAV_MORE) | {"index"} != set(by_name):
        raise BuildError("header nav (NAV_PRIMARY + NAV_MORE) must cover the footer pages")
    menu = {"primary": [by_name[n] for n in NAV_PRIMARY], "more": [by_name[n] for n in NAV_MORE]}
    report, outputs = {}, {}
    tpl = env.get_template("page.html")
    pblocks = {name: drop_hidden_sections(parsed[name], name) for _f, name in PAGES}
    site_frames = assign_site_frames({n: [b["id"] for b in bl if b["kind"] == "frame"] for n, bl in pblocks.items()},
                                     frames_cfg)
    for fname, name in PAGES:
        meta, blocks = metas[name], pblocks[name]
        frames = site_frames[name]
        page = structure(blocks, frames, alts, name, model)
        url = slugs[name]
        out = tpl.render(
            name=name, url=url, canonical=BASE_URL + url,
            title=html.escape(meta["Meta title"], quote=True),
            description=html.escape(meta["Meta description"], quote=True),
            og_title=html.escape(meta["OG title"], quote=True),
            og_image=BASE_URL + "/static/tenerife/site/img/og-tenerife-1200x630.jpg",
            nav=nav, menu=menu, footer=footer, page=page,
            calc=calc_view(model) if name == CALC_PAGE else None,
            calc_labels=calc_labels(page) if name == CALC_PAGE else None,
            lds=[x for x in (faq_ld(page) if name == FAQ_LD_PAGE else None,
                             org_ld(footer) if name == "index" else breadcrumb_ld(nav, name)) if x],
            calc_short=calc_view(model) if any(x["calc_short"] for x in page["sections"]) else None,
            calc_short_labels=short_labels(page),
        )
        out = wrap(out)
        if name == "index":
            marker = '<section class="plinth"'
            if marker in out:
                out = out.replace(marker, portfolio_html() + marker, 1)
        if name in ("simon", "boris"):
            gallery = team_gallery(name)
            if gallery:
                hero_end = out.find("</section>", out.find('<section class="hero'))
                if hero_end != -1:
                    pos = hero_end + len("</section>")
                    out = out[:pos] + gallery + out[pos:]
        check_output(name, out)
        outputs[name] = out
        report[name] = {"url": url, "file": fname, "frames": frames,
                        "hidden": sorted(hide_no_photo_slots(frames, name)),
                        "alts": {fid: slot_alt(alts, name, fid, stem) for fid, stem in frames.items() if stem},
                        "title": meta["Meta title"],
                        "h1": page["hero"]["h1_text"]}
    outputs.update(simple_pages(env, nav, menu, footer))
    check_unique_images(outputs)
    css = site_css(model, frames_cfg)
    if write:
        (STATIC / "tenerife" / "site" / "site.css").write_text(css, encoding="utf-8")
        for name, out in outputs.items():
            (Path(out_dir) / f"{name}.html").write_text(out, encoding="utf-8")
    return outputs, report


LEGAL_TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "templates" / "tenerife"
LEGAL = {"impressum": "Правовая информация — Artemis de la Cruz", "privacy": "Конфиденциальность — Artemis de la Cruz"}
NOTICE_SLOTS = ('<h1 id="h1">{{NOTICE_TITLE}}</h1>\n<p class="hero__lead">{{NOTICE_TEXT}}</p>\n'
                '<p class="back"><a href="{{NOTICE_BACK}}">{{NOTICE_BACK_LABEL}}</a></p>')


def legal_body(name):
    """The legal text, verbatim: the {% block body %} of app/templates/tenerife/<name>.html without its old
    wrapper (<section class="legal"><div class="wrap"> … </div></section>); only the h1 gets id="h1"."""
    src = (LEGAL_TEMPLATES / f"{name}.html").read_text(encoding="utf-8")
    m = re.search(r"\{% block body %\}\s*<section class=\"legal\"><div class=\"wrap\">\n(.*?)\n</div></section>\s*"
                  r"\{% endblock %\}", src, re.S)
    if not m or "{%" in m.group(1) or "{{" in m.group(1) or m.group(1).count("<h1>") != 1:
        raise BuildError(f"{name}.html: legal body block not found / not plain HTML")
    return m.group(1).replace("<h1>", '<h1 id="h1">', 1)


LEGAL_META = HERE / "copy_v3" / "meta_legal.md"   # not part of the combined copy (COPY_SHA256 covers 01-17 only)


def legal_meta(name, path=LEGAL_META):
    """Meta description of a legal page: the PRIMARY variant («**Основной (N симв.):**», next line, verbatim) under
    «## /tenerife/<name>/»; N must equal the Unicode length. Fallback variants are ignored."""
    md = path.read_text(encoding="utf-8")
    m = re.search(rf"^## /tenerife/{name}/[^\n]*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not m:
        raise BuildError(f"meta_legal.md: no section for /tenerife/{name}/")
    p = re.search(r"^\*\*Основной \((\d+) симв\.\):\*\*\n(.+)$", m.group(1), re.M)
    if not p or len(p.group(2).strip()) != int(p.group(1)):
        raise BuildError(f"meta_legal.md: primary description for {name} missing or length != declared")
    return p.group(2).strip()


def simple_pages(env, nav, menu, footer):
    """QA T3-09: Impressum / privacy in the v2 layout; QA T3-05: shell of the no-JS form answers."""
    tpl = env.get_template("simple.html")
    out = {}
    for name, title in LEGAL.items():
        url = f"/tenerife/{name}/"
        out[name] = wrap(tpl.render(title=title, canonical=BASE_URL + url, url=url, kind="legal",
                                    description=html.escape(legal_meta(name), quote=True),
                                    body=legal_body(name), nav=nav, menu=menu, footer=footer))
    out["_notice"] = wrap(tpl.render(title="{{NOTICE_TITLE}} — Artemis de la Cruz", canonical=None, url="",
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
