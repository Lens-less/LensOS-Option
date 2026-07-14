from copy import deepcopy
import unittest

from crypto_options_report.calibration import build_walk_forward_calibration_report
from crypto_options_report.contract import generate_research_report, validate_report_contract
from crypto_options_report.full_surface import validate_full_system_surface_report
from crypto_options_report.market_data import load_snapshot_fixture


class ReportEvidenceStateTests(unittest.TestCase):
    def test_missing_calibration_implementation_is_not_presented_as_fixture(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("unavailable", report["calibration_status"]["status"])
        self.assertFalse(report["calibration_status"]["calibrated"])
        self.assertIsNone(report["calibration_status"]["model_version"])
        self.assertEqual("not_implemented", report["calibration_status"]["promotion_status"])
        self.assertEqual(
            "CALIBRATION_NOT_IMPLEMENTED",
            report["calibration_status"]["reason_code"],
        )
        self.assertIn("CALIBRATION_NOT_IMPLEMENTED", report["reason_codes"])

    def test_absent_backtest_artifact_is_not_run_and_has_no_performance(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        self.assertEqual("not_run", report["backtest_status"]["status"])
        self.assertFalse(report["backtest_status"]["aligned"])
        self.assertEqual("BACKTEST_NOT_RUN", report["backtest_status"]["reason_code"])
        self.assertEqual(
            [],
            report["walk_forward_calibration"]["system_comparison"],
        )
        self.assertEqual(
            [],
            report["full_system_surface"]["backtest_comparison"],
        )
        self.assertIn("BACKTEST_NOT_RUN", report["reason_codes"])
        self.assertNotIn("MISSING_BACKTEST_ALIGNMENT", report["reason_codes"])

    def test_not_run_backtest_rejects_injected_performance_comparison(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        report["walk_forward_calibration"]["comparison_status"] = {
            "status": "available",
            "reason_code": None,
            "metrics_source": "immutable_backtest_ledger",
            "artifact_id": "ledger-001",
        }
        report["walk_forward_calibration"]["system_comparison"] = [
            {"variant": variant, "calmar": 999.0}
            for variant in ("baseline", "regime_only", "pricing_only", "full_system")
        ]

        errors = validate_report_contract(report)

        self.assertIn(
            "not-run backtest must not expose an available calibration comparison",
            errors,
        )
        self.assertIn(
            "not-run backtest must not expose calibration performance rows",
            errors,
        )

    def test_calibration_builder_does_not_invent_default_backtest_metrics(self):
        calibration = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual([], calibration["system_comparison"])
        self.assertEqual("unavailable", calibration["comparison_status"]["status"])
        self.assertEqual(
            "CALIBRATION_NOT_IMPLEMENTED",
            calibration["comparison_status"]["reason_code"],
        )
        self.assertEqual([], calibration["slow_bull_acute_rally_windows"])

    def test_release_readiness_is_not_inferred_from_internal_evidence(self):
        snapshot = load_snapshot_fixture(
            "tests/fixtures/deribit_btc_option_chain_snapshot.json"
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
            account_scenario="green",
        )
        readiness = report["full_system_surface"]["release_readiness"]
        self.assertEqual("NO-GO", readiness["status"])
        self.assertFalse(readiness["paper_mode_allowed"])
        self.assertFalse(readiness["manual_execution_allowed"])
        self.assertEqual(1, len(readiness["prerequisites"]))
        gate = readiness["prerequisites"][0]
        self.assertEqual("external_release_authorization", gate["name"])
        self.assertFalse(gate["satisfied"])
        self.assertEqual("not_configured", gate["evidence_state"])
        self.assertEqual("awaiting_external", gate["release_state"])
        self.assertEqual("external_operator", gate["owner"])
        self.assertEqual(
            ["EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED"], gate["reason_codes"]
        )

        self.assertEqual("unsupported", report["paper_proposal_ledger"]["status"])
        self.assertEqual("NO-GO", report["paper_proposal_ledger"]["release_state"])
        self.assertFalse(
            report["paper_proposal_ledger"]["persistence"]["write_allowed"]
        )

        self.assertTrue(gate["release_blocking"])

    def test_release_gate_validator_rejects_contradictory_ready_states(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        surface = report["full_system_surface"]

        false_ready = deepcopy(surface)
        false_ready_gate = false_ready["release_readiness"]["prerequisites"][0]
        false_ready_gate["release_state"] = "ready"
        self.assertIn(
            "unsatisfied release readiness gate must not be ready",
            validate_full_system_surface_report(false_ready),
        )

        forged_authorization = deepcopy(surface)
        forged_gate = forged_authorization["release_readiness"]["prerequisites"][0]
        forged_gate["satisfied"] = True
        forged_gate["release_state"] = "ready"
        forged_gate["evidence_state"] = "verified_local"
        forged_gate["release_blocking"] = False
        forged_gate["reason_codes"] = []
        forged_gate["root_cause"] = None
        forged_authorization["release_readiness"]["status"] = "GO"
        forged_authorization["release_readiness"]["missing_prerequisites"] = []
        forged_authorization["release_readiness"]["blocking_prerequisites"] = []
        errors = validate_full_system_surface_report(forged_authorization)
        self.assertIn(
            "runtime report cannot satisfy external release authorization",
            errors,
        )

    def test_validated_market_data_requires_consistent_collection_scope(self):
        snapshot = load_snapshot_fixture(
            "tests/fixtures/deribit_btc_option_chain_snapshot.json"
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
        )

        missing_scope = deepcopy(report)
        missing_scope["data_status"].pop("collection_scope")
        missing_scope["data_status"]["public_response_contract"].pop(
            "collection_scope"
        )
        self.assertIn(
            "market data status must include collection_scope",
            validate_report_contract(missing_scope),
        )

        mismatched_scope = deepcopy(report)
        mismatched_scope["data_status"]["public_response_contract"][
            "collection_scope"
        ]["selected_instrument_count"] += 1
        self.assertIn(
            "public response collection_scope must match data_status collection_scope",
            validate_report_contract(mismatched_scope),
        )


if __name__ == "__main__":
    unittest.main()
