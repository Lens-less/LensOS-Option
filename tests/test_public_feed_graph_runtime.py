import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest import mock

from crypto_options_report.market_data import (
    advance_trust_evidence,
    build_market_data_status,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
    parse_timestamp_ms,
    write_snapshot_fixture,
    write_snapshot_trust_state,
)

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURED_AT = "2026-07-13T00:00:00Z"


class PublicFeedGraphRuntimeTests(unittest.TestCase):
    def test_source_checkout_tool_imports_package_outside_repo_cwd(self):
        tool = Path(__file__).parents[1] / "tools" / "refresh_market_snapshot.py"
        completed = subprocess.run(
            [sys.executable, str(tool), "--help"],
            cwd=Path.home(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--complete-feed-graph", completed.stdout)

    def test_live_collector_builds_real_bounded_feed_graph_with_provenance(self):
        calls = []

        def rpc(url, params, timeout):
            calls.append((url.rsplit("/", 1)[-1], dict(params)))
            endpoint = url.rsplit("/", 1)[-1]
            if endpoint == "get_book_summary_by_currency":
                return {"result": [_summary(index) for index in range(8)]}
            if endpoint == "get_instruments":
                return {"result": [_instrument(index) for index in range(8)]}
            if endpoint == "ticker":
                name = params["instrument_name"]
                return {"result": _ticker(name)}
            if endpoint == "get_volatility_index_data":
                return {
                    "result": {
                        "data": [[1783900800000, 60.0, 61.0, 59.0, 60.5]]
                    }
                }
            if endpoint == "get_index_price":
                return {
                    "result": {
                        "index_price": 100000.0,
                        "estimated_delivery_price": 100010.0,
                    }
                }
            if endpoint == "get_funding_rate_value":
                return {"result": 0.00012}
            if endpoint == "get_order_book":
                return {
                    "result": {
                        "instrument_name": params["instrument_name"],
                        "timestamp": 1783900800000,
                        "state": "open",
                        "change_id": 42,
                        "index_price": 100000.0,
                        "mark_price": 0.08,
                        "best_bid_price": 0.079,
                        "best_bid_amount": 4.0,
                        "best_ask_price": 0.081,
                        "best_ask_amount": 5.0,
                        "bids": [[0.079, 4.0]],
                        "asks": [[0.081, 5.0]],
                    }
                }
            if endpoint == "status":
                return {
                    "result": {
                        "locked": False,
                        "locked_currencies": [],
                        "locked_indices": [],
                    }
                }
            raise AssertionError(f"unexpected endpoint {endpoint}")

        with (
            mock.patch("crypto_options_report.market_data.utc_timestamp", return_value=CAPTURED_AT),
            mock.patch("crypto_options_report.market_data._get_json", side_effect=rpc),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                instrument_limit=8,
                include_feed_graph=True,
            )

        status = build_market_data_status(
            snapshot,
            now_ms=parse_timestamp_ms(CAPTURED_AT),
        )
        feeds = snapshot["feeds"]
        self.assertEqual(
            {"events", "funding_basis", "index_spot", "order_book", "vol_index"},
            set(feeds),
        )
        self.assertEqual("research_sample", feeds["order_book"]["scope"]["kind"])
        self.assertEqual(1, feeds["order_book"]["scope"]["sampled_instrument_count"])
        self.assertEqual(8, feeds["order_book"]["scope"]["selected_instrument_count"])
        self.assertEqual("exchange_native_only", feeds["events"]["scope"])
        self.assertEqual([], feeds["events"]["macro_events"])
        self.assertEqual(0.00012, feeds["funding_basis"]["funding_rate"])
        self.assertEqual(100000.0, feeds["index_spot"]["index_price"])
        self.assertEqual([], status["feed_coverage"]["missing_required_feeds"])
        self.assertTrue(status["feed_coverage"]["graph_complete"])
        self.assertEqual("live_required", status["feed_coverage"]["scope"])
        for name in ("order_book", "funding_basis", "index_spot", "events"):
            self.assertEqual("available", status["feed_coverage"]["feeds"][name]["status"])
            self.assertTrue(feeds[name]["source_endpoint"].startswith("public/"))
            self.assertEqual("DERIBIT", feeds[name]["provenance"]["venue"])

        endpoints = {name for name, _ in calls}
        self.assertTrue(
            {"get_order_book", "get_index_price", "get_funding_rate_value", "status"}
            <= endpoints
        )

    def test_live_auxiliary_feed_failure_is_visible_and_fails_closed(self):
        def rpc(url, params, timeout):
            endpoint = url.rsplit("/", 1)[-1]
            if endpoint == "get_book_summary_by_currency":
                return {"result": [_summary(index) for index in range(8)]}
            if endpoint == "get_instruments":
                return {"result": [_instrument(index) for index in range(8)]}
            if endpoint == "ticker":
                return {"result": _ticker(params["instrument_name"])}
            if endpoint == "get_volatility_index_data":
                return {"result": {"data": [[1783900800000, 60, 61, 59, 60.5]]}}
            if endpoint == "get_index_price":
                raise ValueError("network error: upstream unavailable")
            if endpoint == "get_funding_rate_value":
                return {"result": 0.00012}
            if endpoint == "get_order_book":
                return {
                    "result": {
                        "instrument_name": params["instrument_name"],
                        "timestamp": 1783900800000,
                        "state": "open",
                        "change_id": 42,
                        "index_price": 100000.0,
                        "mark_price": 0.08,
                        "best_bid_price": 0.079,
                        "best_bid_amount": 4.0,
                        "best_ask_price": 0.081,
                        "best_ask_amount": 5.0,
                        "bids": [[0.079, 4.0]],
                        "asks": [[0.081, 5.0]],
                    }
                }
            if endpoint == "status":
                return {"result": {"locked": False, "locked_currencies": []}}
            raise AssertionError(endpoint)

        with (
            mock.patch("crypto_options_report.market_data.utc_timestamp", return_value=CAPTURED_AT),
            mock.patch("crypto_options_report.market_data._get_json", side_effect=rpc),
        ):
            snapshot = fetch_deribit_option_chain_snapshot(
                instrument_limit=8,
                include_feed_graph=True,
            )

        status = build_market_data_status(
            snapshot,
            now_ms=parse_timestamp_ms(CAPTURED_AT),
        )
        self.assertNotIn("index_spot", snapshot["feeds"])
        self.assertIn("index_spot", status["feed_coverage"]["missing_required_feeds"])
        self.assertFalse(status["feed_coverage"]["graph_complete"])
        self.assertEqual("blocked", status["status"])
        self.assertTrue(any(error.startswith("index_spot:") for error in snapshot["fetch_errors"]))

    def test_consecutive_live_evidence_promotes_then_resets_on_broken_feed(self):
        previous = None
        base_ms = parse_timestamp_ms(CAPTURED_AT)
        for offset_seconds in range(0, 200, 10):
            current_ms = base_ms + offset_seconds * 1000
            snapshot = _complete_live_snapshot(current_ms)
            evidence = advance_trust_evidence(snapshot, previous_snapshot=previous)
            snapshot["trust_evidence"] = evidence
            previous = snapshot

        self.assertEqual("promoted", previous["trust_evidence"]["status"])
        self.assertEqual(20, previous["trust_evidence"]["consecutive_passes"])
        self.assertGreaterEqual(previous["trust_evidence"]["observation_seconds"], 60)
        self.assertTrue(previous["trust_evidence"]["feed_graph_complete"])
        self.assertEqual([], previous["trust_evidence"]["reason_codes"])
        self.assertEqual("ready", previous["trust_evidence"]["rolling_status"])
        self.assertEqual(20, previous["trust_evidence"]["rolling_observation_count"])
        self.assertNotIn("production_gate", previous["trust_evidence"])
        self.assertEqual(
            {"observed_at", "index_price", "dvol", "atm_iv", "iv_unit", "funding_rate", "source"},
            set(previous["trust_evidence"]["rolling_observations"][-1]),
        )

        broken = _complete_live_snapshot(base_ms + 200_000)
        broken["feeds"].pop("events")
        reset = advance_trust_evidence(broken, previous_snapshot=previous)
        self.assertEqual("reset", reset["status"])
        self.assertEqual(0, reset["consecutive_passes"])
        self.assertIn("PUBLIC_FEED_GRAPH_INCOMPLETE", reset["reason_codes"])
        self.assertEqual(20, reset["rolling_observation_count"])

    def test_restart_after_pass_gap_resets_continuity_and_rolling_window(self):
        previous = None
        base_ms = parse_timestamp_ms(CAPTURED_AT)
        for offset_seconds in range(0, 200, 10):
            snapshot = _complete_live_snapshot(base_ms + offset_seconds * 1000)
            snapshot["trust_evidence"] = advance_trust_evidence(
                snapshot,
                previous_snapshot=previous,
            )
            previous = snapshot

        resumed = _complete_live_snapshot(base_ms + 600_000)
        evidence = advance_trust_evidence(resumed, previous_snapshot=previous)

        self.assertEqual("reset", evidence["status"])
        self.assertEqual(1, evidence["consecutive_passes"])
        self.assertEqual(resumed["captured_at"], evidence["first_pass_at"])
        self.assertEqual(0, evidence["observation_seconds"])
        self.assertIn("TRUST_PASS_GAP_EXCEEDED", evidence["reason_codes"])
        self.assertEqual(1, evidence["rolling_observation_count"])

    def test_future_auxiliary_feed_timestamp_cannot_be_fresh_or_trusted(self):
        captured_ms = parse_timestamp_ms(CAPTURED_AT)
        snapshot = _complete_live_snapshot(captured_ms)
        snapshot["feeds"]["order_book"]["timestamp"] = _iso(
            captured_ms + 60_000
        )

        status = build_market_data_status(snapshot, now_ms=captured_ms)
        evidence = advance_trust_evidence(snapshot)

        order_book = status["feed_coverage"]["feeds"]["order_book"]
        self.assertEqual("invalid", order_book["status"])
        self.assertEqual("future", order_book["freshness_status"])
        self.assertEqual("FUTURE_TIMESTAMP_ORDER_BOOK", order_book["reason_code"])
        self.assertIn("order_book", status["feed_coverage"]["missing_required_feeds"])
        self.assertEqual("reset", evidence["status"])

    def test_future_vol_index_and_ticker_timestamps_fail_closed(self):
        captured_ms = parse_timestamp_ms(CAPTURED_AT)
        snapshot = _complete_live_snapshot(captured_ms)
        future_at = _iso(captured_ms + 60_000)
        snapshot["feeds"]["vol_index"]["timestamp"] = future_at
        for row in snapshot["rows"]:
            row["ticker"]["timestamp"] = captured_ms + 60_000

        status = build_market_data_status(snapshot, now_ms=captured_ms)
        evidence = advance_trust_evidence(snapshot)

        vol_index = status["feed_coverage"]["feeds"]["vol_index"]
        self.assertEqual("invalid", vol_index["status"])
        self.assertEqual("future", vol_index["freshness_status"])
        self.assertEqual("FUTURE_TIMESTAMP_VOL_INDEX", vol_index["reason_code"])
        self.assertIn(
            "FUTURE_QUOTE_TIMESTAMP",
            status["quality_gate"]["reason_codes"],
        )
        self.assertEqual("blocked", status["status"])
        self.assertEqual("reset", evidence["status"])

    def test_snapshot_cannot_self_attest_trust_even_with_canonical_thresholds(self):
        captured_ms = parse_timestamp_ms(CAPTURED_AT)
        snapshot = _complete_live_snapshot(captured_ms)
        snapshot["trust_evidence"] = {
            "status": "promoted",
            "schema_version": "market_trust_evidence.v1",
            "consecutive_passes": 999,
            "minimum_consecutive_passes": 6,
            "observation_seconds": 999,
            "minimum_observation_seconds": 60,
            "source_identity": "deribit_live:https://www.deribit.com|BTC",
            "first_pass_at": CAPTURED_AT,
            "last_pass_at": CAPTURED_AT,
        }

        status = build_market_data_status(snapshot, now_ms=captured_ms)
        evidence = status["trust_evidence"]

        self.assertEqual("collecting", evidence["status"])
        self.assertEqual(6, evidence["minimum_consecutive_passes"])
        self.assertEqual(60, evidence["minimum_observation_seconds"])
        self.assertEqual(0, evidence["consecutive_passes"])
        self.assertIn("TRUST_EVIDENCE_NOT_OBSERVED", evidence["reason_codes"])

    def test_bound_sidecar_state_can_promote_the_exact_live_snapshot(self):
        previous = None
        base_ms = parse_timestamp_ms(CAPTURED_AT)
        for offset_seconds in range(0, 70, 10):
            snapshot = _complete_live_snapshot(base_ms + offset_seconds * 1000)
            evidence = advance_trust_evidence(
                snapshot,
                previous_snapshot=previous,
            )
            snapshot["trust_evidence"] = evidence
            previous = snapshot

        self.assertEqual("promoted", evidence["status"])
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            key_dir = Path(tmp) / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            path = data_dir / "snapshot.json"
            auth_key = key_dir / "sidecar.key"
            auth_key.write_bytes(b"k" * 32)
            write_snapshot_fixture(path, snapshot)
            write_snapshot_trust_state(
                path,
                evidence,
                expected_snapshot=snapshot,
                auth_key_file=auth_key,
            )
            loaded = load_snapshot_fixture(path, auth_key_file=auth_key)

        status = build_market_data_status(
            loaded,
            now_ms=parse_timestamp_ms(snapshot["captured_at"]),
        )
        self.assertEqual("promoted", status["trust_evidence"]["status"])

    def test_legacy_fixture_without_evidence_remains_compatible_and_collecting(self):
        snapshot = json.loads(
            (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(encoding="utf-8")
        )
        status = build_market_data_status(snapshot, now_ms=1783382490000)
        self.assertEqual("collecting", status["trust_evidence"]["status"])
        self.assertIn("TRUST_EVIDENCE_NOT_OBSERVED", status["trust_evidence"]["reason_codes"])
        self.assertIn("order_book", status["feed_coverage"]["remaining_out_of_scope_feeds"])


def _summary(index):
    strike = 100000 + index * 1000
    name = f"BTC-31JUL26-{strike}-C"
    return {
        "instrument_name": name,
        "bid_price": 0.079,
        "ask_price": 0.081,
        "mid_price": 0.08,
        "mark_price": 0.08,
        "underlying_price": 100000.0,
        "open_interest": 20.0,
        "creation_timestamp": 1783900800000,
    }


def _instrument(index):
    strike = 100000 + index * 1000
    return {
        "instrument_name": f"BTC-31JUL26-{strike}-C",
        "settlement_currency": "BTC",
        "quote_currency": "BTC",
        "base_currency": "BTC",
        "kind": "option",
    }


def _ticker(name):
    payload = {
        "instrument_name": name,
        "timestamp": 1783900800000,
        "best_bid_price": 0.079,
        "best_ask_price": 0.081,
        "best_bid_amount": 4.0,
        "best_ask_amount": 5.0,
        "mark_price": 0.08,
        "bid_iv": 59.0,
        "ask_iv": 61.0,
        "mark_iv": 60.0,
        "underlying_price": 100000.0,
        "open_interest": 20.0,
    }
    if name == "BTC-PERPETUAL":
        payload.update(
            {
                "mark_price": 100010.0,
                "index_price": 100000.0,
                "current_funding": 0.00002,
                "funding_8h": 0.00016,
            }
        )
    return payload


def _complete_live_snapshot(captured_ms):
    snapshot = json.loads(
        (FIXTURES / "deribit_btc_option_chain_snapshot.json").read_text(encoding="utf-8")
    )
    captured_at = _iso(captured_ms)
    snapshot["captured_at"] = captured_at
    snapshot["source"] = "deribit_live:https://www.deribit.com"
    for row in snapshot["rows"]:
        row["ticker"]["timestamp"] = captured_ms
        row["summary"]["creation_timestamp"] = captured_ms
    snapshot["feeds"] = {
        "vol_index": {
            "index_name": "BTC DVOL",
            "currency": "BTC",
            "timestamp": captured_at,
            "volatility": 0.64,
            "source_endpoint": "public/get_volatility_index_data",
            "provenance": _provenance(
                "public/get_volatility_index_data", captured_at
            ),
        },
        "index_spot": {
            "index_name": "btc_usd",
            "currency": "BTC",
            "index_price": 100000.0,
            "estimated_delivery_price": 100010.0,
            "observed_at": captured_at,
            "source_endpoint": "public/get_index_price",
            "scope": "btc_usd",
            "provenance": _provenance("public/get_index_price", captured_at),
        },
        "funding_basis": {
            "instrument_name": "BTC-PERPETUAL",
            "funding_rate": 0.00012,
            "basis_rate": 0.0001,
            "index_price": 100000.0,
            "mark_price": 100010.0,
            "window_start": _iso(captured_ms - 3_600_000),
            "window_end": captured_at,
            "observed_at": captured_at,
            "source_endpoint": "public/get_funding_rate_value",
            "scope": "one_hour_realized",
            "provenance": _provenance(
                "public/get_funding_rate_value+public/ticker", captured_at
            ),
        },
        "order_book": {
            "instrument_name": snapshot["rows"][0]["instrument_name"],
            "timestamp": captured_at,
            "state": "open",
            "change_id": 42,
            "best_bid_price": 0.079,
            "best_bid_amount": 4.0,
            "best_ask_price": 0.081,
            "best_ask_amount": 5.0,
            "bids": [[0.079, 4.0]],
            "asks": [[0.081, 5.0]],
            "source_endpoint": "public/get_order_book",
            "scope": {"kind": "research_sample", "sampled_instrument_count": 1},
            "provenance": _provenance("public/get_order_book", captured_at),
        },
        "events": {
            "observed_at": captured_at,
            "exchange_locked": False,
            "locked_currencies": [],
            "locked_indices": [],
            "macro_events": [],
            "source_endpoint": "public/status",
            "scope": "exchange_native_only",
            "provenance": _provenance("public/status", captured_at),
        },
    }
    snapshot["fetch_errors"] = []
    snapshot["adapter_events"] = []
    return snapshot


def _iso(timestamp_ms):
    from datetime import datetime

    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _provenance(endpoint, observed_at):
    return {
        "venue": "DERIBIT",
        "transport": "HTTPS_JSON_RPC",
        "source_endpoint": endpoint,
        "observed_at": observed_at,
        "schema_version": "deribit_public_feed.v1",
    }


if __name__ == "__main__":
    unittest.main()
