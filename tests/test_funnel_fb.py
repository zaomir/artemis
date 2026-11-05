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
import funnel_fb as fb
import funnel_store as store


class FacebookIntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'isolated.db')
        with sqlite3.connect(self.db) as conn:store.migrate(conn)
        self.master='isolated-service-key-not-a-production-credential'
        self.env=patch.dict(os.environ,ARTEMIS_ADMIN_TOKEN=self.master);self.env.start()
        self.dbpatch=patch.object(app,'DB',self.db);self.dbpatch.start()
        self.client=app.app.test_client();self.headers={'X-Artemis-Intake-Key':fb.intake_key(self.master)}
        self.data=dict(source_kind='comment',source_message_id='123456789',permalink='https://www.facebook.com/groups/testgroup/posts/987654321/?comment_id=123456789&ref=ignored',
            explicit_request=True,quoted_request='TEST: Please send project information.',operator_task_id='AS-13-test-0001',
            observed_at=store.utcnow().isoformat(),name='TEST FB',intent='investor',contact_type='facebook',contact='https://www.facebook.com/test.person',language='de')
    def tearDown(self):self.dbpatch.stop();self.env.stop();self.tmp.cleanup()
    def post(self,data=None,headers=None,**kw):return self.client.post(fb.PATH,json=data or self.data,headers=self.headers if headers is None else headers,**kw)
    def counts(self):
        with sqlite3.connect(self.db) as conn:return [conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['artemis_events','artemis_crm_outbox','artemis_subscriptions','artemis_mail_outbox']]
    def test_scoped_host_auth_is_required_and_no_query_credential(self):
        self.assertEqual(self.post(headers={}).status_code,403)
        self.assertEqual(self.post(headers={'X-Artemis-Intake-Key':self.master}).status_code,403)
        self.assertEqual(self.post(environ_base={'REMOTE_ADDR':'198.51.100.5'}).status_code,403)
        self.assertEqual(self.post(headers=dict(self.headers,**{'X-Forwarded-For':'198.51.100.5'})).status_code,403)
        self.assertEqual(self.counts(),[0,0,0,0])
    def test_missing_master_fails_closed(self):
        with patch.dict(os.environ,ARTEMIS_ADMIN_TOKEN=''):self.assertEqual(self.post().status_code,503)
    def test_explicit_request_is_queued_once_without_subscription(self):
        first=self.post();second=self.post()
        self.assertEqual(first.status_code,200);self.assertTrue(first.json['created']);self.assertFalse(second.json['created'])
        self.assertEqual(first.json['source_event_id'],second.json['source_event_id']);self.assertEqual(self.counts(),[1,1,0,0])
        with sqlite3.connect(self.db) as conn:event=json.loads(conn.execute('SELECT payload FROM artemis_events').fetchone()[0])
        self.assertEqual(event['contact_type'],'facebook');self.assertFalse(event['newsletter_opt_in'])
        self.assertNotIn('ref=',event['facebook_context']['permalink'])
        self.assertEqual(event['facebook_context']['source_verification'],'operator_attested_not_Meta_API')
    def test_reaction_and_implicit_newsletter_are_rejected(self):
        self.assertEqual(self.post(dict(self.data,explicit_request=False)).status_code,400)
        self.assertEqual(self.post(dict(self.data,newsletter_opt_in=True)).status_code,400)
        self.assertEqual(self.counts(),[0,0,0,0])
    def test_source_id_or_contact_change_cannot_overwrite_existing_event(self):
        self.post();self.assertEqual(self.post(dict(self.data,contact='https://www.facebook.com/other.person')).status_code,409)
        self.assertEqual(self.counts(),[1,1,0,0])
    def test_reobservation_does_not_duplicate(self):
        self.post();data=dict(self.data,observed_at=(store.utcnow()+store.timedelta(seconds=1)).isoformat())
        self.assertFalse(self.post(data).json['created']);self.assertEqual(self.counts(),[1,1,0,0])
    def test_comment_id_and_permalink_must_agree(self):
        self.assertEqual(self.post(dict(self.data,source_message_id='different')).status_code,400)
        self.assertEqual(self.post(dict(self.data,permalink='https://facebook.com.evil.invalid/post')).status_code,400)
    def test_outbox_failure_rolls_back_capture(self):
        with sqlite3.connect(self.db) as conn:conn.execute("CREATE TRIGGER blocked BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'isolated'); END")
        self.assertEqual(self.post().status_code,503);self.assertEqual(self.counts(),[0,0,0,0])


if __name__=='__main__':unittest.main()
