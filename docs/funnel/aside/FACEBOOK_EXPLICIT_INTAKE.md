# Aside: one explicit Facebook enquiry

Use this after AS-01 verifies the actual Valerie identity and permissions and
AS-12 observes a real request for a project reply. A reaction, membership request
or ordinary discussion is not an enquiry. Do not create a Twenty card manually.

The trusted host interface is:

`/var/www/artemis/venv/bin/python /var/www/artemis/scripts/capture_fb_enquiry.py`

- `--check`: validate private JSON from stdin; no side effects.
- `--apply`: capture the observed request in the existing Artemis event/outbox.
- `--probe`: verify the host credential using invalid input; no source is created.

Aside returns the observation through the authorized private task handoff to the
code executor. The code executor runs this host interface; browser-only Aside
does not need SSH, a credential or direct Twenty access.

The interface derives a purpose-scoped key from existing host configuration. It
never returns the admin key or CRM credential. Aside's task payload contains no
key. The host dispatcher invokes the interface; no arbitrary shell command or
credential is accepted from an enquiry.

The private JSON has exactly these fields:

| Field | Required observation |
|---|---|
| source_kind | `comment` or `messenger` |
| source_message_id | Real immutable comment/message ID, never an invented example |
| permalink | Observed Facebook comment or conversation permalink; comment ID must agree |
| explicit_request | Boolean `true` only for a request for project information/reply |
| quoted_request | Minimum necessary original request text, private |
| operator_task_id | Stable AS-13 task instance ID |
| observed_at | Actual timezone-aware observation time |
| name | Observed display name; no invented person |
| intent | investor, buyer, partner or other, from the actual request |
| contact_type | email or facebook |
| contact | Explicit supplied email or observed requester profile URL |
| language | en, es, de, fr, ru or unknown |

Keep the actual payload only in authorized private job storage/stdin. Never put
contact details, messages, headers or keys in git requests, screenshots published
as evidence, chat summaries or URLs. Do not submit documentation/example values.

Acceptance: successful source_event_id and queued receipt, safe retry with the
same ID, and the code executor's independent Person/Opportunity GET receipt.
Conflicting content under the same source ID returns 409 instead of overwriting
the original. Newsletter opt-in is always false and membership remains unknown.
Source provenance is operator-attested, not a claimed Meta API verification.

The endpoint is `/api/artemis/internal/facebook-enquiry`, loopback only, POST
JSON, max 16KB, with the purpose-scoped header supplied by the trusted host
interface. Missing configuration fails closed. No new timer or CRM writer exists.
