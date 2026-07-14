from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from crypto_options_report import snapshot_sidecar as refresh_market_snapshot
from crypto_options_report import market_data
from crypto_options_report.market_data import (
    MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
    MAX_MARKET_HTTP_RESPONSE_BYTES,
    MAX_MARKET_SNAPSHOT_BYTES,
    MAX_MARKET_TRUST_STATE_BYTES,
    bound_snapshot_trust_evidence,
    load_snapshot_fixture,
    snapshot_trust_state_path,
    write_snapshot_fixture,
    write_snapshot_trust_state,
)
from crypto_options_report.sidecar_auth import (
    ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN,
    SidecarAuthUnavailable,
    sign_mapping,
)


class MarketSnapshotSidecarTests(unittest.TestCase):
    def test_account_domain_signature_cannot_forge_market_trust_state(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:00Z",
            "currency": "BTC",
            "source": "deribit_live:https://www.deribit.com",
            "rows": [],
        }
        evidence = {
            "schema_version": "market_trust_evidence.v1",
            "status": "collecting",
            "source_identity": "deribit_live:https://www.deribit.com|BTC",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            output = data_dir / "snapshot.json"
            key_file = key_dir / "shared.key"
            key_file.write_bytes(b"s" * 32)
            write_snapshot_fixture(output, snapshot)
            state_path = write_snapshot_trust_state(
                output,
                evidence,
                expected_snapshot=snapshot,
                auth_key_file=key_file,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            unsigned = {
                key: value for key, value in state.items() if key != "hmac_sha256"
            }
            state["hmac_sha256"] = sign_mapping(
                unsigned,
                key_file=key_file,
                domain=ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN,
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")

            forged = load_snapshot_fixture(output, auth_key_file=key_file)

        self.assertEqual({}, bound_snapshot_trust_evidence(forged))

    def test_market_key_environment_rejects_account_key_path_alias(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:00Z",
            "currency": "BTC",
            "source": "deribit_live:https://www.deribit.com",
            "rows": [],
        }
        evidence = {
            "schema_version": "market_trust_evidence.v1",
            "status": "collecting",
            "source_identity": "deribit_live:https://www.deribit.com|BTC",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            output = data_dir / "snapshot.json"
            key_file = key_dir / "shared.key"
            key_file.write_bytes(b"s" * 32)
            write_snapshot_fixture(output, snapshot)
            relative_alias = os.path.relpath(key_file, Path.cwd())

            with mock.patch.dict(
                os.environ,
                {
                    MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV: str(key_file),
                    "CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": relative_alias,
                },
                clear=True,
            ):
                with self.assertRaisesRegex(
                    SidecarAuthUnavailable,
                    "distinct key files",
                ):
                    write_snapshot_trust_state(
                        output,
                        evidence,
                        expected_snapshot=snapshot,
                    )

    def test_market_runtime_uses_only_its_domain_specific_hmac_key(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:00Z",
            "currency": "BTC",
            "source": "deribit_live:https://www.deribit.com",
            "rows": [],
        }
        evidence = {
            "schema_version": "market_trust_evidence.v1",
            "status": "collecting",
            "source_identity": "deribit_live:https://www.deribit.com|BTC",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            output = data_dir / "snapshot.json"
            key_file = key_dir / "market.key"
            key_file.write_bytes(b"m" * 32)
            write_snapshot_fixture(output, snapshot)

            with mock.patch.dict(
                os.environ,
                {"CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE": str(key_file)},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    SidecarAuthUnavailable,
                    MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
                ):
                    write_snapshot_trust_state(
                        output,
                        evidence,
                        expected_snapshot=snapshot,
                    )

            with mock.patch.dict(
                os.environ,
                {MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV: str(key_file)},
                clear=True,
            ):
                write_snapshot_trust_state(
                    output,
                    evidence,
                    expected_snapshot=snapshot,
                )
                loaded = load_snapshot_fixture(output)
            self.assertEqual(evidence, bound_snapshot_trust_evidence(loaded))

    def test_snapshot_and_trust_state_reads_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = root / "snapshot.json"
            snapshot.write_bytes(b"{" + b" " * MAX_MARKET_SNAPSHOT_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_snapshot_fixture(snapshot)

            valid = {
                "captured_at": "2026-07-12T15:00:00Z",
                "currency": "BTC",
                "source": "fixture:test",
                "rows": [],
            }
            write_snapshot_fixture(snapshot, valid)
            snapshot_trust_state_path(snapshot).write_bytes(
                b"{" + b" " * MAX_MARKET_TRUST_STATE_BYTES + b"}"
            )
            loaded = load_snapshot_fixture(snapshot)
            self.assertEqual({}, bound_snapshot_trust_evidence(loaded))

    def test_market_http_response_read_is_bounded_to_max_plus_one(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"x" * (MAX_MARKET_HTTP_RESPONSE_BYTES + 1)
        with (
            mock.patch.object(market_data, "urlopen", return_value=response),
            self.assertRaisesRegex(ValueError, "response exceeds"),
        ):
            market_data._get_json("https://www.deribit.com/api/v2/test", {}, 1)
        response.read.assert_called_once_with(MAX_MARKET_HTTP_RESPONSE_BYTES + 1)

    def test_trust_state_is_separate_and_bound_to_exact_snapshot_content(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:00Z",
            "currency": "BTC",
            "source": "deribit_live:https://www.deribit.com",
            "rows": [],
            "trust_evidence": {"status": "promoted", "consecutive_passes": 999},
        }
        evidence = {
            "schema_version": "market_trust_evidence.v1",
            "status": "promoted",
            "source_identity": "deribit_live:https://www.deribit.com|BTC",
            "consecutive_passes": 999,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            key_dir = Path(temp_dir) / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            output = data_dir / "current-snapshot.json"
            auth_key = key_dir / "sidecar.key"
            auth_key.write_bytes(b"k" * 32)
            write_snapshot_fixture(output, snapshot)

            unbound = load_snapshot_fixture(output)
            self.assertEqual({}, bound_snapshot_trust_evidence(unbound))
            self.assertNotIn("trust_evidence", json.loads(output.read_text()))

            write_snapshot_trust_state(
                output,
                evidence,
                expected_snapshot=snapshot,
                auth_key_file=auth_key,
            )
            bound = load_snapshot_fixture(output, auth_key_file=auth_key)
            self.assertEqual(evidence, bound_snapshot_trust_evidence(bound))

            bound["rows"].append({"instrument_name": "mutated-after-load"})
            self.assertEqual({}, bound_snapshot_trust_evidence(bound))

            forged_state = json.loads(
                snapshot_trust_state_path(output).read_text(encoding="utf-8")
            )
            forged_state["hmac_sha256"] = "0" * 64
            snapshot_trust_state_path(output).write_text(
                json.dumps(forged_state), encoding="utf-8"
            )
            forged = load_snapshot_fixture(output, auth_key_file=auth_key)
            self.assertEqual({}, bound_snapshot_trust_evidence(forged))
            write_snapshot_trust_state(
                output,
                evidence,
                expected_snapshot=snapshot,
                auth_key_file=auth_key,
            )

            raw = json.loads(output.read_text(encoding="utf-8"))
            raw["captured_at"] = "2026-07-12T15:00:01Z"
            output.write_text(json.dumps(raw), encoding="utf-8")
            tampered = load_snapshot_fixture(output, auth_key_file=auth_key)
            self.assertEqual({}, bound_snapshot_trust_evidence(tampered))
            with self.assertRaisesRegex(ValueError, "changed before trust state"):
                write_snapshot_trust_state(
                    output,
                    evidence,
                    expected_snapshot=snapshot,
                    auth_key_file=auth_key,
                )

    def test_once_writes_public_snapshot_atomically_with_safe_structured_log(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:00Z",
            "collection_started_at": "2026-07-12T14:59:48Z",
            "collection_duration_ms": 12000,
            "currency": "BTC",
            "source": "deribit_live:https://www.deribit.com",
            "rows": [{"instrument_name": "BTC-31JUL26-100000-C"}],
            "fetch_errors": [],
            "adapter_events": [],
        }
        collector_calls = []

        def collect(**kwargs):
            collector_calls.append(kwargs)
            return snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "current-snapshot.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    refresh_market_snapshot,
                    "fetch_deribit_option_chain_snapshot",
                    side_effect=collect,
                ),
                redirect_stderr(stderr),
            ):
                exit_code = refresh_market_snapshot.main(
                    ["--once", "--output", str(output)]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(snapshot, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(
                [
                    {
                        "currency": "BTC",
                        "base_url": "https://www.deribit.com",
                        "instrument_limit": 20,
                    }
                ],
                collector_calls,
            )
            self.assertEqual([], list(output.parent.glob(f".{output.name}.*.tmp")))

            logs = [json.loads(line) for line in stderr.getvalue().splitlines()]
            self.assertEqual(1, len(logs))
            self.assertEqual("market_snapshot_written", logs[0]["event"])
            self.assertTrue(logs[0]["research_only"])
            self.assertEqual(str(output.resolve()), logs[0]["output"])
            self.assertEqual(1, logs[0]["row_count"])
            self.assertEqual(0, logs[0]["fetch_error_count"])
            self.assertEqual(
                "2026-07-12T14:59:48Z",
                logs[0]["collection_started_at"],
            )
            self.assertEqual(12000, logs[0]["collection_duration_ms"])
            log_text = stderr.getvalue().lower()
            for forbidden in ("private", "account", "order"):
                self.assertNotIn(forbidden, log_text)

    def test_loop_continues_after_failure_and_ctrl_c_exits_cleanly(self):
        snapshot = {
            "captured_at": "2026-07-12T15:00:30Z",
            "currency": "ETH",
            "source": "deribit_live:https://test.deribit.com",
            "rows": [],
            "fetch_errors": ["book_summary: upstream unavailable"],
            "adapter_events": [{"class": "transient_network"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "current-snapshot.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    refresh_market_snapshot,
                    "fetch_deribit_option_chain_snapshot",
                    side_effect=[
                        RuntimeError("public feed unavailable"),
                        snapshot,
                        KeyboardInterrupt(),
                    ],
                ) as collector,
                mock.patch("time.sleep", return_value=None) as sleep,
                redirect_stderr(stderr),
            ):
                exit_code = refresh_market_snapshot.main(
                    [
                        "--output",
                        str(output),
                        "--interval",
                        "0.25",
                        "--currency",
                        "eth",
                        "--base-url",
                        "https://test.deribit.com/",
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(snapshot, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(3, collector.call_count)
            self.assertEqual([mock.call(0.25), mock.call(0.25)], sleep.call_args_list)
            logs = [json.loads(line) for line in stderr.getvalue().splitlines()]
            self.assertEqual(
                [
                    "market_snapshot_refresh_failed",
                    "market_snapshot_written",
                    "market_snapshot_sidecar_stopped",
                ],
                [item["event"] for item in logs],
            )
            self.assertEqual("RuntimeError", logs[0]["error_type"])
            self.assertTrue(logs[0]["retrying"])
            self.assertEqual("keyboard_interrupt", logs[2]["reason"])
            self.assertTrue(all(item["research_only"] for item in logs))

    def test_once_failure_preserves_snapshot_and_redacts_exception_text(self):
        previous = {
            "captured_at": "2026-07-12T14:59:00Z",
            "currency": "BTC",
            "source": "operator_previous_snapshot",
            "rows": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "current-snapshot.json"
            output.write_text(json.dumps(previous), encoding="utf-8")
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    refresh_market_snapshot,
                    "fetch_deribit_option_chain_snapshot",
                    side_effect=RuntimeError("private account order payload"),
                ),
                redirect_stderr(stderr),
            ):
                exit_code = refresh_market_snapshot.main(
                    ["--once", "--output", str(output)]
                )

            self.assertEqual(1, exit_code)
            self.assertEqual(previous, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual([], list(output.parent.glob(f".{output.name}.*.tmp")))
            log = json.loads(stderr.getvalue())
            self.assertEqual("market_snapshot_refresh_failed", log["event"])
            self.assertEqual("SNAPSHOT_REFRESH_FAILED", log["reason_code"])
            self.assertEqual("RuntimeError", log["error_type"])
            self.assertFalse(log["retrying"])
            for forbidden in ("private", "account", "order", "payload"):
                self.assertNotIn(forbidden, stderr.getvalue().lower())

    def test_default_interval_is_ten_seconds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "current-snapshot.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    refresh_market_snapshot,
                    "fetch_deribit_option_chain_snapshot",
                    side_effect=[RuntimeError("unavailable"), KeyboardInterrupt()],
                ),
                mock.patch("time.sleep", return_value=None) as sleep,
                redirect_stderr(stderr),
            ):
                exit_code = refresh_market_snapshot.main(["--output", str(output)])

            self.assertEqual(0, exit_code)
            self.assertEqual([mock.call(10.0)], sleep.call_args_list)

    def test_invalid_arguments_fail_before_collection(self):
        cases = (
            (["--interval", "0"], "interval must be finite and greater than zero"),
            (["--interval", "nan"], "interval must be finite and greater than zero"),
            (["--interval", "inf"], "interval must be finite and greater than zero"),
            (["--instrument-limit", "0"], "instrument_limit must be between 1 and 20"),
            (["--instrument-limit", "21"], "instrument_limit must be between 1 and 20"),
            (["--currency", "BTC/USD"], "currency must contain only letters and digits"),
            (["--currency", "比特币"], "currency must contain only letters and digits"),
            (
                ["--base-url", "https://example.com"],
                "deribit_base_url is not in the allowlist",
            ),
            (
                ["--base-url", "http://www.deribit.com"],
                "deribit_base_url must be an https URL from the allowlist",
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "current-snapshot.json"
            for arguments, expected_error in cases:
                with self.subTest(arguments=arguments):
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            refresh_market_snapshot,
                            "fetch_deribit_option_chain_snapshot",
                        ) as collector,
                        redirect_stderr(stderr),
                        self.assertRaises(SystemExit) as raised,
                    ):
                        refresh_market_snapshot.main(
                            ["--once", "--output", str(output), *arguments]
                        )

                    self.assertEqual(2, raised.exception.code)
                    self.assertIn(expected_error, stderr.getvalue())
                    collector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
