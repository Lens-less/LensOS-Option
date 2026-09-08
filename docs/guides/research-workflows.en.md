# Research Methods And Workflows

[Project home](../../README.en.md) · [Documentation](../README.md) · [中文](research-workflows.md)

Commands below run from the repository root after installing the package. Operational actions require the configured services described in the runbooks.
For a complete input-to-conclusion path, start with the [decision workflow](decision-workflow.en.md).

## Core Concepts

Read these first (full definitions live in the [glossary](../glossary.md),
which is written in Chinese):

| Term | Meaning |
| --- | --- |
| `research_only` | The fixed output mode: research only, never an order instruction. No configuration changes it. |
| Mode gate | The checkpoint blocking out-of-bounds output - trade recommendations, sizes, and order instructions. |
| `AnalysisRecord` | The **immutable** record of one analysis; the carrier of trusted output. |
| `EntryAdmissionDecision` | The **ceiling** on trusted output: "may this be considered for entry", always `execution_allowed=false`. |
| Evidence class | Evidence trust level: `trusted` / `degraded` / `untrusted` / `missing`. |
| Replay | The same build, complete input set, rules, and explicit clock produce comparable deterministic output; identity differences require explanation. |

## Capability Boundaries

This table describes implemented capabilities, not this iteration's test or live
market results. See the [v0.5.0 delivery record](../product/2026-09-08-open-source-decision-platform.md).

| Capability | Status |
| --- | --- |
| Canonical `strategy_brief.v1` and all three one-screen projections | Implemented; cards remain evidence-gated |
| Local deterministic / replay research toolchain | Implemented; replay does not establish data trust |
| Publisher-verified static research artifacts | Implemented; publication and hosting require separate checks |
| Paper / manual trading, order submission, real account execution | **NO-GO** |
| Exact-strategy calibration and promotion/demotion machinery | Implemented; remains `UNAVAILABLE` / `SCREENING_ONLY` without mature real cohorts |
| Bull Put / Iron Condor historical rates | **Unavailable** pending their own frozen future holdouts |
| Trading execution authorization | **NO-GO (permanent)** |

WebSocket gap/resync, 24-hour soak, and seven consecutive days of evidence are
still internal run / execution readiness requirements. They do not block static
research publication that satisfies data-quality, reproducibility, and privacy
boundaries, and the static release does not relax them.

## Usage

### Finding candidates with edge

Candidate comparison describes differences between structures on the current
chain, separating two kinds of evidence:

- **Relative value** - is this strike rich or cheap against its own smile.
  Requires the chain to pass quality and fitting requirements.
- **Absolute expected value** - credit minus expected payout minus fees. Needs
  the underlying's realized-return distribution.

Capture underlying history first (public data, no credentials):

```powershell
crypto-options-underlying-history --currency BTC --days 1200 `
  --output artifacts/history/btc-daily.json --horizon-days 7 --horizon-days 18
```

It reports how many **independent** windows each holding period has. Horizons
without enough windows are blocked rather than given a precise-looking number
that the sample cannot support.

```powershell
crypto-options-report scan `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

This command does not freeze its evaluation clock. Current research needs a new
snapshot; historical inspection can pass
`--generated-at <snapshot-captured-at-with-timezone>` without restoring present eligibility.

Ranking uses a **Pareto frontier plus a published lexicographic tie-break** - no
weighted sum, because weighting incommensurable components asserts a relative
importance nothing has established. Dominated candidates carry which rival beat
them and on which axes. When the frontier swallows nearly everything, the
`frontier_occupancy` field says so honestly.

> **Sample size means independent, non-overlapping windows.** Overlapping
> windows share most return observations and cannot stand in for independent
> samples. Use the history tool's actual count, based on valid observations,
> horizon, and stride.

### Candidate Universe

The universe covers both calls and puts. Structures are expressed as a **signed
set of legs**, not as a structure name, so terminal payoff, max loss, and
position greeks are computed by the same code for every combination:

| Structure | Risk |
| --- | --- |
| `naked_short_calls` | Unbounded (`max_loss` is `None`, so downstream ratios cannot be formed) |
| `call_credit_spreads` | Finite |
| `put_credit_spreads` | Finite |
| `iron_condors` | Finite, both sides |

The table names are published by `structure_types` in the report. Consumers do
not need to hard-code them.

### What happens if you combine these?

`combination_risk` treats the frontier candidates as a hypothetical book, one
structure each, **without any notion of size**:

- **No joint max loss across expiries** - it only publishes a labeled upper
  bound, the sum of each member's worst case. Only when all legs share the same
  expiry does it compute a true joint payoff.
- Net vega appears alongside **vega split by expiry** because the net number
  implicitly assumes a parallel volatility shift.
- Marginal contribution is computed by "remove this member" rather than by the
  member's own worst case.

### Was this strike also this expensive yesterday?

Daily capture started as a way to accumulate validation samples, but it also
answers a different question.

```powershell
crypto-options-report series-history `
  --snapshot-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` rebuilds that artifact after every capture. Feeding it
to the engine via `--series-artifact` shows a **contract x capture day**
heatmap of standardized residuals.

Three deliberate choices:

- **Standardized residuals instead of raw IV.** Every day a contract gets closer
  to expiry, IV, delta, and premium move for reasons unrelated to mispricing.
  Only values normalized by each expiry's residual scale are comparable across
  days.
- **A missing capture is not zero.** The collector samples about one hundred
  contracts from a few hundred listed ones, and the set drifts with spot.
  Empty cells mean "not captured", filled cells mean observed; they never
  impersonate each other.
- **Ranking by shrinkage toward zero.** Otherwise contracts that appear on only
  three days would float to the top on the back of three reads - exactly the
  sample-size error this project tries to avoid. The shrinkage constant is
  published.

> **Persistently positive does not automatically mean opportunity.** A residual
> that stays positive can also mean the secondary fit cannot keep up with the
> true wing at that strike. Both situations look the same on the chart, so the
> sentence sits **above** the chart.

### What can this ranking predict?

The current collector does not backfill historical options chains. Validation
requires quotes, IV, and capture times saved in advance; underlying history or
contract trade candles cannot replace that evidence. Missing dates stay missing.
Capture continuously and wait for contracts to expire.

For capture, scheduling, and sample accumulation, see the [operator guide](operator-guide.en.md).

It uses the **production code path itself** to generate daily candidates and
calculates hypothetical expiry PnL from captured quotes and a `daily_close_proxy`,
then publishes bin tables and an information coefficient. This contains no real
fill evidence and cannot reproduce the exchange's settlement-window average.
Two choices determine whether it is worth trusting:

- **Sample size is counted by expiry cohort, not by observation count.**
  Consecutive snapshots are the same contracts and the same settlement price.
- **Correlation is moneyness-neutralized first.** The raw correlation is
  dominated by moneyness - a signal equivalent to "sort by strike" can score
  0.95 IC in a control group with no mispricing information. The raw value is
  still shown alongside the neutralized one so you can see how large the
  confound is.

The ranking axis itself is also measured, and the outcome can be
`no_detectable_edge`. **That is the point.**

**Only one pre-registered axis is eligible for subsequent promotion review.** On 2026-07-27, when 0/8
cohorts had settled, `smile_residual_z` was pre-registered with a threshold of
`|t| >= 2.0`. The other nine signals are exploratory - even if one has a better
score, it can only inform the next registration, not be promoted from this
sample. The reason is multiple comparison risk: with roughly 7 distinct orderings
in the same sample, picking the top one and promoting it gives noise a real
chance to win. The registration is published with the validation artifact
(`pre_registration`), and the UI marks the registered axis separately from the
highest-scoring exploratory axis in this sample.
The signal-validation artifact does not itself promote a model. Passing its
statistical threshold does not bypass model protocols or other evidence gates.

### EV is negative - which kind of negative?

A negative expected value can mean three different things, and they call for
different responses: the sample period happened to include a bad regime for
sellers; edge exists but sits inside the spread; or the shape is simply bad and
the other direction is the interesting one.

```powershell
crypto-options-report ev-robustness `
  --snapshot-fixture artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

It splits the problem into **execution sensitivity** (buy / sell, bid / mid /
ask) and **period sensitivity** (recompute on continuous historical slices and
see whether the sign flips). Expected payout does not depend on entry price, so
the four execution variants are arithmetic on the same path replay; only the
slices need extra work.

`verdict` only names what the numbers show: `sign_flips_across_periods`,
`no_capturable_edge_at_the_touch` (fair value between bid and ask - normal
market, not a discovery), `other_direction_is_positive`, and
`negative_across_periods_and_execution`.

### Path Risk And Stress Semantics

Historical paths default to `unconditioned_uniform`. Without state features
observed before a path began, similarity conditioning stays unavailable; the
path's future returns cannot select a supposedly similar historical regime.

`adverse_excursion` uses the actual credit legs' `up`, `down`, or `both` risk
direction to measure the underlying's largest adverse move. It is not an option
mark-to-market loss; unsupported directions remain unknown.
`short_strike_cross_probability` describes sample paths crossing short-leg strikes.
Legacy `delta_cross_probability` remains a price-threshold proxy. Dynamic delta
modeling is explicitly `unavailable` / `NO_DYNAMIC_DELTA_PATH_MODEL`.

Bidirectional stress scenarios declare
`scenario_basis=authored_deterministic_shocks`. Their weights are not calibrated
probabilities (`weights_are_calibrated_probabilities=false`) and do not provide
statistical confidence (`statistical_confidence_available=false`). Use them to
compare reactions to specified shocks, not to generate a success rate.
