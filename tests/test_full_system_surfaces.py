import json
import subprocess
import sys
import unittest

from crypto_options_report.api import _payload_for_path
from crypto_options_report.cli import build_parser
from crypto_options_report.contract import generate_research_report, report_shape
from crypto_options_report.full_surface import (
    API_ROUTES,
    CLI_COMMANDS,
    DASHBOARD_VIEWS,
    build_recommendation_projection,
    validate_full_system_surface_report,
)


class FullSystemSurfaceTests(unittest.TestCase):
    def test_cli_parser_supports_required_commands(self):
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        )

        for command in CLI_COMMANDS:
            self.assertIn(command, subparsers.choices)

    def test_api_and_dashboard_descriptors_include_required_surfaces(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        surface = report["full_system_surface"]

        self.assertEqual([], validate_full_system_surface_report(surface))
        self.assertEqual(set(API_ROUTES), {item["route"] for item in surface["api"]["routes"]})
        self.assertEqual(
            set(DASHBOARD_VIEWS),
            {item["name"] for item in surface["dashboard"]["views"]},
        )
        self.assertFalse(surface["cli"]["paper_manual_actions_visible"])
        self.assertFalse(surface["dashboard"]["paper_manual_actions_visible"])
        self.assertEqual("NO-GO", surface["release_readiness"]["status"])

    def test_api_routes_return_shared_report_slices(self):
        self.assertEqual("ok", _payload_for_path("/health", "").get("status", "ok"))
        self.assertIn("final_action", _payload_for_path("/portfolio/risk", ""))
        self.assertIn("ranked_candidates", _payload_for_path("/candidates", ""))
        self.assertIn("action", _payload_for_path("/recommendation", ""))
        self.assertIn("views", _payload_for_path("/dashboard", ""))
        self.assertIn("backtest_comparison", _payload_for_path("/backtest/report/default", ""))

    def test_cli_api_and_dashboard_use_same_projection_shape(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        api_projection = _payload_for_path("/recommendation", "generated_at=2026-07-07T00%3A01%3A30Z")
        dashboard_projection = {
            key: report["full_system_surface"]["shared_schema_projection"][key]
            for key in (
                "action",
                "risk_state",
                "reason_codes",
                "calibration_status",
                "mode_gate",
            )
        }
        direct_projection = build_recommendation_projection(report)

        self.assertEqual(report_shape(direct_projection), report_shape(api_projection))
        self.assertEqual(direct_projection["action"], dashboard_projection["action"])
        self.assertEqual(direct_projection["risk_state"], dashboard_projection["risk_state"])
        self.assertEqual(direct_projection["reason_codes"], dashboard_projection["reason_codes"])

    def test_cli_calibrate_and_recommend_commands_emit_json(self):
        for command, expected_key in (("calibrate", "split_policy"), ("recommend", "mode_gate")):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "crypto_options_report.cli",
                    command,
                    "--generated-at",
                    "2026-07-07T00:01:30Z",
                    "--compact",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertIn(expected_key, payload)


if __name__ == "__main__":
    unittest.main()
