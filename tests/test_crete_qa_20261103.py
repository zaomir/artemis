"""Crete QA: complete locales, accurate CTA, keyboard form and duplicate-request protection.

The frontend behavior runs against a small DOM/fetch mock: no notification or real
lead endpoint is called. Browser layout and native Enter behavior are smoke-tested
separately on the local app before shipping.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from werkzeug.datastructures import MultiDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
LANGS = ("en", "ru", "es", "fr")
T = {lang: json.loads((ROOT / "app" / "translations" / f"{lang}.json").read_text()) for lang in LANGS}


class CreteQaTest(unittest.TestCase):
    def setUp(self):
        import app as artemis_app
        self.client = artemis_app.app.test_client()

    def page(self, lang="en"):
        response = self.client.get(f"/{lang}/")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_body_and_image_text_no_longer_fall_back_to_english(self):
        # Distinct prose from each major section catches the partial-locale failure.
        for lang in ("ru", "es", "fr"):
            h = self.page(lang)
            for key in ("glance_title", "location_intro", "concept_body", "accommodation_intro",
                        "invest_intro", "status_intro", "gov_intro", "cgi_note", "alt_room"):
                self.assertNotEqual(T[lang][key], T["en"][key], (lang, key))
                self.assertNotIn(T["en"][key], h, (lang, key))
            self.assertNotIn("do not mix", h)

    def test_financial_terms_and_values_are_preserved(self):
        for lang in LANGS:
            t = T[lang]
            self.assertEqual(t["invest_raise_v"], "€20M")
            self.assertEqual(t["invest_exit_v"], "€80M")
            for value in ("€20M", "€80M", "€3M", "10%", "4%"):
                self.assertIn(value, t["invest_intro"], (lang, value))
            for value in ("66", "67", "132", "€1.4–1.7M", "30", "3", "20", "5,048", "~€450K", "~€15,000"):
                self.assertIn(value, t["accommodation_intro"], (lang, value))

    def test_navigation_and_form_semantics(self):
        for lang in LANGS:
            h = self.page(lang)
            self.assertEqual(h.count('<main id="main" tabindex="-1">'), 1)
            self.assertIn(f'<a class="skip-link" href="#main">{T[lang]["skip_content"]}</a>', h)
            self.assertIn('aria-controls="primary-links"', h)
            self.assertIn('id="primary-links"', h)
            self.assertIn(f'<a class="btn btn-outline" href="#status">{T[lang]["cta_status"]}</a>', h)
            self.assertNotIn("Calculate returns", h)
            self.assertIn('<form class="form-wrap" id="enquiry-form-wrap" method="post" action="/api/enquiry" novalidate>', h)
            for name in ("name", "email", "organisation", "role", "enquiry_type", "amount", "message", "consent", "lang", "page"):
                self.assertIn(f'name="{name}"', h)
            self.assertIn('<button class="btn" type="submit">', h)
            self.assertNotIn('onclick="submitEnquiry()"', h)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_keyboard_menu_and_submit_lifecycle_with_mocked_fetch(self):
        source = "\n".join(re.findall(r"<script>(.*?)</script>", self.page(), re.S))
        harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function element(value='') {
  return {value, checked:false, style:{}, attrs:{}, listeners:{}, focused:false, disabled:false,
    addEventListener(type, listener){this.listeners[type]=listener;},
    setAttribute(k,v){this.attrs[k]=v;}, getAttribute(k){return this.attrs[k] ?? null;},
    removeAttribute(k){delete this.attrs[k];}, focus(){this.focused=true;}};
}
function setup(){
  const ids = Object.fromEntries(['f-name','f-email','f-org','f-role','f-type','f-amount','f-message',
    'f-consent','f-website','form-err','enquiry-form-wrap','form-ok'].map(id=>[id,element()]));
  const button=element(), menu=element(), destination=element(), link=element();
  menu.attrs['aria-expanded']='false'; link.hash='#location';
  const classes=new Set();
  const nav={classList:{toggle(name,on){on?classes.add(name):classes.delete(name);}}, contains(){return true;}};
  ids['enquiry-form-wrap'].querySelector=()=>button;
  const events={}, media={}, requests=[];
  const ctx={
    document:{getElementById:id=>ids[id], querySelector:q=>q==='nav'?nav:q==='.menu-toggle'?menu:destination,
      querySelectorAll:q=>q==='#primary-links a'?[link]:[], addEventListener:(type,listener)=>{events[type]=listener;}},
    window:{matchMedia:()=>({addEventListener:(type,listener)=>{media[type]=listener;}}),dataLayer:[]},
    location:{pathname:'/en/'},
    fetch:(url,options)=>new Promise((resolve,reject)=>{requests.push({url,options,resolve,reject});})
  };
  vm.runInNewContext(source,ctx);
  const submit=()=>{
    let prevented=false;
    ids['enquiry-form-wrap'].listeners.submit({preventDefault(){prevented=true;}});
    assert.equal(prevented,true);
  };
  const valid=()=>{
    ids['f-name'].value='QA mock'; ids['f-email'].value='qa@example.com';
    ids['f-type'].value='investor'; ids['f-consent'].checked=true;
  };
  return {ids,button,menu,destination,link,classes,events,media,requests,submit,valid};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const a=setup();
  a.menu.listeners.click();
  assert.equal(a.menu.attrs['aria-expanded'],'true'); assert(a.classes.has('menu-open'));
  a.events.keydown({key:'Escape'});
  assert.equal(a.menu.attrs['aria-expanded'],'false'); assert(a.menu.focused);
  a.menu.listeners.click(); a.link.listeners.click();
  assert.equal(a.menu.attrs['aria-expanded'],'false'); assert(a.destination.focused);
  a.menu.listeners.click(); a.media.change({matches:true});
  assert.equal(a.menu.attrs['aria-expanded'],'false');
  a.submit();
  assert.equal(a.requests.length,0); assert(a.ids['f-name'].focused);
  a.valid(); a.submit(); a.submit();
  assert.equal(a.requests.length,1); assert(a.button.disabled);
  assert.equal(a.ids['enquiry-form-wrap'].attrs['aria-busy'],'true');
  assert.equal(a.requests[0].url,'/api/enquiry');
  assert.equal(JSON.parse(a.requests[0].options.body).name,'QA mock');
  a.requests[0].resolve({ok:true,status:200,json:async()=>({ok:true})}); await tick();
  assert.equal(a.ids['enquiry-form-wrap'].style.display,'none');
  assert.equal(a.ids['form-ok'].style.display,'block'); assert(a.ids['form-ok'].focused);
  assert(a.button.disabled); assert.equal(a.ids['enquiry-form-wrap'].attrs['aria-busy'],undefined);
  a.submit(); assert.equal(a.requests.length,1);
  const b=setup(); b.valid(); b.submit(); b.requests[0].reject(new Error('offline')); await tick();
  assert.equal(b.button.disabled,false); assert.equal(b.ids['form-err'].textContent,'Network error. Please try again.');
  b.submit(); assert.equal(b.requests.length,2);
  b.requests[1].resolve({ok:false,status:429,json:async()=>{throw new Error('must not parse nginx HTML');}}); await tick();
  assert.equal(b.button.disabled,false); assert.match(b.ids['form-err'].textContent,/Too many enquiries/);
  console.log('PASS: menu keyboard + localized validation + one request in flight + success guard + retry');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps(source),
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS:", result.stdout)


class NativeEnquiryTest(unittest.TestCase):
    """No-JS path: POST body only, shared validation/notifications and a no-echo receipt."""
    def setUp(self):
        import app as artemis_app
        self.mod = artemis_app
        self.client = artemis_app.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "leads.db")
        patch = mock.patch.object(self.mod, "DB", self.db)
        patch.start()
        self.addCleanup(patch.stop)
        notify = mock.patch.object(self.mod, "notify_lead")
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        limits = mock.patch("ratelimit.ENQUIRY_LIMITS", ())
        limits.start()
        self.addCleanup(limits.stop)

    def payload(self, **changes):
        data = {"name": "NoJS private name", "email": "nojs-private@example.test",
                "organisation": "Private organisation", "role": "Private role", "enquiry_type": "investor",
                "amount": "€3,456,789", "message": "Private enquiry text", "consent": "true",
                "lang": "en", "page": "/en/", "website": ""}
        data.update(changes)
        return data

    def assert_no_personal_echo(self, response):
        body = response.get_data(as_text=True)
        headers = str(response.headers)
        for value in ("NoJS private name", "nojs-private@example.test", "Private organisation",
                      "Private role", "Private enquiry text", "€3,456,789"):
            self.assertNotIn(value, body)
            self.assertNotIn(value, headers)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")

    def test_native_success_in_every_language_uses_post_redirect_get(self):
        for lang in LANGS:
            response = self.client.post("/api/enquiry", data=self.payload(lang=lang, page=f"/{lang}/"))
            self.assertEqual(response.status_code, 303, lang)
            self.assertEqual(response.headers["Location"], f"/{lang}/enquiry-received/")
            self.assert_no_personal_echo(response)
            self.notify.assert_called_with("Crete enquiry", "NoJS private name", "nojs-private@example.test",
                                           lang, f"/{lang}/", amount="€3,456,789")
            count = self.notify.call_count
            for _ in range(2):  # refresh is a GET: neither duplicate DB row nor duplicate notification
                receipt = self.client.get(response.headers["Location"])
                self.assertEqual(receipt.status_code, 200)
                self.assertIn(f'<html lang="{lang}">', receipt.get_data(as_text=True))
                self.assertIn(T[lang]["form_success"], receipt.get_data(as_text=True))
                self.assert_no_personal_echo(receipt)
            self.assertEqual(self.notify.call_count, count)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM leads").fetchone()[0], len(LANGS))
            self.assertEqual(conn.execute("SELECT DISTINCT amount FROM leads").fetchall(), [("€3,456,789",)])

    def test_invalid_native_fields_get_localized_html_without_a_lead(self):
        for lang in LANGS:
            for changes, key in (({"name": ""}, "required"), ({"email": "bad"}, "email"),
                                 ({"enquiry_type": ""}, "required"), ({"amount": "-5"}, "amount"),
                                 ({"consent": ""}, "consent")):
                response = self.client.post("/api/enquiry", data=self.payload(lang=lang, **changes))
                self.assertEqual(response.status_code, 400, (lang, key))
                self.assertIn("text/html", response.content_type)
                self.assertIn(T[lang][f"form_err_{key}"], response.get_data(as_text=True))
                self.assertIn(f'href="/{lang}/#enquiry"', response.get_data(as_text=True))
                self.assert_no_personal_echo(response)
        self.notify.assert_not_called()
        self.assertFalse(Path(self.db).exists())

    def test_native_honeypot_drops_without_a_lead(self):
        with mock.patch("ratelimit.hit") as hit:
            response = self.client.post("/api/enquiry", data=self.payload(website="spam"))
        self.assertEqual(response.status_code, 303)
        self.assert_no_personal_echo(response)
        hit.assert_not_called()
        self.notify.assert_not_called()
        self.assertFalse(Path(self.db).exists())

    def test_native_rate_limit_uses_html_and_retry_after(self):
        with mock.patch("ratelimit.hit", return_value=300):
            response = self.client.post("/api/enquiry", data=self.payload(lang="fr"))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "300")
        body = response.get_data(as_text=True)
        visible = body.replace("<!--email_off-->", "").replace("<!--/email_off-->", "")
        self.assertIn(T["fr"]["form_err_rate_limited"], visible)
        self.assertIn("<!--email_off-->info@artemisresort.com<!--/email_off-->", body)
        self.assert_no_personal_echo(response)
        self.notify.assert_not_called()
        self.assertFalse(Path(self.db).exists())

    def test_duplicate_native_fields_rejected_and_unknown_language_not_reflected(self):
        data = MultiDict(self.payload(lang='<script>private</script>').items())
        data.add("email", "other-private@example.test")
        response = self.client.post("/api/enquiry", data=data, headers={"Accept-Language": "es"})
        self.assertEqual(response.status_code, 400)
        self.assertIn('<html lang="es">', response.get_data(as_text=True))
        self.assertNotIn("<script>", response.get_data(as_text=True))
        self.assert_no_personal_echo(response)
        self.notify.assert_not_called()

    def test_json_contract_and_boolean_consent_stay_unchanged(self):
        body = self.payload()
        response = self.client.post("/api/enquiry", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "code": "consent", "field": "consent",
                                               "error": "Consent is required"})
        body["consent"] = True
        response = self.client.post("/api/enquiry", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.assertEqual(response.content_type, "application/json")
        self.notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
