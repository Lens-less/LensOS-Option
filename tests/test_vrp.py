from __future__ import annotations

import io
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crypto_options_report.vrp import (
    DVOL_HISTORY_SCHEMA_VERSION,
    build_vrp_status,
    fetch_deribit_dvol_history,
    load_dvol_history_fixture,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _dvol_history(values: list[float], *, start_day: int = 1, currency: str = "BTC") -> dict:
    start = datetime(2024, 2, 1, tzinfo=UTC) + timedelta(days=start_day - 1)
    observations = []
    for index, value in enumerate(values):
        observed_at = (start + timedelta(days=index)).strftime("%Y-%m-%dT00:00:00Z")
        observations.append(
            {
                "timestamp_ms": 1_706_745_600_000 + index * 86_400_000,
                "observed_at": observed_at,
                "close": float(value),
            }
        )
    return {
        "schema_version": DVOL_HISTORY_SCHEMA_VERSION,
        "captured_at": "2026-08-02T08:00:00Z",
        "source": "deribit_live:https://www.deribit.com",
        "source_endpoint": "public/get_volatility_index_data",
        "index_name": f"{currency} DVOL",
        "currency": currency,
        "resolution": "1D",
        "resolution_seconds": 86400,
        "value_unit": "percent_points",
        "requested_days": len(observations),
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "coverage": {
            "expected_day_count": len(observations),
            "observed_day_count": len(observations),
            "missing_day_count": 0,
            "coverage_ratio": 1.0,
            "missing_days": [],
        },
        "observations": observations,
    }


def _underlying_history(
    closes: list[float],
    *,
    start_day: int = 1,
    currency: str = "BTC",
) -> dict:
    start = datetime(2024, 2, 1, tzinfo=UTC) + timedelta(days=start_day - 1)
    observations = []
    for index, close in enumerate(closes):
        observed_at = (start + timedelta(days=index)).strftime("%Y-%m-%dT00:00:00Z")
        observations.append(
            {
                "timestamp_ms": 1_706_745_600_000 + index * 86_400_000,
                "observed_at": observed_at,
                "close": float(close),
            }
        )
    return {
        "schema_version": "underlying_price_history.v1",
        "captured_at": "2026-08-02T08:00:00Z",
        "source": "deribit_live:https://www.deribit.com",
        "instrument_name": f"{currency}-PERPETUAL",
        "currency": currency,
        "resolution": "1D",
        "resolution_seconds": 86400,
        "requested_days": len(observations),
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


class DvolHistoryLoaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, payload: dict) -> Path:
        path = Path(self._tmp.name) / "dvol.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_fixture_loads(self):
        loaded = load_dvol_history_fixture(self._write(_dvol_history([55.0, 56.0, 57.0])))

        self.assertEqual(3, loaded["observation_count"])
        self.assertEqual("percent_points", loaded["value_unit"])

    def test_schema_mismatch_is_rejected(self):
        payload = _dvol_history([55.0, 56.0, 57.0])
        payload["schema_version"] = "bad.v1"

        with self.assertRaises(ValueError):
            load_dvol_history_fixture(self._write(payload))

    def test_non_increasing_timestamps_are_rejected(self):
        payload = _dvol_history([55.0, 56.0, 57.0])
        payload["observations"][2]["timestamp_ms"] = payload["observations"][1]["timestamp_ms"]

        with self.assertRaises(ValueError):
            load_dvol_history_fixture(self._write(payload))

    def test_ambiguous_or_wrong_units_are_rejected(self):
        for unit in (None, "decimal_fraction"):
            with self.subTest(unit=unit):
                payload = _dvol_history([55.0, 56.0, 57.0])
                if unit is None:
                    payload.pop("value_unit")
                else:
                    payload["value_unit"] = unit

                with self.assertRaisesRegex(ValueError, "percent_points"):
                    load_dvol_history_fixture(self._write(payload))

    def test_observed_at_must_match_timestamp_and_one_row_per_utc_day(self):
        mismatch = _dvol_history([55.0, 56.0, 57.0])
        mismatch["observations"][1]["observed_at"] = "2024-02-09T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "match timestamp_ms"):
            load_dvol_history_fixture(self._write(mismatch))

        duplicate_day = _dvol_history([55.0, 56.0, 57.0])
        duplicate_day["observations"][1]["timestamp_ms"] = (
            duplicate_day["observations"][0]["timestamp_ms"] + 3_600_000
        )
        duplicate_day["observations"][1]["observed_at"] = "2024-02-01T01:00:00Z"
        with self.assertRaisesRegex(ValueError, "one observation per UTC day"):
            load_dvol_history_fixture(self._write(duplicate_day))


class FetchDvolHistoryTests(unittest.TestCase):
    def test_fetches_history_and_reports_gaps(self):
        payload = {
            "result": {
                "data": [
                    [1_706_745_600_000, 0.0, 0.0, 0.0, 55.0],
                    [1_706_918_400_000, 0.0, 0.0, 0.0, 57.0],
                    [1_707_004_800_000, 0.0, 0.0, 0.0, 59.0],
                ]
            }
        }

        def fake_urlopen(request, timeout):
            self.assertEqual(20, timeout)
            self.assertIn("resolution=1D", request.full_url)
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with mock.patch("crypto_options_report.vrp.urlopen", side_effect=fake_urlopen):
            history = fetch_deribit_dvol_history(
                currency="BTC",
                days=10,
                resolution="1D",
                base_url="https://www.deribit.com",
                timeout=20,
                captured_at="2026-08-02T08:00:00Z",
            )

        self.assertEqual("BTC DVOL", history["index_name"])
        self.assertEqual("percent_points", history["value_unit"])
        self.assertEqual([55.0, 57.0, 59.0], [row["close"] for row in history["observations"]])
        self.assertEqual(["2024-02-02"], history["coverage"]["missing_days"])
        self.assertAlmostEqual(0.75, history["coverage"]["coverage_ratio"], places=6)

    def test_unknown_row_shape_fails_closed(self):
        payload = {"result": {"data": ["bad-row"]}}

        with mock.patch(
            "crypto_options_report.vrp.urlopen",
            return_value=_FakeResponse(json.dumps(payload).encode("utf-8")),
        ):
            with self.assertRaisesRegex(ValueError, "unrecognized volatility index row shape"):
                fetch_deribit_dvol_history(
                    currency="BTC",
                    days=10,
                    base_url="https://www.deribit.com",
                    timeout=20,
                    captured_at="2026-08-02T08:00:00Z",
                )

    def test_non_finite_close_fails_closed(self):
        payload = {
            "result": {
                "data": [[1_706_745_600_000, 0.0, 0.0, 0.0, float("inf")]]
            }
        }

        with mock.patch(
            "crypto_options_report.vrp.urlopen",
            return_value=_FakeResponse(json.dumps(payload).encode("utf-8")),
        ):
            with self.assertRaisesRegex(ValueError, "invalid volatility index value"):
                fetch_deribit_dvol_history(
                    currency="BTC",
                    days=10,
                    base_url="https://www.deribit.com",
                    timeout=20,
                    captured_at="2026-08-02T08:00:00Z",
                )


class BuildVrpStatusTests(unittest.TestCase):
    def test_missing_dvol_history_is_unavailable_with_remediation(self):
        report = build_vrp_status(
            dvol_history=None,
            underlying_history=_underlying_history([100.0] * 40),
            generated_at="2026-08-02T08:00:00Z",
        )

        self.assertEqual("unavailable", report["status"])
        self.assertEqual("unavailable", report["evidence_class"])
        self.assertIsNone(report["current"]["vrp_percent_points"])
        self.assertIn("crypto-options-dvol-history", report["remediation"]["command"])

    def test_short_history_cannot_publish_a_placeholder_headline(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 40),
            underlying_history=_underlying_history([100.0] * 40),
            generated_at="2026-08-02T08:00:00Z",
        )

        self.assertEqual("insufficient_history", report["status"])
        self.assertEqual(["INSUFFICIENT_VRP_HISTORY"], report["reason_codes"])
        self.assertIsNone(report["current"]["vrp_percent_points"])
        self.assertEqual(10, report["series_sample_count"])
        self.assertEqual(1000, report["minimum_series_sample_count"])

    def test_percentile_boundaries_map_to_registered_bands(self):
        cases = [
            ([1, 2, 3, 4, 5, 6, 7, 8, 10, 9], 0.9, "extremely_expensive"),
            ([1, 2, 3, 4, 5, 6, 8, 9, 10, 7], 0.7, "expensive"),
            ([1, 2, 4, 5, 6, 7, 8, 9, 10, 3], 0.3, "thin"),
            ([2, 3, 4, 5, 6, 7, 8, 9, 10, 1], 0.1, "extremely_thin"),
        ]

        for values, percentile, band in cases:
            with self.subTest(percentile=percentile):
                report = build_vrp_status(
                    dvol_history=_dvol_history([50.0] * 30 + values),
                    underlying_history=_underlying_history([100.0] * 40),
                    generated_at="2026-08-02T08:00:00Z",
                    window_days=10,
                    minimum_series_sample_count=1,
                )

                self.assertEqual("validated", report["status"])
                self.assertAlmostEqual(percentile, report["current"]["percentile"], places=6)
                self.assertEqual(band, report["current"]["band"])

    def test_gap_days_are_reported_and_not_interpolated(self):
        history = _dvol_history([50.0] * 40)
        history["observations"].pop(9)
        history["observation_count"] = len(history["observations"])
        history["coverage"]["expected_day_count"] = 40
        history["coverage"]["observed_day_count"] = 39
        history["coverage"]["missing_day_count"] = 1
        history["coverage"]["coverage_ratio"] = 39 / 40
        history["coverage"]["missing_days"] = ["2024-02-10"]
        history["first_observed_at"] = history["observations"][0]["observed_at"]
        history["last_observed_at"] = history["observations"][-1]["observed_at"]

        report = build_vrp_status(
            dvol_history=history,
            underlying_history=_underlying_history([100.0] * 40),
            generated_at="2026-08-02T08:00:00Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertEqual(["2024-02-10"], report["missing_days"])
        self.assertNotIn("2024-02-10", [row["date"] for row in report["time_series"]])

    def test_history_after_evaluation_clock_cannot_leak_into_vrp(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 39 + [99.0] * 6),
            underlying_history=_underlying_history([100.0] * 45),
            generated_at="2024-03-10T12:00:00Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertEqual("2024-03-10", report["current"]["date"])
        self.assertTrue(
            all(point["date"] <= "2024-03-10" for point in report["time_series"])
        )

    def test_large_series_keeps_full_three_year_window_sample_count(self):
        dvol_values = [40.0 + float(index % 20) for index in range(1130)]
        report = build_vrp_status(
            dvol_history=_dvol_history(dvol_values),
            underlying_history=_underlying_history([100.0] * 1130),
            generated_at="2027-03-10T08:00:00Z",
        )

        self.assertEqual("validated", report["status"])
        self.assertGreaterEqual(len(report["time_series"]), 1000)
        self.assertEqual(1095, report["current"]["percentile_sample_count"])
        self.assertEqual(30, report["current"]["rv_sample_count"])
        self.assertEqual(1000, report["minimum_series_sample_count"])


if __name__ == "__main__":
    unittest.main()
