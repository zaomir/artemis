# Artemis Tenerife — RU prod pages (`/tenerife/`)

Generated files. Do not edit by hand: edit the source and rebuild.

## RU v3 (current): 13 pages from `copy_v3`

- Source copy: `scripts/tenerife_site_build/copy_v3/` (01–13 pages + 14 footer, 15–16 legal, 17 form, `numbers.md`,
  `make_numbers.py`, `wc.py`), sha256 pinned in `build_v3.py` (`COPY_SHA256`, over the explicit list `copy_files()`:
  01–17 only, a draft such as `18_investoram.md` is neither built nor hashed) — the build fails if the copy changes
  without re-approval. Form messages (button while sending, success, errors) = `17_forma.md` «Сообщения формы»,
  put on the form as `data-msg-*` for `waitlist.js`; `app/tenerife.py` `FORM_MSG` holds the same texts (tested).
  Text, title, description and H1 are transferred without edits.
- Numbers: one data source. Edit `scripts/tenerife_site_build/model_inputs.json`, then
  `python scripts/tenerife_site_build/make_model.py` → `app/tenerife_site/data/model.json` (r4.1: not under `app/static/`, never served)
  (every price / dividend / tier figure of the copy as a token, plus the calculator block), then
  `python scripts/tenerife_site_build/build_v3.py` → these HTML files + `app/static/tenerife/site/site.css`.
  `make_model.py --check` proves the model reproduces `numbers.md` from `model_inputs.baseline.json`.
  Templates and `calc.js` contain no figures (tested).
- Photos: `[КАДР Fxx]` → project photos in `app/static/tenerife/site/img/` per `frames.json`
  (preferred photo per frame; T47: each photo in ONE slot on the whole site, heroes first, the build fails on a
  repeat by file or dHash); slots without a free photo are text blocks with the basalt bar; see `frames_report.json`.
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
  (clean URLs, canonical, no hreflang: RU is review-only, noindex unless TENERIFE_INDEXING=1); `/tenerife/<page>.html` and `/tenerife/<page>` → 301.
- Waitlist form on every page (`#ochered`, form `#waitlist` kept for the no-JS redirect) → `POST /api/tenerife/waitlist` (unchanged endpoint).
- Tests: `tests/test_tenerife_v3.py` (+ `tests/test_tenerife_site.py`). Smoke: `TENERIFE_PATHS` in `deploy/artemis-deploy.sh`.
- `scripts/tenerife_site_build/build.py` is the previous builder (author HTML from `zaomir/grainee-v2`);
  do not rerun it for `/tenerife/` — it would overwrite the v3 pages.

## Shared

- Static: `app/static/tenerife/site/` (`img/` = project visualisations downloaded once — never hot-linked from
  cdn.leonardo.ai; `fonts/` = Literata / Source Sans 3 woff2 for v3; the older Newsreader / sourcesans3-* files belong to `style.css` of the
  previous builder (kept: still referenced by `build.py`, old tests and the deploy smoke); OFL, no requests to Google).
- Legal pages: `/tenerife/impressum/`, `/tenerife/privacy/` (Jinja templates `app/templates/tenerife/`, indexable,
  canonical, in sitemap; CSS `/static/tenerife/site/site.css` (v3.1, text 68ch), no inline styles — CSP `style-src 'self'` on `/tenerife/`).
- Footer: no disclaimer block and no «Визуализация»/AI captions (founder 31.10 01:44 UTC).
- Indexing: switched by `TENERIFE_INDEXING` (see below). Default = noindex until the founder approves numbers and
  prices; with `TENERIFE_INDEXING=1` indexable as decided in DEC-ARTEMIS-TENERIFE-PREVIEW-2026-10-31 row 5.
  Not linked from the Crete menu. `/tenerife-preview/` (old one-pager) is retired: every URL under it answers one 301
  to the same page under `/tenerife/` if it exists, else `/tenerife/` (designer T47, 31.10.2026).

## Runtime configuration (sysadmin, r4) — `/etc/artemis/artemis.env`, read by `app/tenerife.py` on every request

### Figures switch (r4.1, build time)

`TENERIFE_SHOW_FIGURES` is read by `build_v3.py` only, never by the app. Unset (default, the committed pages) → the
build leaves out every sentence, list item, table row, table, section and meta text of the copy that shows a figure:
any euro amount (price per m² / per share, the price ladder, payments, rents, costs), a dividend or yield %, the
mini ladder and the calculator (C9 and C9 short, so no `calc_*` form fields). Intro lines that announced a removed
table/list, headings left without content and the payment-example sections (`FIGURE_SECTIONS`) go with them; the
build fails (`check_no_figures`) if a figure or a link to an unpublished investor page is left in any page.
`TENERIFE_SHOW_FIGURES=1` → the pages are rebuilt exactly as before r4.1. The copy (`copy_v3/*.md`) and
`model.json` are not changed. The investor page (`/tenerife/inversores/`, draft `18_investoram.md`) is not built
and `app/tenerife.py` answers 404 for `UNPUBLISHED_PAGES` even if it were added to `SITE_PAGES`.

The built HTML is committed; these values are not. Neither is ever written to a log.

| Variable | Value | Effect |
|---|---|---|
| `TENERIFE_WHATSAPP` | E.164 with `+`, digits only (`+` then 8–15 digits, e.g. `+440000000000`) | Footer «Контакты» on every `/tenerife/` page (and the no-JS answer pages): «WhatsApp: » + link `https://wa.me/<digits>`, link text = the number in international form, `aria-label="WhatsApp: <number>"`. Unset or invalid → the contact is left out (never a placeholder) and one warning without the value is logged (`artemis.tenerife`). |
| `TENERIFE_INDEXING` | `1` or unset | Unset (or anything but `1`) → every `/tenerife/` page gets `<meta name="robots" content="noindex, nofollow">` and `X-Robots-Tag: noindex, nofollow` (impressum/privacy included) and no `/tenerife/` URL is in `/sitemap.xml`. `1` → indexable, in the sitemap. Crete pages are not affected. |

Code: `whatsapp_number()`, `tenerife_indexing()`, `_finish()` in `app/tenerife.py` (`_site_page`, `_notice`);
sitemap: `sitemap_paths()` in `app/app.py`. The build (`build_v3.py`) turns the token
`WhatsApp: {номер из TENERIFE_WHATSAPP}` of `14_podval.md` into the empty slot `<li data-tenerife-whatsapp hidden></li>`
(the number itself is never written into these files); it refuses to run when `TENERIFE_WHATSAPP` is empty or invalid
and fails on any `{`, `}` or `TENERIFE_WHATSAPP` left in the output. Restart the app after changing the env file.
