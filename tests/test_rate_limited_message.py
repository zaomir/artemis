"""PR #23 c5: form_err_rate_limited is shown when /api/enquiry answers 429.

Covers the app's own limiter (JSON {"code": "rate_limited", "error": "rate_limited"}) and an nginx
limit_req 429 (HTML body). The Crete enquiry form is JS-only (button type=button + fetch), so the
page script is executed in node against a stubbed DOM and fetch; no nginx is involved."""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt
LANGS = ("en", "ru", "es", "fr")
T = {lg: json.loads((ROOT / "app" / "translations" / f"{lg}.json").read_text(encoding="utf-8")) for lg in LANGS}
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID", "ARTEMIS_ADMIN_TOKEN", "RATE_LIMIT_SALT")
TEST_SALT = "unit-tests-only-not-a-secret"
NODE = shutil.which("node")

# verbatim from webdev/artemis-ui-strings-for-review-reviewed.md line 32 (cycle 3)
EXPECTED = {
    "en": "We have already received your requests. Please try again later or email us at info@artemisresort.com.",
    "ru": "Мы уже получили ваши заявки. Повторите попытку позже или напишите нам на info@artemisresort.com.",
    "es": "Ya hemos recibido sus consultas. Inténtelo de nuevo más tarde o escríbanos a info@artemisresort.com.",
    "fr": "Nous avons déjà reçu vos demandes. Veuillez réessayer plus tard ou nous écrire à info@artemisresort.com.",
}

NGINX_429 = ("<html>\r\n<head><title>429 Too Many Requests</title></head>\r\n<body>\r\n"
             "<center><h1>429 Too Many Requests</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n")

# minimal DOM + fetch stub around the page's own form script
HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const els = {};
function el(id){
  if(!els[id]){
    els[id] = {id, value: '', checked: false, textContent: '', style: {}, attrs: {},
      setAttribute(k, v){ this.attrs[k] = v; }, removeAttribute(k){ delete this.attrs[k]; }, focus(){}};
  }
  return els[id];
}
el('f-name').value = 'Bob'; el('f-email').value = 'bob@x.io'; el('f-type').value = 'investor';
el('f-consent').checked = true;
global.document = {getElementById: el, querySelectorAll: () => []};
global.location = {pathname: '/' + input.lang + '/'};
global.window = {};
const resp = input.response;
global.fetch = async function(){
  return {status: resp.status, ok: resp.status >= 200 && resp.status < 300,
          json: async () => JSON.parse(resp.body), text: async () => resp.body};
};
""" + "\n__SCRIPT__\n" + r"""
submitEnquiry().then(function(){
  process.stdout.write(JSON.stringify({err: el('form-err').textContent, shown: el('form-err').style.display || '',
                                       ok: el('form-ok').style.display || ''}));
});
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        os.environ["RATE_LIMIT_SALT"] = TEST_SALT  # restored in tearDown
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app
        import ratelimit
        importlib.reload(ratelimit)
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()
        nl = mock.patch.object(self.mod, "notify_lead")
        nl.start()
        self.addCleanup(nl.stop)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


class TranslationTest(Base):
    def test_key_present_in_all_languages_verbatim(self):
        for lang in LANGS:
            self.assertEqual(T[lang].get("form_err_rate_limited"), EXPECTED[lang], lang)
            self.assertNotEqual(T[lang]["form_err_rate_limited"], T[lang]["form_err_generic"], lang)
            self.assertIn("info@artemisresort.com", T[lang]["form_err_rate_limited"], lang)

    def test_page_ships_localized_rate_limited_message(self):
        for lang in LANGS:
            h = self.client.get(f"/{lang}/").get_data(as_text=True)
            self.assertIn(f"rate_limited: {json.dumps(EXPECTED[lang])}", h, lang)
            self.assertIn("if(r.status === 429){ return fieldError(null, 'rate_limited'); }", h, lang)

    def test_app_429_carries_rate_limited_code(self):
        body = {"name": "Bob", "email": "bob@x.io", "consent": True, "enquiry_type": "investor", "lang": "en"}
        with mock.patch("ratelimit.ENQUIRY_LIMITS", (("10min", 600, 1),)):
            self.assertEqual(self.client.post("/api/enquiry", json=body).status_code, 200)
            r = self.client.post("/api/enquiry", json=body)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json(), {"ok": False, "code": "rate_limited", "error": "rate_limited"})


@unittest.skipUnless(NODE, "node not installed")
class ClientBehaviourTest(Base):
    def run_form(self, lang, status, body):
        page = self.client.get(f"/{lang}/").get_data(as_text=True)
        script = next(s for s in re.findall(r"<script>(.*?)</script>", page, re.S) if "const I18N" in s)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(HARNESS.replace("__SCRIPT__", script))
        try:
            stdin = json.dumps({"lang": lang, "response": {"status": status, "body": body}})
            out = subprocess.run([NODE, f.name], input=stdin, capture_output=True, text=True, encoding="utf-8",
                                 timeout=30, check=True).stdout
        finally:
            os.unlink(f.name)
        return json.loads(out)

    def test_app_429_shows_rate_limited_not_generic(self):
        body = json.dumps({"ok": False, "code": "rate_limited", "error": "rate_limited"})
        for lang in LANGS:
            res = self.run_form(lang, 429, body)
            self.assertEqual(res["err"], EXPECTED[lang], lang)
            self.assertNotEqual(res["err"], T[lang]["form_err_generic"], lang)
            self.assertEqual(res["shown"], "block", lang)

    def test_legacy_app_429_without_code_shows_rate_limited(self):
        res = self.run_form("en", 429, json.dumps({"ok": False, "error": "rate_limited"}))
        self.assertEqual(res["err"], EXPECTED["en"])

    def test_nginx_html_429_shows_rate_limited_not_network(self):
        for lang in LANGS:
            res = self.run_form(lang, 429, NGINX_429)
            self.assertEqual(res["err"], EXPECTED[lang], lang)
            self.assertNotEqual(res["err"], T[lang]["form_err_network"], lang)

    def test_other_errors_unchanged(self):
        res = self.run_form("en", 400, json.dumps({"ok": False, "code": "generic", "field": "enquiry_type",
                                                   "error": "Invalid enquiry type"}))
        self.assertEqual(res["err"], T["en"]["form_err_generic"])
        res = self.run_form("en", 200, json.dumps({"ok": True}))
        self.assertEqual((res["err"], res["ok"]), ("", "block"))


if __name__ == "__main__":
    unittest.main()
