import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from crypto_options_report.account_risk import (
    build_account_status,
    load_private_replay_fixture,
)
from crypto_options_report.calibration import (
    build_walk_forward_calibration_report,
    validate_walk_forward_calibration_report,
)
from crypto_options_report.contract import generate_research_report
from crypto_options_report.historical import (
    build_historical_reconciliation_report,
    load_historical_fixture,
)
from crypto_options_report.market_data import (
    build_market_data_status,
    load_public_replay_fixture,
)
from crypto_options_report.paper_ledger import build_paper_reconciliation_runbook
from crypto_options_report.path_risk import build_path_risk_report_from_historical_report


FIXTURES = Path(__file__).parent / "fixtures"


class DqrIssueCompletionTests(unittest.TestCase):
    def test_public_replay_harness_covers_deribit_response_classes(self):
        expectations = {
            "success": ("pass", "validated", []),
            "empty_response": ("blocked", "blocked", ["EMPTY_PUBLIC_RESPONSE"]),
            "duplicate_instrument": ("blocked", "blocked", ["DUPLICATE_INSTRUMENT_OR_STRIKE"]),
            "partial_ticker": ("blocked", "blocked", ["MISSING_DEPTH"]),
            "rate_limit": ("retryable", "blocked", ["PUBLIC_RATE_LIMIT_RETRYABLE"]),
            "transient_network": ("retryable", "blocked", ["PUBLIC_NETWORK_RETRYABLE"]),
            "schema_drift": ("malformed", "blocked", ["PUBLIC_SCHEMA_DRIFT_MALFORMED"]),
            "stale_timestamp": ("stale", "blocked", ["MARKET_DATA_AGE_EXCEEDED"]),
        }

        for scenario, (contract_status, data_status, reason_codes) in expectations.items():
            with self.subTest(scenario=scenario):
                snapshot = load_public_replay_fixture(
                    FIXTURES / "public_deribit_replay.json",
                    scenario=scenario,
                )
                status = build_market_data_status(snapshot, now_ms=1783382490000)

                self.assertEqual(contract_status, status["public_response_contract"]["overall_status"])
                self.assertEqual(data_status, status["status"])
                for reason_code in reason_codes:
                    self.assertIn(reason_code, status["quality_gate"]["reason_codes"])
                self.assertFalse(status["public_response_contract"]["credential_required"])
                self.assertFalse(status["public_response_contract"]["network_required_for_tests"])

    def test_vol_index_feed_has_readiness_semantics(self):
        healthy = build_market_data_status(
            load_public_replay_fixture(
                FIXTURES / "public_deribit_replay.json",
                scenario="success",
            ),
            now_ms=1783382490000,
        )
        self.assertEqual("available", healthy["feed_coverage"]["feeds"]["vol_index"]["status"])
        self.assertNotIn("vol_index", healthy["feed_coverage"]["missing_required_feeds"])
        self.assertIn("order_book", healthy["feed_coverage"]["remaining_out_of_scope_feeds"])

        stale = build_market_data_status(
            load_public_replay_fixture(
                FIXTURES / "public_deribit_replay.json",
                scenario="stale_vol_index",
            ),
            now_ms=1783382490000,
        )
        self.assertEqual("stale", stale["feed_coverage"]["feeds"]["vol_index"]["status"])
        self.assertIn("vol_index", stale["feed_coverage"]["missing_required_feeds"])

        misaligned = build_market_data_status(
            load_public_replay_fixture(
                FIXTURES / "public_deribit_replay.json",
                scenario="misaligned_vol_index",
            ),
            now_ms=1783382490000,
        )
        self.assertEqual("misaligned", misaligned["feed_coverage"]["feeds"]["vol_index"]["status"])
        self.assertIn("vol_index", misaligned["feed_coverage"]["missing_required_feeds"])

    def test_malformed_dvol_replay_matrix_fails_closed_offline(self):
        scenarios = {
            "malformed_dvol_null_timestamp": "volatility index row missing timestamp",
            "malformed_dvol_non_integer_timestamp": (
                "volatility index timestamp is not integer-like"
            ),
            "malformed_dvol_timestamp_out_of_range": (
                "volatility index timestamp is out of range"
            ),
            "empty_dvol_data": "empty volatility index data",
        }

        with mock.patch(
            "crypto_options_report.market_data._get_json",
            side_effect=AssertionError("offline replay must not call the network boundary"),
        ):
            for scenario, detail in scenarios.items():
                with self.subTest(scenario=scenario):
                    snapshot = load_public_replay_fixture(
                        FIXTURES / "public_deribit_replay.json",
                        scenario=scenario,
                    )
                    status = build_market_data_status(
                        snapshot,
                        now_ms=1783382490000,
                    )
                    report = generate_research_report(
                        generated_at=snapshot["captured_at"],
                        market_snapshot=snapshot,
                    )

                    expected_error = f"vol_index: {detail}"
                    self.assertEqual([expected_error], snapshot["fetch_errors"])
                    self.assertNotIn("vol_index", snapshot.get("feeds") or {})
                    self.assertEqual(
                        [
                            {
                                "class": "schema_drift",
                                "message": expected_error,
                                "source": "live_public_deribit",
                            }
                        ],
                        snapshot["adapter_events"],
                    )
                    self.assertEqual("blocked", status["status"])
                    self.assertFalse(status["validated"])
                    self.assertEqual(
                        "malformed",
                        status["public_response_contract"]["overall_status"],
                    )
                    self.assertEqual(
                        "missing",
                        status["feed_coverage"]["feeds"]["vol_index"]["status"],
                    )
                    self.assertIn(
                        "vol_index",
                        status["feed_coverage"]["missing_required_feeds"],
                    )
                    self.assertIn(
                        "REQUIRED_FEED_MISSING",
                        status["quality_gate"]["reason_codes"],
                    )
                    self.assertIn(
                        "VOL_INDEX_MISSING",
                        status["quality_gate"]["reason_codes"],
                    )
                    self.assertIn(
                        "PUBLIC_SCHEMA_DRIFT_MALFORMED",
                        status["quality_gate"]["reason_codes"],
                    )
                    self.assertEqual("untrusted", report["data_trust"]["verdict"])
                    self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
                    self.assertEqual("research_only", report["effective_mode"])
                    self.assertFalse(report["mode_gate"]["paper_manual_candidates_allowed"])
                    self.assertFalse(
                        report["paper_proposal_ledger"]["automatic_live_submission_possible"]
                    )

    def test_malformed_dvol_keeps_paper_and_manual_modes_no_go(self):
        snapshot = load_public_replay_fixture(
            FIXTURES / "public_deribit_replay.json",
            scenario="empty_dvol_data",
        )

        for mode in ("paper", "manual_execution"):
            with self.subTest(mode=mode):
                report = generate_research_report(
                    mode=mode,
                    generated_at=snapshot["captured_at"],
                    market_snapshot=snapshot,
                )
                self.assertEqual("research_only", report["effective_mode"])
                self.assertEqual("NO_TRADE", report["action"])
                self.assertEqual("untrusted", report["data_trust"]["verdict"])
                self.assertFalse(report["mode_gate"]["paper_manual_candidates_allowed"])
                self.assertEqual(
                    "NO-GO",
                    report["full_system_surface"]["release_readiness"]["status"],
                )
                self.assertFalse(
                    report["paper_proposal_ledger"]["automatic_live_submission_possible"]
                )

    def test_path_risk_can_be_built_from_validated_historical_records(self):
        payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "path_risk_validated_history.json"
        )
        historical_report = build_historical_reconciliation_report(payload["rows"])

        report = build_path_risk_report_from_historical_report(
            historical_report,
            payload["path_risk_candidate"],
            generated_at="2026-07-07T10:30:00Z",
        )

        evidence = report["input_evidence"]
        self.assertEqual("validated_historical", evidence["status"])
        self.assertFalse(evidence["placeholder_data"])
        self.assertTrue(evidence["no_lookahead_declared"])
        self.assertGreaterEqual(evidence["eligible_path_count"], 2)
        self.assertEqual("ELIGIBLE", evidence["historical_eligibility_decision"])
        self.assertGreater(report["distributions"]["cvar_99_usdc"], 0.0)

    def test_path_risk_blocks_ineligible_historical_windows(self):
        valid_payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "path_risk_validated_history.json"
        )
        failure_payload = load_historical_fixture(
            FIXTURES / "historical_vendor" / "failure_fixtures.json",
            scenario="mark_mid_drift_failed",
        )
        historical_report = build_historical_reconciliation_report(failure_payload["rows"])

        report = build_path_risk_report_from_historical_report(
            historical_report,
            valid_payload["path_risk_candidate"],
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertEqual("blocked", report["input_evidence"]["status"])
        self.assertIn(
            "HISTORICAL_RECONCILIATION_NOT_ELIGIBLE",
            report["input_evidence"]["reason_codes"],
        )
        self.assertTrue(report["report_flags"]["spread_only_required"])

    def test_cli_path_risk_accepts_validated_historical_fixture(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "path-risk",
                "--historical-fixture",
                str(FIXTURES / "historical_vendor" / "path_risk_validated_history.json"),
                "--generated-at",
                "2026-07-07T10:30:00Z",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual("validated_historical", report["input_evidence"]["status"])

    def test_calibration_promotion_requires_explicit_evidence(self):
        default_report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )
        self.assertFalse(default_report["model_registry"]["promoted_for_sizing"])

        promoted = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
            promotion_evidence={
                "validated_historical_data": True,
                "validated_path_risk": True,
                "out_of_sample_passed": True,
                "external_review_approved": True,
                "paper_reconciliation_observed": True,
            },
        )
        self.assertEqual([], validate_walk_forward_calibration_report(promoted))
        registry = promoted["model_registry"]
        self.assertTrue(registry["promoted_for_sizing"])
        self.assertEqual("promoted", registry["promotion_status"])
        self.assertTrue(registry["promotion_evidence"]["validated_path_risk"])

    def test_private_replay_suite_maps_failures_to_no_trade(self):
        expectations = {
            "balance_margin_positions": ("available", "ALLOW_NEW"),
            "stale_auth": ("auth_failed", "NO_TRADE"),
            "stale_data": ("stale", "NO_TRADE"),
            "partial_positions": ("partial", "NO_TRADE"),
            "schema_drift": ("schema_drift", "NO_TRADE"),
            "malformed": ("malformed", "NO_TRADE"),
        }

        for scenario, (status_name, trade_gate) in expectations.items():
            with self.subTest(scenario=scenario):
                payload = load_private_replay_fixture(
                    FIXTURES / "private_account_replay.json",
                    scenario=scenario,
                )
                status = build_account_status(
                    generated_at="2026-07-07T09:51:00Z",
                    account_payload=payload,
                )

                self.assertEqual(status_name, status["status"])
                self.assertEqual(trade_gate, status["trade_gate"])
                contract = status["private_adapter_contract"]
                self.assertTrue(contract["auth_safe"])
                self.assertTrue(contract["replay_fixture"])
                self.assertFalse(contract["live_order_submission_possible"])
                self.assertIn("no_api_keys", contract["redaction_proof"])

    def test_paper_reconciliation_runbook_keeps_live_submission_impossible(self):
        runbook = build_paper_reconciliation_runbook()

        self.assertEqual("paper_reconciliation_runbook.v1", runbook["schema_version"])
        self.assertEqual(30, runbook["window_days"]["minimum"])
        self.assertEqual(60, runbook["window_days"]["target"])
        self.assertIn("observed_fill_when_available", runbook["required_observations"])
        self.assertFalse(runbook["automatic_live_submission_possible"])


if __name__ == "__main__":
    unittest.main()
