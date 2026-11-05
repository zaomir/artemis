import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
os.environ.setdefault('RATE_LIMIT_SALT','isolated-tests-only')
import app
import funnel_store as f
import funnel_http


class Fields(HTMLParser):
    def __init__(self,body):super().__init__();self.inputs=[];self.links=[];self.feed(body.decode())
    def handle_starttag(self,tag,attrs):
        item=dict(attrs)
        if tag=='input':self.inputs.append(item)
        if tag=='a' and 'href' in item:self.links.append(item['href'])


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
    def test_existing_crete_and_tenerife_forms_queue_without_newsletter(self):
        import tenerife
        with sqlite3.connect(self.db) as conn:
            f.migrate(conn);tenerife.init_waitlist_db(conn)
        with patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='0',ARTEMIS_CRM_CAPTURE_ENABLED='1'),patch('app.notify_lead'):
            r=self.client.post('/api/enquiry',json=dict(name='TEST CRM',email='service@example.invalid',consent=True,enquiry_type='investor'))
            self.assertEqual(r.status_code,200)
            r=self.client.post('/api/tenerife/waitlist',json=dict(name='TEST CRM',contact='service@example.invalid',language='de',consent=True,page='/tenerife/de/'))
            self.assertEqual(r.status_code,200)
        events=[json.loads(r[0]) for r in self.rows('SELECT payload FROM artemis_events')]
        self.assertEqual({e['project'] for e in events},{'artemis_crete','artemis_tenerife'})
        self.assertEqual(len(self.rows('SELECT * FROM artemis_crm_outbox')),2)
        self.assertFalse(self.rows('SELECT * FROM artemis_subscriptions'))
        self.assertFalse(self.rows('SELECT * FROM artemis_mail_outbox'))
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
    def test_native_validation_retains_values_and_stable_id_then_captures_once(self):
        d=dict(self.d,consent='on',contact='invalid contact',name='TEST <script>alert(1)</script>')
        d.pop('newsletter_opt_in')
        r=self.client.post('/api/tenerife/waitlist',data=d)
        self.assertEqual(r.status_code,400);self.assertNotIn('Location',r.headers)
        self.assertIn('no-store',r.headers['Cache-Control']);self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
        self.assertIn(b'value="test-http-000001"',r.data);self.assertIn(b'value="invalid contact"',r.data)
        self.assertIn(b'TEST &lt;script&gt;alert(1)&lt;/script&gt;',r.data)
        self.assertNotIn(b'<script>alert(1)</script>',r.data)
        self.assertNotRegex(r.data,rb'name="newsletter_opt_in"[^>]*checked')
        d['contact']='test@example.invalid'
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=d).status_code,200)
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=d).status_code,200)
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1);self.assertEqual(self.mock.call_count,1)
    def test_native_queue_failure_preserves_input_and_rolls_back_original_row(self):
        import tenerife
        with sqlite3.connect(self.db) as conn:
            f.migrate(conn);tenerife.init_waitlist_db(conn)
            conn.execute("CREATE TRIGGER no_delivery BEFORE INSERT ON artemis_crm_outbox BEGIN SELECT RAISE(ABORT,'isolated'); END")
        d=dict(self.d,consent='on');d.pop('newsletter_opt_in')
        r=self.client.post('/api/tenerife/waitlist',data=d)
        self.assertEqual(r.status_code,503);self.assertIn(b'value="test@example.invalid"',r.data)
        self.assertIn(b'value="test-http-000001"',r.data)
        self.assertFalse(self.rows('SELECT * FROM tenerife_waitlist'));self.assertFalse(self.rows('SELECT * FROM artemis_events'))
        self.mock.assert_not_called()
        with sqlite3.connect(self.db) as conn:conn.execute('DROP TRIGGER no_delivery')
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=d).status_code,200)
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1)
    def test_native_rate_error_preserves_input_until_retry(self):
        d=dict(self.d,consent='on');d.pop('newsletter_opt_in')
        with patch('tenerife.RATE_LIMIT_MAX',0):r=self.client.post('/api/tenerife/waitlist',data=d)
        self.assertEqual(r.status_code,429);self.assertIn(b'value="test-http-000001"',r.data)
        self.assertIn(b'value="test@example.invalid"',r.data)
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=d).status_code,200)
        self.assertEqual(len(self.rows('SELECT * FROM tenerife_waitlist')),1)
    def test_cached_native_form_after_flag_rollback_retains_input_without_downgrade(self):
        d=dict(self.d,consent='on');d.pop('newsletter_opt_in')
        with patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='0'):r=self.client.post('/api/tenerife/waitlist',data=d)
        self.assertEqual(r.status_code,503);self.assertIn(b'value="test-http-000001"',r.data)
        self.assertIn(b'value="test@example.invalid"',r.data);self.assertFalse(Path(self.db).exists())
    @unittest.skip("EN r2: public Tenerife is EN-only; no calculadora/locale forms")
    def test_nojs_locale_navigation_retains_only_public_attribution_and_capture(self):
        r=self.client.get('/tenerife/es/inversores/?source_id=fb-public-es-v1&utm_medium=organic&utm_source=private@example.invalid&email=private@example.invalid&newsletter_opt_in=on')
        self.assertEqual(r.status_code,200);self.assertNotIn('Set-Cookie',r.headers)
        self.assertNotIn(b'private@example.invalid',r.data)
        fields=Fields(r.data);self.assertEqual(sum(x.get('name')=='source_id' for x in fields.inputs),1)
        self.assertNotRegex(r.data,rb'name="newsletter_opt_in"[^>]*checked')
        target=next(h for h in fields.links if urlsplit(h).path=='/tenerife/de/inversores/')
        self.assertEqual(parse_qs(urlsplit(target).query),{'source_id':['fb-public-es-v1'],'utm_medium':['organic']})
        response=self.client.get(target);other=Fields(response.data)
        data={x['name']:x.get('value','') for x in other.inputs if x.get('type')=='hidden'}
        data.update(name='TEST Attribution',contact_type='email',contact='test@example.invalid',consent='on')
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=data).status_code,200)
        event=json.loads(self.rows('SELECT payload FROM artemis_events')[0][0])
        self.assertEqual(event['source_id'],'fb-public-es-v1');self.assertEqual(event['utm_medium'],'organic')
        self.assertEqual(event['language'],'de');self.assertEqual(event['landing'],'/tenerife/de/inversores/')
        self.assertFalse(event['newsletter_opt_in'])
    @unittest.skip("EN r2: public Tenerife is EN-only; no calculadora/locale forms")
    def test_news_mobile_and_russian_links_carry_attribution_without_storage(self):
        r=self.client.get('/tenerife/es/actualizaciones/concept-search/?source_id=fb-article-es')
        fields=Fields(r.data)
        for path in ['/tenerife/de/actualizaciones/concept-search/','/tenerife/ru/actualizaciones/concept-search/']:
            matches=[h for h in fields.links if urlsplit(h).path==path]
            self.assertTrue(matches)
            self.assertTrue(all(parse_qs(urlsplit(h).query).get('source_id')==['fb-article-es'] for h in matches))
        self.assertNotIn('Set-Cookie',r.headers)
    def test_attribution_never_rewrites_external_or_token_links(self):
        body='<a href="https://www.facebook.com/example">FB</a><a href="/tenerife/subscription/confirm/?token=opaque">Confirm</a>'
        self.assertEqual(funnel_http.carry_attribution(body,{'source_id':'public-slug'}),body)
    def test_disabled_legacy_form_does_not_gain_typed_attribution(self):
        with patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='0'):
            response=self.client.get('/tenerife/inversores/?source_id=fb-slug')
        self.assertNotIn(b'name="source_id"',response.data);self.assertNotIn(b'data-funnel-version',response.data)
    @unittest.skip("EN r2: public Tenerife is EN-only; no calculadora/locale forms")
    def test_typed_calculator_form_retains_original_server_built_fields_and_recomputation(self):
        with patch.dict(os.environ,ARTEMIS_FUNNEL_ENABLED='0'):
            legacy=Fields(self.client.get('/tenerife/calculadora/').data)
        original={x['name']:x for x in legacy.inputs if x.get('name') in {'calc_m2','calc_step','calc_pay'}}
        self.assertEqual(set(original),{'calc_m2','calc_step','calc_pay'})
        typed=Fields(self.client.get('/tenerife/calculadora/').data)
        fields={x['name']:x for x in typed.inputs if x.get('name') in original}
        for key in original:
            self.assertEqual(fields[key]['value'],original[key]['value']);self.assertEqual(fields[key]['id'],original[key]['id'])
        data={x['name']:x.get('value','') for x in typed.inputs if x.get('type')=='hidden'}
        data.update(name='TEST Calculator',contact_type='email',contact='test@example.invalid',consent='on')
        self.assertEqual(self.client.post('/api/tenerife/waitlist',data=data).status_code,200)
        row=self.rows('SELECT calc_status,calc_m2,calc_step,calc_pay FROM tenerife_waitlist')[0]
        self.assertEqual(row[0],'ok');self.assertEqual(str(row[1]),data['calc_m2']);self.assertEqual(row[2:],(data['calc_step'],data['calc_pay']))
    @unittest.skip("EN r2: public Tenerife is EN-only; no calculadora/locale forms")
    def test_all_five_forms_have_localized_uncertain_send_message_and_empty_optin(self):
        for locale in ['en','es','de','fr','ru']:
            url='/tenerife/'+('' if locale=='en' else locale+'/')+'inversores/'
            response=self.client.get(url)
            self.assertIn(b'data-msg-problem=',response.data)
            self.assertNotRegex(response.data,rb'name="newsletter_opt_in"[^>]*checked')
            self.assertNotIn(b'Request failed',response.data)


if __name__=='__main__':unittest.main()
