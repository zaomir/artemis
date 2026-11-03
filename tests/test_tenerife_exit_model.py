"""Financial regression points agreed in the 2026-11-03 cash-exit workbook.
The reference amounts are independently reviewed examples, not regenerated fixtures.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/tenerife_site_build'))
sys.path.insert(0, str(ROOT / 'app'))
from make_model import project_cash, build_model
from tenerife_calc import check_calc


class CashExitModelTest(unittest.TestCase):
    def setUp(self):
        self.inputs = json.loads((ROOT / 'scripts/tenerife_site_build/model_inputs.json').read_text())
        self.model = build_model(self.inputs)

    def test_sources_uses_and_lowest_balance_match_workbook(self):
        p = self.model['project']
        for field, amount in {'capital_eur':1326528, 'sales_eur':5129876.769094371,
                              'sales_fee_eur':153896.30307283113, 'budget_eur':4490813.25,
                              'redemption_eur':1717892.229312, 'surplus_eur':93802.98670954,
                              'minimum_cash_eur':53083.410255158}.items():
            self.assertAlmostEqual(p[field], amount, places=5, msg=field)
        self.assertEqual((p['early_shares'], p['area_m2'], p['minimum_cash_month']), (564,1409,7))
        self.assertGreaterEqual(min(r['cash_eur'] for r in p['monthly']), 0)
        self.assertAlmostEqual(sum(r['cost_eur'] for r in p['monthly']), 4490813.25)
        self.assertEqual([r['month'] for r in p['monthly'] if r['investor_paid_eur']>0], [36])
        self.assertEqual(self.model['investment']['developer_contribution_eur'], 0)

    def test_homes_sold_once_and_prices_locked_at_signing(self):
        p=self.model['project']
        self.assertEqual(len(p['contracts']),20)
        self.assertAlmostEqual(sum(r['buyer_eur'] for r in p['monthly']),p['sales_eur'])
        # First sale: 92.5m² at month 3; month-9 buyer pays 70% immediately.
        self.assertAlmostEqual(p['monthly'][3]['buyer_eur'], 92.5*3360*1.06**(3/12)*.4)
        self.assertAlmostEqual(p['monthly'][9]['buyer_eur'], 51.5*3360*1.06**(9/12)*.7)
        self.assertAlmostEqual(p['monthly'][36]['buyer_eur'],p['sales_eur']*.2)
        self.assertLess(p['sales_eur'],1409*3360*1.06**3)
        self.assertFalse(self.model['quantity_is_property_entitlement'])

    def test_delays_and_higher_costs_show_unfunded_amounts(self):
        high=project_cash(self.inputs,cost_m2=2100)
        delayed=project_cash(self.inputs,sales_delay=2)
        flat=project_cash(self.inputs,growth=0)
        self.assertAlmostEqual(high['redemption_shortfall_eur'],562579.66329046,places=4)
        self.assertAlmostEqual(-delayed['minimum_cash_eur'],202235.988908,places=3)
        self.assertGreater(delayed['surplus_eur'],0)  # final profit cannot fill an interim cash gap
        self.assertLess(flat['minimum_cash_eur'],0)
        self.assertGreater(flat['redemption_shortfall_eur'],0)

    def test_obsolete_offer_is_marked_stale_and_recomputed(self):
        c, problems=check_calc({'calc_m2':'72','calc_step':'foundation','calc_pay':'m6'},self.model)
        self.assertEqual(c['calc_status'],'mismatch')
        self.assertEqual((c['calc_step_server'],c['calc_pay_server']),('early','now'))
        self.assertEqual((c['calc_amount'],c['calc_exit_amount'],c['calc_income']),(169344,219305,49961))
        self.assertIsNone(c['calc_month_eur'])
        self.assertTrue(problems)

    def test_public_pages_and_calculators_use_only_current_model(self):
        for loc in ('ru','en','es','de','fr'):
            folder=ROOT/'app/tenerife_site'/('' if loc=='en' else loc)
            for name in ('index','inversores','calculadora','producto','proceso','faq','mercado','energia','simon','boris'):
                text=(folder/(name+'.html')).read_text()
                self.assertNotRegex(text,r'2[ \u00a0]950|3[ \u00a0]850|2,5–3,5|@[a-z][a-z0-9_]*@')
            for name in ('inversores','calculadora'):
                text=(folder/(name+'.html')).read_text()
                self.assertIn('data-k="exit">219\u00a0305\u00a0€',text)
                self.assertIn('data-k="gain">49\u00a0961\u00a0€',text)
                self.assertIn('name="calc_pay" id="wl-calc-pay" value="now"',text)
                self.assertIn('calc.js?v=',text)
                self.assertNotIn('name="pay"',text)
                self.assertNotIn('name="step"',text)


if __name__=='__main__':
    unittest.main()
