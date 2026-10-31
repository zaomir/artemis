"""Artemis Tenerife — RU preview (noindex) + free waitlist.

Routes (Blueprint, registered in app.py):
  GET  /tenerife-preview/            RU preview page
  GET  /tenerife-preview/impressum/  legal notice (Impressum / Aviso legal)
  GET  /tenerife-preview/privacy/    privacy notice for the waitlist
  POST /api/tenerife/waitlist        name, contact, language, GDPR consent

Everything under these paths is noindex (meta + X-Robots-Tag) and is not
linked from the Crete site. No amounts, no payments, no yield.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import sqlite3
import urllib.parse

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request

from notify import notify_lead

bp = Blueprint("tenerife", __name__)

PREVIEW_PREFIX = "/tenerife-preview"
NOINDEX_PREFIXES = (PREVIEW_PREFIX, "/api/tenerife/")
WAITLIST_LANGS = {"ru": "Русский", "de": "Deutsch", "en": "English", "es": "Español", "fr": "Français"}
RATE_LIMIT_MAX = 3          # submissions
RATE_LIMIT_WINDOW_MIN = 10  # per this many minutes per client
HONEYPOT_FIELD = "website"


def _db_path() -> str:
    # same sqlite file as Crete leads (app.DB), resolved lazily so tests can override
    import app as main_app  # noqa: WPS433 (runtime import avoids circular import)
    return main_app.DB


def init_waitlist_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tenerife_waitlist
        (id INTEGER PRIMARY KEY,
         name TEXT NOT NULL, contact TEXT NOT NULL, language TEXT NOT NULL,
         page TEXT, consent INTEGER NOT NULL, client_hash TEXT,
         created_at TEXT NOT NULL)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_tw_client_time ON tenerife_waitlist(client_hash, created_at)"
    )


def _client_hash() -> str:
    ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Real-IP")
        or request.remote_addr
        or "?"
    )
    salt = os.environ.get("ARTEMIS_ADMIN_TOKEN", "") or "artemis-tenerife"
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def _noindex(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.after_app_request
def _noindex_preview(resp):
    if request.path.startswith(NOINDEX_PREFIXES):
        _noindex(resp)
    return resp


def _render(template: str, **ctx):
    return _noindex(make_response(render_template(template, langs=WAITLIST_LANGS, **ctx)))


@bp.route(PREVIEW_PREFIX)
def preview_noslash():
    return redirect(PREVIEW_PREFIX + "/", code=301)


@bp.route(PREVIEW_PREFIX + "/")
def preview():
    return _render("tenerife/preview.html", sent=request.args.get("ok") == "1")


@bp.route(PREVIEW_PREFIX + "/impressum/")
def impressum():
    return _render("tenerife/impressum.html")


@bp.route(PREVIEW_PREFIX + "/privacy/")
def privacy():
    return _render("tenerife/privacy.html")


def _payload() -> tuple[dict, bool]:
    if request.is_json:
        return (request.get_json(silent=True) or {}), True
    return request.form.to_dict(), False


def _reply(is_json: bool, ok: bool, status: int = 200, error: str = ""):
    if is_json:
        body = {"ok": ok}
        if error:
            body["error"] = error
        return jsonify(body), status
    if ok:
        return redirect(PREVIEW_PREFIX + "/?ok=1#waitlist", code=303)
    return make_response(error or "Ошибка", status)


@bp.route("/api/tenerife/waitlist", methods=["POST"])
def waitlist():
    d, is_json = _payload()

    # Honeypot: bots fill the hidden field. Pretend success, store nothing.
    if str(d.get(HONEYPOT_FIELD) or "").strip():
        current_app.logger.info("tenerife waitlist: honeypot hit, dropped")
        return _reply(is_json, True)

    name = " ".join(str(d.get("name") or "").split())[:120]
    contact = " ".join(str(d.get("contact") or "").split())[:200]
    language = str(d.get("language") or "").strip().lower()[:5]
    consent = str(d.get("consent")).lower() in {"1", "true", "on", "yes"}
    page = str(d.get("page") or "").strip()[:200] or urllib.parse.urlsplit(request.referrer or "").path
    page = page or PREVIEW_PREFIX + "/"

    if not name or len(contact) < 5:
        return _reply(is_json, False, 400, "Укажите имя и контакт (email, телефон или Telegram).")
    if language not in WAITLIST_LANGS:
        return _reply(is_json, False, 400, "Выберите язык общения.")
    if not consent:
        return _reply(is_json, False, 400, "Нужно согласие на обработку данных.")

    client = _client_hash()
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(minutes=RATE_LIMIT_WINDOW_MIN)).isoformat()
    conn = sqlite3.connect(_db_path(), timeout=5)
    try:
        init_waitlist_db(conn)
        recent = conn.execute(
            "SELECT COUNT(*) FROM tenerife_waitlist WHERE client_hash=? AND created_at>=?",
            (client, since),
        ).fetchone()[0]
        if recent >= RATE_LIMIT_MAX:
            return _reply(is_json, False, 429, "Слишком много заявок. Попробуйте позже.")
        conn.execute(
            """INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (name, contact, language, page, 1, client, now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    notify_lead("Tenerife waitlist", name, contact, language, page)
    return _reply(is_json, True)


def waitlist_rows(conn: sqlite3.Connection):
    init_waitlist_db(conn)
    return conn.execute(
        "SELECT id,name,contact,language,page,created_at FROM tenerife_waitlist ORDER BY id DESC"
    ).fetchall()
