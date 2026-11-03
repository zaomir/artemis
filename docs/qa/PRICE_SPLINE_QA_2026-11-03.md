# Tenerife — six-stage spline price chart

Founder request: replace all price bars with a square spline area chart, a fixed cropped 2,900–3,900 EUR
axis and 100 EUR grid; highlight the first/last price, rename the initial investor stage and clarify percentages.

- One shared SVG component covers investors, market and construction pages in RU/EN/ES/DE/FR (15 placements).
  A French table-header mismatch that previously omitted the main graphic is corrected.
- The line uses monotone cubic interpolation through the six model prices: 2,950 / 3,100 / 3,250 / 3,450 /
  3,650 / 3,850 EUR. No invented peaks or extrapolation. The plot and gradient end at 2,900 EUR; max is 3,900.
- Both responsive canvases are square. The line is 3.5 physical pixels, grid spacing is 100 EUR. Mobile keeps
  every grid line, labels alternate ticks and uses a numbered stage key to accommodate translated names.
- The first stage is Early entry / Ранний вход / Entrada inicial / Früher Einstieg / Entrée initiale.
  The internal `queue` ID and the free waiting-list service remain compatible.
- The comparison is explicitly against the 3,850 EUR handover price. Early entry is 900 EUR / 23.4% lower;
  30.5% was growth from the initial price, so it is not relabelled as a discount. The other reductions are
  19.5%, 15.6%, 10.4% and 5.2%. The copy table is checked against approved baseline inputs and its displayed
  derived comparisons follow a model price edit, alongside the curve and calculator.
- Canary Stone colors, project fonts, design tokens, existing photos, navigation, language routing, privacy
  behavior and calculation algorithms are preserved. There is no chart dependency, network request or JS animation.

Verification: five builds; 477 unit/integration tests (18 optional/environment skips); monotonicity and endpoint
sampling, fixed-range rejection, all 15 localized outputs and the pre-existing 40 calculator snapshots. Browser
checks at 320/768/1024/1440 px cover all 15 chart placements (60 cases): no horizontal overflow, overlapping
SVG text, cropped labels or non-square canvases; 3.5 px stroke verified. Financial model JSON is identical to
the previous release after excluding copy-occurrence counts. Inputs, server calculator, calc.js and design tokens
have no diff. No external form submission or notification is performed.

Production SHA and smoke receipts are recorded in `grainee-v2/docs/projects/artemis/RELEASE_SPLINE_2026-11-03.md`.
