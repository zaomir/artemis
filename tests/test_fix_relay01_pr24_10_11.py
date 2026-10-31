"""QA follow-ups after PR #24 (31.10.2026): RELAY-01, PR24-10, PR24-11, rel=icon on the Crete legal pages."""
import importlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")  # app refuses to start without a salt

SCRIPTS = ("install_artemis.sh", "setup_server.sh")


def read(name):
    return (DEPLOY / name).read_text(encoding="utf-8")


def server_blocks(conf):
    """Top-level `server { ... }` blocks of an nginx config (brace matching, comments stripped)."""
    text = re.sub(r"#[^\n]*", "", conf)
    blocks, i = [], 0
    while True:
        m = re.compile(r"^server\s*\{", re.M).search(text, i)
        if not m:
            return blocks
        depth, j = 0, m.end() - 1
        while True:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(text[m.start():j + 1])
        i = j + 1


class Relay01AutoincrementTest(unittest.TestCase):
    """RELAY-01: databases created by the provisioning scripts never hand out a deleted top id again."""

    def test_scripts_create_leads_with_autoincrement(self):
        for name in SCRIPTS:
            sqls = re.findall(r"CREATE TABLE IF NOT EXISTS leads \([^)]*\)", read(name))
            self.assertEqual(len(sqls), 1, name)
            self.assertIn("id INTEGER PRIMARY KEY AUTOINCREMENT", sqls[0], name)

    def test_provisioned_db_does_not_reuse_ids(self):
        for name in SCRIPTS:
            sql = re.search(r"CREATE TABLE IF NOT EXISTS leads \([^)]*\)", read(name)).group(0)
            with tempfile.TemporaryDirectory() as tmp:
                conn = sqlite3.connect(str(Path(tmp) / "leads.db"))
                conn.execute(sql)
                conn.execute("INSERT INTO leads(name) VALUES ('a')")
                top = conn.execute("INSERT INTO leads(name) VALUES ('b')").lastrowid
                conn.execute("DELETE FROM leads WHERE id = ?", (top,))
                nxt = conn.execute("INSERT INTO leads(name) VALUES ('c')").lastrowid
                conn.close()
            self.assertGreater(nxt, top, name)


class Pr2410RealIpEveryServerBlockTest(unittest.TestCase):
    """PR24-10: every server block of the prod template (main, :80, www:443) includes the realip snippet."""

    def test_all_server_blocks_include_realip(self):
        blocks = server_blocks(read("nginx-artemisresort.com.origin.conf"))
        self.assertEqual(len(blocks), 3)
        for b in blocks:
            name = re.search(r"server_name\s+([^;]+);", b).group(1)
            self.assertRegex(b, r"(?m)^    include /etc/nginx/snippets/cloudflare-realip\.conf;$", name)


class Pr2411NginxTestFailsLoudlyTest(unittest.TestCase):
    """PR24-11: a failed `nginx -t` aborts the installer (rc=1) instead of printing DONE."""

    def test_nginx_t_guarded(self):
        for name in SCRIPTS:
            s = read(name)
            self.assertNotRegex(s, r"(?m)^\s*nginx -t &&", name)
            self.assertRegex(s, r"(?m)^\s*nginx -t \|\| \{ echo \"ERROR: [^\"]*\" >&2; exit 1; \}$", name)
            self.assertLess(s.index("nginx -t ||"), s.rindex("DONE"), name)

    def test_failed_nginx_t_stops_before_done(self):
        """Run the guarded line with a failing `nginx` stub: rc=1, reload never runs, DONE never printed."""
        s = read("install_artemis.sh")
        guard = re.search(r"(?m)^nginx -t \|\|.*\n^systemctl reload nginx.*$", s).group(0)
        with tempfile.TemporaryDirectory() as tmp:
            for tool, rc in (("nginx", 1), ("systemctl", 0)):
                p = Path(tmp) / tool
                p.write_text(f"#!/bin/sh\necho {tool}-called\nexit {rc}\n")
                p.chmod(0o755)
            script = f"set -e\n{guard}\necho DONE\n"
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                               env={"PATH": f"{tmp}:/usr/bin:/bin"})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("systemctl-called", r.stdout)
        self.assertNotIn("DONE", r.stdout)
        self.assertIn("ERROR: nginx -t failed", r.stderr)


class LegalPagesFaviconTest(unittest.TestCase):
    """rel=icon on /<lang>/privacy/ and /<lang>/terms/ (the legal template had none)."""

    @classmethod
    def setUpClass(cls):
        import app as artemis_app
        cls.mod = importlib.reload(artemis_app)
        cls.client = cls.mod.app.test_client()

    def test_icon_links(self):
        for lang in ("en", "ru", "es", "fr"):
            for page in ("privacy", "terms"):
                url = f"/{lang}/{page}/"
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)
                html = r.get_data(as_text=True)
                icons = re.findall(r"<link rel=\"icon\"[^>]*href=\"([^\"]+)\"", html)
                self.assertIn("/static/favicon.ico", icons, url)
                self.assertIn("/static/favicon-32x32.png", icons, url)
                for href in icons:
                    self.assertEqual(self.client.get(href).status_code, 200, href)


class Ps06GracefulReloadTest(unittest.TestCase):
    """PS-06: the deploy switches gunicorn with SIGHUP (no listener gap -> no 502), restart only as fallback."""

    def test_deploy_uses_hup_reload(self):
        s = read("artemis-deploy.sh")
        start = s.index('log "deploy ${OLD:0:7} -> ${NEW:0:7}"')
        body = s[start:s.index("if smoke; then", start)]
        self.assertIn("reload_app", body)
        self.assertNotIn("systemctl restart", body)
        fn = s[s.index("reload_app() {"):]
        fn = fn[:fn.index("\n}\n")]
        # QA PR27-02: no `systemctl kill --kill-whom` (systemd >= 252 only) - plain kill to MainPID
        self.assertIn('kill -s HUP "$main"', fn)
        self.assertNotIn("--kill-whom", s)
        self.assertIn("restart_app ", fn)  # fallback when not running / master gone / not replaced
        rfn = s[s.index("restart_app() {"):]
        rfn = rfn[:rfn.index("\n}\n")]
        self.assertIn('systemctl restart "$SERVICE"', rfn)
        r = subprocess.run(["bash", "-n", str(DEPLOY / "artemis-deploy.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
