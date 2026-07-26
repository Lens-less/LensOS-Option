"""Tests for the ranking-signal validation harness.

The harness exists to answer whether a ranking axis predicts anything, so the
tests are built as a controlled experiment with a known answer rather than as
assertions about a fixture's incidental numbers. Two chains are generated from
the same price path:

* one where the quoted premium moves with the smile residual, so a seller really
  is paid more for the same risk and the signal must be detected;
* one where the residual is stamped on `mark_iv` only and never reaches the
  tradable quote — the exact failure mode that motivated the module, since an
  exchange's own mark smoothing produces precisely this — and the harness must
  report no detectable edge.

A harness that cannot separate those two cases would be worse than none.
"""

from __future__ import annotations

import math
import unittest
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from statistics import NormalDist

from crypto_options_report.signal_validation import (
    SIGNAL_VALIDATION_SCHEMA_VERSION,
    T_STAT_THRESHOLD,
    build_signal_validation_report,
)

_NORMAL = NormalDist()
_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

_HISTORY_START = date(2026, 1, 1)
_FIRST_EXPIRY = date(2026, 3, 12)
_EXPIRY_COUNT = 12
_EXPIRY_STRIDE_DAYS = 14
_SNAPSHOT_OFFSETS_DAYS = (21, 14, 7)
_MONEYNESS = (0.03, 0.05, 0.07, 0.09, 0.12, 0.15, 0.18, 0.21)


class _Deterministic:
    """A tiny linear congruential source so fixtures replay byte for byte."""

    def __init__(self, seed: int) -> None:
        self._state = seed % (2**31)

    def unit(self) -> float:
        self._state = (1103515245 * self._state + 12345) % (2**31)
        return self._state / float(2**31)

    def centred(self, magnitude: float) -> float:
        return (self.unit() - 0.5) * 2.0 * magnitude


def _black_scholes_call(
    spot: float, strike: float, iv_percent: float, dte_days: float
) -> float:
    sigma = iv_percent / 100.0
    years = max(dte_days / 365.0, 1e-9)
    denominator = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * years) / denominator
    d2 = d1 - denominator
    return spot * _NORMAL.cdf(d1) - strike * _NORMAL.cdf(d2)


def _instrument_name(expiry: date, strike: int) -> str:
    return f"BTC-{expiry.day}{_MONTHS[expiry.month - 1]}{expiry.year % 100:02d}-{strike}-C"


def _price_path(days: int, *, seed: int = 20260101) -> dict[date, float]:
    source = _Deterministic(seed)
    price = 100_000.0
    series: dict[date, float] = {}
    for offset in range(days):
        price *= math.exp(source.centred(0.03))
        series[_HISTORY_START + timedelta(days=offset)] = round(price, 2)
    return series


def _underlying_history(series: dict[date, float]) -> dict[str, object]:
    observations = [
        {
            "timestamp_ms": int(
                datetime.combine(day, time(0), tzinfo=UTC).timestamp() * 1000
            ),
            "observed_at": f"{day.isoformat()}T00:00:00Z",
            "close": close,
        }
        for day, close in sorted(series.items())
    ]
    return {
        "schema_version": "underlying_price_history.v1",
        "source": "test:deterministic-path",
        "instrument_name": "BTC-PERPETUAL",
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def _snapshot(
    *,
    captured_on: date,
    spot: float,
    expiry: date,
    seed: int,
    richness_reaches_quote: bool,
) -> dict[str, object]:
    """One chain snapshot with a deliberate per-strike richness perturbation.

    When `richness_reaches_quote` is false the perturbation lands on `mark_iv`
    but the bid and ask are priced off the unperturbed smile, reproducing a mark
    that carries no tradable information.
    """
    captured_at_dt = datetime.combine(captured_on, time(0, 0, 30), tzinfo=UTC)
    expiry_dt = datetime.combine(expiry, time(8), tzinfo=UTC)
    dte_days = (expiry_dt - captured_at_dt).total_seconds() / 86400.0
    timestamp_ms = int(captured_at_dt.timestamp() * 1000)
    source = _Deterministic(seed)

    rows = []
    for moneyness in _MONEYNESS:
        strike = int(round(spot * (1.0 + moneyness) / 1000.0) * 1000)
        log_moneyness = math.log(strike / spot)
        base_iv = 60.0 - 60.0 * log_moneyness
        richness = round(source.centred(0.6), 6)
        mark_iv = round(base_iv + richness, 6)
        pricing_iv = mark_iv if richness_reaches_quote else base_iv
        mark = _black_scholes_call(spot, strike, pricing_iv, dte_days)
        bid = round(mark * 0.98, 6)
        ask = round(mark * 1.02, 6)
        instrument_name = _instrument_name(expiry, strike)
        rows.append(
            {
                "instrument_name": instrument_name,
                "summary": {
                    "instrument_name": instrument_name,
                    "base_currency": "BTC",
                    "quote_currency": "USDC",
                    "settlement_currency": "USDC",
                    "bid_price": bid,
                    "ask_price": ask,
                    "mid_price": round((bid + ask) / 2.0, 6),
                    "mark_price": round(mark, 6),
                    "underlying_price": spot,
                    "open_interest": 50.0,
                    "creation_timestamp": timestamp_ms,
                },
                "ticker": {
                    "instrument_name": instrument_name,
                    "iv_unit": "percent_points",
                    "timestamp": timestamp_ms,
                    "best_bid_price": bid,
                    "best_ask_price": ask,
                    "best_bid_amount": 5.0,
                    "best_ask_amount": 5.0,
                    "mark_price": round(mark, 6),
                    "bid_iv": round(mark_iv - 0.5, 6),
                    "ask_iv": round(mark_iv + 0.5, 6),
                    "mark_iv": mark_iv,
                    "underlying_price": spot,
                    "open_interest": 50.0,
                },
            }
        )

    captured_at = captured_at_dt.isoformat().replace("+00:00", "Z")
    return {
        "captured_at": captured_at,
        "source": "test:synthetic-chain",
        "currency": "BTC",
        "feeds": {
            "vol_index": {
                "index_name": "BTC DVOL",
                "currency": "BTC",
                "timestamp": captured_at,
                "volatility": 0.62,
            }
        },
        "rows": rows,
    }


def _build_series(*, richness_reaches_quote: bool) -> tuple[list[dict], dict]:
    series = _price_path(days=300)
    snapshots = []
    for index in range(_EXPIRY_COUNT):
        expiry = _FIRST_EXPIRY + timedelta(days=_EXPIRY_STRIDE_DAYS * index)
        for offset in _SNAPSHOT_OFFSETS_DAYS:
            captured_on = expiry - timedelta(days=offset)
            spot = series[captured_on]
            snapshots.append(
                _snapshot(
                    captured_on=captured_on,
                    spot=spot,
                    expiry=expiry,
                    seed=7919 * (index + 1) + offset,
                    richness_reaches_quote=richness_reaches_quote,
                )
            )
    return snapshots, _underlying_history(series)


class SignalValidationHarnessTests(unittest.TestCase):
    def test_detects_a_signal_that_is_actually_paid_for(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["schema_version"], SIGNAL_VALIDATION_SCHEMA_VERSION)
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["reason_codes"], [])

        residual = report["signals"]["smile_residual_iv_points"]
        self.assertEqual(residual["status"], "measured")
        self.assertEqual(residual["evidence_verdict"], "positive_ic")
        self.assertGreater(residual["information_coefficient"]["mean"], 0.0)
        self.assertGreaterEqual(
            abs(residual["information_coefficient"]["t_stat"]), T_STAT_THRESHOLD
        )

    def test_reports_no_edge_when_the_residual_never_reaches_the_quote(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=False)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["status"], "measured")
        residual = report["signals"]["smile_residual_iv_points"]
        self.assertEqual(residual["status"], "measured")
        self.assertEqual(residual["evidence_verdict"], "no_detectable_edge")
        self.assertLess(
            abs(residual["information_coefficient"]["t_stat"]), T_STAT_THRESHOLD
        )
        self.assertEqual(
            report["summary"]["ranking_axis_verdict"], "no_detectable_edge"
        )

    def test_sample_size_is_counted_in_expiry_cohorts_not_observations(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        sample = report["sample"]
        self.assertEqual(sample["sample_size_basis"], "independent_expiry_cohorts")
        self.assertEqual(sample["independent_expiry_cohorts"], _EXPIRY_COUNT)
        # The observation count is far larger, and must never be the divisor
        # behind a t-statistic.
        self.assertGreater(sample["observation_count"], _EXPIRY_COUNT * 10)

        residual = report["signals"]["smile_residual_iv_points"]
        self.assertLessEqual(
            residual["effective_sample_size"], sample["independent_expiry_cohorts"]
        )

    def test_settlement_proxy_is_declared(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["sample"]["settlement_basis"], "daily_close_proxy")
        self.assertIn("08:00 UTC", report["sample"]["settlement_note"])

    def test_all_four_signals_are_measured_side_by_side(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(
            sorted(report["signals"]),
            [
                "iv_minus_trailing_realized_vol",
                "smile_residual_iv_points",
                "smile_residual_vega_usd",
                "smile_residual_z",
            ],
        )
        for name, item in sorted(report["signals"].items()):
            with self.subTest(signal=name):
                self.assertEqual(item["status"], "measured", name)
                self.assertTrue(item["buckets"])
                for bucket in item["buckets"]:
                    self.assertGreater(bucket["observation_count"], 0)
                    self.assertGreater(bucket["independent_expiry_cohorts"], 0)

    def test_bucket_table_orders_the_signal_monotonically(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        buckets = report["signals"]["smile_residual_iv_points"]["buckets"]
        self.assertEqual([row["bucket"] for row in buckets], [1, 2, 3, 4, 5])
        for left, right in pairwise(buckets):
            self.assertLessEqual(left["signal_max"], right["signal_min"] + 1e-9)


class MoneynessConfounderTests(unittest.TestCase):
    """The reason the published coefficient is the neutralized one.

    `iv_minus_trailing_realized_vol` is, within a single date, a monotone
    transform of mark IV and therefore of strike. Correlated raw against an
    outcome that is itself strongly ordered by strike, it scores near 0.95 even
    in the chain where the residual carries no tradable information whatsoever.
    Publishing that number would manufacture confidence out of a confounder.
    """

    def test_raw_coefficient_is_inflated_by_moneyness_alone(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=False)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        benchmark = report["signals"]["iv_minus_trailing_realized_vol"]
        self.assertGreater(benchmark["raw_information_coefficient"]["mean"], 0.8)
        self.assertLess(abs(benchmark["information_coefficient"]["mean"]), 0.2)
        self.assertEqual(benchmark["evidence_verdict"], "no_detectable_edge")
        self.assertIn(
            "moneyness-neutral",
            benchmark["raw_information_coefficient"]["warning"],
        )

    def test_published_coefficient_declares_its_neutralization(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        coefficient = report["signals"]["smile_residual_z"]["information_coefficient"]
        self.assertEqual(
            coefficient["neutralization"], "quadratic_in_log_moneyness_within_date"
        )
        self.assertIn("moneyness_neutral", coefficient["method"])


class SameDayDuplicateTests(unittest.TestCase):
    """A scheduled collector runs twice in a day more often than anyone plans for.

    Both captures carry the same snapshot date, so the duplicated instruments
    would land in one cross-section twice and the per-date rank correlation
    would be computed over a sample repeating its own rows.
    """

    def test_a_repeated_capture_does_not_inflate_the_cross_section(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        once = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        twice = build_signal_validation_report(
            snapshots=[*snapshots, *snapshots],
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(
            twice["sample"]["observation_count"],
            once["sample"]["observation_count"],
        )
        self.assertGreater(twice["sample"]["duplicate_observations_dropped"], 0)
        self.assertEqual(
            twice["signals"]["smile_residual_iv_points"]["information_coefficient"][
                "mean"
            ],
            once["signals"]["smile_residual_iv_points"]["information_coefficient"][
                "mean"
            ],
        )

    def test_a_clean_series_reports_no_duplicates(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["sample"]["duplicate_observations_dropped"], 0)


class SignalValidationFailClosedTests(unittest.TestCase):
    def test_blocks_without_underlying_history(self) -> None:
        snapshots, _ = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=None,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("MISSING_UNDERLYING_HISTORY", report["reason_codes"])
        self.assertEqual(report["signals"], {})

    def test_blocks_on_a_sample_too_small_to_publish(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots[:3],
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn(
            "INSUFFICIENT_INDEPENDENT_EXPIRY_COHORTS", report["reason_codes"]
        )
        self.assertEqual(report["signals"], {})
        self.assertIsNone(report["summary"]["best_signal"])

    def test_excludes_snapshots_whose_market_data_does_not_validate(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        broken = dict(snapshots[0])
        broken["rows"] = []
        series = [broken, *snapshots[1:]]

        report = build_signal_validation_report(
            snapshots=series,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        excluded = report["sample"]["excluded_snapshots"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["captured_at"], broken["captured_at"])
        self.assertEqual(
            report["sample"]["validated_snapshot_count"], len(snapshots) - 1
        )

    def test_never_emits_a_trade_or_sizing_surface(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertIs(report["research_only"], True)
        rendered = repr(report)
        for forbidden in (
            "recommended_size",
            "order_instruction",
            "execution_allowed",
            "post_only_price",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
