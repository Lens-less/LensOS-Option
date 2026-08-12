import http.client
import json
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from crypto_options_report.alerts import (
    evaluate_alerts,
    validate_alert_evaluation,
)
from crypto_options_report.analysis_run import build_analysis_record
from crypto_options_report.api import (
    ANALYSIS_RESULT_PATH,
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    _analysis_cache_entry_current,
    _analysis_cache_identity,
    _payload_for_path,
    _report_options_from_query,
    build_api_analysis_record,
    build_api_report,
)
from crypto_options_report.market_data import load_snapshot_fixture

FIXED_CLOCK = "2026-07-07T00:01:30Z"
FIXTURE_PATH = (
    Path(__file__).with_name("fixtures")
    / "deribit_btc_option_chain_snapshot.json"
)


class _FakeRecord:
    def __init__(self, evaluation_clock: str) -> None:
        self.manifest = type("Manifest", (), {"evaluation_clock": evaluation_clock})()


class AnalysisProjectionSurfaceTests(unittest.TestCase):
    def test_cli_and_api_project_the_same_analysis_record(self):
        api_record = build_api_analysis_record(
            snapshot_fixture=str(FIXTURE_PATH),
            generated_at=FIXED_CLOCK,
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "analysis",
                "--snapshot-fixture",
                str(FIXTURE_PATH),
                "--generated-at",
                FIXED_CLOCK,
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cli_record = json.loads(completed.stdout)

        self.assertEqual(api_record.analysis_run_id, cli_record["analysis_run_id"])
        self.assertEqual(api_record.output_hash, cli_record["output_hash"])
        self.assertEqual(api_record.to_dict(), cli_record)

    def test_api_report_is_the_compatibility_projection_of_one_record(self):
        record = build_api_analysis_record(
            snapshot_fixture=str(FIXTURE_PATH),
            generated_at=FIXED_CLOCK,
        )
        report = build_api_report(
            snapshot_fixture=str(FIXTURE_PATH),
            generated_at=FIXED_CLOCK,
        )

        self.assertEqual(record.project_research_report_v1(), report)

    def test_analysis_result_route_returns_the_immutable_record(self):
        payload = _payload_for_path(
            ANALYSIS_RESULT_PATH,
            "",
            runtime=RuntimeConfig(
                profile="development",
                snapshot_fixture=str(FIXTURE_PATH),
                replay=True,
            ),
        )

        self.assertEqual("analysis_record.v1", payload["schema_version"])
        self.assertTrue(payload["analysis_run_id"].startswith("analysis:"))
        self.assertEqual(payload["output_hash"], payload["manifest"]["output_hash"])

    def test_http_server_reuses_one_record_for_get_projections(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        try:
            with patch(
                "crypto_options_report.api.build_api_analysis_record",
                wraps=build_api_analysis_record,
            ) as build:
                first = server.analysis_record("")
                second = server.analysis_record("")

            self.assertIs(first, second)
            self.assertEqual(1, build.call_count)
        finally:
            server.server_close()

    def test_implicit_clock_cache_expires_at_policy_trust_deadline(self):
        first_record = build_api_analysis_record(
            generated_at=FIXED_CLOCK,
        )
        second_clock = "2026-07-07T00:02:31Z"
        second_record = build_api_analysis_record(
            generated_at=second_clock,
        )
        base_clock = datetime.fromisoformat(
            FIXED_CLOCK.replace("Z", "+00:00")
        )
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        try:
            with (
                patch(
                    "crypto_options_report.api.build_api_analysis_record",
                    side_effect=(first_record, second_record),
                ) as build,
                patch(
                    "crypto_options_report.api._analysis_cache_now",
                    return_value=base_clock + timedelta(seconds=30),
                ) as clock,
            ):
                first = server.analysis_record("")
                within_window = server.analysis_record("")
                clock.return_value = base_clock + timedelta(seconds=61)
                after_expiry = server.analysis_record("")

            self.assertIs(first, within_window)
            self.assertIs(after_expiry, second_record)
            self.assertEqual(2, build.call_count)
        finally:
            server.server_close()

    def test_replay_clock_cache_stays_immutable_after_trust_deadline(self):
        runtime = RuntimeConfig(
            profile="development",
            snapshot_fixture=str(FIXTURE_PATH),
            replay=True,
        )
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        try:
            with (
                patch(
                    "crypto_options_report.api.build_api_analysis_record",
                    side_effect=(
                        _FakeRecord(FIXED_CLOCK),
                        _FakeRecord("2026-07-07T00:02:31Z"),
                    ),
                ) as build,
                patch(
                    "crypto_options_report.api._analysis_cache_now",
                    return_value=datetime.fromisoformat(
                        FIXED_CLOCK.replace("Z", "+00:00")
                    )
                    + timedelta(days=1),
                ),
            ):
                first = server.analysis_record("")
                second = server.analysis_record("")

            self.assertIs(first, second)
            self.assertEqual(1, build.call_count)
        finally:
            server.server_close()

    def test_published_clock_cache_is_not_implicitly_immutable(self):
        options = _report_options_from_query(
            "",
            runtime=RuntimeConfig(
                profile="development",
                snapshot_fixture=str(FIXTURE_PATH),
                published=True,
            ),
        )
        record = build_api_analysis_record(generated_at=FIXED_CLOCK)

        self.assertFalse(
            _analysis_cache_entry_current(
                record,
                options,
                now=datetime.fromisoformat(FIXED_CLOCK.replace("Z", "+00:00"))
                + timedelta(days=1),
            )
        )

    def test_analysis_cache_evicts_oldest_implicit_clock_entry_at_capacity(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        try:
            with patch(
                "crypto_options_report.api.build_api_analysis_record",
                side_effect=[
                    _FakeRecord(FIXED_CLOCK) for _ in range(65)
                ],
            ) as build:
                for instrument_limit in range(1, 65):
                    server.analysis_record(f"instrument_limit={instrument_limit}")

                first_key = json.dumps(
                    _analysis_cache_identity(
                        _report_options_from_query(
                            "instrument_limit=1",
                            runtime=RuntimeConfig(profile="development"),
                        )
                    ),
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                sixty_fifth_key = json.dumps(
                    _analysis_cache_identity(
                        _report_options_from_query(
                            "instrument_limit=65",
                            runtime=RuntimeConfig(profile="development"),
                        )
                    ),
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )

                self.assertIn(first_key, server._analysis_records)
                server.analysis_record("instrument_limit=65")

            self.assertNotIn(first_key, server._analysis_records)
            self.assertIn(sixty_fifth_key, server._analysis_records)
            self.assertEqual(64, len(server._analysis_records))
            self.assertEqual(65, build.call_count)
        finally:
            server.server_close()

    def test_repeated_http_gets_do_not_refetch_or_recompute_live_analysis(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(
                profile="development",
                allow_live_fetch=True,
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        query = "live_deribit=1&instrument_limit=8"

        def request(path):
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                server.server_port,
                timeout=5,
            )
            try:
                connection.request("GET", f"{path}?{query}")
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                return response.status, dict(response.getheaders()), payload
            finally:
                connection.close()

        try:
            with patch(
                "crypto_options_report.api.fetch_deribit_option_chain_snapshot",
                return_value=load_snapshot_fixture(FIXTURE_PATH),
            ) as fetch:
                first = request(ANALYSIS_RESULT_PATH)
                second = request("/research/report")
            self.assertEqual(1, fetch.call_count)
            self.assertEqual(200, first[0])
            self.assertEqual(200, second[0])
            self.assertEqual(
                first[1]["X-Analysis-Run-ID"],
                second[1]["X-Analysis-Run-ID"],
            )
            self.assertEqual(first[1]["ETag"], second[1]["ETag"])
            # `runtime_context` describes how the response was produced - live
            # or replayed - which is a property of the request, not of the
            # immutable record. It is compared separately so this assertion
            # keeps testing what it was written to test: that the projection is
            # the record's own, not a recomputation.
            served = dict(second[2])
            runtime_context = served.pop("runtime_context", None)
            self.assertEqual(
                server.analysis_record(query).project_research_report_v1(),
                served,
            )
            self.assertEqual(runtime_context["mode"], "live")
            self.assertIs(runtime_context["replay"], False)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_returns_503_when_cache_is_full_of_immutable_replay_entries(self):
        runtime = RuntimeConfig(
            profile="development",
            snapshot_fixture=str(FIXTURE_PATH),
            replay=True,
        )
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        for instrument_limit in range(1, 65):
            cache_key = json.dumps(
                _analysis_cache_identity(
                    _report_options_from_query(
                        f"instrument_limit={instrument_limit}",
                        runtime=runtime,
                    )
                ),
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            server._analysis_records[cache_key] = object()  # type: ignore[assignment]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=5,
        )
        try:
            connection.request("GET", "/research/report?instrument_limit=65")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(503, response.status)
        self.assertEqual("1", response.getheader("Retry-After"))
        self.assertNotEqual(400, response.status)
        self.assertIn("cache", payload["error"])

    def test_domain_alert_projection_does_not_recompute_legacy_rules(self):
        record = build_analysis_record(generated_at=FIXED_CLOCK)

        with patch(
            "crypto_options_report.alerts._collect_candidate_events",
            side_effect=AssertionError("legacy alert rules must not run"),
        ):
            evaluation = evaluate_alerts(record, cooldown_sec=0)

        self.assertEqual([], validate_alert_evaluation(evaluation))
        self.assertTrue(evaluation["events"])
        self.assertTrue(
            all(
                event["rule_id"].startswith("entry_admission.")
                for event in evaluation["events"]
            )
        )
        self.assertFalse(evaluation["trade_actions_allowed"])


if __name__ == "__main__":
    unittest.main()
