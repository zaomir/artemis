import base64
from datetime import timedelta
from email import message_from_bytes
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_store as f
import funnel_mail as m


class Result:
    def __init__(self,fn):self.fn=fn
    def execute(self):return self.fn()


class Gmail:
    def __init__(self):self.sent={};self.calls=0;self.timeout=False;self.found=True
    def users(self):return self
    def messages(self):return self
    def send(self,**kwargs):
        def do():
            self.calls+=1
            msg=message_from_bytes(base64.urlsafe_b64decode(kwargs['body']['raw']))
            self.sent['google-test-id']=msg
            if self.timeout:raise TimeoutError()
            return {'id':'google-test-id'}
        return Result(do)
    def list(self,**kwargs):return Result(lambda:{'messages':[{'id':k} for k in self.sent]} if self.found else {})
    def get(self,**kwargs):
        msg=self.sent[kwargs['id']]
        return Result(lambda:{'payload':{'headers':[dict(name=k,value=msg[k]) for k in ['X-Artemis-Mail-Key','Message-ID']]}})


class MailTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');f.migrate(self.conn);self.conn.commit()
        self.secret='isolated-test-secret-at-least-32-chars';self.now=f.utcnow();self.gmail=Gmail()
        d=dict(submission_id='mail-test-000001',name='TEST',intent='investor',contact_type='email',contact='test@example.invalid',language='ru',consent=True,newsletter_opt_in=True)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE');f.capture(self.conn,d,self.secret,self.now)
    def tearDown(self):self.conn.close()
    def deliver(self,now=None):return m.deliver_one(self.conn,self.gmail,'sender@example.invalid','replies@example.invalid',self.secret,now or self.now)
    def test_provider_acceptance_is_not_delivery(self):
        r=self.deliver();self.assertEqual(r['state'],'accepted');self.assertEqual(r['provider_id'],'google-test-id')
        self.assertIsNone(self.deliver());self.assertEqual(self.gmail.calls,1)
        message=self.gmail.sent['google-test-id'].as_string()
        self.assertNotIn('facebook',message.casefold())
    def test_timeout_reconciled_by_positive_readback_no_resend(self):
        self.gmail.timeout=True
        self.assertEqual(self.deliver()['state'],'uncertain')
        self.assertEqual(self.deliver(self.now+timedelta(minutes=11))['state'],'accepted')
        self.assertEqual(self.gmail.calls,1)
    def test_negative_search_does_not_allow_duplicate(self):
        self.gmail.timeout=True;self.deliver();self.gmail.found=False
        self.assertEqual(self.deliver(self.now+timedelta(minutes=11))['state'],'uncertain')
        self.assertEqual(self.gmail.calls,1)
    def test_suppression_checked_before_transport(self):
        sid=self.conn.execute('SELECT id FROM artemis_subscriptions').fetchone()[0]
        with self.conn:f.suppress(self.conn,sid,'complaint')
        self.assertIsNone(self.deliver());self.assertEqual(self.gmail.calls,0)
    def test_all_locales_neutral_confirmation(self):
        for loc in m.TEXT:
            msg=m.message(('test-id','test@example.invalid',loc,1,'confirmation','opaque-id'),'sender@example.invalid','reply@example.invalid',self.secret)
            self.assertIsNone(msg['List-Unsubscribe-Post'])
            plain=msg.get_payload()[0].get_payload(decode=True).decode()
            self.assertIn('https://artemisresort.com/tenerife/subscription/confirm/?token=',plain)
            self.assertNotIn('facebook',plain.casefold())
            self.assertNotIn('9%',plain)
    def test_welcome_has_one_click_and_does_not_invent_group(self):
        msg=m.message(('test-id','test@example.invalid','en',1,'welcome','opaque-id'),'sender@example.invalid','reply@example.invalid',self.secret)
        self.assertEqual(msg['List-Unsubscribe-Post'],'List-Unsubscribe=One-Click')
        self.assertNotIn('facebook',msg.as_string().casefold())


if __name__=='__main__':unittest.main()
