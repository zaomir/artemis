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

Delivery guards (31.10.2026, artemisresort.com has no MX):
- Before sending, the recipient domain must have an MX record (ARTEMIS_LEAD_EMAIL_REQUIRE_MX=1, default).
  Without MX (NXDOMAIN / no answer / null MX) or on a DNS error nothing is sent: new leads stay
  queued for the copy and go out automatically once the domain has mail. This avoids Gmail falling back
  to the A record (Cloudflare proxy, no SMTP) and bouncing into info@oxfordframe.com.
  The deferral is logged on change and then once an hour, not every minute.
- Send errors are retried with exponential backoff (1, 2, 4 … min, max 6 h) and at most
  ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS times (default 8). After that the lead is parked (still in leads.db,
  never deleted); `--requeue` clears the attempt counters. Same cap for the Telegram backlog.
- `--status` prints counters only (queued / backing off / parked, last route state), no lead data.
"""
import datetime as dt
import email.message
import email.utils
import base64
import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request

DB = os.environ.get("ARTEMIS_DB", "/var/www/artemis/leads.db")
STATE = os.environ.get("ARTEMIS_RELAY_STATE", "/var/lib/artemis-lead-relay/state.db")
ENV_FILE = os.environ.get("ARTEMIS_ENV_FILE", "/etc/artemis/artemis.env")
MAIL_TO = os.environ.get("ARTEMIS_LEAD_EMAIL_TO", "").strip()
MAIL_FROM = os.environ.get("ARTEMIS_LEAD_EMAIL_FROM", "").strip()
EMAIL_ENGINE = os.environ.get("ARTEMIS_EMAIL_ENGINE", "/opt/email-engine")
REQUIRE_MX = os.environ.get("ARTEMIS_LEAD_EMAIL_REQUIRE_MX", "1").strip() != "0"
MAX_ATTEMPTS = max(1, int(os.environ.get("ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS", "8") or 8))
BACKOFF_CAP = 6 * 3600
DEFER_LOG_EVERY = 3600

SOURCES = {
    # table: (kind label, contact column, extra columns)
    "leads": ("Crete enquiry", "email", ()),
    "tenerife_waitlist": ("Tenerife waitlist", "contact", ("language", "page")),
}


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def ts(t=None):
    return (t or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(*a):
    print(ts(), *a, flush=True)


def mx_hosts(domain):
    """MX hosts of domain. [] = no usable MX (NXDOMAIN, no MX, null MX "."); None = DNS error (unknown)."""
    try:
        import dns.exception
        import dns.resolver
    except ImportError:  # fallback without dnspython
        try:
            p = subprocess.run(["dig", "+short", "+time=4", "+tries=2", "MX", domain],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return None
        hosts = [ln.split()[-1].rstrip(".") for ln in p.stdout.splitlines() if ln.strip()]
        return [h for h in hosts if h]
    try:
        ans = dns.resolver.resolve(domain, "MX", lifetime=10)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        return None
    return [h for h in (str(r.exchange).rstrip(".") for r in ans) if h]


def mail_route(to):
    """(ok, reason). Without MX the message would be tried on the A record and bounce."""
    if not REQUIRE_MX:
        return True, "ok (mx check disabled)"
    domain = to.rsplit("@", 1)[-1].strip().lower()
    hosts = mx_hosts(domain)
    if hosts is None:
        return False, f"MX lookup for {domain} failed (DNS error)"
    if not hosts:
        return False, f"no MX for {domain}"
    return True, "ok"


def state_db():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    s = sqlite3.connect(STATE)
    s.execute("CREATE TABLE IF NOT EXISTS sent(tbl TEXT, lead_id INTEGER, channel TEXT, ref TEXT, at TEXT,"
              " PRIMARY KEY(tbl, lead_id, channel))")
    s.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
    s.execute("CREATE TABLE IF NOT EXISTS attempts(tbl TEXT, lead_id INTEGER, channel TEXT, n INTEGER,"
              " next_at TEXT, last_error TEXT, PRIMARY KEY(tbl, lead_id, channel))")
    return s


def attempt_state(s, tbl, lead_id, channel):
    r = s.execute("SELECT n, next_at FROM attempts WHERE tbl=? AND lead_id=? AND channel=?",
                  (tbl, lead_id, channel)).fetchone()
    return (r[0], r[1]) if r else (0, "")


def may_try(s, tbl, lead_id, channel, now):
    n, next_at = attempt_state(s, tbl, lead_id, channel)
    if n >= MAX_ATTEMPTS:
        return "parked"
    if next_at and next_at > ts(now):
        return "backoff"
    return "try"


def record_failure(s, tbl, lead_id, channel, err, now):
    n = attempt_state(s, tbl, lead_id, channel)[0] + 1
    nxt = now + dt.timedelta(seconds=min(60 * 2 ** (n - 1), BACKOFF_CAP))
    s.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?,?,?,?)", (tbl, lead_id, channel, n, ts(nxt), err))
    s.commit()
    return n, nxt


def clear_attempts(s, tbl, lead_id, channel):
    s.execute("DELETE FROM attempts WHERE tbl=? AND lead_id=? AND channel=?", (tbl, lead_id, channel))
    s.commit()


def note_route(s, ok, why, queued, now):
    """Log route changes once (and a reminder hourly while deferred) instead of every minute."""
    prev, last = kv(s, "email_route"), kv(s, "email_route_logged_at")
    state = "ok" if ok else why
    if state != prev:
        log("email route ok again: sending queued copies" if ok and prev else
            "email route ok" if ok else f"email deferred: {why}; {queued} lead(s) stay queued, nothing sent")
        kv(s, "email_route", state)
        kv(s, "email_route_logged_at", ts(now))
    elif not ok and (not last or (now - dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)).total_seconds() >= DEFER_LOG_EVERY):
        log(f"email still deferred: {why}; {queued} lead(s) queued")
        kv(s, "email_route_logged_at", ts(now))


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
    now_t = utcnow()
    now = ts(now_t)
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
        pending = [(tbl, kind, d) for tbl, kind, d in rows if (tbl, d["id"], "email") not in done]
        if pending:
            ok, why = mail_route(MAIL_TO)
            note_route(s, ok, why, len(pending), now_t)
        else:
            ok = False
        for tbl, kind, d in (pending if ok else []):
            if may_try(s, tbl, d["id"], "email", now_t) != "try":
                continue
            try:
                ref = send_email(kind, tbl, d)
            except Exception as e:
                n, nxt = record_failure(s, tbl, d["id"], "email", type(e).__name__, now_t)
                log("email failed", tbl, d["id"], type(e).__name__, f"attempt {n}/{MAX_ATTEMPTS}",
                    "- parked, lead stays in DB (--requeue to retry)" if n >= MAX_ATTEMPTS else f"- next {ts(nxt)}")
                rc = 1
                continue
            s.execute("INSERT INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], "email", ref, now))
            s.commit()
            clear_attempts(s, tbl, d["id"], "email")
            log("email sent", tbl, d["id"], ref)
    # one-time Telegram backlog once the group chat id is configured
    if env_value("ARTEMIS_TG_CHAT_ID") and env_value("ARTEMIS_TG_BOT_TOKEN") and not kv(s, "tg_backlog_done_at"):
        cutoff = kv(s, "tg_backlog_cutoff")
        if cutoff is None:  # leads created before the chat id was configured never reached Telegram
            cutoff = dt.datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).strftime("%Y-%m-%dT%H:%M:%S")  # server time, same as created_at
            kv(s, "tg_backlog_cutoff", cutoff)
        n = parked = 0
        for tbl, kind, d in rows:
            if (tbl, d["id"], "tg") in done or str(d.get("created_at") or "") >= cutoff:
                continue
            st = may_try(s, tbl, d["id"], "tg", now_t)
            if st == "parked":
                parked += 1
                continue
            if st == "backoff":
                return rc
            try:
                ref = tg_send(lead_text(kind, d, " (↪ переслано из базы, накопленная заявка)"))
            except Exception as e:
                k, nxt = record_failure(s, tbl, d["id"], "tg", str(e)[:80], now_t)
                log("tg backlog failed", tbl, d["id"], str(e), f"attempt {k}/{MAX_ATTEMPTS}")
                return 1
            s.execute("INSERT INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], "tg", ref, now))
            s.commit()
            clear_attempts(s, tbl, d["id"], "tg")
            n += 1
            log("tg backlog forwarded", tbl, d["id"], ref)
        kv(s, "tg_backlog_done_at", now)
        log("tg backlog done:", n, "forwarded", f"({parked} parked after {MAX_ATTEMPTS} attempts)" if parked else "")
    return rc


if __name__ == "__main__":
    if sys.argv[1:] == ["--status"]:
        s = state_db()
        done = {(t, i) for t, i in s.execute("SELECT tbl, lead_id FROM sent WHERE channel='email'")}
        queued = [(t, d["id"]) for t, _, d in leads() if (t, d["id"]) not in done]
        att = {(t, i): (n, nx) for t, i, n, nx in s.execute(
            "SELECT tbl, lead_id, n, next_at FROM attempts WHERE channel='email'")}
        print(json.dumps({"kv": dict(s.execute("SELECT k, v FROM kv").fetchall()),
                          "sent": s.execute("SELECT channel, ref LIKE 'baseline%', count(*) FROM sent GROUP BY 1, 2").fetchall(),
                          "email_queued": len(queued),
                          "email_parked": sum(1 for q in queued if att.get(q, (0,))[0] >= MAX_ATTEMPTS),
                          "email_backing_off": sum(1 for q in queued if 0 < att.get(q, (0,))[0] < MAX_ATTEMPTS),
                          "mail_route": mail_route(MAIL_TO)[1] if MAIL_TO else "MAIL_TO not set"}))
        sys.exit(0)
    if sys.argv[1:] == ["--requeue"]:
        s = state_db()
        n = s.execute("DELETE FROM attempts").rowcount
        s.commit()
        log("requeue: attempt counters cleared:", n)
        sys.exit(0)
    sys.exit(run())
