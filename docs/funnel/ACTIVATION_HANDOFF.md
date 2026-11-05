# Artemis execution handoff — 2026-11-05

Canonical definitions and status: [unified registry](https://github.com/zaomir/grainee-v2/blob/main/docs/projects/artemis/tenerife/ARTEMIS_FUNNEL_ATOMIC_PLAN_2026-11-04.tasks.json). Keep all 92 atoms and 27 PR38 tasks. Start with the [existing checkpoint](../../.agent-execution/state/artemis-funnel-20261104.checkpoint.json): reconcile a pending effect before retrying.

## Confirmed runtime, not preparation

The existing GitHub/VPS2402 server bridge is available; credentials stay on the host. Requests/results live in grainee-v2 `docs/agent-api/{requests,results}/`. Use the existing `artemis_release` and read-only `simon_agent_access/artemis_inventory` providers, not SSH guesses or another worker. Twenty watchdog `--check --json` precedes CRM inspection. Canonical sync checkout is `/opt/grainee-main`; do not reset the divergent `/var/www/grainee-v2`.

- CAP-01 additive source migration and CRM-01 guarded metadata apply are complete. **Do not repeat them.**
- Legacy capture, the original relay/timer and existing Twenty writer are active. Historical source coverage is complete for the current snapshot. At 12:55 UTC all **5 source rows / 5 captured events / 5 independent Person+Opportunity GET checks** passed: 2 real Crete enquiries, 3 marked tests, 0 unexplained. No newsletter consent was inferred. [Metrics receipt](evidence/METRICS-01-runtime-20261105.json).
- Protected explicit Facebook intake and trusted-host CLI are live/probed, using the same outbox. They require an actual explicit request and source context; operator attestation is not Meta API verification. No fabricated real Facebook record was submitted.
- Public news index/article and privacy pages return 200 in all five locales (15 local/public checks). [Five original desktop screenshots](evidence/NEWS-05-desktop-20261105.json) are persisted. Mobile, no-JS new form and Facebook in-app acceptance remain incomplete.
- Successful actual token-log protection: query-free NGINX format, token-route logs excluded, old workers fully replaced, new nonsecret marker absent from access/error/app journal. [Successful receipt](evidence/MAIL-09-token-log-runtime-20261105.json). The old first-attempt marker remains historical evidence of the auto-rolled-back failure, not a second failure.
- Latest confirmed application before the queued diary discovery release: `fe000ec896c9e7ba3cc157d71a6d4d108775ffbf`, 576 total tests, 0 failures, 9 skipped; no migration replay or flag change. Native errors retain escaped values and submission ID; language attribution uses allowlisted links without browser storage; legacy calculator inputs and public math are preserved.

Current release request: `artemis-diary-discovery-release-20261105-02`, source `e47cd4cd2e8ac86ecbab77538ff441cb80d19fc6`, [PR52](https://github.com/zaomir/artemis/pull/52). The first attempt stopped on three exact-list navigation tests before production switched. Their actual candidate log and local reproduction matched; PR53 updates strict expectations with the required diary link, with 72 relevant tests passing and no exclusions. The second complete guarded release is pending. It adds diary links to existing desktop/mobile menus and footer on 100 generated pages. Reconcile its result before another deployment; then capture ordinary-browser navigation proof.

## Mail and retention limits

`ARTEMIS_FUNNEL_ENABLED`, newsletter sending and retention remain off. The current database has 0 subscriptions and 0 newsletter mail jobs. DOI, POST confirmation, unsubscribe, atomic dispatch boundary, positive-only uncertain-send reconciliation, protected correlated operator feedback and coordinated expiry code are deployed but the newsletter transport is not yet connected to the timer. Never interpret code availability as activation.

Use the existing Gmail DWD service factory only. From/alias, SPF/DMARC, public DKIM key and HTTPS certificate validation are observed. Reply-To is unset; responsible reply role and supported reply languages are unassigned; authentication of a delivered test message is unverified. Do not infer a staff assignment from a Gmail account name or DNS key. No subscription purchase is needed for the observed transport.

The expiry code owns site SQLite payloads and owned Twenty fields only. It preserves independent enquiries, fresh requests and complaint suppression, requires original and final CRM readback, and retains a private pseudonymous replay guard. **It does not erase Gmail Sent/Inbox copies or rotated backups.** Observed backup policy is 7 daily / 4 weekly / 14 offhost copies; restore expiry replay is absent. Resolve provider-copy scope, restore behavior and truthful privacy copy before activation. [Feedback/expiry mechanics](MAIL_FEEDBACK.md). Automated authenticated DSN intake also remains incomplete.

Next independent P0 correction: process the CRM queue before legacy email notifications in the same relay, so a hung notification cannot starve CRM. Wire future newsletter processing only behind the disabled flag and actual sender/reply gates; no second daemon or source store.

## External blockers

Aside [packet](aside/ASIDE_TASKS_2026-11-04.json) contains 15 tasks, five localized texts, actual image/hash and acceptance checks. Profile 833304152 is registered; latest read-only connection check still reports no handoff/CDP. No actual Aside assignment channel is exposed in the available tools or Simon gateway. Do not claim the prepared file was dispatched, create duplicate Pages/groups, guess URLs, or run a code subagent under Aside's name.

Financial primitives/baseline and 11 internal tests exist; they are not the public calculator. Keep all 27 PR38 task mappings and unknown mandatory costs, technical/other bundle inclusion, issuer/instrument, day-count and buyer-fund release rules. No personal investor taxes. Continue independent preparation without publishing proposed terms as approved.
