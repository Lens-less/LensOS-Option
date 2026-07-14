from copy import deepcopy
import unittest

from crypto_options_report.calibration import (
    build_walk_forward_calibration_report,
    validate_walk_forward_calibration_report,
)
from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)


class WalkForwardCalibrationTests(unittest.TestCase):
    def test_default_contract_reports_calibration_as_unimplemented(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual([], validate_walk_forward_calibration_report(report))
        self.assertEqual("not_implemented", report["status"])
        self.assertEqual("unavailable", report["evidence_class"])
        self.assertEqual("CALIBRATION_NOT_IMPLEMENTED", report["reason_code"])
        self.assertTrue(report["paper_manual_release_gated"])

    def test_unimplemented_contract_does_not_invent_model_or_performance(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        registry = report["model_registry"]
        self.assertEqual("unavailable", registry["status"])
        self.assertEqual("not_implemented", registry["promotion_status"])
        self.assertIsNone(registry["model_version"])
        self.assertIsNone(registry["artifact_id"])
        self.assertFalse(registry["promoted_for_sizing"])
        self.assertEqual([], report["system_comparison"])
        self.assertEqual([], report["slow_bull_acute_rally_windows"])

    def test_caller_arguments_are_not_calibration_evidence(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
            baseline_backtest={"calmar": 999.0},
            portfolio_risk={"status": "validated"},
            position_management={"status": "validated"},
            promotion_evidence={
                "validated_historical_data": True,
                "out_of_sample_passed": True,
                "external_review_approved": True,
            },
        )

        self.assertEqual([], validate_walk_forward_calibration_report(report))
        self.assertFalse(report["model_registry"]["promoted_for_sizing"])
        self.assertEqual([], report["system_comparison"])

    def test_validator_rejects_fabricated_comparison_rows(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )
        report["comparison_status"] = {
            "status": "available",
            "reason_code": None,
            "metrics_source": "self_attested",
            "artifact_id": "fake-ledger",
        }
        report["system_comparison"] = [{"variant": "full_system", "calmar": 999.0}]

        errors = validate_walk_forward_calibration_report(report)

        self.assertIn(
            "unimplemented calibration must not expose comparison rows",
            errors,
        )

    def test_validator_rejects_self_promoted_model(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )
        report["model_registry"]["promoted_for_sizing"] = True
        report["model_registry"]["model_version"] = "self-attested-v1"

        errors = validate_walk_forward_calibration_report(report)

        self.assertIn(
            "unimplemented calibration must not be promoted for sizing",
            errors,
        )
        self.assertIn("unimplemented calibration must not name a model version", errors)

    def test_whole_contract_rejects_forged_unavailable_calibration_state(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        mutations = (
            (
                "promotion status",
                ("model_registry", "promotion_status"),
                "promoted",
                "calibration model registry promotion status must be not_implemented",
            ),
            (
                "artifact",
                ("model_registry", "artifact_id"),
                "self-attested-artifact",
                "unimplemented calibration must not name a model artifact",
            ),
            (
                "blocking reasons",
                ("model_registry", "blocking_reasons"),
                [],
                (
                    "calibration model registry must remain blocked by "
                    "CALIBRATION_NOT_IMPLEMENTED"
                ),
            ),
            (
                "release gate",
                ("paper_manual_release_gated",),
                False,
                "unimplemented calibration must keep paper/manual release gated",
            ),
        )

        for label, path, value, expected_error in mutations:
            with self.subTest(label=label):
                mutated = deepcopy(report)
                target = mutated["walk_forward_calibration"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                self.assertIn(expected_error, validate_report_contract(mutated))


if __name__ == "__main__":
    unittest.main()
