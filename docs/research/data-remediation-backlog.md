# Data Remediation Backlog

Dependency order: keep live public fail-closed behavior guarded, then complete public/private adapters, then expand historical/path/calibration evidence, then run paper reconciliation.

Latest status: ISSUE-DQR-001 through ISSUE-DQR-012 are accepted for local/replay evidence. Paper/manual mode remains NO-GO because external production evidence is still missing.

## DQR-001

- ID: DQR-001
- Title: Harden live Deribit surface quality fail-closed path
- Severity: P0
- Area: market data / surface
- Status: local/replay complete; keep as regression guardrail
- Evidence: historical audit reproduced `ZeroDivisionError` in `crypto_options_report/surface.py` `_evaluate_no_arb`; latest 2026-07-08 live recheck for instrument limits 5 and 40 returned blocked `MARKET_DATA_QUALITY_FAIL` reports without exception.
- Root cause: Live summary ordering can include duplicate strikes across call/put or repeated rows, while `_evaluate_no_arb` assumes strictly increasing unique strikes.
- Proposed change: keep duplicate/repeated-row fixture coverage and fail-closed quality reporting; do not treat blocked live quality as paper/manual readiness.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-002

- ID: DQR-002
- Title: Add complete public market-data collectors and freshness gates
- Severity: P1
- Area: market data
- Evidence: `market_data.py` fetches book summary plus ticker, while PRD requires option chain, order book, vol index, funding/basis, index/spot, account, positions, and events.
- Root cause: ISSUE-002 scoped a narrow option-chain quality tracer, not the full production feed graph.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-003

- ID: DQR-003
- Title: Add live Deribit mocked contract tests and retry/rate-limit handling
- Severity: P1
- Area: testing / adapters
- Evidence: historical duplicate-strike crash evidence is now fail-closed in the latest live recheck; `market_data.py` still fetches book summary plus ticker while the PRD requires option chain, order book, vol index, funding/basis, index/spot, account, positions, and events.
- Root cause: Live summary ordering can include duplicate strikes across call/put or repeated rows, while `_evaluate_no_arb` assumes strictly increasing unique strikes.; ISSUE-002 scoped a narrow option-chain quality tracer, not the full production feed graph.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-004

- ID: DQR-004
- Title: Create canonical instrument metadata and settlement-currency registry
- Severity: P1
- Area: schema / contract math
- Evidence: `crypto_options_report/historical.py` and CLI require local fixture rows; tests use `tests/fixtures/historical_vendor` only.; `market_data.py` fetches book summary plus ticker, while PRD requires option chain, order book, vol index, funding/basis, index/spot, account, positions, and events.
- Root cause: The accepted slice proves canonicalization/reconciliation logic, not ingestion from Tardis, Amberdata, CDD, or self-collected stores.; ISSUE-002 scoped a narrow option-chain quality tracer, not the full production feed graph.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-005

- ID: DQR-005
- Title: Implement historical vendor adapters and raw-data provenance
- Severity: P0
- Area: historical data
- Evidence: `crypto_options_report/historical.py` and CLI require local fixture rows; tests use `tests/fixtures/historical_vendor` only.
- Root cause: The accepted slice proves canonicalization/reconciliation logic, not ingestion from Tardis, Amberdata, CDD, or self-collected stores.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-006

- ID: DQR-006
- Title: Expand reconciliation corpus and quarantine reporting
- Severity: P1
- Area: historical data quality
- Evidence: `crypto_options_report/historical.py` and CLI require local fixture rows; tests use `tests/fixtures/historical_vendor` only.; `backtest.py` fixed-window path records deterministic fixture windows and unavailable metrics; subagent audit found aggregate eligibility can be optimistic around windowed inputs.
- Root cause: The accepted slice proves canonicalization/reconciliation logic, not ingestion from Tardis, Amberdata, CDD, or self-collected stores.; Windowed fixtures are clean and short by design, while production history needs row-level eligibility propagation into aggregate metrics.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-007

- ID: DQR-007
- Title: Implement private account/positions/simulation adapters
- Severity: P0
- Area: account/margin
- Evidence: `crypto_options_report/account_risk.py` defines synthetic green/yellow/red/stale/simulation/auth scenarios and source endpoint strings, but no authenticated Deribit client.
- Root cause: ISSUE-004 intentionally implemented no-trade replay evidence rather than live private adapters.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-008

- ID: DQR-008
- Title: Add account and margin real-response replay suite
- Severity: P1
- Area: account/margin tests
- Evidence: `crypto_options_report/account_risk.py` defines synthetic green/yellow/red/stale/simulation/auth scenarios and source endpoint strings, but no authenticated Deribit client.
- Root cause: ISSUE-004 intentionally implemented no-trade replay evidence rather than live private adapters.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-009

- ID: DQR-009
- Title: Upgrade vol-surface fitting and no-arb validation
- Severity: P1
- Area: vol surface
- Evidence: historical `instrument-limit 40` live Deribit run exposed a duplicate-strike/no-arb crash; latest live recheck returns blocked `MARKET_DATA_QUALITY_FAIL` instead of an exception.
- Root cause: Live summary ordering can include duplicate strikes across call/put or repeated rows, while `_evaluate_no_arb` assumes strictly increasing unique strikes.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-010

- ID: DQR-010
- Title: Build validated path-risk historical library
- Severity: P1
- Area: path risk
- Evidence: `tests/fixtures/path_risk_distribution_fixture.json` and `ev_scanner.py` use deterministic paths and research-only candidate status.
- Root cause: ISSUE-009/010 prove report contracts and kill conditions, not calibrated production path libraries.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-011

- ID: DQR-011
- Title: Add calibration model registry and promotion gate
- Severity: P1
- Area: calibration/scoring
- Evidence: `python -m crypto_options_report.cli calibrate --generated-at 2026-07-07T00:01:30Z --compact` returns `walk_forward_calibration_report.v1`, but top-level `calibration_status` in `contract.py` stays missing.
- Root cause: The repo exposes a walk-forward report surface but has no model registry/promotion gate feeding candidate sizing.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## DQR-012

- ID: DQR-012
- Title: Persist paper ledger and run 30-60 day reconciliation
- Severity: P0
- Area: paper/manual workflow
- Evidence: `paper_ledger.py` keeps `automatic_live_submission_possible=false`; acceptance report says real 30-60 day paper reconciliation is not satisfied.
- Root cause: The slice intentionally built a tracer and manual-review shape, not an operational ledger with fills.
- Proposed change: implement the narrowest production adapter, validator, or gate needed to make this surface fail closed with recorded evidence.
- Files likely affected: `crypto_options_report/`, `tests/fixtures/`, `tests/`, and docs under `docs/automation/`.
- Tests to add or update: see linked evidence item tests in `current-data-fetching-audit.md`.
- External dependency: Deribit public/private API, vendor historical data, or paper-fill logs depending on area.
- Acceptance criteria: new failing fixture or mocked live-response case passes; report remains `RESEARCH_ONLY` or `NO_TRADE` unless all prerequisite gates are satisfied; evidence is recorded in handoff/acceptance docs.
- Blocks paper/manual mode: yes

## Suggested New Goal Issue Slices

1. ISSUE-DQR-001: Live public Deribit fail-closed hardening and mocked contract tests.
2. ISSUE-DQR-002: Historical vendor adapter and canonical schema corpus.
3. ISSUE-DQR-003: Private Deribit account/positions/simulation adapters with auth-safe fixtures.
4. ISSUE-DQR-004: Vol surface/no-arb and path-risk production evidence upgrade.
5. ISSUE-DQR-005: Paper ledger persistence and 30-60 day reconciliation runbook.
