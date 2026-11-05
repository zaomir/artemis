import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import funnel_store as store
import funnel_legacy as legacy


class LegacyTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');store.migrate(self.db)
        self.db.execute('CREATE TABLE leads(id INTEGER PRIMARY KEY,name TEXT,email TEXT,phone TEXT,enquiry_type TEXT,message TEXT,consent INTEGER,created_at TEXT)')
        self.db.execute('CREATE TABLE tenerife_waitlist(id INTEGER PRIMARY KEY,name TEXT,contact TEXT,language TEXT,page TEXT,consent INTEGER,created_at TEXT,calc_m2 INTEGER,calc_model_version TEXT,client_hash TEXT)')
        self.db.execute("INSERT INTO leads VALUES(1,'Original','a@example.invalid',NULL,'investor','original message',1,'2026-05-23')")
        self.db.execute("INSERT INTO tenerife_waitlist VALUES(1,'Original','@handle','de','/tenerife/de/calculadora/?secret=private',1,'2026-10-31',72,'legacy-version','PRIVATE CLIENT HASH')")
        self.db.commit()
    def tearDown(self):self.db.close()
    def enqueue(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');return legacy.enqueue_missing(self.db)
    def test_both_projects_preserve_original_fields_without_newsletter_consent(self):
        self.assertEqual(len(self.enqueue()),2)
        events=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM artemis_events')]
        self.assertEqual({e['project'] for e in events},{'artemis_crete','artemis_tenerife'})
        self.assertTrue(all(e['newsletter_opt_in'] is False and e['consent_version']=='unknown' for e in events))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_mail_outbox').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_subscriptions').fetchone()[0],0)
        tenerife=next(e for e in events if e['project']=='artemis_tenerife')
        self.assertEqual(tenerife['legacy_fields']['calc_m2'],72)
        self.assertEqual(tenerife['legacy_fields']['calc_model_version'],'legacy-version')
        self.assertNotIn('client_hash',tenerife['legacy_fields']);self.assertNotIn('PRIVATE CLIENT HASH',json.dumps(events))
        self.assertEqual(tenerife['contact_type'],'telegram');self.assertEqual(tenerife['landing'],'/tenerife/de/calculadora/')
    def test_repeat_and_reused_id_are_distinct_only_when_original_timestamp_changes(self):
        original=self.enqueue();self.assertEqual(self.enqueue(),[])
        self.db.execute("UPDATE leads SET created_at='2026-06-24' WHERE id=1");self.db.commit()
        newer=self.enqueue();self.assertEqual(len(newer),1);self.assertNotIn(newer[0],original)
    def test_typed_capture_link_is_not_duplicated(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            store.capture(self.db,dict(submission_id='typed-capture-0001',name='Typed',contact_type='email',contact='typed@example.invalid',intent='buyer',language='en',consent=True),legacy=('tenerife_waitlist',1,'2026-10-31'))
        self.assertEqual(len(self.enqueue()),1)
        self.assertEqual(legacy.source_coverage(self.db)['tenerife_waitlist']['unmapped'],0)
    def test_outbox_failure_rolls_back_the_source_insert(self):
        self.db.execute("CREATE TRIGGER blocked BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'failure'); END");self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError),self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute("INSERT INTO leads(id,name,email,created_at) VALUES(2,'New','b@example.invalid','2026-11-05')")
            legacy.enqueue_row(self.db,'leads',2)
        self.assertIsNone(self.db.execute('SELECT id FROM leads WHERE id=2').fetchone())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM artemis_events').fetchone()[0],0)
    def test_source_transaction_required(self):
        with self.assertRaisesRegex(RuntimeError,'transaction_required'):legacy.enqueue_row(self.db,'leads',1)


if __name__=='__main__':unittest.main()
