"""QA protocol 2026-10-31_tenerife-ru-v3 (T3-03 … T3-12): regression tests. Telegram is always mocked, the
database is a temp file — nothing is sent anywhere."""
import hashlib
import html as htmllib
import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))
SITE = ROOT / "app" / "tenerife_site" / "ru"
BUILD = ROOT / "scripts" / "tenerife_site_build"
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID", "TENERIFE_WHATSAPP", "TENERIFE_INDEXING")

import build_v3  # noqa: E402
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt

RU = "/tenerife/ru"   # RU сайт живёт под /tenerife/ru/; файлы — app/tenerife_site/ru/
PAGES = {name: (RU + "/" if name == "index" else f"{RU}/{name}/") for _f, name in build_v3.PAGES}


def page(name):
    return (SITE / f"{name}.html").read_text(encoding="utf-8")


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        self.tenerife = sys.modules["tenerife"]
        self.nl = mock.patch.object(self.tenerife, "notify_lead").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def lead(self, headers=None, remote="10.9.9.9", json_body=True, **kw):
        d = {"name": "Анна", "contact": "anna@example.de", "language": "ru", "consent": True,
             "page": f"{RU}/proceso/", "website": "", **kw}
        env = {"REMOTE_ADDR": remote}
        if json_body:
            return self.client.post("/api/tenerife/waitlist", json=d, headers=headers or {}, environ_base=env)
        d = {k: ("1" if v is True else v) for k, v in d.items() if v is not False}
        return self.client.post("/api/tenerife/waitlist", data=d, headers=headers or {}, environ_base=env)

    def rows(self):
        if not os.path.exists(self.mod.DB):
            return []
        c = sqlite3.connect(self.mod.DB)
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='tenerife_waitlist'").fetchone():
            c.close()
            return []
        c.row_factory = sqlite3.Row
        out = [dict(r) for r in c.execute("SELECT * FROM tenerife_waitlist ORDER BY id")]
        c.close()
        return out

    def key(self, headers=None, remote="10.9.9.9"):
        with self.mod.app.test_request_context("/", headers=headers or {}, environ_base={"REMOTE_ADDR": remote}):
            return self.tenerife._client_hash()


# ---------------------------------------------------------------- T3-04
class ClientKeyTest(AppCase):
    """Rate-limit key = X-Real-IP (set by nginx from the Cloudflare-verified $remote_addr), else remote_addr.
    Client-supplied CF-Connecting-IP and X-Forwarded-For are ignored, separately and together. No ProxyFix."""
    SPOOF = [{"CF-Connecting-IP": "6.6.6.6"}, {"X-Forwarded-For": "6.6.6.6"},
             {"X-Forwarded-For": "6.6.6.6, 7.7.7.7"},
             {"CF-Connecting-IP": "6.6.6.6", "X-Forwarded-For": "7.7.7.7"}]

    def test_key_is_x_real_ip(self):
        base = self.key({"X-Real-IP": "203.0.113.5"})
        self.assertEqual(base, self.key({"X-Real-IP": "203.0.113.5"}, remote="10.0.0.1"))
        self.assertNotEqual(base, self.key({"X-Real-IP": "203.0.113.6"}))
        with self.mod.app.test_request_context("/", headers={"X-Real-IP": " 203.0.113.5 "}):
            self.assertEqual(self.tenerife._client_ip(), "203.0.113.5")

    def test_spoofed_cf_and_xff_do_not_change_the_key(self):
        for real in ({"X-Real-IP": "203.0.113.5"}, {}):
            ref = self.key(real)
            for spoof in self.SPOOF:
                self.assertEqual(self.key({**real, **spoof}), ref, (real, spoof))

    def test_fallback_to_remote_addr(self):
        ref = self.key(remote="198.51.100.7")
        self.assertEqual(ref, self.key({"X-Real-IP": "198.51.100.7"}, remote="10.0.0.1"))
        for bad in ("", "not-an-ip", "1.2.3.4, 5.6.7.8", "999.1.1.1"):
            self.assertEqual(self.key({"X-Real-IP": bad}, remote="198.51.100.7"), ref, bad)
            with self.mod.app.test_request_context("/", headers={"X-Real-IP": bad},
                                                   environ_base={"REMOTE_ADDR": "198.51.100.7"}):
                self.assertEqual(self.tenerife._client_ip(), "198.51.100.7", bad)
        for spoof in self.SPOOF:
            self.assertEqual(self.key(spoof, remote="198.51.100.7"), ref, spoof)

    def test_rate_limit_cannot_be_dodged_with_xff_or_cf(self):
        for i, spoof in enumerate(self.SPOOF[:3]):
            r = self.lead({"X-Real-IP": "203.0.113.5", **spoof}, contact=f"a{i}@example.de")
            self.assertEqual(r.status_code, 200, spoof)
        r = self.lead({"X-Real-IP": "203.0.113.5", **self.SPOOF[3]})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.lead({"X-Real-IP": "203.0.113.9"}).status_code, 200)

    def test_rate_limit_without_x_real_ip_uses_remote_addr(self):
        codes = [self.lead(spoof, remote="198.51.100.7").status_code for spoof in self.SPOOF]
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(self.lead(remote="198.51.100.8").status_code, 200)

    def test_no_proxyfix_and_no_xff_in_code(self):
        src = (ROOT / "app" / "tenerife.py").read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        code = re.sub(r'"""(.*?)"""', "", code, flags=re.S)
        self.assertNotIn("X-Forwarded-For", code)
        self.assertNotIn("CF-Connecting-IP", code)
        self.assertNotIn("access_route", code)
        for f in (ROOT / "app").glob("*.py"):
            self.assertIsNone(re.search(r"import\s+ProxyFix|ProxyFix\(", f.read_text(encoding="utf-8")), f.name)


# ---------------------------------------------------------------- T3-03 (e2e payload of the built form)
class FormPayloadTest(AppCase):
    def form_payload(self, name):
        """Exactly what waitlist.js sends: name, contact, language, consent, website, page + every calc_* field."""
        form = re.search(r'<form[^>]*id="wl-form".*?</form>', page(name), re.S).group(0)
        d = {"name": "Анна", "contact": "anna@example.de", "language": "ru", "consent": True, "website": ""}
        for tag in re.findall(r"<input[^>]+>", form):
            n = re.search(r'name="([^"]+)"', tag)
            v = re.search(r'value="([^"]*)"', tag)
            if n and (n.group(1) == "page" or n.group(1).startswith("calc_")):
                d[n.group(1)] = htmllib.unescape(v.group(1) if v else "")
        return d

    def test_calculadora_form_stores_calc_columns(self):
        d = self.form_payload("calculadora")
        self.assertEqual(sorted(k for k in d if k.startswith("calc_")), ["calc_m2", "calc_pay", "calc_step"])
        self.assertEqual(d["page"], f"{RU}/calculadora/")
        r = self.client.post("/api/tenerife/waitlist", json=d, headers={"X-Real-IP": "203.0.113.5"})
        self.assertEqual(r.get_json(), {"ok": True})
        row = self.rows()[0]
        model = json.loads((ROOT / "app/static/tenerife/site/model.json").read_text(encoding="utf-8"))
        self.assertEqual((row["calc_status"], row["calc_m2"], row["calc_step"], row["calc_pay"]),
                         ("ok", 52, "queue", "m6"))
        self.assertEqual((row["calc_amount"], row["calc_month_eur"], row["calc_model_version"]),
                         (153400, 24288, model["version"]))
        self.assertEqual(self.nl.call_args.kwargs["calc"]["calc_amount"], 153400)  # mocked: nothing sent

    def test_other_pages_send_page_only(self):
        for name in PAGES:
            d = self.form_payload(name)
            self.assertEqual(d["page"], PAGES[name], name)
            if name != "calculadora":
                self.assertFalse([k for k in d if k.startswith("calc_")], name)


# ---------------------------------------------------------------- T3-05 / T3-10
class NoJsAnswerTest(AppCase):
    def test_success_redirects_to_gracias(self):
        r = self.lead(json_body=False, page=f"{RU}/faq/")
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["Location"].endswith("/tenerife/gracias/?back=%2Ftenerife%2Fru%2Ffaq%2F"))
        g = self.client.get("/tenerife/gracias/?back=%2Ftenerife%2Fru%2Ffaq%2F")
        body = g.get_data(as_text=True)
        self.assertEqual(g.status_code, 200)
        self.assertIn("noindex", g.headers.get("X-Robots-Tag", "") + body)
        self.assertIn("Спасибо! Вы в очереди.", body)
        self.assertIn(f'<a href="{RU}/faq/">← К сайту проекта</a>', body)
        self.assertIn('<link rel="stylesheet" href="/static/tenerife/site/site.css">', body)
        self.assertNotIn("{{NOTICE_", body)

    def test_gracias_back_is_sanitized(self):
        for bad in ("//evil.example/x", "https://evil.example/", "javascript:alert(1)", "/admin/leads", ""):
            body = self.client.get("/tenerife/gracias/?" + urllib.parse.urlencode({"back": bad})).get_data(as_text=True)
            self.assertNotIn("evil", body, bad)
            self.assertNotIn("javascript:", body, bad)
            self.assertIn('<a href="/tenerife/">', body, bad)

    def test_error_page_v2_shell_status_and_back_to_form(self):
        r = self.lead(json_body=False, consent=False, page=f"{RU}/proceso/")
        body = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Отметьте согласие на обработку данных.", body)
        self.assertIn(f'<a href="{RU}/proceso/#ochered">← Назад к форме</a>', body)
        self.assertNotIn('<p class="hero__lead"></p>', body)
        self.assertIn('class="header', body)
        self.assertIn("noindex", r.headers.get("X-Robots-Tag", "") + body)
        self.assertEqual(self.rows(), [])

    def test_error_text_is_escaped(self):
        with mock.patch.object(self.tenerife, "_safe_back", return_value='/tenerife/"><b>x'):
            body = self.lead(json_body=False, name="").get_data(as_text=True)
        self.assertNotIn('"><b>x', body)
        self.assertIn("&quot;&gt;&lt;b&gt;x", body)

    def test_honeypot_and_missing_page(self):
        r = self.lead(json_body=False, website="http://spam.example")
        self.assertEqual((r.status_code, r.headers["Location"].rstrip("/").endswith("/tenerife")), (303, True))
        self.assertEqual(self.rows(), [])
        r = self.client.post("/api/tenerife/waitlist", data={"name": "A", "contact": "a@b.example", "language": "ru",
                                                              "consent": "1"})
        self.assertTrue(r.headers["Location"].endswith("/tenerife/gracias/?back=%2Ftenerife%2F"))

    def test_json_errors_name_the_field(self):
        cases = {"name": {"name": ""}, "contact": {"contact": "ab"}, "language": {"language": "xx"},
                 "consent": {"consent": False}}
        for field, kw in cases.items():
            r = self.lead(**kw)
            self.assertEqual((r.status_code, r.get_json()["field"]), (400, field), field)

    def test_form_fields_have_error_slots(self):
        for name in PAGES:
            form = re.search(r'<form[^>]*id="wl-form".*?</form>', page(name), re.S).group(0)
            for fid in ("wl-name", "wl-contact", "wl-lang", "wl-consent"):
                ctl = re.search(r'<(?:input|select)[^>]*id="%s"[^>]*>' % fid, form).group(0)
                self.assertIn(f'aria-describedby="{fid}-err"', ctl.replace(f" {fid}-err", f"{fid}-err")
                              if "aria-describedby" not in ctl else ctl, (name, fid))
                self.assertIn(f'id="{fid}-err"', form, (name, fid))


# ---------------------------------------------------------------- T3-06 (static; behaviour: pw_v3_ui.py)
class MenuScriptTest(unittest.TestCase):
    def test_focus_trap_inert_escape(self):
        js = (ROOT / "app/static/tenerife/site/site.js").read_text(encoding="utf-8")
        for s in ("inert", "Escape", "Tab", "focus()", "aria-expanded"):
            self.assertIn(s, js, s)

    def test_design_v3_delta(self):
        """Canary Stone v3 (designer, QA_BRIEF.md D12–D17 + notes), ported as is."""
        js = (ROOT / "app/static/tenerife/site/site.js").read_text(encoding="utf-8")
        # «Ещё»: Esc closes the open <details> and returns focus to its summary
        self.assertIn("var d=document.querySelector('.nav details[open]'); if(!d) return;", js)
        self.assertIn("d.open=false; var sm=d.querySelector('summary'); if(sm) sm.focus();", js)
        self.assertNotIn("PENDING", js)
        css = (ROOT / "app/static/tenerife/site/site.css").read_text(encoding="utf-8")
        # D15: inline text links, 12 px hit padding cancelled by negative inline margin; the provisional rule is gone
        self.assertIn(":where(p:not(.f-docs),dd,td,figcaption,.check>span,li:not(:is(nav,footer,.sheet) li))"
                      ">a:not([class])"
                      "{position:relative;"
                      "padding:var(--inline-hit-pad);margin-inline:calc(-1*var(--inline-hit-pad));"
                      "outline-offset:calc(var(--focus-offset) - var(--inline-hit-pad))}", css)
        self.assertIn("--inline-hit-pad: 12px;", css)
        self.assertNotIn("--inline-hit:", css)
        # D17: scrim = plate under the H1 only, lead below the picture; fade 2rem (header only)
        self.assertIn("--scrim-fade: 2rem;", css)
        self.assertIn("--hero-plate-pad: var(--space-6);", css)
        self.assertIn(".hero__body h1{grid-column:1/span 7;margin-inline:calc(-1*var(--hero-plate-pad));"
                      "padding:var(--hero-plate-pad-block) var(--hero-plate-pad);background:var(--cs-scrim);"
                      "color:var(--cs-on-dark)}", css)
        self.assertNotIn("transparent 100%)}\n  .hero__body h1", css)
        for name in PAGES:
            html = page(name)
            if 'class="hero__body"' in html:
                body = html.split('class="hero__body"', 1)[1].split("</section>", 1)[0]
                self.assertNotIn("hero__lead", body.split('class="hero__after"', 1)[0], name)
        # D13 figures, ladder cap
        self.assertIn("container-type:inline-size", css)
        self.assertIn("--fig-cap-tablet: 7cqi;", css)
        self.assertIn("--fig-cap-desktop: 6.5cqi;", css)
        self.assertIn(".figures li:nth-child(3){grid-column:6/10}.figures li:nth-child(4),.figures li:nth-child(5)"
                      "{grid-column:10/13;", css)
        self.assertIn("--ladder-name-cap: 2.2cqi;", css)
        self.assertIn(".ladder__name{font-size:min(var(--fs-h3),var(--ladder-name-cap))}", css)
        # D14 fonts: 12 @font-face, Canary symbol subsets, no modified files under the original names
        self.assertEqual(css.count("@font-face"), 12)
        fonts = ROOT / "app/static/tenerife/site/fonts"
        for f in ("canary-serif-symbols-500.woff2", "canary-sans-symbols-400.woff2", "canary-sans-symbols-600.woff2",
                  "OFL-CanarySerif.txt", "OFL-CanarySans.txt"):
            self.assertTrue((fonts / f).is_file(), f)
        for f in ("literata-symbols-500.woff2", "source-sans-3-symbols-400.woff2", "source-sans-3-symbols-600.woff2"):
            self.assertFalse((fonts / f).exists(), f)
            self.assertNotIn(f, css)
        self.assertIn('--font-display: "Literata", "Canary Serif", "Georgia", "Times New Roman", serif;', css)
        self.assertIn('--font-text:    "Source Sans 3", "Canary Sans", "Segoe UI", "Helvetica Neue", Arial, '
                      'sans-serif;', css)
        # design v3.1 (designer delta, QA_BRIEF 1f16f6cb…): tokens + rules ported verbatim
        for tok in ("--hero-plate-pad-block: var(--space-4);", "--fs-h1-short: clamp(2rem, 4.2cqi, 3.5rem);",
                    "--h1-short-measure: 21ch;", "--hero-short-h: clamp(22rem, 62vh, 36rem);",
                    "--hero-short-overhang: 6rem;", "--legal-h1-cap: 8.6cqi;"):
            self.assertIn(tok, css)
        self.assertIn(":where(p:not(.f-docs),dd,td,figcaption,.check>span,li:not(:is(nav,footer,.sheet) li))"
                      ">a:not([class]){position:relative;", css)
        self.assertIn("padding:var(--hero-plate-pad-block) var(--hero-plate-pad);background:var(--cs-scrim)", css)
        self.assertIn(".hero--short{container-type:inline-size}\n.hero--short .hero__media{aspect-ratio:3/2}", css)
        self.assertIn("font-size:var(--fs-h1-short);", css)
        self.assertIn(".hero--short{grid-template-rows:auto var(--hero-short-overhang) auto}", css)
        self.assertIn(".hero--short .hero__media{grid-area:1/1;aspect-ratio:auto;min-height:var(--hero-short-h)}", css)
        self.assertIn("max-width:calc(var(--h1-short-measure) + 2*var(--hero-plate-pad));", css)
        self.assertIn("background:var(--cs-basalt);color:var(--cs-on-dark)}", css)
        self.assertIn(".legal h1{font-size:min(var(--fs-display),var(--legal-h1-cap));hyphens:manual;"
                      "overflow-wrap:normal}", css)
        self.assertIn("@media (min-width:1024px){.wl .wl__text{grid-column:1/span 5}"
                      ".wl .wl__form{grid-column:7/span 6}}", css)
        for gone in ("--fs-h1)", "(16ch +", "min(60vh,var(--hero-min-h))", ".legal li>a"):
            self.assertNotIn(gone, css)
        faq = (ROOT / "app/tenerife_site/faq.html").read_text(encoding="utf-8")
        self.assertIn('<h1 id="h1" class="hero__h1--short">', faq)
        # removed tokens: none may remain anywhere in the v3 site
        src = css + js + "".join(p.read_text(encoding="utf-8")
                                 for p in (ROOT / "app/templates/tenerife/site").glob("*.html"))
        for tok in ("--space-9", "--space-10", "--radius-0", "--radius-2", "--shadow-none"):
            self.assertIsNone(re.search(re.escape(tok) + r"(?![\w-])", src), tok)

# ---------------------------------------------------------------- T3-07 / T3-11
class ComponentsTest(unittest.TestCase):
    def test_steps_log_people_mini_ladder_short_calc(self):
        self.assertIn('<ol class="ladder ladder--mini"', page("index"))
        for name in ("construccion", "mercado"):
            self.assertIn('<ol class="ladder ladder--mini"', page(name), name)
        # C10 hidden (designer 20:23): copy_v3 has no confirmed log entries; the copy stays as an ordinary table,
        # no log markup and no anchor to it anywhere
        heads = {"index": '<th scope="col">Когда, по плану</th>',
                 "construccion": '<th scope="col">Дата, по плану</th>'}
        for name, th in heads.items():
            self.assertIn(th, page(name), name)
        for f in SITE.glob("*.html"):
            html = f.read_text(encoding="utf-8")
            self.assertNotIn('class="log', html, f.name)
            self.assertNotIn('href="#log', html, f.name)
        # C11 OFF (designer r3 item 4): no documented who/when for the roles -> whole section not rendered
        self.assertEqual(build_v3.TEAM_SECTIONS, set())
        self.assertIn(("index", "Команда и компания"), build_v3.HIDDEN_SECTIONS)
        for name in PAGES:
            self.assertNotIn('class="people', page(name), name)
        self.assertNotIn("Команда и компания", page("index"))
        self.assertIsNone(re.search(r"<section[^>]*>\s*</section>", page("index")))
        for href in (f"{RU}/simon/", f"{RU}/boris/"):
            self.assertIn(f'<li><a href="{href}">', page("index"))
        a = page("acciones")
        self.assertIn('class="wrap grid calc calc--short" id="calc"', a)
        self.assertIn('<script type="application/json" id="cs-model">', a)
        self.assertIn('<script src="/static/tenerife/site/calc.js"', a)
        self.assertNotIn("Сумма", re.sub(r"<script.*?</script>", "", a, flags=re.S))
        self.assertIn('<ol class="grid steps">', page("proceso"))  # 09: numbered paragraphs
        # Kimi r18: the «Порядок входа» / «Как устроен вход» paragraphs of 02 04 05 06 09 12 now have 7 sentences;
        # C7 is 3–6 steps (DESIGN.md), so they stay one paragraph (text as in the copy, not split)
        for name in ("norte", "calculadora", "alquiler", "mercado"):
            self.assertNotIn('<ol class="grid steps">', page(name), name)
            self.assertIn("Денег до выбора участка не берём", page(name), name)

    def test_f14_f16_no_interim_photo(self):
        """Updated 2026-11-02: F14–F16 may only show the generated Canary Stone construction frames,
        never one of the interim project photos that predate the style lock."""
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        allowed = {"build-pit-3ab7c2", "build-frame-5e6d77", "roof-montazh-6d90ef", "solar-flat-2b8f04"}
        for name, rep in report.items():
            for f in ("F14", "F15", "F16"):
                stem = rep.get("frames", {}).get(f)
                if stem is not None:
                    self.assertIn(stem, allowed, (name, f, stem))


# ---------------------------------------------------------------- T3-08
class JsonLdTest(unittest.TestCase):
    def lds(self, name):
        return [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                                   page(name), re.S)]

    def test_organization_on_index(self):
        (org,) = self.lds("index")
        self.assertEqual((org["@type"], org["legalName"]), ("Organization", "OXFORD FRAME REAL ASSETS LTD"))
        self.assertIn("09153936", json.dumps(org))
        self.assertEqual(org["address"]["postalCode"], "RG25 2EE")
        self.assertNotIn("telephone", org)
        self.assertNotIn("email", org)

    def test_breadcrumbs_elsewhere(self):
        for name, url in PAGES.items():
            if name == "index":
                continue
            bc = [x for x in self.lds(name) if x["@type"] == "BreadcrumbList"]
            self.assertEqual(len(bc), 1, name)
            items = bc[0]["itemListElement"]
            self.assertEqual(items[0]["item"], "https://artemisresort.com" + RU + "/", name)
            self.assertEqual(items[-1]["item"], "https://artemisresort.com" + url, name)
            self.assertEqual([i["position"] for i in items], list(range(1, len(items) + 1)), name)


# ---------------------------------------------------------------- T3-09
class LegalPagesTest(AppCase):
    def test_v2_layout_and_text_verbatim(self):
        for name in ("impressum", "privacy"):
            body = self.client.get(f"{RU}/{name}/").get_data(as_text=True)
            # текст правовой страницы дословный; внутренние ссылки получают префикс языка (/tenerife/ru/…)
            self.assertIn(build_v3.prefix_internal_links(build_v3.legal_body(name), "ru"), body, name)
            self.assertIn('class="header', body)
            self.assertIn('<footer', body)
            self.assertNotIn("cloudflareinsights", body)
            self.assertEqual(body, self.tenerife._finish(page(name)))  # r4: runtime slots (WhatsApp, robots)

    def test_legal_meta_description_from_copy(self):
        """r3: meta description of impressum / privacy = the PRIMARY variant of copy_v3/meta_legal.md, verbatim
        (read from the file; fallback variants ignored); exactly one per page, served as built."""
        md = (BUILD / "copy_v3/meta_legal.md").read_text(encoding="utf-8")
        for name in ("impressum", "privacy"):
            sec = re.search(rf"^## /tenerife/{name}/.*?(?=^## |\Z)", md, re.S | re.M).group(0)
            n, want = re.search(r"^\*\*Основной \((\d+) симв\.\):\*\*\n(.+)$", sec, re.M).groups()
            self.assertEqual(len(want), int(n), name)
            self.assertTrue(120 <= len(want) <= 155, name)
            body = self.client.get(f"/tenerife/{name}/").get_data(as_text=True)
            for html_ in (body, page(name)):
                got = re.findall(r'<meta name="description" content="([^"]*)">', html_)
                self.assertEqual([htmllib.unescape(g) for g in got], [want], name)
            self.assertEqual(build_v3.legal_meta(name), want)
        self.assertNotIn('name="description"', page("_notice"))

    def test_app_csp_has_no_cloudflareinsights(self):
        """QA R12 item 3 / D-04: CSP for /tenerife/ is set by nginx (deploy/nginx-artemis-security-map.conf:11-13,
        Sysadmin's file); the app must not add a CSP that allows the analytics beacon."""
        for u in ("/tenerife/", "/tenerife/privacy/", "/tenerife/impressum/", "/tenerife/calculadora/",
                  "/tenerife-preview/", "/static/tenerife/site/site.js"):
            r = self.client.get(u)
            for h in ("Content-Security-Policy", "Content-Security-Policy-Report-Only"):
                self.assertNotIn("cloudflareinsights", r.headers.get(h, ""), (u, h))


class KimiTextsTest(unittest.TestCase):
    """T3-09 texts by Kimi (31.10.2026): copy_v3 15/16 word for word, «очередь» instead of «лист ожидания»,
    consent wording, no analytics beacon (no consent mechanism for analytics, no beacon token)."""

    @staticmethod
    def words(t):
        t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", htmllib.unescape(t))
        t = re.sub(r"\s+", " ", re.sub(r"(?m)^(#+|-) |\*\*", " ", t)).strip()
        return re.sub(r"\( ", "(", re.sub(r" ([.,)])", r"\1", t))  # spaces left by removed inline tags

    def test_copy_hash(self):
        self.assertEqual(build_v3.COPY_SHA256_DEFAULT,
                         "e50088725a11bca90d3c62fe50ef2489963615599fb4cfda12cf05e1867acedb")
        self.assertEqual(build_v3.combined_sha(), build_v3.COPY_SHA256)

    def test_copy_hash_is_configurable(self):
        with mock.patch.dict(os.environ, {"TENERIFE_COPY_SHA256": " " + "AB" * 32 + " "}):
            m = importlib.reload(build_v3)
            self.assertEqual(m.COPY_SHA256, "ab" * 32)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TENERIFE_COPY_SHA256", None)
            m = importlib.reload(build_v3)
            self.assertEqual(m.COPY_SHA256, m.COPY_SHA256_DEFAULT)

    def test_legal_templates_are_copy_verbatim(self):
        sys.path.insert(0, str(BUILD))
        import legal_from_copy
        for name, md in legal_from_copy.FILES.items():
            tpl = (ROOT / "app/templates/tenerife" / f"{name}.html").read_text(encoding="utf-8")
            self.assertEqual(tpl, legal_from_copy.template(name), name)
            src = re.sub(r"<!--.*?-->", "", (BUILD / "copy_v3" / md).read_text(encoding="utf-8"), flags=re.S)
            self.assertIn(self.words(src), self.words(page(name)), name)

    def test_no_waiting_list_wording(self):
        files = [*SITE.glob("*.html"), *(ROOT / "app/templates/tenerife").rglob("*.html"),
                 ROOT / "app/static/tenerife/site/waitlist.js", ROOT / "app/tenerife.py"]
        for f in files:
            self.assertIsNone(re.search(r"[Лл]ист\w* ожидани", f.read_text(encoding="utf-8")), f.name)

    def test_consent_wording_and_link(self):
        """QA R12 item 5: the consent line on all 13 pages == copy_v3/17_forma.md line 7 (read from the copy file,
        so a later copy change fails here until the pages are rebuilt)."""
        line7 = (BUILD / "copy_v3/17_forma.md").read_text(encoding="utf-8").splitlines()[6]
        m = re.fullmatch(r"\*\*Согласие\.\*\* (.+)", line7)
        self.assertIsNotNone(m, line7)
        md = m.group(1)
        self.assertNotIn("*", md)
        links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", md)
        self.assertEqual(links, [("политике конфиденциальности", "/tenerife/privacy/")])
        want = "<span>" + re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', md) + "</span>"
        self.assertEqual(len(PAGES), 13)
        # на RU-страницах ссылка на политику ведёт в RU-версию (/tenerife/ru/privacy/)
        want_ru = want.replace('href="/tenerife/privacy/"', f'href="{RU}/privacy/"')
        for name in PAGES:
            html = page(name)
            self.assertEqual(html.count('id="wl-consent"'), 1, name)
            self.assertEqual(re.findall(r'id="wl-consent"[^>]*>(<span>.*?</span>)</label>', html), [want_ru], name)
        for f in ("app/templates/tenerife/preview.html", "scripts/tenerife_site_build/_waitlist.html"):
            self.assertIn(want, (ROOT / f).read_text(encoding="utf-8"), f)

    def test_no_web_analytics_wording(self):
        """QA R12-03: no Tenerife page claims analytics / visit statistics (privacy r12: analytics not used)."""
        rx = re.compile(r"Web\s+Analytics|статистик\w*\s+посещени", re.I)
        files = [*SITE.glob("*.html"), *(ROOT / "app/templates/tenerife").rglob("*.html"),
                 *(BUILD / "copy_v3").glob("1[5-7]_*.md")]
        for f in files:
            self.assertIsNone(rx.search(f.read_text(encoding="utf-8")), f.name)
        for u in ("/tenerife/privacy/", "/tenerife/impressum/", "/tenerife-preview/privacy/"):
            import app as artemis_app
            body = artemis_app.app.test_client().get(u).get_data(as_text=True)
            self.assertIsNone(rx.search(body), u)

    def test_no_analytics_beacon_anywhere(self):
        for f in [*SITE.glob("*.html"), *(ROOT / "app/templates/tenerife").rglob("*.html"),
                  *(ROOT / "app/static/tenerife/site").glob("*.js")]:
            t = f.read_text(encoding="utf-8")
            self.assertNotIn("cloudflareinsights", t, f.name)
            self.assertNotIn("data-cf-beacon", t, f.name)


class LinkColourTest(unittest.TestCase):
    """Designer r3 item 2: link text = --cs-bronze-deep #6F5335 (AA on lime/sand); --cs-bronze #8A6A45 never
    colours link text (only lines, markers, underline colour and large numerals). Computed colour + axe: Playwright."""
    CSS = ROOT / "app/static/tenerife/site/site.css"

    @staticmethod
    def contrast(a, b):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def rules(self):
        css = re.sub(r"/\*.*?\*/", "", self.CSS.read_text(encoding="utf-8"), flags=re.S)
        return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]

    def test_tokens_and_contrast(self):
        css = self.CSS.read_text(encoding="utf-8")
        tok = dict(re.findall(r"(--cs-[\w-]+):\s*(#[0-9A-Fa-f]{6})", css))
        self.assertEqual(tok["--cs-bronze-deep"].upper(), "#6F5335")
        self.assertEqual(tok["--cs-bronze"].upper(), "#8A6A45")
        self.assertEqual(tok["--cs-lime"].upper(), "#F4F1EA")
        self.assertAlmostEqual(self.contrast("#6F5335", "#F4F1EA"), 6.28, delta=0.02)
        self.assertGreaterEqual(self.contrast("#6F5335", tok["--cs-sand"]), 4.5)
        self.assertLess(self.contrast("#8A6A45", "#F4F1EA"), 4.5)     # why bronze is not for small text

    def test_links_use_bronze_deep_never_bronze(self):
        link_sel = re.compile(r"(^|[\s,>+~(])a($|[\s,:\[.>)])")
        base = [b for sel, b in self.rules() if sel == "a"]
        self.assertEqual(len(base), 1)
        self.assertRegex(base[0], r"(^|;)color:var\(--cs-bronze-deep\)")
        bronze = re.compile(r"(?<![-\w])color:\s*(var\(--cs-bronze\)|#8a6a45)", re.I)
        users = []
        for sel, body in self.rules():
            if bronze.search(body):
                users.append(sel)
                self.assertIsNone(link_sel.search(sel), f"bronze link text: {sel}")
        self.assertEqual(users, [".steps__n"])        # 1/2/3 numerals at --fs-h2 (large text), not links
        for name in PAGES:
            for m in re.finditer(r'<span class="steps__n"[^>]*>(.*?)</span>', page(name), re.S):
                self.assertNotIn("<a", m.group(1), name)


class NoCookiesNoStorageTest(AppCase):
    """Privacy §7 (final copy 31.10.2026): the site's own code writes no cookies and no localStorage. Every Tenerife
    response comes without Set-Cookie (the Crete routes set a `lang` cookie: app.py _render_site/_render_legal)."""

    def test_no_set_cookie_on_tenerife_responses(self):
        urls = ["/tenerife", "/tenerife/", "/tenerife/impressum/", "/tenerife/privacy/", "/tenerife/impressum",
                "/tenerife/privacy", "/tenerife/gracias/?back=%2Ftenerife%2F", "/tenerife/no-such-page/",
                "/tenerife-preview", "/tenerife-preview/", "/tenerife-preview/impressum/", "/tenerife-preview/privacy/",
                "/static/tenerife/site/site.css", "/api/tenerife/waitlist"]
        for name in PAGES:
            if name != "index":
                urls += [f"/tenerife/{name}/", f"/tenerife/{name}", f"/tenerife/{name}.html"]
        urls += [f"/static/tenerife/site/{f.name}" for f in (ROOT / "app/static/tenerife/site").glob("*.js")]
        for u in urls:
            r = self.client.get(u)
            self.assertIsNone(r.headers.get("Set-Cookie"), f"{u} {r.status_code}")
        posts = [self.lead(),                                          # json ok
                 self.lead(json_body=False, remote="10.9.9.8"),        # form -> 303 gracias
                 self.lead(name="", remote="10.9.9.7"),                # 400
                 self.lead(website="x", remote="10.9.9.6")]            # honeypot
        posts += [self.lead(remote="10.9.9.5") for _ in range(4)]     # up to 429
        self.assertEqual(posts[-1].status_code, 429)
        for r in posts:
            self.assertIsNone(r.headers.get("Set-Cookie"), r.status_code)
        crete = self.client.get("/ru/")                                # control: the Crete route does set it
        self.assertIn("lang=", crete.headers.get("Set-Cookie", ""))

    def test_tenerife_js_uses_no_cookies_or_storage(self):
        rx = re.compile(r"localStorage|sessionStorage|document\.cookie|indexedDB|cookieStore")
        for f in (ROOT / "app/static/tenerife/site").glob("*.js"):
            self.assertIsNone(rx.search(f.read_text(encoding="utf-8")), f.name)
        inline = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
        for f in [*SITE.glob("*.html"), *(ROOT / "app/templates/tenerife").rglob("*.html")]:
            for js in inline.findall(f.read_text(encoding="utf-8")):
                self.assertIsNone(rx.search(js), f.name)


# ---------------------------------------------------------------- T3-12
class NumbersTest(unittest.TestCase):
    def test_make_numbers_regenerates_numbers_md(self):
        src = BUILD / "copy_v3"
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "copy_v3"
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            (dst / "numbers.md").unlink()
            shutil.copy(BUILD / "model_inputs.json", dst.parent / "model_inputs.json")  # 02.11: единый источник цифр
            r = subprocess.run([sys.executable, str(dst / "make_numbers.py")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("ERR", r.stdout)
            self.assertEqual(hashlib.sha256((dst / "numbers.md").read_bytes()).hexdigest(),
                             hashlib.sha256((src / "numbers.md").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
