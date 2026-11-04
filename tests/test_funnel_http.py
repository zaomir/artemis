import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
os.environ.setdefault('RATE_LIMIT_SALT','isolated-tests-only')
import app
import funnel_store as f


class HTTPTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'isolated.db')
        self.env=patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='1',ARTEMIS_NEWSLETTER_SECRET='isolated-test-secret-at-least-32-chars')
        self.env.start();self.dbpatch=patch.object(app,'DB',self.db);self.dbpatch.start()
        self.notify=patch('tenerife.notify_lead');self.mock=self.notify.start()
        self.client=app.app.test_client()
        self.d=dict(submission_id='test-http-000001',intent='investor',name='TEST',contact_type='email',contact='test@example.invalid',language='en',consent=True,newsletter_opt_in=False,page='/tenerife/inversores/')
    def tearDown(self):self.notify.stop();self.dbpatch.stop();self.env.stop();self.tmp.cleanup()
    def rows(self,sql):
        with sqlite3.connect(self.db) as c:return c.execute(sql).fetchall()
    def submit(self,**kw):return self.client.post('/api/tenerife/waitlist',json=dict(self.d,**kw))
    def test_atomic_legacy_and_crm_no_optin(self):
        r=self.submit();self.assertEqual(r.status_code,200)
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1)
        self.assertEqual(len(self.rows('SELECT * FROM artemis_crm_outbox')),1)
        self.assertFalse(self.rows('SELECT * FROM artemis_mail_outbox'))
        self.assertEqual(r.json['next_url'],'/tenerife/actualizaciones/')
    def test_retry_is_one_legacy_lead_and_notification(self):
        self.submit();self.submit()
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1)
        self.assertEqual(self.mock.call_count,1)
        self.assertEqual(self.submit(intent='buyer').status_code,409)
    def test_facebook_only(self):
        self.assertEqual(self.submit(contact_type='facebook',contact='@test.person').status_code,200)
        event=json.loads(self.rows('SELECT payload FROM artemis_events')[0][0])
        self.assertEqual(event['contact_type'],'facebook')
        self.assertIsNone(event['newsletter_email'])
    def test_newsletter_only_no_legacy_lead(self):
        self.assertEqual(self.submit(intent='newsletter_only',name='',newsletter_opt_in=True,consent=False).status_code,200)
        self.assertFalse(self.rows('SELECT * FROM tenerife_waitlist'))
        self.mock.assert_not_called()
        self.assertIn(b'value="newsletter_only"',self.client.get('/tenerife/actualizaciones/').data)
    def test_get_scanner_does_not_confirm_then_post_confirms(self):
        self.submit(newsletter_opt_in=True)
        sid,gen=self.rows('SELECT id,generation FROM artemis_subscriptions')[0]
        token=f.token_for(os.environ['ARTEMIS_NEWSLETTER_SECRET'],sid,gen,'confirm')
        path='/tenerife/subscription/confirm/?token='+token
        r=self.client.get(path);self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
        self.assertEqual(self.rows('SELECT state FROM artemis_subscriptions')[0][0],'pending_confirmation')
        self.assertEqual(self.client.post('/tenerife/subscription/confirm/',data={'token':token}).status_code,200)
        self.assertEqual(self.rows('SELECT state FROM artemis_subscriptions')[0][0],'active')
        self.assertEqual(len(self.rows("SELECT * FROM artemis_mail_outbox WHERE message_type='welcome'")),1)
    def test_unsubscribe_post_suppresses_before_send(self):
        self.submit(newsletter_opt_in=True)
        sid,gen=self.rows('SELECT id,generation FROM artemis_subscriptions')[0]
        token=f.token_for(os.environ['ARTEMIS_NEWSLETTER_SECRET'],sid,gen,'unsubscribe')
        r=self.client.post('/tenerife/subscription/unsubscribe/',data=dict(id=sid,generation=gen,token=token))
        self.assertEqual(r.status_code,200)
        self.assertFalse(self.rows("SELECT * FROM artemis_mail_outbox WHERE state='queued'"))
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1)
    def test_public_form_new_only_when_enabled(self):
        r=self.client.get('/tenerife/inversores/')
        self.assertIn(b'data-funnel-version="1"',r.data)
        self.assertNotIn(b'name="phone"',r.data)
        self.assertNotRegex(r.data,rb'name="newsletter_opt_in"[^>]*checked')
        with patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='0'):
            r=self.client.get('/tenerife/inversores/')
            self.assertNotIn(b'data-funnel-version',r.data)
            self.assertEqual(self.client.get('/tenerife/subscription/confirm/?token='+'a'*64).status_code,503)
    def test_nojs_same_transaction(self):
        d=dict(self.d,consent='on');r=self.client.post('/api/tenerife/waitlist',data=d)
        self.assertEqual(r.status_code,200)
        self.assertIn(b'/tenerife/actualizaciones/',r.data)
        self.assertEqual(len(self.rows('SELECT * FROM artemis_crm_outbox')),1)


if __name__=='__main__':unittest.main()
