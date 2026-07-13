from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from crypto_options_report import account_snapshot_sidecar
from crypto_options_report.account_risk import build_account_status


class AccountSnapshotSidecarTests(unittest.TestCase):
    def test_currency_environment_default_is_honored(self):
        with mock.patch.dict(
            os.environ,
            {"DERIBIT_ACCOUNT_CURRENCY": "ETH"},
            clear=False,
        ):
            args = account_snapshot_sidecar.build_parser().parse_args(
                ["--output", "account.json"]
            )
        self.assertEqual("ETH", args.currency)

    def test_source_checkout_tool_imports_package_outside_repo_cwd(self):
        tool = Path(__file__).parents[1] / "tools" / "refresh_account_snapshot.py"
        completed = subprocess.run(
            [sys.executable, str(tool), "--help"],
            cwd=Path.home(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("read-only account snapshot", completed.stdout)

    def test_missing_credentials_writes_not_configured_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "account.json"
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(account_snapshot_sidecar, "_rpc_get") as request,
                redirect_stderr(stderr),
            ):
                exit_code = account_snapshot_sidecar.main(
                    ["--once", "--output", str(output)]
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertEqual("missing", payload["account"]["status"])
            self.assertEqual("not_configured", payload["account"]["configuration_status"])
            self.assertEqual("MISSING_ACCOUNT_API_SNAPSHOT", payload["account"]["reason_code"])
            self.assertEqual(
                "MISSING_DERIBIT_READ_ONLY_CREDENTIALS",
                payload["account"]["detail_reason_code"],
            )
            self.assertEqual([], payload["positions"])
            self.assertEqual([], payload["open_orders"])
            self.assertEqual(
                "missing",
                build_account_status(
                    generated_at=payload["captured_at"],
                    account_payload=payload,
                )["status"],
            )
            request.assert_not_called()
            self.assertNotIn("DERIBIT_CLIENT_SECRET", stderr.getvalue())

    def test_read_only_collection_uses_scoped_methods_and_never_serializes_credentials(self):
        secret = "super-secret-never-persist"
        calls = []

        def rpc(base_url, method, params, timeout):
            calls.append((method, dict(params)))
            if method == "public/auth":
                self.assertEqual(secret, params["client_secret"])
                return {
                    "access_token": "access-token-never-persist",
                    "scope": "account:read trade:read",
                    "expires_in": 900,
                }
            self.assertEqual("access-token-never-persist", params["access_token"])
            if method == "private/get_account_summary":
                return {
                    "currency": "BTC",
                    "equity": 1.2,
                    "balance": 1.1,
                    "margin_balance": 1.2,
                    "available_funds": 0.8,
                    "initial_margin": 0.4,
                    "maintenance_margin": 0.2,
                    "portfolio_margining_enabled": True,
                }
            if method == "private/get_positions":
                return [
                    {
                        "instrument_name": "BTC-31JUL26-100000-C",
                        "direction": "sell",
                        "size": -1.0,
                        "mark_price": 0.08,
                        "index_price": 100000.0,
                        "floating_profit_loss": -0.01,
                        "initial_margin": 0.1,
                        "maintenance_margin": 0.05,
                        "delta": -0.2,
                    }
                ]
            if method == "private/get_open_orders_by_currency":
                return [
                    {
                        "order_id": "sensitive-order-id",
                        "instrument_name": "BTC-31JUL26-100000-C",
                        "direction": "sell",
                        "amount": 1.0,
                        "filled_amount": 0.0,
                        "price": 0.081,
                        "order_state": "open",
                        "order_type": "limit",
                        "creation_timestamp": 1783900800000,
                        "last_update_timestamp": 1783900800000,
                    }
                ]
            raise AssertionError(method)

        with (
            mock.patch.object(account_snapshot_sidecar, "_rpc_get", side_effect=rpc),
            mock.patch.object(account_snapshot_sidecar, "utc_timestamp", return_value="2026-07-13T00:00:00Z"),
        ):
            snapshot = account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="client-id-never-persist",
                client_secret=secret,
                currency="BTC",
            )

        encoded = json.dumps(snapshot, sort_keys=True)
        for forbidden in (
            secret,
            "client-id-never-persist",
            "access-token-never-persist",
            "sensitive-order-id",
            "client_secret",
            "access_token",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual("available", snapshot["account"]["status"])
        self.assertEqual("portfolio_margin", snapshot["account"]["margin_model"])
        self.assertEqual(1, len(snapshot["positions"]))
        self.assertEqual(1, len(snapshot["open_orders"]))
        self.assertEqual(
            "available",
            build_account_status(
                generated_at=snapshot["captured_at"],
                account_payload=snapshot,
            )["status"],
        )
        account_status = build_account_status(
            generated_at=snapshot["captured_at"],
            account_payload=snapshot,
        )
        self.assertFalse(account_status["live_snapshot"])
        self.assertEqual("HALT", account_status["margin_light"])
        self.assertEqual("NO_TRADE", account_status["trade_gate"])
        self.assertEqual(
            "SIMULATION_NOT_REQUESTED",
            account_status["simulation_status"]["reason_code"],
        )
        self.assertEqual(
            [
                "public/auth",
                "private/get_account_summary",
                "private/get_positions",
                "private/get_open_orders_by_currency",
            ],
            [method for method, _ in calls],
        )

    def test_auth_failure_snapshot_and_log_redact_exception_text(self):
        secret = "never-print-this-secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "account.json"
            stderr = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "DERIBIT_CLIENT_ID": "client-id",
                        "DERIBIT_CLIENT_SECRET": secret,
                    },
                    clear=True,
                ),
                mock.patch.object(
                    account_snapshot_sidecar,
                    "fetch_deribit_account_snapshot",
                    side_effect=RuntimeError(f"bad auth {secret}"),
                ),
                redirect_stderr(stderr),
            ):
                exit_code = account_snapshot_sidecar.main(
                    ["--once", "--output", str(output)]
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, exit_code)
            self.assertEqual("auth_failed", payload["account"]["status"])
            self.assertEqual("AUTH_FAILED_ACCOUNT_API", payload["account"]["reason_code"])
            self.assertNotIn(secret, stderr.getvalue())
            self.assertNotIn(secret, json.dumps(payload))
            self.assertNotIn("bad auth", stderr.getvalue())

    def test_write_capable_grant_is_rejected_before_private_account_calls(self):
        with mock.patch.object(
            account_snapshot_sidecar,
            "_rpc_get",
            return_value={
                "access_token": "must-not-be-used",
                "scope": "account:read_write trade:read_write",
            },
        ) as rpc:
            with self.assertRaisesRegex(ValueError, "exact read-only scopes"):
                account_snapshot_sidecar.fetch_deribit_account_snapshot(
                    client_id="configured-id",
                    client_secret="configured-secret",
                )
        self.assertEqual(1, rpc.call_count)
        self.assertEqual("public/auth", rpc.call_args.args[1])

    def test_extra_scope_is_rejected_by_exact_read_only_boundary(self):
        with mock.patch.object(
            account_snapshot_sidecar,
            "_rpc_get",
            return_value={
                "access_token": "must-not-be-used",
                "scope": "account:read trade:read wallet:read",
            },
        ) as rpc:
            with self.assertRaisesRegex(ValueError, "exact read-only scopes"):
                account_snapshot_sidecar.fetch_deribit_account_snapshot(
                    client_id="configured-id",
                    client_secret="configured-secret",
                )
        self.assertEqual(1, rpc.call_count)
        self.assertEqual("public/auth", rpc.call_args.args[1])

    def test_account_age_is_recomputed_from_observed_at_and_fails_closed(self):
        snapshot = {
            "schema_version": "deribit_account_snapshot.v1",
            "account": {
                "status": "available",
                "source": "deribit_live_private_read_only",
                "source_endpoint": "private/get_account_summary",
                "observed_at": "2026-07-13T00:00:00Z",
                "data_age_ms": 0,
                "currency": "BTC",
                "margin_model": "portfolio_margin",
                "equity": 1.0,
                "balance": 1.0,
                "margin_balance": 1.0,
                "available_funds": 0.8,
                "initial_margin": 0.1,
                "maintenance_margin": 0.05,
            },
            "positions": [],
            "simulation": {
                "status": "available",
                "attempted": True,
                "source_endpoint": "private/simulate_portfolio",
                "projected": {
                    "initial_margin": 0.1,
                    "maintenance_margin": 0.05,
                    "nav_usd": 1.0,
                },
            },
        }

        status = build_account_status(
            generated_at="2026-07-13T01:00:00Z",
            account_payload=snapshot,
        )

        self.assertEqual("stale", status["status"])
        self.assertFalse(status["live_snapshot"])
        self.assertEqual("NO_TRADE", status["trade_gate"])
        self.assertEqual(3_600_000, status["data_age_ms"])

    def test_account_freshness_fails_closed_after_thirty_seconds(self):
        snapshot = {
            "account": {
                "status": "available",
                "source": "deribit_live_private_read_only",
                "source_endpoint": "private/get_account_summary",
                "observed_at": "2026-07-13T00:00:00Z",
                "currency": "BTC",
                "margin_model": "portfolio_margin",
                "equity": 1.0,
                "balance": 1.0,
                "margin_balance": 1.0,
                "available_funds": 0.8,
                "initial_margin": 0.1,
                "maintenance_margin": 0.05,
            },
            "positions": [],
            "simulation": {
                "status": "available",
                "attempted": True,
                "source_endpoint": "private/simulate_portfolio",
                "projected": {
                    "initial_margin": 0.1,
                    "maintenance_margin": 0.05,
                    "nav_usd": 1.0,
                },
            },
        }

        boundary = build_account_status(
            generated_at="2026-07-13T00:00:30Z",
            account_payload=snapshot,
        )
        stale = build_account_status(
            generated_at="2026-07-13T00:00:30.001Z",
            account_payload=snapshot,
        )

        self.assertEqual("available", boundary["status"])
        self.assertEqual("ALLOW_NEW", boundary["trade_gate"])
        self.assertEqual("stale", stale["status"])
        self.assertEqual("NO_TRADE", stale["trade_gate"])
        self.assertEqual(30_001, stale["data_age_ms"])

    def test_available_account_without_observed_at_fails_closed(self):
        snapshot = {
            "account": {
                "status": "available",
                "source": "deribit_live_private_read_only",
                "source_endpoint": "private/get_account_summary",
                "currency": "BTC",
                "margin_model": "portfolio_margin",
                "equity": 1.0,
                "available_funds": 0.8,
                "initial_margin": 0.1,
                "maintenance_margin": 0.05,
            },
            "positions": [],
            "simulation": {
                "status": "available",
                "attempted": True,
                "source_endpoint": "private/simulate_portfolio",
            },
        }

        status = build_account_status(
            generated_at="2026-07-13T01:00:00Z",
            account_payload=snapshot,
        )

        self.assertEqual("stale", status["status"])
        self.assertFalse(status["live_snapshot"])
        self.assertEqual("NO_TRADE", status["trade_gate"])
        self.assertEqual("MISSING_ACCOUNT_OBSERVED_AT", status["reason_code"])

    def test_base_url_allowlist_rejects_non_deribit_hosts(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="id",
                client_secret="secret",
                base_url="https://evil.example",
            )


if __name__ == "__main__":
    unittest.main()
