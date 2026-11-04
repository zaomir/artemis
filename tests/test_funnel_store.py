import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
import funnel_store as f


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        f.migrate(self.db)
        self.db.commit()
        self.secret = 'isolated-test-secret-at-least-32-chars'
        self.now = f.utcnow()
        self.data = dict(submission_id='test-submission-0001', name='TEST Investor',
                         intent='investor',contact_type='email',contact='test@example.invalid',
                         language='de',consent=True,newsletter_opt_in=False,page='/tenerife/de/inversores/?email=secret')

    def tearDown(self):
        self.db.close()

    def capture(self, **changes):
        d = dict(self.data, **changes)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            return f.capture(self.db, d, self.secret, self.now)

    def subscription(self):
        return self.db.execute('SELECT id,generation,state FROM artemis_subscriptions').fetchone()

    def confirm(self):
        sid,gen,_ = self.subscription()
        token=f.token_for(self.secret,sid,gen,'confirm')
        with self.db:
            self.assertTrue(f.confirm(self.db,token,self.now))
        return sid,gen,token

    def test_migration_preserves_legacy_calc(self):
        self.db.execute('CREATE TABLE tenerife_waitlist(id INTEGER,contact TEXT,calc_m2 INTEGER,consent INTEGER)')
        self.db.execute("INSERT INTO tenerife_waitlist VALUES(7,'@legacy',72,1)")
        f.migrate(self.db);f.migrate(self.db)
        self.assertEqual(self.db.execute('SELECT * FROM tenerife_waitlist').fetchone(),(7,'@legacy',72,1))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_subscriptions').fetchone()[0],0)

    def test_capture_atomic_no_optin_no_mail(self):
        self.capture()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_crm_outbox').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_mail_outbox').fetchone()[0],0)
        e=json.loads(self.db.execute('SELECT payload FROM artemis_events').fetchone()[0])
        self.assertEqual(e['landing'],'/tenerife/de/inversores/')
        self.assertEqual(e['source_id'],'unknown')

    def test_duplicate_and_conflict(self):
        self.assertTrue(self.capture()[1]);self.assertFalse(self.capture()[1])
        with self.assertRaisesRegex(ValueError,'conflict'):self.capture(intent='buyer')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_events WHERE source_event_id LIKE "artemis:submission:%"').fetchone()[0],1)

    def test_outbox_failure_rolls_back_event(self):
        self.db.execute("CREATE TRIGGER no_outbox BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'isolated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.capture()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_events').fetchone()[0],0)

    def test_newsletter_only_no_waitlist_state(self):
        self.capture(intent='newsletter_only',newsletter_opt_in=True,name='')
        e=json.loads(self.db.execute('SELECT payload FROM artemis_events').fetchone()[0])
        self.assertIsNone(e['waitlist_state'])
        self.assertEqual(self.subscription()[2],'pending_confirmation')

    def test_facebook_does_not_become_telegram(self):
        self.capture(contact_type='facebook',contact='@test.person')
        e=json.loads(self.db.execute('SELECT payload FROM artemis_events').fetchone()[0])
        self.assertEqual(e['contact_type'],'facebook')
        self.assertEqual(e['contact'],'https://www.facebook.com/test.person')
        for bad in ['https://facebook.com.evil.invalid/person','https://user:pass@facebook.com/person','https://facebook.com/person?email=secret']:
            with self.assertRaises(ValueError): f.contact_value('facebook',bad)

    def test_tokens_hashed_no_email_in_token(self):
        self.capture(newsletter_opt_in=True)
        sid,gen,_=self.subscription(); token=f.token_for(self.secret,sid,gen,'confirm')
        dump='\n'.join(self.db.iterdump())
        self.assertNotIn(token,dump)
        self.assertEqual(len(token),64)

    def test_confirmation_idempotent_one_welcome(self):
        self.capture(newsletter_opt_in=True);sid,gen,token=self.confirm()
        self.assertTrue(f.confirm(self.db,token,self.now))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM artemis_mail_outbox WHERE message_type='welcome'").fetchone()[0],1)

    def test_expired_token(self):
        self.capture(newsletter_opt_in=True)
        sid,gen,_=self.subscription(); token=f.token_for(self.secret,sid,gen,'confirm')
        self.assertFalse(f.confirm(self.db,token,self.now+timedelta(hours=49)))

    def test_unsubscribe_suppresses_queued_welcome_and_old_token(self):
        self.capture(newsletter_opt_in=True);sid,gen,token=self.confirm()
        m=self.db.execute("SELECT id FROM artemis_mail_outbox WHERE message_type='welcome'").fetchone()[0]
        self.assertTrue(f.eligible_mail(self.db,m,self.now))
        self.assertTrue(f.unsubscribe(self.db,sid,gen,f.token_for(self.secret,sid,gen,'unsubscribe'),self.secret,self.now))
        self.assertFalse(f.eligible_mail(self.db,m,self.now))
        self.assertFalse(f.confirm(self.db,token,self.now))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_events WHERE source_event_id LIKE "artemis:submission:%"').fetchone()[0],1)

    def test_old_generation_cannot_confirm_new_request(self):
        self.capture(newsletter_opt_in=True);sid,gen,_=self.subscription()
        old=f.token_for(self.secret,sid,gen,'confirm')
        e=f.normalize(dict(self.data,newsletter_opt_in=True),self.now)
        f.request_subscription(self.db,e,self.secret,self.now+timedelta(minutes=11))
        self.assertFalse(f.confirm(self.db,old,self.now+timedelta(minutes=12)))

    def test_complaint_cannot_be_reset_by_reimport(self):
        self.capture(newsletter_opt_in=True);sid,gen,_=self.subscription()
        f.suppress(self.db,sid,'complaint')
        e=f.normalize(dict(self.data,newsletter_opt_in=True),self.now)
        f.request_subscription(self.db,e,self.secret,self.now+timedelta(minutes=11))
        self.assertEqual(self.db.execute('SELECT deliverability FROM artemis_subscriptions').fetchone()[0],'complaint')
        self.assertEqual(self.subscription()[1],gen)

    def test_empty_rollback_and_nonempty_refusal(self):
        f.rollback_empty_migration(self.db);f.migrate(self.db);self.db.commit()
        self.capture()
        with self.assertRaisesRegex(ValueError,'nonempty'):f.rollback_empty_migration(self.db)

    def test_strings_false_do_not_opt_in(self):
        self.capture(newsletter_opt_in='false')
        self.assertIsNone(self.subscription())

    def test_transaction_required(self):
        with self.assertRaises(RuntimeError):f.capture(self.db,self.data,self.secret)


if __name__=='__main__':unittest.main()
