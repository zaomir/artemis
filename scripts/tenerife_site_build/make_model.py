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
    """2026-11-02: единый источник цифр — copy_v3/make_numbers.py (пределы цен, дивиденд в % и в €,
    шесть платежей со скидкой 5 %). Здесь только калькулятор и порядок токенов; формулы не дублируются."""
    path = HERE / "copy_v3" / "make_numbers.py"
    src = path.read_text(encoding="utf-8")
    head = src[: src.index("files=sorted(")]
    ns = {"__file__": str(path), "__name__": "mn"}
    exec(compile(head, str(path), "exec"), ns)
    stages = [(n, lo, hi) for n, lo, hi in ns["STAGES"]]
    tok = [(n, val, opt) for n, val, opt in ns["TOK"]]
    calc = {"stages": [{"name": n, "min": lo, "max": hi} for n, lo, hi in stages],
            "dividend": ns["D"], "months": ns["MONTHS"], "discount_pct": int(ns["DISC"] * 100),
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
    st = [(n, lo, hi) for n, lo, hi in inputs["stages"]]
    design = {  # = web-designer/tenerife/design/model.json schema (DESIGN.md §C8, §C9)
        "version": "2026-11-02-v3",
        "status": "APPROVED — цены пределами, дивиденд в % и €, шесть платежей со скидкой 5 % (основатель 01.11 00:08, 31.10 23:54–23:59)",
        "currency": "EUR", "share_m2": 1,
        "steps": [dict({"id": inputs["stage_ids"][i], "name": n, "event": inputs["stage_events"][i],
                        "price_min_eur_m2": lo, "price_max_eur_m2": hi, "entry": i < len(st) - 1},
                       **({"current": True} if i == inputs["current_stage"] else {}))
                  for i, (n, lo, hi) in enumerate(st)],
        "installments": {"months": inputs["installment_months"],
                         "discount_pct": inputs.get("installment_discount_pct", 0)},
        "dividend_eur_per_share_year": calc["dividend"],
        "dividend_pct_range": inputs.get("dividend_pct_range", [2.5, 3.5]),
        "area_m2": {"min": inputs["calc_area_range"][0], "max": inputs["calc_area_range"][1],
                    "default": inputs["calc_default_area"]},
        "types": [{"id": inputs["unit_ids"][i], "name": u[0], "min": u[2], "max": u[3], "count": u[1]}
                  for i, u in enumerate(inputs["units"])],
        "house_on_handover_eur_m2": {"min": inputs["house_price_range"][0], "max": inputs["house_price_range"][1]},
        "rounding": {"rule": "ROUND_HALF_UP", "money": "integer_eur_half_up", "percent": "1_decimal_half_up",
                     "type_midpoint_m2": "integer_half_up"},
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
