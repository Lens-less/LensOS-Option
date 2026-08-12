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

import copy
import math
import unittest
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from statistics import NormalDist

from crypto_options_report.market_data import (
    build_market_data_status,
    normalize_market_snapshot,
    parse_timestamp_ms,
)
from crypto_options_report.signal_validation import (
    PRE_REGISTERED_AXIS,
    RANK_EQUIVALENCE_THRESHOLD,
    SIGNAL_DEFINITIONS,
    SIGNAL_VALIDATION_SCHEMA_VERSION,
    T_STAT_THRESHOLD,
    build_signal_preflight_report,
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
_SNAPSHOT_OFFSETS_DAYS = (7, 28)
_CAPTURE_STRIDE_DAYS = 3
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


def _expiry_rows(
    *,
    captured_at_dt: datetime,
    spot: float,
    expiry: date,
    seed: int,
    richness_reaches_quote: bool,
    term_shift: float,
) -> list[dict]:
    """One expiry's quotes, with a deliberate per-strike richness perturbation.

    When `richness_reaches_quote` is false the perturbation lands on `mark_iv`
    but the bid and ask are priced off the unperturbed smile, reproducing a mark
    that carries no tradable information.

    Open interest, resting size and quote width vary across strikes rather than
    being constant, because a chain where they do not vary cannot exercise the
    microstructure signals at all — they would be flat within every date and
    silently skipped.
    """
    expiry_dt = datetime.combine(expiry, time(8), tzinfo=UTC)
    dte_days = (expiry_dt - captured_at_dt).total_seconds() / 86400.0
    timestamp_ms = int(captured_at_dt.timestamp() * 1000)
    source = _Deterministic(seed)

    rows = []
    for moneyness in _MONEYNESS:
        strike = int(round(spot * (1.0 + moneyness) / 1000.0) * 1000)
        log_moneyness = math.log(strike / spot)
        base_iv = 60.0 + term_shift - 60.0 * log_moneyness
        richness = round(source.centred(0.6), 6)
        mark_iv = round(base_iv + richness, 6)
        pricing_iv = mark_iv if richness_reaches_quote else base_iv
        mark = _black_scholes_call(spot, strike, pricing_iv, dte_days)
        half_spread = 0.02 + 0.01 * source.unit()
        bid = round(mark * (1.0 - half_spread), 6)
        ask = round(mark * (1.0 + half_spread), 6)
        open_interest = round(20.0 + 180.0 * source.unit(), 4)
        bid_amount = round(2.0 + 8.0 * source.unit(), 4)
        ask_amount = round(2.0 + 8.0 * source.unit(), 4)
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
                    "open_interest": open_interest,
                    "creation_timestamp": timestamp_ms,
                },
                "ticker": {
                    "instrument_name": instrument_name,
                    "iv_unit": "percent_points",
                    "timestamp": timestamp_ms,
                    "best_bid_price": bid,
                    "best_ask_price": ask,
                    "best_bid_amount": bid_amount,
                    "best_ask_amount": ask_amount,
                    "mark_price": round(mark, 6),
                    "bid_iv": round(mark_iv - 0.5, 6),
                    "ask_iv": round(mark_iv + 0.5, 6),
                    "mark_iv": mark_iv,
                    "underlying_price": spot,
                    "open_interest": open_interest,
                },
            }
        )
    return rows


def _snapshot(
    *,
    captured_on: date,
    spot: float,
    expiries: list[date],
    seed: int,
    richness_reaches_quote: bool,
) -> dict[str, object]:
    """One capture, carrying every expiry currently inside the research window.

    A real snapshot lists several expiries at once, and a fixture carrying one
    at a time cannot exercise any cross-expiry signal: the term premium would be
    identically zero on every row.
    """
    captured_at_dt = datetime.combine(captured_on, time(0, 0, 30), tzinfo=UTC)
    rows: list[dict] = []
    for index, expiry in enumerate(sorted(expiries)):
        rows.extend(
            _expiry_rows(
                captured_at_dt=captured_at_dt,
                spot=spot,
                expiry=expiry,
                seed=seed + 7919 * (index + 1),
                richness_reaches_quote=richness_reaches_quote,
                # A rising term structure, so the tenor premium has something to
                # rank rather than being flat across the chain.
                term_shift=1.5 * index,
            )
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
                "raw_close": 58.0,
                "raw_close_unit": "percent_points",
                "volatility": 0.58,
                "volatility_unit": "fraction",
            }
        },
        "rows": rows,
    }


def _build_series(*, richness_reaches_quote: bool) -> tuple[list[dict], dict]:
    series = _price_path(days=300)
    expiries = [
        _FIRST_EXPIRY + timedelta(days=_EXPIRY_STRIDE_DAYS * index)
        for index in range(_EXPIRY_COUNT)
    ]
    first_capture = _FIRST_EXPIRY - timedelta(days=max(_SNAPSHOT_OFFSETS_DAYS))
    last_capture = expiries[-1] - timedelta(days=min(_SNAPSHOT_OFFSETS_DAYS))

    snapshots = []
    captured_on = first_capture
    step = 0
    while captured_on <= last_capture:
        in_window = [
            expiry
            for expiry in expiries
            if min(_SNAPSHOT_OFFSETS_DAYS)
            <= (expiry - captured_on).days
            <= max(_SNAPSHOT_OFFSETS_DAYS)
        ]
        if in_window and captured_on in series:
            snapshots.append(
                _snapshot(
                    captured_on=captured_on,
                    spot=series[captured_on],
                    expiries=in_window,
                    seed=104_729 + 31 * step,
                    richness_reaches_quote=richness_reaches_quote,
                )
            )
        captured_on += timedelta(days=_CAPTURE_STRIDE_DAYS)
        step += 1
    return snapshots, _underlying_history(series)


def _partially_blocked_snapshot(snapshot: dict) -> tuple[dict, str, set[str]]:
    """Make one expiry fail its quote gate while leaving peer expiries healthy."""
    broken = copy.deepcopy(snapshot)
    captured_at = str(broken["captured_at"])
    normalized = normalize_market_snapshot(
        broken,
        now_ms=parse_timestamp_ms(captured_at),
    )
    expiry_names: dict[str, set[str]] = {}
    for quote in normalized["quotes"]:
        expiry_names.setdefault(str(quote["expiry_date"]), set()).add(
            str(quote["instrument_name"])
        )
    if len(expiry_names) < 2:
        raise AssertionError("partial-expiry fixture needs at least two expiries")

    failed_expiry = sorted(expiry_names)[0]
    failed_names = expiry_names[failed_expiry]
    for row in broken["rows"]:
        if row["instrument_name"] in failed_names:
            row["ticker"]["bid_iv"] = None
    return broken, failed_expiry, set(expiry_names) - {failed_expiry}


def _first_multi_expiry_snapshot(snapshots: list[dict]) -> dict:
    return next(
        snapshot
        for snapshot in snapshots
        if len(
            {
                row["instrument_name"].split("-")[1]
                for row in snapshot["rows"]
            }
        )
        >= 2
    )


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
            report["summary"]["pre_registered_axis_verdict"], "no_detectable_edge"
        )
        self.assertIs(report["summary"]["promotion_eligible"], False)

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

    def test_every_declared_signal_is_measured_in_one_pass(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(sorted(report["signals"]), sorted(SIGNAL_DEFINITIONS))
        for name, item in sorted(report["signals"].items()):
            with self.subTest(signal=name):
                self.assertEqual(item["status"], "measured", name)
                self.assertTrue(item["buckets"])
                for bucket in item["buckets"]:
                    self.assertGreater(bucket["observation_count"], 0)
                    self.assertGreater(bucket["independent_expiry_cohorts"], 0)

    def test_cross_expiry_signals_need_a_multi_expiry_chain(self) -> None:
        """The tenor premium is identically zero on a one-expiry capture."""
        snapshots, history = _build_series(richness_reaches_quote=True)
        for snapshot in snapshots:
            first = snapshot["rows"][0]["instrument_name"].split("-")[1]
            snapshot["rows"] = [
                row
                for row in snapshot["rows"]
                if row["instrument_name"].split("-")[1] == first
            ]

        report = build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        tenor = report["signals"]["tenor_iv_premium"]
        self.assertEqual(tenor["status"], "blocked")
        self.assertEqual(
            tenor["reason_code"], "SIGNAL_HAS_NO_CROSS_SECTIONAL_VARIATION"
        )

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
        raw = benchmark["raw_information_coefficient"]["mean"]
        neutral = benchmark["information_coefficient"]["mean"]

        # Raw, it looks like one of the strongest orderings available.
        self.assertGreater(raw, 0.8)
        # Neutralized, most of that disappears: the gap is the confounder's
        # size, and it is far larger than whatever survives it.
        self.assertGreater(raw - abs(neutral), 0.5)
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


class PreflightTests(unittest.TestCase):
    """A sample that cannot be backfilled must be monitored while it accumulates.

    A defect in collection costs however long it goes unnoticed. Discovering
    after two months that every quote was dropped for an undeclared premium unit
    would waste the entire wait, so the projection walks the same surface
    construction the measurement uses and reports what each captured expiry
    would contribute once it settles.
    """

    def test_settled_cohorts_are_counted_once_the_history_covers_them(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_preflight_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(report["status"], "projected")
        self.assertTrue(report["cohorts"])
        for cohort in report["cohorts"]:
            with self.subTest(expiry=cohort["expiry_date"]):
                self.assertTrue(cohort["settlement_close_available"])
                self.assertGreater(cohort["prospective_observation_count"], 0)

    def test_a_failed_expiry_is_isolated_from_healthy_preflight_cohorts(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        partial, failed_expiry, passing_expiries = _partially_blocked_snapshot(
            _first_multi_expiry_snapshot(snapshots)
        )
        status = build_market_data_status(
            partial,
            now_ms=parse_timestamp_ms(partial["captured_at"]),
        )
        self.assertEqual("blocked", status["status"])

        report = build_signal_preflight_report(
            snapshots=[partial],
            underlying_history=history,
            generated_at=partial["captured_at"],
        )

        self.assertEqual("projected", report["status"])
        self.assertTrue(report["cohorts"])
        self.assertNotIn(
            failed_expiry,
            {row["expiry_date"] for row in report["cohorts"]},
        )
        self.assertTrue(
            {row["expiry_date"] for row in report["cohorts"]}
            <= passing_expiries
        )
        self.assertEqual(failed_expiry, report["excluded_expiries"][0]["expiry_date"])
        self.assertIn(partial["captured_at"][:10], report["usable_capture_dates"])

    def test_an_expiry_with_no_settlement_close_is_pending_not_dropped(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        # Truncate the history so the last expiries have not settled yet, which
        # is the state a live capture series sits in for weeks.
        history["observations"] = history["observations"][:120]

        report = build_signal_preflight_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        band = report["bands"]["research_window"]
        self.assertGreater(band["pending_cohorts"], 0)
        self.assertGreater(band["pending_observation_count"], 0)
        self.assertEqual(
            band["cohorts_short_by"],
            max(band["cohorts_required"] - band["settled_cohorts"], 0),
        )

    def test_unusable_quotes_are_reported_as_named_blocking_reasons(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        for snapshot in snapshots:
            for row in snapshot["rows"]:
                row["summary"]["quote_currency"] = "UNKNOWN"
                row["summary"]["settlement_currency"] = "UNKNOWN"

        report = build_signal_preflight_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        # Either the chain stops validating outright or the quotes are named as
        # unusable; silently producing zero observations with no reason is the
        # outcome this exists to prevent.
        blocked = report["excluded_snapshots"] or [
            cohort
            for cohort in report["cohorts"]
            if cohort["blocking_reasons"]
            or cohort["prospective_observation_count"] == 0
        ]
        self.assertTrue(blocked)

    def test_the_projection_declares_that_it_is_not_a_measurement(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)

        report = build_signal_preflight_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertIn("not measurements", report["note"])
        self.assertNotIn("signals", report)


class PreRegistrationTests(unittest.TestCase):
    """Ten signals are measured; exactly one was nominated in advance.

    Promoting whichever scored highest would be selection on the sample that
    produced the score, and at roughly seven distinct orderings a conventional
    threshold produces a winner from noise often enough to matter. The
    registration is surfaced beside the measurement rather than left in a
    document, because the moment the coefficient appears is the moment the
    distinction is most tempting to forget.
    """

    def _report(self, *, reaches_quote: bool) -> dict:
        snapshots, history = _build_series(richness_reaches_quote=reaches_quote)
        return build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

    def test_the_registered_axis_travels_with_the_measurement(self) -> None:
        registration = self._report(reaches_quote=True)["pre_registration"]

        self.assertEqual(registration["axis"], PRE_REGISTERED_AXIS)
        self.assertEqual(registration["threshold"], T_STAT_THRESHOLD)
        self.assertEqual(registration["document"], "docs/model-promotion.md")
        self.assertIn("exploratory", registration["note"])

    def test_the_registered_axis_is_one_the_product_actually_ranks_on(self) -> None:
        self.assertIn(PRE_REGISTERED_AXIS, SIGNAL_DEFINITIONS)

    def test_eligibility_follows_the_registered_axis_not_the_best_score(
        self,
    ) -> None:
        report = self._report(reaches_quote=True)
        summary = report["summary"]

        self.assertEqual(summary["pre_registered_axis"], PRE_REGISTERED_AXIS)
        self.assertEqual(
            summary["promotion_eligible"],
            report["signals"][PRE_REGISTERED_AXIS]["evidence_verdict"]
            == "positive_ic",
        )

    def test_the_strongest_signal_is_labelled_exploratory(self) -> None:
        """`tenor_iv_premium` outscores the registered axis in this fixture.

        It is still not promotable, and the summary key says so in its name.
        """
        summary = self._report(reaches_quote=True)["summary"]

        self.assertIn("best_exploratory_signal", summary)
        self.assertNotIn("best_signal", summary)

    def test_a_dead_registered_axis_is_not_rescued_by_a_live_other_one(
        self,
    ) -> None:
        report = self._report(reaches_quote=False)

        # In this arm the residual carries nothing, while the tenor premium
        # still scores: promotion must follow the registration regardless.
        self.assertIs(report["summary"]["promotion_eligible"], False)
        self.assertGreater(report["summary"]["signals_with_detectable_ic"], 0)


class CollinearityTests(unittest.TestCase):
    """Counting signals is not counting information.

    Any signal of the form `mark_iv - c`, where `c` is constant across a date,
    produces identical ranks within that date. Measuring implied volatility
    against the venue's index and against trailing realized volatility is one
    ordering wearing two names, however different the two references are as
    economics. Without this block a reader counts ten signals, sees several
    agree, and reads restatement as corroboration.
    """

    def _report(self) -> dict:
        snapshots, history = _build_series(richness_reaches_quote=True)
        return build_signal_validation_report(
            snapshots=snapshots,
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

    def test_two_references_subtracted_from_iv_are_one_ordering(self) -> None:
        pairs = {
            tuple(pair["signals"]): pair["mean_rank_correlation"]
            for pair in self._report()["collinearity"]["pairs"]
        }

        correlation = pairs[
            ("iv_minus_dvol", "iv_minus_trailing_realized_vol")
        ]
        self.assertAlmostEqual(correlation, 1.0, places=6)

    def test_rank_equivalent_pairs_are_called_out(self) -> None:
        collinearity = self._report()["collinearity"]

        equivalent = {
            tuple(pair["signals"]) for pair in collinearity["rank_equivalent_pairs"]
        }
        self.assertIn(
            ("iv_minus_dvol", "iv_minus_trailing_realized_vol"), equivalent
        )
        for pair in collinearity["rank_equivalent_pairs"]:
            self.assertGreaterEqual(
                abs(pair["mean_rank_correlation"]), RANK_EQUIVALENCE_THRESHOLD
            )

    def test_the_distinct_estimate_is_below_the_declared_count(self) -> None:
        report = self._report()

        self.assertLess(
            report["collinearity"]["distinct_signal_estimate"],
            len(SIGNAL_DEFINITIONS),
        )

    def test_rank_equivalent_signals_report_the_same_coefficient(self) -> None:
        """The consequence: their agreement carries no extra evidence."""
        report = self._report()

        left = report["signals"]["iv_minus_dvol"]["information_coefficient"]
        right = report["signals"]["iv_minus_trailing_realized_vol"][
            "information_coefficient"
        ]
        self.assertEqual(left["mean"], right["mean"])
        self.assertEqual(left["t_stat"], right["t_stat"])


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
        self.assertNotIn("best_signal", report["summary"])
        self.assertIsNone(report["summary"]["best_exploratory_signal"])
        self.assertEqual(report["summary"]["pre_registered_axis"], PRE_REGISTERED_AXIS)
        self.assertIs(report["summary"]["promotion_eligible"], False)

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

    def test_measurement_counts_a_partially_usable_snapshot(self) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        source = _first_multi_expiry_snapshot(snapshots)
        partial, failed_expiry, _ = _partially_blocked_snapshot(source)
        source_index = snapshots.index(source)

        report = build_signal_validation_report(
            snapshots=[*snapshots[:source_index], partial, *snapshots[source_index + 1 :]],
            underlying_history=history,
            generated_at="2026-12-01T00:00:00Z",
        )

        self.assertEqual(
            len(snapshots),
            report["sample"]["validated_snapshot_count"],
        )
        self.assertEqual(
            failed_expiry,
            report["sample"]["excluded_expiries"][0]["expiry_date"],
        )

    def test_excludes_exchange_locked_snapshots_from_measurement_and_preflight(
        self,
    ) -> None:
        snapshots, history = _build_series(richness_reaches_quote=True)
        locked = {
            **snapshots[0],
            "feeds": {
                **snapshots[0]["feeds"],
                "events": {
                    "exchange_locked": True,
                    "locked_currencies": ["BTC"],
                    "locked_indices": [],
                },
            },
        }
        series = [locked, *snapshots[1:]]

        for builder in (build_signal_validation_report, build_signal_preflight_report):
            with self.subTest(builder=builder.__name__):
                report = builder(
                    snapshots=series,
                    underlying_history=history,
                    generated_at="2026-12-01T00:00:00Z",
                )
                excluded = (
                    report["sample"]["excluded_snapshots"]
                    if "sample" in report
                    else report["excluded_snapshots"]
                )
                self.assertIn(
                    {
                        "captured_at": locked["captured_at"],
                        "reason_code": "EXCHANGE_FULL_LOCK",
                    },
                    excluded,
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
