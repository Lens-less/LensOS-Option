import json
import subprocess
import sys
import unittest
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
