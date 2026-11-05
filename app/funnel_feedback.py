"""Authenticated operator feedback. Gmail has no direct complaint callback.

The operator must correlate an actual message and retain its evidence privately.
This endpoint never treats an unauthenticated bounce email as provider proof.
It only changes deliverability and queues the existing Person projection.
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
from flask import jsonify,request
import funnel_store as store

PATH='/api/artemis/internal/mail-feedback'
FIELDS={'mail_id','reason','evidence_ref','operator_task_id'}


def intake_key(master):
    return hmac.new(master.encode(),b'artemis-mail-feedback-v1',hashlib.sha256).hexdigest()


def record(conn,data,now=None):
    if not conn.in_transaction:raise RuntimeError('feedback_transaction_required')
    now=now or store.utcnow()
    if not isinstance(data,dict) or set(data)!=FIELDS or not all(isinstance(v,str) for v in data.values()):raise ValueError('feedback_fields')
    if not re.fullmatch('[a-f0-9-]{36}',data['mail_id']) or data['reason'] not in {'hard_bounce','complaint'}:raise ValueError('feedback_identity')
    if not re.fullmatch('[A-Za-z0-9_.:-]{5,128}',data['operator_task_id']):raise ValueError('operator_task_id')
    if not re.fullmatch(r'(?:gmail|operator):[A-Za-z0-9_.:-]{5,200}',data['evidence_ref']):raise ValueError('evidence_reference')
    digest=hashlib.sha256(data['evidence_ref'].encode()).hexdigest()
    source='artemis:mail-feedback:'+digest+':'+data['reason']
    feedback={'mail_id':data['mail_id'],'reason':data['reason'],'evidence_sha256':digest,
        'operator_task_id':data['operator_task_id'],'source_verification':'authenticated_operator_not_provider_callback'}
    old=conn.execute('SELECT payload FROM artemis_events WHERE source_event_id=?',(source,)).fetchone()
    if old:
        if json.loads(old[0]).get('mail_feedback')!=feedback:raise ValueError('feedback_conflict')
        return source,False
    mail=conn.execute('SELECT subscription_id,state FROM artemis_mail_outbox WHERE id=?',(data['mail_id'],)).fetchone()
    if not mail or mail[1] not in {'accepted','uncertain'}:raise ValueError('correlated_dispatched_message_required')
    sub=conn.execute('SELECT source_event_id FROM artemis_subscriptions WHERE id=?',(mail[0],)).fetchone()
    if not sub or not conn.execute('SELECT 1 FROM artemis_events WHERE source_event_id=?',sub).fetchone():raise ValueError('subscription_source_required')
    store.suppress(conn,mail[0],data['reason'],project=False)
    store.queue_subscription_projection(conn,mail[0],data['reason'],now,source_event_id=source,feedback=feedback)
    return source,True


def register(app,db_path):
    @app.post(PATH)
    def mail_feedback():
        master=os.environ.get('ARTEMIS_ADMIN_TOKEN','')
        if not master:return jsonify(ok=False,error='feedback_not_configured'),503
        if request.remote_addr not in {'127.0.0.1','::1'} or any(request.headers.get(h) for h in
                ['X-Forwarded-For','X-Real-IP','CF-Connecting-IP','Forwarded']):return jsonify(ok=False,error='internal_only'),403
        if not hmac.compare_digest(intake_key(master).encode(),request.headers.get('X-Artemis-Feedback-Key','').encode()):return jsonify(ok=False,error='forbidden'),403
        if not request.is_json or request.content_length is None or request.content_length>2000:return jsonify(ok=False,error='invalid_body'),400
        try:
            with sqlite3.connect(db_path(),timeout=5) as conn:
                conn.execute('BEGIN IMMEDIATE');source,created=record(conn,request.get_json())
            response=jsonify(ok=True,source_event_id=source,created=created,crm_state='queued')
            response.headers.update({'Cache-Control':'no-store','X-Robots-Tag':'noindex,nofollow'})
            return response
        except ValueError as exc:return jsonify(ok=False,error='feedback_conflict' if str(exc)=='feedback_conflict' else 'invalid_correlated_feedback'),409 if str(exc)=='feedback_conflict' else 400
        except sqlite3.Error:return jsonify(ok=False,error='feedback_unavailable'),503
