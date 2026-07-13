import json
import http.client
import re
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from crypto_options_report.api import (
    DASHBOARD_PAGE_PATH,
    GET_SURFACE_PATHS,
    POST_SURFACE_PATHS,
    REPORT_PATH,
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    _payload_for_path,
    build_parser as build_api_parser,
    dashboard_page_html,
    readiness_payload,
    serve,
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
        route_status = {
            item["route"]: item["status"] for item in surface["api"]["routes"]
        }
        self.assertEqual("not_implemented", route_status["POST /backtest/run"])

    def test_api_route_descriptors_match_runtime_routes(self):
        declared_routes = set(API_ROUTES)
        expected_get_routes = {
            "GET /health",
            "GET /livez",
            "GET /readyz",
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
        self.assertNotIn("api_base", html)
        self.assertIn("连接失败，显示离线预览", html)
        self.assertIn("paper mode 已阻断", html)
        self.assertIn("证据链", html)
        self.assertNotIn("order_template", html)
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_http_dashboard_page_route_returns_html(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="production"),
        )
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
        self.assertEqual("no-store, max-age=0", response.getheader("Cache-Control"))
        self.assertEqual("same-origin", response.getheader("Cross-Origin-Resource-Policy"))
        self.assertNotIn("Python", response.getheader("Server"))
        self.assertIn("connect-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertIn("Crypto Options 研究控制台", body)

    def test_liveness_and_readiness_are_distinct_fail_closed_contracts(self):
        live_status, _, live_body = self._request("GET", "/livez")
        ready_status, _, ready_body = self._request("GET", "/readyz")

        self.assertEqual(200, live_status)
        self.assertEqual({"status": "alive"}, json.loads(live_body))
        self.assertEqual(200, ready_status)
        readiness = json.loads(ready_body)
        self.assertTrue(readiness["service_ready"])
        self.assertTrue(readiness["research_only"])
        self.assertEqual("NO-GO", readiness["product_release"])
        self.assertFalse(readiness["live_order_adapter_available"])

    def test_production_profile_rejects_browser_controlled_replay_inputs(self):
        status, _, body = self._request(
            "GET",
            "/research/report?account_scenario=green&generated_at=2099-01-01T00:00:00Z",
            runtime=RuntimeConfig(profile="production"),
        )

        self.assertEqual(400, status)
        self.assertIn("production", json.loads(body)["error"])

    def test_unsupported_http_methods_return_json_405(self):
        status, headers, body = self._request("PUT", "/research/report")

        self.assertEqual(405, status)
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual({"error": "method_not_allowed"}, json.loads(body))

    def test_api_parser_exposes_validated_production_runtime_controls(self):
        args = build_api_parser().parse_args(
            [
                "--runtime-profile",
                "production",
                "--max-workers",
                "4",
                "--request-timeout",
                "7.5",
            ]
        )

        self.assertEqual("production", args.runtime_profile)
        self.assertEqual(4, args.max_workers)
        self.assertEqual(7.5, args.request_timeout)
        with self.assertRaisesRegex(ValueError, "max_workers"):
            RuntimeConfig(profile="production", max_workers=0).validate()

    def test_production_startup_preflights_before_binding(self):
        runtime = RuntimeConfig(profile="production")
        with (
            patch(
                "crypto_options_report.api.readiness_payload",
                return_value={"service_ready": False},
            ),
            patch("crypto_options_report.api.ResearchHTTPServer") as server_class,
            self.assertRaisesRegex(SystemExit, "preflight failed"),
        ):
            serve("127.0.0.1", 8000, runtime=runtime)
        server_class.assert_not_called()

    def test_readiness_maps_unexpected_validation_failure_to_unavailable(self):
        runtime = RuntimeConfig(profile="production")
        with patch(
            "crypto_options_report.api.dashboard_page_html",
            side_effect=RuntimeError("asset changed after startup"),
        ):
            payload = readiness_payload(runtime)
        self.assertFalse(payload["service_ready"])
        self.assertTrue(payload["research_only"])
        self.assertEqual("NO-GO", payload["product_release"])

    def test_expected_socket_abort_is_logged_as_client_disconnect(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(),
        )
        try:
            with patch("crypto_options_report.api._log_json") as log_json:
                try:
                    raise ConnectionResetError("client closed")
                except ConnectionResetError:
                    server.handle_error(None, ("127.0.0.1", 12345))
            log_json.assert_called_once_with(
                "client_disconnected",
                client="127.0.0.1",
                error="ConnectionResetError",
            )
        finally:
            server.server_close()

    def test_overload_returns_bounded_503_instead_of_spawning_more_work(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_payload(path, query, *, runtime):
            entered.set()
            release.wait(timeout=5)
            return {"schema_version": "research_report.v1"}

        runtime = RuntimeConfig(profile="development", max_workers=1)
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        first_result = {}

        def first_request():
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            try:
                connection.request("GET", "/research/report")
                response = connection.getresponse()
                first_result["status"] = response.status
                response.read()
            finally:
                connection.close()

        request_thread = threading.Thread(target=first_request, daemon=True)
        with patch("crypto_options_report.api._payload_for_path", side_effect=slow_payload):
            request_thread.start()
            self.assertTrue(entered.wait(timeout=2))
            try:
                overload_responses = []
                for _ in range(20):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=2
                    )
                    try:
                        connection.request("GET", "/health")
                        response = connection.getresponse()
                        payload = json.loads(response.read().decode("utf-8"))
                        overload_responses.append(
                            (
                                response.status,
                                payload,
                                response.getheader("Retry-After"),
                                response.getheader("X-Frame-Options"),
                                response.getheader("Cross-Origin-Resource-Policy"),
                            )
                        )
                    finally:
                        connection.close()
            finally:
                release.set()
                request_thread.join(timeout=5)
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(20, len(overload_responses))
        for (
            status,
            payload,
            retry_after,
            frame_policy,
            resource_policy,
        ) in overload_responses:
            self.assertEqual(503, status)
            self.assertEqual("overloaded", payload["error"])
            self.assertEqual("1", retry_after)
            self.assertEqual("DENY", frame_policy)
            self.assertEqual("same-origin", resource_policy)
        self.assertEqual(200, first_result["status"])

    def test_overload_log_correlates_client_request_and_status(self):
        first, second = socket.socketpair()
        try:
            with patch("crypto_options_report.api._log_json") as log_json:
                ResearchHTTPServer._reject_overloaded(
                    first,
                    ("127.0.0.1", 12345),
                )
            event, = log_json.call_args.args
            fields = log_json.call_args.kwargs
            self.assertEqual("overload_rejected", event)
            self.assertEqual("127.0.0.1", fields["client"])
            self.assertEqual(503, fields["status"])
            self.assertRegex(fields["request_id"], r"^[0-9a-f]{32}$")
        finally:
            first.close()
            second.close()

    def test_http_backtest_run_route_refuses_to_invent_performance(self):
        status, headers, body = self._request(
            "POST",
            "/backtest/run?generated_at=2026-07-07T00%3A01%3A30Z",
        )
        payload = json.loads(body)

        self.assertEqual(501, status)
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual("backtest_run_response.v1", payload["schema_version"])
        self.assertEqual("not_implemented", payload["status"])
        self.assertIsNone(payload["report_id"])
        self.assertTrue(payload["research_only"])
        self.assertEqual([], payload["backtest_comparison"])

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

    def _request(self, method, path, *, runtime=None):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime or RuntimeConfig(profile="development"),
        )
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
