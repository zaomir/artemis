# ARTEMIS TENERIFE — ATOMIC CODEX PLAN
## Financial model, investor and buyer calculators, numerical consistency across the site
**Date:** 2026-11-04  
**Status:** execution specification; proposed parameter changes are NOT contractual approval  
**Repo:** zaomir/artemis (main)  
**Production:** https://artemisresort.com  
**Mirror:** grainee-v2/site-artemis/  
**Owner for business decisions:** founder. Legal/tax assertions require qualified professional review.

> **READ FIRST — NON-NEGOTIABLE:** DO NOT CALCULATE INVESTORS' PERSONAL TAXES. No investor tax rate input, investor tax residency, investor after-tax return, simulated withholding, credits, deductions, or personal tax optimisation in the UI, API, model, stored lead, or reports. All investor principal/income/payout figures are **before the investor's personal taxes**. Project/issuer taxes and legally applicable buyer purchase taxes MUST still be accounted for where relevant. Any issuer statutory withholding is a separate legal/accounting compliance question, not a personal investor-tax calculator.

## 0. Assignment, source priority and delivery protocol

Goal: replace the current unconditional investment × 1.09³ output with a cash-flow-consistent, auditable project forecast that distinguishes contractual targets, achievable payouts, unfunded gaps and timing. Identify and correct other numerical inconsistencies on Tenerife pages in RU/EN/ES/DE/FR without inventing data.

**Priority of authority (most to least):**
1. Explicit founder decisions (2026-11-04): 9% annual compounding for **actual funded period**; no share of upside above 9%; investor repayment waterfall direction; minimum package of 48 units. The legal instrument and feasibility of seniority must be confirmed by counsel.
2. Founder direction for pre-permit commitments: project needs funds when reserving land and wants investor commitments/payments before reservation; make seller carry maximum permit risk. Exact 20/80 split, 9-month permit lag, 75% subscription gate, escrow, deposit, max pre-permit loss and 48-month remedies are **PROPOSED, NOT APPROVED CONTRACT TERMS**. Implement scenario/configurable proposals; do not publish them as final terms.
3. Existing reproducible baseline, not a promise: scripts/tenerife_site_build/model_inputs.json → make_model.py → app/static/tenerife/site/model.json (version 2026-11-03-exit-e217663f18e3). See docs/qa/ARTEMIS_EXIT_MODEL_2026-11-03.md.
4. The 2026-11-03/04 consultant note “Artemis Tenerife — что и как должен считать калькулятор инвестора” is a proposal, NOT final finance or legal truth.

**Execution constraints:**
- Work from a clean, freshly updated main, record HEAD SHA, and do ONE ATOMIC IMPLEMENTATION PR PER TASK below. For each PR: purpose, exact files, tests, before/after numerical fixture, assumptions, residual risks and rollback. Merge only when explicitly authorized; after merge rebase the next task on current main.
- No direct commits to main for implementation, no server/prod deployment, no sending actual leads, no changing customer data or published copy without founder release approval.
- Preserve compatibility for existing URLs, the public waitlist flow, old calc_* payloads and records; avoid breaking Crete. Never manually edit generated HTML/model.json.
- The project may remain financially **incomplete** until quotes, permissions and legal structure are verified. A model status of incomplete MUST fail closed for claims of achievable return; do not silently substitute zero for unknown mandatory costs.
- All numbers and labels in one versioned source; avoid hard-coded finance numbers in JS, templates or translations. Keep source-status metadata and date visible in detailed results.
- Each task below is an independently reviewable PR. A task may deliver internal-only scaffolding; release is gated until the full chain is complete.

**Baseline regression (for OLD version only):**
20 homes; area midpoint 1,409 m²; 564 units × €2,352 = €1,326,528; buyer contract revenue €5,129,876.77; total model budget €4,490,813.25; selling cost €153,896.30; pool 36-month target €1,717,892.23; residual €93,802.99; minimum monthly cash €53,083.41 in month 7; 72 units: €169,344 → target €219,305; 9% compound for 36 months = +29.5029%.
Old month-0 outflow €1,057,426.93, while 20% of the full pool would yield only €265,305.60: a naïve introduction of 20/80 would cause a €792,121.33 month-0 shortage. Do not reuse the old expenditure schedule as a valid two-tranche forecast.

## PHASE A — establish truth and independent accounts

### A01 — Freeze the reproducible starting point (P0)
**Files:** model_inputs.json, make_model.py, model.json, tenerife_calc.py, tests/test_tenerife_exit_model.py.  
**Action:** snapshot file hashes, model version, baseline values, tests, generated pages and routes; compare current main with live pages where reachable. Record unverified live deployment explicitly.  
**Artifact:** docs/qa/ARTEMIS_NUMERIC_BASELINE.md, no business logic changed.  
**Acceptance:** reproduction of all OLD regression values to cents, checked against independent arithmetic; known gaps documented.

### A02 — Schema for assumptions and evidence (P0; requires A01)
**Action:** create versioned source records for value, unit, scope, status [verified/assumed/proposed/pending_legal], provenance URL or file, verification date and owner. Track €3,360/m², 6% growth, €1,750/built m², €799k land, twenty contracts, signing milestones, quote statuses. Distinguish gross/net areas and whether €3,360 is net of purchase taxes.  
**Acceptance:** all externally asserted material numeric inputs have a traceable evidence record; changes alter model hash/version.

### A03 — Budget ledger and expense completeness (P0; A02)
**Action:** distinguish land, acquisition tax and deed, hard construction, technical costs, infrastructure, sales costs, ICIO and municipal fees, project/issuer taxes, structural insurance, guarantees on buyer advances, legal/notary/registry, financing fees and contingency. Require explicit inclusion mapping if a cost is folded into “technical 10%”, “other €100k”, or other budget; prohibit duplicate items.  
**Acceptance:** expenses reconcile by category; unknown mandatory applicable lines have incomplete status rather than silently zero.

### A04 — Contingency as available versus spent (P0; A03)
**Action:** separate reserve allocation, committed reserve, spent reserve and unused reserve in monthly cash; recalculate the reserve consistently. The baseline contingency €408,255.75 is already included in the €4,490,813.25 budget and currently spent by phase. It CANNOT be “drawn again” to repair a cash gap.  
**Acceptance:** zero double counting, deterministic reserve-ledger reconciliation and tests.

### A05 — Restricted buyer funds and separate balances (P0; A03)
**Action:** separate escrow/special account for buyer advances, investor funds, unrestricted project operating cash and any other legally segregated cash. Model legal use-of-funds rules as REVIEW-PENDING configurations; a positive consolidated balance does not imply funds are available for investor redemption.  
**Acceptance:** tests fail when buyer advances improperly finance investor buyback or unrelated land/payment items; month-by-month inflow/outflow/encumbrance reconciles.

### A06 — Missing financing policy and solvency gate (P0; A04–A05)
**Action:** at every month and payment milestone detect cash < 0, liquidity cushion breaches and unpaid obligations. Define explicit outcomes: funded, external cash required, delayed/stopped pending funding, or infeasible. DO NOT insert free bridge credit or continue construction after unfinanced expenses. New financing requires explicit instrument, timing, ranking, amount, cost and founder/legal permission.  
**Acceptance:** any unfunded interval is flagged with exact amount/month and cannot be reported as an achievable unconditional payout.

## PHASE B — timing, instruments and investor cash flows

### B01 — Event-based project timeline (P0; A01–A03)
**Action:** model reservation, permit application, permit approval/refusal, final purchase, building commencement, buyer contracting, foundation, shell, handover, actual investor exit. Set event dates from inputs and dependencies; do not treat month 0 automatically as both land purchase and investor entry.  
**Acceptance:** changing approval date consistently shifts dependent events and cash flows; no buyer advances are assumed before the legally permissible/approved point.

### B02 — Pre-permit investor funding scenario (P0; B01, A05)
**Action:** configure proposed 20% at contract and 80% within 10 days of permit; alternative proposals selectable as internal scenario, NOT a published legal offering. Include subscription thresholds (illustrative 75% = 423 units), capital actually collected, seller reservation/deposit terms, escrow, refundable and nonrefundable spend, refusal scenario, permit-expiry date. First tranche of 564-unit pool €265,305.60; at 75% first tranche €198,979.20. Record seller and lawyer approvals separately.  
**Acceptance:** the simulator will NOT automatically pay €799k for land at month 0 from €265k contributions; upfront coverage and conditional acquisition are properly modeled.

### B03 — Per-tranche interest, actual duration and XIRR (P0; B02)
**Action:** interest ceiling 9% per year compounded on each actual paid tranche from its funding date to actual repayment date, with the contractually selected day-count convention explicitly documented. Calculate absolute payment obligations and optionally the effective annual rate (XIRR) from dated cash flows. Do not create personal tax logic.  
**Reference proposal example:** 72 units; €169,344 total; €33,868.80 at contract, €135,475.20 at permit 9 months later; exit 36 months after permit; pre-personal-tax target approx. €222,233.90. Base all production values on date-aware model, not a fixed hard-coded example.  
**Acceptance:** mathematical independent tests on day/month boundaries, 36/45/48+ months; no early-payment double interest; consistent rounding only on final amounts.

### B04 — Waterfall and upside cap (P0; A05–A06, B03)
**Action:** maintain separately (i) principal owed, (ii) accrued capped target return, (iii) legally accessible funds at exit, (iv) paid principal, (v) paid interest and (vi) sponsor residual. Founder direction: operating/mandatory expenses first, investor principal, then investor interest up to 9% annual target, sponsor takes residual only afterwards. Priority of any new financing and creditor ranking REQUIRE legal signoff; do not imply statutory priority solely from a marketing statement.  
**Acceptance:** no investor receives a percentage above 9% per funded period, no sponsor residual precedes investor contract payments, principal and interest can both be partial with precise shortfalls shown.

### B05 — Delay, failure to license, and exit remedies (P0; B01–B04)
**Action:** model permit rejection/refund, unrecovered reservation deposit, nonrecoverable professional costs, late second tranche/default, postponed exit, unsold inventory, and month-48 review/remedy as conditional choices. The proposed “investor loss at most 10%” must NOT be shown as guaranteed absent independently evidenced escrow, seller obligations and legal enforcement. A remedy to request asset sale does not imply instant liquidity or guaranteed sale price.  
**Acceptance:** counterexamples produce appropriate warnings and ranges; rules require verified contract flags to show any capital protection claim.

### B06 — Stress engine with scenario definitions (P0; A06, B04)
**Action:** externalize scenario overrides in input JSON: built_m2 cost, buyer price factor, annual price growth, reservation/permit delay, sales delay, unsold types/identities, exit month, buyer payment delays, tax/cost variants and financing options. Run the SAME cash engine for each scenario, never override final cash as a standalone number.  
**Acceptance:** scenarios are deterministic, monotonic under isolated adverse inputs where expected, and show financing need separately from target and cash-paid results. Keep historical benchmark rows but mark legacy/infeasible assumptions.

### B07 — Feasibility thresholds and cost/price matrix (P1; B06)
**Action:** compute “full contractual target possible” and “principal fully recoverable” thresholds by bisection or exhaustive search ONLY for one-variable-at-a-time sensitivities; also provide combined 2D grid of construction costs and sale prices, stress, financing need and result. Never present independent thresholds as simultaneous safe bounds.  
**Acceptance:** boundary tests ±€1, correct failure classification, no impossible monotonicity claims for complex combined stress conditions.

### B08 — Legal/tax perimeter for issuer and buyer (P0 legal gate; A02–A03)
**Action:** record actual intended issuer/SPV, country, instrument (loan/bonds/other), cash and refund protection, eligible offerees and required disclosures. Check 100k exemptions carefully: Prospectus Regulation Article 1(4)(c) is denomination per security; Article 1(4)(d) concerns €100k per investor per offer. Two separately issued tranches of <€100k cannot simply borrow another offer’s exemption. Escalate all sale-of-securities, German investor, Russia-sanctions and Spanish funds-raising questions to qualified legal counsel. Determine applicable issuer/company taxes (including deductibility restrictions) and buyer taxes at transaction-level. No investor personal tax calculations.  
**Acceptance:** legal conclusions are tagged reviewed/unreviewed; unavailable signoff blocks regulated claims, not all educational site pages.

## PHASE C — calculators, server and records

### C01 — Published financial snapshot schema (P0; B06–B08)
**Action:** generate one read-only, versioned build artifact from inputs, cash engine, scenarios and evidence: assumptions, status, mandatory-cost gaps, payments, forecast receipts, funding gaps, payout waterfalls, thresholds and date/version. Separate public-safe values from sensitive internal data. Explicitly omit investor-tax fields.  
**Acceptance:** data validation prevents a “confirmed forecast” when financial/legal essentials are missing; file content hash stable and reproducible.

### C02 — Investor browser calculator (P0; C01)
**Files:** app/static/tenerife/site/calc.js, generation/template sources.  
**Action:** remove finance formula from browser and display selected precomputed, trusted snapshot results multiplied/parameterised by quantity when mathematically valid. Show price per contractual unit, two dated tranches (once legally approved), target payable, cash-available estimate, funding gap, four risk scenarios, sensitivity and model version. If the snapshot is incomplete, display “target, not project-funded forecast” and a visible data-gap statement. Permit sensible free-step packages above 48, subject to remaining issuance cap, not arbitrary 100-unit cap. Avoid claiming “1 unit = 1 m².”  
**Acceptance:** UI recalculates for every valid N, no arithmetic drift, accessible with JS and useful server-rendered default without JS; no investor tax questions.

### C03 — Backend recomputation, validation and lead persistence (P0; C01–C02)
**Files:** app/tenerife_calc.py, app/tenerife.py, DB migration, tests.  
**Action:** server recomputes N, tranche amounts/dates, target, feasible payment, earnings, risk flags, version and source status; do not trust submitted euros. Preserve legacy calc_m2/calc_step/calc_pay request fields and old rows. Schema migration idempotent, no personal tax fields. Define invalid/obsolete/version-mismatch behavior and transparent consent.  
**Acceptance:** browser/server exact parity including half-up on final euros, no €1 discrepancy for 72 shares, no real notifications while testing.

### C04 — Independent buyer purchase calculator (P1; A02–A03, B01)
**Action:** new separate calculation for residence type, precise unit area, timing of contract and price lock, applicable price growth until signing, staged purchase payments 40/30/10/20 and catch-up, IGIC/AJD purchase transaction taxes by confirmed classification, notary/registry estimate and all-in cost. Buyer purchase taxes ARE IN SCOPE; never cross-wire them into investor personal taxes. Show tax-rate assumptions and exceptions rather than universal 7%/1% rules.  
**Acceptance:** baseline 73 m² × €3,360 × 1.06^(7/12) ≈ €253,760 gross-before-purchase-tax sale price; independently verified payment schedule and no double-taxing instalments.

### C05 — Clear output semantics and investor-risk disclosure (P1; C02–C04)
**Action:** explicitly label contractual target vs achievable under model vs shortfall; investable funds are not cash guarantees; scenario shortfall and external finance requirements must be close to the amounts. Label upfront schedule as PROPOSAL until approved, display projection before personal taxes with no calculation of personal taxes. Avoid green “guaranteed” signals, unverified protection claims or fabricated testimonials.  
**Acceptance:** assisted UX audit shows no reasonable interpretation that 9% is unconditional or initial funds are safe by default.

## PHASE D — site-wide numerics, language and delivery integrity

### D01 — Full numerical inventory of Tenerife pages (P0; A01–A02)
**Pages in each of RU/EN/ES/DE/FR:** index, norte, producto, inversores, calculadora, alquiler, energia, construccion, proceso, faq, simon, mercado, boris, equipo, impressum and privacy where relevant, plus metadata, FAQ schema, forms and calculator scripts.  
**Action:** extract ALL numeric claims: investment amounts, unit ranges, deadlines, pricing, floor areas, home count, distances, energy production/savings, construction cost, budget, property taxes and exits. For each, record URL, literal displayed number, provenance, arithmetic, correction/pending evidence, and all five language equivalents. Verify site actual live state independently; do not treat git HTML as proof that production has updated.  
**Acceptance:** CSV/Markdown audit with one row per claim and zero unclassified numerical claims.

### D02 — Update investment-facing public copy in all languages (P1; C05, D01)
**Action:** update site copy sources, not generated HTML: investor page, investment calculator, home, FAQ, process, timeline and market. Remove single assured 9%-based output and obsolete “full upfront payment” once contract terms finalized. Explain project stage, dates, floor/ceiling, assumptions and forecast failure. Keep equivalents in all five languages; preserve canonical URLs and metadata.  
**Acceptance:** exact amounts from model tokens; no stale amounts, no untranslated tokens and no contradictory payment dates.

### D03 — Correct residence and energy/other arithmetic (P1; C04, D01)
**Action:** add complete buyer budget and taxes in product pages without overclaiming; audit 48–100 m² versus share ranges (different units); verify PVGIS assumptions (flat roof, 1490 kWh/kWp), system size 3–4 kW, annual savings €600–€1,000 and €120/mo base bill; distinguish independent examples from project verified equipment. Check travel times/distances against actual routes or mark estimated.  
**Acceptance:** correct dimensions and traceable links; claims not backed by site/engineering evidence labeled as estimates.

### D04 — Lead-to-CRM Twenty reconciliation (P1; C03)
**Action:** inspect current integration status before modifying it. The required behavioral goal is that every successfully accepted Artemis enquiry is durably recorded and delivered to Twenty CRM, without double leads or lost events. Implement idempotent queued/retryable delivery and reconciliation report only if existing architecture and access permit; preserve existing notifications and no-phone lead policy. Do not send actual test leads to production. Store calculator model version and scenario references, NOT investor personal-tax fields.  
**Acceptance:** simulated failures/retries are lossless and deduplicated; controlled Twenty test result or explicit documented blocker, not an unverified “all leads arrive” claim.

### D05 — Legal entity and contract terminology consistency (P0 release gate; B08, D02)
**Action:** check actual issuer/SPV vs Oxford Frame Real Assets Ltd footer and legal disclosures. Until counsel resolves instrument, avoid implying an actual statutory “share” entitlement, 48-share securities exemption or 100% protected refund. Ensure 48 units minimum; Germany 86-unit proposed threshold only if legally justified and explicitly approved.  
**Acceptance:** no legal identity conflict across site, PDFs, CRM records or application; unresolved questions listed in release blockers.

## PHASE E — test, evidence and controlled release

### E01 — Math/property regression tests (P0; after B/C)
**Action:** fixed historical fixtures + new approved scenario fixtures, unit conversion, cost/cash reconciliation, minimum cash, sales counted once, interest by funded date, 36/45/48-month exits, adverse-price/cost monotonic cases, reserve nonduplication, separated restricted cash, delayed permit, unfunded months, cash waterfall, two-variable grid boundaries, exactly half-up final euros, no investor-tax computations.  
**Acceptance:** independent recomputation and unit/property tests pass; new fixtures are reviewed rather than rubber-stamping generated output.

### E02 — Five-language, browser and API integration tests (P0; after C/D)
**Action:** test JS/no-JS, 319px/1280px/mobile, keyboard accessibility, copy and server parity at min, 49, 72, 100 and max permitted quantity, external form responses, CRM mocks, invalid/stale submissions, FAQ schema, SEO, all public paths/redirects, privacy/consent. Detect stale old financial text anywhere including translations/metadata.  
**Acceptance:** all 5 locales render without untranslated financial placeholders, overflow, stale old-payment statements, or JS/console errors. Crete tests remain green.

### E03 — Release review, diff report and safety stop (P0; E01–E02)
**Action:** produce docs/qa/ARTEMIS_NUMERIC_AUDIT_FINAL.md with (a) old/new input matrix, (b) old/new amounts by page and locale, (c) scenario and liquidity results, (d) source evidence, (e) legal and financial unresolved items, (f) tests, (g) deployment/rollback/smoke checklist, (h) explicit approvals required. Create a final release PR; request founder approval before merge/deploy. Run server deployment and smoke checks ONLY after explicit approval.  
**Acceptance:** founder can see a precise delta and remaining uncertainty; production unchanged unless explicitly approved.

## Required PR template for ALL tasks
- Task ID / dependency / commit SHA.
- Objective and exact changed paths.
- Source-of-truth assumption and approved/unapproved status.
- Numerical comparison, including exact dates and whether targets are fundable.
- Tests executed and results (do not claim passes without running).
- Legal/financial blockers not solved by code.
- No production change; explicit next task.

## Nonnegotiable numerical checks
1. 72 old units: €169,344 × 1.09³ = €219,305.0 after final rounding; gross gain €49,961. Incremental unit values must NOT be rounded to cents before multiplication if it creates a €1 drift.
2. 564 × €2,352 = €1,326,528. 20% proposed first tranche €265,305.60; 75% of 564 units is 423, whose first tranche totals €198,979.20.
3. If the baseline reserve is fully expensed, it is NOT independently available as spare cash.
4. For the 9-month pre-permit example, incremental compounded target over the OLD one-tranche baseline is approx. €22,939.96 for the WHOLE pool, leaving approx. €70,863.03 of old residual, BEFORE recasting the timeline/taxes. This is **NOT** a valid new full-project forecast.
5. Four-year constant-funded target for 72 units €169,344 × 1.09^4 ≈ €239,043; if the project cannot fund this, show the actual funds shortfall. Do not reuse €219,305 as a 48-month target.
6. No “investor max loss 10%” claim without legally enforceable and funded protection evidence.
7. Scenario grid must consider simultaneous cost inflation and buyer-price fall; standalone break-even sensitivities are NOT jointly safe.
8. “Personal taxes of the investor”: NEVER calculate them anywhere. Label investor outputs before investor personal tax only if necessary; avoid tax-rate fields and after-tax figures.

## Explicit founder / counsel checkpoints (not to be guessed by Codex)
- Issuer/SPV and instrument, repayment ranking, regulatory offer basis by jurisdiction.
- Land reservation/deposit and seller permit risk allocation, real quote and permit horizon.
- Proposed tranche percentage, 75% commitment threshold, second-tranche deadline and refund/default rules.
- Buyer pre-sale receipt legality, protective accounts, guarantee wording and timing.
- Verified project taxes/insurance/fee estimates and actual construction tenders.
- Definition of actual exit trigger, maximum period and unsold-home remedies.
- Whether market/buyer prices and 6% growth are supportable as a forecast.

## Execution command for a new Codex agent
“Read docs/qa/ARTEMIS_CODEX_NUMERIC_REMEDIATION_PLAN_2026-11-04.md and the existing 2026-11-03 exit-model report. Start ONLY with A01 on a fresh implementation branch based on current main. Deliver an atomic draft PR and evidence, do not merge or deploy. Never calculate investors' personal taxes. Do not treat proposed 20/80 payment terms as final or guarantee forecast results.”

**Document lifecycle:** This plan is a coordination/specification artifact. Its PR is separate from all implementation PRs. Anyone making a decision that supersedes this plan must update the document with dated founder approval and propagate the updated version to the next agent.
