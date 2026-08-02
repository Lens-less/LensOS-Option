from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crypto_options_report.dvol_history_tool import main


def _history_payload() -> dict:
    return {
        "schema_version": "dvol_history.v1",
        "captured_at": "2026-08-02T08:00:00Z",
        "source": "deribit_live:https://www.deribit.com",
        "source_endpoint": "public/get_volatility_index_data",
        "index_name": "BTC DVOL",
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "requested_days": 5,
        "observation_count": 3,
        "first_observed_at": "2024-01-30T00:00:00Z",
        "last_observed_at": "2024-02-02T00:00:00Z",
        "value_unit": "percent_points",
        "coverage": {
            "expected_day_count": 4,
            "observed_day_count": 3,
            "missing_day_count": 1,
            "coverage_ratio": 0.75,
            "missing_days": ["2024-01-31"],
        },
        "observations": [
            {
                "timestamp_ms": 1_706_745_600_000,
                "observed_at": "2024-01-30T00:00:00Z",
                "close": 55.0,
            },
            {
                "timestamp_ms": 1_706_832_000_000,
                "observed_at": "2024-02-01T00:00:00Z",
                "close": 57.0,
            },
            {
                "timestamp_ms": 1_706_918_400_000,
                "observed_at": "2024-02-02T00:00:00Z",
                "close": 59.0,
            },
        ],
    }


class DvolHistoryToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_main_writes_json_and_prints_gap_summary(self):
        output_path = Path(self._tmp.name) / "btc-dvol.json"
        stdout = io.StringIO()

        with (
            mock.patch(
                "crypto_options_report.dvol_history_tool.fetch_deribit_dvol_history",
                return_value=_history_payload(),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["--output", str(output_path)])

        self.assertEqual(0, exit_code)
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual("BTC DVOL", saved["index_name"])
        summary = json.loads(stdout.getvalue())
        self.assertEqual(1, summary["missing_day_count"])
        self.assertEqual(["2024-01-31"], summary["missing_days"])

    def test_main_reports_fetch_failures_to_stderr(self):
        stderr = io.StringIO()

        with (
            mock.patch(
                "crypto_options_report.dvol_history_tool.fetch_deribit_dvol_history",
                side_effect=ValueError("bad payload"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = main(["--output", str(Path(self._tmp.name) / "btc-dvol.json")])

        self.assertEqual(1, exit_code)
        self.assertEqual({"error": "bad payload"}, json.loads(stderr.getvalue()))


if __name__ == "__main__":
    unittest.main()
