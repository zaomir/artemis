"""Tenerife waitlist: calculator fields sent with a lead from /tenerife/calculadora/.

The form (DESIGN.md C13, variant «calculadora») sends exactly three hidden fields besides `page`:
calc_m2, calc_step, calc_pay. No amount is sent and no model version: the server recomputes the
calculation from calc_m2 with the CURRENT model.json and records that model's version with the lead.

check_calc(data, model) -> (calc | None, log_reasons)
  * no calc_* field in the request -> (None, [])  a normal lead, no calc block
  * a field missing / wrong type / out of sane bounds -> calc_status "invalid": only the status, the
    field names with the problem and the model version are kept (no submitted garbage); logged
  * fields well-formed, but not what the current model gives (area outside the model range, step no
    longer an entry step, payment option not offered) -> calc_status "mismatch" («расчёт не совпадает»):
    the submitted values AND the recomputed ones are stored and shown; logged
  * otherwise -> calc_status "ok"
The lead itself is never rejected because of the calculator.

Recomputation (current model.json): area clamped to area_m2 min…max; step = the submitted one if it is
still an entry step, else the model's current step; payment = the submitted one if offered, else "now";
type = the type whose range holds the area; shares = area / share_m2; amount = area × price of the step;
monthly = amount / installments.months — money rounded ROUND_HALF_UP to whole euros (model.json rounding),
the same rule as calc.js, so the page and the server agree to the euro.
Rounding tolerance: calc_m2 may arrive as "72", "72.0" or "72,00"; a value within ±0.01 m² of a whole
number counts as that number (float/locale formatting), anything else is invalid. Money is not sent by
the form, so there is no money tolerance to apply: it is always recomputed here.
"""
from __future__ import annotations

import json
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "tenerife_site" / "data" / "model.json"   # r4.1: not public (was static/)
FIELDS = ("calc_m2", "calc_step", "calc_pay")
M2_TOLERANCE = Decimal("0.01")
M2_SANE = (1, 10000)            # beyond this the value is garbage, not a stale page
NUM_RE = re.compile(r"^\d{1,5}(?:[.,]\d{1,6})?$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# DB columns (tenerife_waitlist), in this order. calc_m2/calc_step/calc_pay = as submitted (normalised);
# *_server = recomputed with the current model.json; the derived figures are for the server values.
COLUMNS = (("calc_status", "TEXT"), ("calc_note", "TEXT"),
           ("calc_m2", "INTEGER"), ("calc_step", "TEXT"), ("calc_pay", "TEXT"),
           ("calc_m2_server", "INTEGER"), ("calc_step_server", "TEXT"), ("calc_pay_server", "TEXT"),
           ("calc_type", "TEXT"), ("calc_shares", "INTEGER"), ("calc_price_eur_m2", "INTEGER"),
           ("calc_amount", "INTEGER"), ("calc_month_eur", "INTEGER"), ("calc_model_version", "TEXT"))

_cache: dict = {}


def load_model(path: Path | str = MODEL_PATH) -> dict:
    """model.json, re-read when the file changes (deploy replaces it together with the pages)."""
    p = str(path)
    mtime = os.stat(p).st_mtime_ns
    hit = _cache.get(p)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(p, encoding="utf-8") as f:
        model = json.load(f)
    _cache[p] = (mtime, model)
    return model


def half_up(x) -> int:
    return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _m2(v):
    """Whole m² or None (type/format/tolerance/sanity)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        v = repr(v)
    if not isinstance(v, str) or not NUM_RE.fullmatch(v.strip()):
        return None
    d = Decimal(v.strip().replace(",", "."))
    n = half_up(d)
    if abs(d - n) > M2_TOLERANCE or not M2_SANE[0] <= n <= M2_SANE[1]:
        return None
    return n


def _id(v):
    return v.strip() if isinstance(v, str) and ID_RE.fullmatch(v.strip()) else None


def _short(v) -> str:
    """Safe value for the log line: repr (no raw newlines), max 24 chars (never the name/contact)."""
    return repr(str(v)[:24])


def pay_options(model: dict) -> tuple:
    months = (model.get("installments") or {}).get("months")
    return ("now", f"m{int(months)}") if months else ("now",)


def compute(m2: int, step: str, pay: str, model: dict) -> dict:
    """The calculation for valid model inputs (as calc.js does it)."""
    price = next(s["price_eur_m2"] for s in model["steps"] if s["id"] == step)
    ctype = next((t["id"] for t in model["types"] if t["min"] <= m2 <= t["max"]), None)
    amount = half_up(Decimal(m2) * price)
    month = None
    if pay != "now":
        month = half_up(Decimal(m2) * price / Decimal(model["installments"]["months"]))
    return {"calc_type": ctype, "calc_shares": m2 // int(model.get("share_m2", 1)),
            "calc_price_eur_m2": price, "calc_amount": amount, "calc_month_eur": month}


def check_calc(data: dict, model: dict) -> tuple[dict | None, list[str]]:
    present = {k: data.get(k) for k in FIELDS if data.get(k) not in (None, "")}
    if not present:
        return None, []
    version = str(model.get("version", ""))[:32]
    m2, step, pay = _m2(present.get("calc_m2")), _id(present.get("calc_step")), _id(present.get("calc_pay"))
    bad = []
    for k, v in (("calc_m2", m2), ("calc_step", step), ("calc_pay", pay)):
        if k not in present:
            bad.append(f"{k}: нет")
        elif v is None:
            bad.append(f"{k}: неверный формат")
    if bad:
        log = [f"{k}={_short(present[k])}" for k in FIELDS if k in present]
        return {"calc_status": "invalid", "calc_note": "; ".join(bad), "calc_model_version": version}, bad + log

    area = model["area_m2"]
    entry = [s["id"] for s in model["steps"] if s.get("entry")]
    current = next((s["id"] for s in model["steps"] if s.get("current") and s.get("entry")), entry[0])
    m2_s = min(max(m2, area["min"]), area["max"])
    step_s = step if step in entry else current
    pay_s = pay if pay in pay_options(model) else "now"
    diff = [f"{k}: {a} → {b}" for k, a, b in (("calc_m2", m2, m2_s), ("calc_step", step, step_s),
                                              ("calc_pay", pay, pay_s)) if a != b]
    calc = {"calc_status": "mismatch" if diff else "ok", "calc_note": "; ".join(diff) or None,
            "calc_m2": m2, "calc_step": step, "calc_pay": pay,
            "calc_m2_server": m2_s, "calc_step_server": step_s, "calc_pay_server": pay_s,
            "calc_model_version": version}
    calc.update(compute(m2_s, step_s, pay_s, model))
    return calc, [f"расчёт не совпадает: {calc['calc_note']}"] if diff else []


def migrate(conn) -> None:
    """Idempotent: add the calc columns to an existing tenerife_waitlist (old rows keep NULL)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(tenerife_waitlist)")}
    for col, typ in COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE tenerife_waitlist ADD COLUMN {col} {typ}")
