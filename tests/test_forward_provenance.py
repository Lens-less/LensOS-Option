"""The forward and the spot index are not interchangeable, and must not be conflated.

Deribit's option ticker reports `underlying_price` as the forward for that
expiry and `index_price` as spot. The normalizer used to fall through from one
to the other in a single expression, so a chain missing the forward was priced
off spot with nothing in the output saying so. That substitution shifts every
strike's log-moneyness, drags the fitted smile below the marks, and surfaces as
richness that is an artefact of the missing field rather than a property of the
market — in a trending crypto market the basis behind it runs to double-digit
annualized rates.

The fallback is still allowed: a smile fitted off spot beats no smile. What is
no longer allowed is the fallback being invisible.
"""

from __future__ import annotations

import unittest

from crypto_options_report.market_data import (
    normalize_market_snapshot,
    parse_timestamp_ms,
)

CAPTURED_AT = "2026-07-07T00:01:00Z"


def _snapshot(*, ticker_extra: dict, summary_extra: dict | None = None) -> dict:
    timestamp_ms = parse_timestamp_ms(CAPTURED_AT)
    summary = {
        "instrument_name": "BTC-25JUL26-115000-C",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "bid_price": 300.0,
        "ask_price": 320.0,
        "mid_price": 310.0,
        "mark_price": 310.0,
        "open_interest": 50.0,
        "creation_timestamp": timestamp_ms,
    }
    summary.update(summary_extra or {})
    ticker = {
        "instrument_name": "BTC-25JUL26-115000-C",
        "iv_unit": "percent_points",
        "timestamp": timestamp_ms,
        "best_bid_price": 300.0,
        "best_ask_price": 320.0,
        "best_bid_amount": 5.0,
        "best_ask_amount": 5.0,
        "mark_price": 310.0,
        "bid_iv": 53.0,
        "ask_iv": 54.0,
        "mark_iv": 53.5,
        "open_interest": 50.0,
    }
    ticker.update(ticker_extra)
    return {
        "captured_at": CAPTURED_AT,
        "source": "test:forward-provenance",
        "currency": "BTC",
        "rows": [
            {
                "instrument_name": "BTC-25JUL26-115000-C",
                "summary": summary,
                "ticker": ticker,
            }
        ],
    }


def _quote(**kwargs) -> dict:
    normalized = normalize_market_snapshot(
        _snapshot(**kwargs), now_ms=parse_timestamp_ms(CAPTURED_AT)
    )
    return normalized["quotes"][0]


class ForwardProvenanceTests(unittest.TestCase):
    def test_a_declared_forward_is_used_and_labelled(self) -> None:
        quote = _quote(
            ticker_extra={"underlying_price": 101_500.0, "index_price": 100_000.0}
        )

        self.assertEqual(quote["underlying_price"], 101_500.0)
        self.assertEqual(quote["forward_price"], 101_500.0)
        self.assertEqual(quote["index_price"], 100_000.0)
        self.assertEqual(quote["underlying_price_source"], "option_forward")

    def test_the_basis_between_forward_and_spot_is_computed(self) -> None:
        quote = _quote(
            ticker_extra={"underlying_price": 101_500.0, "index_price": 100_000.0}
        )

        self.assertAlmostEqual(quote["forward_basis"], 0.015, places=8)

    def test_spot_substitution_is_recorded_rather_than_silent(self) -> None:
        quote = _quote(ticker_extra={"index_price": 100_000.0})

        self.assertEqual(quote["underlying_price"], 100_000.0)
        self.assertIsNone(quote["forward_price"])
        self.assertEqual(quote["underlying_price_source"], "index_spot_fallback")
        # With no forward observed there is no basis to report, and a zero here
        # would assert the very thing that is unknown.
        self.assertIsNone(quote["forward_basis"])

    def test_a_summary_forward_still_counts_as_a_forward(self) -> None:
        quote = _quote(
            ticker_extra={"index_price": 100_000.0},
            summary_extra={"underlying_price": 101_500.0},
        )

        self.assertEqual(quote["underlying_price_source"], "option_forward")
        self.assertEqual(quote["forward_price"], 101_500.0)

    def test_neither_price_available_is_unavailable_not_zero(self) -> None:
        quote = _quote(ticker_extra={})

        self.assertIsNone(quote["underlying_price"])
        self.assertEqual(quote["underlying_price_source"], "unavailable")
        self.assertIn("INVALID_UNDERLYING_PRICE", quote["quality_flags"])


if __name__ == "__main__":
    unittest.main()
