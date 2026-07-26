"""One instrument's readings across the capture series, rather than one snapshot.

Every other surface in this product answers a question about now. The daily
capture has been accumulating for the validation sample, and it already contains
the answer to a different question that nothing was asking: *was this strike
rich yesterday too?*

Four things make that question easy to answer wrongly, and each is handled here
rather than left to the reader:

* **Persistence is not evidence of opportunity.** A residual that is positive
  every single day is at least as likely to mean the fitted smile is
  systematically wrong at that strike — a quadratic cannot follow a real wing —
  as it is to mean the market is. The report says so beside the number, because
  a chart of persistent richness is exactly what a model artifact looks like.
* **Raw implied volatility is not comparable across days.** An instrument's time
  to expiry shrinks every capture, so its IV, its delta and its premium all move
  for reasons that have nothing to do with mispricing. The standardized residual
  is comparable by construction, so it is the series this module leads with, and
  the raw figures travel as context.
* **A gap is not a zero.** The collector selects roughly a hundred of several
  hundred listed instruments, and which ones it picks moves with spot, so an
  instrument can simply be absent from a capture. Absent dates are reported as
  absent; nothing is interpolated across them.
* **Two captures on one day are one observation.** The scheduled job retries,
  and a day with two captures must not become a day with two readings.
"""

from __future__ import annotations

import math
from typing import Any

from .edge_score import normalize_premium_to_usd
from .market_data import build_market_data_status, parse_timestamp_ms
from .surface import build_vol_surface_and_candidate_research

SERIES_HISTORY_SCHEMA_VERSION = "instrument_series_history.v1"

DEFAULT_SERIES_CONFIG = {
    # Below this many distinct capture dates a series is a couple of points and
    # a line drawn through them implies a trend that is not there.
    "min_capture_dates": 3,
    # Instruments are ranked for display by how persistently rich they read;
    # the whole set is still published, this only orders it.
    "max_instruments": 60,
}

NO_VALIDATED_CAPTURES = "NO_VALIDATED_CAPTURES"
INSUFFICIENT_CAPTURE_DATES = "INSUFFICIENT_CAPTURE_DATES"

# Shrinkage constant for the display ordering: a series' mean is pulled toward
# zero by `n / (n + PRIOR)`. Published because it changes what appears at the top
# of the list, which makes it a contract rather than a tuning knob. At this value
# a three-observation mean keeps under 40% of its size while a forty-observation
# one keeps almost 90%.
PERSISTENCE_PRIOR_OBSERVATIONS = 5.0


def build_series_history_report(
    *,
    snapshots: list[dict[str, Any]],
    generated_at: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-instrument readings across every validated capture in the series."""
    merged = dict(DEFAULT_SERIES_CONFIG)
    merged.update(config or {})

    readings: dict[str, dict[str, dict[str, Any]]] = {}
    capture_dates: list[str] = []
    excluded: list[dict[str, Any]] = []

    for snapshot in sorted(
        [item for item in snapshots if isinstance(item, dict)],
        key=lambda item: str(item.get("captured_at") or ""),
    ):
        captured_at = str(snapshot.get("captured_at") or "")
        if not captured_at:
            continue
        try:
            now_ms = parse_timestamp_ms(captured_at)
        except (ValueError, TypeError):
            excluded.append(
                {"captured_at": captured_at, "reason_code": "UNPARSEABLE_CAPTURED_AT"}
            )
            continue

        data_status = build_market_data_status(snapshot, now_ms=now_ms)
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
        date = captured_at[:10]
        if date not in capture_dates:
            capture_dates.append(date)

        for expiry in vol_surface_status.get("expiries") or []:
            if not isinstance(expiry, dict):
                continue
            points = list(expiry.get("surface_points") or []) + list(
                expiry.get("put_surface_points") or []
            )
            for point in points:
                reading = _reading(point, captured_at=captured_at, expiry=expiry)
                if reading is None:
                    continue
                # Later captures on one date replace earlier ones: a retry must
                # not become a second observation of the same day.
                readings.setdefault(reading["instrument_name"], {})[date] = reading

    if not capture_dates:
        return {
            **_base(generated_at, merged),
            "status": "blocked",
            "reason_codes": [NO_VALIDATED_CAPTURES],
            "capture_dates": [],
            "instruments": [],
            "excluded_captures": excluded,
        }

    ordered_dates = sorted(capture_dates)
    instruments = [
        series
        for series in (
            _series(name, by_date, ordered_dates)
            for name, by_date in sorted(readings.items())
        )
        if series["capture_date_count"] >= merged["min_capture_dates"]
    ]
    # Ordered by the shrunk mean, not the raw one. Sorting on the raw mean puts
    # the thinnest series on top: an instrument seen on three of fifty-nine
    # dates outranks one seen on forty, because three readings can average
    # anything. Shrinking toward zero by observation count is the same sample-size
    # discipline this product applies everywhere else, moved into the display
    # order so the top of the list is not simply the noisiest row.
    instruments.sort(
        key=lambda series: (
            -(series["persistence"]["shrunk_mean"] or float("-inf")),
            series["instrument_name"],
        )
    )

    return {
        **_base(generated_at, merged),
        "status": "measured" if instruments else "blocked",
        "reason_codes": [] if instruments else [INSUFFICIENT_CAPTURE_DATES],
        "capture_dates": ordered_dates,
        "capture_count": len(ordered_dates),
        "instrument_count": len(instruments),
        "instruments": instruments[: int(merged["max_instruments"])],
        "truncated_instruments": max(
            len(instruments) - int(merged["max_instruments"]), 0
        ),
        "excluded_captures": excluded,
        "cannot_tell": [
            "A residual that stays positive is as consistent with a smile the "
            "quadratic fit cannot follow at that strike as it is with a market "
            "that keeps mispricing it. Persistence narrows nothing on its own.",
            "Raw implied volatility, delta and premium all move as an "
            "instrument ages, so only the standardized residual is comparable "
            "across capture dates.",
            "Absent dates mean the collector did not select that instrument "
            "that day; they are not zero readings and nothing is interpolated "
            "across them.",
            "Nothing here is a forecast. Whether any of these orderings predict "
            "anything is what the signal validation measures.",
        ],
    }


def _base(generated_at: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SERIES_HISTORY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "config": dict(config),
        "primary_series": "residual_z",
        "primary_series_reason": (
            "standardized by each expiry's own residual scale, so it is "
            "comparable between capture dates and between chains"
        ),
    }


def _reading(
    point: dict[str, Any], *, captured_at: str, expiry: dict[str, Any]
) -> dict[str, Any] | None:
    name = point.get("instrument_name")
    residual_z = _number(point.get("fit_residual_z"))
    if not name or residual_z is None:
        return None
    spot = _number(point.get("underlying_price"))
    bid = _number(point.get("market_bid"))
    return {
        "instrument_name": str(name),
        "captured_at": captured_at,
        "expiry_date": str(expiry.get("expiry_date") or ""),
        "dte_days": _number(expiry.get("dte_days")),
        "option_type": point.get("option_type"),
        "strike_price": _number(point.get("strike_price")),
        "underlying_price": spot,
        "residual_z": residual_z,
        "residual_iv_points": _number(point.get("fit_residual_iv")),
        "mark_iv": _number(point.get("market_mark_iv")),
        "model_delta": _number(point.get("model_delta")),
        "open_interest": _number(point.get("open_interest")),
        "bid_usdc": normalize_premium_to_usd(
            bid,
            premium_unit=point.get("premium_unit"),
            underlying_price=spot,
        ),
    }


def _series(
    instrument_name: str,
    by_date: dict[str, dict[str, Any]],
    ordered_dates: list[str],
) -> dict[str, Any]:
    """One instrument aligned to the series' capture calendar, gaps included."""
    points = [
        {
            "date": date,
            "present": date in by_date,
            **(
                {
                    key: by_date[date][key]
                    for key in (
                        "residual_z",
                        "residual_iv_points",
                        "mark_iv",
                        "model_delta",
                        "bid_usdc",
                        "dte_days",
                        "open_interest",
                        "underlying_price",
                    )
                }
                if date in by_date
                else {}
            ),
        }
        for date in ordered_dates
    ]
    observed = [by_date[date]["residual_z"] for date in sorted(by_date)]
    latest = by_date[sorted(by_date)[-1]]

    return {
        "instrument_name": instrument_name,
        "expiry_date": latest["expiry_date"],
        "option_type": latest["option_type"],
        "strike_price": latest["strike_price"],
        "capture_date_count": len(by_date),
        "missing_date_count": len(ordered_dates) - len(by_date),
        "latest": {
            "date": sorted(by_date)[-1],
            "residual_z": latest["residual_z"],
            "dte_days": latest["dte_days"],
            "model_delta": latest["model_delta"],
            "bid_usdc": latest["bid_usdc"],
        },
        "residual_z": _summarize(observed),
        "persistence": _persistence(observed, len(ordered_dates)),
        "points": points,
    }


def _persistence(values: list[float], capture_date_count: int) -> dict[str, Any]:
    """The display ordering, with everything that produced it on the record.

    `shrunk_mean` is the raw mean pulled toward zero by observation count. It is
    an ordering, not a statistic about the market: consecutive daily readings of
    one instrument are heavily autocorrelated, so nothing here should be read as
    a standard error or a significance test. It exists so a three-reading average
    does not sit above a forty-reading one.
    """
    if not values:
        return {
            "shrunk_mean": None,
            "raw_mean": None,
            "coverage": None,
            "prior_observations": PERSISTENCE_PRIOR_OBSERVATIONS,
        }
    count = len(values)
    raw_mean = sum(values) / count
    weight = count / (count + PERSISTENCE_PRIOR_OBSERVATIONS)
    return {
        "shrunk_mean": round(raw_mean * weight, 6),
        "raw_mean": round(raw_mean, 6),
        "shrinkage_weight": round(weight, 6),
        "coverage": (
            round(count / capture_date_count, 6) if capture_date_count else None
        ),
        "prior_observations": PERSISTENCE_PRIOR_OBSERVATIONS,
        "basis": "mean_shrunk_toward_zero_by_observation_count",
        "not_a_significance_test": (
            "Daily readings of one instrument are autocorrelated; this is a "
            "display ordering, not a standard error."
        ),
    }


def _summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": None, "min": None, "max": None, "positive_share": None}
    mean = sum(values) / len(values)
    return {
        "mean": round(mean, 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        # How often it read rich at all. Reported beside the mean because one
        # large day and a persistent tilt produce the same average.
        "positive_share": round(
            sum(1 for value in values if value > 0) / len(values), 6
        ),
        "observation_count": len(values),
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)
