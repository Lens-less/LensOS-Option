import unittest

from crypto_options_report.calibration import (
    build_walk_forward_calibration_report,
    validate_walk_forward_calibration_report,
)


class WalkForwardCalibrationTests(unittest.TestCase):
    def test_split_uses_training_test_embargo_and_purge(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual([], validate_walk_forward_calibration_report(report))
        split = report["split_policy"]
        self.assertEqual(24, split["training_window_months"])
        self.assertEqual(3, split["test_window_months"])
        self.assertTrue(split["max_dte_embargo"])
        self.assertTrue(split["purge_overlapping_labels"])

    def test_training_only_robust_z_buckets_and_targets_are_recorded(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        standardization = report["feature_standardization"]
        self.assertEqual("robust_z_score", standardization["method"])
        self.assertEqual("training_only", standardization["reference_scope"])
        self.assertEqual(
            ["currency", "structure", "dte_bucket", "delta_bucket"],
            standardization["separate_buckets"],
        )
        self.assertFalse(standardization["future_data_used"])
        self.assertIn("realized_utility", report["targets"])
        self.assertIn("adverse_event", report["targets"])

    def test_collinearity_and_calibrated_percentile_score_are_reported(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertGreater(report["collinearity"]["ev_vrp_correlation"], 0.8)
        self.assertGreater(report["collinearity"]["ev_vrp_vif"], 1.0)
        self.assertIn(report["collinearity"]["action"], {"residualize_vrp", "drop_vrp"})
        self.assertEqual("calibrated", report["score"]["status"])
        self.assertEqual(
            report["score"]["train_distribution_percentile"],
            report["score"]["score"],
        )

    def test_compares_all_system_variants_and_highlights_slow_bull_windows(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual(
            {"baseline", "regime_only", "pricing_only", "full_system"},
            {row["variant"] for row in report["system_comparison"]},
        )
        for row in report["system_comparison"]:
            for metric in (
                "calmar",
                "max_drawdown",
                "cvar_99",
                "touch_rate",
                "forced_exit_count",
                "margin_breach_count",
                "premium_to_cvar",
                "recovery_days",
            ):
                self.assertIn(metric, row)
        self.assertGreaterEqual(len(report["slow_bull_acute_rally_windows"]), 2)

    def test_no_future_data_is_used(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        for check in report["leakage_checks"]:
            self.assertFalse(check["future_data_used"])


if __name__ == "__main__":
    unittest.main()
