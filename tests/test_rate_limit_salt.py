"""PR #23 c4/c6: the rate-limit HMAC key is RATE_LIMIT_SALT, else ARTEMIS_ADMIN_TOKEN; with neither the
app refuses to start. There is no built-in (public) default salt.

Unit level only: no nginx, the client IP comes from X-Real-IP in a Flask test request context; the
startup refusal is checked by importing the app in a child interpreter."""
import hashlib
import hmac
import importlib
import logging
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import ratelimit  # noqa: E402

IP = "203.0.113.7"
ENV_KEYS = ("RATE_LIMIT_SALT", "ARTEMIS_ADMIN_TOKEN")


def expected(salt: str, ip: str = IP) -> str:
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def child_env(**values):
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(values)
    return env


class RateLimitSaltTest(unittest.TestCase):
    def setUp(self):
        self.rl = importlib.reload(ratelimit)
        self.app = Flask(__name__)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for k in ENV_KEYS:
            os.environ.pop(k, None)

    def key(self, ip=IP):
        with self.app.test_request_context("/api/enquiry", method="POST", headers={"X-Real-IP": ip}):
            return self.rl.client_hash()

    # case 1: RATE_LIMIT_SALT
    def test_rate_limit_salt_is_used(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        self.assertEqual(self.rl.hmac_salt(), "salt-one-for-tests")
        self.assertEqual(self.key(), expected("salt-one-for-tests"))
        self.assertNotEqual(self.key(), expected("admin-token-for-tests"))

    def test_rate_limit_salt_alone_is_enough(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        self.assertEqual(self.key(), expected("salt-one-for-tests"))
        self.rl.require_salt()  # no exception

    # case 2: fallback to ARTEMIS_ADMIN_TOKEN
    def test_falls_back_to_admin_token_when_unset_empty_or_blank(self):
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        for salt in (None, "", "   ", "\t\n"):
            with self.subTest(salt=repr(salt)):
                if salt is None:
                    os.environ.pop("RATE_LIMIT_SALT", None)
                else:
                    os.environ["RATE_LIMIT_SALT"] = salt
                self.assertEqual(self.rl.hmac_salt(), "admin-token-for-tests")
                self.assertEqual(self.key(), expected("admin-token-for-tests"))
                self.rl.require_salt()

    def test_fallback_keeps_pre_c4_key(self):
        # without RATE_LIMIT_SALT the key is exactly what 9e86d69 produced: no counter reset on deploy
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        legacy = hmac.new(b"admin-token-for-tests", IP.encode(), hashlib.sha256).hexdigest()[:32]
        self.assertEqual(self.key(), legacy)

    # case 3: neither -> refusal, no public default
    def test_neither_set_raises_no_default(self):
        for salt, token in ((None, None), ("", ""), ("  ", "\t"), ("", None), (None, " ")):
            with self.subTest(salt=repr(salt), token=repr(token)):
                for k, v in (("RATE_LIMIT_SALT", salt), ("ARTEMIS_ADMIN_TOKEN", token)):
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v
                with self.assertRaises(self.rl.SaltNotConfigured):
                    self.rl.hmac_salt()
                with self.assertRaises(self.rl.SaltNotConfigured):
                    self.key()

    def test_require_salt_logs_clear_error_and_raises(self):
        with self.assertLogs("artemis", level=logging.CRITICAL) as logs, \
                self.assertRaises(self.rl.SaltNotConfigured):
            self.rl.require_salt()
        msg = "\n".join(logs.output)
        self.assertIn("refusing to start", msg)
        self.assertIn("RATE_LIMIT_SALT", msg)
        self.assertIn("ARTEMIS_ADMIN_TOKEN", msg)

    def test_app_refuses_to_start_without_salt(self):
        code = "import app"
        for env in (child_env(), child_env(RATE_LIMIT_SALT="", ARTEMIS_ADMIN_TOKEN=" ")):
            r = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "app", env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertNotEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertIn("refusing to start: rate limit: RATE_LIMIT_SALT and ARTEMIS_ADMIN_TOKEN", r.stderr)
            self.assertIn("SaltNotConfigured", r.stderr)

    def test_app_starts_with_either_variable(self):
        code = "import app; assert app.app.name"
        for env in (child_env(RATE_LIMIT_SALT="unit-tests-only-not-a-secret"),
                    child_env(ARTEMIS_ADMIN_TOKEN="admin-token-for-tests")):
            r = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "app", env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertNotIn("refusing to start", r.stderr)

    def test_no_builtin_default_in_source(self):
        for name in ("ratelimit.py", "tenerife.py", "app.py"):
            src = (ROOT / "app" / name).read_text(encoding="utf-8")
            for const in ('"artemis-crete"', '"artemis-tenerife"', "salt_default", 'or "artemis'):
                self.assertNotIn(const, src, (name, const))
        src = (ROOT / "app" / "ratelimit.py").read_text(encoding="utf-8")
        self.assertIn('SALT_ENV_VARS = ("RATE_LIMIT_SALT", "ARTEMIS_ADMIN_TOKEN")', src)

    def test_different_salt_gives_different_key(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        one = self.key()
        os.environ["RATE_LIMIT_SALT"] = "salt-two-for-tests"
        two = self.key()
        self.assertNotEqual(one, two)
        self.assertEqual((len(one), len(two)), (32, 32))
        self.assertEqual(two, self.key())                       # stable for the same salt and IP
        self.assertNotEqual(two, self.key(ip="198.51.100.9"))   # different IP -> different key
        self.assertNotIn("salt-two-for-tests", two)

    def test_tenerife_waitlist_uses_the_same_secret(self):
        import tenerife
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        with self.app.test_request_context("/api/tenerife/waitlist", method="POST", headers={"X-Real-IP": IP}):
            self.assertEqual(tenerife._client_hash(), expected("salt-one-for-tests"))
            os.environ.pop("RATE_LIMIT_SALT")
            with self.assertRaises(self.rl.SaltNotConfigured):
                tenerife._client_hash()

    def test_readme_documents_rate_limit_salt(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        row = next(line for line in readme.splitlines() if line.startswith("| `RATE_LIMIT_SALT` |"))
        self.assertIn("ARTEMIS_ADMIN_TOKEN", row)
        self.assertIn("refuses to start", row)


if __name__ == "__main__":
    unittest.main()
