"""Founder layout brief: photographs explain a section; only portfolio cases form a strip."""
import unittest
from pathlib import Path

from test_tenerife_investors_architecture import Document, has_class

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "app/tenerife_site"
LANGUAGES = ("en", "es", "de", "fr", "ru")


def page(locale, slug):
    path = SITE / ("" if locale == "en" else locale) / (slug + ".html")
    return Document(path.read_text()).root


def owner(node, tag):
    while node and node.tag != tag:
        node = node.parent
    return node


class ProfileLayoutTest(unittest.TestCase):
    def test_every_personal_photo_accompanies_its_own_subject(self):
        expected = {
            "simon": {"introduction": "h1", "owner-development": "s1", "permits": "s3", "site-delivery": "s4"},
            "boris": {"introduction": "h1", "structural-check": "s1", "roof-and-solar": "s4", "drawings-and-coordination": "s6"},
        }
        for locale in LANGUAGES:
            for person, subjects in expected.items():
                doc = page(locale, person)
                photos = [n for n in doc.nodes("figure") if n.attrs.get("data-person-photo") == person]
                self.assertEqual(len(photos), 4, (locale, person))
                self.assertEqual({n.attrs["data-photo-context"] for n in photos}, set(subjects))
                sources = []
                for figure in photos:
                    section = owner(figure, "section")
                    heading = section.by_id(subjects[figure.attrs["data-photo-context"]])
                    self.assertIsNotNone(heading, (locale, person, figure.attrs))
                    paragraphs = list(section.nodes("p"))
                    self.assertTrue(paragraphs, (locale, person))
                    self.assertGreater(sum(len(n.text()) for n in paragraphs), 80)
                    image = next(figure.nodes("img"))
                    sources.append(image.attrs["src"])
                    self.assertTrue(image.attrs.get("alt"))
                    if locale != "ru":
                        self.assertNotRegex(image.attrs["alt"], r"[А-Яа-яЁё]")
                self.assertEqual(len(set(sources)), 4)
                self.assertFalse(any(has_class(n, "tperson") for n in doc.nodes()))

    def test_only_cases_have_photo_strips_and_product_images_have_prose(self):
        for locale in LANGUAGES:
            directory = SITE / ("" if locale == "en" else locale)
            for path in directory.glob("*.html"):
                doc = Document(path.read_text()).root
                for container in doc.nodes():
                    if has_class(container, "frames--pair"):
                        self.assertLessEqual(len(list(container.nodes("figure"))), 1, path)
                for photo in (n for n in doc.nodes("figure") if "data-person-photo" in n.attrs):
                    self.assertEqual(len(list(owner(photo, "section").nodes("figure"))), 1, path)
            product = page(locale, "producto")
            panels = [n for n in product.nodes() if has_class(n, "illustrated-panel")]
            self.assertEqual(len(panels), 2)
            for panel in panels:
                self.assertEqual(len(list(panel.nodes("figure"))), 1)
                self.assertTrue(list(panel.nodes("p")))
            for person in ("simon", "boris"):
                cases = [n for n in page(locale, person).nodes() if has_class(n, "cases__track")]
                self.assertEqual(len(cases), 1)
                self.assertEqual(len([n for n in cases[0].nodes() if has_class(n, "case")]), 4)

    def test_embedded_calculator_has_one_section_and_keeps_its_tool_contract(self):
        for locale in LANGUAGES:
            investor = page(locale, "inversores")
            calc = investor.by_id("calc")
            self.assertEqual(calc.tag, "div")
            self.assertTrue(has_class(calc, "calc-sec--embedded"))
            self.assertEqual(owner(calc, "section").attrs["aria-labelledby"], "calculate")
            self.assertIsNotNone(owner(calc, "section").by_id("calculate"))
            self.assertEqual(list(owner(calc, "section").nodes("figure")), [])
            self.assertEqual(page(locale, "calculadora").by_id("calc").tag, "section")
            self.assertEqual({n.attrs.get("name") for n in calc.nodes("input")}, {"type", "m2"})
            self.assertIsNotNone(investor.by_id("wl-form"))


if __name__ == "__main__":
    unittest.main()
