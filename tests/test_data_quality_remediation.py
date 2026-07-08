import copy
import json
import tempfile
import unittest
from pathlib import Path

from crypto_options_report.account_risk import (
    build_account_status,
    load_account_scenario,
)
from crypto_options_report.calibration import build_walk_forward_calibration_report
from crypto_options_report.contract import generate_research_report
from crypto_options_report.historical import (
    build_historical_reconciliation_report,
    load_historical_fixture,
)
from crypto_options_report.market_data import build_market_data_status
from crypto_options_report.paper_ledger import build_paper_proposal_ledger
from crypto_options_report.path_risk import build_path_risk_report_from_fixture


FIXTURES = Path(__file__).parent / "fixtures"


class DataQualityRemediationTests(unittest.TestCase):
    def test_duplicate_live_strikes_fail_closed_without_surface_crash(self):
        snapshot = self._duplicate_strike_snapshot()

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
        )

        self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
        expiry = report["vol_surface_status"]["expiries"][0]
        self.assertFalse(expiry["no_arb_pass"])
        self.assertIn("SURFACE_DUPLICATE_STRIKE", expiry["reason_codes"])
        self.assertEqual("blocked", report["candidate_research"]["status"])

    def test_market_data_status_exposes_public_contract_metadata_and_feed_coverage(self):
        snapshot = self._base_snapshot()

        status = build_market_data_status(
            snapshot,
            now_ms=1783382490000,
        )

        self.assertIn("public_response_contract", status)
        self.assertIn("feed_coverage", status)
        self.assertEqual(
            "available",
            status["public_response_contract"]["endpoints"]["book_summary"]["status"],
        )
        self.assertIn(
            "order_book",
            status["feed_coverage"]["missing_feeds"],
        )
        first_quote = status["quality_gate"]["sample_canonical_metadata"][0]
        self.assertEqual("BTC", first_quote["base_currency"])
        self.assertEqual("call", first_quote["option_type"])
        self.assertEqual("BTC-25JUL26-90000-C", first_quote["instrument_name"])

    def test_historical_report_records_raw_provenance_and_quarantine_reasons(self):
        payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "failure_fixtures.json",
            scenario="mark_mid_drift_failed",
        )

        report = build_historical_reconciliation_report(payload["rows"])

        self.assertIn("raw_data_provenance", report)
        self.assertIn("aggregate_eligibility", report)
        self.assertEqual("blocked", report["aggregate_eligibility"]["status"])
        first_quarantine = report["quarantine"]["quotes"][0]
        self.assertIn("failure_reasons", first_quarantine)
        self.assertIn("MARK_MID_DRIFT_FAILED", first_quarantine["failure_reasons"])
        self.assertGreaterEqual(report["raw_data_provenance"]["raw_rows"], 1)

    def test_path_risk_report_marks_fixture_inputs_as_research_only_placeholder(self):
        report = build_path_risk_report_from_fixture(
            FIXTURES / "path_risk_distribution_fixture.json",
            generated_at="2026-07-07T10:30:00Z",
        )

        evidence = report["input_evidence"]
        self.assertEqual("research_only_fixture", evidence["status"])
        self.assertTrue(evidence["no_lookahead_declared"])
        self.assertGreater(evidence["eligible_path_count"], 0)
        self.assertTrue(evidence["placeholder_data"])

    def test_partial_historical_reconciliation_blocks_training_and_backtest(self):
        pass_payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "pass_fixture.json",
        )
        fail_payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "failure_fixtures.json",
            scenario="mark_mid_drift_failed",
        )

        report = build_historical_reconciliation_report(
            pass_payload["rows"][:1] + fail_payload["rows"],
        )

        self.assertEqual("PARTIAL", report["eligibility"]["decision"])
        self.assertFalse(report["eligibility"]["training_allowed"])
        self.assertFalse(report["eligibility"]["backtest_allowed"])
        self.assertTrue(report["aggregate_eligibility"]["blocks_downstream"])

    def test_calibration_report_contains_unpromoted_model_registry_gate(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        registry = report["model_registry"]
        self.assertEqual("research_only_unpromoted", registry["promotion_status"])
        self.assertFalse(registry["promoted_for_sizing"])
        self.assertIn("MISSING_EXTERNAL_PROMOTION_REVIEW", registry["blocking_reasons"])

    def test_private_account_status_exposes_auth_safe_replay_contract(self):
        payload = load_account_scenario("green")

        status = build_account_status(
            generated_at="2026-07-07T09:51:00Z",
            account_payload=payload,
        )

        contract = status["private_adapter_contract"]
        self.assertTrue(contract["auth_safe"])
        self.assertTrue(contract["replay_fixture"])
        self.assertFalse(contract["live_order_submission_possible"])
        self.assertIn("private/get_account_summary", contract["source_endpoints"])

    def test_paper_ledger_records_persistence_and_reconciliation_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "paper-ledger.json"
            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-07T00:01:30Z",
                report=self._paper_ready_report(),
                allow_paper=True,
                storage_path=path,
                review_decisions=[
                    {
                        "proposal_id": "proposal-01-candidate-1",
                        "state": "paper_filled",
                        "simulated_fill_usdc": 118.0,
                        "observed_fill_usdc": 117.5,
                        "observed_fee_usdc": 1.7,
                        "latency_ms": 250,
                    }
                ],
            )

            self.assertEqual("persistent_json", ledger["persistence"]["mode"])
            self.assertTrue(ledger["persistence"]["idempotent"])
            self.assertEqual("30_to_60_days_required", ledger["reconciliation"]["window"])
            first = ledger["ledger_entries"][0]
            self.assertIn("observed_fill_usdc", first)
            self.assertIn("fee_delta_usdc", first)
            self.assertFalse(ledger["automatic_live_submission_possible"])

            saved = json.loads(Path(ledger["persistence"]["storage_path"]).read_text())
            self.assertEqual(ledger["schema_version"], saved["schema_version"])

            second = build_paper_proposal_ledger(
                generated_at="2026-07-08T00:01:30Z",
                report={
                    **self._paper_ready_report(),
                    "ev_candidate_scanner": {
                        "ranked_candidates": [
                            self._candidate("candidate-2", "naked_short_call", 90.0)
                        ]
                    },
                },
                allow_paper=True,
                storage_path=path,
            )
            saved = json.loads(path.read_text())
            self.assertEqual(2, len(saved["ledger_entries"]))
            self.assertTrue(second["persistence"]["history_preserved"])
            self.assertEqual(1, second["persistence"]["prior_entry_count"])

    def test_paper_ledger_blocks_unpromoted_or_missing_private_replay_evidence(self):
        report = self._paper_ready_report()
        report["walk_forward_calibration"]["model_registry"]["promoted_for_sizing"] = False

        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=report,
            allow_paper=True,
        )

        self.assertEqual("blocked", ledger["status"])
        self.assertIn("MISSING_PROMOTED_SCORE_MODEL", ledger["reason_codes"])

        report = self._paper_ready_report()
        report["account_status"]["private_adapter_contract"]["replay_fixture"] = False
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=report,
            allow_paper=True,
        )

        self.assertEqual("blocked", ledger["status"])
        self.assertIn("MISSING_PRIVATE_ACCOUNT_REPLAY_EVIDENCE", ledger["reason_codes"])

    def test_partial_ticker_and_missing_settlement_metadata_block_market_readiness(self):
        snapshot = self._base_snapshot()
        snapshot["rows"][0]["ticker"] = None
        snapshot["rows"][0]["summary"].pop("settlement_currency", None)

        status = build_market_data_status(
            snapshot,
            now_ms=1783382490000,
        )

        self.assertEqual("blocked", status["status"])
        self.assertIn("MISSING_SETTLEMENT_CURRENCY", status["quality_gate"]["reason_codes"])
        self.assertEqual(
            "partial",
            status["public_response_contract"]["endpoints"]["ticker"]["status"],
        )
        self.assertEqual("partial", status["feed_coverage"]["feeds"]["ticker"]["status"])
        self.assertIn("ticker", status["feed_coverage"]["missing_feeds"])

    def test_release_readiness_lists_evidence_driven_dqr_gates(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        readiness = report["full_system_surface"]["release_readiness"]

        self.assertEqual("NO-GO", readiness["status"])
        for gate_name in (
            "public_response_contract",
            "public_feed_graph_complete",
            "private_account_replay_contract",
            "calibration_model_promoted",
            "paper_ledger_persistence",
            "paper_ledger_reconciliation",
        ):
            self.assertIn(gate_name, readiness["missing_prerequisites"])

    def _base_snapshot(self):
        return json.loads((FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text())

    def _duplicate_strike_snapshot(self):
        snapshot = self._base_snapshot()
        duplicated = copy.deepcopy(snapshot["rows"][1])
        duplicated["instrument_name"] = "BTC-25JUL26-90000-C"
        duplicated["summary"]["instrument_name"] = "BTC-25JUL26-90000-C"
        duplicated["ticker"]["instrument_name"] = "BTC-25JUL26-90000-C"
        duplicated["summary"]["mid_price"] = 0.19
        duplicated["ticker"]["mark_price"] = 0.19
        snapshot["rows"][1] = duplicated
        return snapshot

    def _paper_ready_report(self):
        return {
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
            "ev_candidate_scanner": {
                "ranked_candidates": [
                    self._candidate("candidate-1", "naked_short_call", 120.0)
                ]
            },
        }

    def _candidate(self, candidate_id, structure, credit):
        return {
            "candidate_id": candidate_id,
            "structure_type": structure,
            "action": "RESEARCH_ONLY",
            "kill_conditions": [],
            "instrument_name": f"{candidate_id}-BTC-25JUL26-120000-C",
            "dte_days": 14,
            "model_delta": 0.12,
            "executable_credit_usdc": credit,
            "ev_after_cost_usdc": 10.0,
            "path_risk": {
                "p_touch": 0.22,
                "cvar_99_usdc": 300.0,
                "stress_loss_usdc": 450.0,
            },
            "fee_usdc": 1.5,
            "slippage_usdc": 2.0,
            "reason_codes": [],
        }


if __name__ == "__main__":
    unittest.main()
