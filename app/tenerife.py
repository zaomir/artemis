"""Artemis de la Cruz — RU preview (noindex) + free waitlist.

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
SITE_PAGES = ("norte", "producto", "inversores", "calculadora", "alquiler", "energia", "construccion",
              "proceso", "faq", "simon", "mercado", "boris", "equipo")
SITE_URL = "https://artemisresort.com"


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
                    lambda _:funnel_http.form(loc,request.path),page,count=1)
        page=page.replace('</body>','<script src="/static/tenerife/site/funnel.js" defer></script>\n</body>')
    return page


ALL_LANGS = ("en", "ru", "es", "de", "fr")
LOCALES = ("ru", "es", "de", "fr")   # EN — корень /tenerife/, остальные — /tenerife/<locale>/

# Гео-открытие (02.11.2026; P1-02 06.11.2026): страну посетителя встречает корень сайта `/`, а не /tenerife/.
# /tenerife/ — канонический URL английской главной (canonical, hreflang en и x-default всех страниц ведут сюда),
# поэтому он обязан отвечать 200 EN, а не 302 → DE. Сайт не пишет cookie и не трогает хранилище (privacy §7),
# выбор не запоминается: уйти с гео-редиректа можно ссылкой /tenerife/?lang=en. Cloudflare отдаёт страну в CF-IPCountry.
GEO_LOCALES = {
    "ES": "es",
    "DE": "de", "AT": "de", "CH": "de",
    "FR": "fr", "BE": "fr", "LU": "fr", "MC": "fr",
}


def geo_locale() -> str | None:
    """Язык входа по стране Cloudflare: "es"/"de"/"fr" или None (EN / неизвестная страна)."""
    return GEO_LOCALES.get((request.headers.get("CF-IPCountry") or "").strip().upper())


def entry_target() -> str:
    """Куда корень `/` уводит посетителя: язык страны, EN для неизвестной страны.
    ?lang= сильнее страны: en → английская главная /tenerife/, остальные локали → их префикс."""
    wanted = (request.args.get("lang") or "").strip().lower()
    if wanted == "en":
        return SITE_PREFIX + "/"
    if wanted in ALL_LANGS:
        return f"{SITE_PREFIX}/{wanted}/"
    geo = geo_locale()
    return f"{SITE_PREFIX}/{geo}/" if geo else SITE_PREFIX + "/"


def _site_page(name: str, locale: str = "en"):
    base = SITE_DIR if locale == "en" else SITE_DIR / locale
    f = base / f"{name}.html"
    if not f.is_file():
        return _not_found(locale)
    resp = make_response(_finish(f.read_text(encoding="utf-8")))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    if not tenerife_indexing():  # QA PS-03: header as well as the meta, legal pages included
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def _not_found(locale: str = ""):
    if locale not in ALL_LANGS:
        parts = request.path.strip("/").split("/")
        locale = parts[1] if len(parts) > 1 and parts[0] == "tenerife" and parts[1] in LOCALES else "en"
    base = SITE_DIR if locale == "en" else SITE_DIR / locale
    f = base / "_404.html"
    body = _finish(f.read_text(encoding="utf-8")) if f.is_file() else "Not found"
    resp = make_response(body, 404)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@bp.route(SITE_PREFIX)
def site_noslash():
    return redirect(SITE_PREFIX + "/", code=301)


@bp.route(SITE_PREFIX + "/")
def site_index():
    # P1-02: /tenerife/ — это EN-главная, canonical и hreflang en/x-default всех страниц, поэтому гео-редиректа
    # здесь нет: он живёт в корне сайта (`/`, app.py:root -> tenerife.entry_target()). ?lang=<code> как раньше:
    # en -> 200 /tenerife/, остальные локали -> 302 на свой префикс (так переключатель уводит на язык).
    wanted = (request.args.get("lang") or "").strip().lower()
    if wanted == "en":
        return _site_page("index")
    if wanted in ALL_LANGS:
        return redirect(_with_query(f"{SITE_PREFIX}/{wanted}/"), code=302)
    return _site_page("index")


@bp.route('/tenerife/actualizaciones/')
@bp.route('/tenerife/<locale>/actualizaciones/')
@bp.route('/tenerife/actualizaciones/<slug>/')
@bp.route('/tenerife/<locale>/actualizaciones/<slug>/')
def project_news(locale='en', slug=None):
    """Explicit nested article route, never an arbitrary filesystem path."""
    if locale not in ALL_LANGS:
        return _not_found()
    if '/tenerife/en/' in request.path:
        return redirect(_with_query('/tenerife/actualizaciones/' + (slug+'/' if slug else '')),code=301)
    if slug and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug):
        return _not_found(locale)
    base = SITE_DIR if locale=='en' else SITE_DIR/locale
    target = base / ('actualizaciones/'+slug+'.html' if slug else 'actualizaciones.html')
    if not target.is_file():
        return _not_found(locale)
    content=_finish(target.read_text(encoding='utf-8'))
    if funnel_http.enabled():
        content=content.replace('</main>','<section class="section"><div class="wrap">'+funnel_http.form(locale,request.path,'newsletter_only')+'</div></section></main>')
        content=content.replace('</body>','<script src="/static/tenerife/site/funnel.js" defer></script></body>')
    response=make_response(content)
    response.headers['Content-Type']='text/html; charset=utf-8'
    # Per-route policy: adding news must not globally enable investor indexing.
    response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


# P1-02: английская локаль живёт в корне (/tenerife/<page>/), а не под /en/. Старые /tenerife/en/* (их в отчёте 14:
# 12 страниц + impressum + privacy) отвечают одним 301 на рабочий unprefixed URL, а не 404. EN-главная
# /tenerife/en/ -> /tenerife/ обрабатывается в site_page()/site_legacy().
def _en_page_target(page: str) -> str | None:
    """Рабочий EN-URL страницы или None, если такой страницы нет (тогда 404, а не 301 в 404)."""
    return _canonical_target(page)


def _canonical_target(page: str, locale: str = "en") -> str | None:
    page = "inversores" if page == "acciones" else page
    prefix = f"{SITE_PREFIX}/" + (f"{locale}/" if locale != "en" else "")
    if page == "index":
        return prefix
    if page in SITE_PAGES or page in LEGAL_PAGES:
        return f"{prefix}{page}/"
    return None


@bp.route(SITE_PREFIX + "/<locale>/<page>")
@bp.route(SITE_PREFIX + "/<locale>/<page>.html")
def site_locale_legacy(locale: str, page: str):
    """Clean URL of a locale page: /tenerife/de/norte and /tenerife/de/norte.html -> 301 /tenerife/de/norte/."""
    page = page[:-5] if page.endswith(".html") else page
    if locale == "en":   # /tenerife/en/simon[/.html] -> /tenerife/simon/ (P1-02, без промежуточного /en/)
        target = _en_page_target(page)
        return redirect(_with_query(target), code=301) if target else _not_found()
    if locale not in LOCALES:
        return _not_found()
    if page == "acciones":
        return redirect(_with_query(_canonical_target(page, locale)), code=301)
    if page == "index":
        return redirect(_with_query(f"{SITE_PREFIX}/{locale}/"), code=301)
    if page in SITE_PAGES or page in LEGAL_PAGES:
        return redirect(_with_query(f"{SITE_PREFIX}/{locale}/{page}/"), code=301)
    return _not_found()


@bp.route(SITE_PREFIX + "/<locale>/<page>/")
def site_locale_page(locale: str, page: str):
    if locale == "en":   # P1-02: /tenerife/en/<page>/ -> 301 /tenerife/<page>/ (14 URL больше не 404)
        target = _en_page_target(page)
        return redirect(_with_query(target), code=301) if target else _not_found()
    if locale not in LOCALES:
        return _not_found()
    if page == "acciones":
        return redirect(_with_query(_canonical_target(page, locale)), code=301)
    if page not in SITE_PAGES and page not in LEGAL_PAGES:
        return _not_found()
    return _site_page(page, locale)


@bp.route(SITE_PREFIX + "/impressum/")
@bp.route(SITE_PREFIX + "/privacy/")
def legal_page():
    # v2 layout (QA T3-09): static pages built by build_v3.py; the legal text itself stays in
    # app/templates/tenerife/{impressum,privacy}.html (body block, copied verbatim by the build)
    return _site_page(request.path.rstrip("/").rsplit("/", 1)[-1])


@bp.route(SITE_PREFIX + "/<page>/")
def site_page(page: str):
    """One segment under /tenerife/: the home of a locale (/tenerife/ru/), the EN home (/tenerife/),
    an EN page or legal page, everything else 404."""
    if page == "en":
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)   # EN живёт в корне (P1-02)
    if page in LOCALES:
        return _site_page("index", page)
    if page == "acciones":
        return redirect(_with_query(_canonical_target(page)), code=301)
    if page not in SITE_PAGES and page not in LEGAL_PAGES:
        return _not_found()
    return _site_page(page)


@bp.route(SITE_PREFIX + "/<page>")
@bp.route(SITE_PREFIX + "/<page>.html")
def site_legacy(page: str):
    page = page[:-5] if page.endswith(".html") else page
    if page == "index":
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if page == "en":   # /tenerife/en -> /tenerife/ (P1-02; раньше 404)
        return redirect(_with_query(SITE_PREFIX + "/"), code=301)
    if page in LOCALES:   # /tenerife/ru -> /tenerife/ru/
        return redirect(_with_query(f"{SITE_PREFIX}/{page}/"), code=301)
    if page == "acciones":
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
    "ok-title": "Спасибо! Заявка на расчёт принята.",
    "ok-next": "Команда свяжется с вами по указанному контакту, пришлёт персональный расчёт и объяснит срок и порядок выхода.",
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


def _i18n():
    """Строки формы и подписей для ES/DE/FR: общий словарь с сайтом (scripts/tenerife_site_build/i18n_strings.json).
    RU — канон в этом файле; если словаря нет (урезанный деплой), локали получают русские строки."""
    try:
        return json.loads((Path(__file__).resolve().parent.parent / "scripts" / "tenerife_site_build"
                           / "i18n_strings.json").read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001 — сайт важнее словаря
        return {}


def _page_locale(path: str | None = None) -> str:
    """Язык страницы по адресу: /tenerife/es/... -> es, всё остальное (EN в корне и RU) -> как есть."""
    parts = (path or request.path).strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "tenerife" and parts[1] in LOCALES:
        return parts[1]
    return "en"


def _payload_locale(d: dict | None = None) -> str:
    """Язык заявки: страница, с которой пришла форма (скрытое поле page); без неё — русский, как было до локалей."""
    page = str((d or {}).get("page") or "")
    parts = page.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "tenerife":
        return parts[1] if parts[1] in LOCALES else "en"
    return "ru"


def _form_msg(key: str, locale: str = "") -> str:
    loc = locale or _page_locale()
    if loc == "ru":
        return FORM_MSG[key]
    return _i18n().get(loc, {}).get("msgs", {}).get(key, FORM_MSG[key])


def _back_label(which: str, locale: str = "") -> str:
    loc = locale or _page_locale()
    if loc in ("ru", "en"):
        if loc == "ru":
            return BACK_SITE if which == "site" else BACK_FORM
        return _i18n().get("en", {}).get("back", {}).get(which, BACK_SITE if which == "site" else BACK_FORM)
    return _i18n().get(loc, {}).get("back", {}).get(which, BACK_SITE if which == "site" else BACK_FORM)


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


@bp.route("/api/tenerife/waitlist", methods=["POST"])
def waitlist():
    d, is_json = _payload()
    loc = _payload_locale(d)

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
    typed=funnel_http.enabled() and bool(d.get('contact_type'))
    newsletter_only=typed and d.get('intent')=='newsletter_only'
    if typed:
        try:
            normalized=funnel_store.normalize(d)
        except ValueError as exc:
            field=str(exc)
            return _reply(is_json,False,400,_form_msg('contact' if field in ('contact','newsletter_email') else 'server',loc),back,field,locale=loc)

    if not name and not newsletter_only:
        return _reply(is_json, False, 400, _form_msg("name", loc), back, "name", locale=loc)
    if not typed and not valid_contact(contact):
        return _reply(is_json, False, 400, _form_msg("contact", loc), back, "contact", locale=loc)
    if language not in WAITLIST_LANGS:
        return _reply(is_json, False, 400, _form_msg("language", loc), back, "language", locale=loc)
    if not consent:
        return _reply(is_json, False, 400, _form_msg("consent", loc), back, "consent", locale=loc)

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
        if typed:
            funnel_store.migrate(conn)
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        if typed and conn.execute('SELECT 1 FROM artemis_events WHERE submission_id=?',(d['submission_id'],)).fetchone():
            try:
                funnel_store.capture(conn,d,funnel_http.secret(),now=now,client_hash=client)
            except ValueError:
                return _reply(is_json,False,409,_form_msg('server',loc),back,locale=loc)
            conn.commit()
            return _typed_capture_reply(is_json,loc,newsletter_only)
        recent = conn.execute(
            "SELECT COUNT(*) FROM tenerife_waitlist WHERE client_hash=? AND created_at>=?",
            (client, since),
        ).fetchone()[0]
        if typed:
            recent=conn.execute('SELECT COUNT(*) FROM artemis_events WHERE client_hash=? AND created_at>=?',(client,since)).fetchone()[0]
        if recent >= RATE_LIMIT_MAX:
            return _reply(is_json, False, 429, _form_msg("rate", loc), back, locale=loc)
        cols = ("name", "contact", "language", "page", "consent", "client_hash", "created_at")
        vals = (name, contact, language, page, 1, client, now.isoformat())
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
        conn.commit()
    finally:
        conn.close()

    if newsletter_only:
        return _typed_capture_reply(is_json,loc,True)
    if calc:
        notify_lead("Tenerife waitlist", name, contact, language, page, calc=calc, model=model)
    else:
        notify_lead("Tenerife waitlist", name, contact, language, page)
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
        "SELECT id,name,contact,language,page,created_at FROM tenerife_waitlist ORDER BY id DESC"
    ).fetchall()
