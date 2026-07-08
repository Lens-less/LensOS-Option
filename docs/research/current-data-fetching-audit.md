# Current Data Fetching Audit

## Baseline

- Source of truth reread: `docs/automation/goal-board.md` and `docs/automation/project-acceptance-report.md`.
- Current baseline: GO for the local deterministic research toolchain, NO-GO for paper/manual mode.
- Repo-wide verification in the latest implementation run: `python -m pytest -q` passed 121 tests and 25 subtests.
- Latest live public Deribit recheck: `ingestion-status --live-deribit --instrument-limit 5 --compact` and `--instrument-limit 40 --compact` returned blocked quality reports without uncaught exceptions.

## Data-Flow Map

- CLI/API call `generate_research_report`, optionally with a snapshot fixture, live public Deribit option-chain fetch, or replayed account scenario.
- Missing market data becomes `MISSING_VALIDATED_MARKET_DATA`; missing account data becomes `MISSING_ACCOUNT_API_SNAPSHOT` and `NO_TRADE`.
- Market data path: `market_data.py` fetches Deribit book summary by currency and per-instrument ticker, then normalizes quotes and applies freshness/spread/IV/depth gates.
- Historical path: `historical.py` fixture rows become canonical quotes and quarantine reports; `backtest.py` consumes eligible quotes or fixed-window fixtures.
- Surface/candidate path: `surface.py` fits a simple IV-vs-log-moneyness model, applies no-arb checks, and builds research-only candidate tables.
- Account/margin path: `account_risk.py` uses replay scenarios for account summary, positions, and simulation status.
- EV/path/calibration/paper path: deterministic report builders keep candidates research-only and release readiness NO-GO.

## Reproduction Evidence

| Command | Result | Evidence |
| --- | --- | --- |
| `python -m pytest -q` | pass | 121 tests and 25 subtests passed |
| `python -m crypto_options_report.cli recommend --generated-at 2026-07-07T00:01:30Z --compact` | pass | Returned `recommendation_projection.v1`, `action=RESEARCH_ONLY`, `trade_recommendation_allowed=false` |
| `python -m crypto_options_report.cli calibrate --generated-at 2026-07-07T00:01:30Z --compact` | pass | Returned `walk_forward_calibration_report.v1`, `status=validated`, `paper_manual_release_gated=true` |
| `python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 5 --compact` | pass, blocked quality | Reached Deribit but returned `MARKET_DATA_QUALITY_FAIL` with insufficient valid quotes |
| `python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 40 --compact` | pass, blocked quality | Reached Deribit and returned `MARKET_DATA_QUALITY_FAIL`; no `ZeroDivisionError` |

## Problems

### DQA-001 - Historical live public Deribit duplicate-strike crash path is now fail-closed

- Status: historical finding; local/replay fix accepted, latest live recheck did not reproduce the crash
- Original severity: P0
- Area: market data / vol surface
- Historical symptom/evidence: an earlier `python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 40 --compact` run exited 1 with `ZeroDivisionError` in `crypto_options_report/surface.py` `_evaluate_no_arb`.
- Latest evidence: the 2026-07-08 live recheck for instrument limits 5 and 40 returned blocked `MARKET_DATA_QUALITY_FAIL` reports without uncaught exceptions.
- Root cause: Live summary ordering can include duplicate strikes across call/put or repeated rows, while `_evaluate_no_arb` assumes strictly increasing unique strikes.
- Impact if regressed: public live market-data smoke could crash instead of returning `RESEARCH_ONLY_NO_TRADE`.
- Current guardrail: keep duplicate/repeated-row regression coverage and continue treating malformed or sparse public data as blocked research-only quality.
- Blocks paper/manual mode: not by itself after the local/replay fix; broader missing production feeds, private adapters, promoted models, and paper reconciliation still block paper/manual mode.

### DQA-002 - Private account, positions, and portfolio simulation are replay scenarios only

- Severity: P0
- Area: account/margin
- Symptom/evidence: `crypto_options_report/account_risk.py` defines synthetic green/yellow/red/stale/simulation/auth scenarios and source endpoint strings, but no authenticated Deribit client.
- Root cause: ISSUE-004 intentionally implemented no-trade replay evidence rather than live private adapters.
- Impact: Margin, NAV/MM, positions, and post-trade margin cannot be trusted against real account responses.
- Proposed fix: Add private Deribit account, positions, and simulation adapter interfaces with recorded response fixtures and auth/rate-limit fail-closed handling.
- Required tests/external verification: Golden private-response fixtures, auth failure, stale response, rate limit, simulation unavailable, and schema-drift tests.
- Blocks paper/manual mode: yes

### DQA-003 - Historical vendor normalization has no real vendor downloader or corpus

- Severity: P0
- Area: historical data
- Symptom/evidence: `crypto_options_report/historical.py` and CLI require local fixture rows; tests use `tests/fixtures/historical_vendor` only.
- Root cause: The accepted slice proves canonicalization/reconciliation logic, not ingestion from Tardis, Amberdata, CDD, or self-collected stores.
- Impact: Schema drift, missing quote history, OI/volume units, delivery price mismatches, and vendor disagreements remain unknown.
- Proposed fix: Build vendor adapters that write raw snapshots, canonical rows, and quarantine artifacts with vendor/version provenance.
- Required tests/external verification: Golden multi-vendor samples, schema-drift cases, cross-vendor overlap, and payoff replay against official delivery prices.
- Blocks paper/manual mode: yes

### DQA-004 - Current public data fetch lacks full PRD data coverage

- Severity: P1
- Area: market data completeness
- Symptom/evidence: `market_data.py` fetches book summary plus ticker, while PRD requires option chain, order book, vol index, funding/basis, index/spot, account, positions, and events.
- Root cause: ISSUE-002 scoped a narrow option-chain quality tracer, not the full production feed graph.
- Impact: Regime, EV, liquidity, event, and path-risk features can be stale, missing, or fixture-only.
- Proposed fix: Add collectors and validation gates for order book depth, volatility index, futures/basis/funding, index/spot, and event calendar.
- Required tests/external verification: Per-feed mocked responses, stale/missing feed fail-closed tests, and cross-feed timestamp alignment checks.
- Blocks paper/manual mode: yes

### DQA-005 - Calibration report is deterministic tracer, not promoted model

- Severity: P1
- Area: calibration/scoring
- Symptom/evidence: `python -m crypto_options_report.cli calibrate --generated-at 2026-07-07T00:01:30Z --compact` returns `walk_forward_calibration_report.v1`, but top-level `calibration_status` in `contract.py` stays missing.
- Root cause: The repo exposes a walk-forward report surface but has no model registry/promotion gate feeding candidate sizing.
- Impact: Score, size, and paper/manual proposals must remain blocked even when the calibration sub-report says validated.
- Proposed fix: Create model artifact registry, training-data lineage, promotion checks, and explicit linkage from promoted model to report gate.
- Required tests/external verification: Unpromoted model blocks; promoted fixture enables research candidate scoring only after leakage, calibration, and backtest checks pass.
- Blocks paper/manual mode: yes

### DQA-006 - Backtest fixed-window reports can hide aggregate ineligibility

- Severity: P1
- Area: backtest eligibility
- Symptom/evidence: `backtest.py` fixed-window path records deterministic fixture windows and unavailable metrics; subagent audit found aggregate eligibility can be optimistic around windowed inputs.
- Root cause: Windowed fixtures are clean and short by design, while production history needs row-level eligibility propagation into aggregate metrics.
- Impact: A bad row or missing path may not be visible enough in summary acceptance evidence.
- Proposed fix: Propagate per-row and per-window reconciliation failures into aggregate backtest eligibility and report exclusion tables.
- Required tests/external verification: Ineligible entry row, missing path instrument, no eligible candidates, margin breach, and forced-close fixture cases.
- Blocks paper/manual mode: yes

### DQA-007 - Path-risk and EV inputs are toy fixtures

- Severity: P1
- Area: path risk / EV
- Symptom/evidence: `tests/fixtures/path_risk_distribution_fixture.json` and `ev_scanner.py` use deterministic paths and research-only candidate status.
- Root cause: ISSUE-009/010 prove report contracts and kill conditions, not calibrated production path libraries.
- Impact: P_Touch, CVaR, stress loss, and EV cannot yet be trusted for real candidate promotion.
- Proposed fix: Build validated historical path library with ESS checks, stress-mixture floors, and realized forecast backtests.
- Required tests/external verification: Slow-bull acute rally windows, sparse-regime fallback, terminal-vs-path touch comparison, and realized-outcome calibration tests.
- Blocks paper/manual mode: yes

### DQA-008 - Paper proposal ledger has no persisted 30-60 day reconciliation

- Severity: P0
- Area: paper/manual workflow
- Symptom/evidence: `paper_ledger.py` keeps `automatic_live_submission_possible=false`; acceptance report says real 30-60 day paper reconciliation is not satisfied.
- Root cause: The slice intentionally built a tracer and manual-review shape, not an operational ledger with fills.
- Impact: Paper/manual mode cannot be enabled under PRD Definition of Done.
- Proposed fix: Persist proposals, reviews, simulated fills, exits, fees, slippage, and reconciliation outcomes over a paper-trading window.
- Required tests/external verification: Idempotent state transitions, blocked-state no proposal, recorded paper fill reconciliation, fee/slippage mismatch, and audit trail tests.
- Blocks paper/manual mode: yes
