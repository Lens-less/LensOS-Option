import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from crypto_options_report.alerts import (
    deliver_webhook,
    evaluate_alerts,
    load_alert_state,
    save_alert_state,
    validate_alert_evaluation,
)
from crypto_options_report.cli import main
from crypto_options_report.contract import generate_research_report
from crypto_options_report.market_data import (
    _fetch_vol_index_feed,
    _fetch_option_instrument_metadata,
    write_snapshot_fixture,
)


FIXTURES = Path(__file__).parent / "fixtures"


class AlertsAndOpsTests(unittest.TestCase):
    def test_alert_eval_fires_risk_degradation_not_orders(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        evaluation = evaluate_alerts(report, cooldown_sec=0)
        self.assertEqual([], validate_alert_evaluation(evaluation))
        self.assertTrue(evaluation["research_only"])
        self.assertFalse(evaluation["trade_actions_allowed"])
        self.assertFalse(evaluation["delivery"]["automatic_live_submission_possible"])
        self.assertGreaterEqual(evaluation["summary"]["fired"], 1)
        rule_ids = {event["rule_id"] for event in evaluation["events"]}
        self.assertIn("release_readiness.nogo", rule_ids)
        for event in evaluation["events"]:
            self.assertIsNone(event.get("trade_action"))
            self.assertNotEqual("opportunity", event.get("category"))

    def test_alert_cooldown_suppresses_repeat_fingerprints(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        first = evaluate_alerts(report, cooldown_sec=3600)
        second = evaluate_alerts(
            report,
            previous_state=first["state"],
            cooldown_sec=3600,
        )
        self.assertGreaterEqual(first["summary"]["fired"], 1)
        self.assertEqual(0, second["summary"]["fired"])
        self.assertGreaterEqual(second["summary"]["suppressed"], 1)

    def test_opportunity_alerts_remain_blocked_without_evidence(self):
        snapshot = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(encoding="utf-8")
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
            account_scenario="green",
        )
        evaluation = evaluate_alerts(
            report,
            allow_opportunity_alerts=True,
            cooldown_sec=0,
        )
        self.assertFalse(evaluation["opportunity_alerts_allowed"])
        self.assertFalse(
            any(event["category"] == "opportunity" for event in evaluation["events"])
        )

    def test_webhook_dry_run_and_state_persistence(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        evaluation = evaluate_alerts(report, cooldown_sec=0)
        dry = deliver_webhook(
            evaluation,
            url="https://example.invalid/hooks/alerts",
            dry_run=True,
        )
        self.assertEqual("dry_run", dry["status"])

        with self.assertRaisesRegex(ValueError, "https"):
            deliver_webhook(
                evaluation,
                url="http://example.invalid/hooks/alerts",
                dry_run=True,
            )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "alert-state.json"
            save_alert_state(state_path, evaluation["state"])
            loaded = load_alert_state(state_path)
            self.assertEqual(evaluation["state"]["last_fired"], loaded["last_fired"])

    def test_cli_alert_eval_and_report_output_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code = main(
                [
                    "report",
                    "--generated-at",
                    "2026-07-07T00:01:30Z",
                    "--output",
                    str(out),
                    "--quiet",
                    "--fail-on-blocked",
                    "--compact",
                ]
            )
            self.assertEqual(10, code)
            self.assertTrue(out.exists())

            alert_out = Path(tmp) / "alerts.json"
            state = Path(tmp) / "state.json"
            code = main(
                [
                    "alert-eval",
                    "--report-json",
                    str(out),
                    "--state-file",
                    str(state),
                    "--output",
                    str(alert_out),
                    "--dry-run",
                    "--fail-on-alert",
                    "--compact",
                ]
            )
            self.assertEqual(11, code)
            payload = json.loads(alert_out.read_text(encoding="utf-8"))
            self.assertEqual("alert_evaluation.v1", payload["schema_version"])

    def test_write_snapshot_fixture_roundtrip(self):
        snapshot = {
            "captured_at": "2026-07-07T00:00:00Z",
            "currency": "BTC",
            "rows": [],
            "source": "unit-test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_snapshot_fixture(Path(tmp) / "snap.json", snapshot)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("BTC", loaded["currency"])
            self.assertEqual([], loaded["rows"])

    def test_fetch_vol_index_and_instruments_helpers(self):
        vol_payload = {
            "result": {
                "data": [
                    [1783382400000, 0.5, 0.6, 0.4, 55.0],
                ]
            }
        }
        instruments_payload = {
            "result": [
                {
                    "instrument_name": "BTC-9JUL26-90000-C",
                    "settlement_currency": "BTC",
                    "quote_currency": "BTC",
                    "base_currency": "BTC",
                }
            ]
        }

        def fake_get_json(url, params, timeout):
            if "get_volatility_index_data" in url:
                return vol_payload
            if "get_instruments" in url:
                return instruments_payload
            raise AssertionError(url)

        with mock.patch(
            "crypto_options_report.market_data._get_json",
            side_effect=fake_get_json,
        ):
            vol = _fetch_vol_index_feed(
                "https://www.deribit.com",
                currency="BTC",
                timeout=5,
                captured_at="2026-07-07T00:01:00Z",
            )
            meta = _fetch_option_instrument_metadata(
                "https://www.deribit.com",
                currency="BTC",
                timeout=5,
            )
        self.assertEqual("BTC DVOL", vol["index_name"])
        self.assertAlmostEqual(0.55, vol["volatility"], places=6)
        self.assertEqual("BTC", meta["BTC-9JUL26-90000-C"]["settlement_currency"])

    def test_malformed_dvol_row_fails_closed_without_crash(self):
        from crypto_options_report.market_data import fetch_deribit_option_chain_snapshot

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {"result": []}
            if "get_instruments" in url:
                return {"result": []}
            if "get_volatility_index_data" in url:
                return {"result": {"data": [[None, 0.5, 0.6, 0.4, 55.0]]}}
            raise AssertionError(url)

        with mock.patch(
            "crypto_options_report.market_data._get_json",
            side_effect=fake_get_json,
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=1,
            )
        expected_error = "vol_index: volatility index row missing timestamp"
        self.assertEqual([], snapshot["rows"])
        self.assertEqual({}, snapshot["feeds"])
        self.assertEqual([expected_error], snapshot["fetch_errors"])
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

    def test_live_adapter_malformed_timestamp_and_empty_dvol_return_structured_evidence(self):
        from crypto_options_report.market_data import fetch_deribit_option_chain_snapshot

        cases = {
            "non_integer_timestamp": (
                {"result": {"data": [["not-an-integer", 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "fractional_timestamp": (
                {"result": {"data": [[1783382445000.5, 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "fractional_dict_timestamp": (
                {"result": {"data": [{"timestamp": 1783382445000.5, "close": 55.0}]}},
                "volatility index timestamp is not integer-like",
            ),
            "boolean_timestamp": (
                {"result": {"data": [[True, 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "non_finite_timestamp": (
                {"result": {"data": [[float("inf"), 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "out_of_range_timestamp": (
                {"result": {"data": [[10**30, 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is out of range",
            ),
            "empty_data": (
                {"result": {"data": []}},
                "empty volatility index data",
            ),
        }

        for case_name, (dvol_payload, detail) in cases.items():
            with self.subTest(case=case_name):
                def fake_get_json(url, params, timeout):
                    if "get_book_summary_by_currency" in url:
                        return {"result": []}
                    if "get_instruments" in url:
                        return {"result": []}
                    if "get_volatility_index_data" in url:
                        return dvol_payload
                    raise AssertionError(url)

                with mock.patch(
                    "crypto_options_report.market_data._get_json",
                    side_effect=fake_get_json,
                ):
                    snapshot = fetch_deribit_option_chain_snapshot(
                        currency="BTC",
                        instrument_limit=1,
                    )

                expected_error = f"vol_index: {detail}"
                self.assertEqual([], snapshot["rows"])
                self.assertEqual({}, snapshot["feeds"])
                self.assertEqual([expected_error], snapshot["fetch_errors"])
                self.assertEqual(0, snapshot["instrument_metadata_count"])
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

    def test_instruments_do_not_infer_settlement_from_quote_currency(self):
        instruments_payload = {
            "result": [
                {
                    "instrument_name": "BTC-9JUL26-90000-C",
                    "quote_currency": "BTC",
                    "base_currency": "BTC",
                }
            ]
        }
        with mock.patch(
            "crypto_options_report.market_data._get_json",
            return_value=instruments_payload,
        ):
            meta = _fetch_option_instrument_metadata(
                "https://www.deribit.com",
                currency="BTC",
                timeout=5,
            )
        self.assertIsNone(meta["BTC-9JUL26-90000-C"]["settlement_currency"])
        self.assertEqual("missing", meta["BTC-9JUL26-90000-C"]["settlement_currency_source"])

    def test_smoke_once_live_query_omits_deribit_base_url(self):
        from crypto_options_report import api as api_mod

        captured: dict[str, Any] = {}

        def fake_request_json(port, path, timeout):
            if path == "/readyz":
                return {"service_ready": True}
            captured["path"] = path
            return {
                "schema_version": "research_report.v1",
                "action": "RESEARCH_ONLY",
            }

        with mock.patch.object(api_mod, "_request_json", side_effect=fake_request_json):
            with mock.patch.object(api_mod.time, "sleep", return_value=None):
                payload = api_mod.smoke_once(live_deribit=True, instrument_limit=1)
        self.assertEqual("research_report.v1", payload["schema_version"])
        self.assertIn("live_deribit=1", captured["path"])
        self.assertNotIn("deribit_base_url", captured["path"])

    def test_failed_webhook_does_not_persist_alert_state(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            state_path = Path(tmp) / "state.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with mock.patch(
                "crypto_options_report.cli.deliver_webhook",
                return_value={
                    "status": "failed",
                    "http_status": 500,
                    "error": "boom",
                    "event_count": 1,
                },
            ) as deliver:
                with mock.patch.dict(
                    "os.environ",
                    {"ALERT_WEBHOOK_SECRET": "test-secret"},
                ):
                    code = main(
                        [
                            "alert-eval",
                            "--report-json",
                            str(report_path),
                            "--state-file",
                            str(state_path),
                            "--webhook-url",
                            "https://example.invalid/hooks",
                            "--compact",
                        ]
                    )
            self.assertEqual(1, code)
            self.assertFalse(state_path.exists())
            self.assertEqual("test-secret", deliver.call_args.kwargs["secret"])

    def test_regime_input_provenance_marks_defaults(self):
        snapshot = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(encoding="utf-8")
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
        )
        provenance = report["permission_state"]["input_provenance"]
        self.assertTrue(provenance["synthetic_inputs"])
        self.assertIn(
            "REGIME_DEFAULTS_OR_FALLBACK_APPLIED",
            report["permission_state"]["reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
