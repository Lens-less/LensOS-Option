import http.client
import json
import threading
import unittest

from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
)


class BacktestApiTruthfulnessTests(unittest.TestCase):
    def test_post_backtest_run_requires_operator_historical_fixture_without_performance(self):
        status, headers, payload = self._request(
            "POST",
            "/backtest/run",
            body={
                "schema_version": "backtest_run_request.v1",
                "generated_at": "2026-07-07T00:01:30Z",
            },
            headers={"Idempotency-Key": "missing-history"},
        )

        self.assertEqual(409, status)
        self.assertEqual(
            {
                "schema_version": "backtest_run_response.v1",
                "status": "historical_data_not_configured",
                "reason_code": "MISSING_HISTORICAL_FIXTURE",
                "action": "CONFIGURE_HISTORICAL_FIXTURE",
                "report_id": None,
                "backtest_comparison": [],
                "research_only": True,
            },
            payload,
        )
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual("no-store, max-age=0", headers["cache-control"])
        self.assertEqual("nosniff", headers["x-content-type-options"])
        self.assertEqual("DENY", headers["x-frame-options"])
        self.assertEqual("same-origin", headers["cross-origin-resource-policy"])
        self.assertRegex(headers["x-request-id"], r"^[0-9a-f]{32}$")
        self.assertNotIn("Python", headers["server"])

    def test_get_default_backtest_report_is_not_run_without_performance(self):
        status, _, payload = self._request(
            "GET",
            "/backtest/report/default?generated_at=2026-07-07T00%3A01%3A30Z",
        )

        self.assertEqual(200, status)
        self.assertEqual(
            {
                "schema_version": "backtest_report_lookup.v1",
                "status": "not_run",
                "reason_code": "BACKTEST_NOT_RUN",
                "report_id": None,
                "backtest_comparison": [],
                "research_only": True,
            },
            payload,
        )

    def test_post_backtest_run_rejects_invalid_query_before_configuration_status(self):
        status, headers, payload = self._request(
            "POST",
            "/backtest/run?instrument_limit=not-an-int",
        )

        self.assertEqual(400, status)
        self.assertEqual(
            {"error": "backtest run accepts JSON body fields, not query parameters"},
            payload,
        )
        self.assertEqual("no-store, max-age=0", headers["cache-control"])
        self.assertNotIn("backtest_comparison", payload)

    def test_post_backtest_run_rejects_unknown_json_fields(self):
        status, _, payload = self._request(
            "POST",
            "/backtest/run",
            body={
                "schema_version": "backtest_run_request.v1",
                "fixture_path": "client-controlled.json",
            },
            headers={"Idempotency-Key": "unknown-field"},
        )

        self.assertEqual(422, status)
        self.assertIn("unknown backtest request fields", payload["error"])

    def test_post_backtest_run_requires_idempotency_key(self):
        status, _, payload = self._request(
            "POST",
            "/backtest/run",
            body={"schema_version": "backtest_run_request.v1"},
        )

        self.assertEqual(400, status)
        self.assertIn("Idempotency-Key", payload["error"])

    def test_post_backtest_run_rejects_non_rfc3339_timestamp(self):
        status, _, payload = self._request(
            "POST",
            "/backtest/run",
            body={
                "schema_version": "backtest_run_request.v1",
                "generated_at": "2026-07-14 00:00:00+00:00",
            },
            headers={"Idempotency-Key": "bad-timestamp"},
        )

        self.assertEqual(422, status)
        self.assertIn("RFC3339", payload["error"])

    def _request(self, method: str, path: str, *, body=None, headers=None):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=5,
        )
        try:
            encoded = None if body is None else json.dumps(body).encode("utf-8")
            request_headers = dict(headers or {})
            if encoded is not None:
                request_headers["Content-Type"] = "application/json"
            connection.request(method, path, body=encoded, headers=request_headers)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, headers, json.loads(body)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
