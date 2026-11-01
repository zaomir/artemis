"""Tenerife RU v3 (copy_v3 + Canary Stone design system): 13 pages built by
scripts/tenerife_site_build/build_v3.py. Re-runs every prod-site test over all 13 pages and checks
the v3 acceptance criteria: verbatim copy, one figure source (model.json), no markers, word counts,
design tokens as is, CSP-safe markup."""
import html as htmllib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import test_tenerife_site as base

ROOT = base.ROOT
BUILD = ROOT / "scripts" / "tenerife_site_build"
COPY = BUILD / "copy_v3"
DESIGN = BUILD / "design"
SITE_STATIC = base.STATIC / "tenerife" / "site"
TEMPLATES = ROOT / "app" / "templates" / "tenerife" / "site"
sys.path.insert(0, str(BUILD))
# build_v3.build() requires a valid TENERIFE_WHATSAPP (Kimi r16); a fake one, the output never contains it
os.environ.setdefault("TENERIFE_WHATSAPP", "+440000000000")
import build_v3  # noqa: E402
import make_model  # noqa: E402

V3 = {name: ("/tenerife/" if name == "index" else f"/tenerife/{name}/") for _f, name in build_v3.PAGES}
FILES = {name: f for f, name in build_v3.PAGES}


def shown_copy(name):
    """The copy of a page minus sections the build hides (build_v3.HIDDEN_SECTIONS: C11 off, designer r3) and minus
    the figures (r4.1: the committed pages are built with TENERIFE_SHOW_FIGURES off)."""
    md = build_v3.hide_figures_md((COPY / FILES[name]).read_text(encoding="utf-8"), None, name)
    lines, out, skip = md.splitlines(), [], False
    for line in lines:
        h = re.match(r"^#{1,3} (.+)$", line)
        if h:
            skip = (name, h.group(1).strip()) in build_v3.HIDDEN_SECTIONS
        elif line.strip() == "---":
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out) + "\n"
# wc.py (copy_v3): numbers with thin/regular spaces count as one word
NUM = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?"
WORD = re.compile(NUM + r"|[^\W_]+(?:[-’'.,][^\W_]+)*")


class V3AllPagesTest(base.TenerifeSiteTest):
    """Every test of the prod Tenerife suite, run over the 13 v3 pages (form lives on every page)."""

    @classmethod
    def setUpClass(cls):
        cls.saved_mod = (base.PAGES, base.SHIPPED, base.FORM_HOST)
        base.PAGES = dict(V3)
        base.SHIPPED = dict(V3)
        base.FORM_HOST = "proceso"

    @classmethod
    def tearDownClass(cls):
        base.PAGES, base.SHIPPED, base.FORM_HOST = cls.saved_mod

    def test_no_inline_script_for_csp(self):
        # script-src 'self': inline <script> only as non-executable data: the JSON island of C9 (calculadora,
        # short on acciones) and JSON-LD (Organization on index, BreadcrumbList elsewhere, + FAQPage on faq)
        ld, island = '<script type="application/ld+json">', '<script type="application/json" id="cs-model">'
        # r4.1: figures off -> no calculator anywhere; the island comes back only with TENERIFE_SHOW_FIGURES=1
        allowed = {"faq": [ld, ld]}
        self.assertNotIn(island, "".join(self.page(u)[0] for u in V3.values()))
        for name, url in V3.items():
            page, _ = self.page(url)
            scripts = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", page)
            self.assertEqual(scripts, allowed.get(name, [ld]), name)
            self.assertNotRegex(page, r"\son[a-z]+=", name)
            self.assertNotIn("style=", page, name)

    def test_images_responsive_webp_sized_lazy(self):
        # designer r2: a hero slot may have no photo (text hero + basalt bar) -> then nothing is preloaded
        # and every picture is lazy; with a hero photo the prod rule holds (first image eager + preload)
        for name, url in V3.items():
            page, _ = self.page(url)
            imgs = re.findall(r"<img[^>]+>", page)  # T47: may be empty (one photo = one slot site-wide)
            hero_img = re.search(r'<div class="hero__media"><picture>|<figure class="frame hero-text__frame">', page)
            for i, tag in enumerate(imgs):
                self.assertRegex(tag, r'width="\d+" height="\d+"', f"{name}: no size {tag}")
                if i == 0 and hero_img:
                    self.assertIn('fetchpriority="high"', tag, name)
                    self.assertNotIn('loading="lazy"', tag, name)
                else:
                    self.assertIn('loading="lazy"', tag, f"{name}: {tag}")
                    self.assertNotIn("fetchpriority", tag, name)
            self.assertEqual(len(re.findall(r'<source type="image/webp"', page)), len(imgs), name)
            self.assertEqual(page.count('<link rel="preload" as="image" type="image/webp" imagesrcset='),
                             1 if hero_img else 0, name)
            for srcset in re.findall(r'(?:imagesrcset|srcset)="([^"]+)"', page):
                parts = [part.split(" ") for part in srcset.split(", ")]
                for ref, _w in parts:
                    self.assertTrue(ref.endswith(".webp") and (base.STATIC / ref[len("/static/"):]).is_file(), ref)
                self.assertEqual([w for _r, w in parts], ["640w", "800w", "1024w", "1600w"], name)


# ------------------------------------------------------------------ text extraction
class _Text(HTMLParser):
    """Visible text of <main> in document order. Skips aria-hidden subtrees (C8 ladder duplicates the table,
    step numbers), visually-hidden text, the calculator widget (#calc: labels repeat the copy, values are
    computed) and the form fields; inside the form only the button and its microcopy (the copy's) count."""
    VOID = {"img", "input", "br", "hr", "source", "meta", "link", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.out = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        hide = (a.get("aria-hidden") == "true" or a.get("id") == "calc" or tag in ("script", "style")
                or "visually-hidden" in cls)
        keep = "cta-primary" in cls or "micro" in cls
        self.stack.append((tag, hide, keep))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        tags = [t for t, _h, _k in self.stack]
        if "main" not in tags or any(h for _t, h, _k in self.stack):
            return
        if "form" in tags and not any(k for _t, _h, k in self.stack):
            return
        self.out.append(data)


def main_text(page):
    p = _Text()
    p.feed(page)
    return " ".join(p.out)


def words(text):
    return WORD.findall(text.replace("\u00a0", " "))


def copy_words(md):
    """Words of a copy file as published: no META/comments, no [КАДР] markers, no markdown syntax."""
    md = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    md = re.sub(r"^\[КАДР F\d\d\].*$", " ", md, flags=re.M)
    md = re.sub(r"^\*\*Кнопка: «(.+)»\*\*$", r"\1", md, flags=re.M)
    md = re.sub(r"^\|(?:\s*:?-+:?\s*\|)+\s*$", " ", md, flags=re.M)
    md = re.sub(r"\[([^\]]+)\]\((/[^)\s]*)\)", r"\1", md)
    md = re.sub(r"^(?:#{1,3} |\d+\. |- )", " ", md, flags=re.M)
    md = md.replace("**", " ").replace("|", " ")
    md = re.sub(r"^---$", " ", md, flags=re.M)
    return words(md)


class V3BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {n: (base.SITE / f"{n}.html").read_text(encoding="utf-8") for n in V3}

    # ---- criterion 1: texts as written
    def test_copy_sha_pinned(self):
        self.assertEqual(build_v3.combined_sha(), build_v3.COPY_SHA256)

    def test_meta_title_description_h1_exact(self):
        for name, page in self.pages.items():
            md = build_v3.hide_figures_md((COPY / FILES[name]).read_text(encoding="utf-8"), None, name)  # r4.1
            meta = build_v3.hide_figures_meta(build_v3.parse_page(md)[0], md)
            h1 = re.search(r"^# (.+)$", md, re.M).group(1)
            self.assertIn(f"<title>{htmllib.escape(meta['Meta title'], quote=True)}</title>", page, name)
            desc, og = (htmllib.escape(meta[k], quote=True) for k in ("Meta description", "OG title"))
            self.assertIn(f'<meta name="description" content="{desc}">', page, name)
            self.assertIn(f'<meta property="og:title" content="{og}">', page, name)
            got = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
            self.assertEqual(htmllib.unescape(re.sub(r"<[^>]+>", "", got)), h1, name)

    def test_page_text_is_the_copy_word_for_word(self):
        for name, page in self.pages.items():
            want = copy_words(shown_copy(name))
            got = words(main_text(page))
            self.assertEqual(got, want, f"{name}: first diff at "
                             f"{next((i for i, (a, b) in enumerate(zip(got, want, strict=False)) if a != b),
                                     min(len(got), len(want)))}")

    def test_footer_is_the_copy(self):
        # Kimi r16: «WhatsApp: {номер из TENERIFE_WHATSAPP}» = the WhatsApp slot (filled at runtime, test_tenerife_r4)
        md = build_v3.hide_figures_md((COPY / build_v3.FOOTER).read_text(encoding="utf-8"))   # r4.1: figures off
        self.assertEqual(md.count(" · " + build_v3.WA_TOKEN), 1)
        md = md.replace(" · " + build_v3.WA_TOKEN, "")
        for item in build_v3.NAV_FUTURE:  # Kimi r18 «Инвесторам»: hidden until page 18 is built (no broken link)
            md = md.replace(" · " + item, "")
        want = copy_words(md)
        for name, page in self.pages.items():
            foot = re.search(r"<footer.*?</footer>", page, re.S).group(0)
            self.assertEqual(foot.count("<li data-tenerife-whatsapp hidden></li>"), 1, name)
            got = words(htmllib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<!--/?email_off-->", "", foot))))
            self.assertEqual(got, want, name)

    def test_one_main_cta_per_page(self):
        for name, page in self.pages.items():
            self.assertEqual(len(re.findall(r'class="[^"]*\bcta-primary\b[^"]*"', page)), 1, name)
            btn = re.search(r'class="[^"]*\bcta-primary\b[^"]*"[^>]*>([^<]+)<', page).group(1)
            md = (COPY / FILES[name]).read_text(encoding="utf-8")
            self.assertIn(f"**Кнопка: «{htmllib.unescape(btn)}»**", md, name)

    # ---- criterion 2: one figure source
    def test_model_up_to_date_and_baseline(self):
        r = subprocess.run([sys.executable, str(BUILD / "make_model.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(make_model.baseline_check(), [])

    def test_model_matches_designer_schema(self):
        model = json.loads((build_v3.MODEL).read_text(encoding="utf-8"))
        designer = json.loads((DESIGN / "model.json").read_text(encoding="utf-8"))
        for k, v in designer.items():
            if k == "steps":  # Kimi r18: the stage event is the copy's (04 table); the designer file still has r17's
                v = [dict(st, event=m["event"]) for st, m in zip(v, model["steps"], strict=True)]
                self.assertEqual(model["steps"][0]["event"],
                                 "участок одобрен большинством очереди, инвестиционный договор")
            self.assertEqual(model[k], v, k)

    def test_build_is_reproducible(self):
        outputs, _ = build_v3.build(write=False)
        for name, out in outputs.items():  # 13 pages + impressum, privacy, _notice (QA T3-05, T3-09)
            self.assertEqual(out, (base.SITE / f"{name}.html").read_text(encoding="utf-8"), name)
        self.assertEqual(build_v3.site_css(build_v3.load_model()),
                         (SITE_STATIC / "site.css").read_text(encoding="utf-8"))

    def test_price_change_is_one_edit(self):
        inp = json.loads((BUILD / "model_inputs.json").read_text(encoding="utf-8"))
        inp["stages"][0][1] = 3000
        model = make_model.build_model(inp)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model.json"
            p.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            outputs, _ = build_v3.build(model_path=p, write=False, show_figures=True)   # r4.1: figures on
        joined = "\n".join(outputs.values())
        self.assertNotIn("2 950", joined)
        self.assertNotIn("2\u00a0950", joined)
        self.assertIn("216 000", outputs["index"])          # 72 × 3 000 (mini calculation)
        self.assertIn("216\u00a0000", outputs["calculadora"])  # calculator default, server-rendered
        self.assertIn('"price_eur_m2":3000', outputs["calculadora"])

    def test_no_hardcoded_figures_in_templates_and_js(self):
        model = json.loads((build_v3.MODEL).read_text(encoding="utf-8"))
        figs = {t["value"] for t in model["tokens"] + model["extra"] if len(re.sub(r"\D", "", t["value"])) >= 3}
        for f in list(TEMPLATES.glob("*.html")) + [SITE_STATIC / "calc.js", SITE_STATIC / "site.js"]:
            src = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", " ", f.read_text(encoding="utf-8"), flags=re.S)
            self.assertIsNone(re.search(r"(?<![\w\\])\d\s*(?:€|м²|%)", src), f.name)
            for v in figs:
                self.assertNotIn(v, src, f"{f.name}: {v}")

    # ---- criterion 3: frames, no markers
    def test_no_markers_or_comments_in_output(self):
        for name, page in self.pages.items():
            for bad in ("[КАДР", "{{", "{%", "**", "Кнопка:"):
                self.assertNotIn(bad, page, name)
            comments = re.findall(r"<!--.*?-->", page, re.S)
            self.assertTrue(set(comments) <= {"<!--email_off-->", "<!--/email_off-->"}, (name, set(comments)))

    def test_build_fails_on_marker(self):
        ok = (base.SITE / "norte.html").read_text(encoding="utf-8")
        build_v3.check_output("norte", ok)
        for bad in ("<p>[КАДР F01]</p>", "<p>{{ x }}</p>", "<!-- note -->", "<p>**b**</p>",
                    "<script>alert(1)</script>", '<p style="x">'):
            with self.assertRaises(build_v3.BuildError, msg=bad):
                build_v3.check_output("norte", ok.replace("</main>", bad + "</main>"))
        with self.assertRaises(build_v3.BuildError):
            build_v3.parse_page("# H\n\nтекст [КАДР F01] в строке\n")

    def test_every_frame_is_a_project_photo(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        cfg = json.loads((BUILD / "frames.json").read_text(encoding="utf-8"))
        alts = json.loads((BUILD / "alts.json").read_text(encoding="utf-8"))
        for name, page in self.pages.items():
            md = shown_copy(name)
            ids = re.findall(r"^\[КАДР (F\d\d)\]", md, re.M)
            self.assertEqual(list(report[name]["frames"]), ids, name)
            stems = [s for s in report[name]["frames"].values() if s]
            self.assertEqual(len(re.findall(r"<img ", page)), len(stems), name)
            for fid, stem in report[name]["frames"].items():
                if stem is None:
                    continue
                self.assertIn(stem, cfg["prefer"][fid], f"{name} {fid}: only a theme-matching photo")
                self.assertIn(stem, alts["images"])
                self.assertIn(f"/static/tenerife/site/img/{stem}.jpg", page)

    # ---- designer r2 (31.10.2026), item 1: photos until the Leonardo frames arrive
    def test_r2_photo_at_most_once_per_page(self):
        site = []  # T47 (31.10.2026): at most once on the whole site, not only per page
        for name, page in self.pages.items():
            srcs = re.findall(r'<img [^>]*src="/static/tenerife/site/img/([^"]+)\.jpg"', page)
            site += srcs
            self.assertEqual(len(srcs), len(set(srcs)), f"{name}: {srcs}")
            webp = [re.sub(r"-\d+\.webp$", "", u.split()[0].rsplit("/", 1)[1])
                    for u in re.findall(r'<source type="image/webp" srcset="([^"]+)"', page)]
            self.assertEqual(sorted(webp), sorted(srcs), name)
        self.assertTrue(site)
        self.assertEqual(len(site), len(set(site)), site)

    # ---- designer r3 (31.10.2026), item 1: F17 («отделка») never shows a finished-house photo
    def test_r3_f17_no_finished_house_photo(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        cfg = json.loads((BUILD / "frames.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["prefer"]["F17"], [])
        with_f17 = {n for n, r in report.items() if "F17" in r["frames"]}
        # r4.1: the F17 slots of calculadora / mercado sit in sections hidden with the figures
        self.assertEqual(with_f17, {"index", "acciones", "construccion", "proceso"})
        for name in with_f17:
            self.assertIsNone(report[name]["frames"]["F17"], name)
            others = [s for f, s in report[name]["frames"].items() if f != "F17" and s]
            self.assertEqual("F17" in report[name]["hidden"], name != "construccion" and bool(others), name)
        with self.assertRaises(build_v3.BuildError):
            build_v3.structure([], {"F17": "golden-hou-d4cc25"}, {}, "index")

    def test_r3_f17_text_block_with_bar_on_construccion(self):
        md = (COPY / FILES["construccion"]).read_text(encoding="utf-8")
        head = None
        for line in md.splitlines():
            if re.match(r"^#{2,3} ", line):
                head = re.sub(r"^#+ ", "", line).strip()
            if line.startswith("[КАДР F17]"):
                break
        page = self.pages["construccion"]
        sec = next(c.split("</section>")[0] for c in re.split(r"(?=<section\b)", page) if f">{head}<" in c)
        self.assertIn(" bar-under", sec)
        self.assertNotIn("<figure", sec)
        self.assertNotIn("<img", sec)

    def test_r2_slots_without_subject_have_no_image(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        for name in self.pages:
            for fid in ("F13", "F18", "F19", "F20"):
                if fid in report[name]["frames"]:
                    self.assertIsNone(report[name]["frames"][fid], f"{name} {fid}")

    def test_r2_no_empty_figure_or_placeholder(self):
        for name, page in self.pages.items():
            figs = re.findall(r"<figure\b.*?</figure>", page, re.S)
            self.assertEqual(len(figs), page.count("<figure"), name)
            for f in figs:
                self.assertRegex(f, r"<picture><source [^>]+><img [^>]+></picture>", f"{name}: empty figure {f[:120]}")
                self.assertNotIn("<figcaption", f, name)
            heroes = page.count('class="hero__media')
            self.assertEqual(page.count('class="frame__media'), page.count("<picture>") - heroes, name)
            self.assertEqual(page.count('<div class="hero__media">'),
                             page.count('<div class="hero__media"><picture>'), name)

    def test_r2_text_block_gets_basalt_bar(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        for name, page in self.pages.items():
            md = shown_copy(name)
            groups, cur = [], None    # [КАДР] slots per hero / ### section, in copy order
            for line in md.splitlines():
                if re.match(r"^#{1,3} ", line):
                    cur = []
                    groups.append(cur)
                m = re.match(r"^\[КАДР (F\d\d)\]", line)
                if m and m.group(1) not in report[name].get("hidden", []):   # designer r3: hidden F17 slot
                    cur.append(m.group(1))
            hero_slot = groups[0][0]
            groups = [groups[0][:1]] + ([groups[0][1:]] if groups[0][1:] else []) + groups[1:]
            expected = sum(1 for g in groups if g and all(report[name]["frames"][f] is None for f in g))
            self.assertEqual(page.count(" bar-under"), expected, name)
            for chunk in re.split(r"(?=<section\b)", page):
                if " bar-under" in chunk:
                    self.assertNotIn("<figure", chunk.split("</section>")[0], name)
            if report[name]["frames"][hero_slot] is None:
                self.assertNotIn('id="hero"', page, name)
                self.assertIn('<section class="hero-text"', page, name)
        css = (SITE_STATIC / "site.css").read_text(encoding="utf-8")
        self.assertIn(".bar-under::after{content:\"\";display:block;grid-column:1/-1;height:var(--plinth);"
                      "background:var(--cs-basalt);", css)
        tokens = (DESIGN / "tokens.css").read_text(encoding="utf-8")
        self.assertRegex(tokens, r"--plinth:\s*6px;")
        self.assertRegex(tokens, r"--cs-basalt:\s*#3A3A38;")

    def test_r2_focal_point_class_per_photo(self):
        cfg = json.loads((BUILD / "frames.json").read_text(encoding="utf-8"))
        photos = {p.stem for p in (SITE_STATIC / "img").glob("*.jpg") if not p.stem.startswith("og-")}
        self.assertEqual(set(cfg["focal"]), photos)
        self.assertEqual(len(photos), 7)
        css = (SITE_STATIC / "site.css").read_text(encoding="utf-8")
        block = css[css.index("@media (max-width:767px){\n  .hero__media .fp-"):]
        block = block[:block.index("\n}\n")]
        for stem, pos in cfg["focal"].items():
            self.assertIn(f".hero__media .fp-{stem}{{object-position:{pos}}}", block)
        self.assertIn(".hero__media{position:relative;background:var(--cs-placeholder);aspect-ratio:4/5;", css)
        for name, page in self.pages.items():
            for cls, src in re.findall(r'<img class="fp-([^"]+)" src="/static/tenerife/site/img/([^"]+)\.jpg"', page):
                self.assertEqual(cls, src, name)
            self.assertEqual(page.count("<img "), page.count('<img class="fp-'), name)

    # ---- item 4: alts from a data file + review list
    def test_r2_alts_come_from_data_file(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        alts = json.loads((BUILD / "alts.json").read_text(encoding="utf-8"))
        for name, page in self.pages.items():
            for fid, stem in report[name]["frames"].items():
                if stem:
                    alt = alts["slots"].get(f"{name}/{fid}", {}).get("alt") or alts["images"][stem]
                    alt_attr = htmllib.escape(alt, quote=True)
                    self.assertIn(f'src="/static/tenerife/site/img/{stem}.jpg" alt="{alt_attr}"', page)
        # an edited alts.json changes the HTML without any code change; a stale override fails the build
        name, fid = "index", "F01"
        stem = report[name]["frames"][fid]
        edited = json.loads(json.dumps(alts))
        edited["slots"][f"{name}/{fid}"] = {"file": stem, "alt": "Проверка: «дом» & склон"}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "alts.json"
            p.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
            outputs, _ = build_v3.build(write=False, alts_path=p)
            self.assertIn('alt="Проверка: «дом» &amp; склон"', outputs[name])
            edited["slots"][f"{name}/{fid}"]["file"] = "green-hill-3f3856"
            p.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(build_v3.BuildError):
                build_v3.build(write=False, alts_path=p)

    def test_r2_alt_review_export_import(self):
        sys.path.insert(0, str(BUILD))
        import alts as alts_tool
        with tempfile.TemporaryDirectory() as tmp:
            md, store = Path(tmp) / "alt_review.md", Path(tmp) / "alts.json"
            n = alts_tool.export(md)
            self.assertEqual(n, sum(p.count("<img ") for p in self.pages.values()))
            text = md.read_text(encoding="utf-8")
            self.assertIn("| Страница | URL | Слот | Файл | Alt |", text)
            store.write_text((BUILD / "alts.json").read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(alts_tool.import_md(md, store), 0)
            self.assertEqual(store.read_text(encoding="utf-8"), (BUILD / "alts.json").read_text(encoding="utf-8"))
            row = "| index | /tenerife/ | F01 | modern-low-6e9d80.jpg | "
            md.write_text(text.replace(row + "Невысокие дома террасами на склоне над океаном |",
                                       row + "Новый alt | с чертой |"), encoding="utf-8")
            with self.assertRaises(SystemExit):     # an unescaped «|» breaks the row -> refused, nothing written
                alts_tool.import_md(md, store)
            md.write_text(text.replace("Невысокие дома террасами на склоне над океаном |",
                                       "Новый alt \\| с чертой |", 1), encoding="utf-8")
            self.assertEqual(alts_tool.import_md(md, store), 1)
            self.assertEqual(json.loads(store.read_text(encoding="utf-8"))["slots"]["index/F01"],
                             {"file": "modern-low-6e9d80", "alt": "Новый alt | с чертой"})

    # ---- item 5: FAQPage JSON-LD = visible questions and answers, word for word
    def test_r2_faq_jsonld_equals_visible_text(self):
        for name, page in self.pages.items():
            if name != "faq":
                self.assertNotIn('"FAQPage"', page, name)
        page = self.pages["faq"]
        lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        self.assertEqual(len(lds), 2)  # FAQPage + BreadcrumbList (QA T3-08)
        self.assertNotIn("<", lds[0])
        ld = json.loads(lds[0])
        self.assertEqual((ld["@context"], ld["@type"]), ("https://schema.org", "FAQPage"))

        class QA(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.pairs, self.cur, self.inside = [], None, False

            def handle_starttag(self, tag, attrs):
                if tag == "details":
                    self.pairs.append(["", ""])
                    self.inside = True
                elif tag == "summary" and self.inside:
                    self.cur = 0
                elif tag == "p" and self.inside:
                    self.cur = 1

            def handle_endtag(self, tag):
                if tag in ("summary", "p"):
                    self.cur = None
                elif tag == "details":
                    self.inside = False

            def handle_data(self, data):
                if self.cur is not None:
                    self.pairs[-1][self.cur] += data

        p = QA()
        p.feed(page[page.index("<main"):page.index("</main>")])
        visible = [(" ".join(q.split()), " ".join(a.split())) for q, a in p.pairs]
        self.assertGreaterEqual(len(visible), 10)
        got = [(e["name"], e["acceptedAnswer"]["text"]) for e in ld["mainEntity"]]
        self.assertEqual(len(got), len(visible))
        for (q, a), (gq, ga) in zip(visible, got, strict=True):
            self.assertEqual(gq, q)
            self.assertEqual(ga, a)
            self.assertTrue(q.endswith("?"), q)
        for e in ld["mainEntity"]:
            self.assertEqual((e["@type"], e["acceptedAnswer"]["@type"]), ("Question", "Answer"))

    # ---- item 7 + design v2 C13: the calculadora form sends exactly page, calc_m2, calc_step, calc_pay
    def test_r2_calc_hidden_fields_valid_by_default(self):
        sys.path.insert(0, str(ROOT / "app"))
        import tenerife_calc
        page = build_v3.build(write=False, show_figures=True)[0][build_v3.CALC_PAGE]   # r4.1: calculator = figures on
        form = page[page.index('<form class="wl__form'):page.index("</form>")]
        self.assertIn('data-variant="calculadora"', form[:form.index(">")])
        hidden = dict(re.findall(r'<input type="hidden" name="([a-z0-9_]+)"(?: id="[a-z0-9-]+")? value="([^"]*)">',
                                 form))
        self.assertEqual(set(hidden), {"page", "calc_m2", "calc_step", "calc_pay"})
        self.assertEqual(tenerife_calc.FIELDS, ("calc_m2", "calc_step", "calc_pay"))
        self.assertEqual(hidden["page"], "/tenerife/calculadora/")
        model = tenerife_calc.load_model(build_v3.MODEL)
        self.assertNotIn(model["version"], form)          # the version stays server-side
        calc, problems = tenerife_calc.check_calc(hidden, model)
        self.assertEqual((problems, calc["calc_status"]), ([], "ok"))
        self.assertEqual((calc["calc_m2"], calc["calc_step"], calc["calc_pay"], calc["calc_model_version"]),
                         (model["area_m2"]["default"], "queue", "m12", model["version"]))
        for name, other in self.pages.items():
            if name != build_v3.CALC_PAGE:
                self.assertNotIn('name="calc_', other, name)
        js = (SITE_STATIC / "calc.js").read_text(encoding="utf-8")
        self.assertIn("['m2','step','pay']", js)
        for gone in ("'type','shares'", "'amount'", "'version'", "hid.version", "hid.amount"):
            self.assertNotIn(gone, js)
        self.assertIn("/^calc_/.test(el[i].name)", (SITE_STATIC / "waitlist.js").read_text(encoding="utf-8"))

    # ---- criterion 4: words
    def test_visible_words_per_page(self):
        # r4.1: the copy-length criterion is about the copy, i.e. the build with the figures on
        for name, page in build_v3.build(write=False, show_figures=True)[0].items():
            if name not in self.pages:
                continue
            n = len(words(main_text(page)))
            self.assertGreaterEqual(n, 500 if name == build_v3.CALC_PAGE else 700, f"{name}: {n}")

    # ---- criterion 5: SEO, links, routes, deploy
    def test_hreflang_ru_only_and_no_other_languages(self):
        for name, page in self.pages.items():
            self.assertEqual(re.findall(r'hreflang="([^"]+)"', page), ["ru"], name)
            self.assertIsNone(re.search(r'href="/(?:es|de|fr|en)/', page), name)
            self.assertIn('<html lang="ru">', page)

    def test_routes_sitemap_deploy(self):
        import tenerife
        self.assertEqual(set(tenerife.SITE_PAGES) | {"index"}, set(V3))
        deploy = (ROOT / "deploy" / "artemis-deploy.sh").read_text(encoding="utf-8")
        for url in V3.values():
            self.assertIn(f" {url} ", deploy.replace("(", " ").replace("\n", " "), url)
        for page in self.pages.values():
            for ref in re.findall(r'(?:href|src)="(/static/tenerife/site/[^"]+\.(?:css|js))"', page):
                self.assertIn(ref, deploy, ref)

    def test_header_nav_and_sheet_cover_all_pages(self):
        for name, page in self.pages.items():
            head = re.search(r"<header.*?</header>", page, re.S).group(0)
            self.assertEqual(len(re.findall(r'class="[^"]*\bcta-primary\b[^"]*"', head)), 0, name)
            self.assertIn('href="#footer-pages"', head)
            for url in V3.values():
                self.assertIn(f'href="{url}"', head, (name, url))
            # desktop nav (or brand on index) + sheet
            self.assertEqual(len(re.findall(r'aria-current="page"', head)), 2, name)

    def test_js_budget(self):
        total = sum((SITE_STATIC / f).stat().st_size for f in ("site.js", "waitlist.js", "calc.js"))
        self.assertLessEqual(total, 170 * 1024)
        self.assertLessEqual((SITE_STATIC / "calc.js").stat().st_size, 15 * 1024)

    # ---- design system
    def test_tokens_and_fonts_included_as_is(self):
        css = (SITE_STATIC / "site.css").read_text(encoding="utf-8")
        for f in ("tokens.css", "fonts.css"):
            self.assertIn((DESIGN / f).read_text(encoding="utf-8"), css, f)
        for font in re.findall(r"url\((fonts/[^)]+)\)", css):
            self.assertTrue((SITE_STATIC / font).is_file(), font)
        self.assertNotIn("Newsreader", css)
        self.assertIn('family:"Literata"', css.replace("font-family: ", "family:").replace("font-family:", "family:"))
        for page in self.pages.values():
            self.assertIn('<link rel="preload" href="/static/tenerife/site/fonts/literata-cyrillic-500.woff2" '
                          'as="font" type="font/woff2" crossorigin>', page)

    def test_designer_files_unchanged_copy(self):
        # QA T3-13: design v2 is vendored in the repo; the designer's sha256 list (QA_BRIEF.md) is checked here,
        # nothing outside the repo is read
        lines = [x for x in (DESIGN / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if x and x[0] != "#"]
        self.assertEqual(len(lines), 19)  # design v3.1: tokens.css, fonts.css, model.json + 16 fonts / OFL
        for line in lines:
            sha, rel = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((DESIGN / rel).read_bytes()).hexdigest(), sha, rel)
        for f in ("tokens.css", "fonts.css", "model.json"):
            self.assertIn("  " + f, "\n".join(lines))
        # QA r16: the designer docs (DESIGN.md, QA_BRIEF.md, components.html) are not vendored: unused by the build,
        # and they still show the old copy phone; their sha256 stays in the SHA256SUMS header as a reference
        for f in ("DESIGN.md", "QA_BRIEF.md", "components.html"):
            self.assertFalse((DESIGN / f).exists(), f)

    def test_designer_update_header_button_rounding(self):
        # C1: header is solid in the HTML (no state class); .is-over is set only by site.js over the hero picture
        for name, page in self.pages.items():
            self.assertIn('<header class="header" id="site-header">', page, name)
            self.assertEqual(len(re.findall(r'class="cta-primary btn-primary"', page)), 1, name)
        js = (SITE_STATIC / "site.js").read_text(encoding="utf-8")
        self.assertIn("is-over", js)
        self.assertNotIn("addEventListener('scroll'", js)
        # one rounding rule: half-up (model.json rounding), the same in build and calc.js
        self.assertEqual(build_v3.fmt_pct(2.25), "2,3%")
        self.assertEqual(build_v3.fmt_int(2.5), "3")
        calc = (SITE_STATIC / "calc.js").read_text(encoding="utf-8")
        self.assertIn("Math.floor(n+0.5)", calc)
        self.assertIn("roundingMode:'halfExpand'", calc)
        self.assertIn("hu((t.min+t.max)/2)", calc)  # type radio = middle of its range

    def test_tables_stack_with_labels_and_row_headers(self):
        for name, page in self.pages.items():
            for t in re.findall(r"<table.*?</table>", page, re.S):
                ncol = len(re.findall(r"<t[hd][ >]", re.search(r"<thead>.*?</thead>", t, re.S).group(0)))
                if ncol > 3:
                    self.assertIn("dt--stack", t, name)
                for row in re.findall(r"<tbody>.*?</tbody>", t, re.S)[0].split("<tr>")[1:]:
                    self.assertTrue(row.startswith('<th scope="row">'), name)
                    self.assertEqual(row.count("<td"), row.count("data-label="), name)

    # ---- §7.2 bans + the five approved-copy exceptions, narrowed
    def test_v3_bans(self):
        bans = [r"(?i)гарантир\w*[^.]{0,40}доход", r"(?i)\bдол[яиюе]\b", r"(?i)пирамид", r"(?i)lorem",
                r"(?i)уникальн", r"(?i)гармони", r"(?i)погрузит", r"(?i)ветр\w* нет", r"(?i)ни одного ветрен"]
        for name, page in self.pages.items():
            for rx in bans:
                self.assertIsNone(re.search(rx, page), f"{name}: {rx}")

    def test_approved_exceptions_only_where_the_copy_has_them(self):
        allowed_text = ["4–6% аренды", "валовая доходность 5,8%"]
        pages_for = {r"нельзя": {"alquiler"}, r"Сумма": {"calculadora", "index", "proceso"}}
        for name, page in self.pages.items():
            text = page
            for s in allowed_text:
                text = text.replace(s, "")
            for rx in base.V3_ALLOWED:
                if rx in pages_for:
                    if name not in pages_for[rx]:
                        self.assertIsNone(re.search(rx, text), f"{name}: {rx}")
                else:
                    self.assertIsNone(re.search(rx, text), f"{name}: {rx}")


if __name__ == "__main__":
    unittest.main()
