# Strategy Brief Historical Protocols v1

Status: `FROZEN — FUTURE HOLDOUT PENDING`
Frozen at: `2026-08-30T20:00:00+08:00`
Product boundary: `RESEARCH_ONLY / NO_TRADE`

This document freezes the strategy-card history protocol for the three
structure families introduced by the actionable strategy brief:

- `BULL_PUT_CREDIT_SPREAD`
- `BEAR_CALL_CREDIT_SPREAD`
- `IRON_CONDOR`

It does not open or infer any final holdout result. Existing workspace data is
development-only. No existing sample may be relabelled as untouched future
holdout evidence.

## Shared frozen rules

- Structure and direction are fixed per family.
- DTE band is fixed at `7-35` calendar days.
- Selection is deterministic and uses a same-structure comparator.
- Entry uses executable prices only:
  - every short leg enters at `bid - 1 adverse tick`;
  - every long leg enters at `ask + 1 adverse tick`.
- Fees and official expiry settlement are included.
- Exit basis is fixed at `hold_to_expiry`.
- Duplicate rows, overlapping label intervals, stale/invalid quotes, and
  incomplete settlement are excluded rather than repaired.
- Walk-forward metadata uses purged expanding expiry-cohort folds with a
  `35`-day embargo.
- Every artifact must bind protocol, code, configuration, cohort ledger, and
  result payload through a content-addressed hash.
- Any `evaluated` holdout must also carry a one-time audited access receipt:
  pre-frozen protocol, one input hash, one result hash, one command hash,
  `access_count = 1`, `rerun_count = 0`, `previously_viewed = false`, and
  `tuned_after = false`.
- Bootstrap uses whole expiry cohorts, `10,000` resamples, and seed `20260812`.
- Cost stress multiplies all modeled fees and adverse-tick/slippage costs by
  `1.5x`.
- `no_trade` and a deterministic same-structure comparator are both mandatory.

## Family boundaries

### `BEAR_CALL_CREDIT_SPREAD`

- Direction: bearish defined-risk call credit spread.
- Legacy relationship: this family may reference the already frozen
  `CALL_CREDIT_SPREAD` boundary in
  `docs/automation/strategy-eval-spec.md`, because that legacy scope is the
  same bear-call direction.
- This reference is one-way only. It must not be borrowed by bull-put or
  iron-condor histories.

### `BULL_PUT_CREDIT_SPREAD`

- Direction: bullish defined-risk put credit spread.
- Selection: short put closest to absolute delta `0.10`, then the nearest lower
  listed long put, with deterministic tie-breaks.
- This family needs its own aligned replay, comparator, and future holdout.
  Bear-call validation cannot be reused.

### `IRON_CONDOR`

- Direction: neutral/range-bound defined-risk short-vol structure.
- Selection: choose the short put and short call independently by absolute delta
  `0.10` inside the same expiry, then attach the nearest protective wings with
  deterministic tie-breaks.
- This family needs its own aligned replay, comparator, and future holdout.
  Bear-call validation cannot be reused.

## Validation gates

Any future `VALIDATED` result must satisfy all of the following on the exact
same frozen structure, direction, DTE band, entry basis, cost model, settlement
rule, and hold-to-expiry outcome:

- at least `8` further independent settled expiry cohorts after the freeze;
- at least `100` valid strategy observations;
- at least `2` volatility regimes, `2` trend regimes, and `2` liquidity
  regimes in the judging sample;
- no single regime label contributing more than `60%` of the final cohorts;
- `95%` cohort-bootstrap lower bound for mean net `R` above zero;
- positive paired difference versus the same-structure comparator;
- positive mean net `R` after `1.5x` modeled costs;
- bounded loss, known max loss, known margin, and consistent units;
- max drawdown within `10%` of shadow NAV;
- CVaR `95` within `3%` of shadow NAV;
- no single cohort or calendar month contributing more than `40%` of absolute
  gross profit;
- per-trade max loss within `1.5%` NAV, same-expiry loss within `3%`, and new
  modeled margin within `8%`.

## Status semantics

- `INSUFFICIENT`: the available sample is too small or too narrow to judge.
- `EXPLORATORY`: development results exist, but no eligible future holdout has
  been opened yet.
- `VALIDATED`: an eligible future holdout exists and every frozen gate passed.
- `FAILED`: the holdout was eligible to judge, but a frozen performance/risk
  gate failed or the claimed holdout source was invalid.

Only `VALIDATED` may expose public `win_rate` or `mean_net_r`.

Validated artifacts enter the report only through repeatable operator-controlled
`--strategy-history-artifact <path>` flags. Each file is revalidated, at most
one artifact may exist per structure family, and canonical artifact content—not
the filesystem path—is bound into the immutable `AnalysisRun` identity. With no
configured artifact the projector constructs the honest `INSUFFICIENT` default.

## Current truth as of 2026-08-30

- `BEAR_CALL_CREDIT_SPREAD` has a reusable frozen legacy bear-call boundary,
  but still needs future aligned holdout cohorts before it can validate.
- `BULL_PUT_CREDIT_SPREAD` and `IRON_CONDOR` now have frozen successor
  protocols, but they also remain pending future holdout evidence.
- No strategy family may honestly claim `VALIDATED` today from the currently
  inventoried workspace data.
