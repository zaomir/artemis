# Artemis Tenerife — RU prod pages (`/tenerife/`)

Generated files. Do not edit by hand: edit the author's source and rebuild.

- Source: `zaomir/grainee-v2` → `docs/projects/artemis/tenerife/site-ru/` (6 pages + `style.css`).
- Served by `app/tenerife.py`: `/tenerife/`, `/tenerife/<page>/` (clean URLs, canonical);
  `/tenerife/<page>.html` and `/tenerife/<page>` → 301 to the clean URL.
- Static: `app/static/tenerife/site/` (`style.css` = self-hosted fonts + author CSS + form/footer CSS,
  `img/` = Leonardo visualisations downloaded once — never hot-linked from cdn.leonardo.ai,
  `fonts/` = Newsreader / Source Sans 3 woff2, OFL, no requests to Google).
- Builder: `scripts/tenerife_site_build/build.py` (rerun when the author adds/changes pages).
- Status 31.10.2026 02:05 UTC: only `index` and `norte` delivered (grainee-v2 main `e186f8052e`).
  Nav items for missing pages are dropped and the waitlist form sits on `/tenerife/#waitlist`;
  once `proceso.html` arrives the form moves to `/tenerife/proceso/#waitlist`. Add new pages to
  `TENERIFE_PATHS` in `deploy/artemis-deploy.sh`.
- Legal pages: `/tenerife/impressum/`, `/tenerife/privacy/` (Jinja templates `app/templates/tenerife/`, indexable,
  canonical, in sitemap; CSS `/static/tenerife/base.css`, no inline styles — CSP `style-src 'self'` on `/tenerife/`).
  Old `/tenerife-preview/impressum/` and `/tenerife-preview/privacy/` → 301 (31.10.2026).
- Build: links `X.html` → `/tenerife/X/`; images → local (downloaded once);
  shared footer (Impressum/privacy links, OXFORD FRAME REAL ASSETS LTD, 09153936) — no disclaimer block
  and no «Визуализация»/AI captions (founder 31.10 01:44 UTC);
  waitlist form on `/tenerife/proceso/#waitlist` (or `/tenerife/#waitlist` while proceso is missing) → `POST /api/tenerife/waitlist`
  (sqlite + TG `ARTEMIS_TG_CHAT_ID`, GDPR consent, honeypot, rate limit, no amount field).
- Indexable (no noindex) — decision DEC-ARTEMIS-TENERIFE-PREVIEW-2026-10-31 row 5 (`/tenerife/` on this domain).
  Not linked from the Crete menu. `/tenerife-preview/` stays (noindex).
- Tests: `tests/test_tenerife_site.py`. Smoke: `deploy/artemis-deploy.sh` (TENERIFE_PATHS).
