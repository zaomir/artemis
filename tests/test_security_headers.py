"""nginx security headers / www / static cache (QA A-08, B-04, 31.10.2026) and the deploy test gate."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def csp_map():
    txt = (DEPLOY / "nginx-artemis-security-map.conf").read_text(encoding="utf-8")
    block = txt[txt.index("map $uri $artemis_csp"):]
    block = block[:block.index("}")]
    return dict(re.findall(r'^\s*(default|~\S+)\s+"([^"]*)";', block, re.M))


class SecurityHeadersTest(unittest.TestCase):
    def test_crete_default_csp_and_framing(self):
        crete = csp_map()["default"]
        self.assertIn("frame-ancestors 'self'", crete)
        self.assertIn("object-src 'none'", crete)
        self.assertIn("base-uri 'self'", crete)
        self.assertIn("form-action 'self'", crete)
        # Crete templates use inline <script>/onclick and inline styles -> policy must allow them
        html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("onclick=", html)
        self.assertRegex(crete, r"script-src [^;]*'unsafe-inline'")
        self.assertRegex(crete, r"style-src [^;]*'unsafe-inline'")
        self.assertNotIn("https://fonts.", html)       # nothing external the policy would block

    def test_tenerife_policy_unchanged_strict(self):
        ten = csp_map()["~^/tenerife/"]
        self.assertIn("frame-ancestors 'none'", ten)
        self.assertNotIn("unsafe-inline", ten)

    def test_snippet_has_xfo_and_permissions_policy(self):
        s = (DEPLOY / "nginx-artemis-security-headers.conf").read_text(encoding="utf-8")
        self.assertIn("add_header X-Frame-Options $artemis_xfo always;", s)
        self.assertIn('add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;', s)
        m = (DEPLOY / "nginx-artemis-security-map.conf").read_text(encoding="utf-8")
        self.assertIn('default "SAMEORIGIN";', m)

    def test_site_conf_www_redirect_and_single_static_cache_control(self):
        s = (DEPLOY / "nginx-artemisresort.com.origin.conf").read_text(encoding="utf-8")
        self.assertIn("server_name www.artemisresort.com;", s)
        self.assertIn("return 301 https://artemisresort.com$request_uri;", s)
        static = s[s.index("location /static/"):]
        static = static[:static.index("}")]
        self.assertEqual(static.count("Cache-Control"), 1)
        self.assertNotIn("expires", static)
        self.assertNotIn("no-store", static)


class DeployScriptTest(unittest.TestCase):
    def test_tests_run_before_prod_switch(self):
        s = (DEPLOY / "artemis-deploy.sh").read_text(encoding="utf-8")
        self.assertIn("-m unittest discover -s tests", s)
        self.assertLess(s.index("if ! run_tests; then"), s.index('merge --ff-only -q "origin/${BRANCH}"'))


if __name__ == "__main__":
    unittest.main()
