import json
import subprocess
import sys
import unittest
from pathlib import Path

from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)


class DataTrustSummaryTests(unittest.TestCase):
    def test_report_without_market_data_is_explicitly_untrusted(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        self.assertEqual(
            {
                "verdict": "untrusted",
                "reason_codes": ["MISSING_VALIDATED_MARKET_DATA"],
                "source_class": "missing",
            },
            report["data_trust"],
        )

    def test_validator_rejects_report_without_data_trust(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")
        report.pop("data_trust")

        self.assertIn(
            "missing required keys: ['data_trust']",
            validate_report_contract(report),
        )

    def test_validator_rejects_invalid_data_trust_values(self):
        invalid_values = (
            ("verdict", "unknown", "data_trust.verdict must be trusted, degraded, or untrusted"),
            (
                "reason_codes",
                "MISSING_VALIDATED_MARKET_DATA",
                "data_trust.reason_codes must be a list of strings",
            ),
            (
                "source_class",
                "unknown",
                "data_trust.source_class must be live, fixture, replay, or missing",
            ),
        )

        for field, value, expected_error in invalid_values:
            with self.subTest(field=field):
                report = generate_research_report(
                    generated_at="2026-07-07T00:00:00Z"
                )
                report["data_trust"][field] = value

                self.assertIn(expected_error, validate_report_contract(report))

    def test_validator_rejects_trusted_summary_when_market_is_missing(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")
        report["data_trust"] = {
            "verdict": "trusted",
            "reason_codes": [],
            "source_class": "fixture",
        }

        errors = validate_report_contract(report)

        self.assertIn(
            "missing market data must have untrusted data_trust.verdict", errors
        )
        self.assertIn(
            "missing market data must have missing data_trust.source_class", errors
        )
        self.assertIn(
            "missing market data trust must include MISSING_VALIDATED_MARKET_DATA",
            errors,
        )

    def test_present_market_stays_untrusted_until_promotion_policy_exists(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )

        self.assertEqual("validated", report["data_status"]["status"])
        self.assertEqual(
            {
                "verdict": "untrusted",
                "reason_codes": ["DATA_TRUST_PROMOTION_PENDING"],
                "source_class": "fixture",
            },
            report["data_trust"],
        )

    def test_validator_rejects_trusted_summary_when_market_is_blocked(self):
        report = generate_research_report(
            generated_at="2026-07-07T01:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        self.assertEqual("blocked", report["data_status"]["status"])
        report["data_trust"]["verdict"] = "trusted"

        self.assertIn(
            "blocked market data must have untrusted data_trust.verdict",
            validate_report_contract(report),
        )

    def test_validator_rejects_trusted_summary_when_market_is_validated(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        report["data_trust"]["verdict"] = "trusted"

        self.assertIn(
            "validated market data must remain untrusted until promotion policy exists",
            validate_report_contract(report),
        )

    def test_validator_rejects_false_missing_source_for_validated_market(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        report["data_trust"] = {
            "verdict": "untrusted",
            "reason_codes": ["ARBITRARY"],
            "source_class": "missing",
        }

        errors = validate_report_contract(report)

        self.assertIn(
            "validated market data must have fixture data_trust.source_class",
            errors,
        )
        self.assertIn(
            "validated market data trust must include DATA_TRUST_PROMOTION_PENDING",
            errors,
        )

    def test_validator_rejects_noncanonical_data_trust_reason_projections(self):
        cases = (
            (
                "missing_extra_reason",
                "2026-07-07T00:00:00Z",
                None,
                "missing",
                ["MISSING_VALIDATED_MARKET_DATA", "ARBITRARY"],
            ),
            (
                "validated_extra_reason",
                "2026-07-07T00:01:30Z",
                self._load_market_snapshot(),
                "validated",
                ["DATA_TRUST_PROMOTION_PENDING", "ARBITRARY"],
            ),
            (
                "blocked_replaced_reason",
                "2026-07-07T01:01:30Z",
                self._load_market_snapshot(),
                "blocked",
                ["ARBITRARY"],
            ),
        )

        for name, generated_at, market_snapshot, status, reason_codes in cases:
            with self.subTest(name=name):
                report = generate_research_report(
                    generated_at=generated_at,
                    market_snapshot=market_snapshot,
                )
                self.assertEqual(status, report["data_status"]["status"])
                report["data_trust"]["reason_codes"] = reason_codes

                self.assertTrue(
                    validate_report_contract(report),
                    f"{name} unexpectedly passed contract validation",
                )

    def test_validator_rejects_unexplained_degraded_summary(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        report["data_trust"]["verdict"] = "degraded"
        report["data_trust"]["reason_codes"] = []

        self.assertIn(
            "degraded data_trust.reason_codes must not be empty",
            validate_report_contract(report),
        )

    def test_fixed_snapshot_report_is_deterministic_across_independent_builds(self):
        first_report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        second_report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )

        self.assertEqual(first_report, second_report)

    def test_validator_rejects_unexplained_untrusted_summary(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_market_snapshot(),
        )
        report["data_trust"]["reason_codes"] = []

        self.assertIn(
            "untrusted data_trust.reason_codes must not be empty",
            validate_report_contract(report),
        )

    def test_cli_report_and_ingestion_status_share_data_trust(self):
        report = self._run_cli("report")
        ingestion_status = self._run_cli("ingestion-status")

        self.assertEqual(report["data_trust"], ingestion_status["data_trust"])
        self.assertEqual("untrusted", ingestion_status["data_trust"]["verdict"])

    def test_trust_summary_does_not_open_paper_manual_or_live_modes(self):
        for mode in ("paper", "manual_execution"):
            with self.subTest(mode=mode):
                report = generate_research_report(
                    mode=mode,
                    generated_at="2026-07-07T00:00:00Z",
                )
                self.assertEqual("untrusted", report["data_trust"]["verdict"])
                self.assertEqual("research_only", report["effective_mode"])
                self.assertEqual("NO_TRADE", report["action"])
                self.assertFalse(report["permission_state"]["paper_trading_allowed"])
                self.assertFalse(
                    report["permission_state"]["manual_execution_allowed"]
                )
                self.assertEqual(
                    "NO-GO",
                    report["full_system_surface"]["release_readiness"]["status"],
                )

        with self.assertRaisesRegex(ValueError, "unsupported mode 'live'"):
            generate_research_report(mode="live")

    @staticmethod
    def _load_market_snapshot():
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "deribit_btc_option_chain_snapshot.json"
        )
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    @staticmethod
    def _run_cli(command):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                command,
                "--generated-at",
                "2026-07-07T00:00:00Z",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
