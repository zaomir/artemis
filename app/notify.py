"""Lead notifications to the Telegram group «Artemis».

Config only from environment (EnvironmentFile /etc/artemis/artemis.env):
  ARTEMIS_TG_BOT_TOKEN  bot token
  ARTEMIS_TG_CHAT_ID    target chat id (group «Artemis")
If either is missing the lead is still stored in the DB by the caller and a
warning is logged — nothing is sent anywhere else.
Only name, contact, language and page are sent (never the message body), plus:
- for Crete enquiries, when the visitor filled it in, the planned investment amount («Сумма (план)», amount=);
- for a Tenerife lead from the calculator, the server's recomputation with model.json (area, type, shares,
  step, amount, payment, model version; «расчёт не совпадает» with both values when the page sent something
  the model does not give) (calc=, model=). Tenerife waitlist notifications carry no «Сумма (план)».
Plain text: no parse_mode, so nothing in a lead is interpreted as Markdown/HTML; every value is cleaned
to one line (no injected lines). (deploy/artemis-lead-relay.py — main/#26 — does not add calc lines.)
QA PS-09: a TEST lead (the name, or for Crete the message, contains «TEST») is still sent, so delivery stays
visible, but the first line starts with «[TEST] ». The message itself is only checked, never sent.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("artemis.notify")


def _clean(v, n=200):
    return " ".join(str(v or "").split())[:n]


def _eur(n) -> str:
    return f"{int(n):,}".replace(",", " ") + " €"


def _pay(p) -> str:
    """now -> сразу, m12 -> рассрочка 12 мес.; anything else as its (validated) id."""
    p = _clean(p, 16)
    if p == "now":
        return "сразу"
    if p[:1] == "m" and p[1:].isdigit():
        return f"рассрочка {int(p[1:])} мес."
    return p


def format_calc(c: dict, model: dict | None = None) -> list[str]:
    """Calculator lines of a lead (columns of tenerife_waitlist, see app/tenerife_calc.py).
    Step/type names from model.json when available, else the ids. Status mismatch -> «расчёт не совпадает»
    with the submitted and the recomputed values; invalid -> only what was wrong.
    If the relay ever gets calc_lines(), keep it identical (tests switch on by themselves)."""
    if not c or not c.get("calc_status"):
        return []
    model = model or {}
    types = {t.get("id"): t.get("name") for t in model.get("types", [])}
    steps = {s.get("id"): s.get("name") for s in model.get("steps", [])}
    ver = f"Модель: {_clean(c.get('calc_model_version') or '—', 32)}"
    if c["calc_status"] == "invalid":
        return [f"Калькулятор: данные неверны, расчёт не сохранён ({_clean(c.get('calc_note') or '—', 200)})", ver]
    lines = []
    if c["calc_status"] == "mismatch":
        lines += ["Калькулятор: расчёт не совпадает с текущей моделью",
                  f"Прислано: {int(c['calc_m2'])} акций, вариант {_clean(c['calc_step'], 32)}, "
                  f"оплата {_pay(c['calc_pay'])}",
                  f"Пересчёт: {int(c['calc_m2_server'])} акций, вариант {_clean(c['calc_step_server'], 32)}, "
                  f"оплата {_pay(c['calc_pay_server'])}"]
    head = f"Калькулятор: акций: {int(c['calc_shares'])}"
    if c.get("calc_type"):
        head += f", тип: {_clean(types.get(c['calc_type']) or c['calc_type'], 40)}"
    lines.append(head)
    step = _clean(steps.get(c["calc_step_server"]) or c["calc_step_server"], 40)
    lines.append(f"Вход: {step} — {_eur(c['calc_price_eur_m2'])}/акция")
    lines.append(f"Сумма: {_eur(c['calc_amount'])}")
    pay = f"Оплата: {_pay(c['calc_pay_server'])}"
    if c.get("calc_month_eur") is not None:
        pay += f" — {_eur(c['calc_month_eur'])}/мес."
    lines.append(pay)
    if c.get("calc_exit_amount") is not None:
        lines += [f"Выход через {int(c['calc_exit_months'])} мес.: {_eur(c['calc_exit_amount'])}",
                  f"Доход по модели: {_eur(c['calc_income'])}; целевая ставка: {c['calc_target_pct']:g}% годовых"]
    lines.append(ver)
    return lines


def is_test(*values) -> bool:
    """QA PS-09: «TEST» (upper case, as QA and the sysadmin write it) anywhere in the given values."""
    return any("TEST" in str(v or "") for v in values)


def format_lead(kind: str, name: str, contact: str, lang: str, page: str,
                amount: str = "", calc: dict | None = None, model: dict | None = None, test: bool = False,
                co_investment: bool | None = None) -> str:
    """amount: Crete «Сумма (план)» (main); calc/model: Tenerife calculator lines (keyword arguments);
    test: the caller saw «TEST» elsewhere (Crete message); a name with «TEST» is detected here."""
    lines = [
        f"{'[TEST] ' if test or is_test(name) else ''}Artemis — {_clean(kind, 40)}",
        f"Имя: {_clean(name)}",
        f"Контакт: {_clean(contact)}",
        f"Язык: {_clean(lang, 10)}",
        f"Страница: {_clean(page, 200)}",
    ]
    if _clean(amount, 64):
        lines.append(f"Сумма (план): {_clean(amount, 64)}")
    if co_investment is not None:
        lines.append(f"Co-investment interest: {'yes' if co_investment else 'no'}")
    return "\n".join(lines + format_calc(calc, model))


def _send(token: str, chat_id: str, text: str) -> None:
    try:
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        raw = urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=8
        ).read()
    except Exception as e:  # never log the token / URL
        log.warning("artemis lead notification failed: %s", type(e).__name__)
        return
    # QA P10: a successful send is logged with the Telegram message_id only — never the lead text.
    try:
        reply = json.loads(raw)
        message_id = int(reply["result"]["message_id"]) if reply.get("ok") is True else None
    except Exception:
        message_id = None
    if message_id is None:
        log.warning("artemis lead notification: unexpected Telegram reply")
    else:
        log.info("artemis lead notification sent: message_id=%d", message_id)


def notify_lead(kind: str, name: str, contact: str, lang: str, page: str,
                background: bool = True, amount: str = "", calc: dict | None = None,
                model: dict | None = None, test: bool = False, co_investment: bool | None = None) -> bool:
    """Returns True if a send was attempted."""
    token = os.environ.get("ARTEMIS_TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("ARTEMIS_TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning(
            "artemis lead (%s) stored in DB only: ARTEMIS_TG_%s not configured",
            kind, "CHAT_ID" if token else "BOT_TOKEN",
        )
        return False
    text = format_lead(kind, name, contact, lang, page, amount=amount, calc=calc, model=model, test=test,
                       co_investment=co_investment)
    if background:
        threading.Thread(target=_send, args=(token, chat_id, text), daemon=True).start()
    else:
        _send(token, chat_id, text)
    return True
