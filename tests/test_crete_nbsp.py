"""QA ARTEMIS-QA-20261031-33 + copy round 2: non-breaking spaces from the copy-writer reach the page untouched.

U+00A0 (NBSP) and U+202F (narrow NBSP) are typography, not layout: French « : », « ; », « ? », « ! »,
thousands in 3 000 000 €, «3 млн €». legal_i18n.parse used str.split(), which treats them as whitespace
and silently replaced them with ordinary spaces. The texts must be byte-identical to the reviewed files.

Optional cross-check against the copy-writer's originals (outside the repo, skipped when unset):
    ARTEMIS_LEGAL_SRC_DIR=/path/to/legal_translations   (artemis-<page>-<lang>.md)
    ARTEMIS_UI_REVIEW_MD=/path/to/artemis-ui-strings-for-review-reviewed.md
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt
LANGS = ("ru", "es", "fr")
PAGES = ("privacy", "terms")
LEGAL = ROOT / "app" / "legal_translations"
T = {l: json.loads((ROOT / "app" / "translations" / f"{l}.json").read_text(encoding="utf-8"))
     for l in ("en",) + LANGS}
NBSP, NNBSP = "\u00a0", "\u202f"
_COMMENT = re.compile(r"<!--.*?-->", re.S)

# (NBSP, narrow NBSP) per UI string, as in the reviewed copy (artemis-ui-strings-for-review-reviewed.md,
# round 2). Every other key of ru/es/fr/en.json has none.
UI_NBSP = {
    ("ru", "form_err_amount"): (3, 0), ("es", "form_err_amount"): (2, 0), ("fr", "form_err_amount"): (1, 2),
    ("ru", "ph_amount"): (3, 0), ("es", "ph_amount"): (1, 0), ("fr", "ph_amount"): (1, 2),
    ("ru", "enquiry_intro"): (2, 0), ("es", "enquiry_intro"): (1, 0), ("fr", "enquiry_intro"): (1, 0),
    ("fr", "enquiry_warn"): (0, 1), ("fr", "legal_body_pending"): (0, 1), ("fr", "privacy_recipients"): (1, 0),
}


def counts(s):
    return s.count(NBSP), s.count(NNBSP)


def html_counts(h):
    """NBSP / narrow NBSP in served HTML, whether sent as characters or as entities."""
    return (h.count(NBSP) + h.count("&nbsp;") + h.count("&#160;") + h.count("&#xa0;"),
            h.count(NNBSP) + h.count("&#8239;") + h.count("&#x202f;"))


def source_text(page, lang):
    """The translation file without its HTML comments (the part that reaches the page)."""
    return _COMMENT.sub("", (LEGAL / f"{page}.{lang}.md").read_text(encoding="utf-8"))


class ParserKeepsNbspTest(unittest.TestCase):
    """QA-33: parse() must not turn U+00A0 / U+202F into ordinary spaces."""

    def test_french_punctuation_nbsp_preserved(self):
        import legal_i18n
        src = ("<!-- @title -->\nConfidentialit\u00e9\u00a0?\n<!-- @body -->\n"
               "Destinataire\u00a0: Google\u00a0; montant\u00a0: 3\u202f000\u202f000\u00a0\u20ac\n"
               "vraiment\u00a0? oui\u00a0!\n\n  Second   paragraphe\u00a0!  \n"
               "<!-- @recipients -->\nDestinataire et sous-traitant des copies des demandes\u00a0: Google.\n")
        out = legal_i18n.parse(src)
        self.assertEqual(out["title"], "Confidentialit\u00e9\u00a0?")
        self.assertEqual(out["body"], [
            "Destinataire\u00a0: Google\u00a0; montant\u00a0: 3\u202f000\u202f000\u00a0\u20ac vraiment\u00a0? oui\u00a0!",
            "Second paragraphe\u00a0!",
        ])
        self.assertEqual(out["recipients"], "Destinataire et sous-traitant des copies des demandes\u00a0: Google.")
        joined = out["title"] + "".join(out["body"]) + out["recipients"]
        for mark in (":", ";", "?", "!"):
            self.assertIn("\u00a0" + mark, joined, mark)
            self.assertNotIn(" " + mark, joined, mark)       # no ordinary space crept in
        self.assertEqual(counts(joined), counts(src))       # (9, 2): nothing lost

    def test_nbsp_is_not_a_paragraph_break_or_edge_trim(self):
        import legal_i18n
        self.assertEqual(legal_i18n.parse("<!-- @body -->\n\u00a0a\u00a0\n\u202fb\u202f"),
                         {"body": ["\u00a0a\u00a0 \u202fb\u202f"]})
        # ASCII layout whitespace is still collapsed, as before
        self.assertEqual(legal_i18n.parse("<!-- @body -->\n  a \t b\r\n\n \t\nc  "), {"body": ["a b", "c"]})


class LegalTranslationsByteMatchTest(unittest.TestCase):
    """The shipped legal translations keep every NBSP from the file, in parse() and in the served page."""

    def setUp(self):
        import app as artemis_app
        self.tmp = tempfile.TemporaryDirectory()
        artemis_app.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = artemis_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_keeps_source_nbsp_count(self):
        import legal_i18n
        seen = 0
        for page in PAGES:
            for lang in LANGS:
                li = legal_i18n.load(page, lang)
                text = (li.get("title") or "") + "".join(li["body"]) + (li.get("recipients") or "")
                src = source_text(page, lang)
                self.assertEqual(counts(text), counts(src), (page, lang))
                for para in li["body"]:          # every paragraph is a verbatim run of the file (up to line wraps)
                    self.assertIn(para, " ".join(src.split("\n")), (page, lang))
                seen += sum(counts(src))
        self.assertGreater(seen, 0)              # the FR privacy file has «demandes : Google»

    def test_served_pages_keep_nbsp(self):
        import legal_i18n
        for page in PAGES:
            for lang in LANGS:
                h = self.client.get(f"/{lang}/{page}/").get_data(as_text=True)
                li = legal_i18n.load(page, lang)
                text = (li.get("title") or "") + "".join(li["body"]) + (li.get("recipients") or "")
                exp = counts(text)
                if page == "privacy" and not li.get("recipients"):
                    exp = tuple(a + b for a, b in zip(exp, counts(T[lang]["privacy_recipients"])))
                self.assertEqual(html_counts(h), exp, (page, lang))
        h = self.client.get("/fr/privacy/").get_data(as_text=True)
        self.assertIn("des copies des demandes\u00a0: Google", h)
        self.assertNotIn("des copies des demandes : Google", h)

    def test_pending_note_keeps_nbsp(self):
        import legal_i18n
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(legal_i18n, "LEGAL_DIR", Path(empty)):
            for lang in LANGS:
                h = self.client.get(f"/{lang}/terms/").get_data(as_text=True)
                self.assertIn(T[lang]["legal_body_pending"], h, lang)
                self.assertEqual(html_counts(h), counts(T[lang]["legal_body_pending"]), lang)

    @unittest.skipUnless(os.environ.get("ARTEMIS_LEGAL_SRC_DIR"), "copy-writer originals not available")
    def test_files_byte_identical_to_copywriter(self):
        src = Path(os.environ["ARTEMIS_LEGAL_SRC_DIR"])
        for page in PAGES:
            for lang in LANGS:
                self.assertEqual((LEGAL / f"{page}.{lang}.md").read_bytes(),
                                 (src / f"artemis-{page}-{lang}.md").read_bytes(), (page, lang))


class UiStringsNbspTest(unittest.TestCase):
    """Reviewed UI strings: NBSP counts match the reviewed copy and survive rendering of /<lang>/."""

    def setUp(self):
        import app as artemis_app
        self.tmp = tempfile.TemporaryDirectory()
        artemis_app.DB = os.path.join(self.tmp.name, "leads.db")
        self.client = artemis_app.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_nbsp_counts(self):
        for lang, t in T.items():
            for key, value in t.items():
                if isinstance(value, str):
                    self.assertEqual(counts(value), UI_NBSP.get((lang, key), (0, 0)), (lang, key))

    def test_rendered_home_keeps_nbsp(self):
        from markupsafe import escape
        for lang in LANGS:
            h = self.client.get(f"/{lang}/").get_data(as_text=True)
            for key in ("enquiry_intro", "enquiry_warn", "enquiry_title", "enquiry_label", "form_type",
                        "form_consent", "form_success", "type_investor", "type_lender_finance_adviser",
                        "type_general_professional"):
                self.assertIn(str(escape(T[lang][key])), h, (lang, key))
            self.assertIn(f'placeholder="{escape(T[lang]["ph_amount"])}"', h, lang)
            self.assertIn(f'placeholder="{escape(T[lang]["ph_message"])}"', h, lang)
            js = re.search(r"\bamount: (\"(?:[^\"\\]|\\.)*\")", h).group(1)
            self.assertEqual(json.loads(js), T[lang]["form_err_amount"], lang)      # JSON-escaped, same string

    @unittest.skipUnless(os.environ.get("ARTEMIS_UI_REVIEW_MD"), "reviewed UI strings file not available")
    def test_json_matches_reviewed_table(self):
        rows = 0
        for line in Path(os.environ["ARTEMIS_UI_REVIEW_MD"]).read_text(encoding="utf-8").split("\n"):
            if not line.startswith("| `"):
                continue
            cells = line.split("|")[1:-1]
            key = re.match(r" `(\w+)`", cells[0]).group(1)
            for lang, cell in zip(("en", "ru", "es", "fr"), cells[1:5]):
                self.assertEqual(T[lang][key], cell[1:-1], (lang, key))       # strip only the table padding
            rows += 1
        self.assertEqual(rows, 42)


if __name__ == "__main__":
    unittest.main()
