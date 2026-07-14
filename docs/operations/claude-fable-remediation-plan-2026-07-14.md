# Claude Fable Review Remediation Plan

## Baseline and intent

- Fixed point: `f53aae1c6e0c6501c06150789790590cc7570056` (`main`, clean, one commit ahead of `origin/main`).
- Baseline verification: `344 passed, 1 skipped, 160 subtests passed`.
- Goal: remove false confidence, correct financial/unit bugs, narrow exposed runtime risk, and reduce process debris without weakening the research-only safety boundary or deleting active audit truth.

## Non-negotiable invariants

1. The package contains no live-order adapter or order-submission transport.
2. `research_only`, `NO_TRADE`, and `NO-GO` remain externally visible and cannot be relaxed by fixture, query parameter, UI state, or a local boolean.
3. Missing, stale, malformed, unit-unknown, or self-attested evidence fails closed.
4. Financial values are never compared across currencies or units without explicit conversion.
5. Fixture/tracer constants never appear as measured, calibrated, ranked, or production-ready evidence.
6. The current North Star job contract remains asynchronous (`202`, bounded queue, idempotency, immutable result); this is an explicit requirement, not optional ceremony.
7. Content-addressed V2 cutover evidence under `docs/automation/archive/options-platform-v1/` and `docs/automation/evidence-store/` remains byte-for-byte intact.

## Public seams selected for regression tests

The remediation is test-first at these externally observable boundaries:

- Pricing and surface: `build_vol_surface_and_candidate_research`.
- Path risk: `build_path_risk_distribution_report`.
- Historical reconciliation: `build_historical_reconciliation_report`.
- Regime: `build_regime_permission_state`.
- Account risk: `build_account_status`.
- Report truth: `generate_research_report` and `validate_report_contract`.
- Market trust: file-backed `load_snapshot_fixture` plus `build_market_data_status`.
- Runtime: HTTP `/readyz`, `/backtest/run`, and `/backtest/jobs/{id}`.
- Sidecars/webhooks: `fetch_deribit_account_snapshot`, public snapshot refresh, and `deliver_webhook` with mocked transports.
- Packaging/deployment: wheel entry points and the container default command.

## Phase 1 - correctness and security (completed)

| Review item | Disposition | Required change and proof |
| --- | --- | --- |
| A1 | Fix | Make the configured no-arbitrage tolerance authoritative while keeping duplicate/invalid strikes hard failures. Test below/above threshold. |
| A2 | Fix | Canonicalize IV to explicit percent-point units before surface fitting/Greeks; retain unit provenance. Test fraction/percent-point equivalence and ambiguous values fail closed. |
| A3 | Fix | Scale log returns, reject non-finite or `<= -100%` source returns, and prove every simulated price stays finite and positive. |
| A4 | Fix | Reuse inverse payoff logic and compare using a tolerance expressed in the payoff currency. Add inverse good/bad reconciliation rows. |
| A5 | Fix remainder | Remove IV-level-as-percentile fallback. Only explicit trustworthy ranks or empirical rolling history may produce permission caps; otherwise collect/block. |
| A6 | Fix | Missing market/account age is a kill condition, never zero-age. |
| A7 | Fix | Reject timezone-naive market timestamps instead of applying host-local timezone. |
| A8 | Fix/honest output | Never derive collected premium from absolute PnL and never invent hedge/roll/protective-spread values. Unknown evidence remains unavailable. |
| A9 | Fix | Malformed/non-finite account numerics return structured `malformed` + `NO_TRADE`, not an uncaught conversion error. |
| A10 | Fix | Map job-store `OSError`/sharing violations to structured retryable HTTP responses. |
| A11 | Fix | A pre-admission executor failure must not permanently poison an idempotency key. The same key/body can be admitted after recovery; conflicting bodies still return `409`. |
| A12 | Partial finding, harden | Add bounded Windows replace retry and expose snapshot/store/queue/model dependency readiness with reason codes. Keep liveness separate. |
| B1 | Fix | Send auth parameters in a JSON POST body and private HTTP tokens in `Authorization: Bearer`; assert secrets/tokens never enter URLs or logs. |
| B2 | Fix | Remove baked-in remote permission and `0.0.0.0` default. Remote container binding becomes an explicit deployment choice behind the documented proxy controls. |
| B3 | Fix | Sign timestamp + nonce + body, expose timestamp/nonce headers, and reject redirects rather than following them. |
| B4 | Fix | Ignore snapshot-embedded trust claims. The snapshot sidecar writes a separate bound trust-state file; only loader-attached sidecar state may promote research trust. |

## Phase 2 - evidence honesty (completed)

1. Replace calibration literals and prose-only leakage claims with an explicit `not_implemented`/`unavailable` report plus policy references. No score, correlation, VIF, percentile, or leakage pass is emitted without a real ledger/fold artifact.
2. Remove hardcoded EV/path templates from ranking. When validated path evidence is absent, return `unavailable` with no ranked candidates and no plausible EV/CVaR/p-touch values.
3. Remove fabricated position-management economics. State transitions may use observed inputs only; roll/hedge/protective evidence is `not_available` until supplied.
4. Stop claiming static CLI/API/dashboard entries are runtime-probed. Use one canonical interface registry where practical; otherwise label declarations as unverified rather than `available`.
5. Collapse the constant production observation gate into one explicit manual/external-evidence status instead of thirteen pseudo-computed booleans.
6. Remove the current paper proposal/approval machinery from the executable report path. Gate 7 is future, separately authorized scope; current output is a small unsupported/NO-GO status.

## Phase 3 - structural simplification (completed)

1. Keep the async job API required by the North Star PRD, but remove permanent-failure idempotency state and redundant compatibility branches that have no published consumer.
2. Make `/readyz` cheap and dependency-oriented; do not build the full research report just to answer readiness.
3. Stop parsing the same fixture twice per report request by carrying one loaded snapshot through status and report construction.
4. Emit one canonical key for new schemas; accept legacy aliases only at the input boundary where compatibility is proven necessary.
5. Narrow forbidden output keys to genuinely executable/order-directive concepts. Generic domain words such as strike, expiry, side, symbol, and quantity are not security controls.
6. Reduce self-validation to stable public and safety invariants. Component tests own detailed builder shape; production code does not mirror every builder branch line-for-line.
7. Consolidate duplicate timestamp/unique-code/log helpers only where this shortens the current diff without creating a new dependency layer.

## Phase 4 - repository hygiene (completed)

1. Remove tracked `.workflow/ultracode/` run products after verifying no runtime, package, CI, or immutable audit fence reads them; add the directory to `.gitignore`.
2. Keep `.workflow/verify-dashboard-cdp.mjs`, runtime sidecar wrappers, current issues, the generated/current Goal board, coordination V2 tests, and immutable V2 evidence because they still have explicit consumers or governance/security roles.
3. Do not bulk-delete `docs/automation/`, `issues/`, `tools/`, or all coordination tests. The review's "zero risk" claim is false for the current tree.
4. Update README/runbook/CI references so no retained document points at deleted runtime artifacts as required current evidence.

## Verification and review gate

Each vertical slice runs its targeted test first red then green. Before completion:

1. `python -m compileall -q crypto_options_report tools`
2. `python -m pytest -q`
3. `python -m crypto_options_report.api --smoke`
4. wheel build/install and all console-entry `--help`/smoke checks
5. container build plus secure-default/liveness/readiness checks
6. `git diff --check`
7. two-axis review against this plan and repository standards, followed by fixes and a second verification pass
8. Lore-protocol commit on the current branch

## Explicitly rejected recommendations

- **Synchronous backtest POST:** rejected because the North Star PRD explicitly requires async `202`, bounded queue, idempotency, job lifecycle, and immutable results.
- **Delete the entire job service:** rejected for the same reason; its defects are repaired at the public contract rather than deleting a required seam.
- **Delete all automation/issues/tools first:** rejected because the current Goal projection, published issue contract, CI, SECURITY policy, and immutable migration fence still reference parts of those trees.
- **Treat data staleness as process death:** rejected as a conflation of liveness and readiness. `/health` stays process-only; `/readyz` gains explicit dependency readiness and returns a reasoned non-ready result when production dependencies are not usable.
