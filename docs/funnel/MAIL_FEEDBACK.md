# Correlated mail feedback

Gmail messages API does not supply a direct complaint webhook. An authorized
operator reviews the original bounce/complaint in the existing mailbox, checks
the recipient and the Artemis message key against the actual dispatched message,
and retains the private evidence there. An arbitrary inbound From header is not
authenticated provider proof.

On the trusted host, pass one private JSON object to
`venv/bin/python scripts/record_mail_feedback.py --apply` on stdin. Fields:
`mail_id` (Artemis outbox UUID), `reason` (`hard_bounce` or `complaint`),
`evidence_ref` (`gmail:<message-id>` or `operator:<private-reference>`) and
`operator_task_id`. No recipient, credentials or evidence body goes into GitHub,
task URLs or public logs. The host derives a separate purpose-scoped credential.

The loopback-only endpoint refuses forwarded requests. It checks message
correlation, records a hash of the evidence reference, suppresses future mail and
queues the existing subscription projection in one transaction. Duplicate
evidence cannot be rebound to another message. Complaint wins over a later
bounce; imports cannot clear deliverability. An independent enquiry is retained.

`--probe` sends invalid empty JSON and must receive authenticated HTTP 400. It
does not create a test complaint or change any real subscriber.

This is operator-attested feedback, not an automated Gmail delivery receipt.
Automatic authenticated DSN collection remains an incomplete MAIL-06 subunit.
Coordinated expiry is implemented in `funnel_retention.py` and the existing
writer, behind `ARTEMIS_RETENTION_ENABLED=1` (off until release/privacy QA).
It requires the original independently verified Person receipt, expires the
pending generation, pauses its old source jobs, and requests contact anonymization.
Only a matching CRM readback receipt permits final local payload/address cleanup.
New requests, independent enquiries and complaints arriving during the roundtrip
are protected. A minimal private pseudonymous identity/expiry record prevents
stale replays; it is not described as anonymous or as a new sales lead.
Rotated backups are not claimed erased. Newsletter activation is still gated.

The implemented cleanup scope is site SQLite and the Artemis-owned Twenty
fields. It does not delete confirmation-message copies in Gmail Sent/Inbox.
Existing mail permissions and the handling of those copies must be established
before activation; moving mail to Trash must not be reported as permanent
erasure. The observed backup configuration keeps 7 daily, 4 weekly and 14
offhost copies; the restore scripts currently have no Artemis expiry replay
hook. Neither the backup copies nor restored data are covered by an erasure
claim. These are remaining MAIL-06/CAP-06 requirements, not completed cleanup.
