"""QA PR27-01 / PR27-02 (31.10.2026): deploy/artemis-deploy.sh failure paths, run for real in a sandbox.

The real script runs against a temp git checkout with fakes first in PATH:
  systemctl - manages a fake gunicorn master (a bash process: N child "workers", SIGHUP re-reads the code);
              rejects --kill-whom like systemd < 252;
  curl      - 200 (403 for /admin/leads) only while the master is alive and has workers, else 502;
  sleep     - 0.02 s, so timeouts are fast.
pgrep, kill, git, flock are the real ones. Service name / lock / state / log paths are all inside the
temp dir, so nothing touches /var/www/artemis or the real artemis unit.
Code markers in the checkout: BROKEN - workers fail to boot, master exits (gunicorn HaltServer);
HANG - master stays up but no worker comes up.
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "artemis-deploy.sh"
NEED = ("bash", "git", "flock", "pgrep", "comm", "timeout", "tar", "sleep")
MISSING = [t for t in NEED if not shutil.which(t)]

MASTER = r'''#!/bin/bash
# fake gunicorn master
APP=$1; PIDFILE=$2; SLEEP=$3
W=()
boot() {
  if [ -e "$APP/BROKEN" ]; then echo "Worker failed to boot" >&2; kill "${W[@]}" 2>/dev/null; rm -f "$PIDFILE"; exit 3; fi
  local new=()
  if [ ! -e "$APP/HANG" ]; then for i in 1 2; do "$SLEEP" 1000 & new+=($!); done; fi
  [ ${#W[@]} -gt 0 ] && kill "${W[@]}" 2>/dev/null
  W=("${new[@]}")
}
trap boot HUP
trap 'kill "${W[@]}" 2>/dev/null; rm -f "$PIDFILE"; exit 0' TERM
boot
echo $$ > "$PIDFILE"
exec 3<> "$APP/../fifo"
while :; do read -r -t 0.2 -u 3 _ || true; done
'''

SYSTEMCTL = r'''#!/bin/bash
S="$SANDBOX"; echo "systemctl $*" >> "$S/systemctl.log"
alive() { local p; p=$(cat "$S/master.pid" 2>/dev/null) && [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
for a in "$@"; do case $a in --kill-whom=*) echo "systemctl: unrecognized option '$a'" >&2; exit 1;; esac; done
svc="${@: -1}"; [ "$svc" = "$SANDBOX_SERVICE" ] || { echo "fake systemctl: unknown unit $svc" >&2; exit 5; }
case $1 in
  show) if alive; then cat "$S/master.pid"; else echo 0; fi ;;
  is-active) alive ;;
  reset-failed) exit 0 ;;
  restart)
    [ -e "$S/FAIL_RESTART" ] && exit 1
    if alive; then p=$(cat "$S/master.pid"); kill -TERM "$p"; for i in $(seq 100); do kill -0 "$p" 2>/dev/null || break; "$REAL_SLEEP" 0.02; done; fi
    rm -f "$S/master.pid"
    setsid bash "$S/master.sh" "$S/app" "$S/master.pid" "$REAL_SLEEP" >>"$S/master.log" 2>&1 < /dev/null 9>&- &
    echo $! >> "$S/masters.all"
    for i in $(seq 50); do alive && exit 0; "$REAL_SLEEP" 0.02; done
    exit 1 ;;
  *) exit 1 ;;
esac
'''

CURL = r'''#!/bin/bash
S="$SANDBOX"; url="${@: -1}"
p=$(cat "$S/master.pid" 2>/dev/null)
if [ -n "$p" ] && kill -0 "$p" 2>/dev/null && [ -n "$(pgrep -P "$p")" ]; then
  case $url in */admin/leads) printf 403;; *) printf 200;; esac
else printf 502; fi
'''


@unittest.skipIf(MISSING, f"missing tools: {MISSING}")
class DeployReloadFailureSandboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="artemis-deploy-sbx-"))
        t = self.tmp
        real_sleep = shutil.which("sleep")
        (t / "bin").mkdir()
        for name, body in (("systemctl", SYSTEMCTL), ("curl", CURL),
                           ("sleep", f"#!/bin/sh\nexec {real_sleep} 0.02\n"),
                           ("fakepy", "#!/bin/sh\necho 'Ran 1 test'; echo OK\n")):
            f = t / "bin" / name
            f.write_text(body)
            f.chmod(0o755)
        (t / "master.sh").write_text(MASTER)
        os.mkfifo(t / "fifo")
        self.env = {
            "PATH": f"{t / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(t), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "SANDBOX": str(t), "REAL_SLEEP": real_sleep,
            "SANDBOX_SERVICE": "artemis-sandbox-test",
            "ARTEMIS_SERVICE": "artemis-sandbox-test",
            "ARTEMIS_DIR": str(t / "app"),
            "ARTEMIS_LOCK": str(t / "deploy.lock"),
            "ARTEMIS_STATE_DIR": str(t / "state"),
            "ARTEMIS_DEPLOY_LOG": str(t / "deploy.log"),
            "ARTEMIS_TEST_PYTHON": str(t / "bin" / "fakepy"),
            "ARTEMIS_LOCAL_URL": "http://127.0.0.1:1", "ARTEMIS_PUBLIC_URL": "http://127.0.0.1:1",
            "ARTEMIS_RELOAD_TIMEOUT": "20", "ARTEMIS_SKIP_ROOT_CHECK": "1",
        }
        self.git("init", "-q", "--bare", "-b", "main", str(t / "origin.git"))
        self.git("clone", "-q", str(t / "origin.git"), str(t / "seed"))
        self.good1 = self.commit("v1")
        self.git("-C", str(t / "seed"), "push", "-q", "origin", "main")
        self.git("clone", "-q", str(t / "origin.git"), str(t / "app"))
        self.assertEqual(self.sh(t / "bin" / "systemctl", "restart", "artemis-sandbox-test").returncode, 0)

    def tearDown(self):
        for line in (self.tmp / "masters.all").read_text().split() if (self.tmp / "masters.all").exists() else []:
            pid = int(line)
            kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
            for p in [pid] + [int(k) for k in kids]:
                try:
                    os.kill(p, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def sh(self, *cmd, **kw):
        return subprocess.run([str(c) for c in cmd], env=self.env, capture_output=True, text=True, timeout=120, **kw)

    def git(self, *args):
        r = self.sh("git", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, ver, marker=None, push=False):
        seed = self.tmp / "seed"
        (seed / "app.txt").write_text(ver)
        for m in ("BROKEN", "HANG"):
            if (seed / m).exists():
                self.git("-C", str(seed), "rm", "-q", m)
        if marker:
            (seed / marker).write_text("1")
            self.git("-C", str(seed), "add", marker)
        self.git("-C", str(seed), "add", "app.txt")
        self.git("-C", str(seed), "commit", "-q", "-m", ver)
        if push:
            self.git("-C", str(seed), "push", "-q", "origin", "main")
        return self.git("-C", str(seed), "rev-parse", "HEAD")

    def deploy(self, **extra):
        env = dict(self.env, **extra)
        r = subprocess.run(["bash", str(DEPLOY)], env=env, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def head(self):
        return self.git("-C", str(self.tmp / "app"), "rev-parse", "HEAD")

    def master(self):
        try:
            p = int((self.tmp / "master.pid").read_text())
            os.kill(p, 0)
            return p
        except (OSError, ValueError):
            return None

    def healthy(self):
        return self.sh(self.tmp / "bin" / "curl", "http://x/health").stdout == "200"

    def state(self, name):
        f = self.tmp / "state" / name
        return f.read_text().strip() if f.exists() else None

    # scenarios
    def test_s1_hup_success_keeps_master(self):
        m0 = self.master()
        good2 = self.commit("v2", push=True)
        rc, out = self.deploy()
        self.assertEqual(rc, 0, out)
        self.assertIn("workers replaced in", out)
        self.assertIn(f"deploy OK at {good2[:7]}", out)
        self.assertEqual(self.master(), m0)  # HUP, not restart
        self.assertEqual(self.head(), good2)
        self.assertEqual(self.state("last_good"), good2)
        self.assertIsNone(self.state("pending"))
        self.assertNotIn("restart", (self.tmp / "systemctl.log").read_text().split("\n", 1)[1])

    def test_s3_workers_fail_master_exits_rollback(self):
        bad = self.commit("v2-broken", "BROKEN", push=True)
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn("gone after HUP", out)
        self.assertIn(f"ROLLBACK to {self.good1[:7]}", out)
        self.assertIn("rollback OK", out)
        self.assertEqual(self.head(), self.good1)
        self.assertTrue(self.healthy())
        self.assertEqual(self.state("failed"), bad)
        # rerun: does not redeploy the failed commit, prod stays healthy on good1
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn(f"ABORT: {bad[:7]} already failed", out)
        self.assertEqual(self.head(), self.good1)
        self.assertTrue(self.healthy())
        # explicit retry: deploys again and rolls back again
        rc, out = self.deploy(ARTEMIS_RETRY_FAILED="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("rollback OK", out)
        self.assertEqual(self.head(), self.good1)
        # a fixed commit deploys normally and clears the failed marker
        fixed = self.commit("v3", push=True)
        rc, out = self.deploy()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.head(), fixed)
        self.assertIsNone(self.state("failed"))

    def test_s3_workers_never_come_up_timeout_rollback(self):
        self.commit("v2-hang", "HANG", push=True)
        rc, out = self.deploy(ARTEMIS_RELOAD_TIMEOUT="5")
        self.assertEqual(rc, 1, out)
        self.assertIn("workers not replaced in 5s - restart", out)
        self.assertIn("rollback OK", out)
        self.assertEqual(self.head(), self.good1)
        self.assertTrue(self.healthy())

    def test_master_dies_and_restart_fails_reports_manual_attention(self):
        self.commit("v2-broken", "BROKEN", push=True)
        (self.tmp / "FAIL_RESTART").write_text("1")
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn("systemctl restart artemis-sandbox-test failed", out)
        self.assertIn(f"ROLLBACK to {self.good1[:7]}", out)
        self.assertIn("ROLLBACK SMOKE ALSO FAILED", out)
        self.assertEqual(self.head(), self.good1)  # code is restored even if the service is down

    def test_rerun_after_killed_deploy_is_not_up_to_date(self):
        # state left by the d20583c failure: checkout on the broken commit, master dead, run killed
        bad = self.commit("v2-broken", "BROKEN", push=True)
        app = str(self.tmp / "app")
        self.git("-C", app, "fetch", "-q", "origin")
        self.git("-C", app, "merge", "--ff-only", "-q", "origin/main")
        (self.tmp / "state").mkdir()
        (self.tmp / "state" / "pending").write_text(f"{self.good1} {bad}\n")
        os.kill(self.master(), signal.SIGHUP)  # broken code -> master exits
        for _ in range(100):
            if not self.master():
                break
            time.sleep(0.02)
        self.assertFalse(self.healthy())
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn("up to date", out)
        self.assertIn("did not finish", out)
        self.assertIn(f"ROLLBACK to {self.good1[:7]} (unfinished deploy", out)
        self.assertIn("rollback OK", out)
        self.assertNotIn("smoke OK", out)
        self.assertEqual(self.head(), self.good1)
        self.assertTrue(self.healthy())

    def test_up_to_date_failing_smoke_rolls_back_to_last_good(self):
        good2 = self.commit("v2", push=True)
        self.assertEqual(self.deploy()[0], 0)
        self.assertEqual(self.state("last_good"), good2)
        bad = self.commit("v3-broken", "BROKEN", push=True)
        app = str(self.tmp / "app")
        self.git("-C", app, "fetch", "-q", "origin")
        self.git("-C", app, "merge", "--ff-only", "-q", "origin/main")  # manual update, no pending marker
        os.kill(self.master(), signal.SIGHUP)  # broken code -> master exits
        for _ in range(100):
            if not self.master():
                break
            time.sleep(0.02)
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn("smoke FAILED", out)
        self.assertIn(f"ROLLBACK to {good2[:7]} (last good commit)", out)
        self.assertEqual(self.head(), good2)
        self.assertTrue(self.healthy())
        self.assertEqual(self.state("failed"), bad)

    def test_error_after_switch_goes_to_rollback(self):
        # local commit on prod main -> ff-only merge fails after the switch began -> ERR trap -> rollback
        self.commit("v2", push=True)
        app = str(self.tmp / "app")
        (self.tmp / "app" / "local.txt").write_text("x")
        self.git("-C", app, "add", "local.txt")
        self.git("-C", app, "commit", "-q", "-m", "local")
        local = self.head()
        rc, out = self.deploy()
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR: rc=", out)
        self.assertIn(f"ROLLBACK to {local[:7]} (deploy step failed)", out)
        self.assertIn("rollback OK", out)
        self.assertEqual(self.head(), local)

    def test_old_systemd_without_kill_whom(self):
        # the fake systemctl rejects --kill-whom like systemd < 252; the deploy must still HUP
        good2 = self.commit("v2", push=True)
        rc, out = self.deploy()
        self.assertEqual(rc, 0, out)
        self.assertIn("workers replaced in", out)
        self.assertNotIn("unrecognized option", out)
        self.assertEqual(self.head(), good2)
        self.assertNotIn("--kill-whom", DEPLOY.read_text(encoding="utf-8"))

    def test_service_not_running_restarts(self):
        os.kill(self.master(), signal.SIGTERM)
        for _ in range(100):
            if not self.master():
                break
            time.sleep(0.02)
        good2 = self.commit("v2", push=True)
        rc, out = self.deploy()
        self.assertEqual(rc, 0, out)
        self.assertIn("not running - restart", out)
        self.assertIn(f"deploy OK at {good2[:7]}", out)


if __name__ == "__main__":
    unittest.main()
