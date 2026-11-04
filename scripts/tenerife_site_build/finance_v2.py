"""PR38 internal deterministic finance primitives; NOT the public released model.

Integer cents for cash, Decimal for unrounded compound targets. Unknown mandatory
costs and unreviewed cash restrictions block any achievable-return assertion.
No taxpayer-specific fields or calculations are accepted.
"""
from datetime import date,timedelta
from decimal import Decimal as D, ROUND_HALF_UP
import hashlib
import json


def cents(value):
    return int((D(str(value))*100).quantize(D(1),rounding=ROUND_HALF_UP))


def version(inputs,assumptions,ledger):
    return 'artemis-v2-'+hashlib.sha256(json.dumps([inputs,assumptions,ledger],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]


def compound_target(tranches,exit_on,annual='0.09',day_count='ACT/365F'):
    """Day-count is a labeled modelling convention until counsel confirms it."""
    if day_count!='ACT/365F':raise ValueError('unsupported_day_count')
    exit_date=date.fromisoformat(exit_on);principal=0;target=D(0)
    for tranche in tranches:
        amount=tranche['principal_cents']
        if type(amount) is not int or amount<0:raise ValueError('invalid_principal')
        start=date.fromisoformat(tranche['funded_on'])
        if start>exit_date:raise ValueError('exit_before_funding')
        principal+=amount
        target+=D(amount)*(1+D(annual))**(D((exit_date-start).days)/365)
    target_cents=int(target.quantize(D(1),rounding=ROUND_HALF_UP))
    return dict(principal_cents=principal,target_cents=target_cents,
                target_interest_cents=target_cents-principal,annual_target=str(annual),
                day_count=day_count,day_count_status='proposed_not_contractual')


def waterfall(available_cents,principal_cents,interest_cents,mandatory_unpaid_cents=0):
    if any(type(v) is not int or v<0 for v in [available_cents,principal_cents,interest_cents,mandatory_unpaid_cents]):
        raise ValueError('invalid_cash')
    operating_paid=min(available_cents,mandatory_unpaid_cents)
    available=available_cents-operating_paid
    principal_paid=min(available,principal_cents);available-=principal_paid
    interest_paid=min(available,interest_cents);available-=interest_paid
    return dict(mandatory_paid_cents=operating_paid,mandatory_shortfall_cents=mandatory_unpaid_cents-operating_paid,
        principal_paid_cents=principal_paid,interest_paid_cents=interest_paid,
        principal_shortfall_cents=principal_cents-principal_paid,interest_shortfall_cents=interest_cents-interest_paid,
        sponsor_residual_cents=available)


def timeline(definitions):
    """Resolve explicit dates/dependencies; reject cycles and backward milestones."""
    pending={r['id']:dict(r) for r in definitions};resolved={}
    if len(pending)!=len(definitions):raise ValueError('duplicate_event')
    while pending:
        progressed=False
        for key,row in list(pending.items()):
            dep=row.get('after')
            if dep and dep not in resolved:continue
            if row.get('on'):
                due=date.fromisoformat(row['on'])
                if dep and due<resolved[dep]:raise ValueError('event_before_dependency')
            elif dep:
                due=resolved[dep]+timedelta(days=int(row.get('days_after',0)))
                if due<resolved[dep]:raise ValueError('negative_event_offset')
            else:raise ValueError('event_date_unknown')
            resolved[key]=due;del pending[key];progressed=True
        if not progressed:raise ValueError('cyclic_or_missing_event')
    return {k:v.isoformat() for k,v in resolved.items()}


def reserve_reconcile(allocated,committed,spent):
    """Allocation/commitment are classifications; only actual spend is an outflow.

    committed includes spent. Never add unused allocation to project cash.
    """
    if not 0<=spent<=committed<=allocated:raise ValueError('invalid_reserve_ledger')
    return dict(allocated_cents=allocated,committed_cents=committed,spent_cents=spent,
                unspent_committed_cents=committed-spent,unused_cents=allocated-committed)


def simulate(inflows,obligations,tranches,exit_on,*,reserve_allocated_cents=0,
             buyer_use_reviewed=False,budget_complete=False,legal_reviewed=False):
    """One event engine for isolated and combined stresses.

    No free funding plug. At the first uncovered expense construction stops;
    later obligations remain unpaid. Restricted buyer funds are never available
    to investor repayment. This deliberately conservative scaffold is internal.
    """
    days={date.fromisoformat(exit_on)}
    for row in inflows+obligations:days.add(date.fromisoformat(row['on']))
    if any(day>date.fromisoformat(exit_on) for day in days):raise ValueError('cash_after_exit_requires_later_exit')
    ids=[x['id'] for x in obligations]
    if len(set(ids))!=len(ids):raise ValueError('duplicate_cost')
    unknown=[r['id'] for r in obligations if r.get('amount_cents') is None and r.get('mandatory',True)]
    for row in inflows+obligations:
        amount=row.get('amount_cents')
        if amount is not None and (type(amount) is not int or amount<0):raise ValueError('invalid_amount')
    operating=restricted=0;stopped=False;unpaid=0;rows=[];gaps=[];reserve_spent=0
    for day in sorted(days):
        for r in [x for x in inflows if date.fromisoformat(x['on'])==day]:
            if r['bucket']=='buyer_restricted':restricted+=r['amount_cents']
            elif r['bucket']=='operating':operating+=r['amount_cents']
            else:raise ValueError('unknown_bucket')
        spent=0
        for r in [x for x in obligations if date.fromisoformat(x['on'])==day]:
            amount=r.get('amount_cents')
            if amount is None:
                stopped=True;continue
            if stopped:
                unpaid+=amount;continue
            eligible=bool(r.get('buyer_eligible')) and buyer_use_reviewed
            available=operating+(restricted if eligible else 0)
            if available<amount:
                gaps.append({'on':day.isoformat(),'obligation':r['id'],'required_external_cents':amount-available})
                stopped=True;unpaid+=amount;continue
            from_buyer=min(restricted,amount) if eligible else 0
            restricted-=from_buyer;operating-=amount-from_buyer;spent+=amount
            if r.get('reserve_draw'):
                reserve_spent+=amount
                if reserve_spent>reserve_allocated_cents:raise ValueError('reserve_overspent')
        rows.append(dict(on=day.isoformat(),operating_cents=operating,restricted_cents=restricted,spent_cents=spent,stopped=stopped))
    target=compound_target(tranches,exit_on)
    result=waterfall(operating,target['principal_cents'],target['target_interest_cents'],unpaid)
    complete=budget_complete and legal_reviewed and buyer_use_reviewed and not unknown
    status='incomplete' if not complete else 'stopped_pending_funding' if stopped else 'funded'
    return dict(status=status,target=target,arithmetic_only_waterfall=result,
        achievable_payout_cents=None if not complete or stopped else result['principal_paid_cents']+result['interest_paid_cents'],
        operating_cents=operating,restricted_cents=restricted,unpaid_costs_cents=unpaid,
        missing_mandatory_costs=unknown,gaps=gaps,monthly_or_event_rows=rows,
        reserve_spent_cents=reserve_spent,reserve_allocation_is_extra_cash=False,
        protection_claim_allowed=False)


def stress(inflows,obligations,tranches,exit_on,*,cost_factor='1',price_factor='1',sales_delay_days=0,**settings):
    """Overrides apply to source cash events, never directly to final balances."""
    if D(cost_factor)<0 or D(price_factor)<0 or sales_delay_days<0:raise ValueError('invalid_stress')
    incoming=[];costs=[]
    for item in inflows:
        row=dict(item)
        if row.get('source')=='buyer_sale':
            row['amount_cents']=int((D(row['amount_cents'])*D(price_factor)).quantize(D(1),rounding=ROUND_HALF_UP))
            row['on']=(date.fromisoformat(row['on'])+timedelta(days=sales_delay_days)).isoformat()
        incoming.append(row)
    for item in obligations:
        row=dict(item)
        if row.get('category')=='construction' and row.get('amount_cents') is not None:
            row['amount_cents']=int((D(row['amount_cents'])*D(cost_factor)).quantize(D(1),rounding=ROUND_HALF_UP))
        costs.append(row)
    return simulate(incoming,costs,tranches,exit_on,**settings)
