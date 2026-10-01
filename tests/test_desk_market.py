"""Fixture-only checks for complete discovery and fail-closed exact-leg reads."""

import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from itertools import pairwise

from crypto_options_report.desk_market import DeskMarketCollector, _Pacer


class Clock:
    def __init__(self):
        self.elapsed = 100.0
        self.origin = datetime(2026, 10, 1, 3, tzinfo=UTC)
        self.sleeps = []

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds

    def now(self):
        return self.origin + timedelta(seconds=self.elapsed - 100)

    def milliseconds(self):
        return int(self.now().timestamp() * 1000)


def instrument(name, *, asset="BTC", inverse=False, **overrides):
    row = {
        "instrument_name": name,
        "base_currency": asset,
        "kind": "option",
        "option_type": "call",
        "strike": 65000 if asset == "BTC" else 3000,
        "expiration_timestamp": int(datetime(2026, 10, 23, 8, tzinfo=UTC).timestamp() * 1000),
        "contract_size": 1,
        "min_trade_amount": 0.01,
        "tick_size": 5,
        "tick_size_steps": [{"above_price": 1000, "tick_size": 20}],
        "instrument_type": "reversed" if inverse else "linear",
        "settlement_currency": asset if inverse else "USDC",
        "quote_currency": asset if inverse else "USDC",
        "price_index": f"{asset.lower()}_{'usd' if inverse else 'usdc'}",
        "is_active": True,
        "settlement_period": "week",
        "maker_commission": 0,
        "taker_commission": 0.0003,
    }
    row.update(overrides)
    return row


class PublicFixture:
    def __init__(self, clock, count=4):
        self.clock = clock
        self.btc = [instrument(f"BTC_USDC-23OCT26-{65000 + i * 1000}-C") for i in range(count)]
        self.eth = [instrument("ETH_USDC-23OCT26-3000-C", asset="ETH")]
        self.inverse = [instrument("BTC-23OCT26-65000-C", inverse=True)]
        self.calls = []
        self.book_overrides = {}
        self.book_error = None
        self.summary_error = None
        self.extra = {}

    def __call__(self, url, params, timeout):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, dict(params), self.clock.monotonic(), timeout))
        if endpoint == "get_instruments":
            result = self.inverse if params["currency"] == "BTC" else []
            if params["currency"] == "USDC":
                result = self.btc + self.eth
        elif endpoint == "get_book_summary_by_currency":
            if self.summary_error and params["currency"] == "USDC":
                raise ValueError(self.summary_error)
            rows = self.inverse if params["currency"] == "BTC" else []
            if params["currency"] == "USDC":
                rows = self.btc + self.eth
            result = [{"instrument_name": row["instrument_name"], "bid_price": 500, "ask_price": 510, "mark_iv": 50, "open_interest": 100, "volume": 10, "creation_timestamp": self.clock.milliseconds(), "underlying_price": 60010} for row in rows]
        elif endpoint == "get_index_price":
            result = {"index_price": 60000 if params["index_name"] == "btc_usdc" else 3000}
        elif endpoint == "get_order_book":
            if self.book_error:
                raise ValueError(self.book_error)
            result = {"instrument_name": params["instrument_name"], "bids": [[500, 2]], "asks": [[510, 3]], "mark_iv": 50, "timestamp": self.clock.milliseconds(), "state": "open", "index_price": 60000, "underlying_price": 60010, "greeks": {"delta": 0.2}}
            result.update(self.book_overrides)
        elif endpoint == "get_instrument":
            result = self.extra[params["instrument_name"]]
        else:
            raise AssertionError(endpoint)
        return {"jsonrpc": "2.0", "result": copy.deepcopy(result)}


class DeskMarketTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.public = PublicFixture(self.clock)
        self.collector = self.make_collector()

    def make_collector(self, **kwargs):
        return DeskMarketCollector(transport=self.public, clock=self.clock.monotonic, sleep=self.clock.sleep, now=self.clock.now, pacer=_Pacer(), **kwargs)

    def test_truncated_registry_is_reported_as_partial_without_leaking_response_bytes(self):
        def transport(url, params, timeout):
            if url.endswith("/get_instruments") and params["currency"] == "USDC":
                raise IncompleteRead(b"private-response-fragment", 10)
            return self.public(url, params, timeout)

        self.collector.transport = transport
        snapshot = self.collector.fetch_snapshot("BTC")
        self.assertFalse(snapshot["coverage"]["scan_complete"])
        failure = snapshot["coverage"]["failures"][0]
        self.assertEqual("PUBLIC_DATA_UNAVAILABLE", failure["code"])
        self.assertEqual("USDC", failure["scope"])
        self.assertIn("incomplete", failure["message"])
        self.assertNotIn("private-response-fragment", str(snapshot))

    def test_truncated_exact_book_withdraws_the_previous_quote(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        name = self.public.btc[0]["instrument_name"]
        previous = self.collector.deepen(snapshot, [name])
        self.assertIn(name, previous["quotes"])

        def transport(url, params, timeout):
            if url.endswith("/get_order_book"):
                raise IncompleteRead(b"partial-book", 20)
            return self.public(url, params, timeout)

        self.collector.transport = transport
        refreshed = self.collector.deepen(previous, [name])
        self.assertNotIn(name, refreshed["quotes"])
        self.assertEqual("PUBLIC_DATA_UNAVAILABLE", refreshed["coverage"]["failures"][-1]["code"])
        self.assertIn(name, previous["quotes"])

    def test_complete_discovery_does_not_apply_ticker_sample_and_preserves_units(self):
        self.public.btc = [instrument(f"BTC_USDC-23OCT26-{65000 + i * 1000}-C") for i in range(140)]
        snapshot = self.collector.fetch_snapshot("BTC")
        self.assertEqual(141, snapshot["coverage"]["registry_count"])
        self.assertEqual(141, snapshot["coverage"]["summary_count"])
        self.assertEqual(140, snapshot["coverage"]["eligible_instrument_count"])
        self.assertEqual(1, snapshot["coverage"]["inverse_excluded_count"])
        self.assertTrue(snapshot["coverage"]["scan_complete"])
        self.assertEqual({}, snapshot["quotes"])
        row = snapshot["instruments"][self.public.btc[0]["instrument_name"]]
        self.assertEqual(1, row["contract_size"])
        self.assertEqual([{ "above_price": 1000, "tick_size": 20}], row["tick_size_steps"])
        self.assertEqual("USDC", row["price_currency"])
        self.assertEqual("btc_usdc", snapshot["index"]["name"])
        self.assertEqual("summary_created", next(iter(snapshot["summaries"].values()))["timestamp_kind"])
        self.assertFalse(snapshot["execution_allowed"])
        self.assertEqual(8, len(self.public.calls))
        for before, after in pairwise(self.public.calls):
            self.assertGreaterEqual(after[2] - before[2], 0.5)
        registries = [call for call in self.public.calls if call[0] == "get_instruments"]
        for before, after in pairwise(registries):
            self.assertGreaterEqual(after[2] - before[2], 1)

    def test_btc_eth_share_finite_discovery_cache_without_rejuvenating_timestamp(self):
        first = self.collector.fetch_snapshot("BTC")
        original_time = first["captured_at"]
        first["instruments"].clear()
        self.clock.sleep(2)
        cached = self.collector.fetch_snapshot("BTC")
        eth = self.collector.fetch_snapshot("ETH")
        self.assertTrue(cached["instruments"])
        self.assertEqual(original_time, cached["captured_at"])
        self.assertEqual(original_time, eth["captured_at"])
        self.assertEqual(8, len(self.public.calls))
        self.clock.sleep(16)
        refreshed = self.collector.fetch_snapshot("BTC")
        self.assertNotEqual(original_time, refreshed["captured_at"])
        # Registry cache is retained; summaries and both indices are refreshed.
        self.assertEqual(13, len(self.public.calls))

    def test_missing_multiplier_and_invalid_tick_schedule_cannot_be_eligible(self):
        self.public.btc[0].pop("contract_size")
        self.public.btc[1]["tick_size_steps"] = [{"above_price": 1000, "tick_size": 0}]
        snapshot = self.collector.fetch_snapshot("BTC")
        for index in (0, 1):
            row = snapshot["instruments"][self.public.btc[index]["instrument_name"]]
            self.assertFalse(row["eligible"])
            self.assertTrue(row["validation_errors"])
        self.assertIsNone(snapshot["instruments"][self.public.btc[0]["instrument_name"]]["contract_size"])
        self.assertEqual(2, snapshot["coverage"]["exclusions"]["INVALID_INSTRUMENT_METADATA"])

    def test_malformed_numbers_and_option_types_are_unavailable_not_defaulted(self):
        self.public.btc[0]["strike"] = 10**400
        self.public.btc[1]["option_type"] = {"call": True}
        self.public.btc[2]["contract_size"] = float("nan")
        snapshot = self.collector.fetch_snapshot("BTC")
        for index in range(3):
            row = snapshot["instruments"][self.public.btc[index]["instrument_name"]]
            self.assertFalse(row["eligible"])
            self.assertTrue(row["validation_errors"])
        self.assertEqual(3, snapshot["coverage"]["exclusions"]["INVALID_INSTRUMENT_METADATA"])

    def test_deepen_only_exact_requested_legs_keeps_discovery_clock_and_origin_immutable(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        name = self.public.btc[2]["instrument_name"]
        deep = self.collector.deepen(snapshot, [name, name])
        self.assertEqual([name], list(deep["quotes"]))
        self.assertEqual({}, snapshot["quotes"])
        self.assertEqual(snapshot["captured_at"], deep["captured_at"])
        self.assertEqual(snapshot["expires_at"], deep["expires_at"])
        self.assertNotEqual(snapshot["snapshot_id"], deep["snapshot_id"])
        quote = deep["quotes"][name]
        self.assertTrue(quote["valid"])
        self.assertEqual(2, quote["bid_size"])
        self.assertEqual(3, quote["ask_size"])
        self.assertEqual("exchange_quote", quote["timestamp_kind"])
        self.assertEqual({"instrument_name": name, "depth": 1}, self.public.calls[-1][1])

    def test_complete_candidate_leg_request_order_is_preserved_for_quote_synchrony(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        names = [self.public.btc[index]["instrument_name"] for index in (3, 1, 2, 0)]
        result = self.collector.deepen(snapshot, names)
        observed_names = [row[1]["instrument_name"] for row in self.public.calls if row[0] == "get_order_book"]
        self.assertEqual(names, observed_names)
        times = [quote["exchange_timestamp"] for quote in result["quotes"].values()]
        self.assertLessEqual(max(times) - min(times), 2000)

    def test_unmatched_summary_is_counted_without_inventing_instrument_metadata(self):
        transport = self.public
        name = "BTC_USDC-23OCT26-99000-C"

        def with_new_listing(url, params, timeout):
            payload = transport(url, params, timeout)
            if url.endswith("get_book_summary_by_currency") and params["currency"] == "USDC":
                payload["result"].append({"instrument_name": name, "bid_price": 5, "ask_price": 10, "creation_timestamp": self.clock.milliseconds()})
            return payload

        self.collector.transport = with_new_listing
        snapshot = self.collector.fetch_snapshot("BTC")
        self.assertIn(name, snapshot["summaries"])
        self.assertNotIn(name, snapshot["instruments"])
        self.assertEqual(6, snapshot["coverage"]["summary_count"])
        self.assertEqual(1, snapshot["coverage"]["exclusions"]["MISSING_INSTRUMENT_METADATA"])

    def test_bad_books_fail_closed_and_observation_time_never_fills_missing_quote_clock(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        name = self.public.btc[0]["instrument_name"]
        cases = [({"timestamp": None}, "MISSING_EXCHANGE_TIMESTAMP"), ({"timestamp": self.clock.milliseconds() - 121000}, "STALE_QUOTE"), ({"timestamp": self.clock.milliseconds() + 20000}, "FUTURE_QUOTE_TIMESTAMP"), ({"bids": [[600, 2]], "asks": [[500, 2]]}, "CROSSED_QUOTE"), ({"asks": []}, "INVALID_ASK"), ({"bids": [[500, 0]]}, "INVALID_BID_SIZE"), ({"state": "locked"}, "INSTRUMENT_NOT_OPEN")]
        for overrides, expected in cases:
            with self.subTest(expected=expected):
                self.public.book_overrides = overrides
                quote = self.collector.deepen(snapshot, [name])["quotes"][name]
                self.assertFalse(quote["valid"])
                self.assertIn(expected, quote["validation_errors"])

    def test_failed_exact_refresh_removes_previous_quote(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        name = self.public.btc[0]["instrument_name"]
        deep = self.collector.deepen(snapshot, [name])
        self.public.book_error = "http 503 Service Unavailable"
        failed = self.collector.deepen(deep, [name])
        self.assertNotIn(name, failed["quotes"])
        self.assertEqual(0, failed["coverage"]["deepened_count"])
        self.assertEqual("PUBLIC_DATA_UNAVAILABLE", failed["coverage"]["failures"][-1]["code"])
        self.assertIn(name, deep["quotes"])

    def test_partial_partition_cannot_claim_complete_scan_and_is_not_cached(self):
        self.public.summary_error = "http 503 Service Unavailable"
        failed = self.collector.fetch_snapshot("BTC")
        self.assertFalse(failed["coverage"]["scan_complete"])
        self.assertEqual("USDC", failed["coverage"]["failures"][0]["scope"])
        self.public.summary_error = None
        recovered = self.collector.fetch_snapshot("BTC")
        self.assertTrue(recovered["coverage"]["scan_complete"])
        self.assertEqual(5, recovered["coverage"]["summary_count"])

    def test_review_exact_fetches_saved_leg_outside_discovery_without_substitution(self):
        name = "BTC_USDC-23OCT26-90000-C"
        self.public.extra[name] = instrument(name, strike=90000)
        snapshot = self.collector.review_exact("BTC", [name])
        self.assertTrue(snapshot["quotes"][name]["valid"])
        self.assertNotIn(name, snapshot["summaries"])
        endpoints = [row[0] for row in self.public.calls]
        self.assertIn("get_instrument", endpoints)
        self.assertEqual(name, self.public.calls[-1][1]["instrument_name"])

    def test_deadline_shared_with_deepening_and_never_restored_by_cache_receipt(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        self.clock.sleep(60)
        before = len(self.public.calls)
        deep = self.collector.deepen(snapshot, [self.public.btc[0]["instrument_name"]])
        self.assertEqual(before, len(self.public.calls))
        self.assertEqual({}, deep["quotes"])
        self.assertEqual("COLLECTION_DEADLINE", deep["coverage"]["failures"][-1]["code"])

    def test_missing_collection_context_cannot_restart_an_old_snapshot_deadline(self):
        snapshot = self.collector.fetch_snapshot("BTC")
        self.collector._deadlines.clear()
        before = len(self.public.calls)
        result = self.collector.deepen(snapshot, [self.public.btc[0]["instrument_name"]])
        self.assertEqual(before, len(self.public.calls))
        self.assertEqual({}, result["quotes"])
        self.assertEqual("COLLECTION_DEADLINE", result["coverage"]["failures"][-1]["code"])

    def test_testnet_provenance_is_explicit(self):
        collector = self.make_collector(base_url="https://test.deribit.com")
        source = collector.fetch_snapshot("BTC")["source"]
        self.assertEqual("testnet", source["environment"])
        self.assertEqual("DERIBIT_TESTNET_PUBLIC", source["provider"])
        self.assertIn("not production", source["notice"])

    def test_rate_limit_retry_is_bounded_and_keeps_shared_pacing(self):
        original = self.public
        errors = 2

        def transport(url, params, timeout):
            nonlocal errors
            if url.endswith("get_order_book") and errors:
                errors -= 1
                original.calls.append(("get_order_book", dict(params), self.clock.monotonic(), timeout))
                return {"error": {"code": 10028, "message": "too_many_requests"}}
            return original(url, params, timeout)

        self.collector.transport = transport
        snapshot = self.collector.fetch_snapshot("BTC")
        result = self.collector.deepen(snapshot, [self.public.btc[0]["instrument_name"]])
        self.assertEqual(3, sum(row[0] == "get_order_book" for row in self.public.calls))
        self.assertEqual(1, result["coverage"]["deepened_count"])
        self.assertIn(1, self.clock.sleeps)
        self.assertIn(2, self.clock.sleeps)

    def test_concurrent_fetches_share_one_discovery_and_return_detached_objects(self):
        barrier = threading.Barrier(5)

        def fetch(_):
            barrier.wait()
            return self.collector.fetch_snapshot("BTC")

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(fetch, range(5)))
        self.assertEqual(8, len(self.public.calls))
        self.assertEqual(1, len({result["snapshot_id"] for result in results}))
        results[0]["instruments"].clear()
        self.assertTrue(results[1]["instruments"])

    def test_public_boundaries_reject_unapproved_hosts_assets_and_unbounded_exact_names(self):
        with self.assertRaises(ValueError):
            self.make_collector(base_url="https://example.com")
        with self.assertRaises(ValueError):
            self.collector.fetch_snapshot("SOL")
        with self.assertRaises(ValueError):
            self.collector.deepen({}, "BTC")
        with self.assertRaises(ValueError):
            self.collector.deepen({}, [f"BTC_USDC-{i}" for i in range(121)])
        with self.assertRaises(ValueError):
            self.collector.deepen({}, ["../../private"])


if __name__ == "__main__":
    unittest.main()
