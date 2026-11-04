#!/usr/bin/env python3
"""BASE-02/03: read-only, PII-free host inventory. Never sends or mutates CRM/DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess


def inspect(db_path):
    result = {"schema": "artemis-runtime-inventory/1", "mode": "read_only", "crm_delivery": "UNVERIFIED"}
    result["runtime_checkout"] = Path('/var/www/artemis/.git').is_dir()
    result["key_available"] = bool(os.environ.get('TWENTY_API_KEY')) or any(
        p.is_file() and p.stat().st_size for p in [Path(os.environ.get('TWENTY_KEY_FILE', '/nonexistent')), Path('/root/.twenty_api_key'), Path.home()/'.twenty_api_key'])
    result["sender"] = {"provider_source": "existing lead relay uses Gmail domain-wide delegation",
                        "runtime_verified": False, "dns_verified": False, "reply_owner_verified": False}
    result["files_present"] = {p: Path(p).is_file() for p in [
        '/etc/artemis/artemis.env', '/etc/artemis/lead-relay.env',
        '/usr/local/sbin/artemis-lead-relay.py', '/var/lib/artemis-lead-relay/state.db']}
    db = Path(db_path)
    result["source_db_present"] = db.is_file()
    if db.is_file():
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result["tables"] = {}
            for table in ['leads', 'tenerife_waitlist', 'artemis_crm_outbox', 'artemis_subscriptions', 'artemis_mail_outbox']:
                if table in tables:
                    fields = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
                    row = {"columns": fields, "count": conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}
                    if 'created_at' in fields:
                        row['date_range'] = conn.execute(f'SELECT MIN(created_at), MAX(created_at) FROM {table}').fetchone()
                    result['tables'][table] = row
    result['blockers'] = []
    if not result['runtime_checkout']: result['blockers'].append('not_on_authorized_VPS_checkout')
    if not result['source_db_present']: result['blockers'].append('source_SQLite_not_mounted')
    if not result['key_available']: result['blockers'].append('Twenty_key_unavailable_in_canonical_host_sources')
    result['status'] = 'blocked' if result['blockers'] else 'inventory_only_readback_still_required'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default='/var/www/artemis/leads.db')
    a = p.parse_args()
    print(json.dumps(inspect(a.db), indent=2))
