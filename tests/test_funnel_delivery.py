from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_delivery as d
import funnel_store as f


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');f.migrate(self.conn);self.conn.commit()
        self.now=f.utcnow()
        event=dict(submission_id='delivery-test-0001',name='TEST',intent='investor',contact_type='email',contact='test@example.invalid',language='en',consent=True)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE');f.capture(self.conn,event,now=self.now)
    def tearDown(self):self.conn.close()
    def good(self,event):
        return {'ok':True,'result':dict(state='verified',source_event_id=event['source_event_id'],person_id='p1',opportunity_id='o1',independent_readback=True,payload_sha256=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest())}
    def test_full_receipt_only(self):
        self.assertEqual(d.deliver_one(self.conn,self.good,self.now)['state'],'verified')
        self.assertIsNone(d.deliver_one(self.conn,self.good,self.now))
        self.assertEqual(d.summary(self.conn)['verified_events'],1)
        self.assertFalse(d.summary(self.conn)['all_Artemis_sources_verified'])
    def test_http_ok_without_readback_is_uncertain(self):
        r=d.deliver_one(self.conn,lambda _:dict(ok=True),self.now)
        self.assertEqual(r['state'],'uncertain')
        self.assertEqual(d.summary(self.conn)['verified_events'],0)
    def test_timeout_retries_same_event_and_backoff(self):
        seen=[]
        def timeout(e):seen.append(e['source_event_id']);raise TimeoutError()
        d.deliver_one(self.conn,timeout,self.now)
        self.assertIsNone(d.deliver_one(self.conn,timeout,self.now+timedelta(seconds=30)))
        def recovered(e):seen.append(e['source_event_id']);return self.good(e)
        self.assertEqual(d.deliver_one(self.conn,recovered,self.now+timedelta(seconds=61))['state'],'verified')
        self.assertEqual(seen[0],seen[1])
    def test_missing_opportunity_not_verified(self):
        def partial(e):r=self.good(e);r['result']['opportunity_id']=None;return r
        self.assertEqual(d.deliver_one(self.conn,partial,self.now)['state'],'uncertain')
    def test_old_lease_can_reconcile(self):
        self.conn.execute("UPDATE artemis_crm_outbox SET state='uncertain',lease_until=?",((self.now-timedelta(seconds=1)).isoformat(),));self.conn.commit()
        self.assertEqual(d.deliver_one(self.conn,self.good,self.now)['state'],'verified')


if __name__=='__main__':unittest.main()
