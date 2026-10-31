"""PR #23 c4: the rate-limit client hash uses RATE_LIMIT_SALT, falling back to ARTEMIS_ADMIN_TOKEN.

Unit level only: no nginx, the client IP comes from X-Real-IP in a Flask test request context."""
import hashlib
import hmac
import importlib
import os
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


class RateLimitSaltTest(unittest.TestCase):
    def setUp(self):
        self.rl = importlib.reload(ratelimit)
        self.app = Flask(__name__)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for k in ENV_KEYS:
            os.environ.pop(k, None)

    def key(self, ip=IP, default="artemis-crete"):
        with self.app.test_request_context("/api/enquiry", method="POST", headers={"X-Real-IP": ip}):
            return self.rl.client_hash(default)

    def test_rate_limit_salt_is_used(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        self.assertEqual(self.rl.hmac_salt("artemis-crete"), "salt-one-for-tests")
        self.assertEqual(self.key(), expected("salt-one-for-tests"))
        self.assertNotEqual(self.key(), expected("admin-token-for-tests"))

    def test_falls_back_to_admin_token_when_unset(self):
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        self.assertEqual(self.key(), expected("admin-token-for-tests"))

    def test_falls_back_to_admin_token_when_empty_or_blank(self):
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        for blank in ("", "   ", "\t\n"):
            with self.subTest(salt=repr(blank)):
                os.environ["RATE_LIMIT_SALT"] = blank
                self.assertEqual(self.rl.hmac_salt("artemis-crete"), "admin-token-for-tests")
                self.assertEqual(self.key(), expected("admin-token-for-tests"))

    def test_fallback_keeps_pre_c4_key(self):
        # without RATE_LIMIT_SALT the key is exactly what 9e86d69 produced: no counter reset on deploy
        os.environ["ARTEMIS_ADMIN_TOKEN"] = "admin-token-for-tests"
        legacy = hmac.new(b"admin-token-for-tests", IP.encode(), hashlib.sha256).hexdigest()[:32]
        self.assertEqual(self.key(), legacy)

    def test_default_when_neither_is_set(self):
        self.assertEqual(self.key(default="artemis-crete"), expected("artemis-crete"))
        os.environ["RATE_LIMIT_SALT"] = ""
        self.assertEqual(self.key(default="artemis-crete"), expected("artemis-crete"))

    def test_different_salt_gives_different_key(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        one = self.key()
        os.environ["RATE_LIMIT_SALT"] = "salt-two-for-tests"
        two = self.key()
        self.assertNotEqual(one, two)
        self.assertEqual(len(one), 32)
        self.assertEqual(len(two), 32)
        # same salt, same IP -> same key (stable across calls / workers)
        self.assertEqual(two, self.key())
        # same salt, different IP -> different key
        self.assertNotEqual(two, self.key(ip="198.51.100.9"))

    def test_salt_not_in_key_and_no_secret_in_source(self):
        os.environ["RATE_LIMIT_SALT"] = "salt-one-for-tests"
        self.assertNotIn("salt-one-for-tests", self.key())
        src = (ROOT / "app" / "ratelimit.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("RATE_LIMIT_SALT", "")', src)

    def test_readme_documents_rate_limit_salt(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("| `RATE_LIMIT_SALT` |", readme)


if __name__ == "__main__":
    unittest.main()
