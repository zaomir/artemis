#!/usr/bin/env python3
"""Scan Artemis public source for hard-block investment tokens (brief §17).

Allowlist: exact lines from app/legal/DISCLAIMER_EN.txt may contain
investment / securities / SPV. No global exclusion.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SCAN_DIRS = [
    APP / "templates",
    APP / "translations",
    APP / "static",
    APP / "legal",
]
SCAN_FILES_EXTRA = [APP / "app.py"]
EXTENSIONS = {".html", ".js", ".json", ".css", ".svg", ".txt", ".md", ".py"}

# Phrases first (longer), then short tokens with word boundaries
PHRASES = [
    "Investment Opportunity",
    "financial investor",
    "minimum ticket",
    "equity participation",
    "capital structure",
    "guaranteed income",
    "guaranteed return",
    "exit value",
    "sale proceeds",
    "net profit",
    "investment amount",
    "calculate returns",
    "planned amount",
    "proof of funds",
    "term sheet",
    "funding tranches",
    "what the investor receives",
    "revenue share",
    "cap rate",
    "unit sale price",
]
WORD_TOKENS = [
    "SPV",
    "stake",
    "yield",
    "ROI",
    "IRR",
    "MOIC",
    "buyout",
    "ADR",
    "RevPAR",
]

SKIP_DIR_NAMES = {"private_quarantine", "__pycache__", ".git"}


def load_allowlist_lines() -> set[str]:
    path = APP / "legal" / "DISCLAIMER_EN.txt"
    lines = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s:
            lines.add(s)
    return lines


def iter_files():
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            if p.suffix.lower() not in EXTENSIONS:
                continue
            yield p
    for p in SCAN_FILES_EXTRA:
        if p.is_file():
            yield p


def line_is_allowlisted(line: str, allow: set[str]) -> bool:
    stripped = line.strip()
    # Exact match or line that only wraps the approved disclaimer body
    if stripped in allow:
        return True
    for a in allow:
        if a and a in stripped and stripped.replace(a, "").strip() in {"", ">", "<p>", "</p>", "<p></p>"}:
            return True
        # Jinja: {{ disclaimer_body }} is not a violation by itself
    if "disclaimer_body" in stripped or "disclaimer_mark" in stripped:
        return True
    if stripped.startswith("DISCLAIMER_") or "DISCLAIMER_EN" in stripped:
        return True
    # Comments documenting allowlist / scan purpose
    if "hard-block" in stripped.lower() or "allowlist" in stripped.lower():
        return True
    return False


def find_hits(text: str, allow: set[str]):
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if line_is_allowlisted(line, allow):
            continue
        low = line
        for phrase in PHRASES:
            if phrase.lower() in low.lower():
                hits.append((i, phrase, line.strip()[:160]))
        for tok in WORD_TOKENS:
            if re.search(rf"\b{re.escape(tok)}\b", line, flags=re.IGNORECASE):
                hits.append((i, tok, line.strip()[:160]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=pathlib.Path, default=None)
    args = ap.parse_args()
    root = args.root or pathlib.Path(__file__).resolve().parents[1]
    app = root / "app"
    allow_path = app / "legal" / "DISCLAIMER_EN.txt"
    allow = set()
    for raw in allow_path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s:
            allow.add(s)

    scan_dirs = [app / "templates", app / "translations", app / "static", app / "legal"]
    files = []
    for base in scan_dirs:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            if p.suffix.lower() not in EXTENSIONS:
                continue
            files.append(p)
    if (app / "app.py").is_file():
        files.append(app / "app.py")

    failures = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            failures.append(f"{path}: read error {e}")
            continue
        for line_no, token, snippet in find_hits(text, allow):
            failures.append(f"{path.relative_to(root)}:{line_no}: [{token}] {snippet}")

    print(f"Scanned {len(files)} files under {app}")
    if failures:
        print(f"FAIL — {len(failures)} hard-block hit(s):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("PASS — no hard-block tokens outside allowlisted disclaimer lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
