# Artemis Tenerife — prod pages in five languages (`/tenerife/`)

Generated files. Do not edit by hand: edit the source and rebuild.

## Locales (2026-11-02)

| What | RU | EN | ES | DE | FR |
|---|---|---|---|---|---|
| URL | `/tenerife/ru/…` | `/tenerife/…` | `/tenerife/es/…` | `/tenerife/de/…` | `/tenerife/fr/…` |
| Files | `app/tenerife_site/ru/` | `app/tenerife_site/` | `app/tenerife_site/es/` | `app/tenerife_site/de/` | `app/tenerife_site/fr/` |
| Copy | `scripts/tenerife_site_build/copy_v3/` | `copy_en/` | `copy_es/` | `copy_de/` | `copy_fr/` |

- Build one language at a time (13 pages + impressum + privacy + `_notice.html` in each directory):
  `TENERIFE_LOCALE=en python3 scripts/tenerife_site_build/build_v3.py` (same for `ru`, `es`, `de`, `fr`; Python 3.10+).
  `TENERIFE_COPY_DIR` / `TENERIFE_OUT_DIR` override the directories; by default they follow the locale.
- RU is the master (sha256-pinned copy, hand-written). EN/ES/DE/FR are translations of the same 13 page files plus
  the footer; the build matches components by heading order (RU heading ↔ translated heading), so a translation must
  keep the heading structure. Files 15–17 in `copy_<loc>/` are not read: legal text and the form come from
  `app/templates/tenerife/` and `copy_v3/17_forma.md`.
- `<html lang>`, `og:locale` and the `<link rel=alternate hreflang>` set (all five languages + `x-default` = EN) come
  from `build_v3.ALL_LANGS`; canonical is the page's own locale URL. The header switcher is EN/ES/DE/FR, the Russian
  version is a quiet «Русский» link in the footer.
- Investor release 2026-11-03: 14 content pages, legal pages, `_notice.html` and `_404.html` per locale.
  `04_akcii.md` is the sole source for `/inversores/`; `19_komanda.md` owns `/equipo/`.
  The same complete C9 calculator serves `/inversores/#calculate` and `/calculadora/`, with identical model/JS,
  labels from i18n_strings.json, and the existing waitlist endpoint/three calculator fields.
  The 2026-11-03 cash-exit release replaces the rental/stage offer: full upfront payment, 36 months, 9% annualised
  target and cash exit only. Entry is 70% of a provisional 3,360 €/m² reference; 6% annual growth applies only until
  each buyer signs. Neither the reference nor the growth is presented as observed current market data.
  The monthly schedule uses investor funding and buyer payments only, with zero developer top-up or debt.
  The 564-share pool is a planning input, never a claim of subscriptions already secured.
  Lead amounts, exit proceeds, income, term and target are recomputed server-side; old stage/installment payloads
  are marked stale and normalized. Legacy DB field names remain compatible but now hold share quantity and price.
  Validation and financial references: `docs/qa/ARTEMIS_EXIT_MODEL_2026-11-03.md`.
- Primary menu: producto / inversores / norte / construccion / equipo, then a request link to `#ochered`.
  The footer owns the auxiliary links in Project / Participation / Team / Documents groups; mobile uses the same
  primary hierarchy and exposes the four non-RU languages. Russian remains a quiet footer link.
- Full entry procedure belongs to proceso, home-use/letting context to alquiler, model-price references to mercado,
  financing and cash exit to inversores. Other pages link to those owners instead of repeating the full copy.
- All supported acciones slash/no-slash/HTML and locale/preview variants redirect once to the matching inversores
  URL with query intact. Its semantic section IDs retain s1…s13 aliases. The builder deletes old acciones.html.
- Profile/spacing release 2026-11-03: `people.json` assigns a portrait and three contextual photos to the
  Simon/Boris introduction and named sections. Photos use responsive picture elements; only case portfolios
  form horizontal strips. The calculator embeds without another padded section, and uses the standard gutters.
  Photo review, ownership and validation: `docs/qa/LAYOUT_PROFILE_QA_2026-11-03.md` in the repository root.
- Interface strings (menu, footer labels, skip link, «сейчас», stage names of the mini ladder, portfolio places) live in
  `locale_cfg.UI` / `locale_cfg.NAV_UI` / `locale_cfg.STAGE_NAMES` / `cases.json:place_by_locale`. Form, calculator,
  messages, alt texts and legal are localized via `i18n_strings.json`; RU form copy remains in `copy_v3/17_forma.md`.
- Routes: `app/tenerife.py` serves all five (locale roots, `/tenerife/en/` → `/tenerife/`, legacy `.html` → 301);
  `app/app.py` sitemap lists every locale. Smoke list: `TENERIFE_PATHS` in `deploy/artemis-deploy.sh`.

## RU v3 (current): 13 pages from `copy_v3`

- Source copy: `scripts/tenerife_site_build/copy_v3/` (01–13 pages + 14 footer, 15–16 legal, 17 form, `numbers.md`,
  `make_numbers.py`, `wc.py`), sha256 pinned in `build_v3.py` (`COPY_SHA256`, over the explicit list `copy_files()`:
  published page sources + footer/legal/form, now including 19; draft 18 is neither built nor hashed). The guard
  fails on unexpected copy changes; an explicitly authorized content release updates the pins in the same change.
  Form messages (button while sending, success, errors) = `17_forma.md` «Сообщения формы»,
  put on the form as `data-msg-*` for `waitlist.js`; `app/tenerife.py` `FORM_MSG` holds the same texts (tested).
  Text, title, description and H1 are transferred without edits.
- Numbers: one data source. Edit `scripts/tenerife_site_build/model_inputs.json`, then
  `python scripts/tenerife_site_build/make_model.py` → `app/static/tenerife/site/model.json`
  (explicit @name@ financial tokens, calculator inputs and monthly project cash flow), then
  `python scripts/tenerife_site_build/build_v3.py` → these HTML files + `app/static/tenerife/site/site.css`.
  `make_model.py --check` checks generation and base funding; `copy_v3/make_numbers.py` exports the current
  token table to `numbers.md`. The old `model_inputs.baseline.json` and designer price curve remain historical
  references and do not drive the public calculator. Explicit tokens prevent unrelated equal numbers changing together.
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
- Served by `app/tenerife.py` (`SITE_PAGES`; sitemap in `app/app.py`): `/tenerife/<page>/` (EN), `/tenerife/<locale>/`
  and `/tenerife/<locale>/<page>/` (RU/ES/DE/FR) — clean URLs, canonical per locale, hreflang on five languages;
  `/tenerife/<page>.html`, `/tenerife/<page>`, `/tenerife/<locale>/<page>.html` → 301.
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
