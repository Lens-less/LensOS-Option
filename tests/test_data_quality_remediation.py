import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_options_report.account_risk import (
    build_account_status,
    load_account_scenario,
)
from crypto_options_report.api import (
    HTTP_MAX_INSTRUMENT_LIMIT,
    RuntimeConfig,
    _report_from_query,
    _report_options_from_query,
    build_api_report,
)
from crypto_options_report.calibration import build_walk_forward_calibration_report
from crypto_options_report.contract import generate_research_report
from crypto_options_report.historical import (
    build_historical_reconciliation_report,
    load_historical_fixture,
)
from crypto_options_report.market_data import (
    build_market_data_status,
    load_snapshot_fixture,
    normalize_market_snapshot,
    parse_timestamp_ms,
    validate_deribit_base_url,
)
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

    def test_calibration_report_is_explicitly_unimplemented(self):
        report = build_walk_forward_calibration_report(
            generated_at="2026-07-07T00:01:30Z",
        )

        registry = report["model_registry"]
        self.assertEqual("not_implemented", report["status"])
        self.assertEqual("unavailable", report["evidence_class"])
        self.assertEqual("not_implemented", registry["promotion_status"])
        self.assertIsNone(registry["model_version"])
        self.assertIsNone(registry["artifact_id"])
        self.assertFalse(registry["promoted_for_sizing"])
        self.assertEqual(["CALIBRATION_NOT_IMPLEMENTED"], registry["blocking_reasons"])

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

    def test_paper_ledger_refuses_persistence_and_reconciliation_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "paper-ledger.json"
            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-07T00:01:30Z",
                report={"mode_gate": {"paper_manual_candidates_allowed": True}},
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

            self.assertEqual("unsupported", ledger["status"])
            self.assertEqual("NO-GO", ledger["release_state"])
            self.assertEqual([], ledger["proposals"])
            self.assertEqual([], ledger["ledger_entries"])
            self.assertFalse(ledger["automatic_live_submission_possible"])
            self.assertEqual("unsupported", ledger["persistence"]["mode"])
            self.assertFalse(ledger["persistence"]["write_allowed"])
            self.assertEqual("not_authorized", ledger["reconciliation"]["status"])
            self.assertFalse(path.exists())

    def test_caller_flags_cannot_authorize_paper_mode(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report={
                "mode_gate": {"paper_manual_candidates_allowed": True},
                "walk_forward_calibration": {
                    "status": "validated",
                    "model_registry": {"promoted_for_sizing": True},
                },
            },
            allow_paper=True,
        )

        self.assertEqual("unsupported", ledger["status"])
        self.assertEqual("not_authorized", ledger["authorization_state"])
        self.assertFalse(ledger["proposal_creation_allowed"])
        self.assertIn("PAPER_MODE_NOT_AUTHORIZED", ledger["reason_codes"])

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

    def test_release_readiness_exposes_only_external_authorization_gate(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        readiness = report["full_system_surface"]["release_readiness"]

        self.assertEqual("NO-GO", readiness["status"])
        self.assertFalse(readiness["paper_mode_allowed"])
        self.assertFalse(readiness["manual_execution_allowed"])
        self.assertEqual(
            ["external_release_authorization"],
            readiness["missing_prerequisites"],
        )
        self.assertEqual(1, len(readiness["prerequisites"]))
        gate = readiness["prerequisites"][0]
        self.assertEqual("external_release_authorization", gate["name"])
        self.assertFalse(gate["satisfied"])
        self.assertEqual("not_configured", gate["evidence_state"])
        self.assertEqual("awaiting_external", gate["release_state"])
        self.assertEqual("manual_external_authorization", gate["evidence_class"])
        self.assertEqual(
            ["EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED"],
            gate["reason_codes"],
        )

    def test_single_digit_expiry_parses_without_crash(self):
        snapshot = self._base_snapshot()
        row = copy.deepcopy(snapshot["rows"][0])
        row["instrument_name"] = "BTC-9JUL26-90000-C"
        row["summary"]["instrument_name"] = "BTC-9JUL26-90000-C"
        row["ticker"]["instrument_name"] = "BTC-9JUL26-90000-C"
        snapshot["rows"] = [row]

        normalized = normalize_market_snapshot(
            snapshot,
            now_ms=parse_timestamp_ms(snapshot["captured_at"]),
        )
        quote = normalized["quotes"][0]
        self.assertEqual("2026-07-09", quote["expiry_date"])
        self.assertEqual(90000.0, quote["strike"])
        self.assertNotIn("INSTRUMENT_PARSE_FAILED", quote["quality_flags"])

    def test_malformed_instrument_is_quarantined_not_crashed(self):
        snapshot = self._base_snapshot()
        row = copy.deepcopy(snapshot["rows"][0])
        row["instrument_name"] = "BTC-BADTOKEN-90000-C"
        row["summary"]["instrument_name"] = "BTC-BADTOKEN-90000-C"
        row["ticker"]["instrument_name"] = "BTC-BADTOKEN-90000-C"
        snapshot["rows"] = [row]

        normalized = normalize_market_snapshot(
            snapshot,
            now_ms=parse_timestamp_ms(snapshot["captured_at"]),
        )
        quote = normalized["quotes"][0]
        self.assertEqual("invalid", quote["quality_status"])
        self.assertIn("INSTRUMENT_PARSE_FAILED", quote["quality_flags"])

    def test_missing_vol_index_blocks_market_validation(self):
        snapshot = self._base_snapshot()
        snapshot.pop("feeds", None)

        status = build_market_data_status(
            snapshot,
            now_ms=parse_timestamp_ms(snapshot["captured_at"]),
        )
        self.assertEqual("blocked", status["status"])
        self.assertIn("REQUIRED_FEED_MISSING", status["quality_gate"]["reason_codes"])
        self.assertIn("VOL_INDEX_MISSING", status["quality_gate"]["reason_codes"])

    def test_http_query_rejects_ssrf_base_url_and_path_escape(self):
        with self.assertRaisesRegex(ValueError, "deribit_base_url"):
            _report_from_query("live_deribit=1&deribit_base_url=http://127.0.0.1:9")
        with self.assertRaisesRegex(ValueError, "snapshot_fixture"):
            _report_from_query("snapshot_fixture=C:/Windows/win.ini")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            validate_deribit_base_url("https://evil.example")
        # Local fixture inside repo remains loadable without HTTP sandbox.
        report = build_api_report(
            snapshot_fixture=str(FIXTURES / "deribit_btc_option_chain_snapshot.json"),
            generated_at="2026-07-07T00:01:30Z",
        )
        self.assertEqual("research_report.v1", report["schema_version"])

    def test_http_live_limit_is_validated_before_any_network_call(self):
        with patch("crypto_options_report.api.fetch_deribit_option_chain_snapshot") as fetch:
            with self.assertRaisesRegex(ValueError, ">= 1"):
                _report_from_query(
                    "live_deribit=1&instrument_limit=-1",
                    runtime=RuntimeConfig(
                        profile="development",
                        allow_live_fetch=True,
                    ),
                )
        fetch.assert_not_called()

    def test_explicit_live_fetch_gate_drives_the_default_development_report(self):
        options = _report_options_from_query(
            "",
            runtime=RuntimeConfig(
                profile="development",
                allow_live_fetch=True,
            ),
        )

        self.assertTrue(options["live_deribit"])
        self.assertEqual(HTTP_MAX_INSTRUMENT_LIMIT, options["instrument_limit"])

    def test_snapshot_fixture_startup_preflight_rejects_non_object_rows(self):
        invalid_rows_cases = (
            {"oops": "not a list"},
            "not-a-list",
            ["not-an-object"],
            [{"instrument_name": "BTC-25JUL26-90000-C"}, []],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "snapshot.json"
            for rows in invalid_rows_cases:
                with self.subTest(rows=rows):
                    fixture_path.write_text(
                        json.dumps(
                            {
                                "captured_at": "2026-07-07T00:01:30Z",
                                "rows": rows,
                            }
                        ),
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(
                        ValueError,
                        "rows must be a list of JSON objects",
                    ):
                        RuntimeConfig(
                            profile="production",
                            snapshot_fixture=str(fixture_path),
                        ).validate()

    def test_snapshot_fixture_loader_preserves_empty_rows_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "empty-snapshot.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "captured_at": "2026-07-07T00:01:30Z",
                        "rows": [],
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_snapshot_fixture(fixture_path)

        self.assertEqual([], snapshot["rows"])
        self.assertEqual("fixture:empty-snapshot.json", snapshot["source"])
        self.assertEqual("BTC", snapshot["currency"])

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

if __name__ == "__main__":
    unittest.main()
