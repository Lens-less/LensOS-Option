"""Realized return distribution derived from public underlying price history.

This is the physical-measure (P) counterpart to the risk-neutral (Q) quantities
in `surface.py`. A quoted implied vol tells you what the market charges; this
module tells you what the underlying actually did. Comparing the two is what
makes an absolute expected-value claim possible at all.

Statistical honesty is the whole point of this module:

* Horizon returns computed from a daily series necessarily use **overlapping**
  windows. With N observations and a T-day horizon you get N-T overlapping
  windows but only about N/T *independent* ones. Every count this module
  reports distinguishes the two, and the independent count is the one that may
  be used as a sample size. Reporting the overlapping count as the sample size
  would overstate confidence by roughly a factor of T.
* Thin samples fail closed. Below `MIN_INDEPENDENT_WINDOWS` the distribution is
  returned with `status="insufficient_history"` and no quantiles, rather than
  quantiles computed from too few points.
"""

from __future__ import annotations

import math
from typing import Any

REALIZED_RETURN_DISTRIBUTION_SCHEMA_VERSION = "realized_return_distribution.v1"

# Below this many *independent* horizon windows, quantiles are not reported.
# At 20 independent observations a 5% tail is represented by a single point, so
# this is already the floor of what can be claimed, not a comfortable sample.
MIN_INDEPENDENT_WINDOWS = 20

# Crypto trades continuously, so calendar days annualize directly.
ANNUALIZATION_DAYS = 365

INSUFFICIENT_HISTORY = "INSUFFICIENT_INDEPENDENT_WINDOWS"
INVALID_HISTORY = "INVALID_UNDERLYING_HISTORY"
NON_DAILY_RESOLUTION = "NON_DAILY_RESOLUTION"


def build_realized_return_distribution(
    *,
    history: dict[str, Any],
    horizon_days: int,
    generated_at: str,
) -> dict[str, Any]:
    """Summarize the underlying's realized `horizon_days` return distribution.

    `history` is the payload from
    `market_data.fetch_deribit_underlying_history`.
    """
    base = {
        "schema_version": REALIZED_RETURN_DISTRIBUTION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "horizon_days": horizon_days,
        "source": history.get("source") if isinstance(history, dict) else None,
    }

    closes, error = _closes_from_history(history)
    if error is not None:
        return {**base, **_blocked(error)}
    if not isinstance(horizon_days, int) or horizon_days <= 0:
        return {**base, **_blocked(INVALID_HISTORY)}

    resolution_seconds = history.get("resolution_seconds")
    if resolution_seconds != 86400:
        # Independent-window accounting below assumes one observation per day.
        return {**base, **_blocked(NON_DAILY_RESOLUTION)}

    observation_count = len(closes)
    overlapping_count = max(0, observation_count - horizon_days)
    # Stride by the horizon so no two windows share an observation. The strided
    # count can trail `observation_count // horizon_days` by one when the
    # observation count is an exact multiple of the horizon, so the gate and
    # every reported count must derive from this actual sample.
    independent_returns = [
        (closes[index + horizon_days] / closes[index]) - 1.0
        for index in range(0, overlapping_count, horizon_days)
    ]

    if overlapping_count <= 0 or len(independent_returns) < MIN_INDEPENDENT_WINDOWS:
        return {
            **base,
            **_blocked(INSUFFICIENT_HISTORY),
            "observation_count": observation_count,
            "overlapping_window_count": overlapping_count,
            "independent_window_count": len(independent_returns),
            "minimum_independent_windows": MIN_INDEPENDENT_WINDOWS,
        }

    overlapping_returns = [
        (closes[index + horizon_days] / closes[index]) - 1.0
        for index in range(overlapping_count)
    ]

    daily_log_returns = [
        math.log(closes[index + 1] / closes[index])
        for index in range(observation_count - 1)
    ]

    return {
        **base,
        "status": "validated",
        "reason_codes": [],
        "observation_count": observation_count,
        "first_observed_at": history.get("first_observed_at"),
        "last_observed_at": history.get("last_observed_at"),
        # Both counts are reported so a consumer cannot mistake one for the
        # other. `independent_window_count` is the only valid sample size.
        "overlapping_window_count": overlapping_count,
        "independent_window_count": len(independent_returns),
        "minimum_independent_windows": MIN_INDEPENDENT_WINDOWS,
        "sample_size_basis": "independent_non_overlapping_windows",
        "realized_volatility_annualized": annualized_volatility(daily_log_returns),
        "horizon_return_quantiles": _quantiles(overlapping_returns),
        "independent_horizon_return_quantiles": _quantiles(independent_returns),
        "mean_horizon_return": _mean(overlapping_returns),
        "overlapping_returns": overlapping_returns,
        "independent_returns": independent_returns,
    }


def upside_breach_frequency(
    distribution: dict[str, Any],
    *,
    threshold_return: float,
) -> dict[str, Any]:
    """Historical frequency of a horizon return at or above `threshold_return`.

    This is a frequency observed in the sample, not a probability forecast, and
    it is reported against the independent-window count so the reader can see
    how few observations stand behind it.
    """
    if distribution.get("status") != "validated":
        return {
            "status": "unavailable",
            "reason_code": distribution.get("reason_code") or INSUFFICIENT_HISTORY,
            "frequency": None,
            "breach_count": None,
            "sample_size": None,
        }

    independent = distribution.get("independent_returns") or []
    breaches = sum(1 for value in independent if value >= threshold_return)
    sample = len(independent)
    return {
        "status": "validated",
        "reason_code": None,
        "measure": "physical_sample_frequency",
        "threshold_return": threshold_return,
        "breach_count": breaches,
        "sample_size": sample,
        "sample_size_basis": "independent_non_overlapping_windows",
        "frequency": (breaches / sample) if sample else None,
    }


def _closes_from_history(history: Any) -> tuple[list[float], str | None]:
    if not isinstance(history, dict):
        return [], INVALID_HISTORY
    observations = history.get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        return [], INVALID_HISTORY
    closes: list[float] = []
    for row in observations:
        if not isinstance(row, dict):
            return [], INVALID_HISTORY
        close = row.get("close")
        if not isinstance(close, (int, float)) or close <= 0:
            return [], INVALID_HISTORY
        closes.append(float(close))
    return closes, None


def _blocked(reason_code: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason_code": reason_code,
        "reason_codes": [reason_code],
        "realized_volatility_annualized": None,
        "horizon_return_quantiles": None,
        "independent_horizon_return_quantiles": None,
        "overlapping_returns": [],
        "independent_returns": [],
    }


def annualized_volatility(log_returns: list[float]) -> float | None:
    """Return sample standard deviation annualized on crypto calendar days."""
    if len(log_returns) < 2:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((value - mean) ** 2 for value in log_returns) / (
        len(log_returns) - 1
    )
    return math.sqrt(variance) * math.sqrt(ANNUALIZATION_DAYS)


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        f"p{int(q * 100):02d}": _percentile(ordered, q)
        for q in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
    }


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
