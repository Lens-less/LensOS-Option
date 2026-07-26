"""Predictive-power measurement for the candidate ranking signals.

The report ranks candidates by how far a mark sits above its own fitted smile
(`edge_score.TIE_BREAK_ORDER`), but nothing in the product ever established that
this ordering predicts anything. `backtest.py` replays one fixed short-call
baseline rather than the ordering, and `calibration.py` reports that walk-forward
promotion is not implemented. Ranking by an unmeasured signal is not neutral: it
concentrates attention on whatever the residual happens to select, which on a
thin chain may be the venue's own mark smoothing rather than mispricing.

This module measures that, and only that. It does not promote a signal, does not
size anything, and does not turn a positive result into an entry permission —
promotion remains `calibration.py`'s unimplemented job. It answers one question:
**does a candidate ordering carry cross-sectional information about what actually
happened next, and against how large a sample?**

Four choices carry the honesty burden:

* **The production code path is the measured path.** Observations come from
  `build_vol_surface_and_candidate_research`, not a reimplementation, so what is
  validated is the signal the report actually ships. Snapshots whose market data
  does not validate are excluded and counted, never silently repaired.
* **Independence is counted in expiry cohorts.** Two snapshots a day apart hold
  nearly the same options resolving to the same settlement print. Treating them
  as independent draws would inflate the t-statistic by roughly the number of
  snapshots per expiry, so every published statistic is stated against the
  cohort count, not the observation count.
* **Outcomes are measured per unit of vega.** Raw dollar P&L is not comparable
  across strikes and expiries, so a dollar-ranked table would mostly rank
  notional. Dividing by vega puts the outcome in the same IV-point units as the
  signal itself.
* **Moneyness is neutralized before the correlation.** Both the signal and the
  outcome carry a large systematic component in log-moneyness — a further-out
  strike is quoted at a different IV *and* keeps its premium more often — so a
  raw rank correlation mostly measures how far out of the money the position
  was. Measured raw, a signal as trivial as "rank by strike" scores an
  information coefficient near 0.95 with no mispricing information in it at all.
  Both series are therefore residualized against a quadratic in log-moneyness
  within each date, and the raw figure is still reported beside the neutralized
  one so the size of that confounder stays visible.
* **Settlement is a declared proxy.** Deribit settles on a 30-minute average
  index at 08:00 UTC; a daily close series cannot reproduce that. The
  approximation is named in the report rather than hidden inside it.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from .edge_score import normalize_premium_to_usd
from .market_data import build_market_data_status, parse_timestamp_ms
from .pnl import (
    delivery_fee_inverse,
    delivery_fee_linear,
    option_fee_inverse,
    option_fee_linear,
)
from .surface import build_vol_surface_and_candidate_research

SIGNAL_VALIDATION_SCHEMA_VERSION = "signal_validation_report.v1"

DEFAULT_SIGNAL_VALIDATION_CONFIG = {
    # Below these the report refuses to publish statistics rather than
    # publishing ones nobody should act on.
    "min_observations": 100,
    "min_independent_cohorts": 8,
    "min_observations_per_date": 4,
    "bucket_count": 5,
    "min_dte_days": 1.0,
    "max_dte_days": 45.0,
    "trailing_vol_window_days": 30,
}

# Published decision threshold. Two standard errors is the conventional bar and
# is deliberately stated in the artifact so a reader can disagree with it
# explicitly rather than guess what "significant" meant here.
T_STAT_THRESHOLD = 2.0

ANNUALIZATION_DAYS = 365

INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_SIGNAL_OBSERVATIONS"
INSUFFICIENT_COHORTS = "INSUFFICIENT_INDEPENDENT_EXPIRY_COHORTS"
MISSING_UNDERLYING_HISTORY = "MISSING_UNDERLYING_HISTORY"
NO_VALIDATED_SNAPSHOTS = "NO_VALIDATED_SNAPSHOTS"
DEGENERATE_SIGNAL = "SIGNAL_HAS_NO_CROSS_SECTIONAL_VARIATION"

SETTLEMENT_BASIS = "daily_close_proxy"

# Every signal is defined so that a *higher* value means "the seller is being
# paid more than the fit says this option is worth". Keeping one orientation
# means a negative IC always reads as "the ordering is backwards", never as an
# artefact of one signal being defined upside down.
SIGNAL_DEFINITIONS: dict[str, str] = {
    "smile_residual_iv_points": (
        "mark IV minus fitted IV, in IV points. The axis the report currently "
        "ranks on."
    ),
    "smile_residual_z": (
        "the same residual divided by the expiry's own residual scale, so a "
        "scattered smile and a tight one are comparable."
    ),
    "smile_residual_vega_usd": (
        "the same residual multiplied by vega, so one IV point at 7 DTE is not "
        "compared against one IV point at 35 DTE."
    ),
    "iv_minus_trailing_realized_vol": (
        "mark IV minus trailing realized volatility. The classic variance-risk-"
        "premium signal, included as a benchmark the smile residual has to beat "
        "to justify its own complexity."
    ),
}


def build_signal_validation_report(
    *,
    snapshots: list[dict[str, Any]],
    underlying_history: dict[str, Any] | None,
    generated_at: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure each ranking signal against what the underlying actually did.

    `snapshots` are market snapshots in capture order, of the same shape the
    report consumes. `underlying_history` supplies the settlement proxy and the
    trailing-volatility benchmark.
    """
    merged = dict(DEFAULT_SIGNAL_VALIDATION_CONFIG)
    merged.update(config or {})

    closes_by_date, ordered_dates = _close_series(underlying_history)
    if not closes_by_date:
        return _blocked(
            generated_at=generated_at,
            config=merged,
            reason_codes=[MISSING_UNDERLYING_HISTORY],
        )

    observations: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    validated_snapshots = 0

    for snapshot in sorted(
        [item for item in snapshots if isinstance(item, dict)],
        key=lambda item: str(item.get("captured_at") or ""),
    ):
        captured_at = str(snapshot.get("captured_at") or "")
        if not captured_at:
            excluded.append({"captured_at": None, "reason_code": "MISSING_CAPTURED_AT"})
            continue
        try:
            evaluation_now_ms = parse_timestamp_ms(captured_at)
        except (ValueError, TypeError):
            excluded.append(
                {"captured_at": captured_at, "reason_code": "UNPARSEABLE_CAPTURED_AT"}
            )
            continue

        data_status = build_market_data_status(snapshot, now_ms=evaluation_now_ms)
        if data_status.get("status") != "validated":
            excluded.append(
                {
                    "captured_at": captured_at,
                    "reason_code": data_status.get("reason_code")
                    or "MARKET_DATA_NOT_VALIDATED",
                }
            )
            continue

        vol_surface_status, _ = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at=captured_at,
            data_status=data_status,
            pnl_evidence={"status": "pass"},
        )
        validated_snapshots += 1
        observations.extend(
            _observations_from_surface(
                vol_surface_status=vol_surface_status,
                captured_at=captured_at,
                closes_by_date=closes_by_date,
                ordered_dates=ordered_dates,
                config=merged,
            )
        )

    if validated_snapshots == 0:
        return _blocked(
            generated_at=generated_at,
            config=merged,
            reason_codes=[NO_VALIDATED_SNAPSHOTS],
            excluded=excluded,
        )

    observations, duplicates = _deduplicate_by_date(observations)
    cohorts = sorted({item["expiry_date"] for item in observations})
    sample = {
        "observation_count": len(observations),
        "snapshot_count": len(snapshots),
        "validated_snapshot_count": validated_snapshots,
        "excluded_snapshot_count": len(excluded),
        "snapshot_date_count": len(
            sorted({item["snapshot_date"] for item in observations})
        ),
        "independent_expiry_cohorts": len(cohorts),
        "sample_size_basis": "independent_expiry_cohorts",
        "expiry_cohorts": cohorts,
        "duplicate_observations_dropped": duplicates,
        "settlement_basis": SETTLEMENT_BASIS,
        "settlement_note": (
            "Deribit settles on a 30-minute average index at 08:00 UTC. A daily "
            "close series cannot reproduce that print, so realized payoffs here "
            "carry settlement-window error that is not modelled."
        ),
        "excluded_snapshots": excluded,
    }

    reason_codes: list[str] = []
    if len(observations) < merged["min_observations"]:
        reason_codes.append(INSUFFICIENT_OBSERVATIONS)
    if len(cohorts) < merged["min_independent_cohorts"]:
        reason_codes.append(INSUFFICIENT_COHORTS)

    if reason_codes:
        return {
            **_base(generated_at, merged),
            "status": "blocked",
            "reason_codes": reason_codes,
            "sample": sample,
            "signals": {},
            "summary": {
                "signals_measured": 0,
                "signals_with_detectable_ic": 0,
                "best_signal": None,
            },
        }

    signals = {
        name: _measure_signal(
            name=name,
            observations=observations,
            independent_cohorts=len(cohorts),
            config=merged,
        )
        for name in sorted(SIGNAL_DEFINITIONS)
    }

    return {
        **_base(generated_at, merged),
        "status": "measured",
        "reason_codes": [],
        "sample": sample,
        "signals": signals,
        "summary": _summary(signals),
        "cannot_tell": [
            "A detectable information coefficient is not a profitable strategy: "
            "it is measured before position sizing, portfolio constraints and "
            "any fill assumption beyond the quoted bid.",
            "This measurement is in-sample over the supplied snapshots. It is "
            "not walk-forward validation and cannot promote a model.",
            "Outcomes assume the option is held to expiry and settled against a "
            "daily close proxy; an early-exit rule would produce a different "
            "distribution.",
        ],
    }


def _base(generated_at: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SIGNAL_VALIDATION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "config": dict(config),
        "t_stat_threshold": T_STAT_THRESHOLD,
        "signal_definitions": dict(SIGNAL_DEFINITIONS),
    }


def _blocked(
    *,
    generated_at: str,
    config: dict[str, Any],
    reason_codes: list[str],
    excluded: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        **_base(generated_at, config),
        "status": "blocked",
        "reason_codes": list(reason_codes),
        "sample": {
            "observation_count": 0,
            "independent_expiry_cohorts": 0,
            "sample_size_basis": "independent_expiry_cohorts",
            "excluded_snapshots": list(excluded or []),
        },
        "signals": {},
        "summary": {
            "signals_measured": 0,
            "signals_with_detectable_ic": 0,
            "best_signal": None,
        },
    }


# --- observation construction ----------------------------------------------


def _close_series(
    underlying_history: dict[str, Any] | None,
) -> tuple[dict[str, float], list[str]]:
    """Map UTC date to close, plus the ordered date list for trailing windows."""
    if not isinstance(underlying_history, dict):
        return {}, []
    observations = underlying_history.get("observations")
    if not isinstance(observations, list):
        return {}, []
    closes: dict[str, float] = {}
    for row in observations:
        if not isinstance(row, dict):
            continue
        observed_at = str(row.get("observed_at") or "")
        close = row.get("close")
        if len(observed_at) < 10 or not isinstance(close, (int, float)):
            continue
        if isinstance(close, bool) or close <= 0:
            continue
        closes[observed_at[:10]] = float(close)
    return closes, sorted(closes)


def _deduplicate_by_date(
    observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep one observation per instrument per day, preferring the latest capture.

    A scheduled collector will sometimes run twice in a day — a retry, a manual
    run, a machine that woke late. Those captures share a snapshot date, so
    without this every duplicated instrument would appear several times inside
    one cross-section. The per-date rank correlation would then be computed over
    a sample that repeats its own rows, which tightens the correlation toward
    whatever the duplicated subset says and does it invisibly.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates = 0
    for row in sorted(observations, key=lambda item: str(item["captured_at"])):
        key = (row["snapshot_date"], str(row["instrument_name"] or ""))
        if key in latest:
            duplicates += 1
        latest[key] = row
    ordered = sorted(
        latest.values(),
        key=lambda item: (item["snapshot_date"], str(item["instrument_name"] or "")),
    )
    return ordered, duplicates


def _observations_from_surface(
    *,
    vol_surface_status: dict[str, Any],
    captured_at: str,
    closes_by_date: dict[str, float],
    ordered_dates: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    snapshot_date = captured_at[:10]
    trailing_vol = _trailing_realized_vol(
        closes_by_date=closes_by_date,
        ordered_dates=ordered_dates,
        as_of_date=snapshot_date,
        window_days=int(config["trailing_vol_window_days"]),
    )

    rows: list[dict[str, Any]] = []
    for expiry in vol_surface_status.get("expiries") or []:
        if not isinstance(expiry, dict) or not expiry.get("candidate_eligible"):
            continue
        expiry_date = str(expiry.get("expiry_date") or "")
        dte_days = expiry.get("dte_days")
        settlement = closes_by_date.get(expiry_date)
        if settlement is None or not isinstance(dte_days, (int, float)):
            continue
        if not (config["min_dte_days"] <= dte_days <= config["max_dte_days"]):
            continue
        if expiry_date <= snapshot_date:
            continue
        for point in expiry.get("surface_points") or []:
            row = _observation(
                point=point,
                snapshot_date=snapshot_date,
                captured_at=captured_at,
                expiry_date=expiry_date,
                dte_days=float(dte_days),
                settlement_price=settlement,
                trailing_vol=trailing_vol,
            )
            if row is not None:
                rows.append(row)
    return rows


def _observation(
    *,
    point: dict[str, Any],
    snapshot_date: str,
    captured_at: str,
    expiry_date: str,
    dte_days: float,
    settlement_price: float,
    trailing_vol: float | None,
) -> dict[str, Any] | None:
    """One short-call observation: what was quoted, and what it later paid.

    Returns None when any input the outcome depends on is absent, because an
    observation with an imputed leg would silently become evidence about the
    imputation rather than about the signal.
    """
    strike = _number(point.get("strike_price"))
    spot = _number(point.get("underlying_price"))
    bid = _number(point.get("market_bid"))
    vega = _number(point.get("model_vega"))
    residual = _number(point.get("fit_residual_iv"))
    mark_iv = _number(point.get("market_mark_iv"))
    premium_unit = point.get("premium_unit")

    if strike is None or spot is None or bid is None or vega is None:
        return None
    if residual is None or strike <= 0 or spot <= 0 or vega <= 1e-9:
        return None

    credit_usd = normalize_premium_to_usd(
        bid, premium_unit=premium_unit, underlying_price=spot
    )
    if credit_usd is None or credit_usd <= 0:
        return None

    # Inverse options settle in coin, but the coin payout of a call is
    # max(S_T - K, 0) / S_T, so the USD payout is max(S_T - K, 0) either way.
    payout_usd = max(settlement_price - strike, 0.0)
    fees_usd = _realized_fees_usd(
        premium_unit=premium_unit,
        spot=spot,
        credit_usd=credit_usd,
        payout_usd=payout_usd,
        expired_itm=payout_usd > 0.0,
    )
    if fees_usd is None:
        return None

    pnl_usd = credit_usd - payout_usd - fees_usd
    signals: dict[str, float | None] = {
        "smile_residual_iv_points": residual,
        "smile_residual_z": _number(point.get("fit_residual_z")),
        "smile_residual_vega_usd": _number(point.get("fit_residual_vega_usd")),
        "iv_minus_trailing_realized_vol": (
            round(mark_iv - trailing_vol, 6)
            if mark_iv is not None and trailing_vol is not None
            else None
        ),
    }

    return {
        "snapshot_date": snapshot_date,
        "captured_at": captured_at,
        "instrument_name": point.get("instrument_name"),
        "expiry_date": expiry_date,
        "dte_days": round(dte_days, 6),
        "log_moneyness": round(math.log(strike / spot), 8),
        "strike_price": strike,
        "underlying_price": spot,
        "settlement_price": settlement_price,
        "model_delta": point.get("model_delta"),
        "vega_usd_per_iv_point": vega,
        "credit_usd": round(credit_usd, 6),
        "payout_usd": round(payout_usd, 6),
        "fees_usd": round(fees_usd, 6),
        "pnl_usd": round(pnl_usd, 6),
        # In IV points: directly comparable to the residual signals above.
        "pnl_per_vega_iv_points": round(pnl_usd / vega, 6),
        "expired_itm": payout_usd > 0.0,
        "signals": signals,
    }


def _realized_fees_usd(
    *,
    premium_unit: Any,
    spot: float,
    credit_usd: float,
    payout_usd: float,
    expired_itm: bool,
) -> float | None:
    """Entry fee plus, when the option actually finished ITM, a delivery fee."""
    if premium_unit == "quote_currency":
        entry = option_fee_linear(credit_usd, spot, 1.0)
        delivery = delivery_fee_linear(
            payout_usd, spot, 1.0, delivery_fee_applies=expired_itm
        )
        return entry + delivery
    if premium_unit == "inverse_base_currency":
        if spot <= 0:
            return None
        entry = option_fee_inverse(credit_usd / spot, 1.0) * spot
        delivery = (
            delivery_fee_inverse(payout_usd / spot, 1.0, delivery_fee_applies=True)
            * spot
            if expired_itm
            else 0.0
        )
        return entry + delivery
    return None


def _trailing_realized_vol(
    *,
    closes_by_date: dict[str, float],
    ordered_dates: list[str],
    as_of_date: str,
    window_days: int,
) -> float | None:
    """Annualized realized volatility in IV points, using only prior closes.

    Strictly backward-looking: including the snapshot date's own close would
    leak information the ranking could not have had.
    """
    prior = [date for date in ordered_dates if date <= as_of_date]
    if len(prior) < window_days + 1:
        return None
    window = prior[-(window_days + 1) :]
    log_returns = [
        math.log(closes_by_date[right] / closes_by_date[left])
        for left, right in pairwise(window)
        if closes_by_date[left] > 0 and closes_by_date[right] > 0
    ]
    if len(log_returns) < 2:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((value - mean) ** 2 for value in log_returns) / (
        len(log_returns) - 1
    )
    return round(math.sqrt(variance) * math.sqrt(ANNUALIZATION_DAYS) * 100.0, 6)


# --- measurement -------------------------------------------------------------


def _measure_signal(
    *,
    name: str,
    observations: list[dict[str, Any]],
    independent_cohorts: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    usable = [
        row
        for row in observations
        if isinstance(row["signals"].get(name), (int, float))
        and not isinstance(row["signals"].get(name), bool)
    ]
    cohorts = sorted({row["expiry_date"] for row in usable})

    if len(usable) < config["min_observations"] or len(cohorts) < config[
        "min_independent_cohorts"
    ]:
        return {
            "status": "blocked",
            "reason_code": INSUFFICIENT_OBSERVATIONS
            if len(usable) < config["min_observations"]
            else INSUFFICIENT_COHORTS,
            "definition": SIGNAL_DEFINITIONS[name],
            "observation_count": len(usable),
            "independent_expiry_cohorts": len(cohorts),
            "information_coefficient": None,
            "buckets": [],
            "evidence_verdict": "insufficient_sample",
        }

    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in usable:
        by_date.setdefault(row["snapshot_date"], []).append(row)

    per_date: list[dict[str, Any]] = []
    for date in sorted(by_date):
        rows = by_date[date]
        if len(rows) < config["min_observations_per_date"]:
            continue
        signal_values = [float(row["signals"][name]) for row in rows]
        outcome_values = [float(row["pnl_per_vega_iv_points"]) for row in rows]
        moneyness = [float(row["log_moneyness"]) for row in rows]

        raw = _spearman(signal_values, outcome_values)
        neutral_signal = _quadratic_residuals(moneyness, signal_values)
        neutral_outcome = _quadratic_residuals(moneyness, outcome_values)
        neutral = (
            _spearman(neutral_signal, neutral_outcome)
            if neutral_signal is not None and neutral_outcome is not None
            else None
        )
        if neutral is None:
            continue
        per_date.append(
            {
                "snapshot_date": date,
                "observation_count": len(rows),
                "information_coefficient": round(neutral, 6),
                "raw_information_coefficient": (
                    round(raw, 6) if raw is not None else None
                ),
            }
        )

    if len(per_date) < 2:
        return {
            "status": "blocked",
            "reason_code": DEGENERATE_SIGNAL,
            "definition": SIGNAL_DEFINITIONS[name],
            "observation_count": len(usable),
            "independent_expiry_cohorts": len(cohorts),
            "information_coefficient": None,
            "buckets": [],
            "evidence_verdict": "insufficient_sample",
        }

    values = [row["information_coefficient"] for row in per_date]
    mean_ic = sum(values) / len(values)
    variance = sum((value - mean_ic) ** 2 for value in values) / (len(values) - 1)
    stdev = math.sqrt(variance)

    # The standard error uses the cohort count, never the number of dates. Dates
    # sharing an expiry share their outcome, so dividing by sqrt(dates) would
    # claim precision the sample does not contain.
    effective_n = min(len(per_date), len(cohorts))
    t_stat = (
        (mean_ic / (stdev / math.sqrt(effective_n))) if stdev > 1e-12 else None
    )

    detectable = t_stat is not None and abs(t_stat) >= T_STAT_THRESHOLD
    if not detectable:
        verdict = "no_detectable_edge"
    elif mean_ic > 0:
        verdict = "positive_ic"
    else:
        verdict = "negative_ic"

    return {
        "status": "measured",
        "reason_code": None,
        "definition": SIGNAL_DEFINITIONS[name],
        "observation_count": len(usable),
        "independent_expiry_cohorts": len(cohorts),
        "measured_date_count": len(per_date),
        "effective_sample_size": effective_n,
        "effective_sample_basis": "min(measured_dates, independent_expiry_cohorts)",
        "information_coefficient": {
            "mean": round(mean_ic, 6),
            "stdev_across_dates": round(stdev, 6),
            "t_stat": round(t_stat, 6) if t_stat is not None else None,
            "method": "spearman_rank_vs_pnl_per_vega_moneyness_neutral",
            "neutralization": "quadratic_in_log_moneyness_within_date",
        },
        # Kept beside the neutralized figure precisely because it is the one
        # that flatters a signal. A large gap between the two means the signal
        # is mostly restating how far out of the money the strike was.
        "raw_information_coefficient": _raw_ic_summary(per_date),
        "per_date": per_date,
        "buckets": _bucket_table(
            usable, name=name, bucket_count=int(config["bucket_count"])
        ),
        "evidence_verdict": verdict,
    }


def _raw_ic_summary(per_date: list[dict[str, Any]]) -> dict[str, Any] | None:
    values = [
        row["raw_information_coefficient"]
        for row in per_date
        if isinstance(row.get("raw_information_coefficient"), (int, float))
    ]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return {
        "mean": round(mean, 6),
        "measured_date_count": len(values),
        "method": "spearman_rank_vs_pnl_per_vega",
        "warning": (
            "Not moneyness-neutral. A signal that is merely monotone in strike "
            "scores highly here without carrying any mispricing information."
        ),
    }


def _quadratic_residuals(xs: list[float], ys: list[float]) -> list[float] | None:
    """Residuals of `ys` after removing a quadratic in `xs`.

    Returns None when the sample cannot support the fit — three parameters need
    more than three points before the residuals mean anything, and a degenerate
    design matrix must not be papered over with a fallback that silently returns
    the original series.
    """
    n = len(xs)
    if n < 5 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    zs = [x - mean_x for x in xs]
    moments = [sum(z**power for z in zs) for power in range(5)]
    targets = [
        sum((z**power) * y for z, y in zip(zs, ys, strict=True)) for power in range(3)
    ]
    matrix = [
        [moments[0], moments[1], moments[2]],
        [moments[1], moments[2], moments[3]],
        [moments[2], moments[3], moments[4]],
    ]
    augmented = [list(row) + [targets[index]] for index, row in enumerate(matrix)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(
                    augmented[row], augmented[column], strict=True
                )
            ]
    coefficients = [augmented[index][3] for index in range(3)]
    return [
        y - (coefficients[0] + coefficients[1] * z + coefficients[2] * z * z)
        for z, y in zip(zs, ys, strict=True)
    ]


def _bucket_table(
    observations: list[dict[str, Any]],
    *,
    name: str,
    bucket_count: int,
) -> list[dict[str, Any]]:
    """Quantile buckets of the signal against the outcome it is supposed to predict.

    Buckets are cut on the pooled sample, so they answer "what happened to the
    richest-looking decile overall", not "per day". Each row carries its own
    cohort count so a bucket resting on two expiries cannot be read as if it
    rested on twenty.
    """
    if bucket_count < 2:
        return []
    ordered = sorted(
        observations,
        key=lambda row: (float(row["signals"][name]), str(row["instrument_name"] or "")),
    )
    total = len(ordered)
    buckets: list[dict[str, Any]] = []
    for index in range(bucket_count):
        start = (index * total) // bucket_count
        end = ((index + 1) * total) // bucket_count
        rows = ordered[start:end]
        if not rows:
            continue
        outcomes = [float(row["pnl_per_vega_iv_points"]) for row in rows]
        signal_values = [float(row["signals"][name]) for row in rows]
        buckets.append(
            {
                "bucket": index + 1,
                "signal_min": round(min(signal_values), 6),
                "signal_max": round(max(signal_values), 6),
                "observation_count": len(rows),
                "independent_expiry_cohorts": len(
                    {row["expiry_date"] for row in rows}
                ),
                "mean_pnl_per_vega_iv_points": round(
                    sum(outcomes) / len(outcomes), 6
                ),
                "median_pnl_per_vega_iv_points": round(_median(outcomes), 6),
                "mean_pnl_usd": round(
                    sum(float(row["pnl_usd"]) for row in rows) / len(rows), 6
                ),
                "win_rate": round(
                    sum(1 for value in outcomes if value > 0) / len(outcomes), 6
                ),
                "expired_itm_rate": round(
                    sum(1 for row in rows if row["expired_itm"]) / len(rows), 6
                ),
            }
        )
    return buckets


def _summary(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    measured = [
        (name, item)
        for name, item in sorted(signals.items())
        if item.get("status") == "measured"
    ]
    detectable = [
        (name, item)
        for name, item in measured
        if item.get("evidence_verdict") in {"positive_ic", "negative_ic"}
    ]
    best = None
    if detectable:
        best = max(
            detectable,
            key=lambda entry: abs(
                entry[1]["information_coefficient"]["t_stat"] or 0.0
            ),
        )[0]
    return {
        "signals_measured": len(measured),
        "signals_with_detectable_ic": len(detectable),
        "best_signal": best,
        "ranking_axis_in_product": "smile_residual_iv_points",
        "ranking_axis_verdict": signals.get("smile_residual_iv_points", {}).get(
            "evidence_verdict"
        ),
    }


# --- statistics --------------------------------------------------------------


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation with tie-averaged ranks; None when either side is flat."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    x_ranks = _ranks(xs)
    y_ranks = _ranks(ys)
    n = len(xs)
    mean_x = sum(x_ranks) / n
    mean_y = sum(y_ranks) / n
    covariance = sum(
        (a - mean_x) * (b - mean_y) for a, b in zip(x_ranks, y_ranks, strict=True)
    )
    var_x = sum((a - mean_x) ** 2 for a in x_ranks)
    var_y = sum((b - mean_y) ** 2 for b in y_ranks)
    if var_x <= 1e-12 or var_y <= 1e-12:
        return None
    return covariance / math.sqrt(var_x * var_y)


def _ranks(values: list[float]) -> list[float]:
    indexed = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position
        while (
            end + 1 < len(indexed)
            and values[indexed[end + 1]] == values[indexed[position]]
        ):
            end += 1
        average = (position + end) / 2.0 + 1.0
        for offset in range(position, end + 1):
            ranks[indexed[offset]] = average
        position = end + 1
    return ranks


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)
