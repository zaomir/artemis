"""Artemis Resort & Spa — public project-information site (Flask)."""
from __future__ import annotations

import datetime
import json
import os
import smtplib
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from flask import (
    Flask,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
)

app = Flask(__name__, template_folder="templates", static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR = os.path.join(BASE_DIR, "translations")
LEGAL_DIR = os.path.join(BASE_DIR, "legal")
SUPPORTED = ["ru", "en", "es", "fr"]
DEFAULT = "en"
OG_LOCALE = {"ru": "ru_RU", "en": "en_US", "es": "es_ES", "fr": "fr_FR"}

# Exact disclaimer (EN) — SSOT for allowlisted counsel draft
with open(os.path.join(LEGAL_DIR, "DISCLAIMER_EN.txt"), encoding="utf-8") as _df:
    DISCLAIMER_LINES = [ln.strip() for ln in _df.read().splitlines() if ln.strip()]
DISCLAIMER_MARK = DISCLAIMER_LINES[0]
DISCLAIMER_BODY = DISCLAIMER_LINES[1]

TRANSLATIONS = {}
for _lang in SUPPORTED:
    with open(os.path.join(TRANS_DIR, f"{_lang}.json"), encoding="utf-8") as _f:
        TRANSLATIONS[_lang] = json.load(_f)

DB = os.path.join(BASE_DIR, "leads.db")

# Legacy public investment surfaces → 410 Gone (do not redirect to homepage)
GONE_PATHS = [
    "/download-pdf",
    "/download-pdf/",
    "/presentation",
    "/presentation/",
    "/investor",
    "/investor/",
    "/investors",
    "/investors/",
    "/opportunity",
    "/opportunity/",
    "/calculator",
    "/calculator/",
    "/returns",
    "/returns/",
    "/deck",
    "/deck/",
    "/term-sheet",
    "/term-sheet/",
    "/proof-of-funds",
    "/proof-of-funds/",
    "/static/Artemis_Resort_Investment.pdf",
    "/static/Artemis_Resort_Investment_Presentation.pdf",
    "/static/artemis-investment.pdf",
    "/static/presentation.pdf",
]


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
        "disclaimer_mark": DISCLAIMER_MARK,
        "disclaimer_body": DISCLAIMER_BODY,
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
        "disclaimer": "legal/disclaimer.html",
        "fraud-warning": "legal/fraud_warning.html",
    }
    if page not in templates:
        abort(404)
    resp = make_response(render_template(templates[page], page=page, **_ctx(lang)))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return no_cache(resp)


@app.before_request
def _gone_legacy():
    path = request.path
    if path in GONE_PATHS or path.rstrip("/") in {p.rstrip("/") for p in GONE_PATHS}:
        abort(410)


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


@app.route("/<lang>/disclaimer/")
def disclaimer(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_legal(lang, "disclaimer")


@app.route("/<lang>/fraud-warning/")
def fraud_warning(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_legal(lang, "fraud-warning")


# Bare legal paths → language-prefixed
@app.route("/privacy/")
def privacy_root():
    return redirect(f"/{_pick_language()}/privacy/", code=302)


@app.route("/terms/")
def terms_root():
    return redirect(f"/{_pick_language()}/terms/", code=302)


@app.route("/disclaimer/")
def disclaimer_root():
    return redirect(f"/{_pick_language()}/disclaimer/", code=302)


@app.route("/fraud-warning/")
def fraud_warning_root():
    return redirect(f"/{_pick_language()}/fraud-warning/", code=302)


def init_db():
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS leads
        (id INTEGER PRIMARY KEY,
         name TEXT, email TEXT, organisation TEXT, role TEXT,
         enquiry_type TEXT, message TEXT, consent INTEGER,
         created_at TEXT)"""
    )
    # Legacy columns may exist from older schema — leave table as-is if already created
    cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for col, typ in [
        ("organisation", "TEXT"),
        ("role", "TEXT"),
        ("enquiry_type", "TEXT"),
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
        """INSERT INTO leads(name,email,organisation,role,enquiry_type,message,consent,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            name,
            email,
            organisation,
            role,
            enquiry_type,
            message,
            1 if consent else 0,
            datetime.datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    try:
        body = (
            f"Professional enquiry\n"
            f"Name: {name}\nEmail: {email}\nOrg: {organisation}\n"
            f"Role: {role}\nType: {enquiry_type}\nMessage: {message}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"Artemis — professional enquiry: {name}"
        msg["From"] = "noreply@artemisresort.com"
        msg["To"] = "INFO@ARTEMISRESORT.COM"
        with smtplib.SMTP("localhost", 25, timeout=5) as s:
            s.sendmail(msg["From"], [msg["To"]], msg.as_string())
    except Exception:
        pass

    return jsonify({"ok": True})


# Legacy endpoint: reject investment registration payloads
@app.route("/api/register", methods=["POST", "GET"])
def register_gone():
    abort(410)


@app.route("/download-pdf")
@app.route("/download-pdf/")
def download_pdf_gone():
    abort(410)


@app.route("/admin/leads")
def admin_leads():
    if request.args.get("t", "") != os.environ.get("ARTEMIS_ADMIN_TOKEN", "rovlex2025"):
        abort(403)
    init_db()
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """SELECT id,name,email,organisation,role,enquiry_type,message,consent,created_at
               FROM leads ORDER BY id DESC"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT id,name,email,'','','','',0,created_at FROM leads ORDER BY id DESC"
        ).fetchall()
    conn.close()
    v = get_version()
    h = (
        "<style>body{font-family:sans-serif;padding:20px}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:8px;font-size:13px}"
        "tr:nth-child(even){background:#f9f9f9}</style>"
    )
    h += f"<h2>Artemis professional enquiries ({len(rows)})</h2>"
    h += f'<p style="color:#888;font-size:12px">{v}</p>'
    h += (
        "<table><tr><th>#</th><th>Name</th><th>Email</th><th>Org</th>"
        "<th>Role</th><th>Type</th><th>Message</th><th>Consent</th><th>Date</th></tr>"
    )
    for r in rows:
        h += (
            f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td>"
            f"<td>{r[4]}</td><td>{r[5]}</td><td>{(r[6] or '')[:120]}</td>"
            f"<td>{r[7]}</td><td>{r[8]}</td></tr>"
        )
    return no_cache(make_response(h + "</table>"))


# Telegram ops webhook — env token only (no hardcoded secret in source)
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
        notify = (
            f"Artemis site message\nFrom: {name} ({handle})\nMessage: {text}"
        )
        tg_send(TG_GROUP, notify)
        tg_send(
            chat.get("id"),
            "Thank you. Please use the professional enquiry form on artemisresort.com.",
        )
    return jsonify({"ok": True})


@app.errorhandler(410)
def gone(_e):
    body = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<title>410 Gone</title></head><body>"
        "<h1>410 Gone</h1>"
        "<p>This resource has been permanently removed from the public site.</p>"
        "</body></html>"
    )
    resp = make_response(body, 410)
    return no_cache(resp)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8082, debug=False)
