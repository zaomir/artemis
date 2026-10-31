"""Keep e-mail addresses on /tenerife/ readable without JavaScript (31.10.2026).

Cloudflare Email Obfuscation (zone setting, stays ON) rewrites every address and
mailto: link into /cdn-cgi/l/email-protection#..., which only decodes with JS and
404s without it. Cloudflare skips anything between <!--email_off--> and
<!--/email_off-->, so every address / mailto link on the Tenerife pages is wrapped
in those markers. Do not run the pages through an HTML minifier that strips
comments: tests/test_tenerife_site.py asserts the markers reach the response.
"""
import re

ON, OFF = "<!--email_off-->", "<!--/email_off-->"
EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
_BLOCK = re.compile(re.escape(ON) + r".*?" + re.escape(OFF), re.S)
# 1: <a href="mailto:..">..</a>  2: any other tag (attributes are left alone)  3: bare address in text
_TOKEN = re.compile(r'(<a\b[^>]*\bhref="mailto:[^"]*"[^>]*>.*?</a>)|(<[^>]*>)|(' + EMAIL + r")", re.S | re.I)


def _outside_blocks(html):
    """Yield (is_protected, chunk) pieces of html, split on email_off blocks."""
    last = 0
    for m in _BLOCK.finditer(html):
        yield False, html[last:m.start()]
        yield True, m.group(0)
        last = m.end()
    yield False, html[last:]


def wrap(html):
    """Wrap every mailto link / bare address not yet inside email_off markers. Idempotent."""
    def rep(m):
        if m.group(2):
            return m.group(0)
        return ON + m.group(0) + OFF
    return "".join(chunk if done else _TOKEN.sub(rep, chunk) for done, chunk in _outside_blocks(html))


def unprotected(html):
    """Addresses / mailto links that Cloudflare would still obfuscate (outside the markers)."""
    found = []
    for done, chunk in _outside_blocks(html):
        if not done:
            found += re.findall(r"mailto:[^\"'\s>]*|" + EMAIL, chunk)
    return found
