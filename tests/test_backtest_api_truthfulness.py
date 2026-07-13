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
    def test_post_backtest_run_reports_unimplemented_without_performance(self):
        status, headers, payload = self._request(
            "POST",
            "/backtest/run?generated_at=2026-07-07T00%3A01%3A30Z",
        )

        self.assertEqual(501, status)
        self.assertEqual(
            {
                "schema_version": "backtest_run_response.v1",
                "status": "not_implemented",
                "reason_code": "BOUNDED_BACKTEST_JOB_NOT_IMPLEMENTED",
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

    def test_post_backtest_run_rejects_invalid_query_before_unimplemented_status(self):
        status, headers, payload = self._request(
            "POST",
            "/backtest/run?instrument_limit=not-an-int",
        )

        self.assertEqual(400, status)
        self.assertEqual(
            {"error": "instrument_limit must be an integer"},
            payload,
        )
        self.assertEqual("no-store, max-age=0", headers["cache-control"])
        self.assertNotIn("backtest_comparison", payload)

    def _request(self, method: str, path: str):
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
            timeout=2,
        )
        try:
            connection.request(method, path)
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
