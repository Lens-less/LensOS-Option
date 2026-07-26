"""The two filters that decide whether a defined-risk structure can exist at all.

On a live chain both call spreads and iron condors came out at zero eligible.
Neither was a market fact:

* the width window was written in absolute dollars, so the same configuration
  described a 7.8%-23.3% search at one price level and 4.2%-12.5% at another,
  and BTC covered both inside the sample this product measures against;
* the protective leg was gated on its own quote-spread ratio, the same gate the
  sell leg gets. A deep out-of-the-money wing quoted 0.0003/0.0004 shows a 28%
  ratio because its premium is tiny, and crossing it costs about three dollars.
  Rejecting a structure that bounds a ten-thousand-dollar loss on that basis
  threw away every defined-risk candidate — and, since a condor needs a wing on
  both sides, every condor.
"""

from __future__ import annotations

import unittest

from crypto_options_report.surface import (
    DEFAULT_SURFACE_LIMITS,
    _protective_leg_cost,
    _spread_width_bounds,
)


class WidthScalesWithPriceTests(unittest.TestCase):
    def test_the_window_is_a_fraction_of_the_underlying(self) -> None:
        low = _spread_width_bounds(64_000.0)
        high = _spread_width_bounds(128_000.0)

        assert low is not None and high is not None
        # Twice the price, twice the window: the search keeps its shape.
        self.assertAlmostEqual(high["min"], low["min"] * 2, places=6)
        self.assertAlmostEqual(high["max"], low["max"] * 2, places=6)

    def test_the_resolved_dollar_bounds_are_published(self) -> None:
        bounds = _spread_width_bounds(64_000.0)

        assert bounds is not None
        self.assertEqual(
            bounds["min_fraction"],
            DEFAULT_SURFACE_LIMITS["min_spread_width_fraction"],
        )
        self.assertEqual(bounds["underlying_price"], 64_000.0)
        self.assertAlmostEqual(
            bounds["min"],
            64_000.0 * DEFAULT_SURFACE_LIMITS["min_spread_width_fraction"],
            places=6,
        )

    def test_an_unusable_underlying_yields_no_bounds_rather_than_zero(self) -> None:
        # A zero-width window would silently pass every pair.
        for value in (None, 0.0, -1.0, "64000", True):
            with self.subTest(value=value):
                self.assertIsNone(_spread_width_bounds(value))


class ProtectiveLegCostTests(unittest.TestCase):
    """A wing is priced by what crossing it costs, not by its own ratio."""

    def _leg(self, *, bid: float, ask: float, ratio: float | None = None) -> dict:
        return {
            "market_bid": bid,
            "market_ask": ask,
            "spread_ratio": ratio,
        }

    def test_a_wide_but_cheap_wing_is_accepted(self) -> None:
        # The real case: 0.0003/0.0004 is a 28% quote spread and costs 0.00005
        # to cross, against a credit of 0.0028. That is under two percent.
        result = _protective_leg_cost(
            self._leg(bid=0.0003, ask=0.0004, ratio=0.286), net_credit=0.0028
        )

        self.assertEqual(result["reason_codes"], [])
        self.assertLess(result["detail"]["cost_share_of_credit"], 0.02)

    def test_a_wing_that_eats_the_credit_is_rejected(self) -> None:
        result = _protective_leg_cost(
            self._leg(bid=0.0010, ask=0.0030, ratio=1.0), net_credit=0.0020
        )

        self.assertIn("BUY_LEG_COST_EXCEEDS_CREDIT_SHARE", result["reason_codes"])

    def test_an_implausible_quote_is_still_caught(self) -> None:
        """The ratio gate survives as data sanity, far above the executable one."""
        result = _protective_leg_cost(
            self._leg(bid=0.0001, ask=0.0100, ratio=1.96), net_credit=1.0
        )

        self.assertIn("BUY_LEG_QUOTE_IMPLAUSIBLE", result["reason_codes"])

    def test_a_missing_quote_blocks_rather_than_costing_zero(self) -> None:
        result = _protective_leg_cost(
            {"market_bid": None, "market_ask": 0.0004}, net_credit=0.0028
        )

        self.assertIn("BUY_LEG_QUOTE_UNAVAILABLE", result["reason_codes"])
        self.assertEqual(result["detail"]["status"], "unavailable")

    def test_a_non_positive_credit_makes_the_share_incomparable(self) -> None:
        result = _protective_leg_cost(
            self._leg(bid=0.0003, ask=0.0004), net_credit=0.0
        )

        self.assertIn("BUY_LEG_COST_NOT_COMPARABLE", result["reason_codes"])
        self.assertIsNone(result["detail"]["cost_share_of_credit"])

    def test_the_measurement_states_its_own_basis(self) -> None:
        result = _protective_leg_cost(
            self._leg(bid=0.0003, ask=0.0004), net_credit=0.0028
        )

        self.assertEqual(result["detail"]["basis"], "half_spread_over_net_credit")
        self.assertEqual(
            result["detail"]["max_cost_share"],
            DEFAULT_SURFACE_LIMITS["max_protective_leg_cost_ratio"],
        )

    def test_the_sell_side_gate_is_untouched(self) -> None:
        """The credit is taken at the bid, so there the ratio *is* the cost."""
        self.assertEqual(DEFAULT_SURFACE_LIMITS["max_spread_ratio"], 0.25)
        self.assertGreater(
            DEFAULT_SURFACE_LIMITS["max_quote_spread_ratio_hard"],
            DEFAULT_SURFACE_LIMITS["max_spread_ratio"],
        )


if __name__ == "__main__":
    unittest.main()
