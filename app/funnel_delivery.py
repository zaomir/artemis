"""Existing relay extension: durable Artemis events -> existing twenty-sync only.

No direct Twenty client, metadata writes, second service, or startup backfill.
Every uncertain request is retried with the SAME source ID through the adapter's
lookup-before-write reconciliation. Empty health or HTTP 200 is never verified.
"""
from datetime import timedelta
import hashlib
import json
import os
import sqlite3
from urllib.request import Request, build_opener, HTTPRedirectHandler
import funnel_store as store


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def transport(event):
    secret=os.environ.get('TWENTY_SYNC_SECRET','')
    if not secret:raise RuntimeError('sync_secret_unavailable')
    req=Request('http://127.0.0.1:8889/sync-artemis',data=json.dumps(event).encode(),
        headers={'Content-Type':'application/json','X-Sync-Secret':secret},method='POST')
    with build_opener(NoRedirect()).open(req,timeout=15) as response:
        return json.load(response)


def deliver_one(conn,send=transport,now=None):
    now=now or store.utcnow()
    conn.execute('BEGIN IMMEDIATE')
    row=conn.execute('''SELECT o.source_event_id,e.payload,o.attempts FROM artemis_crm_outbox o
        JOIN artemis_events e USING(source_event_id)
        WHERE o.state IN ('queued','retrying','uncertain')
          AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=?)
          AND (o.lease_until IS NULL OR o.lease_until<=?)
        ORDER BY e.created_at LIMIT 1''',(now.isoformat(),now.isoformat())).fetchone()
    if not row:conn.commit();return None
    key,payload,attempts=row;event=json.loads(payload)
    conn.execute("UPDATE artemis_crm_outbox SET state='uncertain',attempts=attempts+1,lease_until=? WHERE source_event_id=?",
        ((now+timedelta(seconds=90)).isoformat(),key));conn.commit()
    try:
        body=send(event)
        r=body.get('result',{})
        digest=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
        needs_deal=event['intent']!='newsletter_only' and event.get('event_kind')!='subscription'
        if not (body.get('ok') is True and r.get('state')=='verified' and r.get('independent_readback') is True
            and r.get('source_event_id')==key and r.get('person_id')
            and (r.get('opportunity_id') if needs_deal else not r.get('opportunity_id'))
            and r.get('payload_sha256')==digest):
            raise ValueError('incomplete_readback_receipt')
        if event.get('event_kind')=='pending_expiry':
            import funnel_retention
            conn.execute('BEGIN IMMEDIATE')
            funnel_retention.finalize(conn,event,r,now)
        elif r.get('retention_expired') is True:
            if event['intent']!='newsletter_only':raise ValueError('invalid_expired_source_receipt')
            conn.execute("UPDATE artemis_crm_outbox SET state='erasing',lease_until=NULL,next_attempt_at=NULL WHERE source_event_id=? AND state='uncertain'",(key,))
            conn.commit();return {'source_event_id':key,'state':'erasing'}
    except Exception as exc:
        conn.rollback()
        # Error class only: urllib errors can contain secrets, URLs or PII.
        conn.execute('''UPDATE artemis_crm_outbox SET state='uncertain',last_error=?,lease_until=NULL,
            next_attempt_at=? WHERE source_event_id=? AND state='uncertain' ''',(type(exc).__name__,
            (now+timedelta(seconds=min(60*2**min(attempts,8),21600))).isoformat(),key))
        conn.commit()
        current=conn.execute('SELECT state FROM artemis_crm_outbox WHERE source_event_id=?',(key,)).fetchone()
        return {'source_event_id':key,'state':current[0] if current else 'uncertain'}
    receipt={k:r[k] for k in ('source_event_id','person_id','opportunity_id','independent_readback','payload_sha256')}
    if r.get('retention_outcome'):receipt['retention_outcome']=r['retention_outcome']
    conn.execute('''UPDATE artemis_crm_outbox SET state='verified',receipt=?,person_id=?,opportunity_id=?,
        verified_at=?,last_error=NULL,lease_until=NULL,next_attempt_at=NULL WHERE source_event_id=? AND state='uncertain' ''',
        (json.dumps(receipt),r['person_id'],r['opportunity_id'],now.isoformat(),key))
    conn.commit()
    state=conn.execute('SELECT state FROM artemis_crm_outbox WHERE source_event_id=?',(key,)).fetchone()[0]
    return {'source_event_id':key,'state':state}


def summary(conn):
    states=dict(conn.execute('SELECT state,COUNT(*) FROM artemis_crm_outbox GROUP BY state'))
    accepted=conn.execute('SELECT COUNT(*) FROM artemis_events').fetchone()[0]
    verified=states.get('verified',0)
    return {'scope':'canonical_events_only_historical_and_Crete_inventory_required',
        'accepted_events':accepted,'verified_events':verified,'states':states,
        'unexplained_event_outbox_gap':accepted-sum(states.values()),
        'oldest_unverified':conn.execute("SELECT MIN(e.created_at) FROM artemis_events e JOIN artemis_crm_outbox o USING(source_event_id) WHERE o.state!='verified'").fetchone()[0],
        'all_Artemis_sources_verified':False}


def relay_once(db):
    if os.environ.get('ARTEMIS_CRM_DELIVERY_ENABLED')!='1':return None
    with sqlite3.connect(db,timeout=5) as conn:
        # Never create schema as a side effect of source discovery.
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='artemis_crm_outbox'").fetchone():
            return {'state':'blocked_missing_migration'}
        import funnel_legacy
        conn.execute('BEGIN IMMEDIATE')
        funnel_legacy.enqueue_missing(conn)
        if os.environ.get('ARTEMIS_RETENTION_ENABLED')=='1':
            import funnel_retention
            funnel_retention.enqueue(conn)
        conn.commit()
        return deliver_one(conn)
