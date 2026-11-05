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
Automatic authenticated DSN collection and coordinated pending-data expiry remain
separate incomplete MAIL-06 subunits. Newsletter activation is still gated.
