import json
import subprocess
import sys
import unittest
from pathlib import Path

from crypto_options_report.backtest import (
    build_fixed_baseline_backtest_report,
    load_backtest_fixture,
)


class FixedBaselineBacktestReportTests(unittest.TestCase):
    def test_baseline_selects_7dish_point1_delta_calls_from_eligible_snapshots(self):
        report = build_fixed_baseline_backtest_report(
            load_backtest_fixture(self._fixture_path()),
            generated_at="2026-07-07T10:00:00Z",
        )

        self.assertEqual("baseline_backtest_report.v1", report["schema_version"])
        self.assertEqual(3, report["window_summary"]["trade_count"])
        for trade in report["trades"]:
            self.assertEqual("ELIGIBLE", trade["entry_snapshot_eligibility"]["decision"])
            self.assertTrue(trade["selection"]["selected_is_closest_to_target"])
            self.assertAlmostEqual(7.333333, trade["selected_dte_days"], places=3)
            selected_delta = trade["selected_model_delta"]
            candidate_deltas = [
                candidate["abs_delta"]
                for candidate in trade["selection"]["considered_candidates"]
            ]
            self.assertEqual(
                min(abs(value - 0.1) for value in candidate_deltas),
                min(abs(selected_delta - 0.1), abs(selected_delta - 0.1)),
            )

    def test_execution_audit_proves_no_mid_or_mark_optimistic_fills(self):
        report = build_fixed_baseline_backtest_report(
            load_backtest_fixture(self._fixture_path()),
            generated_at="2026-07-07T10:00:00Z",
        )

        self.assertTrue(report["execution_audit"]["passed"])
        self.assertFalse(report["execution_audit"]["optimistic_fill_sources_present"])
        self.assertEqual(["bid"], report["execution_audit"]["entry_fill_sources"])
        self.assertIn("ask", report["execution_audit"]["exit_fill_sources"])
        self.assertIn("expiry_settlement", report["execution_audit"]["exit_fill_sources"])

    def test_report_explicitly_marks_unavailable_metrics(self):
        report = build_fixed_baseline_backtest_report(
            load_backtest_fixture(self._fixture_path()),
            generated_at="2026-07-07T10:00:00Z",
        )

        self.assertEqual(
            "not_implemented",
            report["aggregate_metrics"]["cagr_pct"]["status"],
        )
        self.assertEqual(
            "not_implemented",
            report["aggregate_metrics"]["margin_breach_count"]["status"],
        )
        self.assertEqual(
            "available",
            report["aggregate_metrics"]["total_return_proxy_pct"]["status"],
        )

    def test_cli_replay_is_reproducible_for_fixed_fixture_window(self):
        expected = build_fixed_baseline_backtest_report(
            load_backtest_fixture(self._fixture_path()),
            generated_at="2026-07-07T10:00:00Z",
        )

        cli_payload = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "baseline-backtest",
                "--fixture",
                str(self._fixture_path()),
                "--generated-at",
                "2026-07-07T10:00:00Z",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = json.loads(cli_payload.stdout)

        self.assertEqual(expected, actual)

    def _fixture_path(self) -> Path:
        return Path(__file__).with_name("fixtures") / "fixed_baseline_backtest_window.json"


if __name__ == "__main__":
    unittest.main()
