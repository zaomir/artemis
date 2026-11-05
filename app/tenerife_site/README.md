# Artemis Tenerife — EN public pages (`/tenerife/`)

Generated files. Do not edit by hand: edit the source and rebuild.

## EN r1 (current): 14 pages from `copy_en`, English only

- Source copy: `scripts/tenerife_site_build/copy_en/` (01–14 pages incl. 14 footer, 15–16 legal, 17 form,
  18 investors; `alts_en.json`, `ui_strings_en.md`, `en_notes.md` and `SHA256SUMS` for reference). Approved EN copy
  (Kimi 01.11.2026; 16+17 privacy micropatch 05.11.2026, QA PASS). Every file 01–18 is pinned in `build_v3.py`
  (`COPY_FILE_SHA256`) plus one combined sha (`COPY_SHA256_DEFAULT`, override `TENERIFE_COPY_SHA256`): the build
  fails if the copy changes without re-approval. Text, title, description and H1 are transferred without edits;
  slugs from each file's META (Spanish slugs kept).
- Pages: `index norte producto acciones condiciones alquiler energia construccion proceso faq simon mercado boris
  inversores`. Page 05 is «Terms» at `/tenerife/condiciones/`; the former calculator URLs
  (`/tenerife/calculadora`, `/tenerife/calculadora/`, `.html`, `/tenerife-preview/calculadora/`) answer a permanent
  **301** to `/tenerife/condiciones/` (query kept; `MOVED_PAGES` in `app/tenerife.py`). Page 18 «For investors» is
  built and served at `/tenerife/inversores/`.
- Figures: the pages show the copy as written (approved ranges: ≈2,900–3,100 → ≈3,700–3,900 €/m², dividend
  2.5–3.5% a year before tax). No model.json token substitution, no figure hiding, no calculator, no mini ladder,
  no `calc_*` form fields. `check_en()` fails the build on Cyrillic (only the `Русский` option of the language
  select is allowed), a forbidden figure (`FORBIDDEN_FIGURES`), a calculator link, `calc.js`, `model.json`,
  `name="calc_` or `hreflang=`.
- `app/tenerife_site/data/model.json` stays server side (never under `app/static/`, never served); the build reads it
  only for the C8 ladder bar heights (ratios in `site.css`), no figure reaches a page from it.
  `calc.js` is removed. Flask (`figures_blocked()`) answers 404 for any JSON and `calc.js` under `/static/tenerife/`.
- Form messages = `17_forma.md` «Form messages», put on the form as `data-msg-*` for `waitlist.js`;
  `app/tenerife.py` `FORM_MSG` holds the same texts (tested). Consent line = `17_forma.md` «Consent.».
  Each request goes to the team's Telegram working group with a copy to info@artemisresort.com (privacy 05.11.2026).
- Alts: `alts.json` holds 7 PROVISIONAL EN alts (translations of the RU alts of the 7 photos in use;
  `alts_en.json` is keyed by T47 slot ids of frames not in the repo) — for the designer to confirm.
- Photos: `[FRAME Fxx]` / `[КАДР Fxx]` → project photos in `app/static/tenerife/site/img/` per `frames.json`
  (T47: each photo in ONE slot on the whole site; see `frames_report.json`).
  The build fails if a frame token, `{{`, an HTML comment (except `<!--email_off-->`), `**`, an unprotected e-mail,
  inline script/style, or anything but exactly one `.cta-primary` reaches a page.
- Design system unchanged (Canary Stone v1; `site.css` = `design/fonts.css` + `design/tokens.css` + `site.src.css`
  + generated ladder rules). Fonts: headings Literata 500 (Latin subset preloaded), text Source Sans 3.
- Templates: `app/templates/tenerife/site/page.html` + `_components.html` (`html lang="en"`, `og:locale en_GB`).
  UI chrome strings not in the copy (Skip to content, Main menu, More, Menu, Key figures, field labels,
  ← Back to the project site / form) are developer-provided, pending Kimi review.
- JS (external, CSP `script-src 'self'`): `site.js`, `waitlist.js` (prod).
- Served by `app/tenerife.py` (`SITE_PAGES`; sitemap in `app/app.py`): `/tenerife/`, `/tenerife/<page>/`
  (self-canonical, no hreflang; noindex unless TENERIFE_INDEXING=1); `/tenerife/<page>.html` and `/tenerife/<page>` → 301.
- Waitlist form on every page (`#ochered`) → `POST /api/tenerife/waitlist` (unchanged endpoint).
- Build: `TENERIFE_WHATSAPP=+440000000000 python scripts/tenerife_site_build/legal_from_copy.py && \
  TENERIFE_WHATSAPP=+440000000000 python scripts/tenerife_site_build/build_v3.py`.
- Tests: `tests/test_tenerife_v3.py`, `test_tenerife_site.py`, `test_tenerife_qa_t3.py`, `test_tenerife_r4.py`,
  `test_tenerife_preview.py`. Smoke: `TENERIFE_PATHS` in `deploy/artemis-deploy.sh` (needs the EN r1 update, see
  the deploy notes; Sysadmin only).
- Not used for `/tenerife/` any more: `copy_v3/` (RU source, kept for reference), `build.py` (previous builder —
  do not rerun, it would overwrite the pages), `app/templates/tenerife/_waitlist.html` (RU, unused).

## Shared

- Static: `app/static/tenerife/site/` (`img/` = project visualisations downloaded once — never hot-linked from
  cdn.leonardo.ai; `fonts/` = Literata / Source Sans 3 woff2 for v3; the older Newsreader / sourcesans3-* files belong to `style.css` of the
  previous builder (kept: still referenced by `build.py`, old tests and the deploy smoke); OFL, no requests to Google).
- Legal pages: `/tenerife/impressum/`, `/tenerife/privacy/` (Jinja templates `app/templates/tenerife/`, indexable,
  canonical, in sitemap; CSS `/static/tenerife/site/site.css` (v3.1, text 68ch), no inline styles — CSP `style-src 'self'` on `/tenerife/`).
- Footer: no disclaimer block and no visualisation/AI captions (founder 31.10 01:44 UTC).
- Indexing: switched by `TENERIFE_INDEXING` (see below). Default = noindex until the founder approves numbers and
  prices; with `TENERIFE_INDEXING=1` indexable as decided in DEC-ARTEMIS-TENERIFE-PREVIEW-2026-10-31 row 5.
  Not linked from the Crete menu. `/tenerife-preview/` (old one-pager) is retired: every URL under it answers one 301
  to the same page under `/tenerife/` if it exists, else `/tenerife/` (designer T47, 31.10.2026).

## Runtime configuration (sysadmin, r4) — `/etc/artemis/artemis.env`, read by `app/tenerife.py` on every request

### Figures switch — retired (EN r1)

`TENERIFE_SHOW_FIGURES` has no effect any more (build or runtime). The pages show the approved copy ranges as
written; `figures_blocked()` always answers 404 for JSON and `calc.js` under `/static/tenerife/`; calculator URLs
answer 301 to `/tenerife/condiciones/`. It can be removed from the env file.

The built HTML is committed; these values are not. Neither is ever written to a log.

| Variable | Value | Effect |
|---|---|---|
| `TENERIFE_WHATSAPP` | E.164 with `+`, digits only (`+` then 8–15 digits, e.g. `+440000000000`) | Footer «Contact.» on every `/tenerife/` page (and the no-JS answer pages): «WhatsApp: » + link `https://wa.me/<digits>`, link text = the number in international form, `aria-label="WhatsApp: <number>"`. Unset or invalid → the contact is left out (never a placeholder) and one warning without the value is logged (`artemis.tenerife`). |
| `TENERIFE_INDEXING` | `1` or unset | Unset (or anything but `1`) → every `/tenerife/` page gets `<meta name="robots" content="noindex, nofollow">` and `X-Robots-Tag: noindex, nofollow` (impressum/privacy included) and no `/tenerife/` URL is in `/sitemap.xml`. `1` → indexable, in the sitemap. Crete pages are not affected. |

Code: `whatsapp_number()`, `tenerife_indexing()`, `_finish()` in `app/tenerife.py` (`_site_page`, `_notice`);
sitemap: `sitemap_paths()` in `app/app.py`. The build (`build_v3.py`) always adds the empty slot `<li data-tenerife-whatsapp hidden></li>` after the e-mail in
the footer «Contact.» list (the EN `14_podval.md` has no WhatsApp token)
(the number itself is never written into these files); it refuses to run when `TENERIFE_WHATSAPP` is empty or invalid
and fails on any `{`, `}` or `TENERIFE_WHATSAPP` left in the output. Restart the app after changing the env file.
