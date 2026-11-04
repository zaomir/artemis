from decimal import Decimal as D
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/tenerife_site_build'))
import finance_v2 as f


class FinanceTest(unittest.TestCase):
    def test_actual_funded_days_not_before_funding(self):
        # Exactly 365 days; independent 109% reference, no calendar-month proxy.
        r=f.compound_target([dict(principal_cents=10000,funded_on='2025-01-01')],'2026-01-01')
        self.assertEqual(r['target_cents'],10900)
        self.assertEqual(f.compound_target([dict(principal_cents=10000,funded_on='2026-01-01')],'2026-01-01')['target_cents'],10000)
        with self.assertRaises(ValueError):f.compound_target([dict(principal_cents=1,funded_on='2026-02-01')],'2026-01-01')
    def test_tranche_dates_change_interest(self):
        early=f.compound_target([dict(principal_cents=20000,funded_on='2025-01-01'),dict(principal_cents=80000,funded_on='2025-10-01')],'2028-10-01')
        late=f.compound_target([dict(principal_cents=100000,funded_on='2025-10-01')],'2028-10-01')
        self.assertGreater(early['target_cents'],late['target_cents'])
    def test_waterfall_partial_principal_and_no_sponsor(self):
        r=f.waterfall(5000,10000,900,1000)
        self.assertEqual(r['principal_paid_cents'],4000);self.assertEqual(r['interest_paid_cents'],0)
        self.assertEqual(r['sponsor_residual_cents'],0);self.assertEqual(r['principal_shortfall_cents'],6000)
    def test_sponsor_after_cap(self):
        r=f.waterfall(15000,10000,900)
        self.assertEqual(r['interest_paid_cents'],900);self.assertEqual(r['sponsor_residual_cents'],4100)
    def test_reserve_cannot_be_drawn_twice(self):
        r=f.reserve_reconcile(1000,800,600)
        self.assertEqual(r['unused_cents'],200)
        self.assertEqual(r['unspent_committed_cents'],200)
        with self.assertRaises(ValueError):f.reserve_reconcile(1000,800,801)
    def test_timeline_shifts_dependencies(self):
        r=f.timeline([dict(id='permit',on='2027-08-04'),dict(id='purchase',after='permit',days_after=10),dict(id='works',after='purchase',days_after=30)])
        self.assertEqual(r['purchase'],'2027-08-14');self.assertEqual(r['works'],'2027-09-13')
        with self.assertRaises(ValueError):f.timeline([dict(id='a',after='b'),dict(id='b',after='a')])
    def scenario(self,**settings):
        return f.simulate([dict(on='2026-01-01',amount_cents=20000,bucket='operating'),dict(on='2026-01-01',amount_cents=80000,bucket='buyer_restricted')],
            [dict(id='land',on='2026-01-01',amount_cents=79900,category='land',buyer_eligible=False)],
            [dict(principal_cents=20000,funded_on='2026-01-01')],'2027-01-01',**settings)
    def test_restricted_cash_does_not_buy_land_or_redeem(self):
        r=self.scenario(buyer_use_reviewed=True,budget_complete=True,legal_reviewed=True)
        self.assertEqual(r['gaps'][0]['required_external_cents'],59900)
        self.assertEqual(r['restricted_cents'],80000)
        self.assertIsNone(r['achievable_payout_cents'])
        self.assertEqual(r['status'],'stopped_pending_funding')
    def test_incomplete_never_claims_achievable_return(self):
        r=self.scenario()
        self.assertEqual(r['status'],'incomplete');self.assertIsNone(r['achievable_payout_cents'])
    def test_unknown_cost_is_missing_not_zero(self):
        r=f.simulate([], [dict(id='mandatory_tax',on='2026-01-01',amount_cents=None)],[],'2026-01-01',budget_complete=True,legal_reviewed=True,buyer_use_reviewed=True)
        self.assertIn('mandatory_tax',r['missing_mandatory_costs']);self.assertEqual(r['status'],'incomplete')
    def test_version_changes_with_evidence(self):
        self.assertNotEqual(f.version({}, {'status':'assumed'},{}),f.version({}, {'status':'verified'},{}))
    def test_final_rounding_once(self):
        self.assertEqual(f.cents('1.005'),101)


if __name__=='__main__':unittest.main()
