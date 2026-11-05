"""A privacy result must cover event payloads and CRM, not one email cell."""
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_store as store


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


if __name__=='__main__':unittest.main()
