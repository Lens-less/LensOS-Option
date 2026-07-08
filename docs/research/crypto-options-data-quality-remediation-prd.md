# Crypto Options Data Quality Remediation PRD

Generated: 2026-07-08
Status: Draft PRD for implementation planning
Scope: crypto options short-call system data-quality remediation and readiness gates

## Problem Statement

The crypto options short-call system has reached local research-toolchain acceptance, but it is not ready for paper/manual trading enablement. The current accepted baseline proves deterministic report contracts, research-only recommendations, calibration surfaces, CLI/API/dashboard projections, and a blocked paper proposal ledger. It does not yet prove that live public data, authenticated private account data, historical vendor data, volatility surfaces, path-risk inputs, calibration promotion, or paper reconciliation are production-grade.

The central product problem is evidence quality. Today the system can produce useful local research outputs, but several critical data paths are fixture-only, deterministic tracers, or narrow adapters. A live Deribit public ingestion smoke also exposed a fail-closed defect: a larger instrument fetch can crash surface quality evaluation instead of producing a blocked research-only report. That means the next product step should not be enabling trading modes; it should be turning the current research toolchain into an evidence-backed data platform that fails closed under real exchange/vendor responses.

The existing remediation backlog identifies twelve data-quality items. They are all useful, but not all should be treated as equal trading-safety blockers. Some items are hard readiness gates for paper/manual mode, while others improve research validity or model quality after the foundational data surfaces exist. This PRD converts the audit findings, open-source research, subagent reviews, and adversarial-review attempt into a dependency-ordered product plan.

## Solution

Build an evidence-driven data-quality remediation program with two explicit value lines:

1. Research-quality value line: make local and historical research outputs more trustworthy without changing the system's trading posture.
2. Paper/manual readiness value line: keep all trade-enabling gates closed until real public/private/vendor/paper evidence satisfies external Definition of Done criteria.

The product should continue to expose `RESEARCH_ONLY`, `NO_TRADE`, and `NO-GO` states until readiness evidence proves otherwise. The near-term solution is not a broad model rewrite. The first deliverable is a narrow fail-closed fix for live public Deribit surface quality. After that, the platform should add mocked/live-response contract tests, canonical instrument metadata, feed-by-feed public collectors, raw historical provenance, private account replay boundaries, and paper ledger reconciliation.

The recommended execution model is a sequence of small Goal issue slices, each with fixture/replay evidence, external-response assumptions, acceptance criteria, and an explicit statement about whether paper/manual mode remains blocked.

## Goals

1. Prevent live public data defects from crashing CLI/report surfaces.
2. Preserve the current safe trading posture: no automatic live trading, no paper/manual enablement, no weakening of research-only gates.
3. Convert public market, historical vendor, private account, surface, path-risk, calibration, and paper-ledger concerns into verifiable data contracts.
4. Split broad backlog entries into dependency-ordered implementation slices that can be completed and reviewed independently.
5. Make release readiness evidence-driven instead of relying on static or fixture-only readiness fields.
6. Create a testing strategy that proves fail-closed behavior at the external report, CLI, and replay-contract seams.

## Non-Goals

1. This PRD does not enable live trading.
2. This PRD does not enable paper/manual trading mode.
3. This PRD does not add a new execution broker or live-order adapter.
4. This PRD does not copy code from third-party open-source repositories.
5. This PRD does not rewrite pricing, scoring, dashboard, or portfolio modules before data evidence is improved.
6. This PRD does not require all public/vendor/private feeds to land in a single broad implementation pass.

## Product Phases

### Phase 0: Live Public Fail-Closed Hardening

Primary backlog item: DQR-001.

Fix the live Deribit surface quality crash path first. The product requirement is simple: malformed, duplicated, sparse, stale, or otherwise invalid live public option rows must result in a blocked research-only quality report, not an uncaught exception. This phase should be a narrow production hardening slice, not a volatility-model redesign.

Acceptance signal:

- A live-like duplicate-strike or repeated-row response is covered by a regression fixture.
- The CLI/report returns a blocked status instead of crashing.
- Existing `RESEARCH_ONLY`, `NO_TRADE`, and release `NO-GO` semantics remain intact.

### Phase 1: Public Adapter Contract Harness And Metadata Registry

Primary backlog items: DQR-003 and DQR-004.

Add a contract test harness for Deribit public responses before expanding the public feed graph. The harness must cover successful responses, empty responses, duplicate instruments, partial ticker data, rate limiting, transient network failure, schema drift, and timestamp staleness.

At the same time, define canonical instrument metadata for BTC options at minimum, including instrument naming, expiry, strike, option side, settlement currency, underlying/index mapping, and timestamp semantics. Public collectors, historical adapters, surface validation, and private account positions should all depend on the same metadata vocabulary.

Acceptance signal:

- Public adapter tests prove retry, timeout, stale, empty, partial, and malformed response behavior.
- Instrument identity and settlement fields are canonicalized before downstream analytics.
- Invalid metadata blocks downstream readiness instead of being silently inferred.

### Phase 2: Feed-By-Feed Public Market Coverage

Primary backlog item: DQR-002.

Expand public market data coverage one feed at a time. The desired feed graph includes option chain, ticker/book summary, order book where required, volatility index, funding/basis, index/spot, and market events. Each feed must define freshness, required fields, optional fields, schema validation, and fail-closed status codes before it is considered production evidence.

Acceptance signal:

- Each new public feed has independent fixtures and live-response replay tests.
- Missing or stale feed data degrades readiness explicitly.
- Cross-feed timestamp and instrument alignment are reported.
- Feed rollout does not depend on private account credentials.

### Phase 3: Historical Vendor Provenance And Reconciliation

Primary backlog items: DQR-005 and DQR-006.

Implement historical vendor adapters and raw-data provenance before using history to justify model promotion or paper/manual readiness. Start with one vendor/source and a minimal canonical schema. Capture raw payload metadata, ingestion timestamp, source version, normalization version, and row-level quarantine reasons.

After raw provenance exists, expand the reconciliation corpus and aggregate eligibility reporting. Production history must make invalid rows visible and must propagate row-level ineligibility into aggregate backtest, calibration, and path-risk readiness.

Acceptance signal:

- At least one vendor/source can produce raw and normalized datasets with provenance.
- Quarantined rows include machine-readable reasons.
- Reconciliation reports distinguish clean rows, missing rows, stale rows, schema failures, mark/mid drift, and no-arb failures.
- Backtest or calibration consumers cannot silently treat incomplete corpora as fully eligible.

### Phase 4: Surface, Path-Risk, And Calibration Evidence

Primary backlog items: DQR-009, DQR-010, and DQR-011.

After live fail-closed behavior and data contracts exist, upgrade volatility surface validation, path-risk historical libraries, and calibration model promotion. These are research-quality and model-readiness upgrades; they should not be used to open paper/manual mode until public/private/vendor evidence is already in place.

Acceptance signal:

- Surface validation reports no-arb failures without crashing.
- Path-risk libraries are built from validated historical inputs, not toy deterministic fixtures.
- Calibration promotion uses a registry or equivalent gate with explicit model version, training window, validation window, leakage checks, and out-of-sample evidence.
- Candidate sizing or recommendation surfaces cannot consume unpromoted models as if they were production-ready.

### Phase 5: Private Account, Margin, And Replay Evidence

Primary backlog items: DQR-007 and DQR-008.

Implement private account, positions, and simulation adapters behind auth-safe boundaries. No real credentials should be committed or required for normal test runs. The product must support recorded real-response replay fixtures that prove account balance, margin, position, stale-auth, stale-data, partial-position, and schema-drift behavior.

Acceptance signal:

- Private adapter boundaries can be tested with recorded sanitized responses.
- Auth failure and stale account data force `NO_TRADE`.
- Position and margin evidence is traceable to source response timestamps.
- Private account work does not create a live-order submission path.

### Phase 6: Paper Ledger Persistence And Reconciliation

Primary backlog item: DQR-012.

Only after public, historical, calibration, and private account gates are evidence-backed should the paper ledger become an operational reconciliation lane. The paper ledger must persist proposals, manual approvals, simulated fills, observed fills if available, fees, slippage assumptions, timestamps, state transitions, and reconciliation outcomes over a 30-60 day window.

Acceptance signal:

- Paper ledger state is persistent and idempotent.
- Reconciliation compares expected vs observed execution price, fees, latency, and rejected/expired actions.
- Paper/manual mode remains hidden or blocked until the full external Definition of Done is satisfied.
- Automatic live submission remains impossible.

## Dependency Order

1. DQR-001 must land first because live public ingestion can currently crash instead of failing closed.
2. DQR-003 should follow DQR-001 so live-response behavior is locked by contract tests before public coverage expands.
3. DQR-004 should land before broad public, historical, surface, private, and paper work because all of those lanes need canonical instrument identity.
4. DQR-002 should proceed feed by feed after DQR-003 and DQR-004.
5. A narrow DQR-005 starter slice can run in parallel once DQR-004 defines metadata, but DQR-006 should wait for real raw provenance.
6. DQR-009 should wait until DQR-001, DQR-002, and DQR-003 provide reliable surface inputs.
7. DQR-010 should wait for historical provenance and reconciliation evidence.
8. DQR-011 should wait for DQR-010 and should not promote deterministic tracers as production models.
9. DQR-007 should wait for public contract and metadata boundaries, then DQR-008 should lock real-response replay behavior.
10. DQR-012 should be last because paper reconciliation depends on public, historical, private, and calibration evidence.

Do not merge these pairs into single broad issues:

- DQR-001 and DQR-009.
- DQR-002 and all DQR-003 work.
- DQR-005 and DQR-006.
- DQR-007 and DQR-012.
- DQR-010 and DQR-011.

## User Stories

1. As an options researcher, I want live public ingestion failures to produce a blocked research report so that one malformed exchange response does not break my local research workflow.
2. As an options researcher, I want all invalid market-data states to be explicit so that I can distinguish "no opportunity" from "no trustworthy data."
3. As an options researcher, I want historical datasets to carry raw provenance so that I can trace every normalized row back to its source.
4. As an options researcher, I want quarantined historical rows to include reasons so that I can judge whether a backtest window is representative.
5. As an options researcher, I want path-risk libraries built from validated history so that acute-rally and CVaR estimates are not based on toy fixtures.
6. As a data engineer, I want public Deribit response contracts for success, empty, duplicate, stale, and rate-limited responses so that adapter behavior is stable across real API conditions.
7. As a data engineer, I want canonical instrument metadata so that public feeds, historical data, surface analytics, and private positions use the same identity model.
8. As a data engineer, I want public feeds added one at a time so that each feed has clear freshness, schema, and readiness semantics.
9. As a data engineer, I want raw and normalized historical data stored with versioned provenance so that future schema drift can be audited.
10. As a data engineer, I want row-level quarantine to flow into aggregate eligibility so that downstream reports cannot overstate data quality.
11. As a risk manager, I want private account and margin evidence to remain fail-closed so that missing account data cannot be treated as safe.
12. As a risk manager, I want stale account data to force `NO_TRADE` so that old margin snapshots cannot authorize recommendations.
13. As a risk manager, I want authenticated account fixtures sanitized and replayable so that safety logic can be tested without exposing credentials.
14. As a risk manager, I want paper/manual readiness gates to stay closed until external evidence is complete so that research outputs do not imply operational approval.
15. As a model developer, I want volatility surface no-arb failures to be reported rather than thrown as exceptions so that model diagnostics are usable.
16. As a model developer, I want surface upgrades separated from crash hardening so that bug fixes do not become hidden model rewrites.
17. As a model developer, I want calibration promotion to require model version, training window, validation window, and leakage checks so that promoted scores have audit evidence.
18. As a model developer, I want unpromoted models to remain research-only so that deterministic tracers cannot drive production sizing.
19. As a QA engineer, I want fixture and replay tests at CLI/report seams so that acceptance criteria match the surfaces users actually run.
20. As a QA engineer, I want every DQR issue to include at least one failing fixture before the fix so that regressions are locked.
21. As a QA engineer, I want live-like response replay for public and private adapters so that tests cover real schema shapes without requiring network or credentials.
22. As an operator, I want release readiness to show concrete missing evidence so that I know why paper/manual mode remains blocked.
23. As an operator, I want no automatic live submission path to exist so that implementation work cannot accidentally create live trading.
24. As an operator, I want paper ledger state to be persistent and idempotent so that manual review can survive restarts and repeated runs.
25. As an operator, I want paper reconciliation over 30-60 days so that fees, slippage, expiry, rejection, and execution price assumptions are tested before manual enablement.
26. As a reviewer, I want each issue slice to state whether it blocks paper/manual mode so that backlog priority is not confused with safety criticality.
27. As a reviewer, I want broad backlog items split into narrow dependencies so that changes are reviewable and reversible.
28. As a reviewer, I want external open-source ideas used as inspiration only so that license risk stays low.
29. As a product owner, I want research-only improvements prioritized separately from mode enablement so that the roadmap can deliver value without weakening safety.
30. As a product owner, I want a clear final readiness story so that stakeholders understand why local research GO is different from paper/manual GO.
31. As a future worker, I want each Goal issue to start from the latest board and handoff evidence so that concurrent edits do not invalidate my implementation plan.
32. As a future worker, I want acceptance docs updated after each slice so that the source of truth remains current.
33. As a future worker, I want small, dependency-aware issue slices so that I can complete one slice without needing to understand the entire trading system.
34. As an adversarial reviewer, I want a narrow review bundle with claims to validate so that external review can challenge the actual plan without choking on unrelated dirty worktree state.
35. As a security reviewer, I want all private/live integrations treated as untrusted until replay, failure, and fail-closed behavior is proven so that readiness cannot be inferred from API availability alone.
36. As a maintainer, I want no new dependencies unless justified by a specific data adapter or test harness need so that the system remains easy to audit.

## Implementation Decisions

1. Keep the system research-only until evidence proves readiness. The current safe default is a product requirement, not an incidental implementation detail.
2. Treat live exchange, private account, vendor history, and paper-fill integrations as untrusted until they pass fixture, replay, and fail-closed tests.
3. Implement DQR-001 as a narrow fail-closed hardening slice. Do not combine it with volatility-model upgrades.
4. Add public adapter contract tests before expanding the public feed graph.
5. Use a canonical metadata registry before connecting public, historical, private, surface, or paper-ledger data paths.
6. Expand public feeds incrementally. Each feed must own its required fields, freshness rules, and readiness contribution.
7. Start historical vendor work with one source and one canonical schema before broadening to multiple vendors.
8. Store raw provenance and normalization metadata before relying on historical data for model promotion.
9. Make quarantine reasons machine-readable and propagate them into aggregate eligibility.
10. Keep DQR-006 as a follow-up to DQR-005 because reconciliation quality depends on real provenance.
11. Keep private account adapters separate from paper ledger persistence. Account evidence is a prerequisite, not the paper workflow itself.
12. Keep calibration model promotion separate from path-risk dataset construction. A clean dataset must precede a promoted model.
13. Keep release readiness evidence-driven. Static `NO-GO` fields are safe, but future `GO` states must be justified by external evidence.
14. Use third-party repositories for architecture patterns, schemas, test ideas, and adapter lessons only. Do not import third-party code without a separate dependency/license review.
15. Prefer small Goal issues that can be verified independently and leave board/handoff evidence when completed.

## Testing Decisions

1. Use external behavior tests as the primary acceptance seam: CLI/report JSON, readiness status, and fail-closed recommendation output.
2. Add a DQR-001 regression fixture that reproduces duplicate or repeated live option rows and proves the report blocks instead of crashing.
3. Add public adapter contract tests for rate limit, retry, timeout, empty response, partial response, stale timestamp, duplicate instrument, and schema drift.
4. Add canonical metadata tests for option side, strike, expiry, settlement currency, index/underlying mapping, and timestamp normalization.
5. Add one test group per public feed so a stale or missing feed cannot be hidden by a healthy feed elsewhere.
6. Add historical vendor golden-sample tests covering raw payload capture, normalized rows, provenance fields, and schema versioning.
7. Add quarantine tests for missing bid/ask, invalid mark/mid, stale timestamp, metadata mismatch, no-arb failure, and incomplete window eligibility.
8. Add private account replay tests using sanitized real-response shapes for balance, margin, positions, stale auth, stale data, and malformed data.
9. Add explicit tests that private account failures force `NO_TRADE` and never create a live-order submission path.
10. Add volatility surface tests that distinguish crash hardening from model-quality validation.
11. Add path-risk tests that verify no lookahead, sufficient sample evidence, stress-window coverage, and eligibility propagation.
12. Add calibration registry tests for model version, training/validation windows, leakage checks, promotion status, and blocked unpromoted model usage.
13. Add paper ledger tests for persistence, idempotency, manual approval state transitions, fees, slippage, expiry, rejection, and reconciliation output.
14. Keep existing full repo tests passing after each slice.
15. Record verification commands and evidence in acceptance or handoff docs for every implemented DQR issue.

## Out Of Scope

1. Live trading or live order placement.
2. Paper/manual mode enablement before external Definition of Done is satisfied.
3. A broad all-at-once ingestion rewrite.
4. A full volatility, optimizer, or scoring-model redesign before data contracts are reliable.
5. Importing open-source project code without dependency and license review.
6. Storing real credentials in fixtures, docs, commits, or local acceptance artifacts.
7. Treating a single passing live smoke as sufficient production evidence.
8. Treating deterministic tracers as promoted models.

## Suggested Goal Issue Slices

1. ISSUE-DQR-001: Live public Deribit fail-closed hardening and public response regression fixtures.
2. ISSUE-DQR-002: Public Deribit contract harness for retry, stale, partial, duplicate, and schema-drift responses.
3. ISSUE-DQR-003: Canonical BTC option instrument metadata and settlement-currency registry.
4. ISSUE-DQR-004: Feed-by-feed public market-data coverage with freshness and cross-feed alignment gates.
5. ISSUE-DQR-005: Single-source historical vendor raw provenance baseline.
6. ISSUE-DQR-006: Historical reconciliation corpus expansion and quarantine reporting.
7. ISSUE-DQR-007: Surface validation upgrade after fail-closed public data contracts.
8. ISSUE-DQR-008: Validated path-risk historical library.
9. ISSUE-DQR-009: Calibration model registry and promotion gate.
10. ISSUE-DQR-010: Private account, positions, and margin adapter boundary.
11. ISSUE-DQR-011: Private account real-response replay suite.
12. ISSUE-DQR-012: Persistent paper ledger and 30-60 day reconciliation runbook.

## Further Notes

The current acceptance posture should be worded carefully: the local research toolchain is accepted, but paper/manual mode is still intentionally blocked. "Safety acceptance pass" applies to the implemented research-only toolchain, not to live or paper trading readiness.

The current backlog marks many items as paper/manual blockers. For implementation planning, distinguish hard operational blockers from research-quality upgrades. Public fail-closed behavior, public feed coverage, canonical metadata, historical provenance, private account evidence, account replay, calibration promotion, and paper reconciliation are direct readiness blockers. Reconciliation corpus breadth, surface quality, and path-risk depth are important evidence/model-quality upgrades that should not be used as a substitute for operational safety gates.

The prior Claude adversarial-review attempt did not produce a valid target review result because the Windows companion hit a worktree-size/process-spawn limit. For a future adversarial review, prepare a narrow clean review bundle containing this PRD, the data audit, the remediation backlog, and a claims-to-validate file.

No remote issue tracker is assumed. This PRD is designed to be converted into local Goal issue slices or tracker issues later.
