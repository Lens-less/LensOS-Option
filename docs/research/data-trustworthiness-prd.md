# Data Trustworthiness PRD — 数据是否可信

Generated: 2026-07-10
Status: Ready for agent
Label: `ready-for-agent`
Program priority: **Analysis truth first** (alerts/trading later)
Related backlog: `docs/automation/next-backlog-analysis-alerts-trading.md` Wave 1 (NEXT-A01–A04) + Wave 1 settlement honesty (NEXT-A03)

## Problem Statement

As a research analyst using this crypto options short-call console, I need to know whether the numbers on screen are **economically true** and **evidence-backed**, not merely schema-valid JSON.

Today the local research toolchain is fail-closed for trading (research-only, paper/manual NO-GO), and many crash paths are hardened. But trust gaps remain:

1. **Live public validation is fragile.** DVOL and instrument metadata can be fetched, yet a healthy-day path to consistently `validated` market status is not productized. Operators often see blocked quality without a clear runbook for “what good looks like.”
2. **Product economics can still lie by unit.** Inverse (coin-settled) and linear (USDC-settled) products share report fields that look like USD/USDC credits and EV, while premiums and fees may not share the same unit. Settlement must never be inferred from quote currency.
3. **Historical honesty is uneven.** Live quality is strict about explicit settlement; historical normalization can still default settlement optimistically, so “ELIGIBLE” history is not the same bar as live trust.
4. **Live adapter shapes are under-tested offline.** DVOL and instruments paths rely heavily on mocks; real response drift can still surprise ops without a recorded contract harness.
5. **Trust is not summarized at the top of the report.** Analysts must hunt nested `data_status`, feed coverage, and provenance flags to answer: “Can I trust this run?”

Without a dedicated **Data Trustworthiness** program, alerts and trading remain built on sand: risk notifications may page on noise, and future paper unlock would size on wrong units.

## Solution

Ship a **Data Trustworthiness program** that makes every analysis run answer three questions in the shared research report:

1. **Is the market evidence valid for this timestamp?** (freshness, required feeds, settlement, quote quality)
2. **What product units am I looking at?** (inverse coin vs linear USDC; no silent conversion)
3. **Where did the data come from?** (live, fixture, replay; measured vs synthetic; explicit vs missing settlement)

The solution reuses existing seams rather than adding parallel data planes:

| Seam | Role |
| --- | --- |
| **S1 — Research report trust surface** | Top-level trust summary + reason codes on `research_report.v1` |
| **S2 — Public market snapshot quality** | Snapshot → normalize → quality gate → `data_status` |
| **S3 — Product unit / settlement identity** | Canonical product economics on quotes and candidate economics |
| **S4 — Historical eligibility honesty** | Explicit settlement / unit bar aligned with live (not full vendor download) |

Delivery is phased Goal issues (ISSUE-DT-*). Paper/manual and opportunity alerts stay **out of scope** for this PRD. Path libraries and multi-vendor corpora are deferred to a later program unless they block unit truth.

### Success signal (program)

An operator can capture a live or fixture snapshot, generate a report, and immediately see:

- a single **trust verdict** (trusted / degraded / untrusted) with reason codes;
- product **unit and settlement** on economic fields;
- no crash under malformed DVOL/instruments;
- historical rows failing closed when settlement is missing;
- offline harness proving adapter contract shapes.

## User Stories

1. As a research analyst, I want a single trust verdict on every report, so that I know whether to believe the numbers without reading every nested section.
2. As a research analyst, I want clear reason codes when trust is degraded, so that I can fix data inputs instead of guessing.
3. As a research analyst, I want live Deribit option chains to validate when the market is healthy, so that I can do daily analysis without only using fixtures.
4. As a research analyst, I want blocked live runs to explain which feed or field failed, so that I can distinguish sparse books from adapter bugs.
5. As a research analyst, I want DVOL to appear as a first-class required feed when available, so that vol context is not missing by accident.
6. As a research analyst, I want instrument settlement currency from the exchange registry, so that inverse vs linear is not guessed.
7. As a research analyst, I want missing settlement to block quality, so that I never treat unknown product economics as valid.
8. As a research analyst, I want quote currency and settlement currency kept distinct, so that I do not confuse premium unit with settlement unit.
9. As a research analyst, I want every candidate credit and EV field to declare its unit, so that I do not compare coin premiums to USDC EV.
10. As a research analyst, I want inverse multi-contract fees and payoffs to stay unit-correct, so that multi-lot research is not silently wrong.
11. As a research analyst, I want linear USDC products labeled and computed in USDC, so that linear books do not inherit inverse rules.
12. As a research analyst, I want surface and candidate filters to respect product units, so that bid/credit thresholds are economically meaningful.
13. As a research analyst, I want historical rows without explicit settlement to be ineligible, so that history is not looser than live.
14. As a research analyst, I want historical fixtures that claim settlement to match premium scale, so that no-arb and credits are not unit theater.
15. As a research analyst, I want snapshot capture with provenance (source, time, feed list), so that I can replay yesterday’s trust verdict.
16. As a research analyst, I want offline report generation from a saved snapshot, so that trust analysis is reproducible.
17. As an operator, I want a live validation runbook, so that I know instrument limits and expected outcomes on a normal day.
18. As an operator, I want exit codes that distinguish blocked quality from hard errors, so that schedulers can page correctly.
19. As an operator, I want a live-optional contract harness, so that CI stays offline while still covering real response shapes.
20. As an operator, I want malformed DVOL rows to fail closed, so that live ingestion never crashes the process.
21. As an operator, I want partial ticker failures to be visible in trust codes, so that “validated” cannot hide large fetch error sets when policy forbids it.
22. As an operator, I want rate-limit and transient network classes in adapter events, so that retryable issues are not treated as permanent schema failure.
23. As a research analyst, I want feed coverage to list missing required feeds, so that incomplete public graphs cannot look fully trusted.
24. As a research analyst, I want stale vol index to block trust, so that I do not use yesterday’s DVOL as live context.
25. As a research analyst, I want trust verdict to stay untrusted when market data is missing, so that empty runs are obvious.
26. As a research analyst, I want trust verdict degraded when only synthetic regime inputs are present, so that I do not over-read regime caps (report-level honesty only; regime model rewrite out of scope).
27. As a research analyst, I want CLI `ingestion-status` to surface the same trust reasons as the full report, so that quick checks match deep checks.
28. As a research analyst, I want API `/market/chain` and full report trust fields to agree, so that dashboard and CLI do not diverge.
29. As a dashboard user, I want a visible trust banner (trusted/degraded/untrusted), so that I do not misread blocked runs as normal.
30. As a dashboard user, I want to open a live-backed report via safe query params only, so that I can inspect trust without SSRF risks.
31. As a test engineer, I want fixture cases for missing settlement, wrong unit labels, and malformed DVOL, so that regressions are caught offline.
32. As a test engineer, I want golden replay fixtures from real public responses (redacted), so that schema drift is detectable.
33. As a product owner, I want paper/manual to remain NO-GO, so that better data trust does not accidentally unlock trading.
34. As a product owner, I want opportunity alerts to remain disabled by default, so that untrusted path EV cannot page as opportunity.
35. As a product owner, I want this program scoped without full vendor corpus, so that we can finish trust foundations before multi-month data engineering.
36. As a compliance-minded operator, I want no private credentials in trust tests, so that CI never needs secrets for public trust work.
37. As a research analyst, I want explicit `product_type` on positions-like research candidates, so that short-call research states inverse vs linear clearly.
38. As a research analyst, I want conversion to USD shadow PnL labeled as shadow, so that I never treat shadow as settlement currency cash.
39. As a research analyst, I want backtest baseline inputs to refuse unknown settlement, so that historical replays do not invent linear USDC economics.
40. As a research analyst, I want quarantine reason codes stable and greppable, so that automated quality monitors can key off them.
41. As an operator, I want artifact paths for snapshots and trust reports by date, so that audits can retrieve past verdicts.
42. As a research analyst, I want documentation of unit conventions in the PRD/runbook, so that new contributors do not invent scales.
43. As a research analyst, I want trust summary to include feed graph completeness flags, so that “validated quotes” is not confused with “full PRD feed graph.”
44. As a research analyst, I want partial public graph still able to validate **quote quality** when required feeds for that verdict are present, so that order-book absence does not block all analysis if product policy allows quote-level trust.
45. As a product owner, I want each issue slice to state whether it changes trust verdict rules, so that agents do not silently tighten or loosen gates.
46. As a research analyst, I want EV scanner outputs to inherit unit metadata from candidates, so that ranking columns are interpretable.
47. As a research analyst, I want portfolio shadow caps (if shown) to inherit unit metadata, so that research sizing shadows are not unit-ambiguous (sizing still non-actionable).
48. As an operator, I want live smoke paths that do not self-reject allowlisted defaults, so that smoke verifies trust ingestion.
49. As a research analyst, I want instrument parse failures quarantined, so that one bad name cannot void the whole trust pipeline by crash.
50. As a research analyst, I want duplicate strike/instrument issues to remain fail-closed, so that surface trust is not claimed on corrupt chains.
51. As a research analyst, I want a checklist mapping NEXT-A01–A04 to shipped acceptance, so that the backlog and PRD stay aligned.
52. As a future trading risk manager, I want unit truth completed before any paper unlock, so that paper recon is not built on wrong economics.
53. As a research analyst, I want trust degraded (not trusted) when fetch_errors are present under the project’s fail-closed policy, so that partial live pulls cannot look fully healthy.
54. As a research analyst, I want to re-run trust evaluation on the same snapshot at a fixed `generated_at`, so that results are deterministic for review.
55. As a documentation reader, I want non-goals clearly separating this PRD from alerts noise work and trading DoD, so that scope does not sprawl.

## Implementation Decisions

### Program boundary

1. This PRD implements **data trust foundations** for analysis: live validation productization, product unit truth, settlement honesty, and offline live-contract harness.
2. This PRD does **not** implement vendor historical downloaders, path-risk libraries, calibration promotion, private account auth, paper unlock, or opportunity alerts.
3. Trading posture remains: research-only effective mode; paper/manual NO-GO; no live order adapter.

### Seam S1 — Research report trust surface

4. Extend the shared research report with a single **trust summary** object (name can be `data_trust` or equivalent) including at least: verdict (`trusted` | `degraded` | `untrusted`), reason codes, feed completeness flag, unit_policy_status, settlement_policy_status, source class (`live` | `fixture` | `replay` | `missing`).
5. Verdict mapping (normative intent):
   - `untrusted`: market missing/blocked, hard unit policy fail, or process would previously crash (always fail closed).
   - `degraded`: market validated for quotes but incomplete optional graph, synthetic regime provenance, or non-blocking warnings.
   - `trusted`: required public feeds for quote analysis present, settlement explicit on used quotes, unit policy pass, quality gate pass.
6. Trust summary is derived from existing builders; it must not invent a second quality engine. Prefer pure projection from `data_status`, feed coverage, and unit/settlement checks.
7. Mode gate, blocked trade outputs, and release readiness NO-GO rules stay intact unless they currently depend on false “validated” economic labels—those must be tightened, not loosened.

### Seam S2 — Public market snapshot quality

8. Keep snapshot → normalize → evaluate quality → `data_status` as the only public market quality path.
9. Live fetch continues to attach DVOL and instrument metadata fail-closed; malformed DVOL/instruments become fetch/adapter errors, never process crashes.
10. Required-feed and fetch-error policies already in quality evaluation remain; this PRD documents and tests them as trust inputs rather than inventing parallel flags.
11. Deliver an operator runbook: capture snapshot, report, interpret trust verdict, instrument-limit ladder, exit codes.
12. Optional artifact convention under dated directories for snapshots and trust reports (documentation + CLI guidance; no mandatory cloud storage).

### Seam S3 — Product unit / settlement identity

13. Introduce a shared product-economics vocabulary used by market quotes, candidates, EV economics, and backtest entries: at minimum `product_type` (`inverse` | `linear` | `unknown`), `settlement_currency`, `premium_unit` (`coin` | `usdc` | `unknown`), and whether USD fields are `shadow` only.
14. Settlement currency is accepted only from **explicit venue fields** (summary/instrument registry). Never infer from quote currency.
15. Inverse economics: coin premium/payoff/fees; USD only as labeled shadow. Linear economics: USDC (or declared quote) premium/payoff/fees.
16. EV and candidate credit fields must carry unit metadata; multi-contract inverse fee composition must remain per-unit-correct (prior fee fix preserved).
17. Baseline backtest refuses unknown settlement or mislabeled units instead of assuming linear USDC.
18. Surface filters that compare money thresholds must be unit-aware or skipped with reason codes when unit is unknown.

### Seam S4 — Historical eligibility honesty

19. Historical normalization requires explicit settlement for ELIGIBLE training/backtest eligibility; missing settlement → quarantine / ineligible with stable codes.
20. Do not implement multi-vendor download in this PRD; improve honesty of the existing fixture/normalization path and contracts so later vendor adapters plug into the same bar.
21. Payoff replay remains required when delivery fields claim settlement outcomes; skip-as-pass without delivery facts is not allowed for ELIGIBLE claims.

### Issue slicing (implementation sequence)

Vertical tracer bullets (to-issues, 2026-07-10) — see `issues/ISSUE-DT-000` and children:

22. **ISSUE-DT-001** — Trust summary missing → untrusted (S1).
23. **ISSUE-DT-002** — Trust summary validated fixture → trusted/degraded (S1+S2).
24. **ISSUE-DT-003** — Trust banner + CLI/API parity (S1 UI/API).
25. **ISSUE-DT-004** — Inverse unit truth quote→candidate→EV (S3).
26. **ISSUE-DT-005** — Linear units + backtest refuse unknown (S3).
27. **ISSUE-DT-006** — Historical missing settlement ineligible (S4).
28. **ISSUE-DT-007** — Fixture settlement/premium scale alignment (S4).
29. **ISSUE-DT-008** — Malformed DVOL fail-closed golden (S2).
30. **ISSUE-DT-009** — Instruments settlement + public harness pack (S2).
31. **ISSUE-DT-010** — Operator live runbook + dated artifacts (ops).
32. Each slice ships independently with tests; later slices must not regress earlier trust verdict semantics.

### API / CLI / dashboard

27. CLI report and ingestion-status expose trust summary; `--fail-on-blocked` remains quality blocked; consider aligning exit semantics with `untrusted` without breaking existing 10/11 codes without docs.
28. HTTP API continues research-only; no new unauthenticated remote capabilities; fixture sandbox and base URL allowlist remain.
29. Dashboard shows trust banner from report trust summary; no new trade controls.

### Relationship to prior DQR PRD

30. Prior data-quality remediation PRD established fail-closed local/replay slices. This PRD is the **next program**: analysis-facing trust productization and unit economics, not a re-run of DQR-001–012 acceptance theater.
31. Reuse DQR vocabulary (reason codes, feed coverage, quarantine) where it still matches reality.

## Testing Decisions

### What makes a good test here

1. Prefer **external behavior** at seams: report trust summary, `data_status`, eligibility decisions, CLI exit codes, and fail-closed non-crash under bad live payloads.
2. Do not assert private implementation helpers or exact log strings unless they are part of the contract.
3. Offline by default; live network only behind explicit opt-in and never required for CI green.
4. Use highest seam possible: prefer full `generate_research_report` / CLI over micro-testing pure internals when the behavior is user-visible.
5. Golden fixtures for public JSON-RPC shapes; mutation cases for null timestamps, missing settlement, partial instruments.

### Modules / surfaces under test

6. Market snapshot quality and live fetch fail-closed behavior (S2).
7. Product unit metadata propagation into candidates/EV/backtest (S3).
8. Historical eligibility when settlement missing (S4).
9. Research report trust summary projection (S1).
10. CLI/API agreement on trust fields; dashboard only if a stable string/selector contract exists.

### Prior art in this repo

11. `tests/test_data_quality_remediation.py` — fail-closed market quality, feed coverage, settlement missing.
12. `tests/test_alerts_and_ops.py` — DVOL/instruments mocks, malformed DVOL non-crash, no settlement inference.
13. `tests/test_research_report_contract.py` — mode gate and nested validation.
14. `tests/test_pnl_evidence_report.py` — inverse/linear fee and settlement evidence.
15. `tests/fixtures/public_deribit_replay.json` and historical vendor fixtures — extend rather than invent parallel fixture ecosystems.

### Required new coverage (acceptance for the program)

16. Trust summary present on every report; untrusted when market missing.
17. Malformed DVOL null timestamp → structured fetch error, process returns snapshot.
18. Instruments without settlement_currency do not populate fake settlement; quality blocks.
19. Candidate/EV unit metadata tests for inverse vs linear fixtures.
20. Historical missing settlement → not ELIGIBLE.
21. Runbook commands documented and smoke-tested offline with fixtures.

## Out of Scope

1. Enabling paper or manual trading modes.
2. Live order placement or any broker adapter.
3. Opportunity / candidate “good trade” alerts.
4. Full multi-vendor historical corpus download (Tardis/Amberdata/etc.).
5. Production path-risk library and clearing `PLACEHOLDER_PATH_RISK` for EV.
6. Calibration model promotion and OOS training pipelines.
7. Private account live credentials integration (beyond existing replay contracts).
8. Order book / funding / events full feed productization (may be listed as follow-on; not required to close this PRD).
9. Rewriting vol surface model (SABR/SVI) or scoring models.
10. Multi-channel alert product (Telegram/email) and alert noise redesign (separate alerts program).
11. Dashboard visual redesign beyond trust banner wiring.
12. Remote multi-tenant API auth productization.

## Further Notes

### Recommended Goal issue order

```text
DT-001 → DT-002 → DT-010
      ↘ DT-003 ↗
DT-001 → DT-004 → DT-005
               ↘ DT-006 → DT-007
DT-008 → DT-009   (parallel track)
```

### Mapping to NEXT backlog

| NEXT ID | ISSUE-DT slices |
| --- | --- |
| NEXT-A01 | DT-001, DT-002, DT-003, DT-010 |
| NEXT-A02 | DT-004, DT-005 |
| NEXT-A03 | DT-006, DT-007 |
| NEXT-A04 | DT-008, DT-009 |

### Acceptance board update expectation

When DT issues complete, update `docs/automation/goal-board.md` and mark corresponding NEXT-A0x items done in `next-backlog-analysis-alerts-trading.md`. Paper/manual remains NO-GO.

### Open product policy (resolved in this PRD)

- **Quote-level trust vs full feed graph:** `trusted` may be achievable with required feeds for quote analysis (option chain, ticker, vol_index, explicit settlement on used quotes) even if order_book/funding/events remain not implemented; full graph completeness is reported separately and may force `degraded` but not always `untrusted`.
- **Synthetic regime:** does not by itself force `untrusted` market data; may contribute to `degraded` overall trust if included in trust summary inputs.

### Ready-for-agent

This PRD is labeled **ready-for-agent**. Implementation should proceed issue-by-issue (DT-001 first unless the user reassigns), with tests at S1–S4 seams and no trading unlock.
