# Artemis Atlantic Heritage Watercolour — execution checkpoint

Date: 2026-11-05 (Atlantic/Canary). Scope: zaomir/artemis, branch feat/atlantic-watercolour-site-20261104, draft PR #39. No merge to main or production deployment.

## Authority and canonical registry
Owner authorized the visual direction and its implementation. Specific images, final architecture and production release have not been approved. Canon: docs/funnel/CONTENT_CANON.md. Single task registry: docs/visual/ARTEMIS_SITE_VISUAL_PLAN_2026-11-04.tasks.json. Financial model and CRM remain owned by the funnel work; no investor personal-tax calculation.

## Completed in this continuation
- Reconciled main twice, most recently 6ecefa4f0156edcdd4209aff35dd8f58490d11d3, preserving its CRM, legacy-ingress and privacy changes. No merge conflicts. No visual-branch diff to financial model/calculator, CRM logic or Crete sources.
- Recovered all four existing P0 generations through the connected ElevenLabs completed-session result. Original PNGs are stored under candidates/sources; 20 JPG/WebP derivatives and four per-image manifests are committed. Full prompts and node settings are stored in candidates/p0-generation-settings.json. No short-lived download URLs or login credentials are committed.
- Independently verified original SHA-256, all 20 derivative hashes/dimensions and five-candidate dHash uniqueness (minimum distance 20; duplicate threshold 10). All assets remain REVIEW with owner rights clearance and image approval pending.
- Prepared image-specific alt text and captions in EN/ES/DE/FR/RU and focal positions. The four new candidates have no page assignment. Existing ART01 remains preview-only and its mobile crop remains a draft.
- Fixed a real preview defect: removing a legacy image slot freed that render for a different page. Rejected candidates are now reserved site-wide; synthetic excavation, frame and roof-work images are excluded from preview. F23's raster slot is hidden rather than silently consumed behind the vector locator. Fixed invalid override-list validation as well.
- Added a reproducible mobile coordinate locator with larger labels, preserving the same source coordinates and attribution. Source generator: scripts/tenerife_site_build/location_locator.py. Desktop locator unchanged. See evidence/F23_LA_QUINTA_LOCATION_SOURCES_2026-11-05.md.
- Regenerated the standard five-language diary listing and compiled CSS from canonical sources. No hand edits to generated HTML.

## Verified execution
- Five preview builds and five default builds passed with Python 3.12.13. Rebuilt after latest main integration: all 70 primary-page preview HTML files are byte-identical to the responsive-tested version.
- Responsive browser checks: 14 primary page types × 5 locales × 4 widths (320/768/1024/1440), 280 checks. No horizontal page overflow, broken images after decode, missing concept notice or H1/primary-CTA count failures. This is the current preview with temporary hidden slots, not QA of unassigned artwork.
- Mobile menu: opens, makes background inert, closes on Escape, returns focus. Public diary listing: 320 px, no overflow and visible localized caption.
- Screenshots visually inspected for homepage desktop/mobile and mobile map. Evidence and scope: evidence/RESPONSIVE_2026-11-05.json and evidence/screenshots/.
- Full-suite output: evidence/TESTS_PY312_2026-11-05.txt. Some environment-dependent tests are skipped; do not call this live CRM or production-form validation.
- Durable execution integrity/recovery checks passed (six tests). Git diff whitespace checks passed.
- Read-only production GETs returned HTTP 200 at /tenerife/, /tenerife/norte/ and /tenerife/ru/. Deployed Git SHA was not exposed or verified. No production changes were made by this continuation.
- Previous Actions attempts failed before job steps; no fresh Actions success is claimed. Local execution closes the earlier build/test evidence gap. Manual-only CI workflow remains in place.

## Concrete review package
[P0 illustrations and mobile map](P0_REVIEW_2026-11-05.md) shows ART01 plus the four imported originals, exact intended slots and outstanding approval/composition work. Manifests and source bytes are durable in the same branch.

## Remaining / next action
1. Owner reviews the named five images for their intended purposes and confirms rights before public use. REVIEW must not be silently promoted to APPROVED.
2. Produce independent 4:5 mobile compositions where needed; the current ART01 crop is not an original mobile master. Do not simply crop the construction-stage sequence.
3. Assign specifically approved assets in preview only, apply image-specific captions, and repeat screenshot/dHash QA for actual placements. Keep documentary portraits and seven case photographs intact; their provenance review is still open.
4. Finish concept/specification copy coordination with the funnel/numeric authority. Existing legacy copy still mentions twenty homes, sizes and infrastructure; a concept notice alone does not approve those facts.
5. After P0 approval/placement QA, proceed through the registry's P1/P2 artwork, diagrams and OG work. No financial chart before model verification.
6. Separate owner instruction is required for merge to main and production release.

Canonical execution journal is this file; local durable adapter state points here. No background automation, social posting, messaging or deployment was activated.
