"""P1 legal (04.11.2026): privacy под новую модель и согласие без «waiting list» на пяти языках.

Тексты en/de/es/fr/ru — ЧЕРНОВЫЕ: нужна вычитка носителем и юридическая проверка consent (TODO до запуска).
Проверяем собранные страницы (то, что отдаёт прод) и исходники legal/i18n/copy.
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "tenerife_site_build"
SITE = ROOT / "app" / "tenerife_site"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(BUILD))

import build_v3  # noqa: E402

LOCALES = ("en", "es", "de", "fr", "ru")

VERSION = {
    "en": "Version of 04.11.2026.", "de": "Fassung vom 04.11.2026.",
    "es": "Versión de 04.11.2026.", "fr": "Version du 04.11.2026.", "ru": "Версия от 04.11.2026.",
}
NEW_MODEL = {
    "en": ("number of shares", "price per share", "total investment you select", "calculation derived from them",
           "target exit amount", "target income", "exit period"),
    "de": ("Zahl der Anteile", "Preis pro Anteil", "Gesamtinvestition, die Sie im Rechner auswählen",
           "daraus abgeleitete Berechnung", "angestrebter Ausstiegsbetrag", "angestrebtes Einkommen",
           "Ausstiegszeitraum"),
    "es": ("número de acciones", "precio por acción", "inversión total que usted selecciona",
           "cálculo derivado de ellos", "importe de salida objetivo", "ingresos objetivo", "plazo de salida"),
    "fr": ("nombre d'actions", "prix par action", "investissement total que vous sélectionnez",
           "calcul qui en découle", "montant de sortie cible", "revenu cible", "période de sortie"),
    "ru": ("число акций", "цена акции", "сумма вложения, которые вы выбираете", "расчёт на их основе",
           "целевая сумма выхода", "целевой доход", "срок выхода"),
}
OLD_MODEL = {
    "en": ("waiting list", "area in square metres", "price step", "payment method", "monthly payment",
           "six instalments", "source of the participation payment", "intended exit period"),
    "de": ("Warteliste", "Fläche in Metern", "Preisstufe", "Zahlungsart", "Monatsrate", "sechs Raten",
           "Quelle der Beteiligungszahlung", "beabsichtigter Ausstiegszeitraum"),
    "es": ("lista de espera", "superficie en metros", "etapa de precio", "forma de pago", "cuota mensual",
           "seis plazos", "fuente del pago de la participación", "plazo de salida previsto"),
    "fr": ("liste d'attente", "surface en mètres", "étape de prix", "mode de paiement", "mensualité",
           "six versements", "source du paiement de la participation", "période de sortie envisagée"),
    "ru": ("записи в очередь", "площадь в метрах", "ступень цены", "способ оплаты", "платёж в месяц",
           "шестью платежами", "источник выплаты по участию", "планируемый срок выхода"),
}
NEW_CONSENT = {
    "en": "my request for a personal calculation can be processed and I can be contacted about it",
    "de": "meine Anfrage auf eine persönliche Berechnung bearbeitet und ich dazu kontaktiert werden kann",
    "es": "mi solicitud de cálculo personalizado pueda tramitarse y se pongan en contacto conmigo al respecto",
    "fr": "ma demande de calcul personnalisé puisse être traitée et que je sois contacté à ce sujet",
    "ru": "мою заявку на персональный расчёт обработали и связались со мной по ней",
}
OLD_CONSENT = {
    "en": "added to the waiting list", "de": "in die Warteliste aufgenommen",
    "es": "me incluyan en la lista de espera", "fr": "être inscrit sur la liste d'attente",
    "ru": "меня записали в очередь",
}


def page(locale, name="privacy"):
    base = SITE if locale == "en" else SITE / locale
    return (base / f"{name}.html").read_text(encoding="utf-8")


class PrivacyNewModelTest(unittest.TestCase):
    def test_built_privacy_has_version_and_new_model(self):
        for loc in LOCALES:
            text = page(loc)
            self.assertIn(VERSION[loc], text, loc)
            for phrase in NEW_MODEL[loc]:
                self.assertIn(phrase, text, (loc, phrase))
            for phrase in OLD_MODEL[loc]:
                self.assertNotIn(phrase, text, (loc, phrase))

    def test_sources_have_no_waiting_list_or_old_calculator_fields(self):
        for loc in ("en", "es", "de", "fr"):
            src = (BUILD / "legal" / loc / "privacy.html").read_text(encoding="utf-8")
            for phrase in OLD_MODEL[loc]:
                self.assertNotIn(phrase, src, (loc, phrase))
            self.assertIn(VERSION[loc], src, loc)
        ru = (ROOT / "app" / "templates" / "tenerife" / "privacy.html").read_text(encoding="utf-8")
        for phrase in OLD_MODEL["ru"]:
            self.assertNotIn(phrase, ru, ("ru", phrase))
        self.assertIn(VERSION["ru"], ru)

    def test_legal_meta_has_no_waiting_list(self):
        data = json.loads((BUILD / "i18n_strings.json").read_text(encoding="utf-8"))
        for loc in ("en", "es", "de", "fr"):
            meta = data[loc]["legal"]["meta"]["privacy"].lower()
            self.assertNotIn("waiting", meta, loc)
            self.assertNotIn("warteliste", meta, loc)
            self.assertNotIn("lista de espera", meta, loc)
            self.assertNotIn("liste d'attente", meta, loc)

    def test_version_is_in_the_published_privacy_only(self):
        for loc in LOCALES:
            self.assertIn(VERSION[loc], page(loc))
            impressum = page(loc, "impressum")
            self.assertNotIn(VERSION[loc], impressum, loc)   # версия относится к privacy


class ConsentNoWaitingListTest(unittest.TestCase):
    def test_json_and_ru_canon_use_the_new_consent(self):
        data = json.loads((BUILD / "i18n_strings.json").read_text(encoding="utf-8"))
        for loc in ("en", "es", "de", "fr"):
            consent = data[loc]["form"]["consent"]
            self.assertIn(NEW_CONSENT[loc], consent, loc)
            self.assertNotIn(OLD_CONSENT[loc], consent, loc)
        self.assertIn(NEW_CONSENT["ru"], build_v3.RU_FORM_UI["consent"])

    def test_every_form_carries_the_new_consent(self):
        for loc in LOCALES:
            text = page(loc, "index")
            self.assertIn(NEW_CONSENT[loc], text, loc)
            self.assertNotIn(OLD_CONSENT[loc], text, loc)

    def test_locale_form_copies_use_the_new_consent(self):
        for loc in ("en", "es", "de", "fr"):
            md = (BUILD / f"copy_{loc}" / "17_forma.md").read_text(encoding="utf-8")
            self.assertIn(NEW_CONSENT[loc], md, loc)
            self.assertNotIn(OLD_CONSENT[loc], md, loc)
        ru = (BUILD / "copy_v3" / "17_forma.md").read_text(encoding="utf-8")
        self.assertIn(NEW_CONSENT["ru"], ru)
        self.assertNotIn(OLD_CONSENT["ru"], ru)


class EnglishHomeApiTest(unittest.TestCase):
    def setUp(self):
        import importlib
        import tempfile
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

    def test_english_home_errors_are_english(self):
        """EN-главная (/tenerife/) не должна падать в RU: без language ответ по page -> EN."""
        r = self.client.post("/api/tenerife/waitlist", json={
            "name": "", "contact": "qa@example.com", "consent": True, "page": "/tenerife/"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], self.tenerife.FORM_MSG_BY_LANG["en"]["name"])


if __name__ == "__main__":
    unittest.main()
