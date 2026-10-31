"""Lead notifications to the Telegram group «Artemis».

Config only from environment (EnvironmentFile /etc/artemis/artemis.env):
  ARTEMIS_TG_BOT_TOKEN  bot token
  ARTEMIS_TG_CHAT_ID    target chat id (group «Artemis")
If either is missing the lead is still stored in the DB by the caller and a
warning is logged — nothing is sent anywhere else.
Only name, contact, language and page are sent (no message body, no amounts).
"""
from __future__ import annotations

import logging
import os
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("artemis.notify")


def _clean(v, n=200):
    return " ".join(str(v or "").split())[:n]


def format_lead(kind: str, name: str, contact: str, lang: str, page: str) -> str:
    return (
        f"Artemis — {_clean(kind, 40)}\n"
        f"Имя: {_clean(name)}\n"
        f"Контакт: {_clean(contact)}\n"
        f"Язык: {_clean(lang, 10)}\n"
        f"Страница: {_clean(page, 200)}"
    )


def _send(token: str, chat_id: str, text: str) -> None:
    try:
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=8
        ).read()
    except Exception as e:  # never log the token / URL
        log.warning("artemis lead notification failed: %s", type(e).__name__)


def notify_lead(kind: str, name: str, contact: str, lang: str, page: str,
                background: bool = True) -> bool:
    """Returns True if a send was attempted."""
    token = os.environ.get("ARTEMIS_TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("ARTEMIS_TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning(
            "artemis lead (%s) stored in DB only: ARTEMIS_TG_%s not configured",
            kind, "CHAT_ID" if token else "BOT_TOKEN",
        )
        return False
    text = format_lead(kind, name, contact, lang, page)
    if background:
        threading.Thread(target=_send, args=(token, chat_id, text), daemon=True).start()
    else:
        _send(token, chat_id, text)
    return True
