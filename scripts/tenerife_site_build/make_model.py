"""Public exit model: one source for copy, calculator and monthly financing.
Market price and growth are assumptions. Investor capital is financing;
each residence has one sale, locked at signing. No annual distributions.
"""
import json
import hashlib
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / 'model_inputs.json'
OUT = HERE.parents[1] / 'app/static/tenerife/site/model.json'


def fmt(value, decimals=0):
    value = Decimal(str(value)).quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
    return f'{value:,.{decimals}f}'.replace(',', ' ').replace('.', ',')


def project_cash(inp, *, cost_m2=None, sales_delay=0, growth=None):
    """Unrounded monthly cash flow; contingency is spent, no financing plug."""
    f, costs = inp['financing'], inp['budget']
    market = inp['market_reference_eur_m2']
    growth = inp['growth_annual'] if growth is None else growth
    area = sum(u[1] * (u[2] + u[3]) / 2 for u in inp['units'])
    shares = int(Decimal(str(area * f['early_pool_fraction'])).to_integral_value(rounding=ROUND_CEILING))
    capital = shares * market * (1 - inp['early_discount'])
    hard = area * costs['built_area_factor'] * (cost_m2 or costs['construction_eur_m2'])
    budget = (costs['land_eur'] + hard * (1 + costs['technical_fraction'])
              + costs['infrastructure_eur'] + costs['other_eur']) * (1 + costs['contingency_fraction'])
    exit_month = inp['exit_months']
    redemption = capital * (1 + inp['target_annual']) ** (exit_month / 12)
    receipts = [0.0] * (max(60, exit_month) + 1)
    contracts = []
    for index, (kind, signing) in enumerate(zip(f['sale_unit_types'], f['sale_months'], strict=True), 1):
        unit = inp['units'][kind - 1]
        unit_area = (unit[2] + unit[3]) / 2
        signing += sales_delay
        value = unit_area * market * (1 + growth) ** (signing / 12)
        months = [signing, max(signing, f['foundation_month']), max(signing, f['shell_month']), exit_month]
        for month, fraction in zip(months, f['buyer_installments'], strict=True):
            if month < len(receipts):
                receipts[month] += value * fraction
        contracts.append({'unit': index, 'area_m2': unit_area, 'signing_month': signing, 'value_eur': value})
    cash, rows = 0.0, []
    for month, incoming in enumerate(receipts):
        expense = costs['land_eur'] if month == 0 else 0.0
        for start, end, fraction in f['cost_phases']:
            if start <= month <= end:
                expense += (budget - costs['land_eur']) * fraction / (end - start + 1)
        fee = incoming * f['sales_fee_fraction']
        available = cash + (capital if month == 0 else 0) + incoming - expense - fee
        paid = min(redemption, max(available, 0)) if month == exit_month else 0
        cash = available - paid
        rows.append({'month': month, 'buyer_eur': incoming, 'cost_eur': expense,
                     'sales_fee_eur': fee, 'investor_paid_eur': paid, 'cash_eur': cash})
    sales = sum(c['value_eur'] for c in contracts)
    minimum = min(rows, key=lambda row: row['cash_eur'])
    return {'area_m2': area, 'early_shares': shares, 'capital_eur': capital,
            'budget_eur': budget, 'sales_eur': sales,
            'sales_fee_eur': sales * f['sales_fee_fraction'], 'redemption_eur': redemption,
            'surplus_eur': capital + sales * (1-f['sales_fee_fraction']) - budget - redemption,
            'minimum_cash_eur': minimum['cash_eur'], 'minimum_cash_month': minimum['month'],
            'redemption_shortfall_eur': redemption - rows[exit_month]['investor_paid_eur'],
            'contracts': contracts, 'monthly': rows}


def build_model(inputs=None):
    inp = inputs if inputs is not None else json.loads(INPUTS.read_text(encoding='utf-8'))
    market = inp['market_reference_eur_m2']
    entry = round(market * (1 - inp['early_discount']), 2)
    months = inp['exit_months']
    factor = (1 + inp['target_annual']) ** (months / 12)
    project = project_cash(inp)
    high = project_cash(inp, cost_m2=2100)
    delay = project_cash(inp, sales_delay=2)
    values = {'market': market, 'entry': entry, 'discount': inp['early_discount'] * 100,
              'growth': inp['growth_annual'] * 100, 'target': inp['target_annual'] * 100,
              'months': months, 'gain_pct': (factor-1)*100, 'pool': project['early_shares'],
              'pool_capital': project['capital_eur'], 'pool_exit': project['redemption_eur'],
              'area': project['area_m2'], 'budget': project['budget_eur'],
              'sales': project['sales_eur'], 'sales_fee': project['sales_fee_eur'],
              'surplus': project['surplus_eur'], 'minimum_cash': project['minimum_cash_eur'],
              'high_shortfall': max(high['redemption_shortfall_eur'], 0),
              'delay_gap': max(-delay['minimum_cash_eur'], 0),
              'cost_m2': inp['budget']['construction_eur_m2']}
    for year in range(4):
        values[f'market_y{year}'] = market * (1 + inp['growth_annual']) ** year
    for quantity in (48, 72, 100):
        values[f'entry_{quantity}'] = quantity * entry
        values[f'exit_{quantity}'] = quantity * entry * factor
        values[f'gain_{quantity}'] = quantity * entry * (factor - 1)
    for index, unit in enumerate(inp['units'], 1):
        values[f'home_{index}_low'] = unit[2] * market
        values[f'home_{index}_high'] = unit[3] * market
    tokens = [{'id': key, 'label': key, 'copy': f'@{key}@', 'value': fmt(value, 1 if key == 'gain_pct' else 0)}
              for key, value in values.items()]
    return {'_generated_by': 'scripts/tenerife_site_build/make_model.py from model_inputs.json',
            'version': '2026-11-03-exit-' + hashlib.sha256(json.dumps(inp, sort_keys=True).encode()).hexdigest()[:12], 'status': 'illustrative planning model; market reference unverified',
            'currency': 'EUR', 'kind': 'upfront_exit', 'share_m2': 1,
            'quantity_unit': 'shares', 'quantity_is_property_entitlement': False,
            'steps': [{'id': 'early', 'name': 'Ранний вход', 'price_eur_m2': entry, 'entry': True, 'current': True}],
            'installments': {'months': 0},
            'area_m2': {'min': 48, 'max': 100, 'default': 72},
            'types': [{'id': f'q{q}', 'name': f'{q} акций', 'min': q, 'max': q, 'quantity': q} for q in (48, 72, 100)],
            'investment': {'market_reference_eur_m2': market, 'market_reference_status': 'assumption',
                           'early_discount': inp['early_discount'], 'growth_annual': inp['growth_annual'],
                           'target_annual': inp['target_annual'], 'exit_months': months,
                           'interim_distributions': False, 'developer_contribution_eur': 0,
                           'payment': 'now', 'exit': 'cash_from_sales_or_buyback',
                           'growth_locked_at_buyer_signing': True,
                           'buyer_installments': inp['financing']['buyer_installments'],
                           'early_pool_shares': project['early_shares']},
            'project': project, 'tokens': tokens, 'extra': [],
            'rounding': {'rule': 'ROUND_HALF_UP', 'money': 'integer_eur_half_up'}, 'type_click_sets': 'quantity'}


def baseline_check():
    inp = json.loads(INPUTS.read_text(encoding='utf-8'))
    p = project_cash(inp)
    errors = []
    if abs(sum(inp['financing']['buyer_installments']) - 1) > 1e-9:
        errors.append('buyer installments must sum to 100%')
    if abs(sum(x[2] for x in inp['financing']['cost_phases']) - 1) > 1e-9:
        errors.append('construction cost phases must sum to 100%')
    if len(p['contracts']) != sum(u[1] for u in inp['units']):
        errors.append('one buyer contract per home required')
    if p['minimum_cash_eur'] < 0 or p['redemption_shortfall_eur'] > 0.01:
        errors.append('base schedule does not finance the full target exit')
    return errors


def main():
    errors = baseline_check()
    if errors:
        raise SystemExit('\n'.join(errors))
    text = json.dumps(build_model(), ensure_ascii=False, indent=1) + '\n'
    if '--check' in sys.argv:
        ok = OUT.is_file() and OUT.read_text(encoding='utf-8') == text
        print('model.json up to date' if ok else 'model.json is stale: run make_model.py')
        raise SystemExit(0 if ok else 1)
    OUT.write_text(text, encoding='utf-8')
    print('model.json: upfront investment, single cash exit, monthly project cash flow')


if __name__ == '__main__':
    main()
