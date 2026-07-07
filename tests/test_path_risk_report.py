import json
import subprocess
import sys
import unittest
from pathlib import Path

from crypto_options_report.path_risk import (
    build_path_risk_report_from_fixture,
    load_path_risk_fixture,
)


class PathRiskDistributionReportTests(unittest.TestCase):
    def test_path_records_include_required_fields_and_touch_uses_path_maximum(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertEqual("path_risk_distribution_report.v1", report["schema_version"])
        first = report["historical_path_records"][0]
        for field_name in (
            "start_time",
            "horizon_days",
            "regime_scores",
            "feature_vector",
            "returns",
            "normalized_spot_path",
            "max_up_return",
            "terminal_return",
        ):
            self.assertIn(field_name, first)

        self.assertTrue(report["report_flags"]["path_maximum_touch"])
        self.assertGreater(
            report["distributions"]["p_touch"],
            report["diagnostics"]["terminal_only_touch_proxy"],
        )

    def test_sparse_effective_sample_size_triggers_conservative_fallback(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        similarity = report["path_sampling"]["similarity_weighted"]
        self.assertLess(
            similarity["initial_effective_sample_size"],
            similarity["minimum_effective_sample_size"],
        )
        self.assertTrue(similarity["fallback_triggered"])
        self.assertEqual("hierarchical_pooling", similarity["fallback_mode"])
        self.assertFalse(similarity["restrictions"]["naked_short_allowed"])
        self.assertTrue(similarity["restrictions"]["spread_only_required"])
        self.assertTrue(similarity["restrictions"]["confidence_penalty_applied"])

    def test_circular_block_bootstrap_preserves_multi_day_structure(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        bootstrap = report["path_sampling"]["bootstrap"]
        self.assertEqual("circular_block_bootstrap", bootstrap["method"])
        source = bootstrap["source_returns"]
        valid_pairs = {
            (source[index], source[(index + 1) % len(source)])
            for index in range(len(source))
        }
        for path in bootstrap["paths"]:
            for block in path["sampled_blocks"]:
                self.assertEqual(2, len(block["returns"]))
                self.assertIn(tuple(block["returns"]), valid_pairs)

    def test_stress_mixture_floor_and_stress_loss_are_reported(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        stress = report["stress_mixture"]
        self.assertGreaterEqual(
            stress["applied_weight"],
            stress["configured_min_weight"],
        )
        self.assertEqual(3, len(stress["scenarios"]))
        self.assertGreater(report["distributions"]["stress_loss_usdc"], 0.0)
        self.assertGreater(report["distributions"]["cvar_99_usdc"], 0.0)

    def test_cli_path_risk_command_is_reproducible(self):
        expected = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "path-risk",
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
        return Path(__file__).with_name("fixtures") / "path_risk_distribution_fixture.json"


if __name__ == "__main__":
    unittest.main()
