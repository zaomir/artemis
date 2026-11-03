"""r4: WhatsApp contact from TENERIFE_WHATSAPP, noindex switch TENERIFE_INDEXING, form texts from copy_v3/17_forma.md.
No real number here: the fake +440000000000 only. Telegram is mocked, the DB is a temp file."""
import html as htmllib
import importlib
import logging
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import PIL
except ImportError:
    PIL = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "tenerife_site_build"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt

import build_v3  # noqa: E402

SITE = ROOT / "app" / "tenerife_site" / "ru"
BUILD = ROOT / "scripts" / "tenerife_site_build"
FAKE = "+440000000000"
SLOT = '<li data-tenerife-whatsapp hidden></li>'
ROBOTS = '<meta name="robots" content="noindex, nofollow">'
URLS = ([("/tenerife/" if n == "index" else f"/tenerife/{n}/") for _f, n in build_v3.PAGES]
        + ["/tenerife/impressum/", "/tenerife/privacy/", "/tenerife/gracias/"])
KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID", "TENERIFE_WHATSAPP", "TENERIFE_INDEXING")


class R4Case(unittest.TestCase):
    env = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        clean = {k: v for k, v in os.environ.items() if k not in KEYS}
        p = mock.patch.dict(os.environ, {**clean, **self.env}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        self.tenerife = sys.modules["tenerife"]
        self.tenerife._warned.clear()
        n = mock.patch.object(self.tenerife, "notify_lead")
        n.start()
        self.addCleanup(n.stop)

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.get_data(as_text=True)

    def footer(self, body):
        return re.search(r"<footer.*?</footer>", body, re.S).group(0)


class WhatsAppSetTest(R4Case):
    env = {"TENERIFE_WHATSAPP": FAKE}

    def test_every_page_has_one_whatsapp_link(self):
        for url in URLS:
            body = self.get(url)
            foot = self.footer(body)
            links = re.findall(r'<a href="https://wa\.me/[^"]*"[^>]*>[^<]*</a>', body)
            self.assertEqual(len(links), 1, url)
            self.assertIn('<li class="f-wa">WhatsApp: <a href="https://wa.me/440000000000" '
                          'aria-label="WhatsApp: +44 0000 000000">+44&nbsp;0000&nbsp;000000</a></li>', foot, url)
            self.assertNotIn(SLOT, body, url)
            self.assertNotIn("data-tenerife-whatsapp", body, url)
            self.assertNotIn("+34 674", body, url)
            self.assertNotIn("Телефон", foot, url)

    def test_accessible_name_contains_the_visible_text(self):  # WCAG 2.5.3 label in name
        foot = self.footer(self.get("/tenerife/"))
        a = re.search(r'<a href="https://wa\.me/\d+" aria-label="([^"]+)">([^<]+)</a>', foot)
        self.assertTrue(a.group(1).startswith("WhatsApp: "))
        self.assertIn(htmllib.unescape(a.group(2)).replace("\u00a0", " "), a.group(1))

    def test_no_jsonld_telephone(self):
        self.assertNotIn('"telephone"', self.get("/tenerife/"))

    def test_display_format(self):
        self.assertEqual(self.tenerife.whatsapp_display("+440000000001"), "+44 0000 000001")
        self.assertEqual(self.tenerife.whatsapp_display("+10000000000"), "+10000000000")


class WhatsAppMissingTest(R4Case):
    env = {}

    def test_hidden_never_a_placeholder_and_warned_without_value(self):
        for raw in ("", "440000000000", "+44 0000 000000", "+0440000000", "+44abc", "+4412"):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"TENERIFE_WHATSAPP": raw}):
                self.tenerife._warned.clear()
                with self.assertLogs("artemis.tenerife", logging.WARNING) as cm:
                    body = self.get("/tenerife/faq/")
                foot = self.footer(body)
                self.assertNotIn("wa.me", body)
                self.assertNotIn("data-tenerife-whatsapp", body)
                self.assertNotIn("+34 674", body)
                self.assertIn('href="mailto:info@artemisresort.com"', foot)
                self.assertEqual(foot.count("<li"), foot.count("</li>"))
                if raw:
                    self.assertNotIn(raw, "\n".join(cm.output))
                    self.assertNotIn("0000", "\n".join(cm.output))

    def test_notice_page_hidden_too(self):
        self.assertNotIn("data-tenerife-whatsapp", self.get("/tenerife/gracias/"))

    def test_built_files_carry_only_the_slot(self):
        for f in SITE.glob("*.html"):
            t = f.read_text(encoding="utf-8")
            self.assertEqual(t.count(SLOT), 1, f.name)
            self.assertNotIn("wa.me", t, f.name)


class IndexingDefaultTest(R4Case):
    env = {}

    def test_every_tenerife_page_noindex(self):
        for url in URLS:
            body = self.get(url)
            self.assertEqual(body.count(ROBOTS), 1, url)
            self.assertLess(body.index(ROBOTS), body.index("</head>"), url)

    def test_every_tenerife_page_x_robots_tag(self):
        """QA PS-03: unset TENERIFE_INDEXING -> header too, on all 13 pages + impressum/privacy (+ gracias)."""
        self.assertIn("/tenerife/impressum/", URLS)
        self.assertIn("/tenerife/privacy/", URLS)
        self.assertEqual(len(URLS), 16)
        for url in URLS:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow", url)

    def test_sitemap_without_tenerife(self):
        sm = self.get("/sitemap.xml")
        self.assertNotIn("/tenerife", sm)
        self.assertIn("<loc>https://artemisresort.com/en/</loc>", sm)

    def test_only_1_switches_indexing_on(self):
        for v in ("0", "true", "yes", " "):
            with mock.patch.dict(os.environ, {"TENERIFE_INDEXING": v}):
                self.assertIn(ROBOTS, self.get("/tenerife/norte/"), v)


class IndexingOnTest(R4Case):
    env = {"TENERIFE_INDEXING": "1"}

    def test_pages_indexable_and_in_sitemap(self):
        for url in URLS[:-1]:
            self.assertNotIn('name="robots"', self.get(url), url)
        for url in URLS[:-1]:
            self.assertNotIn("X-Robots-Tag", self.client.get(url).headers, url)
        self.assertIn(ROBOTS, self.get("/tenerife/gracias/"))  # the thank-you page is always noindex
        self.assertEqual(self.client.get("/tenerife/gracias/").headers.get("X-Robots-Tag"), "noindex, nofollow")
        sm = self.get("/sitemap.xml")
        for url in URLS[:-1]:
            self.assertIn(f"<loc>https://artemisresort.com{url}</loc>", sm)


class CreteUnaffectedTest(R4Case):
    def test_crete_same_in_both_states(self):
        got = {}
        for v in ("", "1"):
            with mock.patch.dict(os.environ, {"TENERIFE_INDEXING": v, "TENERIFE_WHATSAPP": FAKE}):
                got[v] = {u: self.client.get(u).get_data(as_text=True) for u in ("/en/", "/ru/", "/en/privacy/")}
        self.assertEqual(got[""], got["1"])
        for body in got[""].values():
            self.assertNotIn("noindex", body)
            self.assertNotIn("wa.me", body)


class FormTextsTest(unittest.TestCase):
    """Form strings only from copy_v3/17_forma.md (not from design/components.html, «лист ожидания»)."""

    def test_consent_is_the_copy_on_every_form(self):
        md = (BUILD / "copy_v3" / "17_forma.md").read_text(encoding="utf-8")
        want = re.search(r"^\*\*Согласие\.\*\* (.+)$", md, re.M).group(1)
        want = re.sub(r"\[([^\]]+)\]\((/[^)]+)\)", r'<a href="\2">\1</a>', want)
        # ссылка на политику внутри строки согласия ведёт в RU-версию той же страницы
        want = want.replace('href="/tenerife/privacy/"', 'href="/tenerife/ru/privacy/"')
        forms = 0
        for f in SITE.glob("*.html"):
            t = f.read_text(encoding="utf-8")
            for span in re.findall(r'<input type="checkbox" id="wl-consent"[^>]*><span>(.*?)</span></label>', t):
                forms += 1
                self.assertEqual(span, want, f.name)
        self.assertEqual(forms, len(build_v3.PAGES))

    def test_no_waitlist_wording_from_components(self):
        files = list(SITE.glob("*.html")) + [ROOT / "app/static/tenerife/site/waitlist.js", ROOT / "app/tenerife.py",
                                             ROOT / "app/templates/tenerife/site/_components.html"]
        for f in files:
            self.assertIsNone(re.search(r"(?i)лист\w* ожидания", f.read_text(encoding="utf-8")), f.name)


class FormMessagesTest(unittest.TestCase):
    """Kimi r4: every form message verbatim from 17_forma.md «Сообщения формы» — in the page (data-msg-*, read by
    waitlist.js) and in app/tenerife.py (server answers, no-JS pages)."""

    def setUp(self):
        self.msgs = build_v3.form_messages()
        import tenerife
        self.tenerife = tenerife

    def test_all_ten_messages_parsed(self):
        self.assertEqual(sorted(self.msgs), sorted(build_v3.FORM_MESSAGES.values()))
        self.assertEqual(self.msgs["sending"], "Отправляем…")
        self.assertEqual(self.msgs["ok-title"], "Спасибо! Вы в очереди.")

    def test_server_texts_equal_the_copy(self):
        for k, v in self.tenerife.FORM_MSG.items():
            self.assertEqual(v, self.msgs[k], k)
        self.assertEqual(self.tenerife.THANKS_TITLE, self.msgs["ok-title"])
        self.assertEqual(self.tenerife.THANKS_TEXT, self.msgs["ok-next"])

    def test_every_form_carries_the_messages(self):
        for f in SITE.glob("*.html"):
            t = f.read_text(encoding="utf-8")
            form = re.search(r'<form id="wl-form"[^>]*>', t)
            if not form:
                continue
            for k, v in self.msgs.items():
                m = re.search(r'data-msg-%s="([^"]*)"' % k, form.group(0))
                self.assertIsNotNone(m, (f.name, k))
                self.assertEqual(htmllib.unescape(m.group(1)), v, (f.name, k))
                self.assertNotIn("@", m.group(1))  # &#64;: out of Cloudflare's e-mail obfuscation

    def test_missing_label_fails_the_build(self):
        md = (BUILD / "copy_v3" / "17_forma.md").read_text(encoding="utf-8")
        with self.assertRaises(build_v3.BuildError):
            build_v3.form_messages(md.replace("**Нет согласия.**", "**Согласие нет.**"))

    def test_old_texts_gone(self):
        for f in (ROOT / "app/static/tenerife/site/waitlist.js", ROOT / "app/tenerife.py"):
            t = f.read_text(encoding="utf-8")
            for old in ("Ошибка сети", "Ошибка. Попробуйте", "Нужно согласие", "Укажите имя и контакт",
                        "Слишком много заявок. Попробуйте позже", "Мы свяжемся с вами.');"):
                self.assertNotIn(old, t, (f.name, old))
        code = re.sub(r"/\*.*?\*/", "", (ROOT / "app/static/tenerife/site/waitlist.js").read_text(encoding="utf-8"),
                      flags=re.S)
        self.assertNotRegex(code, r"[А-Яа-яЁё]")  # no Russian literal left in the script: texts come from the page


class FormServerTest(R4Case):
    def post(self, json_body=True, **kw):
        d = {"name": "QA", "contact": "qa@example.com", "language": "ru", "consent": True, "page": "/tenerife/"}
        d.update(kw)
        if json_body:
            return self.client.post("/api/tenerife/waitlist", json=d)
        d["consent"] = "on" if d["consent"] else ""
        return self.client.post("/api/tenerife/waitlist", data=d)

    def test_field_errors_each_their_own_text(self):
        t = self.tenerife.FORM_MSG
        for kw, field in (({"name": ""}, "name"), ({"contact": "abc"}, "contact"), ({"contact": ""}, "contact"),
                          ({"language": "xx"}, "language"), ({"consent": False}, "consent")):
            r = self.post(**kw)
            self.assertEqual(r.status_code, 400, kw)
            self.assertEqual(r.get_json(), {"ok": False, "error": t[field], "field": field}, kw)

    def test_rate_limit_text(self):
        with mock.patch.object(self.tenerife, "RATE_LIMIT_MAX", 1):
            self.assertEqual(self.post().status_code, 200)
            r = self.post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG["rate"])

    def test_no_js_pages_use_the_copy_and_keep_the_email_off_cloudflare(self):
        r = self.post(json_body=False)
        self.assertEqual(r.status_code, 303)
        body = self.get(r.headers["Location"].replace("http://localhost", ""))
        self.assertIn("Спасибо! Вы в очереди.", body)
        self.assertIn("Заявка уходит команде проекта в Telegram и на <!--email_off-->info@artemisresort.com"
                      "<!--/email_off-->. Мы свяжемся с вами.", body)
        r = self.post(json_body=False, consent=False)
        self.assertIn("Отметьте согласие на обработку данных.", r.get_data(as_text=True))


NODE = shutil.which("node")
JS_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const scen = process.argv[3];
const M = JSON.parse(process.argv[4]); const out = {focus: null};
function elt(id){ return {id, value:'', checked:false, textContent:'', className:'', disabled:false, attrs:{},
  setAttribute(k,v){this.attrs[k]=v}, removeAttribute(k){delete this.attrs[k]}, focus(){out.focus=id} }; }
const els = {}; for (const id of ['wl-msg','wl-submit','wl-name','wl-contact','wl-lang','wl-consent',
  'wl-name-err','wl-contact-err','wl-lang-err','wl-consent-err']) els[id] = elt(id);
els['wl-submit'].textContent = 'Встать в очередь';
const data = {}; for (const k in M) data['msg' + k.replace(/(^|-)([a-z])/g, (_, d, c) => c.toUpperCase())] = M[k];
let submit; const fields = {name:{value:'QA'}, contact:{value:'qa@example.com'}, language:{value:'ru'},
  consent:{checked:true}, website:{value:''}, page:{value:'/tenerife/'}};
if (scen === 'empty-name') fields.name.value = '';
const form = {dataset:data, elements:Object.assign([], fields), reset(){out.reset=true},
  addEventListener(_, fn){ submit = fn; }};
Object.assign(form.elements, fields);
global.document = {getElementById: id => id === 'wl-form' ? form : els[id]};
global.location = {search: scen === 'ok-param' ? '?ok=1' : ''};
const resp = (status, type, body) => Promise.resolve({status, ok: status < 300,
  headers:{get: () => type}, json: () => typeof body === 'string' ? Promise.reject(new Error('html'))
                                                                    : Promise.resolve(body)});
global.window = {fetch: true};
global.fetch = () => { out.sending = els['wl-submit'].textContent; out.disabled = els['wl-submit'].disabled; return ({
  ok: () => resp(200, 'application/json', {ok:true}),
  rate: () => resp(429, 'application/json', {ok:false, error:'server 429 text'}),
  s500: () => resp(500, 'text/html', '<html>'),
  s502json: () => resp(502, 'application/json', {ok:false, error:'x'}),
  html200: () => resp(200, 'text/html; charset=utf-8', '<html>'),
  network: () => Promise.reject(new TypeError('Failed to fetch')),
  field: () => resp(400, 'application/json', {ok:false, field:'contact', error:'server text'}),
  plain400: () => resp(400, 'application/json', {ok:false, error:'Сервер: текст'}),
}[scen] || (() => resp(200, 'application/json', {ok:true})))(); };
eval(src);
if (scen === 'ok-param') { console.log(JSON.stringify({msg: els['wl-msg'].textContent})); process.exit(0); }
submit({preventDefault(){}});
setTimeout(() => { Object.assign(out, {msg: els['wl-msg'].textContent, cls: els['wl-msg'].className,
  button: els['wl-submit'].textContent, after_disabled: els['wl-submit'].disabled,
  contact_err: els['wl-contact-err'].textContent, name_err: els['wl-name-err'].textContent,
  contact_invalid: els['wl-contact'].attrs['aria-invalid'] || null});
  console.log(JSON.stringify(out)); }, 50);
"""


@unittest.skipUnless(NODE, "node not installed")
class WaitlistJsTest(unittest.TestCase):
    """waitlist.js run in node against a DOM stub: r.ok / status / Content-Type are checked before r.json()."""

    @classmethod
    def setUpClass(cls):
        cls.msgs = build_v3.form_messages()
        cls.dir = tempfile.TemporaryDirectory()
        cls.harness = Path(cls.dir.name) / "h.js"
        cls.harness.write_text(JS_HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def run_js(self, scen):
        r = subprocess.run([NODE, str(self.harness), str(ROOT / "app/static/tenerife/site/waitlist.js"), scen,
                            json.dumps(self.msgs)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_success_and_sending_label(self):
        o = self.run_js("ok")
        self.assertEqual(o["sending"], "Отправляем…")
        self.assertTrue(o["disabled"])
        self.assertEqual(o["msg"], self.msgs["ok-title"] + " " + self.msgs["ok-next"])
        self.assertEqual(o["cls"], "msg ok")
        self.assertTrue(o["reset"])
        self.assertEqual(o["button"], "Встать в очередь")
        self.assertFalse(o["after_disabled"])

    def test_429(self):
        self.assertEqual(self.run_js("rate")["msg"], self.msgs["rate"])

    def test_5xx_and_html_are_server_errors(self):
        for scen in ("s500", "s502json", "html200"):
            o = self.run_js(scen)
            self.assertEqual(o["msg"], self.msgs["server"], scen)
            self.assertEqual(o["button"], "Встать в очередь", scen)

    def test_network(self):
        o = self.run_js("network")
        self.assertEqual(o["msg"], self.msgs["network"])
        self.assertFalse(o["after_disabled"])

    def test_server_field_gets_its_own_text(self):
        o = self.run_js("field")
        self.assertEqual(o["contact_err"], self.msgs["contact"])
        self.assertEqual(o["contact_invalid"], "true")
        self.assertEqual(o["msg"], "")

    def test_other_400_shows_the_server_text(self):
        self.assertEqual(self.run_js("plain400")["msg"], "Сервер: текст")

    def test_client_validation_and_ok_param(self):
        o = self.run_js("empty-name")
        self.assertEqual(o["name_err"], self.msgs["name"])
        self.assertNotIn("sending", o)
        self.assertEqual(self.run_js("ok-param")["msg"], self.msgs["ok-title"] + " " + self.msgs["ok-next"])


class BuildWhatsAppTokenTest(unittest.TestCase):
    """Kimi r16: 14_podval «WhatsApp: {номер из TENERIFE_WHATSAPP}» -> runtime slot; the build needs a valid env."""

    def test_footer_token_becomes_the_slot(self):
        md = (BUILD / "copy_v3" / "14_podval.md").read_text(encoding="utf-8")
        self.assertIn(build_v3.WA_TOKEN, md)
        fmap = build_v3.figure_map(build_v3.load_model(build_v3.MODEL))
        foot = build_v3.parse_footer(md, fmap, build_v3.figure_regex(fmap))
        self.assertIn("whatsapp", foot["contacts"])
        for bad in ("WhatsApp: +440000000000", "WhatsApp: {номер}", "+44 0000 000000", "WhatsApp: 0044 0000 000000"):
            with self.assertRaises(build_v3.BuildError, msg=bad):
                build_v3.parse_footer(md.replace(build_v3.WA_TOKEN, bad), fmap, build_v3.figure_regex(fmap))

    def test_build_fails_without_or_with_invalid_env_and_never_shows_the_value(self):
        for v in ("", "  ", "+44 0000", "440000000000", "+0123456789", "+4400000000000000"):
            with mock.patch.dict(os.environ, {"TENERIFE_WHATSAPP": v}):
                with self.assertRaises(build_v3.BuildError) as cm:
                    build_v3.build(write=False)
                if v.strip():
                    self.assertNotIn(v.strip(), str(cm.exception))
        with mock.patch.dict(os.environ, {"TENERIFE_WHATSAPP": FAKE}):
            outputs, _ = build_v3.build(write=False)
        for name, out in outputs.items():
            self.assertNotIn(FAKE[1:], out, name)  # the value is never baked into the files
            self.assertNotIn("TENERIFE_WHATSAPP", out, name)

    def test_lone_brace_and_variable_name_fail_the_check(self):
        page = (SITE / "faq.html").read_text(encoding="utf-8")
        for bad in ("{", "}", "TENERIFE_WHATSAPP"):
            with self.assertRaises(build_v3.BuildError, msg=bad):
                build_v3.check_output("faq", page.replace("</footer>", bad + "</footer>", 1))
        build_v3.check_output("faq", page)

    def test_draft_18_is_not_built_or_hashed(self):
        names = [f.name for f in build_v3.copy_files()]
        self.assertEqual(len(names), 17)
        self.assertFalse(any(n.startswith("18_") for n in names))
        self.assertNotIn("investoram", " ".join(n for _f, n in build_v3.PAGES))
        self.assertFalse((SITE / "investoram.html").exists())


# QA r16: only fake numbers (all zeros after the country code, or …01) may appear anywhere in r4's sources
FAKE_DIGITS = {"440000000000", "440000000001", "10000000000", "0440000000", "00440000000000", "0123456789",
               "4400000000000000"}


class PhoneLiteralTest(R4Case):
    """QA r16: no contact number in the code, the copy, the built pages or the tests except the fake ones; on the
    served pages the only number is the TENERIFE_WHATSAPP value."""
    env = {"TENERIFE_WHATSAPP": FAKE, "TENERIFE_INDEXING": "1"}

    def test_served_pages_only_the_env_number_and_no_token(self):
        for env in ({"TENERIFE_WHATSAPP": FAKE}, {}):
            with mock.patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop("TENERIFE_WHATSAPP", None)
                for url in URLS:
                    body = self.get(url)
                    text = re.sub(r'<script type="application/(ld\+)?json"[^>]*>.*?</script>', "", body, flags=re.S)
                    self.assertNotIn("{", text, url)
                    self.assertNotIn("}", text, url)
                    self.assertNotIn("TENERIFE_WHATSAPP", body, url)
                    self.assertNotIn("tel:", body, url)
                    nums = {re.sub(r"\D", "", m.group(0))
                            for m in build_v3.PHONE_RX.finditer(htmllib.unescape(re.sub(r"<[^>]+>", " ", text)))}
                    self.assertEqual(nums, {FAKE[1:]} if env else set(), url)

    def test_build_check_rejects_any_phone_literal(self):
        page = (SITE / "norte.html").read_text(encoding="utf-8")
        for bad in ("<li>+44 0000 000000</li>", "<li>0044 0000 000000</li>", '<a href="tel:+440000000000">x</a>',
                    '<a href="https://wa.me/440000000000">x</a>'):
            with self.assertRaises(build_v3.BuildError, msg=bad):
                build_v3.check_output("norte", page.replace("</footer>", bad + "</footer>", 1))

    def test_sources_contain_fake_numbers_only(self):
        files = [*ROOT.glob("app/tenerife*.py"), *ROOT.glob("app/templates/tenerife/site/*"),
                 *ROOT.glob("app/static/tenerife/site/*.js"), *ROOT.glob("app/tenerife_site/*"),
                 *BUILD.glob("*.py"), *BUILD.glob("*.html"), *BUILD.glob("*.json"), *BUILD.glob("copy_v3/*"),
                 *BUILD.glob("design/*"), *ROOT.glob("tests/test_tenerife*.py"), ROOT / "tests/test_lead_relay.py",
                 ROOT / "README.md"]
        for f in files:
            if f.is_file():
                for m in build_v3.PHONE_RX.finditer(f.read_text(encoding="utf-8", errors="ignore")):
                    self.assertIn(re.sub(r"\D", "", m.group(0)), FAKE_DIGITS, f.name)


class ThanksPageTest(R4Case):
    """QA r16: /tenerife/gracias/ is the no-JS success page of the form (prod a55165b has no such route and nothing
    links to it there): 17_forma success texts, noindex in both TENERIFE_INDEXING states, not in the sitemap."""

    def test_noindex_in_both_states_and_texts(self):
        msgs = build_v3.form_messages()
        for env in ({"TENERIFE_INDEXING": "1"}, {}):
            with mock.patch.dict(os.environ, env):
                if not env:
                    os.environ.pop("TENERIFE_INDEXING", None)
                r = self.client.get("/tenerife/gracias/")
                body = r.get_data(as_text=True)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers["X-Robots-Tag"], "noindex, nofollow")
                self.assertEqual(body.count('<meta name="robots" content="noindex'), 1)
                self.assertIn(msgs["ok-title"], body)
                self.assertIn(msgs["ok-next"].replace("info@artemisresort.com",
                                                      "<!--email_off-->info@artemisresort.com<!--/email_off-->"), body)
                self.assertNotIn("gracias", self.client.get("/sitemap.xml").get_data(as_text=True))

    def test_only_the_no_js_success_leads_there(self):
        r = self.client.post("/api/tenerife/waitlist", data={"name": "QA", "contact": "qa@example.com",
                                                              "language": "ru", "consent": "on", "page": "/tenerife/"})
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["Location"].endswith("/tenerife/gracias/?back=%2Ftenerife%2F"))
        for f in SITE.glob("*.html"):
            self.assertNotIn("/gracias", f.read_text(encoding="utf-8"), f.name)


class OldFormStringsTest(unittest.TestCase):
    def test_old_strings_gone(self):
        files = [*SITE.glob("*.html"), ROOT / "app/static/tenerife/site/waitlist.js", ROOT / "app/tenerife.py",
                 ROOT / "app/templates/tenerife/site/_components.html", BUILD / "build_v3.py"]
        for f in files:
            t = f.read_text(encoding="utf-8")
            for old in ("Согласен", "Согласна", "согласен", "согласна", "(на)"):
                self.assertNotIn(old, t, (f.name, old))
            self.assertIsNone(re.search(r"(?i)лист\w* ожидания", t), f.name)



class NoWaitingWordTest(R4Case):
    """QA PS-04: «ожидан…» (the old «Вы в листе ожидания») appears nowhere in what /tenerife/ serves, since the
    copy itself (copy_v3 01–17) does not contain it; the success text is the 17_forma one."""

    def test_copy_has_no_waiting_word(self):
        for f in build_v3.copy_files():
            self.assertNotIn("ожидан", f.read_text(encoding="utf-8").lower(), f.name)

    def test_zero_in_all_output(self):
        bodies = {u: self.get(u) for u in URLS}  # /tenerife-preview/ is a 301 since T47
        for f in (ROOT / "app/static/tenerife").rglob("*"):
            if f.suffix in (".js", ".css", ".json", ".html", ".txt"):
                bodies[str(f.relative_to(ROOT))] = f.read_text(encoding="utf-8")
        ok = self.client.post("/api/tenerife/waitlist", json={
            "name": "Иван", "contact": "ivan@example.com", "language": "ru", "consent": True, "page": "/tenerife/"})
        bodies["json ok"] = ok.get_data(as_text=True)
        bad = self.client.post("/api/tenerife/waitlist", data={"name": "", "contact": "", "page": "/tenerife/"})
        bodies["no-JS error notice"] = bad.get_data(as_text=True)
        for k, body in bodies.items():
            self.assertEqual(body.lower().count("ожидан"), 0, k)
        thanks = self.get("/tenerife/gracias/")
        self.assertIn(htmllib.escape(self.tenerife.FORM_MSG["ok-title"], quote=False), thanks)
        self.assertIn(self.tenerife.FORM_MSG["ok-title"], build_v3.form_messages()["ok-title"])


class LegalPagesV31Test(R4Case):
    """QA PS-05: impressum / privacy in the v3.1 site design (site.css, not the old base.css), text = copy_v3
    15_impressum.md / 16_privacy.md word for word, meta description = meta_legal.md (sha 7bed1578…), and no
    two /tenerife/ pages share a description."""
    META_LEGAL_SHA = "f1d16ad147d3cab95ab79cefe7935b739854afa43fb7b1de7e810de1e19bf838"

    def test_meta_legal_pinned(self):
        import hashlib
        self.assertEqual(hashlib.sha256((BUILD / "copy_v3/meta_legal.md").read_bytes()).hexdigest(),
                         self.META_LEGAL_SHA)

    def test_design_and_meta(self):
        for name in ("impressum", "privacy"):
            body = self.get(f"/tenerife/ru/{name}/")   # RU — канон юридического текста (03.11.2026)
            self.assertIn('href="/static/tenerife/site/site.css', body, name)
            self.assertNotIn("/static/tenerife/base.css", body, name)
            self.assertRegex(body, r'<section class="[^"]*\blegal\b', name)
            self.assertIn(f'<meta name="description" content="{htmllib.escape(build_v3.legal_meta(name))}">',
                          body, name)

    def test_descriptions_unique(self):
        seen = {}
        for url in URLS:
            got = re.findall(r'<meta name="description" content="([^"]*)">', self.get(url))
            self.assertLessEqual(len(got), 1, url)
            for d in got:
                self.assertNotIn(d, seen, (url, seen.get(d)))
                seen[d] = url
        self.assertGreaterEqual(len(seen), 15)

    def test_legal_text_is_the_copy(self):
        for name, md in (("impressum", "15_impressum.md"), ("privacy", "16_privacy.md")):
            main = re.search(r"<main.*?</main>", self.get(f"/tenerife/ru/{name}/"), re.S).group(0)
            text = htmllib.unescape(re.sub(r"<[^>]+>", " ", main)).replace("← К сайту проекта", " ")
            src = (BUILD / "copy_v3" / md).read_text(encoding="utf-8")
            src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
            src = re.sub(r"\]\([^)]*\)", " ", src)
            words = lambda t: re.findall(r"[\w@.+-]+", t.replace("\\_", "_").replace("**", " "))  # noqa: E731
            self.assertEqual([w.strip(".") for w in words(src) if w.strip(".-+")],
                             [w.strip(".") for w in words(text) if w.strip(".-+")], name)


class TestLeadPrefixTest(R4Case):
    """QA PS-09: TEST leads still notify (QA sees delivery), Telegram text starts with «[TEST] »; others unchanged.
    Telegram is mocked (_send), nothing is sent."""

    def tg_text(self, *args, **kw):
        notify = sys.modules["notify"]
        env = {"ARTEMIS_TG_BOT_TOKEN": "fake-token", "ARTEMIS_TG_CHAT_ID": "-1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(notify, "_send") as send:
            self.assertTrue(notify.notify_lead(*args, background=False, **kw))
        send.assert_called_once()
        return send.call_args[0][2]

    def test_telegram_prefix(self):
        t = self.tg_text("Tenerife waitlist", "TEST QA", "qa-test@example.com", "ru", "/tenerife/")
        self.assertTrue(t.startswith("[TEST] Artemis — Tenerife waitlist\n"), t)
        self.assertIn("Имя: TEST QA", t)
        t = self.tg_text("Crete enquiry", "Bob", "bob@x.io", "en", "/en/", test=True)
        self.assertTrue(t.startswith("[TEST] Artemis — Crete enquiry\n"), t)
        for name in ("Анна", "Testa Celeste", "test"):
            t = self.tg_text("Tenerife waitlist", name, "a@example.com", "ru", "/tenerife/")
            self.assertTrue(t.startswith("Artemis — Tenerife waitlist\n"), (name, t))

    def test_tenerife_test_lead_not_dropped(self):
        r = self.client.post("/api/tenerife/waitlist", json={
            "name": "QA-TEST r4", "contact": "qa-test@example.com", "language": "ru", "consent": True,
            "page": "/tenerife/"})
        self.assertEqual(r.status_code, 200)
        self.tenerife.notify_lead.assert_called_once()
        self.assertEqual(self.tenerife.notify_lead.call_args.args[1], "QA-TEST r4")

    def test_crete_message_with_test(self):
        body = {"name": "Bob", "email": "bob@x.io", "consent": True, "enquiry_type": "investor", "lang": "en",
                "page": "/en/"}
        with mock.patch.object(self.mod, "notify_lead") as nl:
            self.assertEqual(self.client.post("/api/enquiry", json={**body, "message": "TEST QA, ignore"})
                             .status_code, 200)
        nl.assert_called_once_with("Crete enquiry", "Bob", "bob@x.io", "en", "/en/", test=True)
        with mock.patch.object(self.mod, "notify_lead") as nl:
            self.client.post("/api/enquiry", json={**body, "message": "hello", "amount": "1 M €"})
        nl.assert_called_once_with("Crete enquiry", "Bob", "bob@x.io", "en", "/en/", amount="1 M €")
        self.assertNotIn("TEST QA, ignore", sys.modules["notify"].format_lead(
            "Crete enquiry", "Bob", "bob@x.io", "en", "/en/", test=True))


class HermeticTest(unittest.TestCase):
    """QA O-5: no test depends on the live designer folder (or anything else on the box outside the repo);
    the vendored design files are checked against the committed design/SHA256SUMS."""

    def test_no_test_reads_outside_the_repo(self):
        for f in (ROOT / "tests").glob("*.py"):
            src = f.read_text(encoding="utf-8").replace("HermeticTest", "")
            self.assertNotRegex(src, r"[\"']/workspace/" if f.name != Path(__file__).name else r"Path\([\"']/workspace",
                                f.name)


class SiteWideImageUniquenessTest(unittest.TestCase):
    """Designer T47 (31.10.2026): one photo fills one slot on the whole site; the build fails on any repeat."""

    @staticmethod
    def img(stem):
        return f'<img class="fp-{stem}" src="/static/tenerife/site/img/{stem}.jpg" alt="x">'

    def test_built_pages_use_each_photo_once(self):
        stems = []
        for f in sorted((ROOT / "app" / "tenerife_site" / "ru").glob("*.html")):
            stems += build_v3.IMG_SRC_RX.findall(f.read_text(encoding="utf-8"))
        self.assertTrue(stems)
        self.assertEqual(len(stems), len(set(stems)), stems)

    def test_same_file_on_two_pages_fails(self):
        with self.assertRaisesRegex(build_v3.BuildError, "repeats"):
            build_v3.check_unique_images({"a": self.img("golden-hou-d4cc25"), "b": self.img("golden-hou-d4cc25")})

    @unittest.skipUnless(PIL, "Pillow missing")
    def test_same_picture_under_another_name_fails(self):
        # og-tenerife-1200x630.jpg is a re-export of modern-low-6e9d80 (dHash distance 4)
        with self.assertRaisesRegex(build_v3.BuildError, "same picture"):
            build_v3.check_unique_images({"a": self.img("modern-low-6e9d80"), "b": self.img("og-tenerife-1200x630")})

    def test_distinct_photos_pass(self):
        stems = ["modern-low-6e9d80", "private-te-6016b5", "golden-hou-d4cc25", "green-hill-3f3856",
                 "communal-s-af42cd", "entrance-o-9abe9d", "interior-o-74f891"]
        self.assertEqual(build_v3.check_unique_images({s: self.img(s) for s in stems}), 7)

    def test_assign_site_frames_heroes_first_then_text(self):
        cfg = {"prefer": {"F01": ["p1", "p2"], "F02": ["p1"], "F03": ["p2", "p3"]}}
        out = build_v3.assign_site_frames({"a": ["F02", "F03"], "b": ["F01", "F02"]}, cfg)
        self.assertEqual(out, {"a": {"F02": "p1", "F03": "p3"}, "b": {"F01": "p2", "F02": None}})
        with self.assertRaises(build_v3.BuildError):
            build_v3.assign_site_frames({"a": ["F01", "F01"]}, cfg)

    def test_slots_without_photo_are_text_blocks(self):
        report = json.loads((BUILD / "frames_report.json").read_text(encoding="utf-8"))
        pics = [s for r in report.values() for s in r["frames"].values() if s]
        self.assertEqual(len(pics), len(set(pics)))
        self.assertGreater(sum(1 for r in report.values() for s in r["frames"].values() if not s), 0)


class TextWidthT47Test(unittest.TestCase):
    """Designer T47 text containers (audit_t47/fix_proposed.css), in the served site.css after tokens.css."""

    def test_rules(self):
        css = (ROOT / "app/static/tenerife/site/site.css").read_text(encoding="utf-8")
        over = css.index(":root{--fs-body:clamp(1.0625rem, 0.9rem + 0.5vw, 1.25rem);--measure:70ch}")
        self.assertGreater(over, css.index("--measure:    68ch"))  # the override comes after the vendored tokens
        for rule in (".split-head>.split-head__body{grid-column:5/span 8}",
                     ".ti>.ti__text,.ti--rev>.ti__text,.ti>.frame,.ti--rev>.frame{grid-column:1/-1;order:0}",
                     "@media (min-width:1280px){\n  .ti>.ti__text{grid-column:1/span 6}",
                     ".ti--rev>.ti__text{grid-column:7/span 6;order:2}",
                     ".col-text>.list,.col-text>.ledger{max-width:var(--measure)}",
                     ".legal p,.legal li{max-width:68ch}",
                     ".dt thead th.num{white-space:normal}",
                     ".table-wrap{container-type:inline-size}"):
            self.assertIn(rule, css)
        self.assertNotIn(".split-head__body{grid-column:6/span 7}", css)
        self.assertNotIn(".ti--rev>.ti__text{grid-column:8/span 5", css)

    def test_table_heads_keep_numbers_whole(self):
        """Heads wrap since T47: a figure («2 950 €/м²») must not split; NBSP only, same characters."""
        n = 0
        for f in sorted((ROOT / "app/tenerife_site").glob("*.html")):
            for h in re.findall(r"<th scope=\"col\"[^>]*>(.*?)</th>", f.read_text(encoding="utf-8")):
                n += 1
                self.assertNotRegex(h, r"\d (?=\d{3}(?!\d))|\d (?=[€%])", f.name)
        self.assertGreater(n, 0)

if __name__ == "__main__":
    unittest.main()
