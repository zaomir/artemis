"""P1-03 (06.11.2026): форма waitlist и ответы API на пяти языках.

Проверяет серверную половину: сообщения формы выбираются по полю `language` (сильнее страницы), неизвестный
код — страница, затем EN, затем RU; RU-канон не сломан; no-JS страница ошибки и «спасибо» отвечают на языке
заявки. Тексты en/es/de/fr — ЧЕРНОВЫЕ: нужна вычитка носителем и юридическая проверка согласия (TODO).
"""
import importlib
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tenerife_site_build"))

import build_v3  # noqa: E402

ALL = ("en", "es", "de", "fr", "ru")


class FormApiLocaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ("TENERIFE_WHATSAPP", "TENERIFE_INDEXING")}
        os.environ["TENERIFE_INDEXING"] = "1"
        os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")
        import app as artemis_app
        self.mod = importlib.reload(artemis_app)
        self.mod.DB = os.path.join(self.tmp.name, "leads.db")
        self.tenerife = self.mod.tenerife
        self.client = self.mod.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TENERIFE_INDEXING", None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def post(self, json_body=True, **kw):
        d = {"name": "QA", "contact": "qa@example.com", "language": "en", "consent": True, "page": ""}
        d.update(kw)
        if json_body:
            return self.client.post("/api/tenerife/waitlist", json=d)
        d["consent"] = "on" if d["consent"] else ""
        return self.client.post("/api/tenerife/waitlist", data=d)

    def test_error_texts_in_every_language(self):
        for loc in ALL:
            r = self.post(name="", language=loc)
            self.assertEqual(r.status_code, 400, loc)
            self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG[loc]["name"], loc)
            self.assertEqual(r.get_json()["field"], "name", loc)

    def test_language_field_beats_page(self):
        r = self.post(name="", language="de", page="/tenerife/fr/")
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["de"]["name"])

    def test_invalid_language_falls_back_to_page(self):
        r = self.post(name="", language="xx", page="/tenerife/es/")
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["es"]["name"])

    def test_invalid_language_without_page_falls_back_to_english(self):
        r = self.post(name="", language="xx")
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["en"]["name"])

    def test_missing_language_and_page_is_english(self):
        d = {"name": "", "contact": "qa@example.com", "consent": True}
        r = self.client.post("/api/tenerife/waitlist", json=d)
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["en"]["name"])

    def test_english_message_missing_falls_back_to_russian(self):
        with mock.patch.dict(self.tenerife.FORM_MSG_BY_LANG["en"], {"name": ""}):
            r = self.post(name="", language="en")
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG["name"])

    def test_ru_is_intact(self):
        self.assertEqual(self.post(name="", language="ru").get_json()["error"], self.tenerife.FORM_MSG["name"])
        with mock.patch.object(self.tenerife, "RATE_LIMIT_MAX", 1):
            self.assertEqual(self.post(language="ru").status_code, 200)
            r = self.post(language="ru")
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG["rate"])

    def test_rate_limit_text_in_request_language(self):
        with mock.patch.object(self.tenerife, "RATE_LIMIT_MAX", 1), \
                mock.patch.object(self.tenerife, "notify_lead"):
            self.assertEqual(self.post(language="es").status_code, 200)
            r = self.post(language="es")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["es"]["rate"])

    def test_no_js_error_notice_in_language(self):
        r = self.post(json_body=False, language="de", consent=False, page="/tenerife/de/")
        body = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.tenerife.FORM_MSG_BY_LANG["de"]["consent"], body)
        self.assertIn('<html lang="de">', body)
        self.assertIn('<a href="/tenerife/de/#ochered">← Zurück zum Formular</a>', body)

    def test_thanks_page_answers_in_request_language(self):
        for loc in ALL:
            r = self.client.get("/tenerife/gracias/", query_string={"lang": loc})
            body = r.get_data(as_text=True)
            self.assertIn(self.tenerife.FORM_MSG_BY_LANG[loc]["ok-title"], body, loc)
            self.assertIn(f'<html lang="{loc}">', body, loc)

    def test_thanks_page_falls_back_to_the_back_page(self):
        body = self.client.get("/tenerife/gracias/", query_string={"back": "/tenerife/es/faq/"}).get_data(as_text=True)
        self.assertIn(self.tenerife.FORM_MSG_BY_LANG["es"]["ok-title"], body)
        self.assertIn('<html lang="es">', body)

    def test_thanks_page_without_context_stays_russian(self):
        body = self.client.get("/tenerife/gracias/").get_data(as_text=True)
        self.assertIn(self.tenerife.FORM_MSG["ok-title"], body)
        self.assertIn('<html lang="ru">', body)

    def test_form_ui_covers_five_locales(self):
        self.assertEqual(set(self.tenerife.FORM_UI), set(ALL))
        self.assertEqual(set(self.tenerife.FORM_MSG_BY_LANG), set(ALL))
        for loc in ALL:
            ui = self.tenerife.FORM_UI[loc]
            for key in ("name", "contact", "language", "website", "button", "langs", "consent"):
                self.assertTrue(ui.get(key), (loc, key))
            self.assertEqual(set(ui["langs"]), set(ALL), loc)
            if loc != "ru":
                self.assertIsNone(re.search(r"[А-Яа-яЁё]", str(ui)), loc)

    def test_waitlist_js_reads_every_data_msg(self):
        """P1-03: JS не хардкодит тексты — берёт все 10 сообщений из data-msg-* (M.msg…)."""
        with open(os.path.join(ROOT, "app", "static", "tenerife", "site", "waitlist.js"),
                  encoding="utf-8") as fh:
            js = fh.read()
        used = {("msg" + name) for name in re.findall(r"M\.msg([A-Za-z]+)", js)}
        want = {"msg" + "".join(p.capitalize() for p in key.split("-"))
                for key in build_v3.FORM_MESSAGES.values()}
        self.assertEqual(used, want)
        code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        self.assertIsNone(re.search(r"[А-Яа-яЁё]", code))


if __name__ == "__main__":
    unittest.main()
