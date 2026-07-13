from copy import deepcopy
import unittest

from crypto_options_report.calibration import build_walk_forward_calibration_report
from crypto_options_report.contract import generate_research_report, validate_report_contract
from crypto_options_report.full_surface import validate_full_system_surface_report
from crypto_options_report.market_data import load_snapshot_fixture


class ReportEvidenceStateTests(unittest.TestCase):
    def test_local_calibration_fixture_is_pending_promotion_not_missing(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("research_fixture", report["calibration_status"]["status"])
        self.assertFalse(report["calibration_status"]["calibrated"])
        self.assertEqual(
            "walk_forward_fixture_v1",
            report["calibration_status"]["model_version"],
        )
        self.assertEqual(
            "research_only_unpromoted",
            report["calibration_status"]["promotion_status"],
        )
        self.assertEqual(
            "CALIBRATION_PROMOTION_PENDING",
            report["calibration_status"]["reason_code"],
        )
        self.assertNotIn("MISSING_CALIBRATED_MODEL", report["reason_codes"])

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
        self.assertEqual("not_run", calibration["comparison_status"]["status"])
        self.assertEqual(
            "BACKTEST_NOT_RUN",
            calibration["comparison_status"]["reason_code"],
        )
        self.assertEqual([], calibration["slow_bull_acute_rally_windows"])

    def test_release_gates_distinguish_local_evidence_from_release_readiness(self):
        snapshot = load_snapshot_fixture(
            "tests/fixtures/deribit_btc_option_chain_snapshot.json"
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
            account_scenario="green",
        )
        gates = {
            gate["name"]: gate
            for gate in report["full_system_surface"]["release_readiness"][
                "prerequisites"
            ]
        }

        data_gate = gates["data_quality"]
        self.assertFalse(data_gate["satisfied"])
        self.assertEqual("verified_local", data_gate["evidence_state"])
        self.assertEqual("not_ready", data_gate["release_state"])
        self.assertEqual("system_observation", data_gate["owner"])
        self.assertIn("DATA_TRUST_PROMOTION_PENDING", data_gate["reason_codes"])

        calibration_gate = gates["walk_forward_calibration"]
        self.assertFalse(calibration_gate["satisfied"])
        self.assertEqual("verified_local", calibration_gate["evidence_state"])
        self.assertEqual("awaiting_external", calibration_gate["release_state"])

        reconciliation_gate = gates["paper_ledger_reconciliation"]
        self.assertFalse(reconciliation_gate["satisfied"])
        self.assertEqual("not_run", reconciliation_gate["evidence_state"])
        self.assertEqual("awaiting_calendar", reconciliation_gate["release_state"])
        self.assertEqual("system_observation", reconciliation_gate["owner"])

        for gate in gates.values():
            self.assertIn("release_blocking", gate)
            self.assertIsInstance(gate["reason_codes"], list)

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

        true_without_evidence = deepcopy(surface)
        satisfied_gate = next(
            gate
            for gate in true_without_evidence["release_readiness"]["prerequisites"]
            if gate["satisfied"] is True
        )
        satisfied_gate["evidence_state"] = "not_configured"
        satisfied_gate["reason_codes"] = ["FAKE_READY_STATE"]
        errors = validate_full_system_surface_report(true_without_evidence)
        self.assertIn(
            "satisfied release readiness gate must have verified local evidence",
            errors,
        )
        self.assertIn(
            "satisfied release readiness gate must not retain blocking reasons",
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
