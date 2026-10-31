"""Keep e-mail addresses on /tenerife/ readable without JavaScript (31.10.2026).

Cloudflare Email Obfuscation (zone setting, stays ON) rewrites every address and
mailto: link into /cdn-cgi/l/email-protection#..., which only decodes with JS and
404s without it. Cloudflare skips anything between <!--email_off--> and
<!--/email_off-->, so every address / mailto link on the Tenerife pages is wrapped
in those markers. Do not run the pages through an HTML minifier that strips
comments: tests/test_tenerife_site.py asserts the markers reach the response.

What Cloudflare rewrites (and therefore what wrap() protects / unprotected() reports):
  * <a … href=mailto:…>…</a> — any quoting: href="…", href='…', href = "…", href=unquoted;
    the whole element (link + visible text) is wrapped;
  * addresses in text nodes.
Left alone (Cloudflare does not touch them; markers there would corrupt the page):
  other tag attributes (<meta content>, <input placeholder>, srcset …), HTML comments,
  <head>, and the raw-text / RCDATA elements <script> (incl. JSON-LD), <style>, <textarea>, <title>.
"logo@2x.png"-style file names are not e-mail addresses.
wrap() raises EmailOffError rather than emit a marker inside a tag/attribute (QA 2026-10-31 -03).
Attribute values are HTML-unescaped before the scheme check, as the browser does: href="&#109;ailto:…" is a
mailto link too (QA 2026-10-31 pr21 -40). mailto_targets() / mailto_form_actions() are the allowlist helpers
for the tests: every address a mailto URI would write to (path, ?to=, ?cc=, ?bcc=), any quoting / entities.
"""
import html as _html
import re
from urllib.parse import parse_qsl, unquote

ON, OFF = "<!--email_off-->", "<!--/email_off-->"
_IMG_SUFFIX = r"(?!\d+(?:\.\d+)?x\.(?:png|jpe?g|webp|gif|svg|avif)\b)"  # logo@2x.png, icon@1.5x.webp
EMAIL = r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@" + _IMG_SUFFIX + r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w-])"
_EMAIL = re.compile(EMAIL)
_BLOCK = re.compile(re.escape(ON) + r".*?" + re.escape(OFF), re.S)
# a start tag: quoted attribute values may contain ">"
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
_A_BODY = r"(?:(?!<a\b).)*?</a\s*>"  # up to its own </a>; a link is never closed by a later link's </a>
_TOKEN = re.compile(
    r"(?P<comment><!--.*?-->)"
    r"|(?P<raw><(?P<rawtag>script|style|textarea|title|head)\b" + _ATTRS + r">.*?</(?P=rawtag)\s*>)"
    r"|(?P<a><a\b(?P<aattrs>" + _ATTRS + r")>" + _A_BODY + ")"
    r"|(?P<tag></?[A-Za-z!?]" + _ATTRS + r">)"
    r"|(?P<email>" + EMAIL + r")",
    re.S | re.I,
)
_ATTR = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")


class EmailOffError(ValueError):
    """The page cannot be protected safely (marker would land inside a tag / attribute)."""


def _attr(attrs, wanted):
    for name, value in _ATTR.findall(attrs or ""):
        if name.lower() == wanted:
            value = value.strip()
            if value[:1] in "\"'" and value[-1:] == value[:1]:
                value = value[1:-1]
            return value.strip()
    return ""


def _href(attrs):
    return _attr(attrs, "href")


# the browser drops ASCII tab / LF / CR anywhere in a URL and leading C0 controls / spaces
_URL_DROP = re.compile(r"[\t\n\r]")


def _scheme_is_mailto(value):
    v = _URL_DROP.sub("", _html.unescape(value or "")).lstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e"
                                                               "\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19"
                                                               "\x1a\x1b\x1c\x1d\x1e\x1f ")
    return v.lower().startswith("mailto:")


def _is_mailto_link(m):
    return _scheme_is_mailto(_href(m.group("aattrs")))


# "mailto:" with optional tab / LF / CR between the letters (dropped by the URL parser), after unescaping
_MAILTO = re.compile("".join(re.escape(c) + r"[\t\n\r]*" for c in "mailto") + r":([^\"'\s<>`]*)", re.I)
_ADDR_HEADERS = ("to", "cc", "bcc")


def mailto_targets(page):
    """Lower-cased addresses any mailto: URI on the page would write to (QA 2026-10-31 pr21 -40).

    The page is HTML-unescaped first (&#109;ailto:, &amp;cc=), the URI path and the to / cc / bcc header fields
    (RFC 6068, comma-separated, percent-encoded, any case) all count. An empty result for a mailto: with no
    address at all is reported as "" so a bare "mailto:?subject=x" is visible to the caller too."""
    found = set()
    for m in _MAILTO.finditer(_html.unescape(page or "")):
        uri = _URL_DROP.sub("", m.group(1))
        path, _, query = uri.partition("?")
        addrs = [unquote(a) for a in path.split(",")]
        for key, value in parse_qsl(query, keep_blank_values=True):
            if key.strip().lower() in _ADDR_HEADERS:
                addrs += value.split(",")
        addrs = [a.strip().lower() for a in addrs if a.strip()]
        found.update(addrs or [""])
    return found


_START_TAG = re.compile(r"<[A-Za-z][^\s/>]*(" + _ATTRS + r")>", re.S)


def mailto_form_actions(page):
    """action= / formaction= values that submit via mailto (any quoting, case, entities, tabs)."""
    found = []
    for t in _START_TAG.finditer(page or ""):
        for name in ("action", "formaction"):
            value = _attr(t.group(1), name)
            if value and _scheme_is_mailto(value):
                found.append(value)
    return found


def _outside_blocks(html):
    """Yield (is_protected, chunk) pieces of html, split on email_off blocks."""
    last = 0
    for m in _BLOCK.finditer(html):
        yield False, html[last:m.start()]
        yield True, m.group(0)
        last = m.end()
    yield False, html[last:]


def _check_markers_outside_tags(html):
    for m in _TOKEN.finditer(html):
        piece = m.group("tag") or (m.group("a") and re.match(r"<a\b" + _ATTRS + ">", m.group("a"), re.I | re.S).group(0))
        if piece and ("email_off-->" in piece):
            raise EmailOffError(f"email_off marker inside a tag: {piece[:120]!r}")


def wrap(html):
    """Wrap every mailto link / text address not yet inside email_off markers. Idempotent."""
    def rep(m):
        if m.group("a"):
            if _is_mailto_link(m):
                return ON + m.group(0) + OFF
            # a non-mailto link: protect addresses in its text, never inside its start tag
            start = re.match(r"<a\b" + _ATTRS + ">", m.group(0), re.I | re.S).group(0)
            rest = m.group(0)[len(start):]
            return start + _EMAIL.sub(lambda e: ON + e.group(0) + OFF, rest)
        if m.group("email"):
            return ON + m.group(0) + OFF
        return m.group(0)  # comment, raw-text element, other tag: untouched
    out = "".join(chunk if done else _TOKEN.sub(rep, chunk) for done, chunk in _outside_blocks(html))
    _check_markers_outside_tags(out)
    return out


def unprotected(html):
    """mailto links / text addresses that Cloudflare would still obfuscate (outside the markers)."""
    found = []
    for done, chunk in _outside_blocks(html):
        if done:
            continue
        for m in _TOKEN.finditer(chunk):
            if m.group("a"):
                if _is_mailto_link(m):
                    found.append(_href(m.group("aattrs")))
                else:
                    found += _EMAIL.findall(m.group(0)[len(re.match(r"<a\b" + _ATTRS + ">", m.group(0), re.I | re.S).group(0)):])
            elif m.group("email"):
                found.append(m.group(0))
        # an <a> start tag without </a> (cannot be wrapped as a whole)
        for t in re.finditer(r"<a\b(" + _ATTRS + r")>", chunk, re.I | re.S):
            if _scheme_is_mailto(_href(t.group(1))) and not re.match(
                    _A_BODY, chunk[t.end():], re.I | re.S):
                found.append(_href(t.group(1)))
    return found
