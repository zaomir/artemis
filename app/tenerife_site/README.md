# Artemis Tenerife — RU prod pages (`/tenerife/`)

Generated files. Do not edit by hand: edit the source and rebuild.

## RU v3 (current): 13 pages from `copy_v3`

- Source copy: `scripts/tenerife_site_build/copy_v3/` (01–13 pages + 14 footer, `numbers.md`, `make_numbers.py`, `wc.py`),
  sha256 pinned in `build_v3.py` (`COPY_SHA256`) — the build fails if the copy changes without re-approval.
  Text, title, description and H1 are transferred without edits.
- Numbers: one data source. Edit `scripts/tenerife_site_build/model_inputs.json`, then
  `python scripts/tenerife_site_build/make_model.py` → `app/static/tenerife/site/model.json`
  (every price / dividend / tier figure of the copy as a token, plus the calculator block), then
  `python scripts/tenerife_site_build/build_v3.py` → these HTML files + `app/static/tenerife/site/site.css`.
  `make_model.py --check` proves the model reproduces `numbers.md` from `model_inputs.baseline.json`.
  Templates and `calc.js` contain no figures (tested).
- Photos: `[КАДР Fxx]` → project photos in `app/static/tenerife/site/img/` per `frames.json`
  (preferred photo per frame, unique within a page); the result is in `frames_report.json`.
  The build fails if `[КАДР`, `{{`, an HTML comment (except `<!--email_off-->`), `**`, an unprotected e-mail,
  inline script/style, or anything but exactly one `.cta-primary` reaches a page.
- Design system (web-designer `tenerife/design/`, Canary Stone v1, DESIGN.md C1–C16; draft until QA PASS):
  `scripts/tenerife_site_build/design/{tokens.css,fonts.css,model.json}` are verbatim copies (a test compares them
  with the designer folder when it is on the machine; resync = copy again + rebuild).
  `site.css` = `design/fonts.css` + `design/tokens.css` (as is) + `site.src.css` (components.html CSS base…footer
  as is, then «production additions»: image fill, short/text hero, stack/split/long layouts, `.msg.ok/.err` for
  the prod waitlist.js) + generated ladder rules (`--p`/`--i` per step as nth-child rules: CSP forbids `style=`).
  Fonts: RU headings Literata 500, text Source Sans 3 400/600, self-hosted in `fonts/` (OFL texts included;
  `*-symbols-*` cover ← → ≤ ≥). Literata Cyrillic is preloaded. No colours, sizes or radii outside tokens.
- Templates: `app/templates/tenerife/site/page.html` + `_components.html` (C1 header + sheet, C2 hero
  full/short/text, C3 figures, C4 split-head, C5 text+image, C6 table (stacks with data-labels > 3 columns),
  C7 steps/ledger, C8 ladder, C9 calculator, C12 FAQ, C13 waitlist `#ochered`, C14 footer, C15 frames).
  Section layout is chosen by `build_v3.structure()` from the copy itself (faq / long text / stack / split / head).
- JS (all external, CSP `script-src 'self'`): `site.js` (C1: header solid by default and without JS, `.is-over`
  only while the hero picture is under it; mobile sheet, no-JS = anchor to `#footer-pages`; ladder rise only
  without reduced motion), `waitlist.js` (prod, unchanged), `calc.js` (05 only).
- Served by `app/tenerife.py` (`SITE_PAGES`; sitemap in `app/app.py`): `/tenerife/`, `/tenerife/<page>/`
  (clean URLs, canonical, hreflang ru only); `/tenerife/<page>.html` and `/tenerife/<page>` → 301.
- Waitlist form on every page (`#ochered`, form `#waitlist` kept for the no-JS redirect) → `POST /api/tenerife/waitlist` (unchanged endpoint).
- Tests: `tests/test_tenerife_v3.py` (+ `tests/test_tenerife_site.py`). Smoke: `TENERIFE_PATHS` in `deploy/artemis-deploy.sh`.
- `scripts/tenerife_site_build/build.py` is the previous builder (author HTML from `zaomir/grainee-v2`);
  do not rerun it for `/tenerife/` — it would overwrite the v3 pages.

## Shared

- Static: `app/static/tenerife/site/` (`img/` = project visualisations downloaded once — never hot-linked from
  cdn.leonardo.ai; `fonts/` = Literata / Source Sans 3 woff2 for v3; the older Newsreader / sourcesans3-* files belong to `style.css` of the
  previous builder (kept: still referenced by `build.py`, old tests and the deploy smoke); OFL, no requests to Google).
- Legal pages: `/tenerife/impressum/`, `/tenerife/privacy/` (Jinja templates `app/templates/tenerife/`, indexable,
  canonical, in sitemap; CSS `/static/tenerife/base.css`, no inline styles — CSP `style-src 'self'` on `/tenerife/`).
- Footer: no disclaimer block and no «Визуализация»/AI captions (founder 31.10 01:44 UTC).
- Indexable (no noindex) — decision DEC-ARTEMIS-TENERIFE-PREVIEW-2026-10-31 row 5. Not linked from the Crete menu.
  `/tenerife-preview/` stays (noindex).
