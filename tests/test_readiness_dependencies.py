import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    readiness_payload,
)
from crypto_options_report.evidence_store import BacktestJobService
from crypto_options_report.market_data import utc_timestamp
from crypto_options_report.sidecar_auth import write_sidecar_auth_state


def _market_status(*, promoted: bool) -> dict:
    return {
        "status": "validated",
        "trust_evidence": {
            "status": "promoted" if promoted else "collecting",
        },
    }


def _account_payload() -> dict:
    observed_at = utc_timestamp()
    return {
        "schema_version": "deribit_account_snapshot.v1",
        "captured_at": observed_at,
        "source_endpoints": [
            "private/get_account_summary",
            "private/get_positions",
            "private/get_open_orders_by_currency",
        ],
        "account": {
            "status": "available",
            "source": "deribit_live_private_read_only",
            "source_endpoint": "private/get_account_summary",
            "observed_at": observed_at,
            "currency": "BTC",
            "equity": 100.0,
            "balance": 100.0,
            "margin_balance": 100.0,
            "available_funds": 90.0,
            "initial_margin": 10.0,
            "maintenance_margin": 5.0,
        },
        "positions": [],
        "open_orders": [],
        "simulation": {
            "status": "not_requested",
            "attempted": False,
            "reason_code": "SIMULATION_NOT_REQUESTED",
        },
        "replay_metadata": {
            "source": "live_deribit_private_read_only",
            "captured_shape_only": False,
        },
    }


class ReadinessDependencyTests(unittest.TestCase):
    def test_public_account_risk_requires_authenticated_sidecar_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            account_path = data_dir / "account.json"
            account = _account_payload()
            account["simulation"] = {
                "status": "available",
                "attempted": True,
                "source_endpoint": "private/simulate_portfolio",
                "projected": {
                    "initial_margin": 10.0,
                    "maintenance_margin": 5.0,
                    "nav_usd": 100.0,
                },
            }
            account_path.write_text(json.dumps(account), encoding="utf-8")
            key_file = key_dir / "operator.key"
            key_file.write_bytes(b"k" * 32)
            runtime = RuntimeConfig(account_snapshot_fixture=str(account_path))
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=runtime,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                unsigned = self._get_account_risk(server.server_port)

                self.assertEqual("auth_failed", unsigned["status"])
                self.assertFalse(unsigned["live_snapshot"])
                self.assertEqual("NO_TRADE", unsigned["trade_gate"])
                self.assertEqual([], unsigned["positions"])
                self.assertFalse(
                    unsigned["private_adapter_contract"]["auth_safe"]
                )

                write_sidecar_auth_state(
                    account_path,
                    expected_payload=account,
                    key_file=key_file,
                )
                with patch.dict(
                    os.environ,
                    {
                        "CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": str(
                            key_file
                        )
                    },
                    clear=False,
                ):
                    authenticated = self._get_account_risk(server.server_port)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual("available", authenticated["status"])
        self.assertTrue(authenticated["live_snapshot"])
        self.assertEqual("ALLOW_NEW", authenticated["trade_gate"])

    @staticmethod
    def _get_account_risk(port: int) -> dict:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "GET",
                "/account/risk",
                headers={"Host": f"127.0.0.1:{port}"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        if response.status != 200:
            raise AssertionError(f"GET /account/risk returned {response.status}: {payload}")
        return payload

    def test_store_readiness_rejects_malformed_historical_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "history.json"
            historical.write_text("not-json", encoding="utf-8")
            service = BacktestJobService(
                fixture_path=historical,
                artifact_dir=root / "artifacts",
            )
            try:
                payload = readiness_payload(
                    RuntimeConfig(
                        profile="production",
                        historical_fixture=str(historical),
                        backtest_artifact_dir=str(root / "artifacts"),
                    ),
                    job_service=service,
                )
            finally:
                service.close()

        self.assertFalse(payload["store_ready"])
        self.assertIn("BACKTEST_STORE_NOT_READY", payload["reason_codes"])

    def test_queue_readiness_is_false_when_no_admission_slot_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "history.json"
            historical.write_text('{"rows": []}', encoding="utf-8")
            service = BacktestJobService(
                fixture_path=historical,
                artifact_dir=root / "artifacts",
                max_workers=1,
                queue_capacity=0,
            )
            self.assertTrue(service._slots.acquire(blocking=False))
            try:
                payload = readiness_payload(
                    RuntimeConfig(
                        profile="production",
                        historical_fixture=str(historical),
                        backtest_artifact_dir=str(root / "artifacts"),
                    ),
                    job_service=service,
                )
            finally:
                service._slots.release()
                service.close()

        self.assertFalse(payload["queue_ready"])
        self.assertIn("BACKTEST_QUEUE_NOT_READY", payload["reason_codes"])

    def test_unpromoted_snapshot_does_not_satisfy_last_trusted_snapshot(self):
        runtime = RuntimeConfig(profile="production", snapshot_fixture="market.json")
        with (
            patch("crypto_options_report.api.load_snapshot_fixture", return_value={}),
            patch(
                "crypto_options_report.api.build_market_data_status",
                return_value=_market_status(promoted=False),
            ),
        ):
            payload = readiness_payload(runtime)

        self.assertTrue(payload["market_provider_ready"])
        self.assertFalse(payload["last_trusted_snapshot_ready"])
        self.assertFalse(payload["market_data_ready"])
        self.assertIn("TRUSTED_MARKET_SNAPSHOT_NOT_READY", payload["reason_codes"])

    def test_account_readiness_requires_keyed_sidecar_not_handwritten_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            account_path = data_dir / "account.json"
            account = _account_payload()
            account_path.write_text(json.dumps(account), encoding="utf-8")
            key_file = key_dir / "operator.key"
            key_file.write_bytes(b"k" * 32)
            runtime = RuntimeConfig(
                profile="production",
                account_snapshot_fixture=str(account_path),
            )

            unsigned = readiness_payload(runtime)
            self.assertFalse(unsigned["account_data_ready"])

            write_sidecar_auth_state(
                account_path,
                expected_payload=account,
                key_file=key_file,
            )
            with patch.dict(
                os.environ,
                {"CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": str(key_file)},
                clear=False,
            ):
                authenticated = readiness_payload(runtime)

        self.assertTrue(authenticated["account_data_ready"])

    def test_account_readiness_rejects_signed_but_malformed_position_shape(self):
        valid_position = {
            "instrument_name": "BTC-31JUL26-100000-C",
            "kind": "option",
            "direction": "sell",
            "size": 1.0,
            "mark_price": 0.08,
            "index_price": 100_000.0,
            "floating_pnl": -0.01,
            "initial_margin": 0.1,
            "maintenance_margin": 0.05,
            "delta": -0.2,
        }
        invalid_positions = (
            {},
            {key: value for key, value in valid_position.items() if key != "kind"},
            {**valid_position, "kind": "unknown"},
            {**valid_position, "size": -1.0},
        )
        for position in invalid_positions:
            with self.subTest(position=position), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data_dir = root / "data"
                key_dir = root / "keys"
                data_dir.mkdir()
                key_dir.mkdir()
                account_path = data_dir / "account.json"
                account = _account_payload()
                account["positions"] = [position]
                account_path.write_text(json.dumps(account), encoding="utf-8")
                key_file = key_dir / "account.key"
                key_file.write_bytes(b"a" * 32)
                write_sidecar_auth_state(
                    account_path,
                    expected_payload=account,
                    key_file=key_file,
                )
                runtime = RuntimeConfig(
                    profile="production",
                    account_snapshot_fixture=str(account_path),
                )

                with patch.dict(
                    os.environ,
                    {
                        "CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": str(
                            key_file
                        )
                    },
                    clear=False,
                ):
                    payload = readiness_payload(runtime)

                self.assertFalse(payload["account_data_ready"])
                self.assertIn("ACCOUNT_DATA_NOT_READY", payload["reason_codes"])

    def test_readiness_exposes_store_queue_model_and_can_aggregate_healthy_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "history.json"
            historical.write_text('{"rows": []}', encoding="utf-8")
            artifacts = root / "artifacts"
            artifacts.mkdir()
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            account_path = data_dir / "account.json"
            account = _account_payload()
            account_path.write_text(json.dumps(account), encoding="utf-8")
            key_file = key_dir / "operator.key"
            key_file.write_bytes(b"k" * 32)
            write_sidecar_auth_state(
                account_path,
                expected_payload=account,
                key_file=key_file,
            )
            runtime = RuntimeConfig(
                profile="production",
                snapshot_fixture="market.json",
                account_snapshot_fixture=str(account_path),
                historical_fixture=str(historical),
                backtest_artifact_dir=str(artifacts),
            )

            class HealthyQueue:
                _closed = False
                jobs_dir = artifacts / "jobs"

            HealthyQueue.jobs_dir.mkdir()
            with (
                patch.dict(
                    os.environ,
                    {"CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": str(key_file)},
                    clear=False,
                ),
                patch("crypto_options_report.api.load_snapshot_fixture", return_value={}),
                patch(
                    "crypto_options_report.api.build_market_data_status",
                    return_value=_market_status(promoted=True),
                ),
                patch("crypto_options_report.api._model_dependency_ready", return_value=True),
            ):
                payload = readiness_payload(runtime, job_service=HealthyQueue())

        for field in (
            "market_provider_ready",
            "last_trusted_snapshot_ready",
            "account_data_ready",
            "store_ready",
            "queue_ready",
            "model_ready",
            "dependencies_ready",
            "ready",
        ):
            self.assertTrue(payload[field], field)
        self.assertEqual([], payload["reason_codes"])


if __name__ == "__main__":
    unittest.main()
