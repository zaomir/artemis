"""Artemis Resort & Spa — public project + investment site (Flask)."""
from __future__ import annotations

import datetime
import hmac
import html
import json
import math
import os
import re
import sqlite3
import subprocess
import urllib.parse
import urllib.request

from flask import (
    Flask,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
)

import logging

import ratelimit  # noqa: E402  (shared per-client limiter, QA P09)
import legal_i18n  # drop-in translations of the long legal texts (app/legal_translations/)

# A-13: Cloudflare Email Obfuscation (zone setting, stays ON) rewrites addresses / mailto links into
# /cdn-cgi/l/email-protection#…, which only decodes with JS (404 without it). Every rendered Crete page
# goes through the same email_off.wrap() as the Tenerife build, so addresses sit inside
# <!--email_off-->…<!--/email_off--> and reach the visitor as plain text / plain mailto links.
import importlib.util as _ilu  # noqa: E402

_EO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "tenerife_site_build", "email_off.py")


def _load_email_off(path=_EO_PATH):
    """The email_off module, or None (logged) when it is missing or broken (QA -43).

    A missing / broken module must not stop the app: pages are then served without the markers
    (Cloudflare obfuscates their addresses again, the deploy smoke test catches that)."""
    try:
        spec = _ilu.spec_from_file_location("artemis_email_off", path)
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        logging.exception("email_off: cannot load %s; pages are served without <!--email_off--> markers", path)
        return None


email_off = _load_email_off()
from notify import notify_lead  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")
logging.basicConfig(level=logging.INFO)

import tenerife  # noqa: E402  (blueprint: /tenerife-preview/, noindex)

app.register_blueprint(tenerife.bp)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR = os.path.join(BASE_DIR, "translations")
SUPPORTED = ["ru", "en", "es", "fr"]
DEFAULT = "en"
OG_LOCALE = {"ru": "ru_RU", "en": "en_US", "es": "es_ES", "fr": "fr_FR"}

# Responsive image variants (tools/build_images.py -> app/static/img/opt/manifest.json; QA P02/P05).
# Missing/broken manifest: templates fall back to the original JPEGs.
try:
    with open(os.path.join(BASE_DIR, "static", "img", "opt", "manifest.json"), encoding="utf-8") as _f:
        IMAGES = json.load(_f)
except (OSError, ValueError):
    logging.exception("image manifest missing/broken: serving original JPEGs")
    IMAGES = {"images": {}, "og": None}

TRANSLATIONS = {}
for _lang in SUPPORTED:
    with open(os.path.join(TRANS_DIR, f"{_lang}.json"), encoding="utf-8") as _f:
        TRANSLATIONS[_lang] = json.load(_f)

DB = os.path.join(os.path.dirname(BASE_DIR), "leads.db")  # repo-root, writable by www-data


def get_version():
    try:
        repo = os.path.dirname(BASE_DIR)
        count = (
            subprocess.check_output(
                ["git", "-C", repo, "rev-list", "--count", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        short = (
            subprocess.check_output(
                ["git", "-C", repo, "log", "-1", "--format=%h"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        date = (
            subprocess.check_output(
                ["git", "-C", repo, "log", "-1", "--format=%ci"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()[:10]
        )
        return f"v{count} · {short} · {date}"
    except Exception:
        return "v1.0"


def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _pick_language():
    c = request.cookies.get("lang")
    if c in SUPPORTED:
        return c
    return request.accept_languages.best_match(SUPPORTED) or DEFAULT


def _ctx(lang):
    return {
        "t": TRANSLATIONS[lang],
        "lang": lang,
        "og_locale": OG_LOCALE[lang],
        "version": get_version(),
        "supported": SUPPORTED,
        # one validation rule for the form script and the API (QA -41 / -42)
        "email_pattern": EMAIL_PATTERN,
        "amount_ws": AMOUNT_WS,
        "images": IMAGES.get("images", {}),
        "og_image": IMAGES.get("og"),
    }


def _email_off(html_text: str) -> str:
    """Wrap addresses / mailto links of a rendered Crete page in <!--email_off--> (A-13)."""
    if email_off is None:  # module missing / broken: already logged at start-up
        return html_text
    try:
        return email_off.wrap(html_text)
    except Exception:  # EmailOffError or any bug in wrap(): serve the page unwrapped, but say so (QA -43)
        logging.exception("email_off: page left unwrapped (Cloudflare will obfuscate its addresses)")
        return html_text


def _render_site(lang):
    resp = make_response(_email_off(render_template("index.html", **_ctx(lang))))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return no_cache(resp)


def _render_legal(lang, page):
    templates = {
        "privacy": "legal/privacy.html",
        "terms": "legal/terms.html",
    }
    if page not in templates:
        abort(404)
    resp = make_response(
        _email_off(render_template(templates[page], page=page, legal_i18n=legal_i18n.load(page, lang), **_ctx(lang)))
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return no_cache(resp)


@app.route("/")
def root():
    return redirect(f"/{_pick_language()}/", code=302)


@app.route("/<lang>/")
def localized(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_site(lang)


@app.route("/<lang>/privacy/")
def privacy(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_legal(lang, "privacy")


@app.route("/<lang>/terms/")
def terms(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_legal(lang, "terms")


# Bare legal paths → language-prefixed
@app.route("/privacy/")
def privacy_root():
    return redirect(f"/{_pick_language()}/privacy/", code=302)


@app.route("/terms/")
def terms_root():
    return redirect(f"/{_pick_language()}/terms/", code=302)


# --- SEO: sitemap.xml / robots.txt (before: /sitemap.xml 308 -> /sitemap.xml/ -> 404) -------------
SITE_URL = "https://artemisresort.com"


def sitemap_paths() -> list[str]:
    """Indexable 200 pages only: Crete language homes + shipped Tenerife pages (no preview / noindex)."""
    paths = [f"/{lang}/" for lang in SUPPORTED]
    for name in ("index",) + tenerife.SITE_PAGES:
        if (tenerife.SITE_DIR / f"{name}.html").is_file():
            paths.append("/tenerife/" if name == "index" else f"/tenerife/{name}/")
    paths += [f"/tenerife/{name}/" for name in tenerife.LEGAL_PAGES]
    return paths


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = "".join(f"  <url><loc>{html.escape(SITE_URL + p)}</loc></url>\n" for p in sitemap_paths())
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    resp = make_response(body)
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# Cloudflare's managed robots.txt is prepended at the edge and already carries the one
# `User-agent: *` group (Allow: / + Content-Signal). A second `User-agent: *` group from the
# origin made two groups for the same agent (QA P07), so the origin only adds the Sitemap line.
# Same effective rules: with no matching group everything is allowed (RFC 9309 §2.2.1).
ROBOTS_TXT = f"# artemisresort.com origin: all paths allowed\nSitemap: {SITE_URL}/sitemap.xml\n"


@app.route("/robots.txt")
def robots_txt():
    resp = make_response(ROBOTS_TXT)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# --- /health and /favicon.ico (QA P04 / P08: both were 308 -> "/x/" -> 404 via /<lang>/) ----------
@app.route("/health")
def health():
    """Liveness only: no DB access, no config/secret values in the body."""
    resp = jsonify(ok=True)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/favicon.ico")
def favicon_ico():
    resp = send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon", max_age=86400)
    return resp


# Removed investment-strip pages — 404 (no disclaimer / fraud-warning restore)
@app.route("/<lang>/disclaimer/")
@app.route("/disclaimer/")
@app.route("/<lang>/fraud-warning/")
@app.route("/fraud-warning/")
def legal_removed(lang=None):
    abort(404)


def init_db():
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS leads
        (id INTEGER PRIMARY KEY,
         name TEXT, email TEXT, organisation TEXT, role TEXT,
         enquiry_type TEXT, amount TEXT, message TEXT, consent INTEGER,
         created_at TEXT)"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for col, typ in [
        ("organisation", "TEXT"),
        ("role", "TEXT"),
        ("enquiry_type", "TEXT"),
        ("amount", "TEXT"),
        ("message", "TEXT"),
        ("consent", "INTEGER"),
    ]:
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass
    conn.commit()
    conn.close()


ENQUIRY_TYPES = {
    "investor",
    "project_adviser",
    "operator",
    "contractor_supplier",
    "lender_finance_adviser",
    "public_planning",
    "general_professional",
    "other",
}


# Server-side validation shared with the client (templates/index.html: EMAIL_RE / amountClean()).
# Errors carry a machine "code" (+ "field"); the page maps it to the localized message.
#
# E-mail (QA -42): dot-atom local part (no quotes, <>, spaces, leading / trailing / double dots) @ domain of
# letter-digit-hyphen labels and a TLD of >= 2 letters (or xn--…). Non-ASCII letters allowed (IDN / EAI).
# The same pattern string is handed to the page (new RegExp(...)), so client and server cannot drift.
_EMAIL_UNI = "\\u00c0-\\u1fff\\u2c00-\\u2fff\\u3001-\\ud7ff\\uf900-\\ufdcf\\ufdf0-\\uffef"
_EMAIL_ATOM = "[A-Za-z0-9!#$%&'*+/=?^_{|}~" + _EMAIL_UNI + "-]+"
_EMAIL_LABEL = "[A-Za-z0-9" + _EMAIL_UNI + "](?:[A-Za-z0-9" + _EMAIL_UNI + "-]{0,61}[A-Za-z0-9" + _EMAIL_UNI + "])?"
EMAIL_PATTERN = ("^(?=.{1,64}@)" + _EMAIL_ATOM + "(?:\\." + _EMAIL_ATOM + ")*@(?:" + _EMAIL_LABEL + "\\.)+"
                 "(?:[A-Za-z" + _EMAIL_UNI + "]{2,63}|xn--[A-Za-z0-9-]{1,59})$")
EMAIL_RE = re.compile(EMAIL_PATTERN)
EMAIL_MAX = 254

# Planned investment amount (QA -41): one rule, implemented twice (here and amountClean() in index.html,
# kept in step by tests/test_crete_pr21_c4.py, which runs the page's function in node):
#   * runs of the whitespace below collapse to one space (NBSP / narrow NBSP as in «3 000 000 €»);
#   * at most 64 characters; only ASCII digits 0-9, letters (any script: «M EUR», «от 3 млн €»),
#     spaces and € $ £ . , ' ’ + - – ~ / ( );  no other digits (², ٣, １), no %, _, <, ;
#   * at least one ASCII digit and one non-zero digit (no «0», «0,00 €»);
#   * no minus / dash before the first digit (no «-5», «-€3,000,000»; ranges «3-5 M EUR» are fine);
#   * no NaN / Inf / Infinity words.
AMOUNT_MAX = 64
AMOUNT_WS = "\\t\\n\\v\\f\\r \\u00a0\\u2000-\\u200a\\u202f\\u205f\\u3000"
_AMOUNT_WS_RE = re.compile("[" + AMOUNT_WS + "]+")
_AMOUNT_CHARS = set("0123456789 €$£.,'’+-–~/()")
_AMOUNT_BAD_WORDS = {"nan", "inf", "infinity"}


def amount_ok(value: str) -> bool:
    """The amount rule above, on an already normalised value (see _clean_amount)."""
    if not value or len(value) > AMOUNT_MAX:
        return False
    if any(ch not in _AMOUNT_CHARS and not ch.isalpha() for ch in value):
        return False
    first = next((i for i, ch in enumerate(value) if ch in "0123456789"), None)
    if first is None or not any(ch in "123456789" for ch in value):
        return False
    if any(ch in "-–" for ch in value[:first]):
        return False
    words = re.findall(r"[^\W\d_]+", value)  # letter runs (non-letters were rejected above)
    return not any(w.lower() in _AMOUNT_BAD_WORDS for w in words)


def _clean_amount(raw) -> str | None:
    """Planned investment amount: optional free text such as "€3,000,000" or "3-5 M EUR".

    Returns the normalised value ("" when empty) or None when invalid (rule above)."""
    if raw is None:
        return ""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    if isinstance(raw, float) and not math.isfinite(raw):  # NaN / Infinity in the JSON body
        return None
    value = _AMOUNT_WS_RE.sub(" ", str(raw)).strip(" ")
    if not value:
        return ""
    return value if amount_ok(value) else None


def email_ok(value: str) -> bool:
    return 0 < len(value) <= EMAIL_MAX and EMAIL_RE.fullmatch(value) is not None


HONEYPOT_FIELD = "website"  # same name as the Tenerife waitlist honeypot
_TEXT_FIELDS = ("name", "email", "organisation", "role", "enquiry_type", "message", "lang", "page")


def _enquiry_error(code: str, field: str, error: str):
    return jsonify({"ok": False, "code": code, "field": field, "error": error}), 400


@app.route("/api/enquiry", methods=["POST"])
def enquiry():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        d = {}
    # QA P09 honeypot: the hidden "website" field is empty for people. Pretend success, store and send nothing.
    if str(d.get(HONEYPOT_FIELD) or "").strip():
        logging.info("crete enquiry: honeypot hit, dropped")
        return jsonify({"ok": True})
    # QA -42: text fields must be JSON strings (or absent / null); lists, objects, numbers are rejected,
    # never stored as their Python repr. consent must be the JSON boolean true (not "false", 1, "yes").
    for key in _TEXT_FIELDS:
        if d.get(key) is not None and not isinstance(d.get(key), str):
            if key == "email":
                return _enquiry_error("email", "email", "Invalid email address")
            return _enquiry_error("generic", key, f"Invalid {key}")
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    organisation = (d.get("organisation") or "").strip()
    role = (d.get("role") or "").strip()
    enquiry_type = (d.get("enquiry_type") or "").strip()
    amount = _clean_amount(d.get("amount"))
    message = (d.get("message") or "").strip()
    consent = d.get("consent") is True

    if not name:
        return _enquiry_error("required", "name", "Name and work email are required")
    if not email:
        return _enquiry_error("required", "email", "Name and work email are required")
    if not email_ok(email):
        return _enquiry_error("email", "email", "Invalid email address")
    if not consent:
        return _enquiry_error("consent", "consent", "Consent is required")
    if enquiry_type and enquiry_type not in ENQUIRY_TYPES:
        return _enquiry_error("generic", "enquiry_type", "Invalid enquiry type")
    if amount is None:
        return _enquiry_error("amount", "amount", "Invalid planned investment amount")

    retry = ratelimit.hit(DB, "crete_enquiry", ratelimit.client_hash("artemis-crete"))
    if retry:
        resp = jsonify({"ok": False, "code": "rate_limited", "error": "rate_limited"})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry)
        return resp

    init_db()
    conn = sqlite3.connect(DB)
    conn.execute(
        """INSERT INTO leads(name,email,organisation,role,enquiry_type,amount,message,consent,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            name,
            email,
            organisation,
            role,
            enquiry_type,
            amount,
            message,
            1 if consent else 0,
            datetime.datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    lang = (d.get("lang") or "").strip()[:5]
    if lang not in SUPPORTED:
        lang = request.cookies.get("lang", "") if request.cookies.get("lang") in SUPPORTED else "?"
    page = (d.get("page") or "").strip()[:200] or urllib.parse.urlsplit(request.referrer or "").path or "/"
    if amount:
        notify_lead("Crete enquiry", name, email, lang, page, amount=amount)
    else:
        notify_lead("Crete enquiry", name, email, lang, page)

    return jsonify({"ok": True})


# Investor registration alias (restored — no longer 410)
@app.route("/api/register", methods=["POST"])
def register():
    return enquiry()


@app.route("/download-pdf")
@app.route("/download-pdf/")
def download_pdf():
    # Presentation path — serve if file exists; otherwise soft message
    for name in (
        "Artemis_Resort_Investment.pdf",
        "Artemis_Resort_Investment_Presentation.pdf",
        "artemis-investment.pdf",
        "presentation.pdf",
    ):
        path = os.path.join(BASE_DIR, "static", name)
        if os.path.isfile(path):
            return redirect(f"/static/{name}", code=302)
    abort(404)


def _admin_token_ok() -> bool:
    """Fail-closed admin check: no ARTEMIS_ADMIN_TOKEN in env -> always denied."""
    expected = os.environ.get("ARTEMIS_ADMIN_TOKEN", "")
    if len(expected) < 24:
        return False
    supplied = request.args.get("t", "") or request.headers.get("X-Admin-Token", "")
    return hmac.compare_digest(supplied.encode(), expected.encode())


@app.route("/admin/leads")
def admin_leads():
    if not _admin_token_ok():
        abort(403)
    init_db()
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """SELECT id,name,email,organisation,role,enquiry_type,amount,message,consent,created_at
               FROM leads ORDER BY id DESC"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT id,name,email,'','','','','',0,created_at FROM leads ORDER BY id DESC"
        ).fetchall()
    conn.close()
    v = get_version()
    h = (
        "<style>body{font-family:sans-serif;padding:20px}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:8px;font-size:13px}"
        "tr:nth-child(even){background:#f9f9f9}</style>"
    )
    h += f"<h2>Artemis enquiries ({len(rows)})</h2>"
    h += f'<p style="color:#888;font-size:12px">{v}</p>'
    h += (
        "<table><tr><th>#</th><th>Name</th><th>Email</th><th>Org</th>"
        "<th>Role</th><th>Type</th><th>Amount</th><th>Message</th>"
        "<th>Consent</th><th>Date</th></tr>"
    )
    for r in rows:
        e = [html.escape(str(x if x is not None else "")) for x in r]
        e[7] = html.escape(str(r[7] or "")[:120])
        h += (
            f"<tr><td>{e[0]}</td><td>{e[1]}</td><td>{e[2]}</td><td>{e[3]}</td>"
            f"<td>{e[4]}</td><td>{e[5]}</td><td>{e[6]}</td>"
            f"<td>{e[7]}</td><td>{e[8]}</td><td>{e[9]}</td></tr>"
        )
    h += "</table>"
    conn = sqlite3.connect(DB)
    try:
        tw = tenerife.waitlist_rows(conn)
        conn.commit()
    finally:
        conn.close()
    h += f"<h2>Tenerife waitlist ({len(tw)})</h2>"
    h += "<table><tr><th>#</th><th>Name</th><th>Contact</th><th>Lang</th><th>Page</th><th>Date (UTC)</th></tr>"
    for r in tw:
        e = [html.escape(str(x if x is not None else "")) for x in r]
        h += "<tr>" + "".join(f"<td>{x}</td>" for x in e) + "</tr>"
    resp = no_cache(make_response(h + "</table>"))
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_GROUP = os.environ.get("TG_OPS_GROUP", "-5168641824")


def tg_send(chat_id, text):
    if not TG_TOKEN:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data, timeout=5
        )
    except Exception:
        pass


@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    upd = request.get_json(silent=True) or {}
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat", {})
    frm = msg.get("from", {})
    text = msg.get("text", "")
    if chat.get("type") == "private":
        uname = frm.get("username", "")
        name = (frm.get("first_name", "") + " " + frm.get("last_name", "")).strip()
        uid = frm.get("id", "")
        handle = f"@{uname}" if uname else f"id{uid}"
        notify = f"Artemis site message\nFrom: {name} ({handle})\nMessage: {text}"
        tg_send(TG_GROUP, notify)
        tg_send(
            chat.get("id"),
            "Thank you. Please use the enquiry form on artemisresort.com.",
        )
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8082, debug=False)
