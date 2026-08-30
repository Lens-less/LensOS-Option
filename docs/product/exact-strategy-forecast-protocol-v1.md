# Exact Strategy Forecast Protocol v1

Status: `FROZEN SUCCESSOR PROTOCOL`
Frozen: `2026-08-30T09:00:00+08:00`
Product boundary: `RESEARCH_ONLY / NO_TRADE / NO_AUTO_EXECUTION`

This protocol governs one claim only: whether the product may expose a
calibrated 95% win-rate interval for one exact strategy card. It does not
promote the ranking axis and it does not replace aligned historical replay.

## Claim separation

- Ranking promotion answers whether a registered ordering signal carries
  predictive information.
- Strategy history answers whether one exact strategy family produced validated
  holdout outcomes after costs.
- Exact-strategy forecast answers whether the current card may show a calibrated
  win-rate interval for one exact scope.

Passing one claim never auto-promotes the other two.

## Canonical scope

Every forecast artifact is bound to all of these fields:

- `underlying`
- `structure`
- `direction`
- `dte.min` / `dte.max`
- `entry_cost_basis`
- `exit_basis`

An artifact may not be reused outside that scope. A scope mismatch retires the
forecast immediately and old probabilities must be nulled.

## Sequence

The sequence is strict:

1. Freeze the model, calibrator, scope, thresholds, and protocol while the
   final holdout is still sealed.
2. Record `holdout_status_at_freeze = sealed`.
3. Open the final holdout exactly once for the evaluation run.
4. Persist the one-time access record and evaluation hashes.
5. Promote only if every forecast gate passes.

Promotion happens after audited holdout access, not before it.

## Promotion gates

An exact-strategy forecast may become `CALIBRATED` only if all of these are
true:

1. The model and calibrator are pre-registered and frozen in this successor
   protocol.
2. The preregistration records that the holdout was sealed at freeze.
3. Holdout access is recorded exactly once with:
   `accessed_at`, `command_hash`, `input_hash`, `result_hash`,
   `access_count = 1`, `rerun_count = 0`, and `invalidated = false`.
4. The holdout access record also confirms `previously_viewed = false` and
   `tuned_after_access = false`.
5. Walk-forward validation is purged and embargoed by expiry-cohort
   independence rules.
6. There are at least 8 independent future cohorts and 100 observations.
7. The sample covers at least 2 regimes and no single regime contributes more
   than 60% of cohorts.
8. Out-of-sample Brier score beats the unconditional base-rate model.
9. Reliability passes with no systematic inversion or severe distortion.
10. The displayed 95% win-rate interval passes a decision-width gate.
11. The aligned exact-strategy history claim is `VALIDATED`.
12. The matching risk gate still passes for the same exact strategy.

Fixture, demo, placeholder, tracer, reused holdout, previously viewed holdout,
or post-access tuned evidence may not produce a calibrated artifact.

## Artifact

The promotion output is one content-addressed record:

`exact_strategy_forecast_artifact.v1`

It records:

- `promoted_at`
- `expires_at`
- exact strategy `scope`
- preregistration and frozen protocol references
- one-time `holdout_access` evidence
- frozen model and calibrator ids plus digests
- walk-forward, OOS, Brier, reliability, interval, history, and risk evidence
- input fingerprints for dataset, config, feature schema, and unit semantics
- lineage references for ranking, history, and risk artifacts

`artifact_id` is required on every external artifact and must equal the
SHA-256 of the canonical JSON payload with the `artifact_id` field omitted.
Missing or mismatched IDs are invalid and may not be treated as calibrated
evidence.

## Lifecycle states

- `UNAVAILABLE`: production default, no calibrated forecast exists
- `SCREENING_ONLY`: may inform backend ranking, but never shows win-rate numbers
- `CALIBRATED`: may expose the 95% win-rate interval and confidence
- `RETIRED`: artifact once existed, but one or more retirement gates fired

Only `CALIBRATED` may emit `win_rate_low` and `win_rate_high`.

Keeping `CALIBRATED` also requires complete current evidence at projection
time:

- a current live input fingerprint with dataset, config, feature-schema,
  unit-semantics, and continuity fields
- a current verified lineage record whose history/risk/ranking artifact IDs
  still match the promoted artifact
- a current OOS monitor that explicitly passes adverse, directional, and
  base-rate quality gates

If any current evidence is missing, incomplete, non-live, mismatched, or fails
its gate, the product must retire the forecast and clear the old interval.

The runtime carrier is `strategy_forecast_runtime_evidence.v1`. It contains the
immutable promoted artifact plus separately refreshed `current_input_fingerprint`,
`current_lineage`, and `current_oos_monitor` blocks. The promoted artifact may
not copy its own frozen values into those current blocks. Operators provide the
envelope with repeatable `--strategy-forecast-runtime-evidence <path>` flags to
the report/API/publication surfaces; its canonical content is bound into the
`AnalysisRun` identity and cache key.

## Retirement gates

Any of these must retire the forecast and null out old probabilities:

- artifact age exceeds 90 days
- current evidence is missing or incomplete
- dataset hash changes
- config hash changes
- feature schema version changes
- unit semantics change
- strategy scope mismatch
- lineage verification fails or lineage IDs drift
- continuity gap exceeds 3 days
- 3 consecutive new adverse out-of-sample cohorts accumulate
- current OOS directional quality fails
- current OOS base-rate quality fails

Retirement is fail-closed. The product must not keep showing the old interval as
"low confidence" or downgrade it to a heuristic probability.

## Operational note

As of `2026-08-30`, the production-safe default remains `UNAVAILABLE`. This
protocol does not authorize fabricating promotion evidence, inventing future
cohorts, reusing previously viewed holdouts, or tuning after holdout access.
