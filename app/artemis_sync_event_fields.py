"""Twenty consumer field allowlist (artemis_sync.py).

Vendored from zaomir/grainee-v2 ``scripts/outreach/artemis_sync.py``.
File blob sha256 at grainee commit ``8d46aa6c88`` (2026-11-04):
``23d6b47fc97136b21c72fdad2a27839b899ae010db96e9345d2f2e2c55cace37``
(Not claimed to match current ``main``; re-vendor if that script changes.)

The sync service rejects any other top-level event keys with
``ValueError: unknown_artemis_fields``.
"""
from __future__ import annotations

# Top-level keys accepted by scripts/outreach/artemis_sync.py before Twenty sync.
ARTEMIS_SYNC_EVENT_FIELDS = frozenset(
    {
        "source_event_id",
        "submission_id",
        "project",
        "intent",
        "name",
        "contact_type",
        "contact",
        "language",
        "created_at",
        "capture_origin",
        "source_id",
        "landing",
        "consent_version",
        "newsletter_opt_in",
        "newsletter_email",
        "newsletter_requested_at",
        "newsletter_consent_version",
        "waitlist_state",
        "membership_state",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "form_id",
        "model_version",
        "scenario_id",
        "event_kind",
        "subscription",
        "mail_feedback",
        "facebook_context",
        "legacy_fields",
        "test_record",
        "test_reason",
    }
)


def assert_artemis_sync_event(event: dict) -> None:
    """Mirror artemis_sync.py: fail on keys outside the Twenty allowlist."""
    extra = set(event.keys()) - ARTEMIS_SYNC_EVENT_FIELDS
    if extra:
        raise ValueError("unknown_artemis_fields:" + ",".join(sorted(extra)))
