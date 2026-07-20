#!/usr/bin/env bash
# Wrapper: Artemis public-source compliance gate (brief §17)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/compliance_scan.py" --root "$ROOT"
