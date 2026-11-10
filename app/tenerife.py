"""Artemis Tenerife — EN-only public site (EN r2 / t122u).

Routes (Blueprint, registered in app.py):
  GET  /tenerife/…                 English pages (Spanish slugs) from copy_en via build_v3
  GET  /tenerife/{ru,es,de,fr}/…   301 → EN equivalent (or /tenerife/)
  GET  /tenerife/calculadora…      301 → /tenerife/condiciones/ (Terms; page 05)
  GET  /tenerife/condiciones/      Terms (EN copy)
  GET  /tenerife/inversores/       Investors (EN copy)
  GET  /tenerife/acciones/         Shares (EN copy; not aliased to inversores)
  GET  /tenerife/equipo/           301 → /tenerife/ (no EN equipo page in copy_en 01–18)
  GET  /tenerife-preview/…         301 → matching /tenerife/… page
  POST /api/tenerife/waitlist      waitlist (+ optional funnel/CRM plumbing from main)

Public Tenerife is English only. Geo entry always lands on EN. Default noindex unless
TENERIFE_INDEXING=1. model.json / calc.js are never served (404).
"""
from __future__ import annotations

import datetime
import hashlib
import html
import hmac
import ipaddress
import json
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
from contact_format import valid_contact
import funnel_http
import funnel_store

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
    migrate_co_investment(conn)


def migrate_co_investment(conn: sqlite3.Connection) -> None:
    """Idempotent: co_investment flag on tenerife_waitlist (optional waitlist checkbox, t15u)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(tenerife_waitlist)")}
    if "co_investment" not in have:
        conn.execute("ALTER TABLE tenerife_waitlist ADD COLUMN co_investment INTEGER NOT NULL DEFAULT 0")


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
    if funnel_http.enabled() and request.path.startswith('/tenerife/'):
        # Dynamic form IDs are per response; never share them through a cache.
        resp.headers['Cache-Control']='no-store'
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
    parts = sub.strip("/").split("/")
    locale = parts.pop(0) if parts and parts[0] in ALL_LANGS else "en"
    first = (parts[0] if parts else "index").removesuffix(".html")
    target = _canonical_target(first, locale) or "/tenerife/"
    return redirect(_with_query(target), code=301)


def _with_query(url: str) -> str:
    qs = request.query_string.decode("latin-1")
    return f"{url}?{qs}" if qs else url


# --- /tenerife/ prod (static RU pages, clean URLs) ---------------------------
SITE_PREFIX = "/tenerife"
SITE_DIR = Path(__file__).resolve().parent / "tenerife_site"
SITE_PAGES = ("norte", "producto", "condiciones", "energia", "construccion", "proceso", "faq", "simon",
              "mercado", "boris", "inversores")
SITE_URL = "https://artemisresort.com"
# EN r2+: calculator → condiciones; equipo/acciones/alquiler retired (t15u).
MOVED_PAGES = {"calculadora": "condiciones", "equipo": "", "acciones": "inversores", "alquiler": ""}
# Never public: model.json & calc.js (404 before static).
FIGURE_STATIC_RX = re.compile(r"^/static/tenerife/(?:.*/)?[^/]*\.json(?:\.gz|\.br)?$", re.I)
CALC_JS_RX = re.compile(r"^/static/tenerife/(?:.*/)?calc\.js(?:\.gz|\.br|\.map)?$", re.I)


def figures_blocked(path: str) -> bool:
    return bool(FIGURE_STATIC_RX.match(path or "") or CALC_JS_RX.match(path or ""))



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
    if funnel_http.enabled() and 'id="wl-form"' in page:
        locale_match=re.search(r'<html lang="([a-z]+)"',page)
        loc=locale_match.group(1) if locale_match else 'en'
        page=re.sub(r'<form\b(?=[^>]*\bid="wl-form")[\s\S]*?</form>',
                    lambda match:funnel_http.form(loc,request.path,values=funnel_http.compatibility_fields(match[0])),page,count=1)
        page=page.replace('</body>','<script src="/static/tenerife/site/funnel.js" defer></script>\n</body>')
    if funnel_http.enabled():page=funnel_http.carry_attribution(page)
    return page


ALL_LANGS = ("en", "ru", "es", "de", "fr")  # recognised only so old locale URLs can 301 → EN
LOCALES = ("ru", "es", "de", "fr")

# EN r2 / t122u: public Tenerife is English only. Geo never sends visitors to ES/DE/FR/RU.
GEO_LOCALES = {}  # disabled


def geo_locale() -> str | None:
    """Always None: EN-only public Tenerife (t122u / Lead GO 05.11.2026)."""
    return None


def entry_target() -> str:
    """Site root `/` always opens the English Tenerife home. ?lang=* is ignored for locale choice
    (non-EN values still land on /tenerife/; old /tenerife/<locale>/ URLs 301 to EN)."""
    return SITE_PREFIX + "/"


def _site_page(name: str, locale: str = "en"):
    # EN r2: only English HTML is built; locale arg kept for call-site compat and ignored.
    f = SITE_DIR / f"{name}.html"
    if not f.is_file():
        return _not_found()
    resp = make_response(_finish(f.read_text(encoding="utf-8")))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    if not tenerife_indexing():
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def _not_found(locale: str = ""):
    f = SITE_DIR / "_404.html"
    body = _finish(f.read_text(encoding="utf-8")) if f.is_file() else "Not found"
    resp = make_response(body, 404)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@bp.route(SITE_PREFIX)
def site_noslash():
    return redirect(SITE_PREFIX + "/", code=301)


@bp.route(SITE_PREFIX + "/")
def site_index():
    # EN r2: always English home. ?lang=* does not open non-EN locales (those URLs 301 → EN).
    return _site_page("index")


@bp.route('/tenerife/actualizaciones/')
@bp.route('/tenerife/<locale>/actualizaciones/')
@bp.route('/tenerife/actualizaciones/<slug>/')
@bp.route('/tenerife/<locale>/actualizaciones/<slug>/')
def project_news(locale='en', slug=None):
    """Project diary — EN only; other locale prefixes 301 to EN."""
    if locale not in ALL_LANGS:
        return _not_found()
    en_url = '/tenerife/actualizaciones/' + (slug + '/' if slug else '')
    if locale != 'en':
        return redirect(_with_query(en_url), code=301)
    if slug and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        return _not_found()
    target = SITE_DIR / ('actualizaciones/' + slug + '.html' if slug else 'actualizaciones.html')
    if not target.is_file():
        return _not_found()
    content = _finish(target.read_text(encoding='utf-8'))
    if funnel_http.enabled():
        content = content.replace(
            '</main>',
            '<section class="section"><div class="wrap">'
            + funnel_http.form('en', request.path, 'newsletter_only')
            + '</div></section></main>')
        content = content.replace(
            '</body>', '<script src="/static/tenerife/site/funnel.js" defer></script></body>')
    response = make_response(content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


# P1-02: английская локаль живёт в корне (/tenerife/<page>/), а не под /en/. Старые /tenerife/en/* (их в отчёте 14:
# 12 страниц + impressum + privacy) отвечают одним 301 на рабочий unprefixed URL, а не 404. EN-главная
# /tenerife/en/ -> /tenerife/ обрабатывается в site_page()/site_legacy().
def _en_page_target(page: str) -> str | None:
    """Рабочий EN-URL страницы или None, если такой страницы нет (тогда 404, а не 301 в 404)."""
    return _canonical_target(page)


def _canonical_target(page: str, locale: str = "en") -> str | None:
    # EN r2: always the English URL. acciones is its own page; calculadora/equipo via MOVED_PAGES.
    if page in MOVED_PAGES:
        dest = MOVED_PAGES[page]
        return SITE_PREFIX + "/" if dest == "" else f"{SITE_PREFIX}/{dest}/"
    if page == "index":
        return SITE_PREFIX + "/"
    if page in SITE_PAGES or page in LEGAL_PAGES:
        return f"{SITE_PREFIX}/{page}/"
    return None


@bp.route(SITE_PREFIX + "/<locale>/<page>")
@bp.route(SITE_PREFIX + "/<locale>/<page>.html")
def site_locale_legacy(locale: str, page: str):
    """Any /tenerife/<locale>/… → 301 to the English equivalent (EN r2)."""
    page = page[:-5] if page.endswith(".html") else page
    if locale not in ALL_LANGS:
        return _not_found()
    target = _canonical_target(page)
    return redirect(_with_query(target), code=301) if target else _not_found()


@bp.route(SITE_PREFIX + "/<locale>/<page>/")
def site_locale_page(locale: str, page: str):
    """EN r2: non-EN (and /en/) locale pages permanently redirect to the EN URL."""
    if locale not in ALL_LANGS:
        return _not_found()
    target = _canonical_target(page)
    return redirect(_with_query(target), code=301) if target else _not_found()


@bp.route(SITE_PREFIX + "/impressum/")
@bp.route(SITE_PREFIX + "/privacy/")
def legal_page():
    # v2 layout (QA T3-09): static pages built by build_v3.py; the legal text itself stays in
    # app/templates/tenerife/{impressum,privacy}.html (body block, copied verbatim by the build)
    return _site_page(request.path.rstrip("/").rsplit("/", 1)[-1])


@bp.route(SITE_PREFIX + "/<page>/")
def site_page(page: str):
    """One segment under /tenerife/: EN page, legal, moved slug, or locale home → 301 EN."""
    if page == "en" or page in LOCALES:
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if page in MOVED_PAGES:
        return redirect(_with_query(_canonical_target(page)), code=301)
    if page not in SITE_PAGES and page not in LEGAL_PAGES:
        return _not_found()
    return _site_page(page)


@bp.route(SITE_PREFIX + "/<page>")
@bp.route(SITE_PREFIX + "/<page>.html")
def site_legacy(page: str):
    page = page[:-5] if page.endswith(".html") else page
    if page == "index" or page == "en" or page in LOCALES:
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if page in MOVED_PAGES:
        return redirect(_with_query(_canonical_target(page)), code=301)
    if page in SITE_PAGES or page in LEGAL_PAGES:
        return redirect(_with_query(f"{SITE_PREFIX}/{page}/"), code=301)
    return _not_found()


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
    "ok-title": "Thank you! You're in the queue.",
    "ok-next": "Your request goes to the project team on Telegram and to info@artemisresort.com. We will be in touch.",
    "server": "We couldn't send your request. Please try again or email us at info@artemisresort.com.",
    "rate": "Too many requests have been sent from this connection. Please try again later or email us at "
            "info@artemisresort.com.",
    "name": "Please enter your name.",
    "contact": "Please enter a contact: email, phone or Telegram.",
    "language": "Please choose your preferred language.",
    "consent": "Please tick the box to consent to data processing.",
}
THANKS_TITLE = FORM_MSG["ok-title"]
THANKS_TEXT = FORM_MSG["ok-next"]
BACK_SITE = "← Back to the project site"
BACK_FORM = "← Back to the form"


def _i18n():
    """Строки формы и подписей для ES/DE/FR: общий словарь с сайтом (scripts/tenerife_site_build/i18n_strings.json).
    RU — канон в этом файле; если словаря нет (урезанный деплой), локали получают русские строки."""
    try:
        return json.loads((Path(__file__).resolve().parent.parent / "scripts" / "tenerife_site_build"
                           / "i18n_strings.json").read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001 — сайт важнее словаря
        return {}


def _page_locale(path: str | None = None) -> str:
    """EN r2: public pages are English; locale prefixes only exist as 301 sources."""
    return "en"


def _payload_locale(d: dict | None = None) -> str:
    """EN r2: form replies use English strings."""
    return "en"


def _form_msg(key: str, locale: str = "") -> str:
    # EN r2: public replies use the English FORM_MSG (copy_en/17), never locale i18n leftovers.
    return FORM_MSG[key]


def _back_label(which: str, locale: str = "") -> str:
    return BACK_SITE if which == "site" else BACK_FORM


_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _notice(status: int, title: str, text: str, back: str, back_label: str, locale: str = ""):
    loc = locale or _page_locale(back or "")
    notice = SITE_DIR / loc / "_notice.html"
    shell = _finish((notice if notice.is_file() else SITE_DIR / "_notice.html").read_text(encoding="utf-8"))
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
    loc = _payload_locale({"page": back})   # язык страницы, с которой пришла форма
    return _notice(200, _form_msg("ok-title", loc), _form_msg("ok-next", loc), back,
                   _back_label("site", loc), locale=loc)


def _reply(is_json: bool, ok: bool, status: int = 200, error: str = "", back: str = "", field: str = "",
           locale: str = ""):
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
    return _notice(status, error or _form_msg("server", locale), "", back + "#ochered", _back_label("form", locale))


def _capture_error(data,is_json,status,error,back='',field='',locale='en'):
    if not is_json and data.get('contact_type'):
        return funnel_http.form_error(data,error,status,locale)
    return _reply(is_json,False,status,error,back,field,locale=locale)


@bp.route("/api/tenerife/waitlist", methods=["POST"])
def waitlist():
    d, is_json = _payload()
    loc = _payload_locale(d)
    if d.get('contact_type') and not funnel_http.enabled():
        # A cached/new typed form must never silently downgrade into legacy
        # capture and lose its explicit subscription request during rollback.
        return _capture_error(d,is_json,503,_form_msg('server',loc),locale=loc)

    # Honeypot: bots fill the hidden field. Pretend success, store nothing.
    if str(d.get(HONEYPOT_FIELD) or "").strip():
        current_app.logger.info("tenerife waitlist: honeypot hit, dropped")
        return jsonify({"ok": True}) if is_json else redirect(SITE_PREFIX + "/", code=303)

    name = " ".join(str(d.get("name") or "").split())[:120]
    contact = " ".join(str(d.get("contact") or "").split())[:200]
    language = str(d.get("language") or "").strip().lower()[:5]
    consent = str(d.get("consent")).lower() in {"1", "true", "on", "yes"}
    raw_ci = d.get("co_investment")
    if isinstance(raw_ci, bool):
        co_investment = raw_ci
    else:
        co_investment = str(raw_ci or "").lower() in {"1", "true", "on", "yes"}
    page = str(d.get("page") or "").strip()[:200] or urllib.parse.urlsplit(request.referrer or "").path
    page = page or SITE_PREFIX + "/"
    back = _safe_back(page)
    typed=funnel_http.enabled() and bool(d.get('contact_type'))
    newsletter_only=typed and d.get('intent')=='newsletter_only'
    if typed:
        try:
            normalized=funnel_store.normalize(d)
            contact=normalized['contact']
            if newsletter_only:
                consent=normalized['newsletter_opt_in']
        except ValueError as exc:
            field=str(exc)
            key={'contact':'contact','newsletter_email':'contact','name':'name','language':'language',
                'consent':'consent','newsletter_opt_in':'consent'}.get(field,'server')
            return _capture_error(d,is_json,400,_form_msg(key,loc),back,field,locale=loc)

    if not name and not newsletter_only:
        return _capture_error(d,is_json,400,_form_msg("name",loc),back,"name",locale=loc)
    if not typed and not valid_contact(contact):
        return _capture_error(d,is_json,400,_form_msg("contact",loc),back,"contact",locale=loc)
    if language not in WAITLIST_LANGS:
        return _capture_error(d,is_json,400,_form_msg("language",loc),back,"language",locale=loc)
    if not consent:
        return _capture_error(d,is_json,400,_form_msg("consent",loc),back,"consent",locale=loc)

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
    conn = None
    try:
        conn = sqlite3.connect(_db_path(), timeout=5)
        init_waitlist_db(conn)
        if typed:
            funnel_store.migrate(conn)
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        if typed and conn.execute('SELECT 1 FROM artemis_events WHERE submission_id=?',(d['submission_id'],)).fetchone():
            try:
                funnel_store.capture(conn,d,funnel_http.secret(),now=now,client_hash=client)
            except ValueError:
                return _capture_error(d,is_json,409,_form_msg('server',loc),back,locale=loc)
            conn.commit()
            return _typed_capture_reply(is_json,loc,newsletter_only)
        recent = conn.execute(
            "SELECT COUNT(*) FROM tenerife_waitlist WHERE client_hash=? AND created_at>=?",
            (client, since),
        ).fetchone()[0]
        if typed:
            recent=conn.execute('SELECT COUNT(*) FROM artemis_events WHERE client_hash=? AND created_at>=?',(client,since)).fetchone()[0]
        if recent >= RATE_LIMIT_MAX:
            return _capture_error(d,is_json,429,_form_msg("rate",loc),back,locale=loc)
        cols = ("name", "contact", "language", "page", "consent", "co_investment", "client_hash", "created_at")
        vals = (name, contact, language, page, 1, 1 if co_investment else 0, client, now.isoformat())
        if calc:
            cols += tuple(c for c, _ in CALC_COLUMNS)
            vals += tuple(calc.get(c) for c, _ in CALC_COLUMNS)
        legacy=None
        if not newsletter_only:
            cursor=conn.execute(
                f"INSERT INTO tenerife_waitlist({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
            legacy=('tenerife_waitlist',cursor.lastrowid,now.isoformat())
        if typed:
            funnel_store.capture(conn,d,funnel_http.secret(),now=now,legacy=legacy,client_hash=client)
        elif os.environ.get('ARTEMIS_CRM_CAPTURE_ENABLED')=='1':
            from funnel_legacy import enqueue_row
            enqueue_row(conn,'tenerife_waitlist',cursor.lastrowid)
        conn.commit()
    except sqlite3.Error as exc:
        if conn:conn.rollback()
        if not typed:raise
        current_app.logger.warning('typed capture unavailable: %s',type(exc).__name__)
        return _capture_error(d,is_json,503,_form_msg('server',loc),back,locale=loc)
    finally:
        if conn:conn.close()

    if newsletter_only:
        return _typed_capture_reply(is_json,loc,True)
    if calc:
        notify_lead("Tenerife waitlist", name, contact, language, page, calc=calc, model=model,
                    co_investment=co_investment)
    else:
        notify_lead("Tenerife waitlist", name, contact, language, page, co_investment=co_investment)
    return _typed_capture_reply(is_json,loc) if typed else _reply(is_json, True, back=back)


def _typed_capture_reply(is_json,locale,newsletter_only=False):
    prefix='/tenerife/'+('' if locale=='en' else locale+'/')
    message=funnel_http.LABELS[locale]['newsletter_pending' if newsletter_only else 'success']
    if is_json:
        return jsonify(ok=True,next_url=prefix+'actualizaciones/',message=message,next_label=funnel_http.LABELS[locale]['diary'])
    return _notice(200,funnel_http.LABELS[locale]['done'],message,
                   prefix+'actualizaciones/',funnel_http.LABELS[locale]['diary'],locale=locale)


funnel_http.register(bp,_db_path)


def waitlist_rows(conn: sqlite3.Connection):
    init_waitlist_db(conn)
    return conn.execute(
        "SELECT id,name,contact,language,page,co_investment,created_at FROM tenerife_waitlist ORDER BY id DESC"
    ).fetchall()
