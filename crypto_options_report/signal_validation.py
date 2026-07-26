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

from .edge_score import find_atm_reference, normalize_premium_to_usd
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

# The axis pre-registered for promotion, recorded in docs/model-promotion.md §0
# on 2026-07-27 while zero of the eight required cohorts had settled.
#
# Ten signals are measured here and they collapse to about seven distinct
# orderings. Promoting whichever scores highest would be selection on the sample
# that produced the score, so exactly one axis was nominated in advance and the
# rest are exploratory: they can inform the *next* registration on a *later*
# sample, and can never be promoted from this one.
#
# It is surfaced beside the measurement rather than left in the document so the
# distinction is legible at the moment the coefficient appears, which is the
# moment it is most tempting to forget.
PRE_REGISTERED_AXIS = "smile_residual_z"
PRE_REGISTERED_AT = "2026-07-27"

# Above this mean pairwise rank correlation two signals order candidates the
# same way, whatever their economics claim to measure.
RANK_EQUIVALENCE_THRESHOLD = 0.95

ANNUALIZATION_DAYS = 365

INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_SIGNAL_OBSERVATIONS"
INSUFFICIENT_COHORTS = "INSUFFICIENT_INDEPENDENT_EXPIRY_COHORTS"
MISSING_UNDERLYING_HISTORY = "MISSING_UNDERLYING_HISTORY"
NO_VALIDATED_SNAPSHOTS = "NO_VALIDATED_SNAPSHOTS"
DEGENERATE_SIGNAL = "SIGNAL_HAS_NO_CROSS_SECTIONAL_VARIATION"

SETTLEMENT_BASIS = "daily_close_proxy"

# The band the product actually screens. Preflight uses it to separate cohorts
# that will answer the shipped question from short-dated ones that arrive sooner
# but describe a different tenor regime.
DEFAULT_SURFACE_MIN_DTE = 7.0
DEFAULT_SURFACE_MAX_DTE = 35.0

# Value signals are oriented so that a *higher* value means "the seller is being
# paid more than some reference says this option is worth". Keeping one
# orientation means a negative coefficient reads as "the ordering is backwards",
# never as an artefact of a signal defined upside down.
#
# The microstructure signals at the end have no such natural direction. Their
# orientation is fixed and published so that a negative coefficient is still
# interpretable as "the other direction wins" rather than as a sign error.
#
# Measuring them together is the point. Each is cheap once the observation
# exists, and running them in one pass answers "does the shipped axis earn its
# complexity" in the same sample rather than across three sequential ones.
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
    "iv_minus_dvol": (
        "mark IV minus the venue's own 30-day volatility index. The same "
        "premium claim as the trailing-volatility signal, but measured against "
        "what the market charges rather than against what the underlying did, "
        "so the two disagree exactly when the market is repricing."
    ),
    "tenor_iv_premium": (
        "this expiry's at-the-money fitted IV minus the mean across the chain's "
        "expiries, in IV points. Constant within an expiry, so it can only be "
        "measured on a date carrying more than one."
    ),
    "atm_relative_skew": (
        "fitted IV minus the same-expiry at-the-money fitted IV, per unit of "
        "log-moneyness: the local steepness of the smile at this strike. "
        "Strongly moneyness-correlated by construction, which is what the "
        "neutralized coefficient is there to strip out."
    ),
    "open_interest_share": (
        "this strike's open interest as a share of its expiry and option type. "
        "A crowding proxy; whether crowding helps or hurts a seller is the "
        "question, not the assumption."
    ),
    "depth_imbalance": (
        "quoted bid size minus ask size over their sum. Higher means more size "
        "resting on the side a seller lifts."
    ),
    "quote_tightness": (
        "the negated bid/ask spread ratio, so higher is tighter. A liquidity "
        "control: if it outranks the value signals, the ordering is finding "
        "execution cost rather than mispricing."
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
                dvol_iv_points=_dvol_iv_points(snapshot),
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
        "collinearity": _collinearity(observations, config=merged),
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


def build_signal_preflight_report(
    *,
    snapshots: list[dict[str, Any]],
    underlying_history: dict[str, Any] | None,
    generated_at: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What the accumulating capture series will yield, before it can be measured.

    The sample cannot be backfilled, so a defect in collection costs however long
    it goes unnoticed. Discovering after two months that every observation was
    dropped for an undeclared premium unit, or that a chain never fitted, would
    waste the entire wait.

    This walks the same surface construction the measurement uses and reports
    what each captured expiry would contribute once it settles - so a series
    producing nothing says so on day one rather than on day sixty.
    """
    merged = dict(DEFAULT_SIGNAL_VALIDATION_CONFIG)
    merged.update(config or {})
    closes_by_date, _ = _close_series(underlying_history)

    cohorts: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []

    for snapshot in sorted(
        [item for item in snapshots if isinstance(item, dict)],
        key=lambda item: str(item.get("captured_at") or ""),
    ):
        captured_at = str(snapshot.get("captured_at") or "")
        if not captured_at:
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
        for expiry in vol_surface_status.get("expiries") or []:
            if not isinstance(expiry, dict):
                continue
            expiry_date = str(expiry.get("expiry_date") or "")
            dte_days = expiry.get("dte_days")
            if not expiry_date or not isinstance(dte_days, (int, float)):
                continue
            points = list(expiry.get("surface_points") or []) + list(
                expiry.get("put_surface_points") or []
            )
            cohort = cohorts.setdefault(
                expiry_date,
                {
                    "expiry_date": expiry_date,
                    "capture_dates": [],
                    "observation_count": 0,
                    "dte_days_observed": [],
                    "fitted_captures": 0,
                    "blocking_reasons": {},
                },
            )
            cohort["capture_dates"].append(captured_at[:10])
            cohort["dte_days_observed"].append(round(float(dte_days), 3))
            if not expiry.get("candidate_eligible") and not expiry.get(
                "put_candidate_eligible"
            ):
                _count(cohort["blocking_reasons"], "SURFACE_NOT_ELIGIBLE")
                continue
            cohort["fitted_captures"] += 1
            for point in points:
                reason = _preflight_blocking_reason(point)
                if reason is None:
                    cohort["observation_count"] += 1
                else:
                    _count(cohort["blocking_reasons"], reason)

    rows = [_preflight_cohort(cohort, closes_by_date) for cohort in cohorts.values()]
    rows.sort(key=lambda row: row["expiry_date"])
    return {
        **_base(generated_at, merged),
        "status": "projected",
        "reason_codes": [],
        "snapshot_count": len(snapshots),
        "excluded_snapshots": excluded,
        "cohorts": rows,
        "bands": {
            band: _preflight_band(rows, band=band, config=merged)
            for band in ("research_window", "short_dated")
        },
        "note": (
            "Projected contributions, not measurements. A cohort counts only "
            "once its expiry has settled and the underlying history carries a "
            "close for that date."
        ),
    }


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _preflight_blocking_reason(point: dict[str, Any]) -> str | None:
    """Why this quote would not become an observation, checked today."""
    if _number(point.get("fit_residual_iv")) is None:
        return "MISSING_FIT_RESIDUAL"
    if _number(point.get("model_vega")) is None:
        return "MISSING_GREEKS"
    spot = _number(point.get("underlying_price"))
    if spot is None or spot <= 0:
        return "MISSING_UNDERLYING_PRICE"
    credit = normalize_premium_to_usd(
        _number(point.get("market_bid")),
        premium_unit=point.get("premium_unit"),
        underlying_price=spot,
    )
    if credit is None:
        return "PREMIUM_UNIT_UNKNOWN"
    if credit <= 0:
        return "NON_POSITIVE_BID"
    return None


def _preflight_cohort(
    cohort: dict[str, Any], closes_by_date: dict[str, float]
) -> dict[str, Any]:
    observed = cohort["dte_days_observed"]
    capture_dates = sorted(set(cohort["capture_dates"]))
    in_research = any(
        DEFAULT_SURFACE_MIN_DTE <= value <= DEFAULT_SURFACE_MAX_DTE
        for value in observed
    )
    return {
        "expiry_date": cohort["expiry_date"],
        "capture_date_count": len(capture_dates),
        "first_capture_date": capture_dates[0] if capture_dates else None,
        "last_capture_date": capture_dates[-1] if capture_dates else None,
        "dte_days_min": round(min(observed), 3) if observed else None,
        "dte_days_max": round(max(observed), 3) if observed else None,
        "band": "research_window" if in_research else "short_dated",
        "prospective_observation_count": cohort["observation_count"],
        "fitted_capture_count": cohort["fitted_captures"],
        # Settled means the expiry is behind us *and* the history carries the
        # close that settles it. Either alone is not enough.
        "settlement_close_available": cohort["expiry_date"] in closes_by_date,
        "blocking_reasons": dict(sorted(cohort["blocking_reasons"].items())),
    }


def _preflight_band(
    rows: list[dict[str, Any]], *, band: str, config: dict[str, Any]
) -> dict[str, Any]:
    in_band = [row for row in rows if row["band"] == band]
    settled = [row for row in in_band if row["settlement_close_available"]]
    pending = [row for row in in_band if not row["settlement_close_available"]]
    required = int(config["min_independent_cohorts"])
    return {
        "cohorts_seen": len(in_band),
        "settled_cohorts": len(settled),
        "pending_cohorts": len(pending),
        "cohorts_required": required,
        "cohorts_short_by": max(required - len(settled), 0),
        "settled_observation_count": sum(
            row["prospective_observation_count"] for row in settled
        ),
        "pending_observation_count": sum(
            row["prospective_observation_count"] for row in pending
        ),
        "next_pending_expiry": pending[0]["expiry_date"] if pending else None,
        "would_be_ready_after_expiry": (
            sorted(row["expiry_date"] for row in pending)[
                required - len(settled) - 1
            ]
            if len(pending) >= required - len(settled) > 0
            else None
        ),
    }


def _base(generated_at: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SIGNAL_VALIDATION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "config": dict(config),
        "t_stat_threshold": T_STAT_THRESHOLD,
        "pre_registration": {
            "axis": PRE_REGISTERED_AXIS,
            "registered_at": PRE_REGISTERED_AT,
            "threshold": T_STAT_THRESHOLD,
            "document": "docs/model-promotion.md",
            "note": (
                "Only this axis is eligible for promotion from this sample. "
                "Every other signal here is exploratory: a higher score on one "
                "of them informs the next registration, not this one."
            ),
        },
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


def _dvol_iv_points(snapshot: dict[str, Any]) -> float | None:
    """The venue's own volatility index, in IV points.

    The feed publishes both a fraction and a percent-point close. The declared
    unit is honoured rather than guessed, because a factor of 100 here would
    move the signal by more than any mispricing it is meant to detect.
    """
    feed = (snapshot.get("feeds") or {}).get("vol_index")
    if not isinstance(feed, dict):
        return None
    raw_close = feed.get("raw_close")
    if isinstance(raw_close, (int, float)) and not isinstance(raw_close, bool):
        if str(feed.get("raw_close_unit") or "") == "percent_points":
            return float(raw_close)
    volatility = feed.get("volatility")
    if isinstance(volatility, (int, float)) and not isinstance(volatility, bool):
        if str(feed.get("volatility_unit") or "") == "fraction":
            return round(float(volatility) * 100.0, 6)
    return None


def _expiry_contexts(
    expiries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-expiry aggregates the cross-expiry signals are measured against."""
    contexts: dict[str, dict[str, Any]] = {}
    for expiry in expiries:
        points = list(expiry.get("surface_points") or [])
        if not points:
            continue
        spot = _number((points[0] or {}).get("underlying_price"))
        atm = find_atm_reference(points, underlying_price=spot)
        open_interest_by_type: dict[str, float] = {}
        for point in points:
            option_type = str((point or {}).get("option_type") or "call")
            value = _number((point or {}).get("open_interest"))
            if value is not None:
                open_interest_by_type[option_type] = (
                    open_interest_by_type.get(option_type, 0.0) + value
                )
        contexts[str(expiry.get("expiry_date") or "")] = {
            "atm_fitted_iv": _number((atm or {}).get("surface_fitted_iv")),
            "open_interest_by_type": open_interest_by_type,
        }
    return contexts


def _observations_from_surface(
    *,
    vol_surface_status: dict[str, Any],
    captured_at: str,
    closes_by_date: dict[str, float],
    ordered_dates: list[str],
    dvol_iv_points: float | None,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    snapshot_date = captured_at[:10]
    trailing_vol = _trailing_realized_vol(
        closes_by_date=closes_by_date,
        ordered_dates=ordered_dates,
        as_of_date=snapshot_date,
        window_days=int(config["trailing_vol_window_days"]),
    )

    expiries = [
        expiry
        for expiry in (vol_surface_status.get("expiries") or [])
        if isinstance(expiry, dict) and expiry.get("candidate_eligible")
    ]
    contexts = _expiry_contexts(expiries)
    atm_levels = [
        context["atm_fitted_iv"]
        for context in contexts.values()
        if context["atm_fitted_iv"] is not None
    ]
    # The tenor premium is measured against the chain's own mean rather than
    # against its front expiry, so every expiry including the front gets a real
    # value instead of a degenerate zero.
    chain_mean_atm_iv = sum(atm_levels) / len(atm_levels) if atm_levels else None

    rows: list[dict[str, Any]] = []
    for expiry in expiries:
        expiry_date = str(expiry.get("expiry_date") or "")
        dte_days = expiry.get("dte_days")
        settlement = closes_by_date.get(expiry_date)
        if settlement is None or not isinstance(dte_days, (int, float)):
            continue
        if not (config["min_dte_days"] <= dte_days <= config["max_dte_days"]):
            continue
        if expiry_date <= snapshot_date:
            continue
        context = contexts.get(expiry_date) or {}
        for point in expiry.get("surface_points") or []:
            row = _observation(
                point=point,
                snapshot_date=snapshot_date,
                captured_at=captured_at,
                expiry_date=expiry_date,
                dte_days=float(dte_days),
                settlement_price=settlement,
                trailing_vol=trailing_vol,
                dvol_iv_points=dvol_iv_points,
                expiry_context=context,
                chain_mean_atm_iv=chain_mean_atm_iv,
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
    dvol_iv_points: float | None,
    expiry_context: dict[str, Any],
    chain_mean_atm_iv: float | None,
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
    log_moneyness = math.log(strike / spot)
    atm_fitted_iv = _number(expiry_context.get("atm_fitted_iv"))
    fitted_iv = _number(point.get("surface_fitted_iv"))
    signals: dict[str, float | None] = {
        "smile_residual_iv_points": residual,
        "smile_residual_z": _number(point.get("fit_residual_z")),
        "smile_residual_vega_usd": _number(point.get("fit_residual_vega_usd")),
        "iv_minus_trailing_realized_vol": (
            round(mark_iv - trailing_vol, 6)
            if mark_iv is not None and trailing_vol is not None
            else None
        ),
        "iv_minus_dvol": (
            round(mark_iv - dvol_iv_points, 6)
            if mark_iv is not None and dvol_iv_points is not None
            else None
        ),
        "tenor_iv_premium": (
            round(atm_fitted_iv - chain_mean_atm_iv, 6)
            if atm_fitted_iv is not None and chain_mean_atm_iv is not None
            else None
        ),
        "atm_relative_skew": _local_skew(
            fitted_iv=fitted_iv,
            atm_fitted_iv=atm_fitted_iv,
            log_moneyness=log_moneyness,
        ),
        "open_interest_share": _open_interest_share(point, expiry_context),
        "depth_imbalance": _depth_imbalance(point),
        "quote_tightness": (
            round(-_number(point.get("spread_ratio")), 6)
            if _number(point.get("spread_ratio")) is not None
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


def _local_skew(
    *,
    fitted_iv: float | None,
    atm_fitted_iv: float | None,
    log_moneyness: float,
) -> float | None:
    """Smile steepness at this strike, in IV points per unit log-moneyness.

    Undefined at the money, where the denominator vanishes and the ratio would
    explode rather than converge to the local slope.
    """
    if fitted_iv is None or atm_fitted_iv is None:
        return None
    if abs(log_moneyness) < 0.01:
        return None
    return round((fitted_iv - atm_fitted_iv) / log_moneyness, 6)


def _open_interest_share(
    point: dict[str, Any], expiry_context: dict[str, Any]
) -> float | None:
    """This strike's share of its expiry and option type's open interest."""
    value = _number(point.get("open_interest"))
    totals = expiry_context.get("open_interest_by_type")
    if value is None or not isinstance(totals, dict):
        return None
    total = totals.get(str(point.get("option_type") or "call"))
    if not isinstance(total, (int, float)) or total <= 0:
        return None
    return round(value / float(total), 8)


def _depth_imbalance(point: dict[str, Any]) -> float | None:
    """Resting bid size versus ask size, normalized to [-1, 1]."""
    bid = _number(point.get("best_bid_amount"))
    ask = _number(point.get("best_ask_amount"))
    if bid is None or ask is None:
        return None
    total = bid + ask
    if total <= 0:
        return None
    return round((bid - ask) / total, 8)


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


def _collinearity(
    observations: list[dict[str, Any]], *, config: dict[str, Any]
) -> dict[str, Any]:
    """Which of the measured signals are the same ordering wearing two names.

    Counting signals is not the same as counting information. Any signal of the
    form `mark_iv - c` where `c` is constant across a date produces identical
    ranks within that date, so measuring implied volatility against the venue's
    index and against trailing realized volatility yields one ordering, not two,
    however different the two references are as economics. The same collapse
    happens to anything constant within an expiry.

    Reporting the pairwise rank correlation makes that visible. Without it a
    reader counts ten signals, sees several agree, and reads the agreement as
    corroboration rather than as restatement.
    """
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        by_date.setdefault(row["snapshot_date"], []).append(row)

    names = sorted(SIGNAL_DEFINITIONS)
    totals: dict[tuple[str, str], list[float]] = {}
    for date in sorted(by_date):
        rows = by_date[date]
        if len(rows) < config["min_observations_per_date"]:
            continue
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                paired = [
                    (row["signals"][left], row["signals"][right])
                    for row in rows
                    if _is_measured(row["signals"].get(left))
                    and _is_measured(row["signals"].get(right))
                ]
                if len(paired) < 3:
                    continue
                correlation = _spearman(
                    [float(value) for value, _ in paired],
                    [float(value) for _, value in paired],
                )
                if correlation is not None:
                    totals.setdefault((left, right), []).append(correlation)

    pairs = [
        {
            "signals": [left, right],
            "mean_rank_correlation": round(sum(values) / len(values), 6),
            "measured_date_count": len(values),
        }
        for (left, right), values in sorted(totals.items())
    ]
    equivalent = [
        pair
        for pair in pairs
        if abs(pair["mean_rank_correlation"]) >= RANK_EQUIVALENCE_THRESHOLD
    ]
    return {
        "method": "mean_pairwise_spearman_within_date",
        "equivalence_threshold": RANK_EQUIVALENCE_THRESHOLD,
        "pairs": pairs,
        "rank_equivalent_pairs": equivalent,
        "distinct_signal_estimate": max(
            len(names) - len({pair["signals"][1] for pair in equivalent}), 0
        ),
        "note": (
            "Rank-equivalent signals produce the same ordering and therefore "
            "the same information coefficient. Their agreement is restatement, "
            "not corroboration."
        ),
    }


def _is_measured(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
    registered = signals.get(PRE_REGISTERED_AXIS, {})
    return {
        "signals_measured": len(measured),
        "signals_with_detectable_ic": len(detectable),
        # The strongest score in the set, which is *not* the promotable one
        # unless it happens to be the registered axis. Named as such so the two
        # are never confused.
        "best_exploratory_signal": best,
        "pre_registered_axis": PRE_REGISTERED_AXIS,
        "pre_registered_axis_verdict": registered.get("evidence_verdict"),
        "promotion_eligible": registered.get("evidence_verdict") == "positive_ic",
        "promotion_eligibility_basis": (
            "pre_registered_axis_only; see docs/model-promotion.md"
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
