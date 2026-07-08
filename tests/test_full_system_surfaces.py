import json
import http.client
import subprocess
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

from crypto_options_report.api import (
    DASHBOARD_PAGE_PATH,
    GET_SURFACE_PATHS,
    POST_SURFACE_PATHS,
    REPORT_PATH,
    ResearchReportHandler,
    _payload_for_path,
    dashboard_page_html,
)
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

    def test_api_route_descriptors_match_runtime_routes(self):
        declared_routes = set(API_ROUTES)
        expected_get_routes = {
            "GET /health",
            f"GET {REPORT_PATH}",
            f"GET {DASHBOARD_PAGE_PATH}",
        }
        expected_get_routes.update(f"GET {path}" for path in GET_SURFACE_PATHS)
        expected_post_routes = {f"POST {path}" for path in POST_SURFACE_PATHS}

        self.assertEqual(expected_get_routes | expected_post_routes, declared_routes)

    def test_api_routes_return_shared_report_slices(self):
        self.assertEqual("ok", _payload_for_path("/health", "").get("status", "ok"))
        self.assertIn("final_action", _payload_for_path("/portfolio/risk", ""))
        self.assertIn("ranked_candidates", _payload_for_path("/candidates", ""))
        self.assertIn("action", _payload_for_path("/recommendation", ""))
        self.assertIn("views", _payload_for_path("/dashboard", ""))
        self.assertIn("backtest_comparison", _payload_for_path("/backtest/report/default", ""))

    def test_dashboard_page_shell_uses_shared_report_routes(self):
        html = dashboard_page_html()

        self.assertIn("Crypto Options 研究控制台", html)
        self.assertIn("/research/report", html)
        self.assertIn("/dashboard", html)
        self.assertIn("api_base", html)
        self.assertIn("连接失败，显示离线预览", html)
        self.assertIn("paper mode 已阻断", html)
        self.assertIn("证据链", html)
        self.assertNotIn("order_template", html)

    def test_http_dashboard_page_route_returns_html(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ResearchReportHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=2,
        )
        try:
            connection.request("GET", DASHBOARD_PAGE_PATH)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(200, response.status)
        self.assertEqual("text/html; charset=utf-8", response.getheader("Content-Type"))
        self.assertIn("Crypto Options 研究控制台", body)

    def test_http_backtest_run_route_returns_schema(self):
        status, headers, body = self._request(
            "POST",
            "/backtest/run?generated_at=2026-07-07T00%3A01%3A30Z",
        )
        payload = json.loads(body)

        self.assertEqual(200, status)
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual("backtest_run_response.v1", payload["schema_version"])
        self.assertEqual("completed", payload["status"])
        self.assertEqual("default", payload["report_id"])
        self.assertTrue(payload["research_only"])
        self.assertIn("backtest_comparison", payload)

    def test_http_backtest_run_rejects_invalid_query(self):
        status, headers, body = self._request(
            "POST",
            "/backtest/run?instrument_limit=not-an-int",
        )
        payload = json.loads(body)

        self.assertEqual(400, status)
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual({"error": "instrument_limit must be an integer"}, payload)

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

    def _request(self, method, path):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ResearchReportHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=2,
        )
        try:
            connection.request(method, path)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, headers, body
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
