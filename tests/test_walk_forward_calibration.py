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
        self.assertEqual("research_fixture_uncalibrated", report["score"]["status"])
        self.assertEqual("research_fixture", report["status"])
        self.assertEqual(
            report["score"]["train_distribution_percentile"],
            report["score"]["score"],
        )

    def test_hides_performance_until_backtest_ledger_evidence_exists(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual("not_run", report["comparison_status"]["status"])
        self.assertEqual("BACKTEST_NOT_RUN", report["comparison_status"]["reason_code"])
        self.assertIsNone(report["comparison_status"]["metrics_source"])
        self.assertEqual([], report["system_comparison"])
        self.assertEqual([], report["slow_bull_acute_rally_windows"])

    def test_available_comparison_requires_artifact_and_complete_numeric_rows(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )
        report["comparison_status"] = {
            "status": "available",
            "reason_code": None,
            "metrics_source": "immutable_backtest_ledger",
            "artifact_id": None,
        }
        report["system_comparison"] = [
            {"variant": variant, "calmar": 999.0}
            for variant in ("baseline", "regime_only", "pricing_only", "full_system")
        ]

        errors = validate_walk_forward_calibration_report(report)

        self.assertIn(
            "available calibration comparison must name immutable ledger artifact",
            errors,
        )
        self.assertIn(
            "available calibration comparison rows must include all performance metrics",
            errors,
        )

    def test_no_future_data_is_used(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        for check in report["leakage_checks"]:
            self.assertFalse(check["future_data_used"])


if __name__ == "__main__":
    unittest.main()
