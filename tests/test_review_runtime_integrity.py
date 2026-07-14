from __future__ import annotations

import http.client
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from crypto_options_report.account_risk import build_account_status
from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    readiness_payload,
)
from crypto_options_report.market_data import parse_timestamp_ms, utc_timestamp
from crypto_options_report.storage import atomic_write_text


class TimestampIntegrityTests(unittest.TestCase):
    def test_market_timestamps_require_an_explicit_timezone(self):
        self.assertEqual(
            parse_timestamp_ms("2026-07-14T08:00:00+08:00"),
            parse_timestamp_ms("2026-07-14T00:00:00Z"),
        )
        with self.assertRaisesRegex(ValueError, "timezone"):
            parse_timestamp_ms("2026-07-14T00:00:00")


class AccountIntegrityTests(unittest.TestCase):
    def test_non_usd_account_equity_is_not_mislabeled_as_nav_usd(self):
        status = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload={
                "account": {
                    "status": "available",
                    "currency": "BTC",
                    "observed_at": "2026-07-14T00:00:00Z",
                    "equity": 1.2,
                    "initial_margin": 0.4,
                    "maintenance_margin": 0.2,
                },
                "positions": [],
                "simulation": {
                    "status": "available",
                    "attempted": True,
                    "projected_initial_margin": 0.4,
                    "projected_maintenance_margin": 0.2,
                    "projected_nav_usd": 100_000,
                },
            },
        )

        snapshot = status["snapshot"]
        self.assertEqual("BTC", snapshot["nav_currency"])
        self.assertEqual(1.2, snapshot["nav_value"])
        self.assertIsNone(snapshot["nav_usd"])
        self.assertAlmostEqual(1 / 3, snapshot["im_nav"])
        self.assertAlmostEqual(6.0, snapshot["nav_to_mm"])

    def test_missing_account_simulation_status_always_blocks_new_trades(self):
        status = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload=None,
        )

        self.assertTrue(status["simulation_status"]["blocks_new_trades"])
        self.assertEqual("NO_TRADE", status["trade_gate"])

    def test_declared_malformed_account_never_parses_untrusted_numbers(self):
        status = build_account_status(
            generated_at="2026-07-14T00:00:00Z",
            account_payload={
                "account": {
                    "status": "malformed",
                    "equity": "not-a-number",
                    "observed_at": "also-not-a-time",
                },
                "positions": [{"size": None, "pnl": "invalid"}],
            },
        )

        self.assertEqual("malformed", status["status"])
        self.assertEqual("HALT", status["margin_light"])
        self.assertEqual("NO_TRADE", status["trade_gate"])
        self.assertIsNone(status["snapshot"])

    def test_available_account_with_non_finite_values_fails_closed(self):
        status = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload={
                "account": {
                    "status": "available",
                    "observed_at": "2026-07-14T00:00:00Z",
                    "equity": "NaN",
                    "initial_margin": 1,
                    "maintenance_margin": 1,
                },
                "positions": [],
                "simulation": {"status": "available"},
            },
        )

        self.assertEqual("malformed", status["status"])
        self.assertEqual("NO_TRADE", status["trade_gate"])

    def test_unknown_or_missing_account_status_fails_closed(self):
        for raw_status in (None, "bogus", "AUTH_FAILED", " malformed "):
            with self.subTest(raw_status=raw_status):
                account = {
                    "observed_at": "2026-07-14T00:00:00Z",
                    "equity": 100,
                    "initial_margin": 10,
                    "maintenance_margin": 5,
                }
                if raw_status is not None:
                    account["status"] = raw_status
                status = build_account_status(
                    generated_at="2026-07-14T00:00:01Z",
                    account_payload={
                        "account": account,
                        "positions": [],
                        "simulation": {"status": "available", "attempted": True},
                    },
                )

                self.assertEqual("malformed", status["status"])
                self.assertEqual("NO_TRADE", status["trade_gate"])

    def test_simulation_must_have_strict_true_attempted_evidence(self):
        for attempted in (False, "false", 1, None):
            with self.subTest(attempted=attempted):
                simulation = {"status": "available"}
                if attempted is not None:
                    simulation["attempted"] = attempted
                status = build_account_status(
                    generated_at="2026-07-14T00:00:01Z",
                    account_payload={
                        "account": {
                            "status": "available",
                            "observed_at": "2026-07-14T00:00:00Z",
                            "equity": 100,
                            "initial_margin": 10,
                            "maintenance_margin": 5,
                        },
                        "positions": [],
                        "simulation": simulation,
                    },
                )

                self.assertFalse(status["live_snapshot"])
                self.assertEqual("NO_TRADE", status["trade_gate"])
                self.assertEqual(
                    "SIMULATION_ATTEMPT_REQUIRED",
                    status["reason_code"],
                )

    def test_non_object_position_and_future_account_timestamp_fail_closed(self):
        malformed = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload={
                "account": {
                    "status": "available",
                    "observed_at": "2026-07-14T00:00:00Z",
                },
                "positions": [123],
                "simulation": {"status": "available", "attempted": True},
            },
        )
        future = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload={
                "account": {
                    "status": "available",
                    "observed_at": "2099-01-01T00:00:00Z",
                    "equity": 100,
                    "initial_margin": 10,
                    "maintenance_margin": 5,
                },
                "positions": [],
                "simulation": {"status": "available", "attempted": True},
            },
        )

        self.assertEqual("malformed", malformed["status"])
        self.assertEqual("NO_TRADE", malformed["trade_gate"])
        self.assertEqual("stale", future["status"])
        self.assertEqual("ACCOUNT_OBSERVED_AT_IN_FUTURE", future["reason_code"])
        self.assertEqual("NO_TRADE", future["trade_gate"])

    def test_available_account_requires_both_margin_inputs(self):
        for missing_field in ("initial_margin", "maintenance_margin"):
            with self.subTest(missing_field=missing_field):
                account = {
                    "status": "available",
                    "observed_at": "2026-07-14T00:00:00Z",
                    "equity": 100,
                    "initial_margin": 10,
                    "maintenance_margin": 5,
                }
                del account[missing_field]

                status = build_account_status(
                    generated_at="2026-07-14T00:00:01Z",
                    account_payload={
                        "account": account,
                        "positions": [],
                        "simulation": {"status": "available", "attempted": True},
                    },
                )

                self.assertEqual("malformed", status["status"])
                self.assertEqual("NO_TRADE", status["trade_gate"])

    def test_available_account_rejects_unsafe_margin_and_nav_values(self):
        invalid_values = (
            ("initial_margin", -1),
            ("maintenance_margin", -1),
            ("equity", 0),
            ("equity", -1),
            ("nav_usd", 0),
            ("nav_usd", -1),
            ("im_nav", -0.1),
            ("nav_to_mm", 0),
            ("nav_to_mm", -1),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                account = {
                    "status": "available",
                    "observed_at": "2026-07-14T00:00:00Z",
                    "equity": 100,
                    "initial_margin": 10,
                    "maintenance_margin": 5,
                    field: value,
                }
                status = build_account_status(
                    generated_at="2026-07-14T00:00:01Z",
                    account_payload={
                        "account": account,
                        "positions": [],
                        "simulation": {"status": "available", "attempted": True},
                    },
                )

                self.assertEqual("malformed", status["status"])
                self.assertEqual("NO_TRADE", status["trade_gate"])

    def test_available_simulation_requires_complete_safe_projection(self):
        base_projection = {
            "status": "available",
            "attempted": True,
            "projected_initial_margin": 12,
            "projected_maintenance_margin": 6,
            "projected_nav_usd": 100,
            "projected_im_nav": 0.12,
            "projected_nav_to_mm": 100 / 6,
        }
        invalid_projections = (
            {},
            {**base_projection, "projected_initial_margin": -1},
            {**base_projection, "projected_maintenance_margin": -1},
            {**base_projection, "projected_nav_usd": 0},
            {**base_projection, "projected_im_nav": -0.1},
            {**base_projection, "projected_nav_to_mm": 0},
            {**base_projection, "projected_nav_to_mm": "NaN"},
        )
        for simulation in invalid_projections:
            with self.subTest(simulation=simulation):
                if not simulation:
                    simulation = {"status": "available", "attempted": True}
                status = build_account_status(
                    generated_at="2026-07-14T00:00:01Z",
                    account_payload={
                        "account": {
                            "status": "available",
                            "observed_at": "2026-07-14T00:00:00Z",
                            "equity": 100,
                            "initial_margin": 10,
                            "maintenance_margin": 5,
                        },
                        "positions": [],
                        "simulation": simulation,
                    },
                )

                self.assertEqual("available", status["status"])
                self.assertEqual("unavailable", status["simulation_status"]["status"])
                self.assertEqual(
                    "SIMULATION_EVIDENCE_INCOMPLETE",
                    status["reason_code"],
                )
                self.assertEqual("NO_TRADE", status["trade_gate"])


class JobApiIntegrityTests(unittest.TestCase):
    def test_job_store_os_error_returns_structured_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(
                    historical_fixture=str(fixture),
                    backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            try:
                with patch.object(
                    server.backtest_jobs,
                    "get",
                    side_effect=PermissionError("store temporarily locked"),
                ):
                    connection.request("GET", "/backtest/jobs/job-" + "a" * 64)
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(503, response.status)
            self.assertEqual("backtest_job_store_unavailable", payload["error"])
            self.assertEqual("1", response.getheader("Retry-After"))

    def test_api_rejects_untrusted_host_header_before_routing(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            rejected_connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            rejected_connection.request(
                "GET",
                "/research/report",
                headers={"Host": "attacker.example"},
            )
            rejected = rejected_connection.getresponse()
            rejected_payload = json.loads(rejected.read().decode("utf-8"))
            rejected_connection.close()

            allowed_connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            allowed_connection.request("GET", "/livez")
            allowed = allowed_connection.getresponse()
            allowed.read()
            allowed_connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(421, rejected.status)
        self.assertEqual("untrusted_host", rejected_payload["error"])
        self.assertEqual(200, allowed.status)

    def test_api_allows_explicit_reverse_proxy_host_only_when_configured(self):
        with patch.dict(
            os.environ,
            {"CRYPTO_OPTIONS_API_ALLOWED_HOSTS": "research.internal"},
            clear=False,
        ):
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            try:
                connection.request(
                    "GET",
                    "/livez",
                    headers={"Host": "research.internal"},
                )
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(200, response.status)

    def test_corrupt_job_and_idempotency_records_return_structured_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(
                    historical_fixture=str(fixture),
                    backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            job_id = "job-" + "a" * 64
            (server.backtest_jobs.jobs_dir / f"{job_id}.json").write_text(
                "{", encoding="utf-8"
            )
            key = "corrupt-mapping"
            key_hash = hashlib.sha256(key.encode("ascii")).hexdigest()
            (
                server.backtest_jobs.jobs_dir
                / f"idempotency-{key_hash}.json"
            ).write_text("{", encoding="utf-8")

            try:
                get_connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=2
                )
                get_connection.request("GET", f"/backtest/jobs/{job_id}")
                get_response = get_connection.getresponse()
                get_payload = json.loads(get_response.read().decode("utf-8"))
                get_connection.close()

                post_connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=2
                )
                post_connection.request(
                    "POST",
                    "/backtest/run",
                    body=b'{"schema_version":"backtest_run_request.v1"}',
                    headers={
                        "Content-Type": "application/json",
                        "Idempotency-Key": key,
                    },
                )
                post_response = post_connection.getresponse()
                post_payload = json.loads(post_response.read().decode("utf-8"))
                post_connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            for response, payload in (
                (get_response, get_payload),
                (post_response, post_payload),
            ):
                self.assertEqual(503, response.status)
                self.assertEqual("backtest_job_store_unavailable", payload["error"])
                self.assertEqual("1", response.getheader("Retry-After"))

    def test_naive_account_timestamp_is_not_assumed_to_be_utc(self):
        status = build_account_status(
            generated_at="2026-07-14T00:00:01Z",
            account_payload={
                "account": {
                    "status": "available",
                    "observed_at": "2026-07-14T00:00:00",
                    "equity": 100,
                    "initial_margin": 10,
                    "maintenance_margin": 5,
                },
                "positions": [],
                "simulation": {"status": "available"},
            },
        )

        self.assertEqual("stale", status["status"])
        self.assertEqual("MISSING_ACCOUNT_OBSERVED_AT", status["reason_code"])
        self.assertEqual("NO_TRADE", status["trade_gate"])


class StorageIntegrityTests(unittest.TestCase):
    def test_atomic_replace_retries_transient_windows_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            real_replace = os.replace
            attempts = 0

            def locked_once(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("sharing violation")
                return real_replace(source, destination)

            with (
                patch("crypto_options_report.storage.os.replace", side_effect=locked_once),
                patch("crypto_options_report.storage.time.sleep") as sleep,
            ):
                atomic_write_text(target, "durable")

            self.assertEqual("durable", target.read_text(encoding="utf-8"))
            self.assertEqual(2, attempts)
            sleep.assert_called_once()


class ReadinessIntegrityTests(unittest.TestCase):
    def test_production_readiness_distinguishes_service_from_dependencies(self):
        payload = readiness_payload(RuntimeConfig(profile="production"))

        self.assertTrue(payload["service_ready"])
        self.assertFalse(payload["dependencies_ready"])
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["market_data_ready"])
        self.assertFalse(payload["account_data_ready"])
        self.assertIn("MARKET_DATA_NOT_READY", payload["reason_codes"])
        self.assertIn("ACCOUNT_DATA_NOT_READY", payload["reason_codes"])

    def test_production_ready_endpoint_returns_503_when_dependencies_are_absent(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="production"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=2
        )
        try:
            connection.request("GET", "/readyz")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(503, response.status)
        self.assertTrue(payload["service_ready"])
        self.assertFalse(payload["ready"])

    def test_readiness_reads_configured_market_snapshot_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_text(
                json.dumps({"captured_at": utc_timestamp(), "rows": []}),
                encoding="utf-8",
            )
            from crypto_options_report import api as api_module

            real_loader = api_module.load_snapshot_fixture
            with patch.object(
                api_module,
                "load_snapshot_fixture",
                wraps=real_loader,
            ) as loader:
                readiness_payload(
                    RuntimeConfig(
                        profile="production",
                        snapshot_fixture=str(snapshot),
                    )
                )

            self.assertEqual(1, loader.call_count)


if __name__ == "__main__":
    unittest.main()
