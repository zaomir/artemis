"""Artemis Tenerife — RU preview (noindex) + free waitlist.

Routes (Blueprint, registered in app.py):
  GET  /tenerife-preview[/<sub>]     301 -> /tenerife/<sub>/ if that page exists, else /tenerife/ (T47)
  GET  /tenerife/impressum/          legal notice (Impressum / Aviso legal); indexable, canonical
  GET  /tenerife/privacy/            privacy notice for the waitlist; indexable, canonical
                                     (both static, v2 layout, built by build_v3.py from the templates' text)
  GET  /tenerife/gracias/?back=      no-JS thank-you page after the form (noindex); errors answer with the
                                     same v2 notice shell and a link back to the form
  POST /api/tenerife/waitlist        name, contact, language, GDPR consent
                                     (+ calc_m2, calc_step, calc_pay from /tenerife/calculadora/:
                                     recomputed with model.json in tenerife_calc.py)
  GET  /tenerife/, /tenerife/<page>/ RU prod site (static pages built from
                                     grainee-v2 docs/projects/artemis/tenerife/site-ru,
                                     see app/tenerife_site/README.md); indexable.
                                     /tenerife/<page>.html -> 301 clean URL.
  GET  /tenerife/calculadora[/|.html] 302 -> /tenerife/ while TENERIFE_SHOW_FIGURES is off (r4.1 c2, temporary)

Preview + API paths are noindex (meta + X-Robots-Tag) and is not
linked from the Crete site. No payments; the only amounts are the server's recomputation of
the visitor's calculator inputs, stored with the lead.
"""
from __future__ import annotations

import datetime
import hashlib
import html
import hmac
import ipaddress
import logging
import os
import re
import sqlite3
import urllib.parse
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request

import ratelimit
from notify import notify_lead
from tenerife_calc import COLUMNS as CALC_COLUMNS, check_calc, load_model, migrate as migrate_calc

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
    migrate_calc(conn)


def _client_ip() -> str:
    """Client IP for the rate-limit key (QA T3-04). nginx (prod and preview) resolves the real client via
    Cloudflare real_ip and sets X-Real-IP to the verified $remote_addr, overwriting anything the client sent.
    CF-Connecting-IP and X-Forwarded-For are client-controllable on the way in and are never read here
    (no ProxyFix on XFF either); without X-Real-IP (local runs) the TCP peer is used."""
    real = (request.headers.get("X-Real-IP") or "").strip()
    try:
        return str(ipaddress.ip_address(real))
    except ValueError:
        return request.remote_addr or "?"


def _client_hash() -> str:
    ip = (
        _client_ip()  # T3-04: X-Real-IP (set by nginx), else the TCP peer
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


# The old RU one-pager /tenerife-preview/ is retired (designer T47, 31.10.2026): every URL under it answers ONE 301
# to the same page under /tenerife/ when it exists (impressum, privacy, the 12 site pages), else to /tenerife/;
# the query string is kept. Legal pages moved here first (31.10.2026, same rule).
LEGAL_PAGES = ("impressum", "privacy")


@bp.route(PREVIEW_PREFIX)
@bp.route(PREVIEW_PREFIX + "/")
@bp.route(PREVIEW_PREFIX + "/<path:sub>")
def preview_moved(sub: str = ""):
    first = sub.strip("/").split("/", 1)[0]
    if figure_page_hidden(first):   # r4.1 c2: straight to /tenerife/ (temporary), not via the 302 page
        return _figure_page_moved()
    target = f"/tenerife/{first}/" if first in LEGAL_PAGES + SITE_PAGES else "/tenerife/"
    return redirect(_with_query(target), code=301)


def _with_query(url: str) -> str:
    qs = request.query_string.decode("latin-1")
    return f"{url}?{qs}" if qs else url


# --- /tenerife/ prod (static RU pages, clean URLs) ---------------------------
SITE_PREFIX = "/tenerife"
SITE_DIR = Path(__file__).resolve().parent / "tenerife_site"
SITE_PAGES = ("norte", "producto", "acciones", "calculadora", "alquiler", "energia", "construccion",
              "proceso", "faq", "simon", "mercado", "boris")  # RU v3: scripts/tenerife_site_build/build_v3.py
SITE_URL = "https://artemisresort.com"
# r4.1: investor pages are not published until the figures are approved: 404 (as the hidden «Инвесторам» footer link),
# never in SITE_PAGES, the sitemap or any internal link. Guarded explicitly so adding one to SITE_PAGES can't leak it.
UNPUBLISHED_PAGES = ("inversores", "investors", "inversiones", "invest")
# r4.1: figure data (model.json & co.) is never served while TENERIFE_SHOW_FIGURES is off (default). The file itself
# lives in app/tenerife_site/data/ (nginx serves /static/ straight from disk); this guard answers 404 in Flask before
# static serving, for any JSON under /static/tenerife/, in case one is ever put back there.
FIGURE_STATIC_RX = re.compile(r"^/static/tenerife/(?:.*/)?[^/]*\.json(?:\.gz|\.br)?$", re.I)
# r4.1 c2 (Lead 01.11): the calculator page has nothing to show without the figures. While TENERIFE_SHOW_FIGURES is off
# every URL of it (/tenerife/calculadora[/][.html], any query, /tenerife-preview/calculadora/) answers a TEMPORARY 302
# to /tenerife/ (it comes back with the figures, so no 301 that browsers/CDN would cache); no page links it.
# app/tenerife_site/calculadora.html stays in the repo and is served again only with TENERIFE_SHOW_FIGURES=1.
# calc.js is not in app/static any more (app/tenerife_site/data/calc.js, not served); the guard also answers 404.
FIGURE_ONLY_PAGES = ("calculadora",)
CALC_JS_RX = re.compile(r"^/static/tenerife/(?:.*/)?calc\.js(?:\.gz|\.br|\.map)?$", re.I)


def show_figures() -> bool:
    return os.environ.get("TENERIFE_SHOW_FIGURES", "").strip() == "1"


def figures_blocked(path: str) -> bool:
    return not show_figures() and bool(FIGURE_STATIC_RX.match(path or "") or CALC_JS_RX.match(path or ""))


def figure_page_hidden(page: str) -> bool:
    return page in FIGURE_ONLY_PAGES and not show_figures()


def _figure_page_moved():
    return redirect(SITE_PREFIX + "/", code=302)


log = logging.getLogger("artemis.tenerife")

# ---- runtime config of the built pages (the static HTML is committed; these two never are)
# TENERIFE_WHATSAPP  E.164 with "+", e.g. +440000000000. Footer «Контакты»: «WhatsApp: » + a wa.me link whose text is
#                    the number. The build leaves WA_SLOT where the copy has the phone; unset/invalid -> the contact
#                    is left out (never a placeholder) and a warning WITHOUT the value is logged.
# TENERIFE_INDEXING  "1" -> /tenerife/ pages indexable and in sitemap.xml; unset/anything else -> every page gets
#                    <meta name="robots" content="noindex, nofollow"> + X-Robots-Tag and none is in the
#                    sitemap (until the founder approves numbers and prices).
WA_SLOT = "<li data-tenerife-whatsapp hidden></li>"
_WA_RX = re.compile(r"\+[1-9]\d{7,14}")
_ROBOTS_META = '<meta name="robots" content="noindex, nofollow">'
_warned = set()


def tenerife_indexing() -> bool:
    return os.environ.get("TENERIFE_INDEXING", "").strip() == "1"


def whatsapp_number() -> str | None:
    raw = os.environ.get("TENERIFE_WHATSAPP", "").strip()
    if _WA_RX.fullmatch(raw):
        return raw
    if "wa" not in _warned:  # once per process; never the value itself
        _warned.add("wa")
        log.warning("TENERIFE_WHATSAPP %s: WhatsApp contact hidden on /tenerife/ pages",
                    "is not set" if not raw else "is not E.164 (+ and 8-15 digits)")
    return None


def whatsapp_display(num: str) -> str:
    """+440000000000 -> «+44 0000 000000» (UK mobile); other numbers: «+» and the digits as given."""
    d = num[1:]
    if d.startswith("44") and len(d) == 12:
        return f"+44 {d[2:6]} {d[6:]}"
    return num


def whatsapp_li(num: str) -> str:
    shown = whatsapp_display(num)
    return (f'<li class="f-wa">WhatsApp: <a href="https://wa.me/{num[1:]}" aria-label="WhatsApp: {shown}">'
            f'{shown.replace(" ", "&nbsp;")}</a></li>')


def _finish(page: str) -> str:
    """Fill the runtime slots of a built page (see above)."""
    num = whatsapp_number()
    if num:
        page = page.replace(WA_SLOT, whatsapp_li(num))
    else:
        page = re.sub(r"[ \t]*" + re.escape(WA_SLOT) + r"\n?", "", page)
    if not tenerife_indexing() and _ROBOTS_META not in page:
        page = page.replace('<meta charset="utf-8">\n', '<meta charset="utf-8">\n' + _ROBOTS_META + "\n", 1)
    return page


def _site_page(name: str):
    f = SITE_DIR / f"{name}.html"
    if not f.is_file():
        return make_response("Not found", 404)
    resp = make_response(_finish(f.read_text(encoding="utf-8")))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    if not tenerife_indexing():  # QA PS-03: header as well as the meta, legal pages included
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
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
    # v2 layout (QA T3-09): static pages built by build_v3.py; the legal text itself stays in
    # app/templates/tenerife/{impressum,privacy}.html (body block, copied verbatim by the build)
    return _site_page(request.path.rstrip("/").rsplit("/", 1)[-1])


@bp.route(SITE_PREFIX + "/<page>/")
def site_page(page: str):
    if page not in SITE_PAGES or page in UNPUBLISHED_PAGES:
        return make_response("Not found", 404)
    if figure_page_hidden(page):
        return _figure_page_moved()
    return _site_page(page)


@bp.route(SITE_PREFIX + "/<page>")
@bp.route(SITE_PREFIX + "/<page>.html")
def site_legacy(page: str):
    page = page[:-5] if page.endswith(".html") else page
    if page == "index":
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if figure_page_hidden(page):
        return _figure_page_moved()
    if (page in SITE_PAGES or page in LEGAL_PAGES) and page not in UNPUBLISHED_PAGES:
        return redirect(_with_query(f"{SITE_PREFIX}/{page}/"), code=301)
    return make_response("Not found", 404)


def _safe_back(page: str) -> str:
    """Where a no-JS form submit returns to: only our own Tenerife pages."""
    if page.startswith(SITE_PREFIX + "/") and "//" not in page and "\\" not in page and len(page) < 60:
        return page.split("?")[0].split("#")[0]
    return SITE_PREFIX + "/"


def _payload() -> tuple[dict, bool]:
    if request.is_json:
        return (request.get_json(silent=True) or {}), True
    return request.form.to_dict(), False


# No-JS answers (QA T3-05): the v2 page shell built by build_v3.py (app/tenerife_site/_notice.html) with
# {{NOTICE_*}} slots; Flask fills them with escaped text. Strings: C13 states (DESIGN.md) and the server errors.
THANKS_URL = SITE_PREFIX + "/gracias/"
# Form messages: copy_v3/17_forma.md «Сообщения формы», verbatim (tests/test_tenerife_r4.py checks them against
# build_v3.form_messages(); the page gets the same texts as data-msg-* for waitlist.js).
FORM_MSG = {
    "ok-title": "Спасибо! Вы в очереди.",
    "ok-next": "Заявка уходит команде проекта в Telegram и на info@artemisresort.com. Мы свяжемся с вами.",
    "server": "Не удалось отправить заявку. Попробуйте ещё раз или напишите нам на info@artemisresort.com.",
    "rate": "С этого подключения отправлено слишком много заявок. Повторите попытку позже или напишите нам на "
            "info@artemisresort.com.",
    "name": "Укажите имя.",
    "contact": "Укажите контакт: email, телефон или Telegram.",
    "language": "Выберите язык общения.",
    "consent": "Отметьте согласие на обработку данных.",
}
THANKS_TITLE = FORM_MSG["ok-title"]
THANKS_TEXT = FORM_MSG["ok-next"]
BACK_SITE = "← К сайту проекта"
BACK_FORM = "← Назад к форме"


_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _notice(status: int, title: str, text: str, back: str, back_label: str):
    shell = _finish((SITE_DIR / "_notice.html").read_text(encoding="utf-8"))
    if not text:  # error answers: the message is the heading, no empty lead paragraph
        shell = shell.replace('<p class="hero__lead">{{NOTICE_TEXT}}</p>\n', "")
    for key, val in (("TITLE", title), ("TEXT", text), ("BACK", back), ("BACK_LABEL", back_label)):
        val = html.escape(val, quote=True)
        if key in ("TITLE", "TEXT"):  # the form texts name info@…: keep it out of Cloudflare's e-mail obfuscation
            val = _EMAIL_RX.sub(lambda m: "<!--email_off-->" + m.group(0) + "<!--/email_off-->", val)
        shell = shell.replace("{{NOTICE_%s}}" % key, val)
    return _noindex(make_response(shell, status, {"Content-Type": "text/html; charset=utf-8"}))


@bp.route(THANKS_URL)
def thanks():
    back = _safe_back(request.args.get("back", ""))
    return _notice(200, THANKS_TITLE, THANKS_TEXT, back, BACK_SITE)


def _reply(is_json: bool, ok: bool, status: int = 200, error: str = "", back: str = "", field: str = ""):
    if is_json:
        body = {"ok": ok}
        if error:
            body["error"] = error
        if field:
            body["field"] = field
        return jsonify(body), status
    back = back or SITE_PREFIX + "/"
    if ok:
        return redirect(THANKS_URL + "?" + urllib.parse.urlencode({"back": back}), code=303)
    return _notice(status, error or FORM_MSG["server"], "", back + "#ochered", BACK_FORM)


@bp.route("/api/tenerife/waitlist", methods=["POST"])
def waitlist():
    d, is_json = _payload()

    # Honeypot: bots fill the hidden field. Pretend success, store nothing.
    if str(d.get(HONEYPOT_FIELD) or "").strip():
        current_app.logger.info("tenerife waitlist: honeypot hit, dropped")
        return jsonify({"ok": True}) if is_json else redirect(SITE_PREFIX + "/", code=303)

    name = " ".join(str(d.get("name") or "").split())[:120]
    contact = " ".join(str(d.get("contact") or "").split())[:200]
    language = str(d.get("language") or "").strip().lower()[:5]
    consent = str(d.get("consent")).lower() in {"1", "true", "on", "yes"}
    page = str(d.get("page") or "").strip()[:200] or urllib.parse.urlsplit(request.referrer or "").path
    page = page or SITE_PREFIX + "/"
    back = _safe_back(page)

    if not name:
        return _reply(is_json, False, 400, FORM_MSG["name"], back, "name")
    if len(contact) < 5:
        return _reply(is_json, False, 400, FORM_MSG["contact"], back, "contact")
    if language not in WAITLIST_LANGS:
        return _reply(is_json, False, 400, FORM_MSG["language"], back, "language")
    if not consent:
        return _reply(is_json, False, 400, FORM_MSG["consent"], back, "consent")

    # calculator fields (calc_m2, calc_step, calc_pay): recomputed with the current model.json and stored
    # with its version as ok / mismatch / invalid (tenerife_calc.py); never blocks the lead
    model = None
    try:
        model = load_model()
        calc, problems = check_calc(d, model)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as e:
        model = None
        calc = {"calc_status": "invalid", "calc_note": "model.json не прочитан"} if any(
            d.get(k) not in (None, "") for k in ("calc_m2", "calc_step", "calc_pay")) else None
        problems = [f"model.json unavailable: {type(e).__name__}"] if calc else []
    if problems:
        current_app.logger.warning("tenerife waitlist calc %s: %s", calc["calc_status"], "; ".join(problems))

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
            return _reply(is_json, False, 429, FORM_MSG["rate"], back)
        cols = ("name", "contact", "language", "page", "consent", "client_hash", "created_at")
        vals = (name, contact, language, page, 1, client, now.isoformat())
        if calc:
            cols += tuple(c for c, _ in CALC_COLUMNS)
            vals += tuple(calc.get(c) for c, _ in CALC_COLUMNS)
        conn.execute(
            f"INSERT INTO tenerife_waitlist({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals
        )
        conn.commit()
    finally:
        conn.close()

    if calc:
        notify_lead("Tenerife waitlist", name, contact, language, page, calc=calc, model=model)
    else:
        notify_lead("Tenerife waitlist", name, contact, language, page)
    return _reply(is_json, True, back=back)


def waitlist_rows(conn: sqlite3.Connection):
    init_waitlist_db(conn)
    return conn.execute(
        "SELECT id,name,contact,language,page,created_at FROM tenerife_waitlist ORDER BY id DESC"
    ).fetchall()
