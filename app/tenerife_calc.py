"""Server recomputation of the upfront cash-exit calculator.
The legacy request/DB names calc_m2 and calc_price_eur_m2 are retained for
migration compatibility; in this model they represent a share quantity and a
share price, never a right to a specific residence. No submitted money is trusted.
"""
from __future__ import annotations

import json
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "tenerife_site" / "data" / "model.json"   # EN r2: not public
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
           ("calc_amount", "INTEGER"), ("calc_month_eur", "INTEGER"), ("calc_model_version", "TEXT"),
           ("calc_exit_amount", "INTEGER"), ("calc_income", "INTEGER"),
           ("calc_exit_months", "INTEGER"), ("calc_target_pct", "REAL"))

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
    """Recompute the complete one-payment/one-exit scenario from current inputs."""
    price = Decimal(str(next(s["price_eur_m2"] for s in model["steps"] if s["id"] == step)))
    ctype = next((t["id"] for t in model["types"] if t["min"] <= m2 <= t["max"]), None)
    raw_amount = Decimal(m2) * price
    inv = model["investment"]
    factor = (Decimal(1) + Decimal(str(inv["target_annual"]))) ** (Decimal(inv["exit_months"]) / 12)
    return {"calc_type": ctype, "calc_shares": m2, "calc_price_eur_m2": float(price),
            "calc_amount": half_up(raw_amount), "calc_month_eur": None,
            "calc_exit_amount": half_up(raw_amount * factor), "calc_income": half_up(raw_amount * (factor - 1)),
            "calc_exit_months": inv["exit_months"], "calc_target_pct": inv["target_annual"] * 100}


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
