import json
import math
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path

from crypto_options_report.historical import (
    HISTORICAL_REPORT_SCHEMA_VERSION,
    build_historical_reconciliation_report,
    load_historical_fixture,
    query_eligible_canonical_quotes,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "historical_vendor"


class HistoricalReconciliationTests(unittest.TestCase):
    def test_passing_fixture_normalizes_into_canonical_and_is_eligible(self):
        payload = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")

        report = build_historical_reconciliation_report(payload["rows"])

        self.assertEqual(HISTORICAL_REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertTrue(report["eligibility"]["training_allowed"])
        self.assertTrue(report["eligibility"]["backtest_allowed"])
        self.assertEqual(2, report["summary"]["eligible_quotes"])
        self.assertEqual(0, report["summary"]["fail_count"])
        self.assertEqual([], report["failures"])
        self.assertEqual([], report["quarantine"]["quotes"])

        metadata = report["canonical_data"]["instrument_metadata"]
        self.assertEqual(1, len(metadata))
        self.assertEqual("BTC-31JAN26-100000-C", metadata[0]["instrument_name"])
        self.assertEqual("USDC", metadata[0]["settlement_currency"])

        quote = report["canonical_data"]["eligible_quotes"][0]
        required_quote_keys = {
            "quote_id",
            "snapshot_key",
            "ts",
            "venue",
            "instrument_name",
            "currency",
            "settlement_currency",
            "expiry",
            "strike",
            "option_type",
            "bid",
            "ask",
            "mid",
            "mark_price",
            "bid_iv",
            "ask_iv",
            "mark_iv",
            "underlying_price",
            "open_interest",
            "volume_24h",
            "quote_age_ms",
            "data_vendor",
            "quality_status",
        }
        self.assertTrue(required_quote_keys.issubset(quote))

    def test_invalid_settlement_currency_is_quarantined_without_canonical_promotion(self):
        cases = (
            ("missing", lambda row: row.pop("settlement_currency", None)),
            ("null", lambda row: row.__setitem__("settlement_currency", None)),
            ("whitespace", lambda row: row.__setitem__("settlement_currency", "   ")),
            ("bool", lambda row: row.__setitem__("settlement_currency", True)),
            ("number", lambda row: row.__setitem__("settlement_currency", 123)),
            ("container", lambda row: row.__setitem__("settlement_currency", {"ccy": "USDC"})),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                rows = deepcopy(
                    load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
                )
                mutate(rows[0])

                report = build_historical_reconciliation_report(rows)

                self.assertEqual("INELIGIBLE", report["eligibility"]["decision"])
                self.assertEqual(0, report["summary"]["eligible_quotes"])
                self.assertEqual([], report["canonical_data"]["instrument_metadata"])
                self.assertEqual([], report["canonical_data"]["normalized_quotes"])
                self.assertEqual(
                    {"METADATA_MAPPING_FAILED": 1},
                    report["summary"]["failure_counts"],
                )
                self.assertEqual(
                    ["METADATA_MAPPING_FAILED"],
                    report["quarantine"]["quotes"][0]["failure_codes"],
                )

    def test_linear_put_payoff_replay_is_eligible(self):
        rows = deepcopy(
            load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
        )
        rows[0]["instrument_name"] = "BTC-31JAN26-100000-P"
        rows[0]["delivery_price"] = 95_000.0
        rows[0]["recorded_long_payoff"] = 5_000.0

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual("PUT", report["canonical_data"]["eligible_quotes"][0]["option_type"])

    def test_linear_contract_size_scales_payoff_replay(self):
        rows = deepcopy(
            load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
        )
        rows[0]["contract_size"] = 2.5
        rows[0]["recorded_long_payoff"] = 12_500.0

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual(
            2.5,
            report["canonical_data"]["instrument_metadata"][0]["contract_size"],
        )

    def test_inverse_call_payoff_replay_remains_eligible(self):
        rows = deepcopy(
            load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
        )
        rows[0]["settlement_currency"] = "BTC"
        rows[0]["quote_currency"] = "BTC"
        rows[0]["recorded_long_payoff"] = 5_000.0 / 105_000.0

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])

    def test_inverse_put_payoff_replay_is_eligible(self):
        rows = deepcopy(
            load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
        )
        rows[0]["instrument_name"] = "BTC-31JAN26-100000-P"
        rows[0]["settlement_currency"] = "BTC"
        rows[0]["quote_currency"] = "BTC"
        rows[0]["delivery_price"] = 95_000.0
        rows[0]["recorded_long_payoff"] = 5_000.0 / 95_000.0

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual("PUT", report["canonical_data"]["eligible_quotes"][0]["option_type"])

    def test_inverse_contract_size_scales_payoff_replay(self):
        rows = deepcopy(
            load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"][:1]
        )
        rows[0]["settlement_currency"] = "BTC"
        rows[0]["quote_currency"] = "BTC"
        rows[0]["contract_size"] = 2.5
        rows[0]["recorded_long_payoff"] = 2.5 * (5_000.0 / 105_000.0)

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual(
            2.5,
            report["canonical_data"]["instrument_metadata"][0]["contract_size"],
        )

    def test_surface_no_arb_evidence_is_explicit_finite_and_fail_closed(self):
        cases = (
            (
                "surface_no_arb_error=false",
                lambda row: row.__setitem__("surface_no_arb_error", False),
            ),
            (
                "surface_no_arb_error=nan",
                lambda row: row.__setitem__("surface_no_arb_error", float("nan")),
            ),
            (
                "surface_no_arb_error=-inf",
                lambda row: row.__setitem__("surface_no_arb_error", float("-inf")),
            ),
            (
                "surface_no_arb_error=negative",
                lambda row: row.__setitem__("surface_no_arb_error", -0.01),
            ),
            (
                "surface_no_arb_error=string",
                lambda row: row.__setitem__("surface_no_arb_error", "0.01"),
            ),
            (
                "surface_no_arb_error=missing",
                lambda row: row.pop("surface_no_arb_error", None),
            ),
            (
                "surface_no_arb_pass=false",
                lambda row: row.__setitem__("surface_no_arb_pass", False),
            ),
            (
                "surface_no_arb_pass=zero",
                lambda row: row.__setitem__("surface_no_arb_pass", 0),
            ),
            (
                "surface_no_arb_pass=one",
                lambda row: row.__setitem__("surface_no_arb_pass", 1),
            ),
            (
                "surface_no_arb_pass=string",
                lambda row: row.__setitem__("surface_no_arb_pass", "true"),
            ),
            (
                "surface_no_arb_pass=missing",
                lambda row: row.pop("surface_no_arb_pass", None),
            ),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                payload = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")
                for row in payload["rows"]:
                    row["surface_no_arb_error"] = 0.01
                    row["surface_no_arb_pass"] = True
                    mutate(row)

                report = build_historical_reconciliation_report(payload["rows"])

                self.assertEqual("INELIGIBLE", report["eligibility"]["decision"])
                self.assertFalse(report["eligibility"]["training_allowed"])
                self.assertFalse(report["eligibility"]["backtest_allowed"])
                self.assertEqual(0, report["summary"]["eligible_quotes"])
                self.assertIn(
                    "SURFACE_NO_ARB_FAILED",
                    report["summary"]["failure_counts"],
                )

    def test_reconciliation_config_is_strict_finite_and_semantically_bounded(self):
        invalid_configs = (
            ([], "config must be a mapping"),
            ({"unknown_threshold": 1.0}, "unknown reconciliation config fields"),
            ({"timestamp_alignment_seconds": True}, "timestamp_alignment_seconds must be finite and non-negative"),
            ({"min_iv": "0.01"}, "min_iv must be finite and non-negative"),
            ({"max_iv": float("nan")}, "max_iv must be finite and positive"),
            ({"max_mark_mid_drift_ratio": float("inf")}, "max_mark_mid_drift_ratio must be finite and non-negative"),
            ({"max_vendor_mid_diff_ratio": -0.01}, "max_vendor_mid_diff_ratio must be finite and non-negative"),
            ({"max_surface_no_arb_error": float("nan")}, "max_surface_no_arb_error must be finite and non-negative"),
            ({"max_surface_no_arb_error": 1e308}, "max_surface_no_arb_error must not exceed 1"),
            ({"max_payoff_bps_error": -1.0}, "max_payoff_bps_error must be finite and non-negative"),
            ({"max_payoff_bps_error": 1e308}, "max_payoff_bps_error must not exceed 10000"),
            ({"quantity_tolerance_contracts": False}, "quantity_tolerance_contracts must be finite and non-negative"),
            ({"default_tick_size": 0.0}, "default_tick_size must be finite and positive"),
            ({"default_contract_size": -1.0}, "default_contract_size must be finite and positive"),
            ({"min_iv": 2.0, "max_iv": 1.0}, "min_iv must not exceed max_iv"),
        )
        rows = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"]

        for config, expected_message in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_historical_reconciliation_report(rows, config=config)

    def test_every_reconciliation_config_field_rejects_coercive_values(self):
        nonnegative_fields = (
            "timestamp_alignment_seconds",
            "min_iv",
            "max_mark_mid_drift_ratio",
            "max_vendor_mid_diff_ratio",
            "max_surface_no_arb_error",
            "max_payoff_bps_error",
            "quantity_tolerance_contracts",
        )
        positive_fields = (
            "max_iv",
            "default_tick_size",
            "default_contract_size",
        )
        nonnegative_invalid_values = (
            False,
            True,
            "0.1",
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
        )
        positive_invalid_values = (*nonnegative_invalid_values, 0.0)
        rows = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"]

        for field_name in nonnegative_fields:
            for invalid_value in nonnegative_invalid_values:
                with self.subTest(
                    field_name=field_name,
                    invalid_value=invalid_value,
                ):
                    with self.assertRaises(ValueError):
                        build_historical_reconciliation_report(
                            rows,
                            config={field_name: invalid_value},
                        )
        for field_name in positive_fields:
            for invalid_value in positive_invalid_values:
                with self.subTest(
                    field_name=field_name,
                    invalid_value=invalid_value,
                ):
                    with self.assertRaises(ValueError):
                        build_historical_reconciliation_report(
                            rows,
                            config={field_name: invalid_value},
                        )

        report = build_historical_reconciliation_report(
            rows,
            config={
                "timestamp_alignment_seconds": 0.0,
                "min_iv": 0.0,
                "max_iv": 5.0,
                "max_mark_mid_drift_ratio": 0.0,
                "max_vendor_mid_diff_ratio": 0.0,
                "max_surface_no_arb_error": 0.0,
                "max_payoff_bps_error": 0.0,
                "quantity_tolerance_contracts": 0.0,
                "default_tick_size": 0.5,
                "default_contract_size": 1.0,
            },
        )
        json.dumps(report, allow_nan=False)

    def test_large_finite_quotes_use_overflow_safe_midpoints_and_strict_json(self):
        rows = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")["rows"]
        for row in rows:
            row["bid"] = 1e308
            row["ask"] = 1e308
            row["mark"] = 1e308

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        mids = [quote["mid"] for quote in report["canonical_data"]["eligible_quotes"]]
        self.assertEqual([1e308, 1e308], mids)
        self.assertTrue(all(math.isfinite(mid) for mid in mids))
        json.dumps(report, allow_nan=False)

    def test_failure_fixtures_cover_each_reconciliation_code(self):
        scenarios = load_historical_fixture(FIXTURE_DIR / "failure_fixtures.json")["scenarios"]

        observed_codes = set()
        for name, scenario in scenarios.items():
            with self.subTest(scenario=name):
                report = build_historical_reconciliation_report(scenario["rows"])
                code = scenario["expected_failure_code"]
                observed_codes.update(report["summary"]["failure_counts"])
                self.assertIn(code, report["summary"]["failure_counts"])
                self.assertEqual("INELIGIBLE", report["eligibility"]["decision"])
                self.assertEqual(0, report["summary"]["eligible_quotes"])
                self.assertGreaterEqual(report["summary"]["quarantined_quotes"], 1)

        self.assertEqual(
            {
                "METADATA_MAPPING_FAILED",
                "TIMESTAMP_ALIGNMENT_FAILED",
                "BID_ASK_SANITY_FAILED",
                "IV_SANITY_FAILED",
                "MARK_MID_DRIFT_FAILED",
                "VENDOR_DIFF_FAILED",
                "PAYOFF_REPLAY_FAILED",
                "OI_VOLUME_MAPPING_FAILED",
                "SURFACE_NO_ARB_FAILED",
            },
            observed_codes,
        )

    def test_query_returns_only_eligible_canonical_quotes(self):
        payload = load_historical_fixture(FIXTURE_DIR / "pass_fixture.json")
        report = build_historical_reconciliation_report(payload["rows"])

        eligible = query_eligible_canonical_quotes(
            report,
            instrument_name="BTC-31JAN26-100000-C",
            snapshot_key="btc-2026-01-15-0000",
        )

        self.assertEqual(2, len(eligible))
        self.assertTrue(
            all(quote["instrument_name"] == "BTC-31JAN26-100000-C" for quote in eligible)
        )

    def test_module_smoke_emits_eligible_report(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.historical",
                "--fixture",
                str(FIXTURE_DIR / "pass_fixture.json"),
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        report = json.loads(completed.stdout)

        self.assertEqual("", completed.stderr)
        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual(2, report["summary"]["eligible_quotes"])


if __name__ == "__main__":
    unittest.main()
