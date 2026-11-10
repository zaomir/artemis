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

Delivery guards (31.10.2026; artemisresort.com mail is Google Workspace: MX = 1 smtp.google.com,
info@artemisresort.com is an alias there):
- Before sending, the recipient domain must have an MX record (ARTEMIS_LEAD_EMAIL_REQUIRE_MX=1, default).
  Without MX (NXDOMAIN / no answer / null MX) or on a DNS error nothing is sent: new leads stay
  queued for the copy and go out automatically once the domain has MX again. The guard is kept as a
  safety net (e.g. a broken DNS change): without MX, Gmail would fall back to the A record
  (Cloudflare proxy, no SMTP) and the message would bounce.
  The deferral is logged on change and then once an hour, not every minute.
- Send errors are retried with exponential backoff (1, 2, 4 … min, max 6 h) and at most
  ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS times (default 8). After that the lead is parked (still in leads.db,
  never deleted); `--requeue` clears the attempt counters. Same cap for the Telegram backlog.
- While the route is deferred (no MX / DNS error) the MX lookup itself backs off too (1, 2, 4 … min,
  max 1 h) instead of running every minute; leads that are backing off or parked never trigger a lookup.
- `--status` prints counters only (queued / backing off / parked, last route state), no lead data.
- `--requeue [--channel email|telegram]` clears attempt counters (all channels, or only the given one).
- Duplicate guard (A-11, 31.10.2026): a `sending` marker is committed BEFORE each Gmail send and replaced
  by the `sent` row after it. A marker left behind (process killed mid-send, e.g. TimeoutStartSec) is
  resolved on the next run by looking for the message in the sender's Sent folder via its
  `X-Artemis-Lead-Key` header: found -> recorded as sent, not re-sent; not found -> sent again.
  Residual risk: if Gmail accepted the message but it is not yet searchable, a duplicate is still
  possible (the marker is only resolved after SENDING_GRACE seconds to make that unlikely).
- Reply-To of the copy = the lead's e-mail when the contact is an e-mail address (else none).
- Stable lead identity (id reuse fix, 31.10.2026): leads.db ids were `INTEGER PRIMARY KEY` without
  AUTOINCREMENT, so SQLite hands a deleted top id to the next lead. `sent`/`attempts` are still keyed by
  (tbl, lead_id, channel) (old rows stay valid, rollback-safe), but the side tables `sent_key` and
  `attempt_key` record which lead (`lead_key` = tbl:id:created_at) a row belongs to. A row whose key
  differs from the current lead's key belongs to a deleted lead: the new lead is sent and the row replaced.
  Legacy rows written before this change have no key; they count for the current lead only if that lead
  was created no later than the row's `at` (a lead created after it was sent/baselined is a reused id).
"""
import base64
import datetime as dt
import email.message
import email.utils
import json
import os
import re
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
DEFAULT_MAX_ATTEMPTS = 8
BACKOFF_CAP = 6 * 3600
ROUTE_RECHECK_CAP = 3600
DEFER_LOG_EVERY = 3600
SENDING_GRACE = 300
CHANNELS = {"email": "email", "telegram": "tg", "tg": "tg"}
EMAIL_RE = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")

SOURCES = {
    # table: (kind label, contact column, extra columns)
    "leads": ("Crete enquiry", "email", ("amount",)),
    "tenerife_waitlist": ("Tenerife waitlist", "contact", ("language", "page", "co_investment")),
}


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def ts(t=None):
    return (t or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(*a):
    print(ts(), *a, flush=True)


def env_int(name, default, minimum=1):
    """Integer env value; an invalid value falls back to the default with a warning (never crashes)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        log(f"warning: {name} is not an integer, using default {default}")
        return default
    if v < minimum:
        log(f"warning: {name}={v} is below {minimum}, using default {default}")
        return default
    return v


MAX_ATTEMPTS = env_int("ARTEMIS_LEAD_EMAIL_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)


def parse_dig_mx(rc, out):
    """Parse `dig +noall +comments +answer MX` output.

    [] = authoritative "no usable MX" (NXDOMAIN, NOERROR without MX rows, null MX "."),
    None = unknown (SERVFAIL/REFUSED/timeout/unparseable) -> retry later, never "no MX".
    Only rows whose type is MX count; a CNAME row is not an MX (its target's MX rows follow it).
    """
    if rc != 0:
        return None
    m = re.search(r"status:\s*([A-Z]+)", out or "")
    if not m:
        return None
    status = m.group(1)
    if status == "NXDOMAIN":
        return []
    if status != "NOERROR":
        return None
    hosts = []
    for ln in out.splitlines():
        if not ln.strip() or ln.lstrip().startswith(";"):
            continue
        f = ln.split()
        # owner TTL class type prio exchange
        if len(f) >= 6 and f[2].upper() == "IN" and f[3].upper() == "MX":
            h = f[5].rstrip(".")
            if h:
                hosts.append(h)
    return hosts


def mx_hosts(domain):
    """MX hosts of domain. [] = no usable MX (NXDOMAIN, no MX, null MX "."); None = DNS error (unknown)."""
    try:
        import dns.exception
        import dns.resolver
    except ImportError:  # fallback without dnspython
        try:
            p = subprocess.run(["dig", "+noall", "+comments", "+answer", "+time=4", "+tries=2", "MX", domain],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return parse_dig_mx(p.returncode, p.stdout)
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
    s.execute("CREATE TABLE IF NOT EXISTS sending(tbl TEXT, lead_id INTEGER, channel TEXT, lead_key TEXT,"
              " started_at TEXT, PRIMARY KEY(tbl, lead_id, channel))")
    # which lead (lead_key) a sent/attempts row belongs to; separate tables keep the old schema intact
    s.execute("CREATE TABLE IF NOT EXISTS sent_key(tbl TEXT, lead_id INTEGER, channel TEXT, lead_key TEXT,"
              " PRIMARY KEY(tbl, lead_id, channel))")
    s.execute("CREATE TABLE IF NOT EXISTS attempt_key(tbl TEXT, lead_id INTEGER, channel TEXT, lead_key TEXT,"
              " PRIMARY KEY(tbl, lead_id, channel))")
    return s


def lead_key(tbl, d):
    """Stable id of one lead for the duplicate guard (created_at guards against SQLite id reuse)."""
    return f"{tbl}:{d['id']}:{clean(d.get('created_at'), 40)}"


def parse_ts(v):
    return dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def created_utc(v):
    """created_at as aware UTC (naive = server local time, as written by the app); None if unparseable."""
    try:
        t = dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.astimezone()).astimezone(dt.timezone.utc).replace(microsecond=0)


def sent_rows(s):
    """{(tbl, lead_id, channel): (at, lead_key or None)} of the state's sent rows (None = legacy row)."""
    keys = {(t, i, ch): k for t, i, ch, k in s.execute("SELECT tbl, lead_id, channel, lead_key FROM sent_key")}
    return {(t, i, ch): (at, keys.get((t, i, ch))) for t, i, ch, at in
            s.execute("SELECT tbl, lead_id, channel, at FROM sent")}


def is_done(done, tbl, d, channel):
    """True if this very lead (not an earlier lead with the same id) was already sent/baselined."""
    row = done.get((tbl, d["id"], channel))
    if row is None:
        return False
    at, key = row
    if key is not None:
        return key == lead_key(tbl, d)
    # legacy row (before the id-reuse fix): it belongs to the current lead unless that lead is newer than it
    created = created_utc(d.get("created_at"))
    try:
        sent_at = parse_ts(at)
    except (TypeError, ValueError):
        return True                                     # unknown -> never resend
    return created is None or created <= sent_at


def mark_sent(s, tbl, d, channel, ref, now):
    """Record (replacing a row of a deleted lead with the same id) that this lead went out."""
    s.execute("INSERT OR REPLACE INTO sent VALUES(?,?,?,?,?)", (tbl, d["id"], channel, ref, now))
    s.execute("INSERT OR REPLACE INTO sent_key VALUES(?,?,?,?)", (tbl, d["id"], channel, lead_key(tbl, d)))


def attempt_state(s, tbl, d, channel):
    """(n, next_at) for this lead; counters of a deleted lead with the same id do not apply to it."""
    r = s.execute("SELECT a.n, a.next_at, k.lead_key FROM attempts a LEFT JOIN attempt_key k ON"
                  " k.tbl=a.tbl AND k.lead_id=a.lead_id AND k.channel=a.channel"
                  " WHERE a.tbl=? AND a.lead_id=? AND a.channel=?", (tbl, d["id"], channel)).fetchone()
    if not r or (r[2] is not None and r[2] != lead_key(tbl, d)):
        return 0, ""
    if r[2] is None and r[1]:                           # legacy row: ignore it if the lead is newer than
        try:                                            # the last failed attempt (next_at minus its backoff)
            last = parse_ts(r[1]) - dt.timedelta(seconds=min(60 * 2 ** (max(r[0], 1) - 1), BACKOFF_CAP))
        except ValueError:
            last = None
        created = created_utc(d.get("created_at"))
        if last is not None and created is not None and created > last:
            return 0, ""
    return r[0], r[1]


def may_try(s, tbl, d, channel, now):
    n, next_at = attempt_state(s, tbl, d, channel)
    if n >= MAX_ATTEMPTS:
        return "parked"
    if next_at and next_at > ts(now):
        return "backoff"
    return "try"


def record_failure(s, tbl, d, channel, err, now):
    n = attempt_state(s, tbl, d, channel)[0] + 1
    nxt = now + dt.timedelta(seconds=min(60 * 2 ** (n - 1), BACKOFF_CAP))
    s.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?,?,?,?)", (tbl, d["id"], channel, n, ts(nxt), err))
    s.execute("INSERT OR REPLACE INTO attempt_key VALUES(?,?,?,?)", (tbl, d["id"], channel, lead_key(tbl, d)))
    s.commit()
    return n, nxt


def clear_attempts(s, tbl, lead_id, channel):
    s.execute("DELETE FROM attempts WHERE tbl=? AND lead_id=? AND channel=?", (tbl, lead_id, channel))
    s.execute("DELETE FROM attempt_key WHERE tbl=? AND lead_id=? AND channel=?", (tbl, lead_id, channel))
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
    elif not ok and (not last or (now - parse_ts(last)).total_seconds() >= DEFER_LOG_EVERY):
        log(f"email still deferred: {why}; {queued} lead(s) queued")
        kv(s, "email_route_logged_at", ts(now))


def route_check(s, queued, now):
    """mail_route(MAIL_TO) with its own backoff while deferred: (ok, why, checked)."""
    nxt, prev = kv(s, "email_route_next_check"), kv(s, "email_route")
    if prev and prev != "ok" and nxt and nxt > ts(now):
        return False, prev, False
    ok, why = mail_route(MAIL_TO)
    note_route(s, ok, why, queued, now)
    if ok:
        s.execute("DELETE FROM kv WHERE k IN ('email_route_fails', 'email_route_next_check')")
        s.commit()
    else:
        n = int(kv(s, "email_route_fails") or 0) + 1
        kv(s, "email_route_fails", str(n))
        kv(s, "email_route_next_check", ts(now + dt.timedelta(seconds=min(60 * 2 ** (n - 1), ROUTE_RECHECK_CAP))))
    return ok, why, True


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
        present = {r[1] for r in c.execute(f"PRAGMA table_info({tbl})")}
        cols = ", ".join(("id", "name", contact, "created_at") + tuple(x for x in extra if x in present))
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
    if d.get("amount") and clean(d["amount"], 64):
        lines.append(f"Сумма (план): {clean(d['amount'], 64)}")
    if "co_investment" in d and d.get("co_investment") is not None:
        lines.append(f"Co-investment interest: {'yes' if int(d['co_investment']) else 'no'}")
    lines.append(f"Время заявки: {clean(d.get('created_at'), 40)}")
    return "\n".join(lines)


def gmail():
    sys.path.insert(0, EMAIL_ENGINE)
    from src.google_auth import build_gmail_service  # noqa: E402
    return build_gmail_service(MAIL_FROM)


def reply_to(d):
    c = clean(d.get("contact"), 254)
    return c if EMAIL_RE.match(c) else ""


def send_email(kind, tbl, d, key=""):
    test = clean(d.get("name")).upper().startswith("TEST")
    m = email.message.EmailMessage()
    m["From"] = f"Artemis leads <{MAIL_FROM}>"
    m["To"] = MAIL_TO
    rt = reply_to(d)
    if rt:
        m["Reply-To"] = rt
    m["Subject"] = f"{'TEST — ' if test else ''}Artemis: новая заявка — {kind} #{d['id']}"
    m["Message-ID"] = email.utils.make_msgid(domain=MAIL_FROM.split("@")[1])
    m["Date"] = email.utils.formatdate(localtime=False)
    m["X-Artemis-Lead-Key"] = key or lead_key(tbl, d)
    m.set_content(lead_text(kind, d) + "\n\nКопия заявки с artemisresort.com (оригинал — в базе сайта).\n")
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    r = gmail().users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"{m['Message-ID']} gmail:{r.get('id')}"


def find_sent_email(key, since):
    """Gmail id of an already sent copy with X-Artemis-Lead-Key == key (sender's Sent folder), else ""."""
    svc = gmail()
    after = int(since.timestamp()) - 120
    r = svc.users().messages().list(userId="me", q=f"in:sent after:{after} subject:Artemis",
                                    maxResults=50).execute()
    for m in r.get("messages", []):
        g = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                       metadataHeaders=["X-Artemis-Lead-Key"]).execute()
        for h in g.get("payload", {}).get("headers", []):
            if h.get("name", "").lower() == "x-artemis-lead-key" and h.get("value", "").strip() == key:
                return m["id"]
    return ""


def env_value(key):
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
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


def send_one_email(s, tbl, kind, d, now_t):
    """True = sent/recorded, None = left for later, False = failed (attempt recorded)."""
    key, now = lead_key(tbl, d), ts(now_t)
    mark = s.execute("SELECT lead_key, started_at FROM sending WHERE tbl=? AND lead_id=? AND channel='email'",
                     (tbl, d["id"])).fetchone()
    if mark and mark[0] == key:
        started = parse_ts(mark[1])
        if (now_t - started).total_seconds() < SENDING_GRACE:
            return None                                 # another run may still be sending / Gmail indexing
        try:
            gid = find_sent_email(key, started)
        except Exception as e:
            n, nxt = record_failure(s, tbl, d, "email", f"verify {type(e).__name__}", now_t)
            log("email state unknown (interrupted send), Sent lookup failed", tbl, d["id"], type(e).__name__,
                f"attempt {n}/{MAX_ATTEMPTS}")
            return False
        if gid:
            mark_sent(s, tbl, d, "email", f"recovered gmail:{gid}", now)
            s.execute("DELETE FROM sending WHERE tbl=? AND lead_id=? AND channel='email'", (tbl, d["id"]))
            s.commit()
            clear_attempts(s, tbl, d["id"], "email")
            log("email already sent (interrupted run), recorded without re-sending", tbl, d["id"], f"gmail:{gid}")
            return True
        log("email interrupted before Gmail accepted it, sending again", tbl, d["id"])
    s.execute("INSERT OR REPLACE INTO sending VALUES(?,?,?,?,?)", (tbl, d["id"], "email", key, now))
    s.commit()                                          # idempotency marker BEFORE the send
    try:
        ref = send_email(kind, tbl, d, key)
    except Exception as e:
        s.execute("DELETE FROM sending WHERE tbl=? AND lead_id=? AND channel='email'", (tbl, d["id"]))
        s.commit()                                      # an exception means Gmail did not accept it
        n, nxt = record_failure(s, tbl, d, "email", type(e).__name__, now_t)
        log("email failed", tbl, d["id"], type(e).__name__, f"attempt {n}/{MAX_ATTEMPTS}",
            "- parked, lead stays in DB (--requeue to retry)" if n >= MAX_ATTEMPTS else f"- next {ts(nxt)}")
        return False
    mark_sent(s, tbl, d, "email", ref, now)
    s.execute("DELETE FROM sending WHERE tbl=? AND lead_id=? AND channel='email'", (tbl, d["id"]))
    s.commit()
    clear_attempts(s, tbl, d["id"], "email")
    log("email sent", tbl, d["id"], ref)
    return True


def run():
    s = state_db()
    rows = leads()
    now_t = utcnow()
    now = ts(now_t)
    done = sent_rows(s)
    # baseline: leads that existed before the relay started are never e-mailed
    if kv(s, "email_baseline_at") is None:
        for tbl, _, d in rows:
            mark_sent(s, tbl, d, "email", "baseline-not-emailed", now)
        s.commit()
        kv(s, "email_baseline_at", now)
        log("baseline set:", len(rows), "existing leads will not be e-mailed")
        return 0
    rc = 0
    if MAIL_TO and MAIL_FROM:
        pending = [(tbl, kind, d) for tbl, kind, d in rows if not is_done(done, tbl, d, "email")]
        # only leads that are due now may trigger the (backed-off) MX lookup; parked/backing-off ones don't
        due = [(tbl, kind, d) for tbl, kind, d in pending if may_try(s, tbl, d, "email", now_t) == "try"]
        ok = route_check(s, len(due), now_t)[0] if due else False
        for tbl, kind, d in (due if ok else []):
            if send_one_email(s, tbl, kind, d, now_t) is False:
                rc = 1
    # one-time Telegram backlog once the group chat id is configured
    if env_value("ARTEMIS_TG_CHAT_ID") and env_value("ARTEMIS_TG_BOT_TOKEN") and not kv(s, "tg_backlog_done_at"):
        cutoff = kv(s, "tg_backlog_cutoff")
        if cutoff is None:  # leads created before the chat id was configured never reached Telegram
            # server local time, same as created_at
            cutoff = dt.datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).strftime("%Y-%m-%dT%H:%M:%S")
            kv(s, "tg_backlog_cutoff", cutoff)
        n = parked = 0
        for tbl, kind, d in rows:
            if is_done(done, tbl, d, "tg") or str(d.get("created_at") or "") >= cutoff:
                continue
            st = may_try(s, tbl, d, "tg", now_t)
            if st == "parked":
                parked += 1
                continue
            if st == "backoff":
                return rc
            try:
                ref = tg_send(lead_text(kind, d, " (↪ переслано из базы, накопленная заявка)"))
            except Exception as e:
                k, nxt = record_failure(s, tbl, d, "tg", str(e)[:80], now_t)
                log("tg backlog failed", tbl, d["id"], str(e), f"attempt {k}/{MAX_ATTEMPTS}")
                return 1
            mark_sent(s, tbl, d, "tg", ref, now)
            s.commit()
            clear_attempts(s, tbl, d["id"], "tg")
            n += 1
            log("tg backlog forwarded", tbl, d["id"], ref)
        kv(s, "tg_backlog_done_at", now)
        log("tg backlog done:", n, "forwarded", f"({parked} parked after {MAX_ATTEMPTS} attempts)" if parked else "")
    return rc


def status():
    s = state_db()
    done = sent_rows(s)
    queued = [(t, d) for t, _, d in leads() if not is_done(done, t, d, "email")]
    att = [attempt_state(s, t, d, "email")[0] for t, d in queued]
    return {"kv": dict(s.execute("SELECT k, v FROM kv").fetchall()),
            "sent": s.execute("SELECT channel, ref LIKE 'baseline%', count(*) FROM sent GROUP BY 1, 2").fetchall(),
            "email_queued": len(queued),
            "email_parked": sum(1 for n in att if n >= MAX_ATTEMPTS),
            "email_backing_off": sum(1 for n in att if 0 < n < MAX_ATTEMPTS),
            "email_sending_markers": s.execute("SELECT count(*) FROM sending WHERE channel='email'").fetchone()[0],
            "mail_route": mail_route(MAIL_TO)[1] if MAIL_TO else "MAIL_TO not set"}


def requeue(args):
    """--requeue [--channel email|telegram]: clear attempt counters (all channels or only one)."""
    channel = None
    if args:
        if len(args) == 2 and args[0] == "--channel" and args[1] in CHANNELS:
            channel = CHANNELS[args[1]]
        elif len(args) == 1 and args[0].startswith("--channel=") and args[0].split("=", 1)[1] in CHANNELS:
            channel = CHANNELS[args[0].split("=", 1)[1]]
        else:
            print("usage: artemis-lead-relay.py --requeue [--channel email|telegram]", file=sys.stderr)
            return 2
    s = state_db()
    if channel:
        n = s.execute("DELETE FROM attempts WHERE channel=?", (channel,)).rowcount
        s.execute("DELETE FROM attempt_key WHERE channel=?", (channel,))
    else:
        n = s.execute("DELETE FROM attempts").rowcount
        s.execute("DELETE FROM attempt_key")
    if channel in (None, "email"):
        s.execute("DELETE FROM kv WHERE k IN ('email_route_fails', 'email_route_next_check')")
    s.commit()
    log("requeue: attempt counters cleared:", n, f"(channel {channel})" if channel else "(all channels)")
    return 0


def crm_step():
    """Run before optional notifications: their network can consume the timeout."""
    if os.environ.get('ARTEMIS_CRM_DELIVERY_ENABLED')!='1':return 0
    if not os.path.isfile(DB):
        log('CRM relay blocked','source_database_missing');return 1
    try:
        sys.path.insert(0, os.path.join(os.environ.get('ARTEMIS_DIR','/var/www/artemis'),'app'))
        from funnel_delivery import relay_once
        result=relay_once(DB)
        return int(bool(result and result.get('state')!='verified'))
    except Exception as exc:
        log('CRM relay failed',type(exc).__name__);return 1


def main(args=None):
    args=sys.argv[1:] if args is None else args
    if args == ["--status"]:
        print(json.dumps(status()))
        return 0
    if args[:1] == ["--requeue"]:return requeue(args[1:])
    # The SAME timer and durable outbox. A hung notification cannot prevent the
    # current CRM attempt; a failed CRM attempt does not discard notifications.
    rc=max(crm_step(),newsletter_step())
    try:return max(rc,run())
    except Exception as exc:
        log('legacy notification relay failed',type(exc).__name__);return 1


def newsletter_step():
    """Inactive until actual sender/reply assignment and controlled release QA."""
    if os.environ.get('ARTEMIS_NEWSLETTER_ENABLED')!='1':return 0
    reply=os.environ.get('ARTEMIS_NEWSLETTER_REPLY_TO','')
    secret=os.environ.get('ARTEMIS_NEWSLETTER_SECRET','')
    owner=os.environ.get('ARTEMIS_REPLY_OWNER_ROLE','').strip()
    if not EMAIL_RE.fullmatch(MAIL_FROM) or not EMAIL_RE.fullmatch(reply) or len(secret)<32 or not owner:
        log('newsletter relay blocked','sender_reply_owner_secret_configuration_required');return 1
    try:
        sys.path.insert(0, os.path.join(os.environ.get('ARTEMIS_DIR','/var/www/artemis'),'app'))
        from funnel_mail import relay_once
        result=relay_once(DB,gmail,MAIL_FROM,reply,secret)
        return int(bool(result and result.get('state') not in {'accepted','suppressed'}))
    except Exception as exc:
        log('newsletter relay failed',type(exc).__name__);return 1


if __name__ == "__main__":
    sys.exit(main())
