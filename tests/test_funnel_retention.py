"""A privacy result must cover event payloads and CRM, not one email cell."""
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_store as store
import funnel_retention as retention


class RetentionGuardTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');store.migrate(self.conn);self.conn.commit()
        self.now=store.utcnow();self.secret='isolated-retention-secret-at-least-32-chars'
    def tearDown(self):self.conn.close()
    def capture(self,**kw):
        data=dict(submission_id='retention-test-00001',intent='newsletter_only',contact_type='email',
            contact='test@example.invalid',name='',language='en',newsletter_opt_in=True)
        data.update(kw)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE');store.capture(self.conn,data,self.secret,self.now)
    def test_expired_pending_cannot_be_misreported_as_erased(self):
        self.capture();before='\n'.join(self.conn.iterdump())
        with self.assertRaisesRegex(RuntimeError,'coordinated_pending_erasure_required'):
            store.cleanup_pending(self.conn,self.now+timedelta(days=8))
        self.assertEqual('\n'.join(self.conn.iterdump()),before)
    def test_independent_enquiry_is_not_deleted_by_pending_cleanup(self):
        self.capture(intent='buyer',name='TEST',consent=True)
        before='\n'.join(self.conn.iterdump())
        self.assertEqual(store.cleanup_pending(self.conn,self.now+timedelta(days=8)),0)
        self.assertEqual('\n'.join(self.conn.iterdump()),before)
    def test_unexpired_pending_not_selected(self):
        self.capture();self.assertEqual(store.cleanup_pending(self.conn,self.now+timedelta(days=6)),0)


class CoordinatedRetentionTest(unittest.TestCase):
    setUp=RetentionGuardTest.setUp
    tearDown=RetentionGuardTest.tearDown
    capture=RetentionGuardTest.capture
    def enqueue(self):
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            keys=retention.enqueue(self.conn,self.now+timedelta(days=8))
        return keys
    def command(self,key):
        import json
        return json.loads(self.conn.execute('SELECT payload FROM artemis_events WHERE source_event_id=?',(key,)).fetchone()[0])
    def receipt(self,command):return dict(state='verified',independent_readback=True,source_event_id=command['source_event_id'],
        payload_sha256=retention.digest(command),person_id=command['person_id'],opportunity_id=None,retention_outcome='anonymized')
    def test_source_and_address_survive_until_matching_independent_receipt(self):
        self.capture();keys=self.enqueue();self.assertEqual(len(keys),1);command=self.command(keys[0])
        self.assertNotIn('test@example.invalid',str(command))
        self.assertEqual(self.conn.execute('SELECT email FROM artemis_subscriptions').fetchone()[0],'test@example.invalid')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(ValueError,'coordinated_expiry_readback_required'):
                retention.finalize(self.conn,command,dict(self.receipt(command),independent_readback=False))
        self.assertIn('test@example.invalid','\n'.join(self.conn.iterdump()))
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE');retention.finalize(self.conn,command,self.receipt(command))
        self.assertNotIn('test@example.invalid','\n'.join(self.conn.iterdump()))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM artemis_crm_outbox WHERE state='erased'").fetchone()[0],1)
    def test_command_is_not_queued_twice(self):
        self.capture();self.enqueue();self.assertEqual(self.enqueue(),[])
    def test_queue_failure_rolls_back_expiry_generation_and_mail_suppression(self):
        self.capture();before='\n'.join(self.conn.iterdump())
        with self.conn:self.conn.execute("CREATE TRIGGER fail_expiry BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'isolated'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.enqueue()
        self.assertEqual(self.conn.execute('SELECT state,generation FROM artemis_subscriptions').fetchone(),('pending_confirmation',1))
        self.assertEqual(self.conn.execute('SELECT state FROM artemis_mail_outbox').fetchone()[0],'queued')
    def test_independent_contact_without_newsletter_optin_prevents_expiry(self):
        self.capture()
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            store.capture(self.conn,dict(submission_id='independent-lead-0001',intent='partner',name='TEST',contact_type='email',
                contact='test@example.invalid',language='en',consent=True),None,self.now)
        self.assertEqual(self.enqueue(),[])
    def test_fresh_request_survives_inflight_expiry(self):
        self.capture();command=self.command(self.enqueue()[0])
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            store.capture(self.conn,dict(submission_id='fresh-request-00001',intent='newsletter_only',name='',contact_type='email',
                contact='test@example.invalid',language='de',newsletter_opt_in=True),self.secret,self.now+timedelta(days=9))
            retention.finalize(self.conn,command,self.receipt(command))
        self.assertEqual(self.conn.execute('SELECT email,state,generation FROM artemis_subscriptions').fetchone(),('test@example.invalid','pending_confirmation',3))
        self.assertIn('fresh-request-00001','\n'.join(self.conn.iterdump()))


if __name__=='__main__':unittest.main()
