#!/usr/bin/env python3
"""PR-A01: independent Decimal reproduction of the historical monthly model."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/tenerife_site_build'))
import make_model


def freeze():
    inputs=json.loads((ROOT/'scripts/tenerife_site_build/model_inputs.json').read_text())
    b,f=inputs['budget'],inputs['financing']
    area=sum(D(n)*(D(lo)+D(hi))/2 for _,n,lo,hi in inputs['units'])
    shares=(area*D(str(f['early_pool_fraction']))).to_integral_value(rounding=ROUND_CEILING)
    entry=D(inputs['market_reference_eur_m2'])*(1-D(str(inputs['early_discount'])))
    capital=shares*entry
    hard=area*D(str(b['built_area_factor']))*D(b['construction_eur_m2'])
    base=D(b['land_eur'])+hard*(1+D(str(b['technical_fraction'])))+D(b['infrastructure_eur'])+D(b['other_eur'])
    budget=base*(1+D(str(b['contingency_fraction'])))
    target=capital*(1+D(str(inputs['target_annual'])))**(D(inputs['exit_months'])/12)
    receipts=[D(0)]*61
    for kind,month in zip(f['sale_unit_types'],f['sale_months'],strict=True):
        unit=inputs['units'][kind-1]
        price=(D(unit[2])+D(unit[3]))/2*D(inputs['market_reference_eur_m2'])*D('1.06')**(D(month)/12)
        due=[month,max(month,f['foundation_month']),max(month,f['shell_month']),inputs['exit_months']]
        for m,fraction in zip(due,f['buyer_installments'],strict=True):receipts[m]+=price*D(str(fraction))
    monthly=[];cash=D(0)
    for month,incoming in enumerate(receipts):
        expense=D(b['land_eur']) if month==0 else D(0)
        for start,end,fraction in f['cost_phases']:
            if start<=month<=end:expense+=(budget-D(b['land_eur']))*D(str(fraction))/D(end-start+1)
        cash+=(capital if month==0 else D(0))+incoming-expense-incoming*D(str(f['sales_fee_fraction']))
        if month==inputs['exit_months']:cash-=min(target,max(cash,D(0)))
        monthly.append((month,cash))
    minimum=min(monthly,key=lambda r:r[1])
    sales=sum(receipts)
    raw=dict(area_m2=area,early_shares=shares,capital_eur=capital,budget_eur=budget,
             sales_eur=sales,sales_fee_eur=sales*D('.03'),redemption_eur=target,
             surplus_eur=capital+sales*D('.97')-budget-target,
             minimum_cash_eur=minimum[1],minimum_cash_month=minimum[0])
    old=make_model.project_cash(inputs)
    for key,value in raw.items():
        if abs(D(str(old[key]))-D(value))>D('.005'):raise ValueError('Independent baseline differs: '+key)
    money=lambda n:str(D(n).quantize(D('.01'),rounding=ROUND_HALF_UP))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
        ROOT/'scripts/tenerife_site_build/model_inputs.json',ROOT/'scripts/tenerife_site_build/make_model.py',
        ROOT/'app/static/tenerife/site/model.json',ROOT/'app/tenerife_calc.py',ROOT/'tests/test_tenerife_exit_model.py',
        *[p for p in (ROOT/'app/tenerife_site').rglob('*.html') if 'actualizaciones' not in str(p)]]}
    return {'atom':'PR-A01','source_sha':'664ecd600a03790738ae06e520c0ff62f61a20d7',
        'baseline_version':make_model.build_model(inputs)['version'],
        'independent_decimal_arithmetic':{k:money(v) for k,v in raw.items()},
        'reserve_already_in_budget_eur':money(base*D('.1')),
        'entry_72_eur':money(72*entry),'target_72_unrounded_display_eur':money(72*entry*D('1.09')**3),
        'target_72_display_eur':str((72*entry*D('1.09')**3).quantize(D('1'),rounding=ROUND_HALF_UP)),
        'hashes':hashes,'regressions_passed':5,'live_baseline':'UNVERIFIED_no_VPS_channel'}


if __name__=='__main__':
    target=ROOT/'docs/funnel/evidence/PR-A01.json'
    target.write_text(json.dumps(freeze(),indent=2)+'\n')
    print('Independent historical baseline reproduced; no public model changed.')
