"""CRM-05: explicit operator-attested FB enquiries into the existing event outbox.

No scraping, ordinary reactions, direct Twenty writes or newsletter opt-in.
The trusted host CLI derives a purpose-scoped key; no CRM/admin key goes to Aside.
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
from urllib.parse import parse_qs,urlencode,urlsplit
from flask import jsonify,request
import funnel_store as store

PATH='/api/artemis/internal/facebook-enquiry'
FIELDS={'source_kind','source_message_id','permalink','explicit_request','quoted_request','operator_task_id',
        'observed_at','name','intent','contact_type','contact','language'}


def intake_key(master):
    return hmac.new(master.encode(),b'artemis-facebook-intake-v1',hashlib.sha256).hexdigest()


def canonical_source(kind,permalink,message_id):
    if kind not in {'comment','messenger'} or not re.fullmatch(r'[A-Za-z0-9_.:$-]{3,200}',message_id):raise ValueError('source_identity')
    u=urlsplit(str(permalink))
    if u.scheme!='https' or u.netloc.lower() not in {'www.facebook.com','facebook.com','m.facebook.com'} or u.fragment:
        raise ValueError('source_permalink')
    query=parse_qs(u.query)
    if kind=='messenger':
        if not re.fullmatch(r'/messages/t/[A-Za-z0-9_.-]{3,200}/?',u.path):raise ValueError('source_permalink')
        path=u.path.rstrip('/')+'/'
        return 'https://www.facebook.com'+path
    if not (re.fullmatch(r'/(?:groups/[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+)/posts/[A-Za-z0-9_.-]{3,200}/?',u.path) or u.path=='/permalink.php'):
        raise ValueError('source_permalink')
    if query.get('comment_id')!=[message_id]:raise ValueError('source_comment_identity')
    stable={}
    for key in ['story_fbid','id','comment_id','reply_comment_id']:
        if key in query:
            if len(query[key])!=1 or not re.fullmatch('[A-Za-z0-9_.-]{3,200}',query[key][0]):raise ValueError('source_permalink')
            stable[key]=query[key][0]
    if u.path=='/permalink.php' and not {'story_fbid','id'}.issubset(stable):raise ValueError('source_permalink')
    return 'https://www.facebook.com'+u.path.rstrip('/')+('/' if u.path!='/permalink.php' else '')+'?'+urlencode(stable)


def normalize(data,now=None):
    now=now or store.utcnow()
    if not isinstance(data,dict) or set(data)!=FIELDS:raise ValueError('fields')
    if data['explicit_request'] is not True:raise ValueError('explicit_request_required')
    if not all(isinstance(data[k],str) for k in FIELDS-{'explicit_request'}):raise ValueError('text_fields')
    if data['intent'] not in {'investor','buyer','partner','other'}:raise ValueError('intent')
    if data['language'] not in store.LANGUAGES|{'unknown'}:raise ValueError('language')
    if not re.fullmatch('[A-Za-z0-9_.:-]{5,128}',data['operator_task_id']):raise ValueError('operator_task_id')
    quote=data['quoted_request'].strip()
    if not 1<=len(quote)<=4000:raise ValueError('quoted_request')
    observed=store.datetime.fromisoformat(data['observed_at'].replace('Z','+00:00'))
    if observed.tzinfo is None or observed>now+store.timedelta(minutes=5):raise ValueError('observed_at')
    source=canonical_source(data['source_kind'],data['permalink'],data['source_message_id'])
    contact=store.contact_value(data['contact_type'],data['contact'])
    event_id='artemis:facebook:'+hashlib.sha256((data['source_kind']+':'+data['source_message_id']).encode()).hexdigest()
    context={'kind':data['source_kind'],'source_message_id':data['source_message_id'],'permalink':source,
        'explicit_request':True,'quoted_request':quote,'operator_task_id':data['operator_task_id'],
        'observed_at':observed.isoformat(),'source_verification':'operator_attested_not_Meta_API'}
    return dict(source_event_id=event_id,submission_id=event_id,project='artemis_tenerife',
        intent=data['intent'],name=' '.join(data['name'].split())[:120],contact_type=data['contact_type'],contact=contact,
        language=data['language'],created_at=now.isoformat(),source_id='aside',capture_origin='facebook_explicit',
        landing='/tenerife/',consent_version='explicit_requested_response_operator_attested_v1',
        newsletter_opt_in=False,waitlist_state='registered',membership_state='unknown',facebook_context=context)


def capture(conn,data,now=None):
    if not conn.in_transaction:raise RuntimeError('source_transaction_required')
    event=normalize(data,now)
    stable={k:v for k,v in event.items() if k!='created_at'}
    stable['facebook_context']=dict(stable['facebook_context']);stable['facebook_context'].pop('observed_at')
    digest=hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest()
    old=conn.execute('SELECT payload_hash FROM artemis_events WHERE source_event_id=?',(event['source_event_id'],)).fetchone()
    if old:
        if old[0]!=digest:raise ValueError('source_event_conflict')
        return event['source_event_id'],False
    conn.execute('INSERT INTO artemis_events(source_event_id,submission_id,payload_hash,payload,created_at) VALUES(?,?,?,?,?)',
        (event['source_event_id'],event['submission_id'],digest,json.dumps(event,sort_keys=True),event['created_at']))
    conn.execute('INSERT INTO artemis_crm_outbox(source_event_id) VALUES(?)',(event['source_event_id'],))
    return event['source_event_id'],True


def register(app,db_path):
    @app.post(PATH)
    def capture_facebook_enquiry():
        master=os.environ.get('ARTEMIS_ADMIN_TOKEN','')
        if not master:return jsonify(ok=False,error='intake_not_configured'),503
        if request.remote_addr not in {'127.0.0.1','::1'} or any(request.headers.get(h) for h in
                ['X-Forwarded-For','X-Real-IP','CF-Connecting-IP','Forwarded']):
            return jsonify(ok=False,error='internal_only'),403
        supplied=request.headers.get('X-Artemis-Intake-Key','')
        if not hmac.compare_digest(intake_key(master).encode(),supplied.encode()):return jsonify(ok=False,error='forbidden'),403
        if not request.is_json or request.content_length is None or request.content_length>16000:return jsonify(ok=False,error='invalid_body'),400
        try:
            with sqlite3.connect(db_path(),timeout=5) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='artemis_crm_outbox'").fetchone():
                    return jsonify(ok=False,error='migration_required'),503
                conn.execute('BEGIN IMMEDIATE');key,created=capture(conn,request.get_json())
            response=jsonify(ok=True,source_event_id=key,state='queued',created=created,newsletter_opt_in=False)
            response.headers.update({'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow'})
            return response
        except ValueError as exc:
            conflict=str(exc)=='source_event_conflict'
            return jsonify(ok=False,error='source_event_conflict' if conflict else 'invalid_explicit_enquiry'),409 if conflict else 400
        except sqlite3.Error:return jsonify(ok=False,error='intake_unavailable'),503
