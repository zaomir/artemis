"""Per-client rate limit for the lead forms (QA ARTEMIS-QA-20261031-P09), stored in the leads DB.

Client key = HMAC-SHA256(salt, client IP)[:32], the same shape as tenerife._client_hash(). The salt is
RATE_LIMIT_SALT, falling back to ARTEMIS_ADMIN_TOKEN when it is unset or empty; with neither the app
refuses to start (require_salt(), called at app creation). There is no built-in default salt.
The IP is X-Real-IP (nginx sets it from the connection's verified $remote_addr; gunicorn listens on
127.0.0.1 only) or, without nginx, request.remote_addr. CF-Connecting-IP and X-Forwarded-For are
never read here: a client can send any value in them. Only the hash is stored, never the IP.

Counters are fixed windows (one row per client, window and window start) incremented atomically
inside a BEGIN IMMEDIATE transaction, so concurrent gunicorn workers cannot both pass the limit.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sqlite3
import time

from flask import request

# (window name, seconds, max accepted submissions per client in that window)
ENQUIRY_LIMITS = (("10min", 600, 3), ("day", 86400, 10))


def client_ip() -> str:
    return (request.headers.get("X-Real-IP") or "").strip() or request.remote_addr or "?"


SALT_ENV_VARS = ("RATE_LIMIT_SALT", "ARTEMIS_ADMIN_TOKEN")


class SaltNotConfigured(RuntimeError):
    """Neither RATE_LIMIT_SALT nor ARTEMIS_ADMIN_TOKEN is set: the client hash would be guessable."""


def hmac_salt() -> str:
    """HMAC key for client hashes: RATE_LIMIT_SALT, else ARTEMIS_ADMIN_TOKEN (the key used before
    RATE_LIMIT_SALT existed, so counters survive the upgrade). There is no built-in default: a public
    constant would let anyone recompute the hash of an IP. Unset, empty or whitespace-only counts as unset.
    Changing the salt only restarts the rate-limit counters (old rows stop matching, purged after 2 days)."""
    for name in SALT_ENV_VARS:
        value = os.environ.get(name, "")
        if value.strip():
            return value
    raise SaltNotConfigured(
        "rate limit: RATE_LIMIT_SALT and ARTEMIS_ADMIN_TOKEN are both unset or empty; "
        "set RATE_LIMIT_SALT (e.g. openssl rand -hex 32) in /etc/artemis/artemis.env"
    )


def require_salt() -> None:
    """Called once at app creation: refuse to start without a secret HMAC key (logged, then raised)."""
    try:
        hmac_salt()
    except SaltNotConfigured as exc:
        logging.getLogger("artemis").critical("refusing to start: %s", exc)
        raise


def client_hash() -> str:
    return hmac.new(hmac_salt().encode(), client_ip().encode(), hashlib.sha256).hexdigest()[:32]


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rate_limit
        (scope TEXT NOT NULL, client_hash TEXT NOT NULL, win TEXT NOT NULL, win_start INTEGER NOT NULL,
         count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (scope, client_hash, win, win_start))"""
    )


def hit(db_path: str, scope: str, client: str, limits=None, now: float | None = None) -> int:
    """Count one submission. Returns 0 when allowed, else the Retry-After seconds (>= 1).

    A refused submission is not counted, so a client is let in again once its window ends."""
    limits = ENQUIRY_LIMITS if limits is None else limits
    now = time.time() if now is None else now
    conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    try:
        _init(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            retry = 0
            starts = []
            for win, seconds, limit in limits:
                start = int(now // seconds * seconds)
                starts.append((win, start))
                row = conn.execute(
                    "SELECT count FROM rate_limit WHERE scope=? AND client_hash=? AND win=? AND win_start=?",
                    (scope, client, win, start),
                ).fetchone()
                if row and row[0] >= limit:
                    retry = max(retry, int(start + seconds - now) + 1)
            if not retry:
                for win, start in starts:
                    conn.execute(
                        """INSERT INTO rate_limit(scope,client_hash,win,win_start,count) VALUES(?,?,?,?,1)
                           ON CONFLICT(scope,client_hash,win,win_start) DO UPDATE SET count=count+1""",
                        (scope, client, win, start),
                    )
            # housekeeping: windows that ended more than a day ago
            conn.execute("DELETE FROM rate_limit WHERE win_start < ?", (int(now) - 2 * 86400,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return retry
    finally:
        conn.close()
