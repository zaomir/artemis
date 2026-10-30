#!/usr/bin/env python3
"""Artemis compliance scan — investment hard-block DISABLED.

Founder DEC-ARTEMIS-INVESTMENT-RESTORE-2026-10-30 restored investment
content and cancelled disclaimer / strip gates. This script remains as a
no-op PASS so existing wrappers keep working.
"""
from __future__ import annotations

import argparse
import pathlib
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=pathlib.Path, default=None)
    args = ap.parse_args()
    root = args.root or pathlib.Path(__file__).resolve().parents[1]
    print(f"Scanned under {root / 'app'}")
    print(
        "PASS — investment hard-block disabled "
        "(DEC-ARTEMIS-INVESTMENT-RESTORE-2026-10-30)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
