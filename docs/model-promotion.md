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

**Status: proposal.** The mechanism below is a design; the numeric thresholds in
§3 and the scope in §5 are decisions for the operator, not defaults to inherit.
Nothing here is implemented, and it should not be implemented before the
thresholds are agreed — picking them after seeing the result is the failure this
whole apparatus exists to prevent.

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

## 3. Evidence required — the proposal

Each of these is necessary; none alone is sufficient.

**3.1 Sample.** At least **8 independent expiry cohorts** (the existing
`min_independent_cohorts`) with settled outcomes, drawn from captures that
passed the market-data gate. Cohorts, never observations.

**3.2 Effect.** The moneyness-neutralized information coefficient is positive
with `|t| ≥ T`, computed against the cohort count.

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

Option (a) is stronger evidence and cheaper to satisfy. It costs the ability to
promote a signal that turns out to be the good one. **This is the operator's
call and it must be made before the data lands.**

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

## 5. Scope of a promotion — operator decision

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

## 8. What to do now, before any data exists

1. **Choose §3.3 (a) or (b).** If (a), nominate the axis in this file, dated,
   and commit it. That commit is the pre-registration.
2. **Confirm or change the thresholds in §3** — they are proposals.
3. **Confirm the scope in §5.**

None of this needs the sample. All of it becomes impossible to do honestly once
the sample exists.
