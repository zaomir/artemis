"""PR #24 QA fixes (31.10.2026): no token in git URL/argv, nginx 429 JSON, log level, CF-Connecting-IP."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SNIPPET_REL = "nginx-snippets/cloudflare-realip.conf"
SNIPPET_DST = "/etc/nginx/snippets/cloudflare-realip.conf"

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


class RealIpSnippetInstallTest(unittest.TestCase):
    """QA PR24-07: the legacy installers install the realip snippet themselves and include it without a glob."""

    def test_no_glob_include_anywhere(self):
        for name in ("install_artemis.sh", "setup_server.sh", "nginx-artemisresort.com.origin.conf"):
            s = read(name)
            includes = re.findall(r"^\s*include\s+(\S*cloudflare-realip\S*);", s, re.M)
            self.assertTrue(includes, name)
            for inc in includes:
                self.assertEqual(inc, SNIPPET_DST, name)
                self.assertNotIn("*", inc, name)

    def test_install_artemis_writes_snippet(self):
        s = read("install_artemis.sh")
        start = s.index("REALIP_SNIPPET=")
        end = s.index("\nfi\n", start) + len("\nfi\n")
        block = s[start:end]
        self.assertIn("exit 1", block)
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "etc/nginx/snippets/cloudflare-realip.conf"
            block = block.replace("/etc/nginx/snippets", str(dst.parent))
            r = subprocess.run(["bash", "-euc", block], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(dst.read_text(encoding="utf-8"), read(SNIPPET_REL))
            self.assertEqual(dst.stat().st_mode & 0o777, 0o644)
        # the snippet is installed before the nginx site config is written
        self.assertLess(s.index('cat > "$REALIP_SNIPPET"'), s.index("cat > /etc/nginx/sites-available/artemisresort.com"))

    def test_setup_server_installs_snippet_from_repo_or_fails(self):
        s = read("setup_server.sh")
        self.assertIn('REALIP_SRC="$SITE_DIR/deploy/' + SNIPPET_REL + '"', s)
        self.assertIn('install -D -m 644 "$REALIP_SRC" "$REALIP_SNIPPET"', s)
        start = s.index('if [ ! -s "$REALIP_SRC" ]')
        end = s.index("cat > /etc/nginx/sites-available/artemisresort.com", start)
        with tempfile.TemporaryDirectory() as tmp:
            block = ('SITE_DIR=%s\nREALIP_SRC="$SITE_DIR/deploy/%s"\nREALIP_SNIPPET=%s/out.conf\n' % (tmp, SNIPPET_REL, tmp)) + s[start:end]
            r = subprocess.run(["bash", "-euc", block], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("ERROR:", r.stderr)
            self.assertFalse((Path(tmp) / "out.conf").exists())
            src = Path(tmp) / "deploy" / SNIPPET_REL
            src.parent.mkdir(parents=True)
            src.write_text(read(SNIPPET_REL), encoding="utf-8")
            r = subprocess.run(["bash", "-euc", block], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((Path(tmp) / "out.conf").read_text(encoding="utf-8"), read(SNIPPET_REL))


if __name__ == "__main__":
    unittest.main()
