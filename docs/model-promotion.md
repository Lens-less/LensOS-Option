# Model promotion — what has to be true, and what it changes

`calibration.py` reports `not_implemented`, and `validate_walk_forward_calibration`
**asserts** that it does:

```python
if report.get("status") != "not_implemented":
    errors.append("walk_forward_calibration.status must be not_implemented")
```

That is a deliberate wall. It exists because fabricated calibration statistics
were removed from this product once already, and a contract test is the only
thing that stops them coming back.

The wall has no door yet. In roughly two months the signal validation produces
its first information coefficient, and if it is positive there is currently no
specified path from *"the ranking axis has measured predictive power"* to
*"the model is promoted"*. This document specifies that path.

**Status: decided, not implemented.** The three decisions §8 asked for were
taken on 2026-07-27 and are recorded in §0 and §3.3. The mechanism itself is
still unimplemented, deliberately: nothing here should be built until there is a
sample to build it against.

---

## 0. Pre-registration — 2026-07-27

Route **(a)** of §3.3 is taken. This section is the registration; the commit that
introduced it is its timestamp.

> **The axis nominated for promotion is `smile_residual_z`.**
> The threshold that applies to it is `|t| ≥ 2.0` on the moneyness-neutralized
> information coefficient, computed against the independent expiry-cohort count.

**Why this axis.** It is the ranking the product actually ships — `edge_score`
orders on the standardized smile residual, and `ev_scanner` publishes it as
`primary_axis`. Registering anything else would be registering a candidate the
product does not use. The standardization is not a tuning choice either: raw IV
points are not comparable between chains, so the z-scored form is the only
version of this axis that can be measured across a sample at all.

**Sample state at registration** — the fact that makes this a pre-registration
rather than a claim about one:

| | |
|---|---|
| Settled expiry cohorts | **0** of 8 required |
| Cohorts pending settlement | 3 (2026-08-07, 08-14, 08-28) |
| Capture dates in series | 1 |
| Repository HEAD | `42c4c2f` (2026-07-27) |

No outcome data existed when this was written. `validate-signal --preflight`
reproduces this table from the capture series, so the claim is checkable rather
than asserted.

**What this forecloses.** The other nine measured signals — and the roughly six
further distinct orderings among them — are **exploratory for this sample and can
never be promoted from it**. If one of them turns out to score higher, that is
information for designing the *next* registration, on a *later* sample. It is not
grounds for promotion, and the corrected threshold of §3.3(b) is not available
retroactively: the whole value of route (a) is that it was chosen before the
result was visible.

---

## 1. What is being promoted

Not "the model" as a single thing. Two separable claims, which can be promoted
independently and probably will be:

| Claim | Produced by | Currently labelled |
|---|---|---|
| **Ranking** — this ordering carries cross-sectional information | `edge_score` axis, measured by `signal_validation` | `UNCALIBRATED_RESEARCH_ONLY` |
| **Expected value** — this level is a usable estimate of the payout | `ev_scanner.build_absolute_ev`, tested by `ev_robustness` | `NO_VALIDATED_PATH_RISK` when absent |

Promoting the ranking does not promote the level. An ordering can be
informative while every expected value in it is wrong.

## 2. What promotion changes — and what it does not

**It does not touch execution.** `execution_allowed` stays `false`, permanently
and by design. Promotion is not a step toward trading; it is a step toward the
product stating a weaker caveat.

What changes:

- `score_status` moves off `UNCALIBRATED_RESEARCH_ONLY` for the promoted axis.
- `walk_forward_calibration.status` becomes `promoted`, carrying the artifact
  id and the evidence that promoted it.
- The ranking's published basis names a validated axis rather than a
  conventional one.
- `readiness` may open the gates that today cite `CALIBRATION_NOT_IMPLEMENTED`.

What does not change:

- `research_only` mode.
- The mode gate, the blocked-output list, sizing, order instructions.
- Every `cannot_tell` line that is about the measurement rather than the
  calibration.

## 3. Evidence required

Each of these is necessary; none alone is sufficient.

*Thresholds confirmed 2026-07-27. They are now the contract, not proposals.*

**3.1 Sample.** At least **8 independent expiry cohorts** (the existing
`min_independent_cohorts`) with settled outcomes, drawn from captures that
passed the market-data gate. Cohorts, never observations.

**3.2 Effect.** The moneyness-neutralized information coefficient is positive
with `|t| ≥ 2.0` — the registered threshold of §0 — computed against the cohort
count, never the observation count.

**3.3 The multiplicity problem — the part that is easy to get wrong.**

`signal_validation` measures **ten** signals, which the collinearity block
reports as roughly **seven distinct orderings**. Promoting whichever scored best
is selection on the same sample that produced the score, and at seven
comparisons a conventional `t ≥ 2` threshold will produce a "winner" from noise
a large fraction of the time.

Two acceptable resolutions. Pick one before the sample completes:

- **(a) Pre-registration.** Nominate the axis to be promoted *now*, in writing,
  before the cohorts settle. The threshold stays `t ≥ 2.0`. Everything else
  measured stays exploratory and can never be promoted from this sample.
- **(b) Correction.** Any axis may be promoted, but the threshold rises for the
  number of distinct orderings actually tested — Bonferroni at seven puts it
  near **`t ≥ 2.8`**. Use `collinearity.distinct_signal_estimate` as the count,
  not the raw signal count, since rank-equivalent signals are one test.

**Decision (2026-07-27): route (a).** `smile_residual_z` is registered in §0 at
`|t| ≥ 2.0`. Route (b) is not available for this sample — choosing it later,
after seeing which axis scored best, would be the selection this section exists
to prevent.

**3.4 Out-of-sample confirmation.** The effect holds on cohorts that settled
*after* the promotion evidence was assembled — at minimum **4 further cohorts**,
same sign, no threshold required. This is the walk-forward part of
"walk-forward calibration" and it is what makes the name honest.

**3.5 For the expected-value claim only.** `ev_robustness` returns a verdict
that is not `sign_flips_across_periods`, on the candidates being promoted. A
level that changes sign between history slices is not a level.

**3.6 Data continuity.** No gap longer than **3 consecutive days** in the
capture series backing the sample. `validate-signal --preflight` already reports
this; a sample assembled across a two-week outage describes two regimes.

## 4. The artifact

Promotion produces one content-addressed record, and the report cites it rather
than restating it:

```
model_promotion.v1
  artifact_id            sha256 of the canonical encoding of this record
  promoted_at            ISO-8601
  claim                  "ranking" | "expected_value"
  axis                   e.g. "smile_residual_z"
  pre_registered         bool           # which §3.3 route was taken
  pre_registered_at      ISO-8601|null
  evidence
    signal_validation_artifact_id
    cohorts, information_coefficient, t_stat, t_threshold_applied
    distinct_orderings_tested
    out_of_sample_cohorts, out_of_sample_ic
    ev_robustness_verdicts        # expected_value claim only
    capture_continuity            # longest gap in days
  expires_at             ISO-8601      # see §6
```

The evidence block records the threshold **that was applied**, not the default,
so a promotion made under the corrected threshold cannot later be read as though
it cleared the pre-registered one.

## 5. Scope of a promotion — confirmed 2026-07-27

A promotion is not global. It is scoped, and the scope has to be written down
because the evidence only covers the scope:

- **Underlying**: BTC. An ETH promotion needs ETH cohorts; ETH expiries settle
  on the same dates as BTC's and their outcomes are correlated, so they are not
  additional independent cohorts for a BTC claim.
- **Tenor band**: the 7–35 day research window. Short-dated behaviour is
  dominated by pin and gamma effects and is a different claim.
- **Structure set**: the structures present in the validated sample.

## 6. Demotion — the part usually left out

A promotion that cannot expire is a permanent claim from a finite sample.

- **Expiry.** Every promotion carries `expires_at`, proposed at **90 days**.
  Past it the status reverts to `not_implemented` with reason
  `PROMOTION_EXPIRED` until re-evidenced.
- **Continuous check.** Each new settled cohort extends the out-of-sample
  series. If the rolling out-of-sample IC turns negative across **3 consecutive
  cohorts**, demote immediately with `PROMOTION_CONTRADICTED`.
- **Input change demotes.** Any change to the fitted surface, the residual
  definition, the filters or the fee model invalidates the evidence, because the
  promoted axis is no longer the measured axis. Demotion here is mechanical, not
  a judgement call.

Demotion is fail-closed like everything else: it reverts to the blocked state,
never to a weaker promotion.

## 7. What the wall becomes

`validate_walk_forward_calibration` currently asserts `not_implemented`. Under
this spec it asserts instead:

- status is `not_implemented`, **or** `promoted` with a well-formed
  `model_promotion.v1` artifact whose evidence satisfies §3;
- `execution_allowed` is `false` in every case;
- a `promoted` status whose `expires_at` has passed is an error, not a
  degradation — a stale promotion must not survive a clock change.

The wall keeps doing its job. It stops being a wall with nothing behind it.

## 8. Decisions — closed 2026-07-27

1. **§3.3 route** — (a) pre-registration. `smile_residual_z` at `|t| ≥ 2.0`,
   recorded in §0.
2. **§3 thresholds** — confirmed as written.
3. **§5 scope** — confirmed: BTC, the 7–35 day research window, the structures
   present in the validated sample.

All three were taken while 0 of 8 cohorts had settled. None of them can be
revisited for this sample without voiding the registration; they can of course
be set differently for the next one.

## 9. What remains unimplemented, and when to build it

Nothing in §4, §6 or §7 exists in code, and that is the correct state today —
there is no artifact to produce and nothing to demote. Build it when the sample
is close to complete, not before: an implementation written now would be tested
against data invented for the purpose, which is how fabricated calibration got
into this product the first time.

The one piece that *is* worth carrying now is visibility: the measurement
surface names the registered axis beside the exploratory ones, so the
distinction is legible at the moment the coefficient appears rather than
recoverable from this file afterwards.
