"""QA PS-08 (31.10.2026): the form rate limit counts an IPv6 client per /64, not per /128."""
import hashlib
import hmac
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "unit-tests-only-not-a-secret")

import ratelimit  # noqa: E402


class LimitKeyTest(unittest.TestCase):
    def test_ipv6_aggregated_to_64(self):
        a = ratelimit.limit_key("2001:db8:1:2:aaaa:bbbb:cccc:1")
        b = ratelimit.limit_key("2001:db8:1:2::ffff")
        self.assertEqual(a, "2001:db8:1:2::/64")
        self.assertEqual(a, b)
        self.assertNotEqual(a, ratelimit.limit_key("2001:db8:1:3::1"))

    def test_ipv4_and_mapped_unchanged(self):
        self.assertEqual(ratelimit.limit_key("203.0.113.7"), "203.0.113.7")
        self.assertEqual(ratelimit.limit_key(" 203.0.113.7 "), "203.0.113.7")
        self.assertEqual(ratelimit.limit_key("::ffff:203.0.113.7"), "203.0.113.7")
        self.assertNotEqual(ratelimit.limit_key("203.0.113.7"), ratelimit.limit_key("203.0.113.8"))

    def test_unparseable_kept(self):
        self.assertEqual(ratelimit.limit_key("?"), "?")
        self.assertEqual(ratelimit.limit_key("not-an-ip"), "not-an-ip")


class ClientHashPer64Test(unittest.TestCase):
    """Both limiters (Crete ratelimit.client_hash, Tenerife tenerife._client_hash) give one key per /64."""

    @classmethod
    def setUpClass(cls):
        import app as artemis_app
        cls.app = importlib.reload(artemis_app).app
        import tenerife
        cls.tenerife = tenerife

    def hashes(self, fn, header, ips):
        out = []
        for ip in ips:
            with self.app.test_request_context("/", headers={header: ip}):
                out.append(fn())
        return out

    def test_same_64_same_key_both_limiters(self):
        same = ["2001:db8:5:6::1", "2001:db8:5:6:ffff:ffff:ffff:fffe"]
        other = "2001:db8:5:7::1"
        for fn, header in ((ratelimit.client_hash, "X-Real-IP"), (self.tenerife._client_hash, "CF-Connecting-IP")):
            h = self.hashes(fn, header, same + [other])
            self.assertEqual(h[0], h[1], fn.__name__)
            self.assertNotEqual(h[0], h[2], fn.__name__)
            salt = ratelimit.hmac_salt().encode()
            self.assertEqual(h[0], hmac.new(salt, b"2001:db8:5:6::/64", hashlib.sha256).hexdigest()[:32])

    def test_ipv4_key_unchanged(self):
        """IPv4 counters written before this change keep matching (same HMAC input)."""
        salt = ratelimit.hmac_salt().encode()
        want = hmac.new(salt, b"198.51.100.4", hashlib.sha256).hexdigest()[:32]
        self.assertEqual(self.hashes(ratelimit.client_hash, "X-Real-IP", ["198.51.100.4"]), [want])
        self.assertEqual(self.hashes(self.tenerife._client_hash, "CF-Connecting-IP", ["198.51.100.4"]), [want])

    def test_limit_hits_whole_64(self):
        """Rotating addresses inside one /64 does not reset the limit."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rl.db")
            res = []
            for i in range(1, 6):
                with self.app.test_request_context("/", headers={"X-Real-IP": f"2001:db8:9:9::{i:x}"}):
                    res.append(ratelimit.hit(db, "t", ratelimit.client_hash(), limits=(("10min", 600, 3),), now=1000.0))
        self.assertEqual(res[:3], [0, 0, 0])
        self.assertTrue(all(r > 0 for r in res[3:]))


if __name__ == "__main__":
    unittest.main()
