"""Historical and current legacy sources in the SAME Artemis event/outbox path.

No sender, direct CRM client or second source daemon. Call inside the source
transaction, or from the existing relay to recover older/unprocessed rows.
Never infer newsletter opt-in or reinterpret legacy calculator units.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit
import funnel_store as store

TABLES=('leads','tenerife_waitlist')
LEGACY_FIELDS={'name','email','phone','contact','language','page','organisation','role','enquiry_type',
    'amount','message','consent','created_at','calc_status','calc_note','calc_m2','calc_step','calc_pay',
    'calc_m2_server','calc_step_server','calc_pay_server','calc_type','calc_shares','calc_price_eur_m2',
    'calc_amount','calc_month_eur','calc_model_version'}


def source_key(table,row):
    if table not in TABLES:raise ValueError('unknown_legacy_source')
    stamp=hashlib.sha256(str(row.get('created_at') or '').encode()).hexdigest()[:24]
    return f'artemis:legacy:{table}:{int(row["id"])}:{stamp}'


def legacy_contact(value):
    value=str(value or '').strip()
    if store.EMAIL.fullmatch(value):return 'email',value.casefold()
    handle=value[1:] if value.startswith('@') else ''
    try:
        url=urlsplit(value if '://' in value else 'https://'+value)
        if url.netloc.lower() in {'t.me','telegram.me','www.t.me'}:handle=url.path.strip('/')
    except ValueError:pass
    if handle and re.fullmatch('[A-Za-z][A-Za-z0-9_]{4,31}',handle):return 'telegram',value
    if re.fullmatch(r'\+?[0-9\s().-]+',value) and 7<=len(re.sub(r'\D','',value))<=15:return 'phone',value
    return 'unknown',value


def event_for(table,row):
    key=source_key(table,row)
    raw=row.get('contact') if table=='tenerife_waitlist' else row.get('email') or row.get('phone')
    kind,contact=legacy_contact(raw)
    language=str(row.get('language') or '').lower()
    if language not in store.LANGUAGES:language='unknown'
    # Only the explicit original Crete enquiry type supplies an investor intent.
    intent='investor' if table=='leads' and row.get('enquiry_type')=='investor' else 'other'
    test=bool(re.search('TEST',str(row.get('name') or ''),re.I) or re.search('TEST',str(row.get('message') or ''),re.I))
    reason='existing_TEST_marker' if test else None
    if kind=='email' and contact.rsplit('@',1)[-1].endswith('.invalid'):test=True;reason=reason or 'reserved_invalid_email_domain'
    page=str(row.get('page') or '')
    landing=store.safe_landing(page) if table=='tenerife_waitlist' else '/'
    return dict(source_event_id=key,submission_id=key,
        project='artemis_tenerife' if table=='tenerife_waitlist' else 'artemis_crete',
        intent=intent,name=str(row.get('name') or ''),contact_type=kind,contact=contact,language=language,
        created_at=str(row.get('created_at') or ''),source_id='unknown',capture_origin='legacy_sqlite',
        landing=landing,consent_version='unknown',newsletter_opt_in=False,membership_state='unknown',
        waitlist_state='registered',legacy_fields={k:v for k,v in row.items() if k in LEGACY_FIELDS},
        test_record=test,test_reason=reason)


def enqueue_row(conn,table,row_id):
    if table not in TABLES:raise ValueError('unknown_legacy_source')
    if not conn.in_transaction:raise RuntimeError('source_transaction_required')
    cur=conn.execute(f'SELECT * FROM {table} WHERE id=?',(row_id,));data=cur.fetchone()
    if data is None:raise ValueError('missing_legacy_source')
    row=dict(zip([c[0] for c in cur.description],data))
    # A typed capture already links to its exact original row; never duplicate it.
    if conn.execute('SELECT 1 FROM artemis_events WHERE legacy_table=? AND legacy_id=? AND legacy_created_at IS ?',
        (table,row_id,row.get('created_at'))).fetchone():return None
    event=event_for(table,row);payload=json.dumps(event,sort_keys=True)
    conn.execute('''INSERT INTO artemis_events
        (source_event_id,submission_id,payload_hash,payload,created_at,legacy_table,legacy_id,legacy_created_at)
        VALUES(?,?,?,?,?,?,?,?)''',(event['source_event_id'],event['submission_id'],
        hashlib.sha256(payload.encode()).hexdigest(),payload,event['created_at'],table,row_id,row.get('created_at')))
    conn.execute('INSERT INTO artemis_crm_outbox(source_event_id) VALUES(?)',(event['source_event_id'],))
    return event['source_event_id']


def enqueue_missing(conn,limit=100):
    if not conn.in_transaction:raise RuntimeError('source_transaction_required')
    queued=[]
    have={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in TABLES:
        if table not in have:continue
        rows=conn.execute(f'''SELECT s.id FROM {table} s WHERE NOT EXISTS
            (SELECT 1 FROM artemis_events e WHERE e.legacy_table=? AND e.legacy_id=s.id
             AND e.legacy_created_at IS s.created_at) ORDER BY s.id LIMIT ?''',(table,max(0,limit-len(queued)))).fetchall()
        for (rid,) in rows:
            key=enqueue_row(conn,table,rid)
            if key:queued.append(key)
    return queued


def source_coverage(conn):
    """Source balance only; stored verified states still need independent CRM GETs."""
    have={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result={}
    for table in TABLES:
        if table not in have:continue
        count=conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        mapped=conn.execute(f'''SELECT COUNT(*) FROM {table} s JOIN artemis_events e
            ON e.legacy_table=? AND e.legacy_id=s.id AND e.legacy_created_at IS s.created_at''',(table,)).fetchone()[0]
        result[table]={'accepted':count,'mapped_to_event':mapped,'unmapped':count-mapped}
    return result
