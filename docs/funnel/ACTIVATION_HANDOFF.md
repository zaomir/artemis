# Resume on the authorized VPS2402 executor

Canonical task definitions/status: grainee-v2/docs/projects/artemis/tenerife/ARTEMIS_FUNNEL_ATOMIC_PLAN_2026-11-04.tasks.json. Do not reconstruct this work or start another CRM service. Read the existing checkpoint and reconcile its pending intent first.

## BASE-02 / BASE-03

Run `scripts/funnel_runtime_inventory.py` on the authorized host, opening existing SQLite in read-only mode. Follow Twenty intent router and OPS REGULATION; run watchdog --check/--status before touching CRM. Inventory actual services, timers, any existing Artemis source reader, schema/unique constraints, source row counts and existing source-to-CRM receipts. Never infer delivery from health. Check existing Gmail DWD sender, reply owner, SPF/DKIM/DMARC/TLS and bounce/complaint capabilities without sending mail. No credentials in reports.

## Integration preparation already available

- Artemis `app/funnel_store.py`: additive migration, original rows and calc columns preserved. Caller controls BEGIN IMMEDIATE. Populated rollback refuses data loss.
- Existing API uses typed capture only with ARTEMIS_FUNNEL_ENABLED=1 and a configured ARTEMIS_NEWSLETTER_SECRET (at least 32 characters, host only). Do not turn it on before dependencies/controlled QA. Legacy UI/API remain default. Newsletter-only has no legacy waitlist row.
- Existing relay extension `app/funnel_delivery.py` is opt-in via ARTEMIS_CRM_DELIVERY_ENABLED=1; it posts only to the existing local twenty-sync /sync-artemis and uses its existing secret. No new systemd unit. Update the installed relay through the existing deployment procedure; first reconcile any reader discovered in BASE-02.
- grainee-v2 `scripts/outreach/artemis_sync.py` is loaded by the existing twenty_sync.py only with ARTEMIS_SYNC_ENABLED=1. Metadata stays deploy-time only, via workspace_manifest.json and existing sync-metadata.mjs after verified backup and live preflight. Manifest additions are unapplied. Check unique identities/source keys and live ID/filter behavior before activation.
- `app/funnel_mail.py`: five neutral templates and existing-service Gmail adapter, not automatically connected or scheduled. Sender/Reply-To are caller supplied after verification. Accepted is not delivered. Uncertain requests need positive Sent-folder readback; a negative search does not authorize resend.
- Confirmation GET is side-effect free; POST activates. Unsubscribe POST suppresses queued welcome/news and leaves the independent enquiry. Token endpoints must have query-free access logging before production; never log token URLs.

## Remaining release-critical work

CAP-06 real controller/privacy, actual mail worker wiring, authenticated provider bounce/complaint callbacks, privacy retention coordinated with CRM, historical Tenerife and Crete inventory/backfill, explicit Facebook inbound ingestion and per-form Meta recovery are not completed. Do not call new-event queue totals a full reconciliation of all historical sources. No historical email opt-in is inferred, and no blast of confirmation emails is authorized by backfill.

Reconcile each real source event with independent Person/Opportunity GET readback, keeping excluded tests separately with reasons. Required balance: verified=accepted and pending/retrying/uncertain=0 at the snapshot. Newsletter-only requires Person and subscription state, no Opportunity.

QA-02 uses controlled service contacts only, labelled test receipts. QA-03 requires real migration receipt, release SHA, production smoke and rollback. NEWS-05 visual observations exist in the execution session at desktop and a 320px iframe; durable exported screenshots remain to be collected by the executor. Financial release is independent and still blocked by unresolved budget inclusion mappings, issuer/instrument, day-count and buyer-fund rules; internal finance_v2 primitives are not the public calculator.

Aside pack: docs/funnel/aside/ASIDE_TASKS_2026-11-04.json, actual image and hash in asset_manifest.json. Inventory first; new links wait for QA-03. No Facebook object or post has been created in this implementation session.
