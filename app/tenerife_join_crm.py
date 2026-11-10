"""Facebook join CRM events — join-only builder; never mutates funnel_store.normalize."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import funnel_store as store

import artemis_sync_event_fields

JOIN_LANDING = "/tenerife/join/"


def build_join_event(
    submission_id: str,
    name: str,
    contact: str,
    intent: str,
    language: str,
    src: str,
    ref: str,
    now,
) -> dict:
    """Server-built event JSON for artemis_events / twenty-sync (no client-internal keys)."""
    event = {
        "source_event_id": "artemis:submission:" + submission_id,
        "submission_id": submission_id,
        "project": "artemis_tenerife",
        "intent": intent,
        "name": name,
        "contact_type": "facebook",
        "contact": contact,
        "language": language,
        "created_at": now.isoformat(),
        "capture_origin": "website",
        "source_id": "FB",
        "landing": JOIN_LANDING,
        "consent_version": store.VERSION,
        "newsletter_opt_in": False,
        "newsletter_email": None,
        "newsletter_requested_at": None,
        "newsletter_consent_version": None,
        "waitlist_state": "registered",
        "membership_state": "unknown",
        "form_id": "fb-join",
    }
    if src:
        event["utm_source"] = src
    if ref:
        event["utm_campaign"] = ref
    artemis_sync_event_fields.assert_artemis_sync_event(event)
    return event


def event_digest(event: dict) -> str:
    stable = {k: v for k, v in event.items() if k != "created_at"}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def capture_join(conn, event: dict, legacy, client_hash) -> tuple[str, bool]:
    """Same idempotency rules as funnel_store.capture."""
    if not conn.in_transaction:
        raise RuntimeError("capture requires caller transaction")
    digest = event_digest(event)
    row = conn.execute(
        "SELECT payload_hash FROM artemis_events WHERE submission_id=?", (event["submission_id"],)
    ).fetchone()
    if row:
        if row[0] != digest:
            raise ValueError("submission_id_conflict")
        return event["source_event_id"], False
    conn.execute(
        """INSERT INTO artemis_events
        (source_event_id,submission_id,payload_hash,payload,created_at,legacy_table,legacy_id,legacy_created_at,client_hash)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            event["source_event_id"],
            event["submission_id"],
            digest,
            json.dumps(event, sort_keys=True),
            event["created_at"],
            legacy[0],
            legacy[1],
            legacy[2],
            client_hash,
        ),
    )
    conn.execute("INSERT INTO artemis_crm_outbox(source_event_id) VALUES (?)", (event["source_event_id"],))
    return event["source_event_id"], True
