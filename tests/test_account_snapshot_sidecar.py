import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from crypto_options_report import account_snapshot_sidecar
from crypto_options_report.account_risk import build_account_status


class AccountSnapshotSidecarTests(unittest.TestCase):
    def test_account_http_response_read_is_bounded_to_max_plus_one(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"x" * (
            account_snapshot_sidecar.MAX_ACCOUNT_HTTP_RESPONSE_BYTES + 1
        )
        with (
            mock.patch.object(
                account_snapshot_sidecar,
                "urlopen",
                return_value=response,
            ),
            self.assertRaisesRegex(ValueError, "response exceeds"),
        ):
            account_snapshot_sidecar._rpc_post(
                "https://www.deribit.com",
                "public/test",
                {},
                1,
            )
        response.read.assert_called_once_with(
            account_snapshot_sidecar.MAX_ACCOUNT_HTTP_RESPONSE_BYTES + 1
        )

    def test_rpc_response_requires_exact_jsonrpc_version_and_request_id(self):
        invalid_envelopes = {
            "missing-version": {"id": 1, "result": {}},
            "wrong-version": {"jsonrpc": "1.0", "id": 1, "result": {}},
            "missing-id": {"jsonrpc": "2.0", "result": {}},
            "mismatched-id": {"jsonrpc": "2.0", "id": 2, "result": {}},
            "boolean-id": {"jsonrpc": "2.0", "id": True, "result": {}},
        }
        for name, payload in invalid_envelopes.items():
            with self.subTest(name=name):
                response = io.BytesIO(json.dumps(payload).encode("utf-8"))
                with (
                    mock.patch.object(
                        account_snapshot_sidecar,
                        "urlopen",
                        return_value=response,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "JSON-RPC version|request id",
                    ),
                ):
                    account_snapshot_sidecar._rpc_post(
                        "https://www.deribit.com",
                        "private/get_account_summary",
                        {"currency": "BTC"},
                        1,
                        access_token="redacted-token",
                    )

    def test_empty_or_non_finite_live_account_rows_fail_closed(self):
        valid_account = {
            "currency": "BTC",
            "equity": 1.2,
            "balance": 1.1,
            "margin_balance": 1.2,
            "available_funds": 0.8,
            "initial_margin": 0.4,
            "maintenance_margin": 0.2,
            "portfolio_margining_enabled": True,
        }
        valid_position = {
            "instrument_name": "BTC-31JUL26-100000-C",
            "kind": "option",
            "direction": "sell",
            "size": 1.0,
            "mark_price": 0.08,
            "index_price": 100000.0,
            "floating_profit_loss": -0.01,
            "initial_margin": 0.1,
            "maintenance_margin": 0.05,
            "delta": -0.2,
        }
        valid_order = {
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
        cases = (
            ({}, [valid_position], [valid_order]),
            ({**valid_account, "equity": float("inf")}, [valid_position], [valid_order]),
            ({**valid_account, "equity": "1.2"}, [valid_position], [valid_order]),
            (
                {**valid_account, "portfolio_margining_enabled": "true"},
                [valid_position],
                [valid_order],
            ),
            (valid_account, [{}], [valid_order]),
            (valid_account, [{**valid_position, "mark_price": float("nan")}], [valid_order]),
            (valid_account, [valid_position], [{}]),
            (valid_account, [valid_position], [{**valid_order, "price": float("inf")}]),
            ({**valid_account, "equity": 0.0}, [valid_position], [valid_order]),
            ({**valid_account, "maintenance_margin": -0.1}, [valid_position], [valid_order]),
            (valid_account, [{**valid_position, "direction": "sideways"}], [valid_order]),
            (
                valid_account,
                [{key: value for key, value in valid_position.items() if key != "kind"}],
                [valid_order],
            ),
            (valid_account, [{**valid_position, "kind": "unknown"}], [valid_order]),
            (valid_account, [{**valid_position, "size": -1.0}], [valid_order]),
            (valid_account, [{**valid_position, "size": 0.0}], [valid_order]),
            (valid_account, [{**valid_position, "delta": 1.1}], [valid_order]),
            (valid_account, [valid_position], [{**valid_order, "amount": 0.0}]),
            (valid_account, [valid_position], [{**valid_order, "filled_amount": 2.0}]),
            (valid_account, [valid_position], [{**valid_order, "creation_timestamp": -1}]),
        )
        auth = {"access_token": "read-only", "scope": "account:read trade:read"}
        for account, positions, orders in cases:
            with self.subTest(account=account, positions=positions, orders=orders):
                with mock.patch.object(
                    account_snapshot_sidecar,
                    "_rpc_post",
                    side_effect=[auth, account, positions, orders],
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "required|finite|positive|non-negative|direction|filled|delta|size|kind",
                    ):
                        account_snapshot_sidecar.fetch_deribit_account_snapshot(
                            client_id="id",
                            client_secret="secret",
                            currency="BTC",
                        )

    def test_incomplete_available_snapshot_is_refused_before_write_or_signature(self):
        incomplete = {
            "schema_version": "deribit_account_snapshot.v1",
            "captured_at": "2026-07-14T00:00:00Z",
            "account": {
                "status": "available",
                "currency": "BTC",
                "margin_model": "portfolio_margin",
                "equity": float("inf"),
            },
            "positions": [],
            "open_orders": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "account.json"
            with self.assertRaisesRegex(ValueError, "configured|finite|required"):
                account_snapshot_sidecar._persist_snapshot(output, incomplete)
            self.assertFalse(output.exists())
            self.assertFalse(
                account_snapshot_sidecar.sidecar_auth_state_path(output).exists()
            )

    def test_invalid_position_domain_is_refused_before_write_or_signature(self):
        account = {
            "status": "available",
            "configuration_status": "configured",
            "source": "deribit_live_private_read_only",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-14T00:00:00Z",
            "currency": "BTC",
            "margin_model": "portfolio_margin",
            "equity": 1.2,
            "balance": 1.1,
            "margin_balance": 1.2,
            "available_funds": 0.8,
            "initial_margin": 0.4,
            "maintenance_margin": 0.2,
        }
        position = {
            "instrument_name": "BTC-31JUL26-100000-C",
            "kind": "option",
            "direction": "sell",
            "size": 1.0,
            "mark_price": 0.08,
            "index_price": 100000.0,
            "floating_pnl": -0.01,
            "initial_margin": 0.1,
            "maintenance_margin": 0.05,
            "delta": -0.2,
            "gamma": None,
            "theta": None,
            "vega": None,
            "source_endpoint": "private/get_positions",
        }
        invalid_positions = {
            "missing-kind": {
                key: value for key, value in position.items() if key != "kind"
            },
            "unknown-kind": {**position, "kind": "unknown"},
            "negative-size": {**position, "size": -1.0},
            "zero-size": {**position, "size": 0.0},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            for name, invalid_position in invalid_positions.items():
                with self.subTest(name=name):
                    output = Path(temp_dir) / f"{name}.json"
                    payload = {
                        "schema_version": "deribit_account_snapshot.v1",
                        "captured_at": "2026-07-14T00:00:00Z",
                        "account": account,
                        "positions": [invalid_position],
                        "open_orders": [],
                    }
                    with self.assertRaisesRegex(ValueError, "kind|required|positive"):
                        account_snapshot_sidecar._persist_snapshot(output, payload)
                    self.assertFalse(output.exists())
                    self.assertFalse(
                        account_snapshot_sidecar.sidecar_auth_state_path(output).exists()
                    )

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
                mock.patch.object(account_snapshot_sidecar, "_rpc_post") as request,
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

        def rpc(base_url, method, params, timeout, *, access_token=None):
            calls.append((method, dict(params)))
            if method == "public/auth":
                self.assertEqual(secret, params["client_secret"])
                self.assertIsNone(access_token)
                return {
                    "access_token": "access-token-never-persist",
                    "scope": "account:read trade:read",
                    "expires_in": 900,
                }
            self.assertNotIn("access_token", params)
            self.assertEqual("access-token-never-persist", access_token)
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
                        "kind": "option",
                        "direction": "sell",
                        "size": 1.0,
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
            mock.patch.object(account_snapshot_sidecar, "_rpc_post", side_effect=rpc),
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
            "_rpc_post",
            return_value={
                "access_token": "must-not-be-used",
                "scope": "account:read_write trade:read_write",
            },
        ) as rpc, self.assertRaisesRegex(ValueError, "exact read-only scopes"):
            account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="configured-id",
                client_secret="configured-secret",
            )
        self.assertEqual(1, rpc.call_count)
        self.assertEqual("public/auth", rpc.call_args.args[1])

    def test_extra_scope_is_rejected_by_exact_read_only_boundary(self):
        with mock.patch.object(
            account_snapshot_sidecar,
            "_rpc_post",
            return_value={
                "access_token": "must-not-be-used",
                "scope": "account:read trade:read wallet:read",
            },
        ) as rpc, self.assertRaisesRegex(ValueError, "exact read-only scopes"):
            account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="configured-id",
                client_secret="configured-secret",
            )
        self.assertEqual(1, rpc.call_count)
        self.assertEqual("public/auth", rpc.call_args.args[1])

    def test_non_object_private_rows_fail_closed_instead_of_being_dropped(self):
        with mock.patch.object(
            account_snapshot_sidecar,
            "_rpc_post",
            side_effect=[
                {
                    "access_token": "read-only-token",
                    "scope": "account:read trade:read",
                },
                {
                    "equity": 1.0,
                    "initial_margin": 0.1,
                    "maintenance_margin": 0.05,
                },
                [123],
                [],
            ],
        ), self.assertRaisesRegex(ValueError, "non-object"):
            account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="configured-id",
                client_secret="configured-secret",
            )

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
