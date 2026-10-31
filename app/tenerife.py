"""Artemis Tenerife — RU preview (noindex) + free waitlist.

Routes (Blueprint, registered in app.py):
  GET  /tenerife-preview/            RU preview page
  GET  /tenerife-preview/impressum/  301 -> /tenerife/impressum/ (canonical since 31.10.2026)
  GET  /tenerife-preview/privacy/    301 -> /tenerife/privacy/
  GET  /tenerife/impressum/          legal notice (Impressum / Aviso legal); indexable, canonical
  GET  /tenerife/privacy/            privacy notice for the waitlist; indexable, canonical
  POST /api/tenerife/waitlist        name, contact, language, GDPR consent
  GET  /tenerife/, /tenerife/<page>/ RU prod site (static pages built from
                                     grainee-v2 docs/projects/artemis/tenerife/site-ru,
                                     see app/tenerife_site/README.md); indexable.
                                     /tenerife/<page>.html -> 301 clean URL.

Preview + API paths are noindex (meta + X-Robots-Tag) and is not
linked from the Crete site. No amounts, no payments, no yield.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import sqlite3
import urllib.parse
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request

import ratelimit
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
    # AUTOINCREMENT (31.10.2026): ids of deleted leads are never handed out again in NEW databases.
    # An existing table keeps its old schema on purpose: SQLite cannot add AUTOINCREMENT in place, it
    # would need a copy-drop-rename rebuild of the lead table. The lead relay identifies a lead by
    # tbl:id:created_at, so id reuse in an existing DB is handled there.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tenerife_waitlist
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    # same secret key as the Crete limiter (RATE_LIMIT_SALT, else ARTEMIS_ADMIN_TOKEN); no public default.
    # QA PS-08: same key shape too - IPv6 counted per /64 (ratelimit.limit_key).
    return hmac.new(ratelimit.hmac_salt().encode(), ratelimit.limit_key(ip).encode(), hashlib.sha256).hexdigest()[:32]


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


# Legal pages moved from /tenerife-preview/<name>/ to the prod prefix (31.10.2026).
# Old preview URLs answer 301 so earlier links keep working; /tenerife-preview/ itself is untouched.
LEGAL_PAGES = ("impressum", "privacy")


def _with_query(url: str) -> str:
    qs = request.query_string.decode("latin-1")
    return f"{url}?{qs}" if qs else url


# With and without the trailing slash: one 301 hop straight to the canonical URL, query string kept
# (without the explicit no-slash rules Werkzeug first answers 308 -> /tenerife-preview/<name>/).
@bp.route(PREVIEW_PREFIX + "/impressum/")
@bp.route(PREVIEW_PREFIX + "/privacy/")
@bp.route(PREVIEW_PREFIX + "/impressum")
@bp.route(PREVIEW_PREFIX + "/privacy")
def preview_legal_moved():
    return redirect(_with_query("/tenerife/" + request.path.rstrip("/").rsplit("/", 1)[-1] + "/"), code=301)


# --- /tenerife/ prod (static RU pages, clean URLs) ---------------------------
SITE_PREFIX = "/tenerife"
SITE_DIR = Path(__file__).resolve().parent / "tenerife_site"
SITE_PAGES = ("norte", "producto", "acciones", "calculadora", "alquiler", "energia", "construccion",
              "proceso", "faq", "simon", "mercado", "boris")  # RU v3: scripts/tenerife_site_build/build_v3.py
SITE_URL = "https://artemisresort.com"


def _site_page(name: str):
    f = SITE_DIR / f"{name}.html"
    if not f.is_file():
        return make_response("Not found", 404)
    resp = make_response(f.read_text(encoding="utf-8"))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@bp.route(SITE_PREFIX)
def site_noslash():
    return redirect(SITE_PREFIX + "/", code=301)


@bp.route(SITE_PREFIX + "/")
def site_index():
    return _site_page("index")


@bp.route(SITE_PREFIX + "/impressum/")
@bp.route(SITE_PREFIX + "/privacy/")
def legal_page():
    name = request.path.rstrip("/").rsplit("/", 1)[-1]
    url = f"{SITE_URL}{SITE_PREFIX}/{name}/"
    resp = make_response(render_template(f"tenerife/{name}.html", langs=WAITLIST_LANGS, canonical=url))
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@bp.route(SITE_PREFIX + "/<page>/")
def site_page(page: str):
    if page not in SITE_PAGES:
        return make_response("Not found", 404)
    return _site_page(page)


@bp.route(SITE_PREFIX + "/<page>")
@bp.route(SITE_PREFIX + "/<page>.html")
def site_legacy(page: str):
    page = page[:-5] if page.endswith(".html") else page
    if page == "index":
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if page in SITE_PAGES or page in LEGAL_PAGES:
        return redirect(_with_query(f"{SITE_PREFIX}/{page}/"), code=301)
    return make_response("Not found", 404)


def _safe_back(page: str) -> str:
    """Where a no-JS form submit returns to: only our own Tenerife pages."""
    if page.startswith(SITE_PREFIX + "/") and "//" not in page and "\\" not in page and len(page) < 60:
        return page.split("?")[0].split("#")[0]
    return PREVIEW_PREFIX + "/"


def _payload() -> tuple[dict, bool]:
    if request.is_json:
        return (request.get_json(silent=True) or {}), True
    return request.form.to_dict(), False


def _reply(is_json: bool, ok: bool, status: int = 200, error: str = "", back: str = ""):
    if is_json:
        body = {"ok": ok}
        if error:
            body["error"] = error
        return jsonify(body), status
    if ok:
        return redirect((back or PREVIEW_PREFIX + "/") + "?ok=1#waitlist", code=303)
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
    return _reply(is_json, True, back=_safe_back(page))


def waitlist_rows(conn: sqlite3.Connection):
    init_waitlist_db(conn)
    return conn.execute(
        "SELECT id,name,contact,language,page,created_at FROM tenerife_waitlist ORDER BY id DESC"
    ).fetchall()
