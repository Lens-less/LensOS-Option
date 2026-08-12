"""Reading the capture series as a series, and the four ways that misleads.

The daily capture has been accumulating for the validation sample and already
answers a question nothing was asking: was this strike rich yesterday too? Each
test below pins one of the ways that question is easy to answer wrongly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_signal_validation import (
    _build_series,
    _first_multi_expiry_snapshot,
    _partially_blocked_snapshot,
)

from crypto_options_report.market_data import (
    build_market_data_status,
    parse_timestamp_ms,
)
from crypto_options_report.series_history import (
    PERSISTENCE_PRIOR_OBSERVATIONS,
    build_series_history_report,
)


def _report(**overrides):
    snapshots, _ = _build_series(richness_reaches_quote=True)
    return build_series_history_report(
        snapshots=snapshots,
        generated_at="2026-07-27T00:00:00Z",
        config=overrides or None,
    )


class SeriesShapeTests(unittest.TestCase):
    def test_every_instrument_is_aligned_to_the_full_capture_calendar(self) -> None:
        report = _report()

        dates = report["capture_dates"]
        self.assertEqual(dates, sorted(dates))
        for instrument in report["instruments"]:
            with self.subTest(instrument=instrument["instrument_name"]):
                self.assertEqual(
                    [point["date"] for point in instrument["points"]], dates
                )

    def test_a_gap_is_a_gap_and_never_a_zero(self) -> None:
        """An instrument the collector did not select is absent, not flat.

        The collector picks about a hundred of several hundred listed
        instruments and which ones move with spot, so absence is common. A zero
        would read as "measured, and fairly priced".
        """
        report = _report()
        gapped = [
            instrument
            for instrument in report["instruments"]
            if instrument["missing_date_count"] > 0
        ]
        self.assertTrue(gapped)

        for instrument in gapped[:5]:
            absent = [
                point for point in instrument["points"] if not point["present"]
            ]
            self.assertTrue(absent)
            for point in absent:
                with self.subTest(instrument=instrument["instrument_name"]):
                    self.assertNotIn("residual_z", point)

    def test_counts_reconcile_with_the_calendar(self) -> None:
        report = _report()
        total = len(report["capture_dates"])

        for instrument in report["instruments"]:
            with self.subTest(instrument=instrument["instrument_name"]):
                self.assertEqual(
                    instrument["capture_date_count"]
                    + instrument["missing_date_count"],
                    total,
                )


class SameDayRetryTests(unittest.TestCase):
    def test_two_captures_on_one_day_are_one_reading(self) -> None:
        """The scheduled job retries; a retry is not a second observation."""
        snapshots, _ = _build_series(richness_reaches_quote=True)
        once = build_series_history_report(
            snapshots=snapshots, generated_at="2026-07-27T00:00:00Z"
        )
        twice = build_series_history_report(
            snapshots=[*snapshots, *snapshots],
            generated_at="2026-07-27T00:00:00Z",
        )

        self.assertEqual(twice["capture_count"], once["capture_count"])
        self.assertEqual(
            [row["capture_date_count"] for row in twice["instruments"]],
            [row["capture_date_count"] for row in once["instruments"]],
        )


class OrderingTests(unittest.TestCase):
    """A three-reading average must not outrank a forty-reading one."""

    def test_the_list_is_ordered_by_the_shrunk_mean(self) -> None:
        report = _report()
        scores = [
            row["persistence"]["shrunk_mean"] for row in report["instruments"]
        ]

        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_shrinkage_pulls_a_thin_series_below_a_weaker_but_thicker_one(
        self,
    ) -> None:
        report = _report()
        rows = {
            row["instrument_name"]: row["persistence"]
            for row in report["instruments"]
        }
        # Find any pair where the thin series has the larger raw mean but the
        # thicker one wins on the published ordering. Without shrinkage the
        # thin row would simply be on top.
        thin_beaten = [
            (thin, thick)
            for thin in rows.values()
            for thick in rows.values()
            if thin["raw_mean"] > thick["raw_mean"]
            and thin["shrunk_mean"] < thick["shrunk_mean"]
        ]
        self.assertTrue(thin_beaten, "shrinkage never changed an ordering")

    def test_the_shrinkage_constant_is_published_with_the_number(self) -> None:
        report = _report()
        persistence = report["instruments"][0]["persistence"]

        self.assertEqual(
            persistence["prior_observations"], PERSISTENCE_PRIOR_OBSERVATIONS
        )
        self.assertIn("autocorrelated", persistence["not_a_significance_test"])

    def test_the_shrunk_mean_never_exceeds_the_raw_one_in_magnitude(self) -> None:
        for row in _report()["instruments"]:
            with self.subTest(instrument=row["instrument_name"]):
                persistence = row["persistence"]
                self.assertLessEqual(
                    abs(persistence["shrunk_mean"]),
                    abs(persistence["raw_mean"]) + 1e-9,
                )


class FailClosedTests(unittest.TestCase):
    def test_a_failed_expiry_is_isolated_without_discarding_healthy_peers(self) -> None:
        snapshots, _ = _build_series(richness_reaches_quote=True)
        partial, failed_expiry, passing_expiries = _partially_blocked_snapshot(
            _first_multi_expiry_snapshot(snapshots)
        )
        status = build_market_data_status(
            partial,
            now_ms=parse_timestamp_ms(partial["captured_at"]),
        )
        self.assertEqual("blocked", status["status"])

        report = build_series_history_report(
            snapshots=[partial],
            generated_at=partial["captured_at"],
            config={"min_capture_dates": 1},
        )

        self.assertEqual("measured", report["status"])
        self.assertEqual([partial["captured_at"][:10]], report["capture_dates"])
        self.assertTrue(report["instruments"])
        self.assertNotIn(
            failed_expiry,
            {row["expiry_date"] for row in report["instruments"]},
        )
        self.assertTrue(
            {row["expiry_date"] for row in report["instruments"]}
            <= passing_expiries
        )
        self.assertEqual(failed_expiry, report["excluded_expiries"][0]["expiry_date"])
        self.assertIn(
            "BAD_QUOTE_RATIO_EXCEEDED",
            report["excluded_expiries"][0]["reason_codes"],
        )

    def test_all_failed_expiries_still_exclude_the_whole_capture(self) -> None:
        snapshots, _ = _build_series(richness_reaches_quote=True)
        failed = _first_multi_expiry_snapshot(snapshots)
        for row in failed["rows"]:
            row["ticker"]["bid_iv"] = None

        report = build_series_history_report(
            snapshots=[failed],
            generated_at=failed["captured_at"],
            config={"min_capture_dates": 1},
        )

        self.assertEqual("blocked", report["status"])
        self.assertEqual([], report["capture_dates"])
        self.assertIn("NO_VALIDATED_CAPTURES", report["reason_codes"])
        self.assertEqual(1, len(report["excluded_captures"]))
        self.assertGreaterEqual(len(report["excluded_expiries"]), 2)

    def test_exchange_locked_capture_is_excluded_from_the_series(self) -> None:
        snapshots, _ = _build_series(richness_reaches_quote=True)
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

        report = build_series_history_report(
            snapshots=[locked, *snapshots[1:]],
            generated_at="2026-07-27T00:00:00Z",
        )

        self.assertIn(
            {
                "captured_at": locked["captured_at"],
                "reason_code": "EXCHANGE_FULL_LOCK",
            },
            report["excluded_captures"],
        )
        self.assertNotIn(locked["captured_at"][:10], report["capture_dates"])

    def test_a_single_capture_cannot_make_a_series(self) -> None:
        snapshots, _ = _build_series(richness_reaches_quote=True)

        report = build_series_history_report(
            snapshots=snapshots[:1], generated_at="2026-07-27T00:00:00Z"
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("INSUFFICIENT_CAPTURE_DATES", report["reason_codes"])
        self.assertEqual(report["instruments"], [])

    def test_no_validated_capture_blocks_rather_than_returning_an_empty_grid(
        self,
    ) -> None:
        report = build_series_history_report(
            snapshots=[{"captured_at": "2026-07-01T00:00:00Z", "rows": []}],
            generated_at="2026-07-27T00:00:00Z",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("NO_VALIDATED_CAPTURES", report["reason_codes"])
        self.assertTrue(report["excluded_captures"])

    def test_the_persistence_caveat_travels_with_the_data(self) -> None:
        """Persistent richness and a mis-specified fit look identical here."""
        report = _report()

        self.assertTrue(
            any(
                "quadratic fit cannot follow" in line
                for line in report["cannot_tell"]
            ),
            report["cannot_tell"],
        )

    def test_the_report_carries_no_trading_surface(self) -> None:
        rendered = repr(_report())

        for forbidden in (
            "recommended_size",
            "order_instruction",
            "execution_allowed",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
