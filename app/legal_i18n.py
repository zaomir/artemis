"""Drop-in translations for the long legal texts (Crete /<lang>/privacy/ and /<lang>/terms/).

The short legal chrome (title, nav, recipients sentence) lives in app/translations/*.json.
The main policy body is English-only until a reviewed translation is dropped in as
    app/legal_translations/<page>.<lang>.md        e.g. app/legal_translations/privacy.ru.md
with section markers (see app/legal_translations/README.md):
    <!-- @title -->       optional, overrides t.<page>_title
    <!-- @body -->        required, paragraphs separated by a blank line
    <!-- @recipients -->  optional (privacy only), overrides t.privacy_recipients
Other HTML comments (<!-- … -->) are ignored. Text is rendered escaped (no HTML / Markdown markup).
English always comes from translations/en.json; an en file is ignored.
"""
from __future__ import annotations

import re
from pathlib import Path

LEGAL_DIR = Path(__file__).resolve().with_name("legal_translations")
SECTIONS = ("title", "body", "recipients")
_MARKER = re.compile(r"^\s*<!--\s*@(\w+)\s*-->\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def parse(text: str) -> dict:
    """Return {"title": str, "body": [paragraph, …], "recipients": str} for the sections present."""
    chunks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = _MARKER.match(line)
        if m:
            current = m.group(1).lower()
            chunks.setdefault(current, [])
            continue
        if current is not None:
            chunks[current].append(line)
    out: dict = {}
    for name in SECTIONS:
        if name not in chunks:
            continue
        raw = _COMMENT.sub("", "\n".join(chunks[name]))
        paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", raw)]
        paras = [p for p in paras if p]
        if not paras:
            continue
        out[name] = paras if name == "body" else " ".join(paras)
    return out


def load(page: str, lang: str, base: Path | None = None) -> dict | None:
    """Translated sections for page/lang, or None (→ the template shows the English body)."""
    if lang == "en" or not re.fullmatch(r"[a-z]{2}", lang or "") or not re.fullmatch(r"[a-z]+", page or ""):
        return None
    path = (base or LEGAL_DIR) / f"{page}.{lang}.md"
    try:
        data = parse(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    return data if data.get("body") else None
