#!/opt/email-engine/.venv/bin/python
"""Artemis lead relay (root, systemd timer every minute).

1. E-mail duplicate: every NEW lead (Crete `leads`, Tenerife `tenerife_waitlist`) is copied to
   ARTEMIS_LEAD_EMAIL_TO (info@artemisresort.com) from ARTEMIS_LEAD_EMAIL_FROM via the existing
   Google Workspace DWD path of /opt/email-engine (read-only use of its settings).
   Leads that existed before the relay was first started are NOT e-mailed (baseline).
2. Telegram backlog: when ARTEMIS_TG_CHAT_ID appears in /etc/artemis/artemis.env, leads stored
   before that moment (they never reached Telegram) are forwarded ONCE with a «переслано из базы»
   mark. New leads go to Telegram from the app itself (app/notify.py), not from here.

leads.db is opened read-only; relay state lives in its own DB (ARTEMIS_RELAY_STATE).
Never prints tokens or lead data; logs only table/id/channel/message id.
"""
import datetime as dt
import email.message
import email.utils
import base64
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

DB = os.environ.get("ARTEMIS_DB", "/var/www/artemis/leads.db")
STATE = os.environ.get("ARTEMIS_RELAY_STATE", "/var/lib/artemis-lead-relay/state.db")
ENV_FILE = os.environ.get("ARTEMIS_ENV_FILE", "/etc/artemis/artemis.env")
MAIL_TO = os.environ.get("ARTEMIS_LEAD_EMAIL_TO", "").strip()
MAIL_FROM = os.environ.get("ARTEMIS_LEAD_EMAIL_FROM", "").strip()
EMAIL_ENGINE = os.environ.get("ARTEMIS_EMAIL_ENGINE", "/opt/email-engine")

SOURCES = {
    # table: (kind label, contact column, extra columns)
    "leads": ("Crete enquiry", "email", ()),
    "tenerife_waitlist": ("Tenerife waitlist", "contact", ("language", "page")),
}


def log(*a):
    print(dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), *a, flush=True)


def state_db():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    s = sqlite3.connect(STATE)
    s.execute("CREATE TABLE IF NOT EXISTS sent(tbl TEXT, lead_id INTEGER, channel TEXT, ref TEXT, at TEXT,"
              " PRIMARY KEY(tbl, lead_id, channel))")
    s.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
    return s


def kv(s, k, v=None):
    if v is None:
        r = s.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else None
    s.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, v))
    s.commit()


def leads():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = []
    for tbl, (kind, contact, extra) in SOURCES.items():
        if tbl not in have:
            continue
        cols = ", ".join(("id", "name", contact, "created_at") + extra)
        for r in c.execute(f"SELECT {cols} FROM {tbl} ORDER BY id"):
            d = dict(r)
            d["contact"] = d.pop(contact)
            out.append((tbl, kind, d))
    c.close()
    return out


def clean(v, n=200):
    return " ".join(str(v or "").split())[:n]


def lead_text(kind, d, mark=""):
    lines = [f"Artemis — {kind}{mark}", f"Имя: {clean(d.get('name'))}", f"Контакт: {clean(d.get('contact'))}"]
    if d.get("language"):
        lines.append(f"Язык: {clean(d['language'], 10)}")
    if d.get("page"):
        lines.append(f"Страница: {clean(d['page'])}")
    lines.append(f"Время заявки: {clean(d.get('created_at'), 40)}")
    return "\n".join(lines)


def send_email(kind, tbl, d):
    sys.path.insert(0, EMAIL_ENGINE)
    from src.google_auth import build_gmail_service  # noqa: E402
    test = clean(d.get("name")).upper().startswith("TEST")
    m = email.message.EmailMessage()
    m["From"] = f"Artemis leads <{MAIL_FROM}>"
    m["To"] = MAIL_TO
    m["Subject"] = f"{'TEST — ' if test else ''}Artemis: новая заявка — {kind} #{d['id']}"
    m["Message-ID"] = email.utils.make_msgid(domain=MAIL_FROM.split("@")[1])
    m["Date"] = email.utils.formatdate(localtime=False)
    m.set_content(lead_text(kind, d) + "\n\nКопия заявки с artemisresort.com (оригинал — в базе сайта).\n")
    svc = build_gmail_service(MAIL_FROM)
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    r = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"{m['Message-ID']} gmail:{r.get('id')}"


def env_value(key):
    try:
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def tg_send(text):
    token, chat = env_value("ARTEMIS_TG_BOT_TOKEN"), env_value("ARTEMIS_TG_CHAT_ID")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10) as r:
            j = json.loads(r.read())
    except Exception as e:  # never log the URL (token)
        raise RuntimeError(f"telegram send failed: {type(e).__name__}") from None
    return f"tg:{j['result']['message_id']}@{j['result']['date']}"


def run():
    s = state_db()
    rows = leads()
    now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    done = {(t, i, ch) for t, i, ch in s.execute("SELECT tbl, lead_id, channel FROM sent")}
    # baseline: leads that existed before the relay started are never e-mailed
    if kv(s, "email_baseline_at") is None:
        for tbl, _, d in rows:
            s.execute("INSERT OR IGNORE INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], "email", "baseline-not-emailed", now))
        s.commit()
        kv(s, "email_baseline_at", now)
        log("baseline set:", len(rows), "existing leads will not be e-mailed")
        return 0
    rc = 0
    if MAIL_TO and MAIL_FROM:
        for tbl, kind, d in rows:
            if (tbl, d["id"], "email") in done:
                continue
            try:
                ref = send_email(kind, tbl, d)
            except Exception as e:
                log("email failed", tbl, d["id"], type(e).__name__)
                rc = 1
                continue
            s.execute("INSERT INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], "email", ref, now))
            s.commit()
            log("email sent", tbl, d["id"], ref)
    # one-time Telegram backlog once the group chat id is configured
    if env_value("ARTEMIS_TG_CHAT_ID") and env_value("ARTEMIS_TG_BOT_TOKEN") and not kv(s, "tg_backlog_done_at"):
        cutoff = kv(s, "tg_backlog_cutoff")
        if cutoff is None:  # leads created before the chat id was configured never reached Telegram
            cutoff = dt.datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).strftime("%Y-%m-%dT%H:%M:%S")  # server time, same as created_at
            kv(s, "tg_backlog_cutoff", cutoff)
        n = 0
        for tbl, kind, d in rows:
            if (tbl, d["id"], "tg") in done or str(d.get("created_at") or "") >= cutoff:
                continue
            try:
                ref = tg_send(lead_text(kind, d, " (↪ переслано из базы, накопленная заявка)"))
            except Exception as e:
                log("tg backlog failed", tbl, d["id"], str(e))
                return 1
            s.execute("INSERT INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], "tg", ref, now))
            s.commit()
            n += 1
            log("tg backlog forwarded", tbl, d["id"], ref)
        kv(s, "tg_backlog_done_at", now)
        log("tg backlog done:", n, "forwarded")
    return rc


if __name__ == "__main__":
    if sys.argv[1:] == ["--status"]:
        s = state_db()
        print(json.dumps({"kv": dict(s.execute("SELECT k, v FROM kv").fetchall()),
                          "sent": s.execute("SELECT channel, ref LIKE 'baseline%', count(*) FROM sent GROUP BY 1, 2").fetchall()}))
        sys.exit(0)
    sys.exit(run())
