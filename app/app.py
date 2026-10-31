"""Artemis Resort & Spa — public project + investment site (Flask)."""
from __future__ import annotations

import datetime
import hmac
import html
import json
import os
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
)

import logging

from notify import notify_lead

app = Flask(__name__, template_folder="templates", static_folder="static")
logging.basicConfig(level=logging.INFO)

import tenerife  # noqa: E402  (blueprint: /tenerife-preview/, noindex)

app.register_blueprint(tenerife.bp)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR = os.path.join(BASE_DIR, "translations")
SUPPORTED = ["ru", "en", "es", "fr"]
DEFAULT = "en"
OG_LOCALE = {"ru": "ru_RU", "en": "en_US", "es": "es_ES", "fr": "fr_FR"}

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
    }


def _render_site(lang):
    resp = make_response(render_template("index.html", **_ctx(lang)))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return no_cache(resp)


def _render_legal(lang, page):
    templates = {
        "privacy": "legal/privacy.html",
        "terms": "legal/terms.html",
    }
    if page not in templates:
        abort(404)
    resp = make_response(render_template(templates[page], page=page, **_ctx(lang)))
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


@app.route("/robots.txt")
def robots_txt():
    resp = make_response(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
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


@app.route("/api/enquiry", methods=["POST"])
def enquiry():
    d = request.json or {}
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    organisation = (d.get("organisation") or "").strip()
    role = (d.get("role") or "").strip()
    enquiry_type = (d.get("enquiry_type") or "").strip()
    amount = (d.get("amount") or "").strip()
    message = (d.get("message") or "").strip()
    consent = bool(d.get("consent"))

    if not name or not email:
        return jsonify({"ok": False, "error": "Name and work email are required"}), 400
    if not consent:
        return jsonify({"ok": False, "error": "Consent is required"}), 400
    if enquiry_type and enquiry_type not in ENQUIRY_TYPES:
        return jsonify({"ok": False, "error": "Invalid enquiry type"}), 400

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
