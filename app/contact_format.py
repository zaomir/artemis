"""Recognise the three reply channels accepted by the Tenerife form; no external lookup."""
import re
from urllib.parse import urlsplit


def valid_contact(value: str) -> bool:
    value = value.strip()
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return True
    handle = value[1:] if value.startswith("@") else ""
    candidate = value if "://" in value else "https://" + value
    try:
        url = urlsplit(candidate)
        if url.scheme in ("https", "http") and url.netloc.lower() in ("t.me", "telegram.me", "www.t.me"):
            handle = url.path.strip("/")
    except ValueError:
        return False
    if handle and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", handle):
        return True
    if re.fullmatch(r"\+?[0-9\s().-]+", value):
        digits = re.sub(r"\D", "", value)
        return 7 <= len(digits) <= 15
    return False
