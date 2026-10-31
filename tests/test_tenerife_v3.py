"""Tenerife RU v3 (copy_v3 + Canary Stone design system): 13 pages built by
scripts/tenerife_site_build/build_v3.py. Re-runs every prod-site test over all 13 pages and checks
the v3 acceptance criteria: verbatim copy, one figure source (model.json), no markers, word counts,
design tokens as is, CSP-safe markup."""
import html as htmllib
import json
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
import build_v3  # noqa: E402
import make_model  # noqa: E402

V3 = {name: ("/tenerife/" if name == "index" else f"/tenerife/{name}/") for _f, name in build_v3.PAGES}
FILES = {name: f for f, name in build_v3.PAGES}
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
        # script-src 'self': the only inline <script> allowed is the non-executable JSON island of C9
        for name, url in V3.items():
            page, _ = self.page(url)
            scripts = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", page)
            self.assertEqual(scripts, ['<script type="application/json" id="cs-model">'] if name == "calculadora" else [], name)
            self.assertNotRegex(page, r"\son[a-z]+=", name)
            self.assertNotIn("style=", page, name)


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
            meta, _ = build_v3.parse_page((COPY / FILES[name]).read_text(encoding="utf-8"))
            md = (COPY / FILES[name]).read_text(encoding="utf-8")
            h1 = re.search(r"^# (.+)$", md, re.M).group(1)
            self.assertIn(f"<title>{htmllib.escape(meta['Meta title'], quote=True)}</title>", page, name)
            self.assertIn(f'<meta name="description" content="{htmllib.escape(meta["Meta description"], quote=True)}">', page, name)
            self.assertIn(f'<meta property="og:title" content="{htmllib.escape(meta["OG title"], quote=True)}">', page, name)
            got = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
            self.assertEqual(htmllib.unescape(re.sub(r"<[^>]+>", "", got)), h1, name)

    def test_page_text_is_the_copy_word_for_word(self):
        for name, page in self.pages.items():
            want = copy_words((COPY / FILES[name]).read_text(encoding="utf-8"))
            got = words(main_text(page))
            self.assertEqual(got, want, f"{name}: first diff at "
                             f"{next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))}")

    def test_footer_is_the_copy(self):
        want = copy_words((COPY / build_v3.FOOTER).read_text(encoding="utf-8"))
        for name, page in self.pages.items():
            foot = re.search(r"<footer.*?</footer>", page, re.S).group(0)
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
        model = json.loads((SITE_STATIC / "model.json").read_text(encoding="utf-8"))
        designer = json.loads((DESIGN / "model.json").read_text(encoding="utf-8"))
        for k, v in designer.items():
            self.assertEqual(model[k], v, k)

    def test_build_is_reproducible(self):
        outputs, _ = build_v3.build(write=False)
        for name, out in outputs.items():
            self.assertEqual(out, self.pages[name], name)
        self.assertEqual(build_v3.site_css(build_v3.load_model()), (SITE_STATIC / "site.css").read_text(encoding="utf-8"))

    def test_price_change_is_one_edit(self):
        inp = json.loads((BUILD / "model_inputs.json").read_text(encoding="utf-8"))
        inp["stages"][0][1] = 3000
        model = make_model.build_model(inp)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model.json"
            p.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            outputs, _ = build_v3.build(model_path=p, write=False)
        joined = "\n".join(outputs.values())
        self.assertNotIn("2 950", joined)
        self.assertNotIn("2\u00a0950", joined)
        self.assertIn("216 000", outputs["index"])          # 72 × 3 000 (mini calculation)
        self.assertIn("216\u00a0000", outputs["calculadora"])  # calculator default, server-rendered
        self.assertIn('"price_eur_m2":3000', outputs["calculadora"])

    def test_no_hardcoded_figures_in_templates_and_js(self):
        model = json.loads((SITE_STATIC / "model.json").read_text(encoding="utf-8"))
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
        for name, page in self.pages.items():
            md = (COPY / FILES[name]).read_text(encoding="utf-8")
            ids = re.findall(r"^\[КАДР (F\d\d)\]", md, re.M)
            self.assertEqual(list(report[name]["frames"]), ids, name)
            self.assertEqual(len(re.findall(r"<img ", page)), len(ids), name)
            for stem in report[name]["frames"].values():
                self.assertIn(stem, cfg["images"])
                self.assertIn(f"/static/tenerife/site/img/{stem}.jpg", page)

    # ---- criterion 4: words
    def test_visible_words_per_page(self):
        for name, page in self.pages.items():
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
            self.assertEqual(len(re.findall(r'aria-current="page"', head)), 2, name)  # desktop nav (or brand on index) + sheet

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
            self.assertIn('<link rel="preload" href="/static/tenerife/site/fonts/literata-cyrillic-500.woff2" as="font" type="font/woff2" crossorigin>', page)

    def test_designer_files_unchanged_copy(self):
        src = Path("/workspace/web-designer/tenerife/design")
        if not src.is_dir():
            self.skipTest("designer folder not on this machine")
        for f in ("tokens.css", "fonts.css", "model.json"):
            self.assertEqual((DESIGN / f).read_bytes(), (src / f).read_bytes(), f)

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
        allowed_text = ["+34 674 567 789", "4–6% аренды", "валовая доходность 5,8%"]
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
