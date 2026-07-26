"""Multi-leg structure payoff, risk bounds and position greeks.

The arithmetic here replaces branches that were previously written out per
structure type, so the tests are written against structures the old code could
not express — put spreads, condors, ratios — as well as the two it could. A
change that quietly reintroduces an upside-only or short-only assumption breaks
one of these rather than surviving until someone trades a put.
"""

from __future__ import annotations

import unittest

from crypto_options_report.structures import (
    CALL,
    PUT,
    Leg,
    Structure,
    build_structure,
    call_credit_spread,
    naked_short_call,
)


def _structure(structure_type: str, *legs: Leg, contract_size: float = 1.0) -> Structure:
    return Structure(
        structure_type=structure_type, legs=tuple(legs), contract_size=contract_size
    )


def _short_put_spread(short: float, long: float) -> Structure:
    return _structure(
        "put_credit_spread",
        Leg(option_type=PUT, strike=short, quantity=-1.0),
        Leg(option_type=PUT, strike=long, quantity=1.0),
    )


def _iron_condor() -> Structure:
    return _structure(
        "iron_condor",
        Leg(option_type=PUT, strike=85_000.0, quantity=1.0),
        Leg(option_type=PUT, strike=90_000.0, quantity=-1.0),
        Leg(option_type=CALL, strike=110_000.0, quantity=-1.0),
        Leg(option_type=CALL, strike=115_000.0, quantity=1.0),
    )


class LegTests(unittest.TestCase):
    def test_quantity_carries_direction_so_no_short_flag_is_needed(self) -> None:
        long_call = Leg(option_type=CALL, strike=100_000.0, quantity=1.0)
        short_call = Leg(option_type=CALL, strike=100_000.0, quantity=-1.0)

        self.assertEqual(long_call.value_at(110_000.0), 10_000.0)
        self.assertEqual(short_call.value_at(110_000.0), -10_000.0)
        self.assertEqual(long_call.to_dict()["direction"], "long")
        self.assertEqual(short_call.to_dict()["direction"], "short")

    def test_put_intrinsic_is_the_mirror_of_a_call(self) -> None:
        put = Leg(option_type=PUT, strike=100_000.0, quantity=1.0)

        self.assertEqual(put.intrinsic_at(90_000.0), 10_000.0)
        self.assertEqual(put.intrinsic_at(110_000.0), 0.0)

    def test_a_zero_quantity_leg_is_rejected_rather_than_ignored(self) -> None:
        with self.assertRaises(ValueError):
            Leg(option_type=CALL, strike=100_000.0, quantity=0.0)

    def test_an_unknown_option_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Leg(option_type="future", strike=100_000.0, quantity=1.0)


class TerminalPayoffTests(unittest.TestCase):
    def test_naked_short_call_owes_intrinsic_above_the_strike(self) -> None:
        structure = naked_short_call(strike=110_000.0)

        self.assertEqual(structure.amount_owed_at(105_000.0), 0.0)
        self.assertEqual(structure.amount_owed_at(120_000.0), 10_000.0)

    def test_call_credit_spread_obligation_caps_at_the_width(self) -> None:
        structure = call_credit_spread(short_strike=110_000.0, long_strike=120_000.0)

        self.assertEqual(structure.amount_owed_at(115_000.0), 5_000.0)
        self.assertEqual(structure.amount_owed_at(120_000.0), 10_000.0)
        self.assertEqual(structure.amount_owed_at(500_000.0), 10_000.0)

    def test_put_credit_spread_obligation_is_on_the_downside(self) -> None:
        structure = _short_put_spread(short=90_000.0, long=80_000.0)

        self.assertEqual(structure.amount_owed_at(95_000.0), 0.0)
        self.assertEqual(structure.amount_owed_at(85_000.0), 5_000.0)
        self.assertEqual(structure.amount_owed_at(0.0), 10_000.0)

    def test_iron_condor_owes_nothing_between_its_short_strikes(self) -> None:
        structure = _iron_condor()

        self.assertEqual(structure.amount_owed_at(100_000.0), 0.0)
        self.assertEqual(structure.amount_owed_at(112_000.0), 2_000.0)
        self.assertEqual(structure.amount_owed_at(88_000.0), 2_000.0)

    def test_contract_size_scales_the_whole_position(self) -> None:
        structure = call_credit_spread(
            short_strike=110_000.0, long_strike=120_000.0, contract_size=0.5
        )

        self.assertEqual(structure.amount_owed_at(500_000.0), 5_000.0)


class RiskBoundTests(unittest.TestCase):
    """Unboundedness is an answer, not a missing value."""

    def test_naked_short_call_reports_no_maximum_loss(self) -> None:
        profile = naked_short_call(strike=110_000.0).risk_profile(entry_cash=500.0)

        self.assertIsNone(profile.max_loss)
        self.assertIs(profile.loss_is_bounded, False)
        self.assertEqual(profile.max_profit, 500.0)
        self.assertIs(profile.profit_is_bounded, True)

    def test_call_credit_spread_max_loss_is_width_minus_credit(self) -> None:
        profile = call_credit_spread(
            short_strike=110_000.0, long_strike=120_000.0
        ).risk_profile(entry_cash=2_400.0)

        self.assertEqual(profile.max_loss, 7_600.0)
        self.assertEqual(profile.max_profit, 2_400.0)
        self.assertIs(profile.loss_is_bounded, True)

    def test_put_credit_spread_loss_is_bounded_by_the_spot_floor(self) -> None:
        profile = _short_put_spread(short=90_000.0, long=80_000.0).risk_profile(
            entry_cash=2_000.0
        )

        self.assertEqual(profile.max_loss, 8_000.0)
        self.assertIs(profile.loss_is_bounded, True)

    def test_iron_condor_max_loss_is_the_wider_wing_minus_credit(self) -> None:
        profile = _iron_condor().risk_profile(entry_cash=1_500.0)

        self.assertEqual(profile.max_loss, 3_500.0)
        self.assertEqual(profile.max_profit, 1_500.0)

    def test_a_ratio_spread_short_more_calls_than_it_is_long_is_unbounded(self) -> None:
        structure = _structure(
            "call_ratio_spread",
            Leg(option_type=CALL, strike=110_000.0, quantity=1.0),
            Leg(option_type=CALL, strike=120_000.0, quantity=-2.0),
        )

        profile = structure.risk_profile(entry_cash=300.0)

        self.assertIs(profile.loss_is_bounded, False)
        self.assertIsNone(profile.max_loss)
        self.assertEqual(profile.upside_slope, -1.0)

    def test_a_long_structure_has_bounded_loss_and_unbounded_profit(self) -> None:
        structure = _structure(
            "long_call", Leg(option_type=CALL, strike=110_000.0, quantity=1.0)
        )

        profile = structure.risk_profile(entry_cash=-500.0)

        self.assertIs(profile.loss_is_bounded, True)
        self.assertEqual(profile.max_loss, 500.0)
        self.assertIs(profile.profit_is_bounded, False)
        self.assertIsNone(profile.max_profit)


class BreakevenTests(unittest.TestCase):
    def test_short_call_breakeven_is_strike_plus_credit(self) -> None:
        profile = naked_short_call(strike=110_000.0).risk_profile(entry_cash=500.0)

        self.assertEqual(profile.breakevens, (110_500.0,))

    def test_credit_spread_breakeven_sits_inside_the_wings(self) -> None:
        profile = call_credit_spread(
            short_strike=110_000.0, long_strike=120_000.0
        ).risk_profile(entry_cash=2_400.0)

        self.assertEqual(profile.breakevens, (112_400.0,))

    def test_iron_condor_has_a_breakeven_on_each_side(self) -> None:
        profile = _iron_condor().risk_profile(entry_cash=1_500.0)

        self.assertEqual(profile.breakevens, (88_500.0, 111_500.0))


class PositionGreekTests(unittest.TestCase):
    """Signed aggregation removes the hand-written negation at each call site."""

    def test_greeks_are_summed_with_the_leg_direction(self) -> None:
        structure = call_credit_spread(
            short_strike=110_000.0,
            long_strike=120_000.0,
            short_instrument="short-leg",
            long_instrument="long-leg",
        )

        greeks = structure.position_greeks(
            {
                "short-leg": {"delta": 0.12, "gamma": 1e-6, "theta": -70.0, "vega": 48.0},
                "long-leg": {"delta": 0.05, "gamma": 5e-7, "theta": -30.0, "vega": 22.0},
            }
        )

        self.assertEqual(greeks["status"], "aggregated")
        # Short the near leg, long the far one: the position is short vega and
        # collects theta, with no caller-side sign flip involved.
        self.assertAlmostEqual(greeks["delta"], -0.07, places=8)
        self.assertAlmostEqual(greeks["vega"], -26.0, places=8)
        self.assertAlmostEqual(greeks["theta"], 40.0, places=8)

    def test_a_missing_leg_greek_blocks_rather_than_counting_as_zero(self) -> None:
        structure = call_credit_spread(
            short_strike=110_000.0,
            long_strike=120_000.0,
            short_instrument="short-leg",
            long_instrument="long-leg",
        )

        greeks = structure.position_greeks(
            {"short-leg": {"delta": 0.12, "gamma": 1e-6, "theta": -70.0, "vega": 48.0}}
        )

        self.assertEqual(greeks["status"], "blocked")
        self.assertEqual(greeks["reason_code"], "MISSING_LEG_GREEKS")
        self.assertIsNone(greeks["vega"])
        self.assertIn("long-leg", greeks["missing"])


class MultiExpiryTests(unittest.TestCase):
    """A calendar has no single terminal payoff, and must refuse to pretend."""

    def test_a_calendar_is_flagged_as_multi_expiry(self) -> None:
        structure = build_structure(
            structure_type="call_calendar",
            legs=[
                {
                    "option_type": CALL,
                    "strike": 110_000.0,
                    "quantity": -1.0,
                    "expiry_date": "2026-08-28",
                },
                {
                    "option_type": CALL,
                    "strike": 110_000.0,
                    "quantity": 1.0,
                    "expiry_date": "2026-09-25",
                },
            ],
        )

        self.assertIs(structure.is_multi_expiry, True)
        self.assertIsNone(structure.expiry_date)

    def test_terminal_evaluation_of_a_calendar_is_refused(self) -> None:
        structure = build_structure(
            structure_type="call_calendar",
            legs=[
                {
                    "option_type": CALL,
                    "strike": 110_000.0,
                    "quantity": -1.0,
                    "expiry_date": "2026-08-28",
                },
                {
                    "option_type": CALL,
                    "strike": 110_000.0,
                    "quantity": 1.0,
                    "expiry_date": "2026-09-25",
                },
            ],
        )

        for operation in (
            lambda: structure.value_at(110_000.0),
            lambda: structure.risk_profile(entry_cash=100.0),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError) as caught:
                    operation()
                self.assertIn("multi-expiry", str(caught.exception))


class ConstructionTests(unittest.TestCase):
    def test_a_spread_with_an_inverted_long_strike_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            call_credit_spread(short_strike=120_000.0, long_strike=110_000.0)

    def test_an_empty_structure_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_structure(structure_type="nothing", legs=[])

    def test_structure_serializes_its_shape_for_the_record(self) -> None:
        payload = call_credit_spread(
            short_strike=110_000.0, long_strike=120_000.0, expiry_date="2026-08-28"
        ).to_dict()

        self.assertEqual(payload["leg_count"], 2)
        self.assertEqual(payload["expiry_date"], "2026-08-28")
        self.assertEqual(payload["upside_slope"], 0.0)
        self.assertEqual(
            [leg["direction"] for leg in payload["legs"]], ["short", "long"]
        )


if __name__ == "__main__":
    unittest.main()
