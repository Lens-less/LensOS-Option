"""Underlying price history as an operator-owned replay fixture.

Production forbids live fetches, so expected value reaches the report through a
mounted file. A malformed file must be rejected outright: a silently truncated
or reordered series would shrink the sample without shrinking the confidence
reported alongside it.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from crypto_options_report.api import RuntimeConfig, _analysis_cache_identity
from crypto_options_report.market_data import (
    UNDERLYING_HISTORY_SCHEMA_VERSION,
    load_underlying_history_fixture,
)


def payload(**overrides) -> dict:
    observations = [
        {
            "timestamp_ms": 1_700_000_000_000 + index * 86_400_000,
            "observed_at": f"2024-01-0{index + 1}T00:00:00Z",
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


if __name__ == "__main__":
    unittest.main()
