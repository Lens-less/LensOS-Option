"""Canonical empirical-rank and VRP-band definitions.

These functions are deliberately small, strict, and shared.  A percentile or
band boundary that is reimplemented at a consumer boundary will eventually
drift, so callers must import this module instead of copying the arithmetic.
"""

from __future__ import annotations

import math


def empirical_percentile(*, current: float, history: list[float]) -> float:
    """Return the inclusive empirical rank of ``current`` in ``history``.

    Empty and non-finite inputs are undefined evidence, not zero-valued ranks.
    """
    if not history:
        raise ValueError("empirical percentile history must not be empty")
    values = [current, *history]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in values
    ):
        raise ValueError("empirical percentile values must be finite numbers")
    less_or_equal = sum(float(value) <= float(current) for value in history)
    return round(less_or_equal / len(history), 6)


def vrp_band_for_percentile(percentile: float) -> str:
    """Map a validated percentile fraction to the canonical internal VRP band."""
    if (
        isinstance(percentile, bool)
        or not isinstance(percentile, (int, float))
        or not math.isfinite(float(percentile))
        or not 0.0 <= float(percentile) <= 1.0
    ):
        raise ValueError("VRP percentile must be a finite fraction in 0..1")
    value = float(percentile)
    if value >= 0.90:
        return "extremely_expensive"
    if value >= 0.70:
        return "expensive"
    if value <= 0.10:
        return "extremely_thin"
    if value <= 0.30:
        return "thin"
    return "neutral"
