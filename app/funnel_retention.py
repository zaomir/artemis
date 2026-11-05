"""Durable pending-expiry source commands and receipt-gated online PII cleanup.

No CRM client, deletion or scheduler here. The existing outbox/writer coordinates
Person anonymization and independently reads it back. Minimal pseudonymous
receipts remain; this does not erase rotated backups or independent enquiries.
"""
from datetime import datetime,timedelta
import hashlib
import json
import uuid
import funnel_store as store


def digest(event):return hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()


def independent(event,email):
    if event.get('intent')=='newsletter_only':return False
    return (event.get('newsletter_email')==email or
        (event.get('contact_type')=='email' and str(event.get('contact','')).casefold()==email) or
        str((event.get('legacy_fields') or {}).get('email','')).casefold()==email)


def enqueue(conn,now=None,limit=50):
    if not conn.in_transaction:raise RuntimeError('retention_transaction_required')
    now=now or store.utcnow();before=(now-timedelta(days=7)).isoformat();queued=[]
    candidates=conn.execute('''SELECT id,email,generation,requested_at,language FROM artemis_subscriptions
        WHERE state='pending_confirmation' AND requested_at<? AND deliverability NOT IN ('hard_bounce','complaint')
        ORDER BY requested_at LIMIT ?''',(before,min(int(limit),50))).fetchall()
    events=[json.loads(r[0]) for r in conn.execute('SELECT payload FROM artemis_events')]
    for sid,email,generation,requested,language in candidates:
        if any(independent(e,email) for e in events):continue
        related=[e for e in events if e.get('intent')=='newsletter_only' and e.get('newsletter_email')==email
            and e.get('newsletter_requested_at','')<=requested and e.get('created_at','')<=now.isoformat()]
        if not related:raise RuntimeError('expiry_source_missing')
        if len(related)>500:raise RuntimeError('expiry_scope_requires_bounded_review')
        identity=hashlib.sha256(('email:'+email.casefold()).encode()).hexdigest()
        key=f'artemis:privacy-expiry:{sid}:{generation}'
        command=dict(source_event_id=key,submission_id=key,event_kind='pending_expiry',project='artemis_tenerife',
            intent='newsletter_only',language=language,created_at=now.isoformat(),subscription_id=sid,
            generation=generation,expiry_generation=generation+1,requested_at=requested,
            identity_sha256=identity,person_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'artemis-person:'+identity)),
            source_event_ids=sorted(e['source_event_id'] for e in related))
        payload=json.dumps(command,sort_keys=True)
        conn.execute("UPDATE artemis_subscriptions SET state='unsubscribed',generation=generation+1,token_hash=NULL,unsubscribed_at=? WHERE id=?",(now.isoformat(),sid))
        conn.execute("UPDATE artemis_mail_outbox SET state='suppressed' WHERE subscription_id=? AND state IN ('queued','retrying')",(sid,))
        for e in related:
            conn.execute("UPDATE artemis_crm_outbox SET state='erasing',lease_until=NULL,next_attempt_at=NULL WHERE source_event_id=?",(e['source_event_id'],))
        conn.execute('INSERT INTO artemis_events(source_event_id,submission_id,payload_hash,payload,created_at) VALUES(?,?,?,?,?)',
            (key,key,digest(command),payload,now.isoformat()))
        conn.execute('INSERT INTO artemis_crm_outbox(source_event_id) VALUES(?)',(key,));queued.append(key)
    return queued


def finalize(conn,command,receipt,now=None):
    """Caller holds BEGIN IMMEDIATE. No PII changes without exact writer proof."""
    if not conn.in_transaction:raise RuntimeError('retention_transaction_required')
    if not (receipt.get('state')=='verified' and receipt.get('independent_readback') is True
            and receipt.get('source_event_id')==command['source_event_id']
            and receipt.get('payload_sha256')==digest(command) and receipt.get('person_id')
            and receipt.get('opportunity_id') is None and receipt.get('retention_outcome') in
                {'anonymized','already_anonymized','retained_independent_context','retained_new_subscription'}):
        raise ValueError('coordinated_expiry_readback_required')
    now=now or store.utcnow();changed=0
    for source in command['source_event_ids']:
        row=conn.execute('SELECT payload,payload_hash FROM artemis_events WHERE source_event_id=?',(source,)).fetchone()
        if not row:raise ValueError('expiry_source_missing')
        event=json.loads(row[0])
        if event.get('event_kind')=='privacy_tombstone':continue
        if event.get('intent')!='newsletter_only' or event.get('legacy_table') or event.get('created_at','')>command['created_at']:
            raise ValueError('independent_source_not_erasable')
        tombstone=dict(source_event_id=source,submission_id=event.get('submission_id',source),project=event['project'],
            intent='newsletter_only',event_kind='privacy_tombstone',created_at=event['created_at'],
            erased_at=now.isoformat(),original_payload_sha256=row[1],expiry_source_event_id=command['source_event_id'])
        conn.execute('UPDATE artemis_events SET payload=?,payload_hash=?,client_hash=NULL WHERE source_event_id=?',
            (json.dumps(tombstone,sort_keys=True),digest(tombstone),source))
        conn.execute("UPDATE artemis_crm_outbox SET state='erased',lease_until=NULL,next_attempt_at=NULL,last_error=NULL WHERE source_event_id=?",(source,));changed+=1
    # A fresh request may have advanced this subscription while CRM was checked.
    # Remove the expired row's address only when it is still the same generation.
    conn.execute('''UPDATE artemis_subscriptions SET email=?,token_hash=NULL,expires_at=NULL,source_event_id=NULL
        WHERE id=? AND generation=? AND state='unsubscribed' ''',
        ('expired:'+command['subscription_id'],command['subscription_id'],command['expiry_generation']))
    return {'sources_scrubbed':changed,'scope':'online_newsletter_only_data','backups_erased':False}
