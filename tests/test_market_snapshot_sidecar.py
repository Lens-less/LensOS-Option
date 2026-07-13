from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from crypto_options_report import snapshot_sidecar as refresh_market_snapshot


class MarketSnapshotSidecarTests(unittest.TestCase):
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
