import json
import subprocess
import sys
import unittest
from pathlib import Path

from crypto_options_report.backtest import (
    build_baseline_backtest_report_from_fixture,
)


class BaselineBacktestReportTests(unittest.TestCase):
    def test_fixture_replay_is_reproducible(self):
        report_a = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )
        report_b = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertEqual(report_a, report_b)
        self.assertEqual("baseline_backtest_report.v1", report_a["schema_version"])
        self.assertEqual(2, report_a["summary"]["trade_count"])

    def test_backtest_selects_eligible_7dish_point_one_delta_calls(self):
        report = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        selected = [item["selected_instrument_name"] for item in report["selection_log"] if item["selected_instrument_name"]]
        self.assertEqual(
            ["BTC-31JAN26-114000-C", "BTC-07FEB26-124000-C"],
            selected,
        )
        for trade in report["trades"]:
            self.assertLessEqual(abs(trade["dte_days"] - 7.0), 2.5)
            self.assertLessEqual(trade["abs_delta"], 0.20)

    def test_fill_policy_proves_no_mid_or_mark_optimism(self):
        report = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertFalse(report["fill_audit"]["optimistic_fill_detected"])
        self.assertEqual(["mid", "mark"], report["fill_audit"]["disallowed_fill_sources"])
        self.assertEqual({"bid": 2}, report["fill_audit"]["entry_fill_source_counts"])
        self.assertEqual(1, report["fill_audit"]["exit_fill_source_counts"]["ask"])
        self.assertEqual(1, report["fill_audit"]["exit_fill_source_counts"]["expiry_settlement"])
        self.assertTrue(all(point["fill_reference"] == "ask" for point in report["replay_points"]))

    def test_report_marks_unavailable_metrics_and_records_touch_event(self):
        report = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertEqual("not_implemented", report["metrics"]["cagr"]["status"])
        self.assertEqual("not_implemented", report["metrics"]["margin_breach_count"]["status"])
        self.assertEqual("not_implemented", report["metrics"]["forced_close_count"]["status"])
        self.assertEqual(1, report["summary"]["touch_event_count"])
        self.assertEqual("closed_before_expiry", report["trades"][1]["close"]["expiry_outcome"])

    def test_cli_backtest_command_emits_same_report(self):
        expected = build_baseline_backtest_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "backtest",
                "--fixture",
                str(self._fixture_path()),
                "--generated-at",
                "2026-07-07T10:30:00Z",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        actual = json.loads(completed.stdout)
        self.assertEqual(expected, actual)

    def _fixture_path(self) -> Path:
        return (
            Path(__file__).with_name("fixtures")
            / "historical_vendor"
            / "baseline_backtest_fixture.json"
        )


if __name__ == "__main__":
    unittest.main()
