# Artemis Atlantic Heritage Watercolour — execution checkpoint

Task date: 2026-11-05. Scope: zaomir/artemis, feat/atlantic-watercolour-site-20261104, draft PR #39. No merge to main or production deployment.

## Current owner authority
- Owner approved the five P0 desktop illustrations for their named pages and instructed continuation. Receipt with exact source hashes: evidence/OWNER_P0_APPROVAL_2026-11-05.json.
- Owner then explicitly rejected the concurrent EN-only rework as erroneous and instructed continuation of the original five-language plan. Receipt: evidence/OWNER_REJECTS_EN_ONLY_2026-11-05.json. This supersedes the temporary EN-only adaptation recorded in EN_MAIN_INTEGRATION_2026-11-05.json.
- Approval covers named artwork, adaptation and preview placement. It does not approve final architecture, factual specifications, investor claims or production release. Do not ask again for the five already approved P0 images.
- Canon: docs/funnel/CONTENT_CANON.md. Single task registry: ARTEMIS_SITE_VISUAL_PLAN_2026-11-04.tasks.json. Do not edit source financial math or calculate investor personal taxes.

## Five-language restoration
- Current main observed at 6d1697795e9ccd383383c91545302ca6971b2dc5. It includes EN-only PR #57.
- Main was integrated, then the EN-only merge was reverted inside PR #39 per the owner's correction. EN/ES/DE/FR/RU routes, copy, calculator presentation and source behavior are restored from the pre-EN baseline. Independent CRM/mail/retention/feedback changes remain.
- No new financial arithmetic was introduced. Model inputs/calculator arithmetic match the pre-EN baseline 3df77a4. The large main diff includes this intentional owner-directed restoration; do not mistake it for accidental locale/calculator regressions.
- Production was not changed. PR #39 must not be merged/deployed by inference.

## P0 completed in preview
- All five owner-approved artworks are assigned to the exact named slots: index/F01, norte/F21, producto/F05, inversores/F14, construccion/F15.
- Each has a new standalone 4:5 mobile composition, original PNG, SHA-256, two mobile WebP variants, five-language alt/caption metadata and a recorded reference. Old ART01 mobile crops remain preserved and are not selected.
- Builder binds desktop sources to the owner's approved hashes, requires approved preview status, verifies mobile hashes and blocks use through production overrides without release authority.
- Mobile sources are selected below 768 px. Concept frames use contain, and fixed navigation/title plates no longer obscure drawings. Image-specific captions remain visible.
- La Quinta locator uses sourced coordinates, desktop/mobile SVGs and attribution; no invented parcel. Equipo/F22 remains intentionally hidden. Suppressed legacy renders cannot migrate to other preview pages.
- P0 review/comparison: P0_REVIEW_2026-11-05.md.

## P1 progress
- Fourteen distinct new candidates cover every remaining P1 image slot in the original registry. Originals, exact prompts, reference paths, dimensions, SHA-256 and EN/ES/DE/FR/RU alt/captions are saved under candidates/p1 and candidates/p1-sources.
- All nineteen desktop concepts (P0 + P1) pass the dHash uniqueness check: minimum distance 14, duplicate threshold 10. Five P0 mobile originals have minimum distance 16.
- P1 status is REVIEW. They have no frame assignments and are not registered as approved assets. Owner review package: P1_REVIEW_2026-11-05.md. After approval: necessary portrait adaptations, placement, post-placement QA, then remaining P1/P2 tasks.
- Added a preview-only nine-stage construction layout sourced directly from each language's existing nine table rows. It adds no dates, completion state, money or engineering claims. Twenty language/width checks passed. Only the five construction pages changed, so previous placement QA remains applicable to the other 65 primary pages.
- Financial flow/market charts remain under the separate verified financial-model authority.

## Provenance findings
- ASSET_PROVENANCE_REGISTER_2026-11-05.json inventories 21 legacy project visuals, 8 profile images, 7 portfolio case images and the news artwork, with actual hashes and dimensions.
- Four existing identity-preserving image_gen edits are explicitly identified from PROFILE_IMAGE_PROMPTS_2026-11-03.json. Original acquisition, public rights, portfolio roles/status and documentary authenticity are not certified by this inventory.
- Removed the unverified claim that simon-site is the Canary Stone project site, in all five alt-text sets. Portrait/case image bytes remain unchanged. Review documentary claims before release; do not describe all existing profile images as authentic project-site evidence.

## Executed validation
- Five preview builds and five normal builds passed after the final source changes.
- Approved P0 placement: 14 primary pages × 5 languages × 4 widths (320/768/1024/1440) = 280 renders, including 100 concept-art placements. No page overflow, broken image, H1/primary-CTA count issue, wrong mobile selection or drawing/header overlap in the final run.
- One earlier local image transport failure was reproduced as a preview-server connection/backlog issue; the image file was present and intact. Server backlog was corrected and the complete final run passed.
- The new nine-stage layout passed another 20 responsive checks and uses exactly nine source labels/results in every language, without current/completed state classes.
- Final full suite: 607 tests discovered; 589 successful, 18 environment-dependent skips; zero failures/errors. Log: evidence/FINAL_607_TESTS_2026-11-05.txt. Six durable recovery tests also passed.
- Evidence: P0_APPROVED_PLACEMENT_2026-11-05.json, FUTURE_STAGES_2026-11-05.json, P1_CANDIDATES_2026-11-05.json, and approved-screenshots. No real lead submission or live CRM/mail mutation was performed in these checks.
- Earlier Actions jobs failed before steps. No fresh Actions success is claimed; local builds/tests are the evidence. Earlier production read-only HTTP checks returned 200 but did not expose a deployed SHA.

## Next concrete action
Review the fourteen named P1 candidates in P1_REVIEW_2026-11-05.md. Named image approval precedes their preview assignment under the existing canon. Keep the five-language owner correction and the five P0 approvals in force. P1 hero portrait adaptations, image placement, final P1/P2 diagrams/OG work, documentary provenance decisions and a separate production release remain open.

No background automation, social posting, external messaging, merge to main or production release was activated.
