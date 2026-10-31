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
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from email_off import unprotected, wrap  # noqa: E402

COPY = HERE / "copy_v3"
SITE = ROOT / "app" / "tenerife_site"
STATIC = ROOT / "app" / "static"
IMG = STATIC / "tenerife" / "site" / "img"
TEMPLATES = ROOT / "app" / "templates" / "tenerife" / "site"
MODEL = STATIC / "tenerife" / "site" / "model.json"
BASE_URL = "https://artemisresort.com"
COPY_SHA256 = "c60ce13336cabf1e34f88b95bf068e5646072e1da15c696f2b683d97f8303725"
WIDTHS = (640, 800, 1024, 1600)

# copy file -> output name (app/tenerife_site/<name>.html); URL comes from the copy's own «Слаг»
PAGES = [("01_glavnaya.md", "index"), ("02_sever.md", "norte"), ("03_rezidencii.md", "producto"),
         ("04_akcii.md", "acciones"), ("05_kalkulyator.md", "calculadora"), ("06_arenda.md", "alquiler"),
         ("07_energiya.md", "energia"), ("08_stroyka.md", "construccion"), ("09_sdelka.md", "proceso"),
         ("10_voprosy.md", "faq"), ("11_simon.md", "simon"), ("12_rynok.md", "mercado"), ("13_boris.md", "boris")]
FOOTER = "14_podval.md"
# footer «Страницы.» names -> output name (names are the copy's; order is the copy's)
NAV = {"Главная": "index", "Север": "norte", "Резиденции": "producto", "Акции": "acciones",
       "Калькулятор": "calculadora", "Аренда": "alquiler", "Энергия": "energia", "Стройка": "construccion",
       "Сделка": "proceso", "Вопросы": "faq", "Рынок и цена метра": "mercado", "Simon Subic": "simon",
       "Boris Ribaut": "boris"}
CALC_PAGE = "calculadora"
FORM_HOST_PAGE = "/tenerife/proceso/"

# DESIGN.md §5: pages 11 and 13 are long text (solid header, 760 px column); 05 and 10 have a short hero
LONG_PAGES = {"simon", "boris"}
SHORT_HERO = {"calculadora", "faq"}
# DESIGN.md C1: 7 links + «Ещё»; labels are the footer's («Страницы.»)
NAV_PRIMARY = ["norte", "producto", "acciones", "calculadora", "construccion", "proceso", "faq"]
NAV_MORE = ["alquiler", "energia", "mercado", "simon", "boris"]

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
def combined_sha():
    files = sorted(COPY.glob("[01][0-9]_*.md"))
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
    """Per page: each F-id gets its first preferred photo not used yet on this page."""
    used, out = set(), {}
    for fid in frame_ids:
        pick = None
        for stem in frames_cfg["prefer"].get(fid, []) + frames_cfg["fallback"]:
            if stem not in used:
                pick = stem
                break
        if pick is None:
            raise BuildError(f"no free photo for {fid}")
        used.add(pick)
        out[fid] = pick
    return out


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


def table_item(b):
    head = [inline(x) for x in b["head"]]
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


def structure(blocks, frames, frames_cfg, name):
    """Group blocks into hero / sections / cta and choose the DESIGN.md component per section.
    Text order inside a section never changes; pictures ([КАДР]) of a section are placed after its text."""
    alt = frames_cfg["images"]
    long_page = name in LONG_PAGES

    def img(fid, role):
        d = dict(image_variant(frames[fid]))
        d.update(alt=alt[frames[fid]], frame=fid, sizes=SIZES[role])
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
    hero = {"h1": inline(h1[0]["text"]), "h1_text": h1[0]["text"],
            "intro": [inline(b["text"]) for b in rest[:j]],
            "img": img(rest[j]["id"], "long" if long_page else "hero"),
            "kind": "text" if long_page else ("short" if name in SHORT_HERO else "full")}
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
    split_n = 0
    for n, s in enumerate(sections, 1):
        s["id"] = f"s{n}"
        s["rev"], s["qa"] = False, []
        body = s["body"]
        qa = [QA_RX.match(i["html"]) if i["kind"] == "p" else None for i in body]
        s["ladder"] = next((ladder_from(i) for i in body if i["kind"] == "table" and ladder_from(i)), None)
        if body and all(qa):
            s["layout"] = "faq"
            s["qa"] = [{"q": m.group(1), "a": m.group(2)} for m in qa]
        elif long_page:
            s["layout"] = "long"
        elif s["ladder"] or any(i["kind"] == "steps" for i in body):
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
            if set(names) != set(NAV) or len(names) != len(NAV):
                raise BuildError(f"footer pages differ from NAV: {names}")
            out["pages"] = names
        elif label == "Контакты.":
            out["contacts"] = rest.split(" · ")
        elif label == "Компания.":
            out["company"] = inline(rest)
        elif label == "Документы.":
            out["docs"] = [re.match(r"\[(.+)\]\((/[^)]+)\)", d).groups() for d in rest.split(" · ")]
        elif out["about"] is None:
            out["about"] = (label, inline(rest))
        else:
            raise BuildError(f"unknown footer line {p[:40]}")
    return out


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
    eur = lambda v: fmt_int(v) + NBSP + "€"
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


def site_css(model):
    """site.css = designer fonts.css + tokens.css (both as is) + components (site.src.css) + C8 ladder."""
    parts = [(DESIGN / "fonts.css").read_text(encoding="utf-8"), (DESIGN / "tokens.css").read_text(encoding="utf-8"),
             (HERE / "site.src.css").read_text(encoding="utf-8"), ladder_css(model)]
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


# ---------------------------------------------------------------- checks
ALLOWED_COMMENTS = ("<!--email_off-->", "<!--/email_off-->")


def check_output(name, out):
    errs = []
    for bad in ("[КАДР", "{{", "{%", "%}", "}}", "**", "Кнопка:"):
        if bad in out:
            errs.append(f"{name}: «{bad}» in output")
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
    if re.search(r'<script(?![^>]*\ssrc=)(?! type="application/json" id="cs-model")[^>]*>', out) or re.search(r"\son[a-z]+=", out) or "style=" in out:
        errs.append(f"{name}: inline script/style (CSP)")
    if errs:
        raise BuildError("\n".join(errs))


# ---------------------------------------------------------------- main
def build(model_path=MODEL, out_dir=SITE, write=True):
    if combined_sha() != COPY_SHA256:
        raise BuildError(f"copy_v3 sha256 {combined_sha()} != {COPY_SHA256} (copy changed: re-approve)")
    model = load_model(model_path)
    fmap = figure_map(model)
    rx = figure_regex(fmap)
    frames_cfg = json.loads((HERE / "frames.json").read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=False, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    footer = parse_footer((COPY / FOOTER).read_text(encoding="utf-8"), fmap, rx)
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
    for fname, name in PAGES:
        meta, blocks = metas[name], parsed[name]
        frame_ids = [b["id"] for b in blocks if b["kind"] == "frame"]
        frames = assign_frames(frame_ids, frames_cfg)
        page = structure(blocks, frames, frames_cfg, name)
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
        )
        out = wrap(out)
        check_output(name, out)
        outputs[name] = out
        report[name] = {"url": url, "file": fname, "frames": frames, "title": meta["Meta title"],
                        "h1": page["hero"]["h1_text"]}
    css = site_css(model)
    if write:
        (STATIC / "tenerife" / "site" / "site.css").write_text(css, encoding="utf-8")
        for name, out in outputs.items():
            (Path(out_dir) / f"{name}.html").write_text(out, encoding="utf-8")
    return outputs, report


def main():
    try:
        outputs, report = build()
    except BuildError as e:
        print("BUILD FAILED:\n" + str(e), file=sys.stderr)
        sys.exit(1)
    for name, r in report.items():
        fr = " ".join(f"{k}->{v.split('-')[0]}-{v.split('-')[1]}" for k, v in r["frames"].items())
        print(f"{r['url']:28} {len(outputs[name]):6d} B  {fr}")
    (HERE / "frames_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
