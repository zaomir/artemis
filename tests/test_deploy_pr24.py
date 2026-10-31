"""PR #24 QA fixes (31.10.2026): no token in git URL/argv, nginx 429 JSON, log level, CF-Connecting-IP."""
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def read(name):
    return (DEPLOY / name).read_text(encoding="utf-8")


class SetupServerTokenTest(unittest.TestCase):
    def test_no_token_in_remote_url_or_argv(self):
        s = read("setup_server.sh")
        self.assertIn("set -euo pipefail", s)
        self.assertNotRegex(s, r"https://\$\{?GITHUB_TOKEN")
        self.assertNotRegex(s, r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")
        self.assertIn('REPO_URL="https://github.com/zaomir/artemis.git"', s)
        self.assertIn("GIT_ASKPASS=", s)
        self.assertIn('git -C "$SITE_DIR" remote set-url origin "$REPO_URL"', s)

    def test_token_guard_only_inside_git_helper(self):
        s = read("setup_server.sh")
        fn = s[s.index("git_with_token() {"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertEqual(s.count("${GITHUB_TOKEN:?"), 1)
        self.assertIn("${GITHUB_TOKEN:?", fn)


class NginxEnquiryLimitTest(unittest.TestCase):
    def test_429_json_and_log_level(self):
        s = read("nginx-artemisresort.com.origin.conf")
        loc = s[s.index("location = /api/enquiry"):]
        loc = loc[:loc.index("}")]
        self.assertIn("limit_req_log_level warn;", loc)
        self.assertIn("error_page 429 = @artemis_enquiry_429;", loc)
        self.assertIn("""return 429 '{"ok":false,"code":"rate_limited"}';""", s)
        self.assertGreaterEqual(s.count("server_tokens off;"), 3)


class LegacyTemplatesRealIpTest(unittest.TestCase):
    def test_cf_connecting_ip_overwritten(self):
        for name in ("install_artemis.sh", "setup_server.sh"):
            s = read(name)
            self.assertRegex(s, r"proxy_set_header CF-Connecting-IP \\?\$remote_addr;", name)
            self.assertIn("cloudflare-realip", s, name)


if __name__ == "__main__":
    unittest.main()
