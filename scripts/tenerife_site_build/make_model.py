"""numbers.md + model_inputs.json -> app/static/tenerife/site/model.json (RU v3, single source of figures).

copy_v3/numbers.md is the baseline: every figure token the copy uses, in make_numbers.py order.
model_inputs.json holds the inputs (stage prices, rent, costs, ...). This script recomputes every
token with the same formulas as copy_v3/make_numbers.py and writes model.json:
  tokens[i] = {"label", "copy": figure as written in the copy, "value": figure for the site}
build_v3.py replaces copy -> value in the texts, calc.js reads "calc" — so a price change is
one edit in model_inputs.json. Exit 1 if numbers.md and the formulas disagree on the baseline.

  python3 scripts/tenerife_site_build/make_model.py [--check]
"""
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NUMBERS = HERE / "copy_v3" / "numbers.md"
INPUTS = HERE / "model_inputs.json"
OUT = ROOT / "app" / "static" / "tenerife" / "site" / "model.json"


def fmt(x, dec=0):
    if dec == 0:
        return f"{round(x):,}".replace(",", " ")
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", " ")


def compute(inp):
    """Port of copy_v3/make_numbers.py (MODEL + tokens), parametrised by model_inputs.json.
    Returns (tokens [(label, value, optional)], calc dict). Order == numbers.md order."""
    stages = [(n, p) for n, p in inp["stages"]]
    sp = dict(stages)
    q, v = stages[0][1], stages[-1][1]          # Очередь, Ввод
    months = inp["installment_months"]
    rent = inp["rent_mid"]
    g = rent * 12
    la, lb = inp["living_area_range"]
    avg = (la + lb) / 2 / sum(u[1] for u in inp["units"])
    c = inp["costs"]
    comm = c["community_per_month"]
    bas = c["waste_per_year"] / c["waste_area"]
    items = [("IBI", c["ibi_per_year"] / c["ibi_area"]), ("Взносы сообщества", comm * 12 / avg),
             ("Управление", g * c["management_share"] * c["igic"]), ("Простой", rent * c["vacancy_months"]),
             ("Страховка", c["insurance_per_year"] / c["insurance_area"]), ("Резерв на ремонт", g * c["repair_share"]),
             ("Сбор за мусор", bas)]
    cost = sum(round(x, 2) for _, x in items)
    d = round(g - cost)

    def scen(s, area):
        gg = s["rent"] * 12
        cc = (c["ibi_per_year"] / c["ibi_area"] + comm * 12 / area + gg * s["management_share"] * c["igic"]
              + s["rent"] * s["vacancy_months"] + c["insurance_per_year"] / c["insurance_area"]
              + gg * s["repair_share"] + bas)
        return cc, cc / gg, gg - cc

    mild = scen(inp["scenario_mild"], inp["scenario_mild"]["area"])
    strict = scen(inp["scenario_strict"], inp["scenario_strict"]["area"])
    r0, r1 = inp["rent_range"]
    h0, h1 = inp["house_price_range"]
    tok = []

    def t(name, val, opt=False):
        tok.append((name, val, opt))

    for n, p in stages:
        t(f"Ступень «{n}», €/м² (PROPOSAL)", fmt(p))
    t("Аренда-середина, €/м²/мес", fmt(rent, 1))
    t("Аренда × 12, € с метра", f"{fmt(g)} €")
    for n, x in items:
        dec = 2 if n in ("IBI", "Простой") else 1
        t(f"Расходы: {n}, € с м²/год", fmt(x, dec))
        t(f"Расходы: {n}, % от 162 €", fmt(x / g * 100, 1) + "%")
    t("Расходы итого, € с м²/год", fmt(cost, 1))
    t("Расходы итого, %", fmt(cost / g * 100, 1) + "%")
    t("Дивиденд, € на акцию в год, расчётно, до налога на прибыль компании", f"{d} €")
    t("Мягкий сценарий, расходы %", fmt(mild[1] * 100, 1) + "%")
    t("Мягкий сценарий, дивиденд", f"около {round(mild[2])} €")
    t("Строгий сценарий, расходы %", fmt(strict[1] * 100, 1) + "%")
    t("Строгий сценарий, дивиденд", f"около {round(strict[2])} €")
    t("Жилая площадь, сумма по типам", f"{fmt(la)}–{fmt(lb)}")
    for m in (48, 72, 100):
        for n, p in stages:
            if m == 72 or n in (stages[0][0], stages[-1][0]):
                t(f"{m} м² × {fmt(p)}", fmt(m * p))
        t(f"{m} м² × {fmt(q)} ÷ {months}", fmt(m * q / months))
        t(f"Разница {m} м² ввод−очередь", fmt(m * (v - q)))
        t(f"{m} × {d} (дивиденд в год)", fmt(m * d))
        t(f"{m} × {d} ÷ 12", fmt(m * d / 12))
    t(f"72 м² × {fmt(sp['Коробка и кровля'])} ÷ {months}", fmt(72 * sp["Коробка и кровля"] / months))
    t("72 м²: очередь→разрешение", fmt(72 * (stages[1][1] - q)))
    units = [(u[2], u[3]) for u in inp["units"]]
    for a, b in units:
        t(f"{a}–{b} м² × {fmt(q)}", f"{fmt(a * q)}–{fmt(b * q)}")
        t(f"{a}–{b} × {d} (дивиденд)", f"{fmt(a * d)}–{fmt(b * d)}")
    for a, b in (units[0], units[2]):
        t(f"{a}–{b} м² × {fmt(v)}", f"{fmt(a * v)}–{fmt(b * v)}")
        t(f"{a}–{b} м² × {r0}–{r1} € аренды/мес", f"{fmt(a * r0)}–{fmt(b * r1)}")
    t(f"72 м² × {r0}–{r1} € аренды/мес", f"{fmt(72 * r0)}–{fmt(72 * r1)}")
    t(f"72 м² × {r0}–{r1} € × 12", f"{fmt(72 * r0 * 12)}–{fmt(72 * r1 * 12)}")
    t(f"IGIC 7% от {fmt(72 * v)}", fmt(72 * v * inp["tax_igic"]))
    t(f"AJD 1% от {fmt(72 * v)}", fmt(72 * v * inp["tax_ajd"]))
    for n, p in stages:
        t(f"Рост до цены ввода от {fmt(p)}", fmt((v / p - 1) * 100, 1) + "%", opt=(n == stages[-1][0]))
        t(f"{d} / {fmt(p)}", fmt(d / p * 100, 1) + "%")
    # Kimi r18 (founder 31.10): payment terms are copy figures only; the calculator still offers «сразу» / 12 months
    t("Оплата сразу полностью: бонус (ОСН 31.10)", "бонус 10%")
    t("Оплата за полгода: бонус (ОСН 31.10)", "бонус 5%")
    t("Оплата за год (ОСН 31.10)", "без бонуса")
    names = ("Резиденция 1 спальня = акций", "2 спальни = акций", "Большой дом = акций")
    for name, (a, b) in zip(names, units, strict=True):
        t(name, f"{a}–{b} акций")
    t0, t1 = inp["topup"]
    t(f"Докупка {t0}→{t1}", f"{t1 - t0} акци")
    t("PVGIS La Quinta, кВт·ч/кВт в год, панели плоско", fmt(inp["pvgis_flat"]))
    t("Канары среднее, кВт·ч/кВт", fmt(inp["canary_avg"]))
    t("PVGIS La Quinta, оптимальный наклон 23°", fmt(inp["pvgis_optimal"]))
    for a, b in units:
        t(f"Дом на вводе {a}–{b} м² × {fmt(h0)}–{fmt(h1)}", f"{fmt(a * h0)}–{fmt(b * h1)}")
    t(f"Дом на вводе 72 м² × {fmt(h0)}–{fmt(h1)}", f"{fmt(72 * h0)}–{fmt(72 * h1)}")
    t(f"Дом на вводе 100 м² × {fmt(h0)} (от)", f"от {fmt(100 * h0)}")
    t("Дом 50 м²", "50 м²")
    t("Дом 95 м²", "95 м²")
    pu = inp["rent_puerto"]
    for m in (50, 72, 95):
        if m != 72:
            t(f"{m} м² × {r0}–{r1} €", f"{fmt(m * r0)}–{fmt(m * r1)}")
        t(f"{m} м² × {pu} € (Puerto)", f"около {fmt(m * pu)} €")
    eb = inp["example_bill_per_month"]
    t(f"Пример счёта {eb} €/мес × 12 (grupodlt)", fmt(eb * 12))
    t("Расходы итого, € с метра (округл.)", f"{round(cost)} € с метра")
    t("Докупка: начали с", f"{t0} акций")
    mk = inp["market"]
    a3, b3 = mk["lq3_prices"]
    t("La Quinta III, цены 4 домов (estatenearme)", f"{fmt(a3)}–{fmt(b3)}")
    t("La Quinta III, € за м² = 420–425 тыс. ÷ 125", f"{fmt(a3 / mk['lq3_area'])}–{fmt(b3 / mk['lq3_area'])}")
    a2, b2 = mk["lq2_prices"]
    t("La Quinta 2, цены (estatenearme)", f"{fmt(a2)}–{fmt(b2)}")
    t("La Quinta 2, € за м² ÷ 110", f"{fmt(a2 / mk['lq2_area'])}–{fmt(b2 / mk['lq2_area'])}")
    t("Kelify, районы Santa Úrsula, март 2026, €/м²", mk["kelify_su"])
    t("Kelify, La Quinta 80 м²", f"{fmt(mk['kelify_80'])} €")
    t("Kelify, La Quinta 60 м²", f"{fmt(mk['kelify_60'])} €")
    t("Kelify, La Quinta 132 м² (8 oct 2026)", f"{fmt(mk['kelify_132'])} €")
    # inputs written in the copy as-is (not in numbers.md): canon house price and rent range
    t("[extra] Дом на вводе, канон €/м²", f"{fmt(h0)}–{fmt(h1)}")
    t("[extra] Дом на вводе, от €/м²", f"от {fmt(h0)} €")
    # 03: «55 метров — 162 250 €», «85 метров — 250 750 €» (upper / lower bound of a type × Очередь)
    t("[extra] Одна спальня, макс. м² × Очередь", f"{fmt(inp['units'][0][3] * q)} €")
    t("[extra] Большой дом, мин. м² × Очередь", f"{fmt(inp['units'][2][2] * q)} €")
    calc = {"stages": [{"name": n, "price": p} for n, p in stages], "dividend": d, "months": months,
            "area": {"min": inp["calc_area_range"][0], "max": inp["calc_area_range"][1],
                     "default": inp["calc_default_area"]},
            "units": [{"name": u[0], "count": u[1], "min": u[2], "max": u[3]} for u in inp["units"]]}
    return tok, calc


def parse_numbers(path=NUMBERS):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (.+?) — (.+?)  \((\d+) вхожд\.\)$", line)
        if m:
            out.append((m.group(1), m.group(2), int(m.group(3))))
    return out


def build_model(inputs=None):
    inputs = inputs if inputs is not None else json.loads(INPUTS.read_text(encoding="utf-8"))
    base = parse_numbers()
    tok, calc = compute(inputs)
    core = [x for x in tok if not x[0].startswith("[extra]")]
    if len(core) != len(base):
        raise SystemExit(f"make_model: {len(core)} formulas vs {len(base)} tokens in numbers.md")
    tokens = []
    for i, ((copy, blabel, hits), (_label, value, _opt)) in enumerate(zip(base, core, strict=True)):
        tokens.append({"id": f"t{i:03d}", "label": blabel, "copy": copy, "value": value, "hits": hits})
    extra = [x for x in tok if x[0].startswith("[extra]")]
    st = inputs["stages"]
    design = {  # = web-designer/tenerife/design/model.json schema (DESIGN.md §C8, §C9)
        "version": "2026-10-31-v2",
        "status": "PROPOSAL — ступени, рассрочка и дивиденд ждут ОК основателя (numbers.md, sources_v3.md)",
        "currency": "EUR", "share_m2": 1,
        "steps": [dict({"id": inputs["stage_ids"][i], "name": n, "event": inputs["stage_events"][i],
                        "price_eur_m2": p, "entry": i < len(st) - 1},
                       **({"current": True} if i == inputs["current_stage"] else {}))
                  for i, (n, p) in enumerate(st)],
        "installments": {"months": inputs["installment_months"], "surcharge": 0},
        "dividend_eur_per_share_year": calc["dividend"],
        "area_m2": {"min": inputs["calc_area_range"][0], "max": inputs["calc_area_range"][1],
                    "default": inputs["calc_default_area"]},
        "types": [{"id": inputs["unit_ids"][i], "name": u[0], "min": u[2], "max": u[3], "count": u[1]}
                  for i, u in enumerate(inputs["units"])],
        "house_on_handover_eur_m2": {"min": inputs["house_price_range"][0], "max": inputs["house_price_range"][1]},
        "rounding": {
            "rule": "ROUND_HALF_UP",
            "note": ("Одно правило везде: x,5 → вверх. Деньги — до целых евро, проценты — до 0,1, "
                     "площадь середины типа — до целого м². Python: decimal ROUND_HALF_UP (copy_v3/make_numbers.py), "
                     "JS: Math.floor(x + 0.5) для положительных, Intl roundingMode 'halfExpand'. "
                     "Пример: 57 м² × 2 950 ÷ 12 = 14 012,5 → 14 013 €."),
            "money": "integer_eur_half_up",
            "percent": "1_decimal_half_up",
            "type_midpoint_m2": "integer_half_up",
        },
        "type_click_sets": "midpoint",
        "type_midpoints_m2": {inputs["unit_ids"][i]: int(Decimal(u[2] + u[3]) / 2 + Decimal("0.5"))
                              for i, u in enumerate(inputs["units"])},
    }
    return {"_generated_by": "scripts/tenerife_site_build/make_model.py from copy_v3/numbers.md + model_inputs.json",
            **design,
            "proposal": True, "calc": calc, "tokens": tokens,
            "extra": [{"id": f"x{i:02d}", "label": n[len('[extra] '):], "value": val, "copy": cp}
                      for i, ((n, val, _o), cp) in enumerate(zip(extra, extra_baseline(), strict=True))]}


def baseline_check():
    """With the committed baseline inputs the formulas must reproduce numbers.md exactly."""
    base = parse_numbers()
    tok, _ = compute(json.loads((HERE / "model_inputs.baseline.json").read_text(encoding="utf-8")))
    core = [x for x in tok if not x[0].startswith("[extra]")]
    errs = []
    if len(core) != len(base):
        errs.append(f"{len(core)} formulas vs {len(base)} tokens")
    for (copy, blabel, _h), (label, value, _o) in zip(base, core, strict=True):
        if (copy, blabel) != (value, label):
            errs.append(f"numbers.md «{copy} — {blabel}» != formula «{value} — {label}»")
    return errs


def extra_baseline():
    tok, _ = compute(json.loads((HERE / "model_inputs.baseline.json").read_text(encoding="utf-8")))
    return [val for n, val, _o in tok if n.startswith("[extra]")]


def main():
    errs = baseline_check()
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    model = build_model()
    text = json.dumps(model, ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        ok = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print("model.json up to date" if ok else "model.json is stale: run make_model.py")
        sys.exit(0 if ok else 1)
    OUT.write_text(text, encoding="utf-8")
    changed = sum(t["copy"] != t["value"] for t in model["tokens"] + model["extra"])
    print(f"model.json: {len(model['tokens'])} tokens + {len(model['extra'])} extra, "
          f"{changed} differ from copy; D={model['calc']['dividend']}")


if __name__ == "__main__":
    main()
