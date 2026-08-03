"""Underlying price history as an operator-owned replay fixture.

Production forbids live fetches, so expected value reaches the report through a
mounted file. A malformed file must be rejected outright: a silently truncated
or reordered series would shrink the sample without shrinking the confidence
reported alongside it.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crypto_options_report.api import RuntimeConfig, _analysis_cache_identity
from crypto_options_report.market_data import (
    UNDERLYING_HISTORY_SCHEMA_VERSION,
    fetch_deribit_underlying_history,
    load_underlying_history_fixture,
)
from crypto_options_report.underlying_history_tool import build_parser


def payload(**overrides) -> dict:
    observations = [
        {
            "timestamp_ms": 1_700_000_000_000 + index * 86_400_000,
            "observed_at": datetime.fromtimestamp(
                (1_700_000_000_000 + index * 86_400_000) / 1000,
                tz=UTC,
            )
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "close": 100_000.0 + index,
        }
        for index in range(4)
    ]
    base = {
        "schema_version": UNDERLYING_HISTORY_SCHEMA_VERSION,
        "captured_at": "2026-07-26T00:00:00Z",
        "source": "deribit_live:https://www.deribit.com",
        "instrument_name": "BTC-PERPETUAL",
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "requested_days": 4,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }
    base.update(overrides)
    return base


class LoaderTests(unittest.TestCase):
    def _write(self, data) -> Path:
        path = Path(self._tmp.name) / "history.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_valid_fixture_loads(self):
        loaded = load_underlying_history_fixture(self._write(payload()))

        self.assertEqual(4, loaded["observation_count"])
        self.assertEqual(86400, loaded["resolution_seconds"])

    def test_wrong_schema_version_is_rejected(self):
        with self.assertRaises(ValueError):
            load_underlying_history_fixture(
                self._write(payload(schema_version="something_else.v1"))
            )

    def test_too_few_observations_are_rejected(self):
        data = payload()
        data["observations"] = data["observations"][:1]

        with self.assertRaises(ValueError):
            load_underlying_history_fixture(self._write(data))

    def test_non_increasing_timestamps_are_rejected(self):
        """Out-of-order rows would corrupt every horizon window silently."""
        data = payload()
        data["observations"][2]["timestamp_ms"] = data["observations"][1][
            "timestamp_ms"
        ]

        with self.assertRaises(ValueError):
            load_underlying_history_fixture(self._write(data))

    def test_duplicate_utc_day_is_rejected(self):
        """Two daily candles for one UTC date must not overwrite each other."""
        data = payload()
        duplicate_ms = data["observations"][1]["timestamp_ms"] + 9 * 60 * 60 * 1000
        data["observations"].insert(
            2,
            {
                "timestamp_ms": duplicate_ms,
                "observed_at": datetime.fromtimestamp(duplicate_ms / 1000, tz=UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "close": 101_234.0,
            },
        )

        with self.assertRaisesRegex(ValueError, "one observation per UTC day"):
            load_underlying_history_fixture(self._write(data))

    def test_observed_at_must_match_timestamp(self):
        data = payload()
        data["observations"][1]["observed_at"] = "2026-08-03T09:00:00Z"

        with self.assertRaisesRegex(ValueError, "observed_at must match"):
            load_underlying_history_fixture(self._write(data))

    def test_declared_candle_open_must_match_resolution(self):
        data = payload()
        data["observations"][1]["candle_open_at"] = "2026-08-03T09:00:00Z"

        with self.assertRaisesRegex(ValueError, "candle_open_at must match"):
            load_underlying_history_fixture(self._write(data))

    def test_non_positive_close_is_rejected(self):
        data = payload()
        data["observations"][1]["close"] = 0.0

        with self.assertRaises(ValueError):
            load_underlying_history_fixture(self._write(data))

    def test_missing_timestamp_is_rejected(self):
        data = payload()
        del data["observations"][1]["timestamp_ms"]

        with self.assertRaises(ValueError):
            load_underlying_history_fixture(self._write(data))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "history.json"
        self.path.write_text(json.dumps(payload()), encoding="utf-8")

    def test_runtime_validates_the_fixture_on_startup(self):
        RuntimeConfig(underlying_history_fixture=str(self.path)).validate()

    def test_runtime_rejects_a_malformed_fixture_on_startup(self):
        self.path.write_text(
            json.dumps(payload(schema_version="bad.v1")), encoding="utf-8"
        )

        with self.assertRaises(ValueError):
            RuntimeConfig(underlying_history_fixture=str(self.path)).validate()

    def test_cache_identity_tracks_the_history_file(self):
        """A refreshed capture must invalidate a cached record.

        Identity is keyed on path/size/mtime, matching how every other fixture
        is tracked. A real refresh appends observations, so both change. Note
        the known narrowness of that key: a same-size rewrite inside one
        filesystem timestamp tick would not be detected — true for all fixtures
        here, not just this one.
        """
        options = {"underlying_history_fixture": str(self.path)}
        before = _analysis_cache_identity(dict(options))

        refreshed = payload()
        refreshed["observations"].append(
            {
                "timestamp_ms": 1_700_000_000_000 + 4 * 86_400_000,
                "observed_at": "2024-01-05T00:00:00Z",
                "close": 100_004.0,
            }
        )
        refreshed["observation_count"] = len(refreshed["observations"])
        self.path.write_text(json.dumps(refreshed), encoding="utf-8")
        after = _analysis_cache_identity(dict(options))

        self.assertNotEqual(before["local_artifacts"], after["local_artifacts"])

    def test_history_fixture_is_absent_from_identity_when_unset(self):
        self.assertEqual([], _analysis_cache_identity({})["local_artifacts"])


class LiveFetchTests(unittest.TestCase):
    def test_cli_default_keeps_headroom_beyond_vrp_window_and_rv_warmup(self):
        args = build_parser().parse_args(["--output", "history.json"])

        self.assertEqual(1200, args.days)

    def test_incomplete_daily_candle_is_not_published_as_closed_history(self):
        captured_at = "2026-08-03T09:00:00Z"
        ticks = [
            int(datetime(2026, 8, day, 8, tzinfo=UTC).timestamp() * 1000)
            for day in (1, 2, 3)
        ]

        with mock.patch(
            "crypto_options_report.market_data._get_json",
            return_value={
                "result": {
                    "status": "ok",
                    "ticks": ticks,
                    "close": [100_000.0, 101_000.0, 99_000.0],
                }
            },
        ):
            history = fetch_deribit_underlying_history(
                days=3,
                captured_at=captured_at,
            )

        self.assertEqual(2, history["observation_count"])
        self.assertEqual("2026-08-03T08:00:00Z", history["last_observed_at"])
        self.assertEqual(
            "2026-08-02T08:00:00Z",
            history["observations"][-1]["candle_open_at"],
        )
        self.assertTrue(history["closed_candles_only"])

    def test_fetch_fails_closed_when_no_candle_has_closed(self):
        tick = int(datetime(2026, 8, 3, 8, tzinfo=UTC).timestamp() * 1000)
        with mock.patch(
            "crypto_options_report.market_data._get_json",
            return_value={
                "result": {
                    "status": "ok",
                    "ticks": [tick],
                    "close": [100_000.0],
                }
            },
        ):
            with self.assertRaisesRegex(ValueError, "no closed candles"):
                fetch_deribit_underlying_history(
                    days=1,
                    captured_at="2026-08-03T09:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
