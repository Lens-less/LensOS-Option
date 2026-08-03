# LensOS Option · Research Brief Design System

## 1. Selected Direction And Product Character

The production surface at `/evidence` follows the user-confirmed direction
**A · 研究晨报**.

- Selection evidence: `design-previews/2026-07-24-lensos-research-desk/selection.json`.
- Design dials: visual variance 3/10, motion 2/10, information density 9/10.
- Product character: a bright institutional options-strategy research desk, not a release checklist and not a trading terminal.
- Primary reading model: conclusion first, supporting evidence second, capability gaps last.
- Product boundary: research-only, read-only, and fail-closed. No live-order, broker, sizing, or manual execution controls.

The remembered visual action is the asymmetric market brief: a large live BTC
price and DVOL pulse on the left, a ranked research-candidate sheet on the
right, joined by one continuous editorial plane.

## 2. Functional Contract

Within three seconds the researcher must be able to answer:

1. What is the current BTC underlying price?
2. What is BTC DVOL?
3. How fresh and trustworthy is the Deribit snapshot?
4. What structure is the primary research setup, and why?
5. Is entry currently permitted or only monitored?
6. Which legs define the setup, and what are credit, reference maximum loss,
   breakeven, strike distance, and expected-move multiple?
7. Which entry conditions pass, fail, or remain unknown?
8. What risk budget, profit-taking, state-transition, monitoring, and review
   rules govern the setup?

The primary reading sequence is:

1. compact masthead, source state, read-only boundary, and refresh action;
2. market pulse with BTC price, DVOL, effective quote age, and data trust;
3. eight-stage strategy workflow: collect, analyze, select, enter, risk, exit,
   monitor, review;
4. a defined-risk primary playbook with real eligible contracts and
   observable screening rank;
5. market, term-structure, call-wing, and expected-move analysis;
6. explicit entry conditions with observed values, thresholds, and status;
7. NAV-relative risk budget, reference one-contract economics, profit-taking,
   position-state ladder, monitoring, and promotion evidence;
8. volatility-surface evidence and the broader candidate table;
9. release and capability limitations in a collapsed secondary disclosure;
10. complete evidence chain for audit.

`strategy_research.v1` is the UI's strategy source of truth. It may synthesize
research playbooks, but it must remain `advisory_only`, keep execution disabled,
leave contract count null, and identify screening-only or missing evidence. A
missing account snapshot blocks sizing, not the rest of the research narrative.

When current market evidence is absent, the page must not invent prices,
surface metrics, candidates, or reassuring prose. It shows a clear unavailable
state and keeps the fail-closed boundary visible.

## 3. Reference DNA

### Coinbase — financial clarity

Borrow these concrete values and actions:

- `#0052ff` as a functional blue for links, focus, active navigation, and refresh controls only.
- `#eef0f3` as a cool secondary surface behind compact market facts.
- near-black `#0a0b0d` for high-contrast display numerals.
- 1.00–1.08 line-height for the single large market-price display.
- blue must never become decoration; charts use it only for the selected/current series.

Rejected from Coinbase:

- 56px pill CTAs and alternating marketing sections. The selected direction is
  a flat research publication, so structural controls stay rectangular.

### IBM Carbon — productive research density

Borrow these concrete values and actions:

- core palette relationship: `#161616` ink, `#ffffff` canvas, `#f4f4f4` layer, `#0f62fe` interaction.
- strict 8px spacing grid with 2px/4px only for micro-alignment.
- 0px radius for structural regions, buttons, tables, and disclosures.
- 48px standard interactive height and 16px component padding.
- flat background layering and 1px hairlines instead of card shadows.
- 12px technical captions with `0.32px` tracking; tabular mono numerals for prices, IV, delta, time, and counts.
- 32px desktop gutters, 16px mobile gutters, and a maximum content width near 1584px.

## 4. Color Roles

```css
--research-canvas: #f7f7f5;
--research-paper: #ffffff;
--research-layer: #f4f4f4;
--research-layer-hover: #e8e8e8;
--research-ink: #161616;
--research-ink-soft: #525252;
--research-muted: #6f6f6f;
--research-line: #c6c6c6;
--research-line-soft: #e0e0e0;
--research-blue: #0f62fe;
--research-blue-hover: #0043ce;
--research-blue-soft: #edf5ff;
--research-green: #198038;
--research-green-soft: #defbe6;
--research-amber: #8e5b00;
--research-amber-soft: #fff1c2;
--research-red: #da1e28;
--research-red-soft: #fff1f1;
```

Rules:

- Blue is interactive/informational, never ornamental.
- Green is reserved for verified market facts and passed evidence.
- Amber means review, partial evidence, ageing, or a failed sub-check inside an otherwise available report.
- Red is reserved for unavailable evidence, product `NO-GO`, and fail-closed boundaries.
- The main market brief remains clean warm white; texture opacity in reading areas stays below 3%.

## 5. Typography

- Chinese UI/body: `-apple-system`, `BlinkMacSystemFont`, `PingFang SC`,
  `Hiragino Sans GB`, `Microsoft YaHei`, `Noto Sans SC`, sans-serif.
- Latin and numeric research values: `Bahnschrift`, `Aptos`, `Cascadia Mono`,
  `SFMono-Regular`, `Consolas`, monospace fallbacks.
- Chinese body: at least 14px, weight 400, line-height 1.5–1.75.
- Chinese headings: weights 500/600 only. No italics and no negative tracking.
- Price: `clamp(3.25rem, 7vw, 6.5rem)`, line-height 0.92–1.0, tabular numerals.
- Section title: `clamp(1.75rem, 3vw, 3rem)`, line-height 1.05.
- Dense table: 12–14px with 1.4–1.5 line-height; numeric columns right-aligned.
- Technical label: 11–12px mono, 0.32–0.64px tracking, uppercase only when the raw contract token is uppercase.
- Chinese and Latin/number tokens use proper spaces: `数据年龄 4 秒`,
  `Deribit live`, `20 / 20 条有效报价`.

## 6. Layout And Components

### Global structure

- Sticky masthead at 64px, followed by a compact horizontal section rail.
- Desktop content width: up to 1584px with 32px gutters.
- Main market brief: asymmetrical `minmax(0, 1.15fr) minmax(360px, .85fr)`.
- Evidence zones use continuous planes, hairlines, and alternating white/gray layers; avoid nested cards.
- Major vertical rhythm: 48px. Internal rhythm: 8/16/24/32px.

### Masthead

- Brand left; current source/freshness and `READ-ONLY` boundary right.
- Primary action is `刷新数据`; raw JSON remains a text link.
- Refresh is a semantic button with 48px minimum height, busy state, press feedback, and brand focus ring.
- Do not display persistent “loaded successfully” text.

### Market brief

- Left: BTC underlying, DVOL, a one-sentence evidence-based market note, then four compact live metrics.
- Right: real eligible candidates from `candidate_research`; show contract, structure, expiry, delta/credit, and surface quality.
- If no candidates are eligible, show an honest empty state, not zero-value fake rows.
- `NO-GO` appears as a compact boundary note, never as the dominant page headline.

### Surface view

- Draw directly from `vol_surface_status.expiries[].surface_points`.
- Axes and series must label expiry, strike, IV unit, fit quality, and no-arbitrage state.
- Never label a surface “healthy” solely because fit quality passed; surface eligibility also requires the no-arbitrage check.
- The graphic must have a table/text fallback in the same section.

### Candidate table

- Rows come only from `candidate_research.*.eligible`.
- Display structure, expiry, legs/instrument, delta, premium or net credit, IV/surface quality, and evidence state.
- It is a research list, not a recommendation and not an order ticket.
- No row-level action button may imply execution.

### Limits and evidence

- Operator/external and system-owned items remain correctly separated.
- Limitations sit below the strategy workflow in a native collapsed `<details>`
  disclosure; a compact count and top-two summary remain visible.
- Every limitation keeps owner, next action, and raw reason code.
- Unknown ownership routes to manual triage; the UI never invents automation.

## 7. Interaction, States, And Accessibility

- Semantic HTML first; one `h1`, continuous heading order, skip link, labelled navigation and tables.
- All focusable elements use a 2px `#0f62fe` focus ring with a 2px offset.
- Buttons use 100–160ms press/hover feedback; never `transition: all`.
- Frequent navigation and keyboard actions do not animate.
- Async updates use `aria-live="polite"` and refresh exposes `aria-busy`.
- Numeric columns use tabular numerals and right alignment.
- Tables scroll inside labelled containers; they must not expand the page.
- Loading state mirrors the final market-brief geometry.
- Error state states what failed and offers a retry.
- Missing market data removes price, DVOL, surface, and candidate claims while preserving the research-only safety boundary.
- Evidence age updates every second and expires fail-closed at the report threshold.

## 8. Craft Density

At least these details ship:

1. warm-paper canvas with a sub-3% editorial grid line;
2. custom cobalt text selection;
3. branded focus-visible ring;
4. asymmetric market brief with one oversized live price;
5. mono folio metadata and tabular numbers;
6. hairline editorial dividers and alternating flat layers;
7. data-driven surface SVG with expiry series markers;
8. narrow branded scrollbar;
9. one short press/hover interaction on refresh and disclosures;
10. quiet footer note restating the no-trade boundary in plain language.

## 9. Responsive Behavior

- `>= 1200px`: market pulse and candidate brief share the hero; surface chart and evidence rail share a wide grid.
- `820–1199px`: market brief remains two-column if each side is at least 340px; lower sections stack.
- `< 820px`: market pulse, live metrics, candidates, surface, limitations, evidence chain stack in that order.
- `< 620px`: 16px page gutters, horizontally scrollable section rail, 44px minimum tap targets, tables contained with horizontal scroll.
- Large price uses `clamp()` and never forces page overflow.
- Surface visualization keeps a minimum logical width inside its own scroll region; page width remains fixed.

## 10. Motion Philosophy

- Motion intensity is 2/10: functional and rare.
- Hover/press: 100–160ms using `transform`, `background-color`, `color`, or `opacity`.
- Disclosure/modal transitions, if used, stay under 220ms and use `cubic-bezier(.23,1,.32,1)`.
- No `transition: all`, no `ease-in`, no UI animation above 300ms.
- Hover rules are guarded by `(hover: hover) and (pointer: fine)`.
- `prefers-reduced-motion` removes movement while preserving state colors.

## 11. Do's And Don'ts

Do:

- lead with current market facts and real research output;
- distinguish fit quality from no-arbitrage eligibility;
- keep source, freshness, and trust beside every headline claim;
- show limitations honestly but secondarily;
- retain all research-only and fail-closed boundaries.

Do not:

- use a blocker list as the product’s main value;
- present a fresh generation timestamp as proof of fresh market data;
- label internal implementation work as operator action;
- fabricate candidates, risk/reward rankings, or market commentary;
- add trade, order, broker, sizing, or “execute” controls;
- use decorative gradients, neon, glassmorphism, floating shadows, pill-heavy UI, or nested dashboard cards.

## 12. Chrome Companion Surface

The unpacked Chrome extension is a personal, local-engine companion for
`https://www.deribit.com/`. It is not a second dashboard and it must not imply
that proximity to an order screen changes the research-only boundary.

### Functional contract

Within three seconds the side panel must answer:

1. which Deribit instrument is currently in context, and whether the report
   actually covers it;
2. whether the report is current and trusted, including source and evidence
   age;
3. the current stance, structure, complete legs, and entry status;
4. the governing maximum-risk, profit-taking, time-exit, monitoring, and review
   rules.

The only primary actions are `同步当前合约` and `刷新研究`. Manual instrument
entry is a recovery path when Deribit DOM detection fails. `打开完整证据` is a
secondary link to the local Evidence Console.

### Composition

- The Chrome Side Panel is the primary extension UI. The content script only
  observes URL/title/limited semantic DOM and sends a typed context update; it
  does not mount a second research overlay.
- At 320–600px widths, the reading order is context → trust line → decision →
  legs → entry conditions → risk/exit → monitoring/review → local settings.
- Source, age, trust, full contract identifiers, and the `READ-ONLY` boundary
  are never hidden to save space.
- Long instrument names wrap. Tables and dense evidence remain in the full
  console instead of forcing horizontal page overflow.
- Current-context mismatch is explicit: a global BTC report must never be
  presented as analysis of an uncovered Deribit contract.

### Visual and interaction rules

- Reuse the bright institutional research-paper palette, hairlines, square
  structure, system Chinese stack, and tabular research numerals.
- Density is 8/10, visual variance 3/10, and motion 2/10. The panel is compact,
  not decorative.
- Loading, engine-offline, invalid-report, expired, unmatched-context, and
  empty-strategy states each state what happened and the next recovery action.
- Settings accept loopback HTTP origins only for the personal-use release.
- No order, trade, broker, contract-count, sizing, or execution control may be
  introduced. Risk templates remain explicitly uncalibrated research guidance.

## 13. P0 Pre-entry Decision Migration

This section is the canonical cleanup and migration plan for the evidence-first
pre-entry engine. It narrows the trusted domain to:

`Mandate → Market Evidence → Analysis → Opportunity → Strategy → Entry Admission`

The immutable endpoint is `EntryAdmissionDecision`. Orders, fills, positions,
exit management, settlement, reconciliation, and post-trade PnL remain outside
the trusted graph. Existing NO-GO modules that block those capabilities stay in
place and are not extended.

### Highest seam and ownership

- `AnalysisRun.evaluate(AnalysisRequest) -> AnalysisRecord` is the single public
  application seam. A fixed evaluation clock and content-addressed evidence,
  policy, model, and configuration references make each run replayable.
- `PolicyCatalog` is the sole owner of P0 trust, TTL, model, cost, liquidity,
  event, veto, and output-ceiling rules.
- Existing market-data, account, historical, surface, and risk modules remain
  evidence adapters or legacy diagnostic producers. Their current dictionaries
  are not silently promoted into trusted domain facts.
- Market trust observations, account facts, and pre-entry portfolio vetoes must
  be content-addressed evidence. A promoted E3 model additionally requires a
  bound trusted historical/OOS promotion artifact; legacy calibration flags
  cannot promote it. Promotion evidence is evaluated against the same fixed
  clock as market and account evidence; future, expired, or policy-stale
  artifacts are rejected.
- `research_report.v1` remains schema-compatible as a projection of one
  `AnalysisRecord`. New API/CLI result projections consume the same immutable
  record and never independently recompute admission conditions.
- Alerts consume domain events or completed admission decisions. They do not
  reimplement entry eligibility.

### Tracer-bullet sequence

1. Lock the existing `research_report.v1` behavior with regression tests.
2. Add immutable mandate, evidence, manifest, domain-event, and analysis-record
   contracts with deterministic canonical hashes.
3. Separate existing candidate screening from trusted `OpportunityRecord`.
   Current short-call and call-credit-spread screens are unpromoted E3 research
   anomalies only. Defined-risk spreads are the only trusted strategy plans;
   naked short calls remain typed rejected alternatives with unbounded loss.
4. Express strategies with typed legs and typed economic values. Unknown units,
   settlement, synchronization, or costs remain explicit and blocking.
5. Centralize the six admission outcomes and every condition's observed value,
   requirement, status, and stable reason code.
6. Project one record through API, CLI, report, and alert surfaces; retain
   compatibility fallbacks only where an existing external contract requires
   them.
7. Verify deterministic replay, fail-closed invariants, projection parity, and
   the absence of downstream execution capabilities before considering P1.

### Compatibility and deletion policy

- During P0, legacy strategy/portfolio fields may remain in
  `research_report.v1` for compatibility, but they are excluded from the trusted
  `AnalysisRecord`. A portfolio result can affect admission only through a
  hash-bound, current `pre_entry_risk_veto` evidence record whose payload is a
  typed `PreEntryRiskClaim`. Legacy `final_action` and exchange action words are
  never interpreted by the trusted graph; `PolicyCatalog` alone maps typed
  portfolio and exchange states to admission vetoes.
- Explicit-clock runs are immutable replay records. Implicit-clock HTTP cache
  entries expire at the shortest policy trust/evidence/decision deadline, so
  GET projection deduplication cannot preserve a stale admission result.
- Duplicate admission recomputation is deleted from new projections. Legacy
  helpers are labelled projection-only until their external consumers migrate;
  they are not copied into the new domain.
- Schema versions and reason codes are append-only within P0. A future breaking
  change requires a new schema version and an explicit projection migration.
- No new dependency or execution adapter is introduced.

### Deferred dependencies

- P1 owns canonical streaming/replay evidence, gap/resync, calls and puts,
  forward/funding/discount, pricing oracles, fair intervals, and E1/E2
  detectors.
- P2 owns real historical/OOS evidence, model promotion and rollback, read-only
  account evidence, venue margin simulation, and incremental portfolio veto.
- P3 execution remains expressly unauthorized.

## 14. Research Workbench Surface

The workbench is the mining-and-understanding surface. The Evidence Console
answers "is today's evidence trustworthy"; the workbench answers "which strike
on this chain is best priced, and why does it rank there".

### 14.1 Two claims, never merged

Every screen must keep these visually and verbally distinct:

- **Relative value** — how this strike is priced against its own smile.
  Available from the current chain alone.
- **Absolute expected value** — credit minus expected payout minus fees.
  Requires a realized-return distribution.

A candidate may carry the first and not the second. When
`ev_after_cost_usdc` is null the cell shows an explicit "no validated path
evidence" state. Never `0`, never blank, never an em dash that could read as
zero.

`expected_payout_usdc` is the seller's expected **cost**. Any label implying it
is profit is a defect.

### 14.2 Ranking is Pareto, not a score

The frontier is candidates no same-structure rival dominates. Within it, order
comes from the published `tie_break_order`. The UI must not present a single
blended number as "the score" — the product deliberately refuses to weight
incommensurable components.

Because of this, "why is it here" has two distinct answers, and the detail view
must show whichever applies:

- Dominated: names the rival and the axes it lost on.
- On the frontier: names the tie-break position.

### 14.3 Sample size

Confidence is read off `authoritative_sample_size` — independent,
non-overlapping windows. The similarity effective sample size that appears
inside path sampling is overlap-blind and typically an order of magnitude
larger; it must never be surfaced as confidence.

### 14.4 Filters narrow, they never promote

Screener controls may hide rows within a server-assigned `action`. No control
may move a candidate between `RESEARCH_ONLY` / `REVIEW` / `REJECT`. A rejected
candidate stays visibly rejected however the dials move, so "how close was it"
stays answerable without becoming "make it eligible".

### 14.5 Empty is not blocked

- **Blocked** — evidence itself is unavailable. Controls disabled, danger tone,
  no reset affordance, because there is nothing to reset your way out of.
- **Empty** — filters excluded everything. Muted tone, honest counts, and a
  reset control.

These must never be confusable at a glance.

### 14.6 Payoff curve

Hand-drawn SVG, per contract, no charting library. A short call renders its loss
side as an explicitly unbounded tail — never a finite floor, which would imply a
maximum loss that does not exist. A credit spread caps at width minus credit.
Mark spot and breakeven; label the vertical axis as per-contract P&L so it can
never be read as a position result.

## 15. Public Research Observatory

The public product is a daily, precomputed research edition. It is not a
public deployment of the local API. A controlled publisher evaluates one
captured snapshot, binds the resulting report and supporting artifacts by
hash, and emits a directory that can be served by an inert static host. The
public host has no Deribit client, credentials, account sidecar, analysis
process, order path, or sizing controls.

### 15.1 Narrative before tooling

The public navigation follows one fixed five-act question sequence:

1. Is volatility expensive now? — the VRP thermometer and its history.
2. Where is it expensive? — term structure and smile evidence.
3. Is selling it worth the risk? — relative value and absolute expected value,
   still kept separate.
4. Does the ranking predict anything? — preregistered signal validation,
   including an honest `no_detectable_edge` outcome.
5. Why trust it? — evidence classes, samples, sources, limitations, and the
   independently reproducible methodology.

Existing evidence, workbench, series, and signal components remain useful
implementation modules, but their module names are not the public information
architecture. The first viewport leads with the measured state and its
evidence, not an authorization warning.

### 15.2 Published time has two clocks

A published edition evaluates at the snapshot's `captured_at` instant so the
analysis remains reproducible. Reader-facing age always uses the real wall
clock. The report declares `captured_at`, `published_at`, `next_expected_at`,
and `stale_after`; the browser compares the wall clock with `stale_after`.
After 48 hours without a new daily edition, every research number is hidden
and the page becomes an explicit publication-stall state.

Only snapshot age is evaluated against the capture-bound clock. Missing rows,
invalid units, incomplete chains, unsupported evidence, and every other
quality gate retain their fail-closed behavior. A static health file cannot
change after publication, so it records `is_stale_at_publish` and
`stale_after`; monitors must compare their current time with the latter.

### 15.3 Publication is not execution

`research_publication` and `execution_authorization` are independent gates.
Publication can become `GO` only from explicit evidence for data quality, the
hash manifest, methodology, and disclaimer. Execution is a non-configurable
product boundary and remains `NO-GO` in every edition. No publish-time option,
environment variable, query parameter, or frontend control may change it.

The legacy `release_readiness` projection remains append-only compatible for
local consumers. Public surfaces lead with `research_publication`; they may
show the permanent execution boundary as supporting context, never as the
headline state of the site.

### 15.4 VRP headline contract

The headline is one measurement, not a weighted score:

`VRP(t) = BTC DVOL close(t) - RV30(t)`

Both values use percentage points. `RV30` is the sample standard deviation of
30 daily close-to-close log returns, annualized by `sqrt(365)`. The gauge is
the leave-current-out empirical percentile of the current VRP over the
configured trailing calendar-day window. The publisher discloses that window
as `window_days`; consumers must read it rather than assume a fixed duration.
Missing dates are neither interpolated nor forward-filled; they are excluded
and listed with the effective comparison sample. Thresholds are registered as
P90/P70/P30/P10 and may not change silently.

Every rendering keeps the limitation next to the number: positive VRP is not
proof of opportunity. It may be compensation for future volatility. Missing,
ambiguous-unit, or insufficient history produces an unavailable state and a
remediation command, never zero or a placeholder.

### 15.5 Public artifact and privacy boundary

The canonical public seams are static `/research/*`, `/api/v1/*.json`, legal
and methodology pages, and `.well-known/publish-manifest.json`. JSON is
canonical and content-hashed; identical inputs, publication time, and git SHA
must produce byte-identical trees. Hosting metadata supplies public CORS and
bounded cache headers without adding an application server.

Publication starts from public market inputs only. Private account snapshots,
positions, margin, sidecar authentication material, credentials, orders, and
sizing data are excluded recursively from the emitted tree. The public site
sets no cookies and loads no analytics, ad, tracker, font, or image request
from a third party. Until a repository and data license are explicitly chosen,
the generated legal pages must not imply a redistribution grant.
