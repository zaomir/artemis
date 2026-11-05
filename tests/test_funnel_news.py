import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
sys.path.insert(0,str(ROOT/'scripts/tenerife_site_build'))
os.environ.setdefault('RATE_LIMIT_SALT','isolated-tests-only')
import news


class NewsTest(unittest.TestCase):
    def test_five_actual_translations(self):
        r=news.load_registry()
        self.assertEqual(set(r['articles'][0]['translations']),set(news.LANGS))
        self.assertFalse(r['articles'][0]['claim_references'])

    def test_drafts_not_in_output(self):
        from unittest.mock import patch
        r=news.load_registry();r['articles'][0]['editorial_status']='draft'
        with patch.object(news,'load_registry',return_value=r):
            out=news.build_pages(lambda *args:args[2],'en')
        self.assertEqual(list(out),['actualizaciones'])
        self.assertNotIn('<article>',out['actualizaciones'])
    def test_internal_brief_is_attributed_without_a_private_hyperlink(self):
        out=news.build_pages(lambda *args:args[2],'en')['actualizaciones/concept-search']
        self.assertIn('Project brief',out)
        self.assertNotIn('github.com/zaomir/grainee-v2',out)
        self.assertNotIn('ARTEMIS_FUNNEL_ATOMIC_PLAN',out)
    @unittest.skip("EN r2: diary is EN-only; no locale switcher / multi-locale news HTML")
    def test_article_menu_and_ru_switch_keep_meaningful_destinations(self):
        for loc in news.LANGS:
            root=ROOT/'app/tenerife_site'
            article=(root if loc=='en' else root/loc)/'actualizaciones/concept-search.html'
            body=article.read_text()
            self.assertIn('class="header__cta" href="'+news.locale_url(loc)+'"',body)
            if loc!='ru':self.assertIn('href="'+news.locale_url('ru','concept-search')+'" lang="ru"',body)

    @unittest.skip("EN r2: diary is EN-only; no locale switcher / multi-locale news HTML")
    def test_diary_is_discoverable_without_js_from_main_pages_and_footer(self):
        for loc in news.LANGS:
            root=ROOT/'app/tenerife_site'
            root=root if loc=='en' else root/loc
            for name in ('index','producto','inversores','privacy','actualizaciones','actualizaciones/concept-search'):
                body=(root/(name+'.html')).read_text()
                header=body[body.index('<header'):body.index('</header>')]
                footer=body[body.index('<footer'):body.index('</footer>')]
                target='href="'+news.locale_url(loc)+'"'
                self.assertGreaterEqual(header.count(target),2,(loc,name,'desktop and mobile menu'))
                self.assertIn(target,footer,(loc,name,'no-JS footer'))
                self.assertIn(news.UI[loc][0],header)

    @unittest.skip("EN r2: diary is EN-only; no locale switcher / multi-locale news HTML")
    def test_live_flask_routes_isolated_no_auth_no_js(self):
        import app
        c=app.app.test_client()
        for loc in news.LANGS:
            for slug in ('','concept-search'):
                response=c.get(news.locale_url(loc,slug))
                self.assertEqual(response.status_code,200,(loc,slug))
                self.assertIn(f'<html lang="{loc}">'.encode(),response.data)
                self.assertIn(b'rel="canonical"',response.data)
                self.assertNotIn(b'<form',response.data)
                self.assertIn(b'noindex',response.headers['X-Robots-Tag'].encode())
                self.assertIn(b'href="https://artemisresort.com'+news.locale_url(loc,slug).encode()+b'"',response.data)
        self.assertEqual(c.get('/tenerife/actualizaciones/missing/').status_code,404)
        r=c.get('/tenerife/en/actualizaciones/concept-search/')
        self.assertEqual(r.status_code,301)
        self.assertEqual(r.headers['Location'],'/tenerife/actualizaciones/concept-search/')


if __name__=='__main__':unittest.main()
