import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from crypto_options_report.calibration import (
    build_walk_forward_calibration_report,
    validate_walk_forward_calibration_report,
)
from crypto_options_report.ev_scanner import build_ev_candidate_scanner
from crypto_options_report.full_surface import build_full_system_surface_report
from crypto_options_report.paper_ledger import (
    build_paper_proposal_ledger,
    validate_paper_proposal_ledger,
)
from crypto_options_report.position_management import (
    build_position_management_report,
    validate_position_management_report,
)


class ReviewEvidenceHonestyTests(unittest.TestCase):
    def test_calibration_reports_unimplemented_without_plausible_fixture_metrics(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-14T00:00:00Z",
        )

        self.assertEqual("not_implemented", report["status"])
        self.assertEqual("unavailable", report["evidence_class"])
        self.assertEqual("CALIBRATION_NOT_IMPLEMENTED", report["reason_code"])
        self.assertNotIn("collinearity", report)
        self.assertNotIn("score", report)
        self.assertNotIn("leakage_checks", report)
        self.assertFalse(report["model_registry"]["promoted_for_sizing"])
        self.assertEqual([], validate_walk_forward_calibration_report(report))

    def test_ev_scanner_is_unavailable_without_validated_path_evidence(self):
        candidate = {
            "candidate_id": "candidate-1",
            "structure_type": "naked_short_call",
            "instrument_name": "BTC-31JUL26-120000-C",
            "underlying_price": 100_000.0,
            "strike_price": 120_000.0,
            "dte_days": 14.0,
            "market_bid": 0.01,
            "market_ask": 0.011,
            "market_bid_iv": 70.0,
            "surface_fitted_iv": 60.0,
            "model_delta": 0.12,
            "model_vega": 0.001,
            "depth": 20.0,
            "spread_ratio": 0.10,
            "decision_reason_codes": [],
            "filter_reason_codes": [],
        }
        scanner = build_ev_candidate_scanner(
            generated_at="2026-07-14T00:00:00Z",
            data_status={"status": "validated", "market_data_age_sec": 0.0},
            account_status={
                "margin_light": "GREEN",
                "trade_gate": "ALLOW_NEW",
                "data_age_ms": 0.0,
                "snapshot": {"nav_usd": 100_000.0},
                "projected_margin": {},
            },
            calibration_status={"calibrated": False},
            permission_state={
                "reason_codes": [],
                "regime_scores": {},
                "volatility_inputs": {},
            },
            candidate_research={
                "status": "validated",
                "naked_short_calls": {
                    "eligible": [candidate],
                    "review": [],
                    "rejected": [],
                },
                "call_credit_spreads": {
                    "eligible": [],
                    "review": [],
                    "rejected": [],
                },
            },
        )

        self.assertEqual("unavailable", scanner["status"])
        self.assertEqual("MISSING_VALIDATED_PATH_RISK", scanner["reason_code"])
        self.assertEqual([], scanner["ranked_candidates"])
        self.assertEqual("unavailable", scanner["path_risk_evidence"]["status"])
        self.assertFalse(scanner["path_risk_evidence"]["validated"])

    def test_account_positions_do_not_receive_synthetic_management_numbers(self):
        report = build_position_management_report(
            generated_at="2026-07-14T00:00:00Z",
            account_status={
                "positions": [
                    {
                        "instrument_name": "BTC-31JUL26-120000-C",
                        "pnl": -250.0,
                        "mark_price": 0.012,
                        "greeks": {"delta": -0.22},
                    }
                ]
            },
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual("unavailable", report["status"])
        self.assertEqual(
            "MISSING_POSITION_MANAGEMENT_EVIDENCE",
            report["reason_code"],
        )
        self.assertEqual([], report["replays"])
        self.assertEqual(1, report["summary"]["positions_observed"])
        self.assertEqual(0, report["summary"]["positions_evaluated"])
        self.assertEqual([], validate_position_management_report(report))

    def test_paper_ledger_stays_unsupported_even_when_allow_paper_is_requested(self):
        report = {
            "mode_gate": {"paper_manual_candidates_allowed": True},
            "walk_forward_calibration": {
                "status": "validated",
                "model_registry": {"promoted_for_sizing": True},
            },
            "data_status": {"status": "validated"},
            "account_status": {
                "trade_gate": "ALLOW_NEW",
                "private_adapter_contract": {
                    "auth_safe": True,
                    "replay_fixture": True,
                    "live_order_submission_possible": False,
                },
            },
            "reason_codes": [],
            "ev_candidate_scanner": {"ranked_candidates": []},
        }
        with TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "paper-ledger.json"
            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-14T00:00:00Z",
                report=report,
                allow_paper=True,
                storage_path=storage_path,
            )

            self.assertEqual("unsupported", ledger["status"])
            self.assertEqual("not_authorized", ledger["authorization_state"])
            self.assertEqual("NO-GO", ledger["release_state"])
            self.assertFalse(ledger["proposal_creation_allowed"])
            self.assertEqual([], ledger["proposals"])
            self.assertEqual([], ledger["ledger_entries"])
            self.assertFalse(storage_path.exists())
            self.assertEqual([], validate_paper_proposal_ledger(ledger))

    def test_full_surface_declarations_do_not_self_certify_availability(self):
        surface = build_full_system_surface_report(
            generated_at="2026-07-14T00:00:00Z",
            report={},
        )

        self.assertEqual("declared_not_probed", surface["status"])
        self.assertTrue(
            all(
                item["status"] == "declared_not_probed"
                for item in surface["cli"]["commands"]
            )
        )
        self.assertTrue(
            all(
                item["status"] == "declared_not_probed"
                for item in surface["api"]["routes"]
            )
        )
        self.assertTrue(
            all(
                item["status"] == "declared_not_probed"
                for item in surface["dashboard"]["views"]
            )
        )
        self.assertEqual("declared_not_probed", surface["alerts"]["status"])
        self.assertEqual("unsupported", surface["trading_spine"]["paper_mode"])
        self.assertEqual(
            "unsupported",
            surface["trading_spine"]["manual_execution"],
        )


if __name__ == "__main__":
    unittest.main()
