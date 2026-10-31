"""Crete privacy (/en|ru|es|fr/privacy/): Google (Gmail / Google Workspace) named as recipient and
processor of enquiry copies (relay to info@artemisresort.com), in the language of each page;
the original privacy text is unchanged."""
import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

ORIGINAL = ("We process enquiry contact details (name, work email, organisation, role, enquiry type, planned amount"
            " and message) to review and respond. Contact INFO@ARTEMISRESORT.COM for privacy requests.")
MARKER = {"en": "Recipient and processor of enquiry copies", "ru": "Получатель и обработчик копий заявок",
          "es": "Destinatario y encargado del tratamiento", "fr": "Destinataire et sous-traitant"}


class CretePrivacyGoogleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as artemis_app  # noqa: E402
        cls.client = importlib.reload(artemis_app).app.test_client()

    def test_google_recipient_in_every_language(self):
        for lang, marker in MARKER.items():
            r = self.client.get(f"/{lang}/privacy/")
            self.assertEqual(r.status_code, 200, lang)
            h = r.get_data(as_text=True)
            self.assertIn(marker, h, lang)
            self.assertIn("Google (Gmail, Google Workspace)", h, lang)
            self.assertIn("info@artemisresort.com", h, lang)
            import legal_i18n
            if legal_i18n.load("privacy", lang) is None:   # no reviewed drop-in translation (A-06) yet
                self.assertIn(ORIGINAL, h, lang)        # rest of the page unchanged

    def test_terms_untouched(self):
        for lang in MARKER:
            self.assertNotIn("Google", self.client.get(f"/{lang}/terms/").get_data(as_text=True), lang)

    def test_body_unchanged_in_translations(self):
        for lang in MARKER:
            t = json.loads((ROOT / "app" / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertEqual(t["privacy_body"], ORIGINAL, lang)


if __name__ == "__main__":
    unittest.main()
