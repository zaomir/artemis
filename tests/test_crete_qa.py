"""Crete page fixes from QA protocol 2026-10-31 prod-deploy fa39ad0 (frontend items).

A-01 submit >= 44px · A-02 planned amount sent, validated, stored and notified · A-03 compact mobile header ·
A-04 status table stacks on phones · A-05 form UI localized (ru/es/fr) · A-06 legal body drop-in translations ·
A-07 e-mail format check + live error region · A-14 recipients sentence with a predicate.
Layout (scrollWidth == viewport at 320/390/1440, real heights) is checked with Playwright outside pytest."""
import importlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
LANGS = ("en", "ru", "es", "fr")
T = {l: json.loads((ROOT / "app" / "translations" / f"{l}.json").read_text(encoding="utf-8")) for l in LANGS}
ENV_KEYS = ("ARTEMIS_TG_BOT_TOKEN", "ARTEMIS_TG_CHAT_ID")

# A-05: every visible string of the enquiry form + legal chrome must be translated on ru/es/fr
FORM_KEYS = (
    "form_name", "form_email", "form_org", "form_role", "form_type", "form_amount", "form_message", "form_consent",
    "form_submit", "form_success", "form_err_required", "form_err_consent", "form_err_email", "form_err_amount",
    "form_err_generic", "form_err_network", "type_investor", "type_project_adviser", "type_operator",
    "type_contractor_supplier", "type_lender_finance_adviser", "type_public_planning", "type_general_professional",
    "type_other", "ph_name", "ph_org", "ph_role", "ph_amount", "ph_message", "enquiry_label", "enquiry_warn",
    "status_th_stream", "status_th_status", "status_th_evidence", "legal_nav_home", "privacy_title", "terms_title",
    "legal_body_pending",
)
# identical to English on purpose (same word in that language)
SAME_AS_EN = {("fr", "form_message"), ("fr", "form_org")}


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.tmp = tempfile.TemporaryDirectory()
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def page(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, path)
        return r.get_data(as_text=True)

    def post(self, **kw):
        body = {"name": "Bob", "email": "bob@x.io", "consent": True, "enquiry_type": "investor",
                "lang": "en", "page": "/en/"}
        body.update(kw)
        return self.client.post("/api/enquiry", json=body)


class AmountTest(Base):
    """A-02: «Planned investment amount» reaches the server, the DB and the lead notifications."""

    def test_page_sends_amount(self):
        h = self.page("/en/")
        body = re.search(r"JSON\.stringify\(\{([^}]*)\}\)", h).group(1)
        self.assertRegex(body, r"\bamount\b")
        self.assertIn('id="f-amount"', h)

    def test_amount_stored_and_notified(self):
        with mock.patch.object(self.mod, "notify_lead") as nl:
            r = self.post(amount="  €3,000,000 ", message="secret text", lang="es", page="/es/")
        self.assertEqual(r.get_json(), {"ok": True})
        nl.assert_called_once_with("Crete enquiry", "Bob", "bob@x.io", "es", "/es/", amount="€3,000,000")
        c = sqlite3.connect(self.mod.DB)
        self.assertEqual(c.execute("select amount from leads").fetchall(), [("€3,000,000",)])
        c.close()

    def test_amount_optional(self):
        with mock.patch.object(self.mod, "notify_lead") as nl:
            self.assertEqual(self.post(amount="").status_code, 200)
        nl.assert_called_once_with("Crete enquiry", "Bob", "bob@x.io", "en", "/en/")

    def test_amount_formats_accepted(self):
        for ok in ("3000000", "€3,000,000", "3 000 000 €", "3-5 M EUR", "от 3 млн €", "3.000.000 €", 3000000):
            with mock.patch.object(self.mod, "notify_lead"):
                self.assertEqual(self.post(amount=ok).status_code, 200, ok)

    def test_amount_rejected_server_side(self):
        for bad in ("lots", "x" * 70, "9" * 65, "<script>1</script>", "1_000", {"v": 1}, ["1"], True):
            with mock.patch.object(self.mod, "notify_lead") as nl:
                r = self.post(amount=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.get_json()["code"], "amount", bad)
            self.assertEqual(r.get_json()["field"], "amount", bad)
            nl.assert_not_called()
        self.assertFalse(os.path.exists(self.mod.DB))     # nothing stored (DB not even created)

    def test_telegram_text_has_amount_not_message(self):
        import notify
        t = notify.format_lead("Crete enquiry", "Bob", "bob@x.io", "en", "/en/", amount="€3,000,000")
        self.assertIn("Сумма (план): €3,000,000", t)
        self.assertEqual(len(t.splitlines()), 6)
        self.assertNotIn("Сумма", notify.format_lead("Tenerife waitlist", "A", "+34", "ru", "/tenerife/"))
        os.environ["ARTEMIS_TG_BOT_TOKEN"], os.environ["ARTEMIS_TG_CHAT_ID"] = "1:a", "-1"
        with mock.patch.object(notify, "_send") as send:
            notify.notify_lead("Crete enquiry", "Bob", "b@x.io", "en", "/en/", background=False, amount="5 M €")
        self.assertIn("Сумма (план): 5 M €", send.call_args[0][2])

    def test_email_copy_has_amount(self):
        spec = importlib.util.spec_from_file_location("relay_qa", ROOT / "deploy" / "artemis-lead-relay.py")
        relay = importlib.util.module_from_spec(spec)
        db = os.path.join(self.tmp.name, "relay.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, name, email, amount, message, created_at)")
        c.execute("INSERT INTO leads(name,email,amount,message,created_at) VALUES('Bob','b@x.io','€3M','secret','t')")
        c.execute("CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY, name, contact, language, page, created_at)")
        c.execute("INSERT INTO tenerife_waitlist(name,contact,language,page,created_at) VALUES('A','+34','ru','/t/','t')")
        c.commit()
        c.close()
        with mock.patch.dict(os.environ, {"ARTEMIS_DB": db}):
            spec.loader.exec_module(relay)
            rows = {tbl: (kind, d) for tbl, kind, d in relay.leads()}
        kind, d = rows["leads"]
        text = relay.lead_text(kind, d)
        self.assertIn("Сумма (план): €3M", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("Сумма", relay.lead_text(*rows["tenerife_waitlist"]))

    def test_relay_works_without_amount_column(self):
        spec = importlib.util.spec_from_file_location("relay_qa2", ROOT / "deploy" / "artemis-lead-relay.py")
        relay = importlib.util.module_from_spec(spec)
        db = os.path.join(self.tmp.name, "old.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE leads(id INTEGER PRIMARY KEY, name, email, created_at)")
        c.execute("INSERT INTO leads(name,email,created_at) VALUES('Old','o@x.io','t')")
        c.commit()
        c.close()
        with mock.patch.dict(os.environ, {"ARTEMIS_DB": db}):
            spec.loader.exec_module(relay)
            [(tbl, kind, d)] = relay.leads()
        self.assertNotIn("Сумма", relay.lead_text(kind, d))


class ValidationTest(Base):
    """A-07 (+A-05): server returns a machine code; the page shows the localized message; live region."""

    def test_email_format_checked_server_side(self):
        for bad in ("bob", "bob@", "bob@x", "a b@x.io", "@x.io", "b@x.io" + "o" * 260):
            r = self.post(email=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.get_json()["code"], "email", bad)

    def test_error_codes(self):
        self.assertEqual(self.post(name="").get_json()["code"], "required")
        self.assertEqual(self.post(email="").get_json()["code"], "required")
        self.assertEqual(self.post(consent=False).get_json()["code"], "consent")
        self.assertEqual(self.post(enquiry_type="nope").get_json()["code"], "generic")
        self.assertEqual(self.client.post("/api/enquiry", data="x", content_type="text/plain").status_code, 400)

    def test_page_maps_codes_to_localized_messages(self):
        for lang in LANGS:
            h = self.page(f"/{lang}/")
            self.assertIn('id="form-err" role="alert" aria-live="assertive"', h, lang)
            self.assertIn('role="status"', h, lang)
            self.assertNotIn("d.error", h, lang)          # English server text is never shown
            for code, key in (("required", "form_err_required"), ("consent", "form_err_consent"),
                              ("email", "form_err_email"), ("amount", "form_err_amount"),
                              ("generic", "form_err_generic"), ("network", "form_err_network")):
                self.assertIn(f"{code}: {json.dumps(T[lang][key])}", h, (lang, code))
            self.assertIn("EMAIL_RE.test(email)", h)
            self.assertIn("AMOUNT_RE.test(amount)", h)


class LocalizationTest(Base):
    """A-05: form labels, placeholders, options, buttons and messages are in the page language."""

    def test_same_keys_in_every_language(self):
        for lang in LANGS:
            self.assertEqual(set(T[lang]), set(T["en"]), lang)

    def test_form_strings_translated(self):
        for lang in ("ru", "es", "fr"):
            for key in FORM_KEYS:
                self.assertTrue(T[lang][key].strip(), (lang, key))
                if (lang, key) not in SAME_AS_EN:
                    self.assertNotEqual(T[lang][key], T["en"][key], (lang, key))

    def test_no_english_form_text_on_translated_pages(self):
        english = [T["en"][k] for k in FORM_KEYS if k not in ("form_message", "form_org", "legal_body_pending")]
        for lang in ("ru", "es", "fr"):
            h = self.page(f"/{lang}/")
            form = h[h.index('id="enquiry"'):h.index("</section>", h.index('id="enquiry"'))]
            own = set(T[lang].values())
            for s in english:
                if s not in own:       # e.g. fr «Organisation» is both the EN placeholder and the FR label
                    self.assertNotIn(s, form, (lang, s))
            for k in ("form_name", "form_submit", "form_consent", "ph_amount", "type_other"):
                self.assertIn(T[lang][k], h, (lang, k))


class LayoutMarkupTest(Base):
    """A-01 / A-03 / A-04: CSS + markup contracts (real sizes are measured with Playwright)."""

    def test_buttons_at_least_44px(self):
        h = self.page("/en/")
        self.assertRegex(h, r"\.btn\{[^}]*min-height:44px")
        self.assertRegex(h, r"#enquiry-form-wrap \.btn\{[^}]*min-height:48px")
        self.assertIn('<button class="btn" type="button" onclick="submitEnquiry()">', h)

    def test_compact_mobile_header(self):
        for lang in LANGS:
            h = self.page(f"/{lang}/")
            self.assertIn(f'<a class="btn" href="#enquiry" aria-label="{T[lang]["cta_request"]}">'
                          f'<span class="cta-long">{T[lang]["cta_request"]}</span>'
                          f'<span class="cta-short">{T[lang]["nav_enquiry"]}</span></a>', h)
        h = self.page("/en/")
        self.assertIn("@media(max-width:1279px){.logo-rest{display:none}}", h)
        self.assertIn("@media(max-width:1099px){.nav-links{display:none}}", h)
        mobile = h[h.index("@media(max-width:600px)"):]
        self.assertIn("nav .btn .cta-long{display:none}", mobile)
        self.assertNotRegex(h, r"(html|body)\{[^}]*overflow-x:hidden")   # real fit, not clipping

    def test_status_table_stacks_on_phones(self):
        h = self.page("/ru/")
        self.assertIn('<div class="table-scroll">\n  <table class="status-table">', h)
        self.assertEqual(h.count(f'data-label="{T["ru"]["status_th_stream"]}"'), 6)
        self.assertIn(".status-table td::before{content:attr(data-label)", h)


class LegalDropInTest(Base):
    """A-06: English body until a reviewed translation is dropped into app/legal_translations/."""

    def test_pending_english_body_marked(self):
        for lang in ("ru", "es", "fr"):
            h = self.page(f"/{lang}/privacy/")
            self.assertIn(f'<p lang="en">{T["en"]["privacy_body"]}</p>', h, lang)
            self.assertIn(T[lang]["legal_body_pending"], h, lang)
            self.assertIn(f"<h1>{T[lang]['privacy_title']}</h1>", h, lang)
            self.assertIn(T[lang]["legal_nav_home"], h, lang)
        h = self.page("/en/privacy/")
        self.assertIn(f"<p>{T['en']['privacy_body']}</p>", h)
        self.assertNotIn('class="pending"', h)

    def test_drop_in_translation_rendered(self):
        import legal_i18n
        d = Path(self.tmp.name) / "legal"
        d.mkdir()
        (d / "privacy.ru.md").write_text(
            "<!-- header: ignored -->\n<!-- @title -->\nПолитика конфиденциальности\n<!-- @body -->\n"
            "Первый абзац <b>текста</b>.\n\nВторой\nабзац.\n<!-- @recipients -->\n"
            "Получатель и обработчик копий заявок — Google (Gmail, Google Workspace): тест.\n", encoding="utf-8")
        (d / "privacy.en.md").write_text("<!-- @body -->\nIgnored\n", encoding="utf-8")
        with mock.patch.object(legal_i18n, "LEGAL_DIR", d):
            h = self.page("/ru/privacy/")
            en = self.page("/en/privacy/")
            es = self.page("/es/privacy/")
        self.assertIn("<h1>Политика конфиденциальности</h1>", h)
        self.assertIn("<p>Первый абзац &lt;b&gt;текста&lt;/b&gt;.</p>", h)
        self.assertIn("<p>Второй абзац.</p>", h)
        self.assertIn("Google (Gmail, Google Workspace): тест.", h)
        self.assertNotIn(T["en"]["privacy_body"], h)
        self.assertNotIn('class="pending"', h)
        self.assertNotIn("Ignored", en)
        self.assertIn(T["en"]["privacy_body"], es)        # other languages keep working meanwhile

    def test_parse_and_load_guards(self):
        import legal_i18n
        self.assertIsNone(legal_i18n.load("privacy", "ru", Path(self.tmp.name)))     # no file
        self.assertIsNone(legal_i18n.load("../x", "ru"))
        self.assertIsNone(legal_i18n.load("privacy", "r/"))
        p = Path(self.tmp.name) / "privacy.fr.md"
        p.write_text("<!-- @title -->\nSans corps\n", encoding="utf-8")
        self.assertIsNone(legal_i18n.load("privacy", "fr", Path(self.tmp.name)))     # body required
        self.assertEqual(legal_i18n.parse("<!-- @body -->\na\nb\n\n\nc"), {"body": ["a b", "c"]})

    def test_repo_ships_no_unreviewed_translation(self):
        files = sorted(p.name for p in (ROOT / "app" / "legal_translations").glob("*.md") if p.name != "README.md")
        for name in files:          # once reviewed translations land they must parse and keep the markers
            page, lang, _ = name.split(".")
            import legal_i18n
            self.assertIsNotNone(legal_i18n.load(page, lang), name)


class RecipientsStyleTest(unittest.TestCase):
    """A-14: the RU/ES recipients sentence has a verb (was a verbless fragment); amount disclosed (A-02)."""

    def test_predicate_and_amount(self):
        self.assertIn("направляется на служебный адрес", T["ru"]["privacy_recipients"])
        self.assertIn("Se envía una copia", T["es"]["privacy_recipients"])
        for lang, word in (("en", "planned amount"), ("ru", "планируемая сумма"), ("es", "importe previsto"),
                           ("fr", "montant prévu")):
            self.assertIn(word, T[lang]["privacy_recipients"], lang)


if __name__ == "__main__":
    unittest.main()
