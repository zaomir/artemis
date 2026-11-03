# Artemis investor journey — release evidence

User authorization: implement the attached 2026-11-03 content/navigation plan, remaining technical QA fixes,
publish source + mirror and verify production. Keep the existing Canary Stone style, media, financial model,
locale/geo entry rules, indexing flag and form data contract. This is a runtime implementation, not a new finance offer.

## Content ownership

| Owner | Responsibility |
|---|---|
| index | short introduction, current stage, residence/investment routes |
| inversores (04_akcii.md) | participation vs purchase, one complete price ladder, two outcomes, top-up/conditional assignment, shared calculator, control/documents |
| producto | types, counts, construida without common areas, finished-home prices, architecture/equipment |
| proceso | complete action sequence, contract/payment timing, existing mortgage/tax/formalization terms |
| calculadora | shared tool, definitions, formula explanations and examples |
| alquiler | rental inputs, operating expenses, assumptions |
| mercado | dated historical market comparisons and provenance notes |
| construccion | nine physical stages, timeline, log/reporting |
| equipo / simon / boris | brief responsibility map / detailed profiles and existing photos |
| faq | short answers linking to the detailed owner |

## Implementation

- Investor and team pages in RU/EN/ES/DE/FR; new primary menu and grouped footer.
- Old acciones URLs redirect once, keep query; old fragment IDs map to semantic investor sections.
- Shared calculator and existing waitlist endpoint; no new financial parameters or formula changes.
- Removed the false starting-price headline, labelled examples and the general dividend estimate clearly.
- Source occurrence validation now permits retired/derived examples to live in the calculator; it still checks
  arithmetic, expense totals, input prices and terms. The regenerated model differs only in token occurrence counts.
- Portfolio is manually scrollable, with seven accessible cards and no endlessly moving clone.
- Localized recovering 404; contact-channel validation; keyboard/mobile navigation and form checks.
- Crete: complete body translations, truthful status CTA, main/skip link, mobile menu, native form with pending
  protection and localized no-JS POST/303 receipt. No notification is sent during tests.
- Only content-fingerprinted images receive immutable cache policy. Unversioned CSS/JS/config still revalidate.

## Verification before release

- Five language builds passed, 14 content pages + two legal + notice/404 shells each.
- 469 unit/integration tests passed on macOS Python 3.11, 18 environment/optional checks skipped. The Linux deploy
  preflight separately runs the suite; the GNU install fixture is skipped only on macOS.
- Forty pre-change calculator cases retained in `tests/fixtures/tenerife_financial_baseline.json` and compared exactly.
- The entire old/new model JSON matches after excluding only `tokens[*].hits`; model inputs, Python calculation
  code and calc.js are unchanged.
- Durable-execution integrity/recovery checks and compliance scan passed.
- Browser checks: new pages in five languages at 320/768/1440; long RU footer link wrapping corrected; keyboard
  menu/CTA and invalid form tested. Production receipt is recorded in the grainee-v2 project release document.

Real owner notifications and real-user leads are not used as QA data. Successful persistence/notification paths
are tested against a temporary database and mocked notifier. Independent market snapshots are not repriced by this change.
