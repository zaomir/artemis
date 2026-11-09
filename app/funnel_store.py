"""Transactional Artemis capture primitives. Activation requires BASE-02/03 and CRM-01.

No CRM network client or sender lives here. The existing relay and twenty-sync own
those transports. This module never infers newsletter consent from legacy consent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from urllib.parse import urlsplit

VERSION = '2026-11-04.1'
LANGUAGES = {'en', 'es', 'de', 'fr', 'ru'}
INTENTS = {'investor', 'buyer', 'partner', 'other', 'newsletter_only'}
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
ID = re.compile(r'[A-Za-z0-9_.:-]{12,128}')


def utcnow():
    return datetime.now(timezone.utc)


def migrate(conn):
    """Add tables, not destructive changes to legacy waitlist/calc/Crete columns.

    Caller controls transaction. Do not use executescript: it implicitly commits.
    """
    statements = [
        '''CREATE TABLE IF NOT EXISTS artemis_events (
            source_event_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE,
            payload_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
            legacy_table TEXT, legacy_id INTEGER, legacy_created_at TEXT, client_hash TEXT,
            UNIQUE(legacy_table,legacy_id,legacy_created_at))''',
        '''CREATE TABLE IF NOT EXISTS artemis_crm_outbox (
            source_event_id TEXT PRIMARY KEY REFERENCES artemis_events(source_event_id),
            state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT, last_error TEXT, person_id TEXT, opportunity_id TEXT,
            receipt TEXT, verified_at TEXT, lease_until TEXT)''',
        '''CREATE TABLE IF NOT EXISTS artemis_subscriptions (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, language TEXT NOT NULL,
            state TEXT NOT NULL, generation INTEGER NOT NULL, token_hash TEXT,
            expires_at TEXT, requested_at TEXT, confirmed_at TEXT, unsubscribed_at TEXT,
            deliverability TEXT NOT NULL DEFAULT 'unknown', consent_version TEXT NOT NULL,
            source_event_id TEXT, created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS artemis_mail_outbox (
            id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL,
            generation INTEGER NOT NULL, message_type TEXT NOT NULL, issue_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued', provider_id TEXT, last_error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, next_attempt_at TEXT,
            UNIQUE(subscription_id,generation,message_type,issue_id))''',
        'CREATE INDEX IF NOT EXISTS artemis_crm_due ON artemis_crm_outbox(state,next_attempt_at)',
    ]
    for sql in statements:
        conn.execute(sql)
    if 'client_hash' not in {r[1] for r in conn.execute('PRAGMA table_info(artemis_events)')}:
        conn.execute('ALTER TABLE artemis_events ADD COLUMN client_hash TEXT')
    if 'next_attempt_at' not in {r[1] for r in conn.execute('PRAGMA table_info(artemis_mail_outbox)')}:
        conn.execute('ALTER TABLE artemis_mail_outbox ADD COLUMN next_attempt_at TEXT')


def rollback_empty_migration(conn):
    """Only an empty pre-activation migration can be rolled back automatically."""
    for table in ['artemis_events', 'artemis_crm_outbox', 'artemis_subscriptions', 'artemis_mail_outbox']:
        if conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
            raise ValueError('nonempty migration: restore verified backup; never discard captured data')
    for table in ['artemis_mail_outbox', 'artemis_subscriptions', 'artemis_crm_outbox', 'artemis_events']:
        conn.execute(f'DROP TABLE {table}')


def contact_value(kind, raw):
    value = str(raw or '').strip()
    if len(value) > 254:
        raise ValueError('contact')
    if kind == 'email' and EMAIL.fullmatch(value):
        return value.casefold()
    if kind == 'facebook':
        # Explicit type: a Facebook handle can never be reclassified as Telegram.
        if re.fullmatch(r'@?[A-Za-z0-9.]{5,80}', value):
            return 'https://www.facebook.com/' + value.lstrip('@')
        u = urlsplit(value)
        if (u.scheme=='https' and u.netloc.lower() in {'facebook.com','www.facebook.com','m.facebook.com'}
                and u.path=='/profile.php' and re.fullmatch(r'id=[0-9]{5,30}',u.query) and not u.fragment):
            return 'https://www.facebook.com/profile.php?'+u.query
        if (u.scheme == 'https' and u.netloc.lower() in {'facebook.com', 'www.facebook.com', 'm.facebook.com'}
                and re.fullmatch(r'/[A-Za-z0-9.]{5,80}/?', u.path) and not u.query and not u.fragment):
            if u.path.strip('/').lower() in {'groups','pages','marketplace','watch','login','help','settings','share'}:
                raise ValueError('contact')
            return 'https://www.facebook.com/' + u.path.strip('/')
    raise ValueError('contact')


def safe_landing(raw):
    u = urlsplit(str(raw or ''))
    # Attribution is an allowlist, never arbitrary query strings, email or tokens.
    return u.path[:200] if not u.netloc and u.path.startswith('/tenerife/') else '/tenerife/'


def normalize(data, now=None):
    now = now or utcnow()
    submission = str(data.get('submission_id') or '')
    if not ID.fullmatch(submission):
        raise ValueError('submission_id')
    intent = data.get('intent')
    if intent not in INTENTS:
        raise ValueError('intent')
    language = data.get('language')
    if language not in LANGUAGES:
        raise ValueError('language')
    # JSON false and strings "false"/"0" are not consent.
    opted = data.get('newsletter_opt_in') in (True, 'on', 'true', '1')
    if intent == 'newsletter_only' and not opted:
        raise ValueError('newsletter_opt_in')
    if intent!='newsletter_only' and data.get('consent') not in (True, 'on', 'true', '1'):
        raise ValueError('consent')
    name = ' '.join(str(data.get('name') or '').split())[:120]
    if intent != 'newsletter_only' and not name:
        raise ValueError('name')
    kind = 'email' if intent == 'newsletter_only' else data.get('contact_type')
    contact = contact_value(kind, data.get('contact'))
    newsletter_email = contact_value('email', data.get('newsletter_email') or (contact if kind == 'email' else '')) if opted else None
    origin = str(data.get('capture_origin') or 'website')
    if origin not in {'website', 'facebook', 'facebook_explicit'}:
        origin = 'website'
    event = dict(source_event_id='artemis:submission:'+submission, submission_id=submission,
                 project='artemis_tenerife', intent=intent, name=name, contact_type=kind,
                 contact=contact, language=language, created_at=now.isoformat(),
                 capture_origin=origin, source_id='unknown', landing=safe_landing(data.get('page')),
                 consent_version=VERSION, newsletter_opt_in=opted,
                 newsletter_email=newsletter_email,
                 newsletter_requested_at=now.isoformat() if opted else None,
                 newsletter_consent_version=VERSION if opted else None,
                 waitlist_state=None if intent == 'newsletter_only' else 'registered', membership_state='unknown')
    for key in ['source_id', 'utm_source', 'utm_medium', 'utm_campaign', 'form_id']:
        value = str(data.get(key) or '')
        if value and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value):
            event[key] = value
    extra_email = str(data.get('optional_email') or '').strip()
    if extra_email and EMAIL.fullmatch(extra_email):
        event['optional_email'] = extra_email.casefold()
    if data.get('consent') in (True, 'on', 'true', '1'):
        event['consent_at'] = now.isoformat()
    return event


def token_for(secret, sub_id, generation, purpose):
    if not secret or len(secret) < 32:
        raise ValueError('newsletter secret not configured')
    return hmac.new(secret.encode(), f'{purpose}:{sub_id}:{generation}'.encode(), hashlib.sha256).hexdigest()


def request_subscription(conn, event, secret, now=None):
    now = now or utcnow()
    email = event['newsletter_email']
    row = conn.execute('SELECT id,state,generation,deliverability,requested_at FROM artemis_subscriptions WHERE email=?', (email,)).fetchone()
    # Neutral response, no welcome or extra confirmation for active/complaint/bounce.
    if row and (row[1] == 'active' or row[3] in ('hard_bounce', 'complaint')):
        return
    if row and row[4] and now - datetime.fromisoformat(row[4]) < timedelta(minutes=10):
        return
    sid, generation = (row[0], row[2]+1) if row else (str(uuid.uuid4()), 1)
    token = token_for(secret, sid, generation, 'confirm')
    values = (sid, email, event['language'], 'pending_confirmation', generation,
              hashlib.sha256(token.encode()).hexdigest(), (now+timedelta(hours=48)).isoformat(),
              now.isoformat(), VERSION, event['source_event_id'], now.isoformat())
    conn.execute('''INSERT INTO artemis_subscriptions
        (id,email,language,state,generation,token_hash,expires_at,requested_at,consent_version,source_event_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET
        language=excluded.language,state=excluded.state,generation=excluded.generation,
        token_hash=excluded.token_hash,expires_at=excluded.expires_at,requested_at=excluded.requested_at,
        consent_version=excluded.consent_version,source_event_id=excluded.source_event_id,confirmed_at=NULL''', values)
    queue_mail(conn, sid, generation, 'confirmation', 'request', now)


def queue_mail(conn, sid, generation, kind, issue, now):
    conn.execute('''INSERT OR IGNORE INTO artemis_mail_outbox
        (id,subscription_id,generation,message_type,issue_id,created_at) VALUES(?,?,?,?,?,?)''',
        (str(uuid.uuid4()), sid, generation, kind, issue, now.isoformat()))


def capture(conn, data, secret=None, now=None, legacy=None, client_hash=None):
    """Caller MUST hold BEGIN IMMEDIATE; no network, no commit, rollback on any failure.

    A reused id with different input is a conflict, never success for another enquiry.
    """
    if not conn.in_transaction:
        raise RuntimeError('capture requires caller transaction')
    now = now or utcnow()
    event = normalize(data, now)
    stable = {k: v for k,v in event.items() if k not in ('created_at', 'newsletter_requested_at', 'consent_at')}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    row = conn.execute('SELECT payload_hash FROM artemis_events WHERE submission_id=?', (event['submission_id'],)).fetchone()
    if row:
        if row[0] != digest:
            raise ValueError('submission_id_conflict')
        return event['source_event_id'], False
    if event['newsletter_opt_in']:
        request_subscription(conn, event, secret, now)
        sub=conn.execute('SELECT id,state,generation,requested_at,confirmed_at,unsubscribed_at,deliverability FROM artemis_subscriptions WHERE email=?',(event['newsletter_email'],)).fetchone()
        if sub:
            event['subscription']=subscription_snapshot(sub)
    conn.execute('''INSERT INTO artemis_events
        (source_event_id,submission_id,payload_hash,payload,created_at,legacy_table,legacy_id,legacy_created_at,client_hash)
        VALUES(?,?,?,?,?,?,?,?,?)''', (event['source_event_id'], event['submission_id'], digest,
        json.dumps(event, sort_keys=True), now.isoformat(), *(legacy or (None, None, None)),client_hash))
    conn.execute('INSERT INTO artemis_crm_outbox(source_event_id) VALUES(?)', (event['source_event_id'],))
    return event['source_event_id'], True


def subscription_snapshot(row):
    # A new subscription row after expiry must still outrank the old Person
    # projection. Milliseconds + state rank remain exact within JSON safe ints.
    base=int(datetime.fromisoformat(row[3]).timestamp()*1000)*100 if row[3] else row[2]*100
    return dict(version=base+({'pending_confirmation':1,'active':2,'unsubscribed':3}[row[1]])+({'unknown':0,'ok':0,'hard_bounce':10,'complaint':20}[row[6]]),state=row[1],
                requested_at=row[3],confirmed_at=row[4],unsubscribed_at=row[5],deliverability=row[6],consent_version=VERSION)


def queue_subscription_projection(conn,sid,kind,now,source_event_id=None,feedback=None):
    row=conn.execute('SELECT id,state,generation,requested_at,confirmed_at,unsubscribed_at,deliverability,source_event_id FROM artemis_subscriptions WHERE id=?',(sid,)).fetchone()
    source=conn.execute('SELECT payload FROM artemis_events WHERE source_event_id=?',(row[7],)).fetchone() if row else None
    if not source:return
    event=json.loads(source[0]);event['event_kind']='subscription'
    event['source_event_id']=source_event_id or f'artemis:subscription:{sid}:{row[2]}:{kind}'
    if feedback is not None:event['mail_feedback']=feedback
    event['subscription']=subscription_snapshot(row);event['created_at']=now.isoformat()
    event['submission_id']=event['source_event_id']
    payload=json.dumps(event,sort_keys=True)
    conn.execute('INSERT OR IGNORE INTO artemis_events(source_event_id,submission_id,payload_hash,payload,created_at) VALUES(?,?,?,?,?)',
        (event['source_event_id'],event['submission_id'],hashlib.sha256(payload.encode()).hexdigest(),payload,now.isoformat()))
    conn.execute('INSERT OR IGNORE INTO artemis_crm_outbox(source_event_id) VALUES(?)',(event['source_event_id'],))


def confirm(conn, token, now=None):
    now = now or utcnow()
    if not re.fullmatch('[a-f0-9]{64}', str(token)):
        return False
    row = conn.execute('SELECT id,state,generation,expires_at,deliverability FROM artemis_subscriptions WHERE token_hash=?',
                       (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row or row[4] in ('hard_bounce','complaint') or datetime.fromisoformat(row[3]) < now:
        return False
    if row[1] == 'active':
        return True
    if row[1] != 'pending_confirmation':
        return False
    conn.execute("UPDATE artemis_subscriptions SET state='active',confirmed_at=? WHERE id=?", (now.isoformat(),row[0]))
    queue_mail(conn, row[0], row[2], 'welcome', 'welcome', now)
    queue_subscription_projection(conn,row[0],'confirmed',now)
    return True


def unsubscribe(conn, sid, generation, token, secret, now=None):
    now = now or utcnow()
    if not hmac.compare_digest(token_for(secret,sid,generation,'unsubscribe'), str(token)):
        return False
    row = conn.execute('SELECT generation,state FROM artemis_subscriptions WHERE id=?',(sid,)).fetchone()
    if not row:
        return False
    if row[1] == 'unsubscribed':
        return True
    if row[0] != generation:
        return False
    conn.execute("UPDATE artemis_subscriptions SET state='unsubscribed',generation=generation+1,token_hash=NULL,unsubscribed_at=? WHERE id=?",(now.isoformat(),sid))
    conn.execute("UPDATE artemis_mail_outbox SET state='suppressed' WHERE subscription_id=? AND state IN ('queued','retrying')",(sid,))
    queue_subscription_projection(conn,sid,'unsubscribed',now)
    return True


def suppress(conn, sid, reason,project=True):
    if reason not in ('hard_bounce','complaint'):
        raise ValueError('deliverability')
    conn.execute("UPDATE artemis_subscriptions SET deliverability=CASE WHEN deliverability='complaint' THEN deliverability ELSE ? END WHERE id=?",(reason,sid))
    conn.execute("UPDATE artemis_mail_outbox SET state='suppressed' WHERE subscription_id=? AND state IN ('queued','retrying')",(sid,))
    if project:queue_subscription_projection(conn,sid,reason,utcnow())


def eligible_mail(conn, mail_id, now=None):
    """Call under write lock immediately before transport, including welcome."""
    now = now or utcnow()
    row = conn.execute('''SELECT m.generation,m.message_type,m.state,s.generation,s.state,s.deliverability,s.expires_at
        FROM artemis_mail_outbox m JOIN artemis_subscriptions s ON s.id=m.subscription_id WHERE m.id=?''',(mail_id,)).fetchone()
    if not row or row[2] not in ('queued','retrying') or row[0] != row[3] or row[5] in ('hard_bounce','complaint'):
        return False
    if row[1] == 'confirmation':
        return row[4] == 'pending_confirmation' and datetime.fromisoformat(row[6]) >= now
    return row[4] == 'active'


def cleanup_pending(conn, now=None):
    """Fail closed until the privacy coordinator verifies all owned stores.

    Replacing just this table's address leaves plaintext in capture/projection
    events and Twenty. It is not erasure and must never be reported as such.
    The deployed API's permanent-delete semantics and independent-contact guards
    are verified separately before that coordinator is activated.
    """
    before = ((now or utcnow())-timedelta(days=7)).isoformat()
    candidates = conn.execute("SELECT id,email FROM artemis_subscriptions WHERE state='pending_confirmation' AND requested_at<? AND deliverability NOT IN ('hard_bounce','complaint')", (before,)).fetchall()
    due = 0
    for sid,email in candidates:
        events = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM artemis_events')]
        related = [e for e in events if e.get('newsletter_email') == email]
        if any(e.get('intent') != 'newsletter_only' for e in related):
            continue
        due += 1
    if due:raise RuntimeError('coordinated_pending_erasure_required')
    return 0
