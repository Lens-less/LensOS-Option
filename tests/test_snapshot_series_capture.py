"""Capture has to cover both sides of the chain, and has to be repeatable.

Two collector defects blocked the expanded universe from ever seeing real data.
The selection policy filtered to calls, which was coherent while the analysis
was call-only but silently starved the put tables afterwards — a live two-sided
chain would have produced a one-sided report with nothing in the artifact saying
why. And the ticker budget was smaller than one expiry's two-sided quota, so
even an unfiltered policy could not have filled both sides of a single expiry.

The second half of the file covers the series capture, which exists because the
signal validation needs many captures over time and a fixed `--output` path
would have each run overwrite the last.
"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_options_report.cli import (
    EXIT_OK,
    EXIT_QUALITY_BLOCKED,
    _cmd_pull_snapshot,
    _snapshot_output_path,
)
from crypto_options_report.market_data import (
    DEFAULT_QUALITY_LIMITS,
    DEFAULT_TICKER_REQUEST_BUDGET,
    _select_research_summaries,
)

CAPTURED_AT = "2026-07-26T00:00:00Z"
SPOT = 100_000.0


def _summary(strike: float, option_type: str, expiry_token: str) -> dict:
    suffix = "C" if option_type == "call" else "P"
    price = 0.01 if option_type == "call" else 0.012
    return {
        "instrument_name": f"BTC-{expiry_token}-{int(strike)}-{suffix}",
        "bid_price": price,
        "ask_price": price * 1.05,
        "mark_price": price,
        "underlying_price": SPOT,
        "open_interest": 100.0,
    }


def _chain(expiry_tokens: tuple[str, ...] = ("14AUG26", "28AUG26")) -> list[dict]:
    rows = []
    for token in expiry_tokens:
        for offset in range(12):
            rows.append(_summary(105_000 + offset * 2_000, "call", token))
            rows.append(_summary(95_000 - offset * 2_000, "put", token))
    return rows


class TwoSidedSelectionTests(unittest.TestCase):
    def test_both_option_types_are_selected(self) -> None:
        selected, policy = _select_research_summaries(
            _chain(),
            captured_at=CAPTURED_AT,
            instrument_limit=DEFAULT_TICKER_REQUEST_BUDGET,
        )

        types = {row["instrument_name"].rsplit("-", 1)[1] for row in selected}
        self.assertEqual(types, {"C", "P"})
        self.assertEqual(policy["preferred_option_types"], ["call", "put"])
        self.assertEqual(policy["stratification"], "expiry_and_option_type")
        self.assertIs(policy["fallback_used"], False)

    def test_each_side_reaches_the_per_expiry_quota(self) -> None:
        minimum = int(DEFAULT_QUALITY_LIMITS["min_valid_quotes_per_expiry"])

        selected, _ = _select_research_summaries(
            _chain(("14AUG26",)),
            captured_at=CAPTURED_AT,
            instrument_limit=DEFAULT_TICKER_REQUEST_BUDGET,
        )

        calls = [row for row in selected if row["instrument_name"].endswith("-C")]
        puts = [row for row in selected if row["instrument_name"].endswith("-P")]
        self.assertGreaterEqual(len(calls), minimum)
        self.assertGreaterEqual(len(puts), minimum)

    def test_non_fallback_selection_never_emits_a_one_sided_expiry(self) -> None:
        minimum = int(DEFAULT_QUALITY_LIMITS["min_valid_quotes_per_expiry"])
        chain = _chain(("14AUG26",))
        chain.extend(
            _summary(105_000 + offset * 2_000, "call", "28AUG26")
            for offset in range(minimum + 2)
        )

        selected, policy = _select_research_summaries(
            chain,
            captured_at=CAPTURED_AT,
            instrument_limit=DEFAULT_TICKER_REQUEST_BUDGET,
        )

        self.assertFalse(policy["fallback_used"])
        selected_expiries = {
            row["instrument_name"].split("-")[1] for row in selected
        }
        self.assertEqual({"14AUG26"}, selected_expiries)

    def test_the_budget_covers_a_two_sided_expiry(self) -> None:
        """At the old budget of 20 this quota could not be met at all."""
        minimum = int(DEFAULT_QUALITY_LIMITS["min_valid_quotes_per_expiry"])

        self.assertGreaterEqual(DEFAULT_TICKER_REQUEST_BUDGET, 2 * minimum)

    def test_put_strikes_are_chosen_out_of_the_money(self) -> None:
        """The call band applied to puts would select deep in-the-money strikes."""
        selected, policy = _select_research_summaries(
            _chain(("14AUG26",)),
            captured_at=CAPTURED_AT,
            instrument_limit=DEFAULT_TICKER_REQUEST_BUDGET,
        )

        puts = [row for row in selected if row["instrument_name"].endswith("-P")]
        self.assertTrue(puts)
        for row in puts:
            strike = float(row["instrument_name"].split("-")[2])
            with self.subTest(instrument=row["instrument_name"]):
                self.assertLess(strike, SPOT)
        self.assertEqual(policy["preferred_put_moneyness"], [0.7, 1.0])

    def test_budget_fill_never_reintroduces_adverse_moneyness_tails(self) -> None:
        chain = _chain()
        for token in ("14AUG26", "28AUG26"):
            for strike in range(70_000, 100_000, 5_000):
                chain.append(_summary(strike, "call", token))
            for strike in range(105_000, 135_000, 5_000):
                chain.append(_summary(strike, "put", token))

        selected, policy = _select_research_summaries(
            chain,
            captured_at=CAPTURED_AT,
            instrument_limit=DEFAULT_TICKER_REQUEST_BUDGET,
        )

        self.assertFalse(policy["fallback_used"])
        self.assertLess(len(selected), DEFAULT_TICKER_REQUEST_BUDGET)
        for row in selected:
            strike = float(row["instrument_name"].split("-")[2])
            option_type = row["instrument_name"].rsplit("-", 1)[1]
            with self.subTest(instrument=row["instrument_name"]):
                if option_type == "C":
                    self.assertGreaterEqual(strike / SPOT, 1.0)
                    self.assertLessEqual(strike / SPOT, 1.3)
                else:
                    self.assertGreaterEqual(strike / SPOT, 0.7)
                    self.assertLessEqual(strike / SPOT, 1.0)


class SeriesCaptureNamingTests(unittest.TestCase):
    def _args(self, **kwargs) -> argparse.Namespace:
        base = {"output": None, "output_dir": None}
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_explicit_output_is_used_verbatim(self) -> None:
        path = _snapshot_output_path(
            self._args(output="artifacts/one.json"),
            {"captured_at": CAPTURED_AT, "currency": "BTC"},
        )

        self.assertEqual(path, "artifacts/one.json")

    def test_series_capture_is_named_by_capture_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _snapshot_output_path(
                self._args(output_dir=directory),
                {"captured_at": CAPTURED_AT, "currency": "BTC"},
            )

            self.assertEqual(
                Path(path).name, "btc-chain-20260726T000000.json"
            )
            self.assertTrue(Path(path).parent.is_dir())

    def test_two_captures_at_different_times_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = _snapshot_output_path(
                self._args(output_dir=directory),
                {"captured_at": "2026-07-26T00:00:00Z", "currency": "BTC"},
            )
            second = _snapshot_output_path(
                self._args(output_dir=directory),
                {"captured_at": "2026-07-27T00:00:00Z", "currency": "BTC"},
            )

            self.assertNotEqual(first, second)

    def test_the_directory_is_created_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "series"

            path = _snapshot_output_path(
                self._args(output_dir=str(target)),
                {"captured_at": CAPTURED_AT, "currency": "ETH"},
            )

            self.assertTrue(target.is_dir())
            self.assertEqual(Path(path).name, "eth-chain-20260726T000000.json")


class PullSnapshotThresholdTests(unittest.TestCase):
    @staticmethod
    def _write_stub_snapshot(path: str, payload: dict) -> Path:
        del payload
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        return target

    def _args(self, **kwargs) -> argparse.Namespace:
        base = {
            "currency": "BTC",
            "deribit_base_url": "https://www.deribit.com",
            "instrument_limit": DEFAULT_TICKER_REQUEST_BUDGET,
            "output": None,
            "output_dir": None,
            "compact": True,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_partial_snapshot_with_fetch_errors_blocks_capture(self) -> None:
        snapshot = {
            "captured_at": CAPTURED_AT,
            "source": "live_public_deribit",
            "rows": [{"instrument_name": f"BTC-14AUG26-{i}-C"} for i in range(12)],
            "fetch_errors": ["ticker: upstream timeout"],
            "feeds": {"option_chain": {}},
            "instrument_metadata_count": 12,
        }

        with tempfile.TemporaryDirectory() as directory:
            args = self._args(output_dir=directory)
            with (
                patch(
                    "crypto_options_report.cli.fetch_deribit_option_chain_snapshot",
                    return_value=snapshot,
                ),
                patch(
                    "crypto_options_report.cli.write_snapshot_fixture",
                    side_effect=self._write_stub_snapshot,
                ),
            ):
                result = _cmd_pull_snapshot(args)

        self.assertEqual(EXIT_QUALITY_BLOCKED, result)

    def test_fetch_errors_above_partial_threshold_keep_capture_green(self) -> None:
        minimum_rows = 58
        snapshot = {
            "captured_at": CAPTURED_AT,
            "source": "live_public_deribit",
            "rows": [
                {"instrument_name": f"BTC-14AUG26-{i}-C"} for i in range(minimum_rows)
            ],
            "fetch_errors": ["ticker: upstream timeout"],
            "feeds": {"option_chain": {}},
            "instrument_metadata_count": minimum_rows,
        }

        with tempfile.TemporaryDirectory() as directory:
            args = self._args(output_dir=directory)
            with (
                patch(
                    "crypto_options_report.cli.fetch_deribit_option_chain_snapshot",
                    return_value=snapshot,
                ),
                patch(
                    "crypto_options_report.cli.write_snapshot_fixture",
                    side_effect=self._write_stub_snapshot,
                ),
            ):
                result = _cmd_pull_snapshot(args)

        self.assertEqual(EXIT_OK, result)


if __name__ == "__main__":
    unittest.main()
