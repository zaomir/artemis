"""scripts/tenerife_site_build/email_off.py edge cases (QA 2026-10-31 pr19 -02, -03, -04) and the build gate."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "tenerife_site_build"
sys.path.insert(0, str(BUILD))

from email_off import OFF, ON, EmailOffError, unprotected, wrap  # noqa: E402

A = "x@artemisresort.com"


def boxed(s):
    return ON + s + OFF


class WrapRawTextTest(unittest.TestCase):
    """-02: never insert markers into raw-text / RCDATA elements or <head>."""

    def test_untouched(self):
        for html in (f'<script type="application/ld+json">{{"email":"{A}"}}</script>',
                     f"<script>var m = 'mailto:{A}';</script>",
                     f"<style>/* {A} */</style>",
                     f"<textarea>{A}</textarea>",
                     f"<TITLE>{A}</TITLE>",
                     f'<head><meta name="author" content="{A}"><title>{A}</title></head>'):
            self.assertEqual(wrap(html), html, html)
            self.assertEqual(unprotected(html), [], html)

    def test_body_after_script_still_wrapped(self):
        html = f"<script>1</script><p>{A}</p>"
        self.assertEqual(wrap(html), f"<script>1</script><p>{boxed(A)}</p>")


class WrapHrefVariantsTest(unittest.TestCase):
    """-03: every href quoting is recognised; a marker never lands inside a tag."""

    def test_quoting_variants(self):
        for a in (f"<a href='mailto:{A}'>write</a>",
                  f'<a href = "mailto:{A}">write</a>',
                  f"<a href=mailto:{A}>write</a>",
                  f'<A class="m" HREF="MAILTO:{A}?subject=Hi">{A}</A>',
                  f'<a title="a>b" href="mailto:{A}">{A}</a>',
                  f"<a data-x='>' href='mailto:{A}'>w</a>"):
            self.assertEqual(unprotected(a) != [], True, a)
            self.assertEqual(wrap(a), boxed(a), a)
            self.assertEqual(unprotected(wrap(a)), [], a)
            self.assertEqual(wrap(wrap(a)), wrap(a), a)

    def test_marker_never_inside_attribute(self):
        html = f'<a title="see {A} >" href="/x">{A}</a>'
        out = wrap(html)
        self.assertTrue(out.startswith(f'<a title="see {A} >" href="/x">'), out)
        self.assertEqual(out.count(ON), 1)

    def test_unclosed_mailto_link_is_reported(self):
        html = f'<p><a href="mailto:{A}">write</p>'
        self.assertEqual(wrap(html), html)            # cannot be wrapped as a whole …
        self.assertEqual(unprotected(html), [f"mailto:{A}"])   # … so the build must fail

    def test_guard_raises(self):
        # the last line of defence in wrap(): a marker inside a start tag is an error, not output
        import email_off
        for bad in ('<a href="mailto:' + ON + A + OFF + '">w</a>', '<img alt="' + ON + '">'):
            with self.assertRaises(EmailOffError):
                email_off._check_markers_outside_tags(bad)


class UnprotectedFalsePositivesTest(unittest.TestCase):
    """-04: things Cloudflare does not rewrite are not reported (and not wrapped)."""

    def test_meta(self):
        html = f'<meta name="author" content="{A}"><meta property="og:email" content="{A}">'
        self.assertEqual(unprotected(html), [])
        self.assertEqual(wrap(html), html)

    def test_srcset_retina_file_names(self):
        html = ('<img src="/img/logo.png" srcset="/img/logo@2x.png 2x, /img/logo@3x.webp 3x" alt="">'
                "<p>see logo@2x.png and icon@1.5x.webp</p>")
        self.assertEqual(unprotected(html), [])
        self.assertEqual(wrap(html), html)

    def test_html_comments(self):
        html = f"<!-- contact {A} --><!--\n mailto:{A}\n-->"
        self.assertEqual(unprotected(html), [])
        self.assertEqual(wrap(html), html)

    def test_other_attributes(self):
        html = f'<input placeholder="{A}"><img alt="{A}"><button formaction="/x" title="{A}">'
        self.assertEqual(unprotected(html), [])
        self.assertEqual(wrap(html), html)

    def test_real_leaks_still_found(self):
        self.assertEqual(unprotected(f"<p>{A}</p>"), [A])
        self.assertEqual(unprotected(f"<p>{boxed(A)} and y@artemisresort.com</p>"), ["y@artemisresort.com"])
        self.assertEqual(unprotected(f'<a href="/x">{A}</a>'), [A])


class BuildGateTest(unittest.TestCase):
    """-03: build.py exits non-zero (and writes nothing) when an address stays outside the markers."""

    def run_build(self, body):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        src, repo = tmp / "src", tmp / "repo"
        src.mkdir()
        (src / "style.css").write_text("body{margin:0}\n", encoding="utf-8")
        (src / "index.html").write_text(
            "<!DOCTYPE html><html lang=\"ru\"><head><title>T</title></head><body>"
            f"<main>{body}</main><footer>x</footer></body></html>", encoding="utf-8")
        r = subprocess.run([sys.executable, str(BUILD / "build.py"), str(src), str(repo), "--allow-missing"],
                           capture_output=True, text=True, timeout=60)
        return r, repo / "app" / "tenerife_site" / "ru" / "index.html"

    def test_ok_page_builds(self):
        r, out = self.run_build(f"<p>{A}</p>")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(boxed(A), out.read_text(encoding="utf-8"))

    def test_unprotected_mailto_fails_build(self):
        r, out = self.run_build(f'<p><a href="mailto:{A}">write</p>')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL index.html", r.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
