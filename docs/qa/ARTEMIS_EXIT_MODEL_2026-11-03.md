# Tenerife cash-exit model release — 2026-11-03

The previous public offer combined rental distributions, six price stages, investor instalments and a share-to-home exchange. The founder requested the self-funded exit model instead: investors pay in full, construction is financed by investors and home sales, and capital plus income is paid at exit. The release updates all five Tenerife locales; Crete is outside scope.

## Current financial contract

- Market comparison reference: **3,360 €/m², provisional assumption**, not a verified current local new-build price. The current peer price list still needs confirmation.
- Early entry: 70% of that reference, **2,352 € per share**. A share quantity is an investment size, not allocation of a specific residence.
- Investor payment: full amount once. **No annual distributions**, investor instalments, extra payment bonuses or simultaneous home transfer and cash buyback.
- Cash exit: sale or buyback of participation, funded by home-sale receipts. **9% annualised target over 36 months**, compound calculation; the result depends on sales, costs and timing.
- Unsold homes: **6% assumed annual price growth** until each buyer signs. Contract prices do not continue appreciating in revenue after signing.
- Proposed buyer payments: **40/30/10/20%**, cumulative 70% at foundation month 8 and 80% at shell month 18. Late signers catch up completed milestones immediately; 20% is settled in month 36.
- Initial financing: 564 whole shares (40% of the 1,409m² midpoint area, rounded up), **1,326,528 €** in month 0 before the plot purchase. No developer contribution, bank loan or unexplained funding plug.
- Twenty distinct buyer contracts in months 3–30; investor financing is not counted as home-sale revenue.

## Regression amounts from the agreed planning workbook

| Shares | Full investment | Target cash exit | Income |
|---|---:|---:|---:|
| 48 | 112,896 € | 146,204 € | 33,308 € |
| 72 | 169,344 € | 219,305 € | 49,961 € |
| 100 | 235,200 € | 304,591 € | 69,391 € |

Total target growth is 29.5029% over three years. Display rounding is half-up to whole euros, without rounding the intermediate financial schedule.

| Project base scenario | Amount |
|---|---:|
| Investor financing | 1,326,528.00 € |
| Buyer contracts | 5,129,876.77 € |
| Land, works, technical costs, common areas and spent contingency | 4,490,813.25 € |
| Selling costs | 153,896.30 € |
| Full investor redemption | 1,717,892.23 € |
| Remaining project cash | 93,802.99 € |
| Minimum monthly closing cash, month 7 | 53,083.41 € |

The schedule assumes planned receipts precede payments within each month. It is a monthly planning model, not evidence of deposits or signed contracts. The 50,000 € internal liquidity target leaves only 3,083 € headroom at the tightest month.

Construction at 2,100 €/built m² leaves **562,579.66 €** missing from the target redemption. Delaying sales two months creates an interim **202,235.99 €** cash deficit even though the hypothetical final balance is positive. No additional developer money is inserted in either stress case. The site explains these dependencies in the financing section and FAQ, without presenting the target as guaranteed.

## Sources and claim classification

| Claim | Classification | Source / method |
|---|---|---|
| 9% target, 36 months, 6% growth, 30% discount | Estimated scenario parameters | Founder instructions and the agreed self-funded planning model in this conversation |
| Entry, exit, project balances and stresses | Calculated | `scripts/tenerife_site_build/model_inputs.json` → `make_model.py`; fixed workbook regression points in `tests/test_tenerife_exit_model.py` |
| 3,360 €/m² comparison reference | Estimated / unverified | Retained provisional planning reference; not promoted to current market evidence |
| Neighbouring developments sold; no current public price list | Observed source state | [Reside Tenerife](https://residentenerife.com/obra-nueva), checked 2026-11-03 |
| Construction reference 1,750 €/built m²; higher case 2,100 € | Benchmark, not project quotation | [Urbara](https://urbara.com/guias/cuanto-cuesta-construir-casa-tenerife), updated 2026-07-12 and checked 2026-11-03; land/design/common works separate |
| Buyer signing dates, payment schedule and project budget | Estimated planning inputs | Proposed schedule, not secured presales or a contractor quotation |

These claims are verified for publication **as the labeled calculation or assumption stated here**, not as confirmed future outcomes or market prices.

## Implementation and validation

- One financial source drives explicit `@name@` copy tokens, the server-rendered calculator, client recalculation and the monthly project ledger. Unresolved financial tokens fail the build.
- Both `/inversores/#calculate` and `/calculadora/` share the same calculator and locale strings. The visible result is available without a form submission or JavaScript.
- Existing `calc_m2`, `calc_step`, `calc_pay` request names are retained for compatibility. In this model they mean share quantity, early entry and full payment. The server ignores submitted money, recomputes the result and stores exit amount, income, months, target and the input-derived model version. Old stages and instalment requests are accepted as enquiries but explicitly marked stale and normalized.
- SQLite additions are idempotent; old rows retain their prior stored values. Lead notification formatting describes shares and cash exit. No production leads or messages were sent for validation.
- Calculator JavaScript has a content hash in its URL so an earlier rental calculator is not reused from cache.
- Five locale builds passed. Full local suite: **484 tests, OK, 18 skips** for existing Linux-only/absent-original/unused-relay fixtures. The server deployment also runs the complete suite on Linux before switching production.
- Financial regression points, signing-price lock, sales counted once, cash-gap stresses, obsolete requests and localized output are covered. Existing navigation, redirect, privacy, consent and CSP checks remain.
- Browser checks: 319px and 1280px wide, no horizontal overflow, no console errors; 72/100-share presets and a 49-share slider value recalculate correctly. Forms were tested locally with notification mocks.
- `slop_lint.py` passed for changed RU copy; only non-blocking list/rhythm notes remain. `git diff --check`, compliance scan and durable-execution checks passed.

Source of deployment remains `zaomir/artemis`, mirrored in `grainee-v2/site-artemis/`. Production uses the existing Artemis deploy script on VPS2402. Indexing, language routing, legal identity, images and design tokens are preserved.
