from __future__ import annotations

import io
import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlparse

from crypto_options_report.vrp import (
    DVOL_HISTORY_SCHEMA_VERSION,
    _band_for_percentile,
    build_vrp_status,
    fetch_deribit_dvol_history,
    load_dvol_history_fixture,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _timestamp_ms(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    if "T" not in normalized:
        normalized = f"{normalized}T00:00:00+00:00"
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


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
        "captured_at": observations[-1]["observed_at"],
        "source": "deribit_live:https://www.deribit.com",
        "source_endpoint": "public/get_volatility_index_data",
        "index_name": f"{currency} DVOL",
        "currency": currency,
        "resolution": "1D",
        "resolution_seconds": 86400,
        "value_unit": "percent_points",
        "requested_days": max(0, len(observations) - 1),
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
    start = datetime(2024, 2, 1, 8, tzinfo=UTC) + timedelta(days=start_day - 1)
    observations = []
    for index, close in enumerate(closes):
        observed = start + timedelta(days=index)
        observed_at = observed.strftime("%Y-%m-%dT%H:%M:%SZ")
        observations.append(
            {
                "timestamp_ms": int(observed.timestamp() * 1000),
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

    def test_fixture_rejects_a_page_sized_series_that_does_not_cover_requested_window(self):
        payload = _dvol_history([55.0, 56.0, 57.0])
        payload["requested_days"] = 4
        payload["coverage"]["expected_day_count"] = 3

        with self.assertRaisesRegex(ValueError, "requested dvol history window"):
            load_dvol_history_fixture(self._write(payload))


class FetchDvolHistoryTests(unittest.TestCase):
    def test_redirect_response_fails_closed_without_following_target(self):
        class RedirectHandler(BaseHTTPRequestHandler):
            target_hits = 0

            def do_GET(self):
                if self.path.startswith("/api/v2/public/get_volatility_index_data"):
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    return
                type(self).target_hits += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"result":{"data":[]}}')

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch(
                "crypto_options_report.vrp.validate_deribit_base_url",
                return_value=f"http://127.0.0.1:{server.server_port}",
            ):
                with self.assertRaisesRegex(ValueError, "http 302"):
                    fetch_deribit_dvol_history(
                        currency="BTC",
                        days=3,
                        resolution="1D",
                        base_url="https://www.deribit.com",
                        timeout=20,
                        captured_at="2024-02-05T08:00:00Z",
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(0, RedirectHandler.target_hits)

    def test_fetches_requested_window_across_continuation_pages(self):
        pages = [
            {
                "result": {
                    "data": [
                        [_timestamp_ms("2024-02-04"), 0.0, 0.0, 0.0, 57.0],
                        [_timestamp_ms("2024-02-05"), 0.0, 0.0, 0.0, 59.0],
                    ],
                    "continuation": _timestamp_ms("2024-02-03"),
                }
            },
            {
                "result": {
                    "data": [
                        [_timestamp_ms("2024-02-02"), 0.0, 0.0, 0.0, 55.0],
                        [_timestamp_ms("2024-02-03"), 0.0, 0.0, 0.0, 56.0],
                    ]
                }
            },
        ]
        seen_queries: list[dict[str, list[str]]] = []

        def fake_urlopen(request, timeout):
            self.assertEqual(20, timeout)
            seen_queries.append(parse_qs(urlparse(request.full_url).query))
            return _FakeResponse(json.dumps(pages[len(seen_queries) - 1]).encode("utf-8"))

        with mock.patch("crypto_options_report.vrp.urlopen", side_effect=fake_urlopen):
            history = fetch_deribit_dvol_history(
                currency="BTC",
                days=3,
                resolution="1D",
                base_url="https://www.deribit.com",
                timeout=20,
                captured_at="2024-02-05T08:00:00Z",
            )

        self.assertEqual("BTC DVOL", history["index_name"])
        self.assertEqual("percent_points", history["value_unit"])
        self.assertEqual(
            [55.0, 56.0, 57.0, 59.0],
            [row["close"] for row in history["observations"]],
        )
        self.assertEqual([], history["coverage"]["missing_days"])
        self.assertAlmostEqual(1.0, history["coverage"]["coverage_ratio"], places=6)
        self.assertEqual(2, len(seen_queries))
        self.assertEqual([str(_timestamp_ms("2024-02-05T08:00:00Z"))], seen_queries[0]["end_timestamp"])
        self.assertEqual([str(_timestamp_ms("2024-02-03"))], seen_queries[1]["end_timestamp"])

    def test_request_window_coverage_counts_requested_dates_not_observed_span(self):
        payload = {
            "result": {
                "data": [
                    [_timestamp_ms("2024-02-02"), 0.0, 0.0, 0.0, 55.0],
                    [_timestamp_ms("2024-02-04"), 0.0, 0.0, 0.0, 57.0],
                    [_timestamp_ms("2024-02-05"), 0.0, 0.0, 0.0, 59.0],
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
                days=3,
                resolution="1D",
                base_url="https://www.deribit.com",
                timeout=20,
                captured_at="2024-02-05T08:00:00Z",
            )

        self.assertEqual(["2024-02-03"], history["coverage"]["missing_days"])
        self.assertEqual(4, history["coverage"]["expected_day_count"])
        self.assertAlmostEqual(0.75, history["coverage"]["coverage_ratio"], places=6)

    def test_requested_window_without_enough_history_fails_closed(self):
        pages = [
            {
                "result": {
                    "data": [
                        [_timestamp_ms("2024-02-04"), 0.0, 0.0, 0.0, 57.0],
                        [_timestamp_ms("2024-02-05"), 0.0, 0.0, 0.0, 59.0],
                    ],
                    "continuation": _timestamp_ms("2024-02-03"),
                }
            },
            {
                "result": {
                    "data": [[_timestamp_ms("2024-02-03"), 0.0, 0.0, 0.0, 56.0]]
                }
            },
        ]

        with mock.patch(
            "crypto_options_report.vrp.urlopen",
            side_effect=lambda request, timeout: _FakeResponse(
                json.dumps(pages.pop(0)).encode("utf-8")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "requested dvol history window"):
                fetch_deribit_dvol_history(
                    currency="BTC",
                    days=3,
                    resolution="1D",
                    base_url="https://www.deribit.com",
                    timeout=20,
                    captured_at="2024-02-05T08:00:00Z",
                )

    def test_non_advancing_continuation_fails_closed(self):
        pages = [
            {
                "result": {
                    "data": [
                        [_timestamp_ms("2024-02-04"), 0.0, 0.0, 0.0, 57.0],
                        [_timestamp_ms("2024-02-05"), 0.0, 0.0, 0.0, 59.0],
                    ],
                    "continuation": _timestamp_ms("2024-02-05T08:00:00Z"),
                }
            }
        ]

        with mock.patch(
            "crypto_options_report.vrp.urlopen",
            side_effect=lambda request, timeout: _FakeResponse(
                json.dumps(pages.pop(0)).encode("utf-8")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "continuation must strictly decrease"):
                fetch_deribit_dvol_history(
                    currency="BTC",
                    days=3,
                    resolution="1D",
                    base_url="https://www.deribit.com",
                    timeout=20,
                    captured_at="2024-02-05T08:00:00Z",
                )

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

    def test_multiple_remediation_commands_are_structured_and_cross_shell_safe(self):
        report = build_vrp_status(
            dvol_history=None,
            underlying_history=None,
            generated_at="2026-08-02T08:00:00Z",
        )

        commands = report["remediation"]["commands"]
        self.assertEqual(2, len(commands))
        self.assertIn("crypto-options-dvol-history", commands[0])
        self.assertIn("crypto-options-underlying-history", commands[1])
        self.assertEqual("\n".join(commands), report["remediation"]["command"])
        self.assertNotIn("&&", report["remediation"]["command"])

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
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9], 0.9, "extremely_expensive"),
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 7], 0.7, "expensive"),
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 3], 0.3, "thin"),
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1], 0.1, "extremely_thin"),
        ]

        for values, percentile, band in cases:
            with self.subTest(percentile=percentile):
                report = build_vrp_status(
                    dvol_history=_dvol_history([50.0] * 30 + values),
                    underlying_history=_underlying_history([100.0] * 41),
                    generated_at="2024-03-12T08:00:00Z",
                    window_days=11,
                    minimum_series_sample_count=1,
                )

                self.assertEqual("validated", report["status"])
                self.assertAlmostEqual(percentile, report["current"]["percentile"], places=6)
                self.assertEqual(band, report["current"]["band"])

    def test_percentile_band_thresholds_reject_near_boundary_mutations(self):
        cases = [
            (0.9, "extremely_expensive"),
            (0.8999, "expensive"),
            (0.7, "expensive"),
            (0.6999, "neutral"),
            (0.3001, "neutral"),
            (0.3, "thin"),
            (0.1001, "thin"),
            (0.1, "extremely_thin"),
        ]

        for percentile, band in cases:
            with self.subTest(percentile=percentile):
                self.assertEqual(band, _band_for_percentile(percentile))

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
            generated_at="2024-03-11T08:00:00Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertEqual(["2024-02-10"], report["missing_days"])
        self.assertNotIn("2024-02-10", [row["date"] for row in report["time_series"]])

    def test_underlying_gap_reports_every_affected_rv30_evaluation_day(self):
        dvol = _dvol_history([50.0] * 100)
        underlying = _underlying_history([100.0] * 100)
        missing_underlying_date = "2024-03-22"
        underlying["observations"] = [
            row
            for row in underlying["observations"]
            if row["observed_at"][:10] != missing_underlying_date
        ]

        report = build_vrp_status(
            dvol_history=dvol,
            underlying_history=underlying,
            generated_at="2024-05-10T08:00:00Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        expected_dates = [
            (datetime(2024, 3, 22, tzinfo=UTC) + timedelta(days=offset))
            .date()
            .isoformat()
            for offset in range(31)
        ]
        self.assertEqual("validated", report["status"])
        self.assertEqual(expected_dates, report["missing_days"])
        self.assertEqual(expected_dates, [item["date"] for item in report["missing_evidence"]])
        self.assertTrue(
            all(
                item["reason_code"] == "INCOMPLETE_UNDERLYING_RV30_WINDOW"
                and item["missing_underlying_days"] == [missing_underlying_date]
                for item in report["missing_evidence"]
            )
        )
        published_dates = {row["date"] for row in report["time_series"]}
        self.assertTrue(published_dates.isdisjoint(expected_dates))

    def test_stale_history_cannot_validate_the_latest_evaluation_date(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 914),
            underlying_history=_underlying_history([100.0] * 80),
            generated_at="2026-08-02T08:00:00Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        self.assertEqual("unavailable", report["status"])
        self.assertEqual(["STALE_VRP_EVALUATION_DATE"], report["reason_codes"])
        self.assertIsNone(report["current"]["vrp_percent_points"])
        self.assertEqual("2026-08-02", report["missing_evidence"][-1]["date"])
        self.assertIn(
            "INCOMPLETE_UNDERLYING_RV30_WINDOW",
            report["missing_evidence"][-1]["reason_codes"],
        )
        self.assertNotIn(
            "MISSING_DVOL_OBSERVATION",
            report["missing_evidence"][-1]["reason_codes"],
        )

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

    def test_only_closed_0800z_candle_contributes_to_headline(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 39 + [60.0, 70.0, 80.0, 90.0, 95.0, 99.0]),
            underlying_history=_underlying_history([100.0] * 45),
            generated_at="2024-03-10T07:59:59Z",
            window_days=10,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertEqual("2024-03-09", report["current"]["date"])
        self.assertTrue(
            all(point["date"] <= "2024-03-09" for point in report["time_series"])
        )

    def test_underlying_history_requires_one_observation_per_utc_day(self):
        underlying = _underlying_history([100.0] * 40)
        underlying["observations"][1]["timestamp_ms"] = (
            underlying["observations"][0]["timestamp_ms"] + 3_600_000
        )
        underlying["observations"][1]["observed_at"] = "2024-02-01T01:00:00Z"

        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 40),
            underlying_history=underlying,
            generated_at="2026-08-02T08:00:00Z",
        )

        self.assertEqual("unavailable", report["status"])
        self.assertEqual(["INVALID_UNDERLYING_HISTORY"], report["reason_codes"])

    def test_percentiles_stay_null_until_minimum_window_sample_count(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([40.0 + float(index) for index in range(131)]),
            underlying_history=_underlying_history([100.0] * 131),
            generated_at="2024-06-10T08:00:00Z",
            window_days=130,
            minimum_series_sample_count=100,
        )

        self.assertEqual("validated", report["status"])
        self.assertEqual(101, len(report["time_series"]))
        self.assertTrue(
            all(
                point["percentile"] is None and point["band"] is None
                for point in report["time_series"][:100]
            )
        )
        self.assertEqual(100, report["time_series"][-1]["percentile_sample_count"])
        self.assertIsNotNone(report["time_series"][-1]["percentile"])
        self.assertIsNotNone(report["time_series"][-1]["band"])

    def test_exactly_minimum_raw_points_cannot_publish_without_prior_comparisons(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([40.0 + float(index) for index in range(130)]),
            underlying_history=_underlying_history([100.0] * 130),
            generated_at="2024-06-09T08:00:00Z",
            window_days=130,
            minimum_series_sample_count=100,
        )

        self.assertEqual("insufficient_history", report["status"])
        self.assertEqual(["INSUFFICIENT_VRP_HISTORY"], report["reason_codes"])
        self.assertIsNone(report["current"]["vrp_percent_points"])
        self.assertEqual(99, report["time_series"][-1]["percentile_sample_count"])
        self.assertIsNone(report["time_series"][-1]["percentile"])

    def test_percentile_compares_current_value_to_prior_points_only(self):
        report = build_vrp_status(
            dvol_history=_dvol_history([50.0] * 30 + [60.0, 40.0]),
            underlying_history=_underlying_history([100.0] * 32),
            generated_at="2024-03-03T08:00:00Z",
            window_days=2,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertIsNone(report["time_series"][0]["percentile"])
        self.assertEqual(0, report["time_series"][0]["percentile_sample_count"])
        self.assertEqual(0.0, report["current"]["percentile"])
        self.assertEqual(1, report["current"]["percentile_sample_count"])
        self.assertEqual("extremely_thin", report["current"]["band"])

    def test_current_rv30_uses_365_day_sample_vol_and_percent_units(self):
        closes = [
            100.0,
            101.25,
            100.1,
            102.5,
            101.8,
            103.4,
            104.2,
            103.7,
            105.1,
            104.6,
            106.3,
            105.4,
            107.0,
            108.2,
            107.6,
            109.4,
            110.1,
            109.7,
            111.5,
            112.3,
            111.2,
            113.0,
            112.6,
            114.4,
            115.1,
            114.2,
            116.0,
            117.3,
            116.5,
            118.1,
            119.4,
        ]
        report = build_vrp_status(
            dvol_history=_dvol_history([60.0] * (len(closes) + 1)),
            underlying_history=_underlying_history([closes[0]] + closes),
            generated_at="2024-03-03T08:00:00Z",
            window_days=2,
            minimum_series_sample_count=1,
        )

        self.assertEqual("validated", report["status"])
        self.assertAlmostEqual(19.981882, report["current"]["rv30_percent_points"], places=6)
        self.assertAlmostEqual(40.018118, report["current"]["vrp_percent_points"], places=6)
        self.assertEqual("2024-03-03T00:00:00Z", report["current"]["dvol_observed_at"])
        self.assertEqual(
            "2024-03-03T08:00:00Z",
            report["current"]["underlying_observed_at"],
        )
        self.assertEqual("2024-03-03T08:00:00Z", report["current"]["evaluation_at"])

    def test_large_series_keeps_full_three_year_window_sample_count(self):
        dvol_values = [40.0 + float(index % 20) for index in range(1130)]
        report = build_vrp_status(
            dvol_history=_dvol_history(dvol_values),
            underlying_history=_underlying_history([100.0] * 1130),
            generated_at="2027-03-06T08:00:00Z",
        )

        self.assertEqual("validated", report["status"])
        self.assertGreaterEqual(len(report["time_series"]), 1000)
        self.assertEqual(1094, report["current"]["percentile_sample_count"])
        self.assertEqual(30, report["current"]["rv_sample_count"])
        self.assertEqual(1000, report["minimum_series_sample_count"])


if __name__ == "__main__":
    unittest.main()
