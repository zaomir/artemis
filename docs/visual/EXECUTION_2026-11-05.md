# Artemis Atlantic Heritage Watercolour — execution checkpoint

Date: 2026-11-05 (Atlantic/Canary). Scope: `zaomir/artemis`, branch `feat/atlantic-watercolour-site-20261104`, draft [PR #39](https://github.com/zaomir/artemis/pull/39). **No merge, no deployment.**

## Authority
- Owner approved artistic direction and execution of the page image refresh; owner did **not** approve a specific final architectural design or production release.
- [Canon](../funnel/CONTENT_CANON.md) and [source Google Doc](https://docs.google.com/document/d/1BeIhmR5gb6uvX4HAUl8eyRBYHfAiNlxCmTGtWLFkQ6A/edit).
- [Site-wide detailed audit](ARTEMIS_SITE_VISUAL_AUDIT_2026-11-04.md), [atomic registry](ARTEMIS_SITE_VISUAL_PLAN_2026-11-04.tasks.json).
- Financial figures, investor return claims and personal tax exclusions are governed by separate PR #38 / funnel contract. Do not change them here.

## Verified in connected GitHub repository
- Main branch at start of original visual branch `6f1dccaf6906ee7213fc9e39f25970387addd4b5`. On 2026-11-05, main advanced by seven unrelated funnel operations/evidence commits; check it afresh before merge.
- `ART01` original + desktop/mobile candidate variants committed under `app/static/tenerife/site/img/`, with `docs/visual/candidates/manifest.json` recording dimensions, SHA256, generation and rights basis. **Status REVIEW**.
- `frames.json:preview_overrides` selects `index/F01` only with `ARTEMIS_VISUAL_PREVIEW=1`. `page_overrides={}`: no production substitution.
- `frames.json:preview_hidden` suppresses `norte/F21`, `producto/F05`, `inversores/F14`, `construccion/F15`, `equipo/F22` **only in review builds** while image bytes are pending. Default builds still use old published assets.
- `norte/F23` false-complex image is replaced in preview with the source-linked, coordinate-based original SVG `app/static/tenerife/site/img/la-quinta-context-locator-20261105.svg`. Coordinates checked against OSM/municipality/AEMET/TITSA; see `evidence/F23_LA_QUINTA_LOCATION_SOURCES_2026-11-05.md`. No made-up parcel boundary, road, route or ocean view.
- Review-only four-step project development diagram, five-language concept notice, five-language map explanation, accessibility and responsive styles in canonical builder/templates; no changes to financial math.
- Project diary list uses the existing provenanced watercolour `diary-atlantic-20261104.webp` as a thumbnail with a localized concept caption; article remains unrestricted.
- `scripts/tenerife_site_build/intake_watercolour.py` stages *actual local downloaded image bytes* into JPG/WebP and a SHA256/rights REVIEW manifest, without enabling a page slot or publishing. Test coverage added: `test_tenerife_art_intake.py`, `test_tenerife_visual_rollout.py`, `test_tenerife_news_visual.py`.

## Completed generations, not yet imported
Four more P0 watercolours generated in [ElevenLabs flow](https://elevenlabs.io/app/flows/lMim2AHTS796dcvWxR3o), IDs `wBYf7vERpRPDQRSzObyC` (norte/F21), `MRSkYIdJ4VasJW40dcsx` (producto/F05), `e23JTMG8M8JQCErDMrFw` (inversores/F14), `7ogqYT3DK47f4vw3nQwc` (construccion/F15). Each 1280×720. Their real bytes and verified hashes are **not** in GitHub; no slot mapped. Source-of-truth `docs/visual/candidates/p0-generation-inventory.json`. Do not substitute a generation URL for a durable file receipt, and do not claim they were imported.

## QA state
- Source readbacks completed for canonical edited code, assets and locale dictionaries.
- **Build/test execution NOT VERIFIED**. Actions run `41999416519` (and subsequent runs) failed before any job step (`steps=[]` or null; logs endpoint returned 404 BlobNotFound). Root cause unknown; do not describe as test failures, CI passes or billing evidence without check-run annotations/runner evidence. Visual workflow is now manual-only; there is no production deployment workflow.
- Public website inaccessible to available web browser; earlier external request returned an error, and separate Artemis funnel runtime reported a possible origin/Cloudflare 521. Exact current production state is **not verified**.
- Do not use screenshot claims or site-wide responsive QA without actual rendered evidence.

## Next atomic actions
1. Reconcile current main/ref and any unrelated concurrent changes, preserve no financial/CRM diffs in PR #39.
2. Fetch P0 source images from the exact ElevenLabs flow using a connected authenticated worker that can transfer full bytes. **Do not paste signed short-lived CDN URLs into the repository.** Import with `intake_watercolour.py`, inspect images visually, obtain owner art approval, verify rights/provenance/sha. For hero images require an original 4:5 composition (do not treat a crop as art-directed).
3. Assign approved assets to distinct page/Fxx slots via `preview_overrides`, remove corresponding `preview_hidden`, fill exact EN/ES/DE/FR/RU alts/captions and verify no repeated image (including dHash). Do not touch Simon/Boris portraits or real case photographs.
4. Run isolated five-language review build and tests (from repository root):
   `python3 -m pip install Pillow Jinja2`
   `python3 -m unittest discover -s tests -p 'test_tenerife_visual_rollout.py' -v`
   `python3 -m unittest discover -s tests -p 'test_tenerife_art_intake.py' -v`
   `python3 -m unittest discover -s tests -p 'test_tenerife_news_visual.py' -v`
   For each `lang` EN/ES/DE/FR/RU: `ARTEMIS_VISUAL_PREVIEW=1 TENERIFE_LOCALE=$lang TENERIFE_WHATSAPP=+440000000000 TENERIFE_OUT_DIR=/tmp/artemis-preview/$lang python3 scripts/tenerife_site_build/build_v3.py` (dummy test phone, not for production).
5. Perform 320/768/1024/1440 px screenshot QA with visual proof, fix failed cases, review documentary cases, then P1/P2. Full test suite and release gating remain mandatory.
6. Obtain explicit approval for specific images and separately for production release. Do not merge/deploy review-only PR by inference.

**Executor status:** implementation prepared and source-verified, not shipped or declared QA PASS. No automation/background task was set.
