import json
import tempfile
import threading
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
    build_market_data_status,
    fetch_deribit_option_chain_snapshot,
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

    def test_alert_eval_treats_malformed_last_fired_as_empty_state(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")

        for malformed in ([1], 7, None):
            with self.subTest(last_fired=malformed):
                previous_state = {
                    "schema_version": "alert_state.v1",
                    "updated_at": "2026-07-07T00:00:00Z",
                    "last_fired": malformed,
                }

                evaluation = evaluate_alerts(
                    report,
                    previous_state=previous_state,
                    cooldown_sec=3600,
                )

                self.assertGreaterEqual(evaluation["summary"]["fired"], 1)
                self.assertEqual(0, evaluation["summary"]["suppressed"])
                self.assertIsInstance(evaluation["state"]["last_fired"], dict)
                self.assertEqual(malformed, previous_state["last_fired"])

    def test_alert_eval_ignores_invalid_last_fired_timestamps(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        baseline = evaluate_alerts(report, cooldown_sec=0)
        fingerprint = baseline["events"][0]["fingerprint"]

        invalid_values = {
            "string": "bad",
            "object": {"ms": 1},
            "list": [1],
            "bool": True,
            "infinity": float("inf"),
            "nan": float("nan"),
        }

        for label, malformed in invalid_values.items():
            with self.subTest(last_fired=label):
                previous_state = {
                    "schema_version": "alert_state.v1",
                    "updated_at": "2026-07-07T00:00:00Z",
                    "last_fired": {fingerprint: malformed},
                }

                evaluation = evaluate_alerts(
                    report,
                    previous_state=previous_state,
                    cooldown_sec=3600,
                )

                self.assertGreaterEqual(evaluation["summary"]["fired"], 1)
                self.assertEqual(0, evaluation["summary"]["suppressed"])
                self.assertIsInstance(evaluation["state"]["last_fired"][fingerprint], int)
                self.assertIs(malformed, previous_state["last_fired"][fingerprint])

    def test_alert_eval_preserves_valid_integer_like_last_fired_timestamps(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        baseline = evaluate_alerts(report, cooldown_sec=0)
        fingerprint = baseline["events"][0]["fingerprint"]
        valid_timestamp = float(baseline["state"]["last_fired"][fingerprint])

        evaluation = evaluate_alerts(
            report,
            previous_state={
                "schema_version": "alert_state.v1",
                "updated_at": "2026-07-07T00:00:00Z",
                "last_fired": {
                    fingerprint: valid_timestamp,
                    "bad-string": "bad",
                    "bad-object": {"ms": 1},
                    "bad-list": [1],
                    "bad-bool": False,
                    "bad-infinity": float("inf"),
                },
            },
            cooldown_sec=3600,
        )

        self.assertGreaterEqual(evaluation["summary"]["suppressed"], 1)
        suppressed = {
            event["fingerprint"]: event
            for event in evaluation["suppressed"]
        }
        self.assertIn(fingerprint, suppressed)
        self.assertEqual(int(valid_timestamp), evaluation["state"]["last_fired"][fingerprint])
        self.assertNotIn("bad-string", evaluation["state"]["last_fired"])
        self.assertNotIn("bad-object", evaluation["state"]["last_fired"])
        self.assertNotIn("bad-list", evaluation["state"]["last_fired"])
        self.assertNotIn("bad-bool", evaluation["state"]["last_fired"])
        self.assertNotIn("bad-infinity", evaluation["state"]["last_fired"])

    def test_alert_eval_ignores_negative_and_future_last_fired_timestamps(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        baseline = evaluate_alerts(report, cooldown_sec=0)
        fingerprint = baseline["events"][0]["fingerprint"]
        now_ms = baseline["state"]["last_fired"][fingerprint]

        for label, malformed in (
            ("negative", -1),
            ("future", now_ms + 10_000_000),
        ):
            with self.subTest(last_fired=label):
                evaluation = evaluate_alerts(
                    report,
                    previous_state={
                        "schema_version": "alert_state.v1",
                        "updated_at": "2026-07-07T00:00:00Z",
                        "last_fired": {fingerprint: malformed},
                    },
                    cooldown_sec=3600,
                )

                self.assertGreaterEqual(evaluation["summary"]["fired"], 1)
                self.assertEqual(0, evaluation["summary"]["suppressed"])
                self.assertEqual(now_ms, evaluation["state"]["last_fired"][fingerprint])

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

    def test_cli_alert_eval_treats_malformed_last_fired_state_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
            report_path = Path(tmp) / "report.json"
            state_path = Path(tmp) / "state.json"
            alert_out = Path(tmp) / "alerts.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "alert_state.v1",
                        "updated_at": "2026-07-07T00:00:00Z",
                        "last_fired": [1],
                    }
                ),
                encoding="utf-8",
            )

            code = main(
                [
                    "alert-eval",
                    "--report-json",
                    str(report_path),
                    "--state-file",
                    str(state_path),
                    "--output",
                    str(alert_out),
                    "--dry-run",
                    "--fail-on-alert",
                    "--compact",
                ]
            )

            self.assertEqual(11, code)
            payload = json.loads(alert_out.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["summary"]["fired"], 1)
            self.assertEqual(0, payload["summary"]["suppressed"])

    def test_cli_alert_eval_ignores_invalid_last_fired_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
            fingerprint = evaluate_alerts(report, cooldown_sec=0)["events"][0]["fingerprint"]
            report_path = Path(tmp) / "report.json"
            alert_out = Path(tmp) / "alerts.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            invalid_values = {
                "string": "bad",
                "object": {"ms": 1},
                "list": [1],
                "bool": True,
                "infinity": float("inf"),
                "nan": float("nan"),
            }

            for label, malformed in invalid_values.items():
                with self.subTest(last_fired=label):
                    state_path = Path(tmp) / f"state-{label}.json"
                    state_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "alert_state.v1",
                                "updated_at": "2026-07-07T00:00:00Z",
                                "last_fired": {fingerprint: malformed},
                            }
                        ),
                        encoding="utf-8",
                    )

                    code = main(
                        [
                            "alert-eval",
                            "--report-json",
                            str(report_path),
                            "--state-file",
                            str(state_path),
                            "--output",
                            str(alert_out),
                            "--dry-run",
                            "--fail-on-alert",
                            "--compact",
                        ]
                    )

                    self.assertEqual(11, code)
                    payload = json.loads(alert_out.read_text(encoding="utf-8"))
                    self.assertGreaterEqual(payload["summary"]["fired"], 1)
                    self.assertEqual(0, payload["summary"]["suppressed"])

    def test_cli_alert_eval_ignores_negative_and_future_last_fired_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
            baseline = evaluate_alerts(report, cooldown_sec=0)
            fingerprint = baseline["events"][0]["fingerprint"]
            now_ms = baseline["state"]["last_fired"][fingerprint]
            report_path = Path(tmp) / "report.json"
            alert_out = Path(tmp) / "alerts.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            for label, malformed in (
                ("negative", -1),
                ("future", now_ms + 10_000_000),
            ):
                with self.subTest(last_fired=label):
                    state_path = Path(tmp) / f"state-{label}.json"
                    state_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "alert_state.v1",
                                "updated_at": "2026-07-07T00:00:00Z",
                                "last_fired": {fingerprint: malformed},
                            }
                        ),
                        encoding="utf-8",
                    )

                    code = main(
                        [
                            "alert-eval",
                            "--report-json",
                            str(report_path),
                            "--state-file",
                            str(state_path),
                            "--output",
                            str(alert_out),
                            "--dry-run",
                            "--fail-on-alert",
                            "--compact",
                        ]
                    )

                    self.assertEqual(11, code)
                    payload = json.loads(alert_out.read_text(encoding="utf-8"))
                    self.assertGreaterEqual(payload["summary"]["fired"], 1)
                    self.assertEqual(0, payload["summary"]["suppressed"])

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
        observed_vol_params = {}
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
                observed_vol_params.update(params)
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
        self.assertEqual(60, observed_vol_params["resolution"])
        self.assertEqual("BTC", meta["BTC-9JUL26-90000-C"]["settlement_currency"])

    def test_deribit_vol_index_uses_documented_percent_point_unit_at_low_values(self):
        payload = {
            "result": {
                "data": [[1783382400000, 4.1, 4.2, 3.9, 4.0]],
            }
        }
        with mock.patch(
            "crypto_options_report.market_data._get_json",
            return_value=payload,
        ):
            vol = _fetch_vol_index_feed(
                "https://www.deribit.com",
                currency="BTC",
                timeout=5,
                captured_at="2026-07-07T00:01:00Z",
            )

        self.assertEqual(0.04, vol["volatility"])
        self.assertEqual("fraction", vol["volatility_unit"])
        self.assertEqual("percent_points", vol["raw_close_unit"])

    def test_one_minute_dvol_rollover_does_not_flicker_stale(self):
        base = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        base["feeds"]["vol_index"]["timestamp"] = "2026-07-07T00:00:00Z"

        rollover = json.loads(json.dumps(base))
        rollover["captured_at"] = "2026-07-07T00:01:03Z"
        rollover_status = build_market_data_status(
            rollover,
            now_ms=1783382463000,
        )
        self.assertEqual(
            "available",
            rollover_status["public_response_contract"]["endpoints"]["vol_index"][
                "status"
            ],
        )
        self.assertEqual(
            90,
            rollover_status["public_response_contract"]["endpoints"]["vol_index"][
                "max_age_sec"
            ],
        )

        stale = json.loads(json.dumps(base))
        stale["captured_at"] = "2026-07-07T00:01:31Z"
        stale_status = build_market_data_status(stale, now_ms=1783382491000)
        self.assertEqual(
            "stale",
            stale_status["public_response_contract"]["endpoints"]["vol_index"][
                "status"
            ],
        )
        self.assertIn(
            "VOL_INDEX_STALE",
            stale_status["quality_gate"]["reason_codes"],
        )

    def test_isolated_bad_quote_is_quarantined_within_declared_ratio(self):
        snapshot = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot["rows"][0]["ticker"]["bid_iv"] = 0

        status = build_market_data_status(
            snapshot,
            now_ms=1783382490000,
            limits={"min_valid_quotes_per_expiry": 7},
        )

        self.assertEqual("validated", status["status"])
        self.assertTrue(status["quality_gate"]["passed"])
        expiry = status["quality_gate"]["per_expiry"][0]
        self.assertEqual(7, expiry["valid_quotes"])
        self.assertEqual(1, expiry["invalid_quotes"])
        self.assertEqual(0.125, expiry["bad_quote_ratio"])
        self.assertIn("INVALID_BID_IV", expiry["observed_quality_flags"])
        self.assertNotIn("INVALID_BID_IV", expiry["reason_codes"])
        contract = status["public_response_contract"]
        self.assertEqual("pass", contract["overall_status"])
        self.assertEqual(1, contract["quarantined_quotes"])
        self.assertTrue(contract["response_classes"]["quality_quarantined"])
        self.assertFalse(contract["response_classes"]["malformed"])

    def test_live_collector_retains_successful_book_summaries(self):
        instrument_name = "BTC-9JUL26-90000-C"

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "bid_price": 0.01,
                            "ask_price": 0.02,
                        }
                    ]
                }
            if "/ticker" in url:
                return {
                    "result": {
                        "instrument_name": instrument_name,
                        "timestamp": 1783382460000,
                    }
                }
            if "get_instruments" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "settlement_currency": "BTC",
                            "quote_currency": "BTC",
                            "base_currency": "BTC",
                        }
                    ]
                }
            if "get_volatility_index_data" in url:
                return {
                    "result": {
                        "data": [[1783382400000, 0.5, 0.6, 0.4, 55.0]],
                    }
                }
            raise AssertionError(url)

        with mock.patch(
            "crypto_options_report.market_data._get_json",
            side_effect=fake_get_json,
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=1,
            )

        self.assertEqual([], snapshot["fetch_errors"])
        self.assertEqual(1, snapshot["instrument_metadata_count"])
        self.assertEqual([instrument_name], [row["instrument_name"] for row in snapshot["rows"]])
        self.assertEqual(
            "explicit_settlement_currency",
            snapshot["rows"][0]["summary"]["settlement_currency_source"],
        )

    def test_live_collector_marks_completion_time_and_runs_auxiliary_feeds_with_ticker(self):
        instrument_name = "BTC-24JUL26-100000-C"
        concurrent_requests = threading.Barrier(3, timeout=2)

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "bid_price": 0.01,
                            "ask_price": 0.011,
                        }
                    ]
                }
            if "/ticker" in url:
                concurrent_requests.wait()
                return {
                    "result": {
                        "instrument_name": instrument_name,
                        "timestamp": 1783872000000,
                    }
                }
            if "get_instruments" in url:
                concurrent_requests.wait()
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "settlement_currency": "BTC",
                            "quote_currency": "BTC",
                            "base_currency": "BTC",
                        }
                    ]
                }
            if "get_volatility_index_data" in url:
                concurrent_requests.wait()
                return {
                    "result": {
                        "data": [[1783872000000, 0.5, 0.6, 0.4, 55.0]],
                    }
                }
            raise AssertionError(url)

        with (
            mock.patch(
                "crypto_options_report.market_data._get_json",
                side_effect=fake_get_json,
            ),
            mock.patch(
                "crypto_options_report.market_data.utc_timestamp",
                side_effect=[
                    "2026-07-12T16:00:00Z",
                    "2026-07-12T16:00:12Z",
                ],
            ),
            mock.patch(
                "crypto_options_report.market_data.monotonic",
                side_effect=[100.0, 112.345],
                create=True,
            ),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=1,
            )

        self.assertEqual([], snapshot["fetch_errors"])
        self.assertEqual("2026-07-12T16:00:00Z", snapshot["collection_started_at"])
        self.assertEqual("2026-07-12T16:00:12Z", snapshot["captured_at"])
        self.assertEqual(12345, snapshot["collection_duration_ms"])
        self.assertEqual(1, snapshot["instrument_metadata_count"])
        self.assertIn("vol_index", snapshot["feeds"])

    def test_live_collector_selects_bounded_stratified_research_universe(self):
        captured_at = "2026-07-12T16:00:00Z"
        captured_ms = 1783872000000

        def summary(expiry: str, strike: int, option_type: str, *, liquid: bool = True):
            bid = 0.01 if liquid else 0.0
            ask = 0.011 if liquid else 0.02
            return {
                "instrument_name": f"BTC-{expiry}-{strike}-{option_type}",
                "bid_price": bid,
                "ask_price": ask,
                "underlying_price": 64000.0,
            }

        upstream = [
            summary("13JUL26", 56000 + offset * 1000, "C")
            for offset in range(10)
        ]
        upstream.extend(
            summary("24JUL26", 50000 + offset * 1000, "C")
            for offset in range(10)
        )
        upstream.extend(
            summary("31JUL26", 50000 + offset * 1000, "C")
            for offset in range(10)
        )
        upstream.extend(
            summary("24JUL26", 65000 + offset * 1000, "C")
            for offset in range(10)
        )
        upstream.extend(
            summary("31JUL26", 65000 + offset * 1000, "C")
            for offset in range(10)
        )
        upstream.extend(
            summary("24JUL26", 110000 + offset * 1000, "P")
            for offset in range(4)
        )
        upstream.extend(
            summary("31JUL26", 120000 + offset * 1000, "C", liquid=False)
            for offset in range(4)
        )
        ticker_requests = []

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {"result": upstream}
            if "/ticker" in url:
                ticker_requests.append(params["instrument_name"])
                return {
                    "result": {
                        "instrument_name": params["instrument_name"],
                        "timestamp": captured_ms,
                        "best_bid_price": 0.01,
                        "best_ask_price": 0.011,
                        "best_bid_amount": 5.0,
                        "best_ask_amount": 5.0,
                        "bid_iv": 50.0,
                        "ask_iv": 51.0,
                        "mark_iv": 50.5,
                        "underlying_price": 100000.0,
                    }
                }
            if "get_instruments" in url:
                return {
                    "result": [
                        {
                            "instrument_name": row["instrument_name"],
                            "settlement_currency": "BTC",
                            "quote_currency": "BTC",
                            "base_currency": "BTC",
                        }
                        for row in upstream
                    ]
                }
            if "get_volatility_index_data" in url:
                return {"result": {"data": [[captured_ms, 0.5, 0.6, 0.4, 55.0]]}}
            raise AssertionError(url)

        with (
            mock.patch(
                "crypto_options_report.market_data._get_json",
                side_effect=fake_get_json,
            ),
            mock.patch(
                "crypto_options_report.market_data.utc_timestamp",
                return_value=captured_at,
            ),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=20,
            )
            bounded_ticker_requests = list(ticker_requests)
            ticker_requests.clear()
            fallback_snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=5,
            )
            fallback_ticker_requests = list(ticker_requests)

        selected_names = [row["instrument_name"] for row in snapshot["rows"]]
        self.assertEqual(58, snapshot["upstream_instrument_count"])
        self.assertEqual(20, snapshot["selected_instrument_count"])
        self.assertEqual(20, len(bounded_ticker_requests))
        self.assertEqual(set(selected_names), set(bounded_ticker_requests))
        self.assertTrue(all("-C" in name for name in selected_names))
        self.assertFalse(any("13JUL26" in name for name in selected_names))
        self.assertTrue(
            all(int(name.split("-")[2]) >= 64000 for name in selected_names)
        )
        self.assertEqual(
            {"2026-07-24": 10, "2026-07-31": 10},
            snapshot["selection_policy"]["selected_per_expiry"],
        )
        self.assertEqual(
            "research_candidate_stratified_v1",
            snapshot["selection_policy"]["name"],
        )
        self.assertFalse(snapshot["selection_policy"]["fallback_used"])
        data_status = build_market_data_status(snapshot, now_ms=captured_ms)
        collection_scope = data_status["collection_scope"]
        self.assertEqual("research_sample", collection_scope["scope"])
        self.assertEqual(58, collection_scope["upstream_instrument_count"])
        self.assertEqual(20, collection_scope["selected_instrument_count"])
        self.assertEqual(
            snapshot["selection_policy"],
            collection_scope["selection_policy"],
        )
        self.assertEqual(
            collection_scope,
            data_status["public_response_contract"]["collection_scope"],
        )
        fallback_names = [
            row["instrument_name"] for row in fallback_snapshot["rows"]
        ]
        self.assertEqual(5, len(fallback_ticker_requests))
        self.assertEqual(set(fallback_names), set(fallback_ticker_requests))
        self.assertTrue(fallback_snapshot["selection_policy"]["fallback_used"])
        self.assertTrue(
            all(int(name.split("-")[2]) >= 64000 for name in fallback_names)
        )

    def test_live_collector_rejects_limits_above_the_public_request_budget(self):
        with self.assertRaisesRegex(
            ValueError,
            "instrument_limit must be between 1 and 20",
        ):
            fetch_deribit_option_chain_snapshot(instrument_limit=21)

    def test_live_collector_classifies_ticker_rate_limits_fail_closed(self):
        instrument_name = "BTC-24JUL26-100000-C"
        captured_at = "2026-07-12T16:00:00Z"
        captured_ms = 1783872000000

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "bid_price": 0.01,
                            "ask_price": 0.011,
                        }
                    ]
                }
            if "/ticker" in url:
                raise ValueError("http 429 Too Many Requests")
            if "get_instruments" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "settlement_currency": "BTC",
                            "quote_currency": "BTC",
                            "base_currency": "BTC",
                        }
                    ]
                }
            if "get_volatility_index_data" in url:
                return {"result": {"data": [[captured_ms, 0.5, 0.6, 0.4, 55.0]]}}
            raise AssertionError(url)

        with (
            mock.patch(
                "crypto_options_report.market_data._get_json",
                side_effect=fake_get_json,
            ),
            mock.patch(
                "crypto_options_report.market_data.utc_timestamp",
                return_value=captured_at,
            ),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=1,
            )

        self.assertEqual(
            [f"{instrument_name}: http 429 Too Many Requests"],
            snapshot["fetch_errors"],
        )
        self.assertEqual(1, len(snapshot["adapter_events"]))
        event = snapshot["adapter_events"][0]
        self.assertEqual("rate_limit", event["class"])
        self.assertEqual("public/ticker", event["endpoint"])
        self.assertEqual(instrument_name, event["instrument_name"])
        self.assertTrue(event["retryable"])

    def test_live_collector_classifies_deribit_jsonrpc_10028_as_retryable_rate_limit(self):
        instrument_name = "BTC-24JUL26-100000-C"
        captured_at = "2026-07-12T16:00:00Z"
        captured_ms = 1783872000000

        def fake_get_json(url, params, timeout):
            if "get_book_summary_by_currency" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "bid_price": 0.01,
                            "ask_price": 0.011,
                        }
                    ]
                }
            if "/ticker" in url:
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": 10028,
                        "message": "too_many_requests",
                    },
                }
            if "get_instruments" in url:
                return {
                    "result": [
                        {
                            "instrument_name": instrument_name,
                            "settlement_currency": "BTC",
                            "quote_currency": "BTC",
                            "base_currency": "BTC",
                        }
                    ]
                }
            if "get_volatility_index_data" in url:
                return {"result": {"data": [[captured_ms, 0.5, 0.6, 0.4, 55.0]]}}
            raise AssertionError(url)

        with (
            mock.patch(
                "crypto_options_report.market_data._get_json",
                side_effect=fake_get_json,
            ),
            mock.patch(
                "crypto_options_report.market_data.utc_timestamp",
                return_value=captured_at,
            ),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                currency="BTC",
                instrument_limit=1,
            )

        self.assertEqual(1, len(snapshot["adapter_events"]))
        event = snapshot["adapter_events"][0]
        self.assertEqual("rate_limit", event["class"])
        self.assertEqual("public/ticker", event["endpoint"])
        self.assertEqual(instrument_name, event["instrument_name"])
        self.assertTrue(event["retryable"])
        self.assertIn("rpc error 10028: too_many_requests", event["message"])

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

    def test_regime_without_bound_history_collects_instead_of_using_defaults(self):
        snapshot = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(encoding="utf-8")
        )
        report = generate_research_report(
            generated_at=snapshot["captured_at"],
            market_snapshot=snapshot,
        )
        permission = report["permission_state"]
        provenance = permission["input_provenance"]
        self.assertEqual("blocked", permission["status"])
        self.assertEqual("collecting", permission["collection_status"])
        self.assertFalse(provenance["synthetic_inputs"])
        self.assertEqual([], provenance["defaults_applied"])
        self.assertIn(
            "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
            permission["reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
