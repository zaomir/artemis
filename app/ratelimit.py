"""Per-client rate limit for the lead forms (QA ARTEMIS-QA-20261031-P09), stored in the leads DB.

Client key = HMAC-SHA256(salt, client IP)[:32], the same shape as tenerife._client_hash().
The IP is X-Real-IP (nginx sets it from the connection's verified $remote_addr; gunicorn listens on
127.0.0.1 only) or, without nginx, request.remote_addr. CF-Connecting-IP and X-Forwarded-For are
never read here: a client can send any value in them. Only the hash is stored, never the IP.

Counters are fixed windows (one row per client, window and window start) incremented atomically
inside a BEGIN IMMEDIATE transaction, so concurrent gunicorn workers cannot both pass the limit.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import time

from flask import request

# (window name, seconds, max accepted submissions per client in that window)
ENQUIRY_LIMITS = (("10min", 600, 3), ("day", 86400, 10))


def client_ip() -> str:
    return (request.headers.get("X-Real-IP") or "").strip() or request.remote_addr or "?"


def client_hash(salt_default: str = "artemis") -> str:
    salt = os.environ.get("ARTEMIS_ADMIN_TOKEN", "") or salt_default
    return hmac.new(salt.encode(), client_ip().encode(), hashlib.sha256).hexdigest()[:32]


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
