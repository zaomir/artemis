import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_feedback as feedback
import funnel_store as store


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'leads.db'
        self.master='isolated-admin-master-key-test';self.secret='isolated-news-secret-at-least-32-chars'
        with sqlite3.connect(self.db) as conn:
            store.migrate(conn);conn.commit();conn.execute('BEGIN IMMEDIATE')
            store.capture(conn,dict(submission_id='feedback-lead-0001',name='TEST',intent='buyer',contact_type='email',
                contact='test@example.invalid',language='en',consent=True,newsletter_opt_in=True),self.secret)
            self.mid,self.sid=conn.execute('SELECT id,subscription_id FROM artemis_mail_outbox').fetchone()
            conn.execute("UPDATE artemis_mail_outbox SET state='accepted',provider_id='provider-test'")
        app=Flask(__name__);feedback.register(app,lambda:self.db);self.client=app.test_client()
        self.env=patch.dict('os.environ',{'ARTEMIS_ADMIN_TOKEN':self.master});self.env.start()
        self.data=dict(mail_id=self.mid,reason='hard_bounce',evidence_ref='gmail:private-evidence-id',operator_task_id='MAIL-06-test')
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def post(self,data=None,headers=None):return self.client.post(feedback.PATH,json=data if data is not None else self.data,
        headers=headers if headers is not None else {'X-Artemis-Feedback-Key':feedback.intake_key(self.master)})
    def test_authorization_and_proxy_boundary(self):
        self.assertEqual(self.post(headers={}).status_code,403)
        self.assertEqual(self.post(headers={'X-Artemis-Feedback-Key':feedback.intake_key(self.master),'X-Forwarded-For':'127.0.0.1'}).status_code,403)
        with patch.dict('os.environ',{'ARTEMIS_ADMIN_TOKEN':''}):self.assertEqual(self.post().status_code,503)
    def test_feedback_is_idempotent_and_uses_existing_person_projection(self):
        first=self.post();self.assertEqual(first.status_code,200);self.assertTrue(first.json['created'])
        self.assertFalse(self.post().json['created']);self.assertNotIn('private-evidence-id',json.dumps(first.json))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT deliverability FROM artemis_subscriptions').fetchone()[0],'hard_bounce')
            event=json.loads(conn.execute('SELECT payload FROM artemis_events WHERE source_event_id=?',(first.json['source_event_id'],)).fetchone()[0])
            self.assertEqual(event['event_kind'],'subscription');self.assertEqual(event['subscription']['deliverability'],'hard_bounce')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM artemis_crm_outbox').fetchone()[0],2)
    def test_complaint_is_never_downgraded_by_later_bounce_or_import(self):
        d=dict(self.data,reason='complaint');self.assertEqual(self.post(d).status_code,200)
        self.assertEqual(self.post().status_code,200)
        with sqlite3.connect(self.db) as conn:
            conn.execute('BEGIN IMMEDIATE')
            store.capture(conn,dict(submission_id='feedback-import-0001',name='TEST',intent='buyer',contact_type='email',
                contact='test@example.invalid',language='en',consent=True,newsletter_opt_in=True),self.secret,store.utcnow()+store.timedelta(days=1))
            self.assertEqual(conn.execute('SELECT deliverability,generation FROM artemis_subscriptions').fetchone(),('complaint',1))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM artemis_mail_outbox').fetchone()[0],1)
    def test_feedback_requires_actual_dispatched_message(self):
        with sqlite3.connect(self.db) as conn:conn.execute("UPDATE artemis_mail_outbox SET state='queued'")
        self.assertEqual(self.post().status_code,400)
        with sqlite3.connect(self.db) as conn:self.assertEqual(conn.execute('SELECT deliverability FROM artemis_subscriptions').fetchone()[0],'unknown')
    def test_source_reference_cannot_be_rebound(self):
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post(dict(self.data,operator_task_id='OTHER-OPERATOR-TASK')).status_code,409)
    def test_queue_failure_rolls_back_suppression(self):
        with sqlite3.connect(self.db) as conn:conn.execute("CREATE TRIGGER fail_feedback BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'isolated'); END")
        self.assertEqual(self.post().status_code,503)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT deliverability FROM artemis_subscriptions').fetchone()[0],'unknown')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM artemis_events').fetchone()[0],1)


if __name__=='__main__':unittest.main()
