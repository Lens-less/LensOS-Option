import unittest
from pathlib import Path
from unittest import mock

from crypto_options_report.contract import generate_research_report
from crypto_options_report.market_data import (
    build_market_data_status,
    fetch_deribit_option_chain_snapshot,
    load_public_replay_fixture,
)

FIXTURES = Path(__file__).parent / "fixtures"


class DvolFailClosedTests(unittest.TestCase):
    def test_live_public_adapter_returns_structured_evidence_for_malformed_dvol(self):
        cases = {
            "null_timestamp": (
                {"result": {"data": [[None, 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index row missing timestamp",
            ),
            "non_integer_timestamp": (
                {"result": {"data": [["not-an-integer", 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "fractional_list_timestamp": (
                {"result": {"data": [[1783382445000.5, 0.5, 0.6, 0.4, 55.0]]}},
                "volatility index timestamp is not integer-like",
            ),
            "fractional_dict_timestamp": (
                {
                    "result": {
                        "data": [{"timestamp": 1783382445000.5, "close": 55.0}]
                    }
                },
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
                {"result": {"data": [[10**400, 0.5, 0.6, 0.4, 55.0]]}},
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
                    if "get_volatility_index_data" in url:
                        return dvol_payload
                    raise AssertionError(f"unexpected network boundary: {url}")

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

    def test_offline_replay_blocks_trust_and_keeps_trading_modes_closed(self):
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
        ) as network_boundary:
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
                    for reason_code in (
                        "PUBLIC_SCHEMA_DRIFT_MALFORMED",
                        "PUBLIC_FETCH_ERRORS_PRESENT",
                        "REQUIRED_FEED_MISSING",
                        "VOL_INDEX_MISSING",
                    ):
                        self.assertIn(
                            reason_code,
                            status["quality_gate"]["reason_codes"],
                        )
                    self.assertEqual("untrusted", report["data_trust"]["verdict"])
                    self.assertEqual("replay", report["data_trust"]["source_class"])
                    self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
                    self.assertEqual("research_only", report["effective_mode"])
                    self.assertFalse(
                        report["paper_proposal_ledger"][
                            "automatic_live_submission_possible"
                        ]
                    )

            closed_snapshot = load_public_replay_fixture(
                FIXTURES / "public_deribit_replay.json",
                scenario="empty_dvol_data",
            )
            for mode in ("paper", "manual_execution"):
                with self.subTest(mode=mode):
                    report = generate_research_report(
                        mode=mode,
                        generated_at=closed_snapshot["captured_at"],
                        market_snapshot=closed_snapshot,
                    )
                    self.assertEqual("research_only", report["effective_mode"])
                    self.assertEqual("NO_TRADE", report["action"])
                    self.assertEqual("untrusted", report["data_trust"]["verdict"])
                    self.assertFalse(
                        report["mode_gate"]["paper_manual_candidates_allowed"]
                    )
                    self.assertEqual(
                        "NO-GO",
                        report["full_system_surface"]["release_readiness"]["status"],
                    )
                    self.assertFalse(
                        report["paper_proposal_ledger"][
                            "automatic_live_submission_possible"
                        ]
                    )

            with self.assertRaisesRegex(ValueError, "unsupported mode 'live'"):
                generate_research_report(
                    mode="live",
                    generated_at=closed_snapshot["captured_at"],
                    market_snapshot=closed_snapshot,
                )

        network_boundary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
