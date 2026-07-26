"""Combining candidates: aggregation, and the two places aggregation lies.

Every risk figure the product produced was per candidate, which is the wrong
unit for deciding what to put on. Two short call spreads a strike apart on one
expiry are very nearly the same trade twice, and a per-candidate view shows them
as two moderate positions rather than one concentrated bet.

The tests below pin the aggregation arithmetic and, more importantly, the two
refusals: a joint maximum loss across expiries, and a net vega that hides its
term-structure composition.
"""

from __future__ import annotations

import unittest

from crypto_options_report.combination_risk import (
    COMBINATION_RISK_SCHEMA_VERSION,
    MULTI_EXPIRY_BOOK,
    build_combination_risk_report,
)

EXPIRY = "2026-08-28"
LATER = "2026-09-25"


def _spread(
    candidate_id: str,
    *,
    short: float,
    long: float,
    option_type: str = "call",
    credit: float = 2_000.0,
    expiry: str = EXPIRY,
    vega: float = -26.0,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "structure_type": f"{option_type}_credit_spread",
        "expiry_date": expiry,
        "underlying_price": 100_000.0,
        "premium_unit": "quote_currency",
        "net_credit": credit,
        "structure_legs": [
            {
                "option_type": option_type,
                "strike": short,
                "quantity": -1.0,
                "expiry_date": expiry,
            },
            {
                "option_type": option_type,
                "strike": long,
                "quantity": 1.0,
                "expiry_date": expiry,
            },
        ],
        "position_greeks": {
            "status": "aggregated",
            "delta": -0.07,
            "gamma": -5e-7,
            "theta": 40.0,
            "vega": vega,
        },
    }


def _naked(candidate_id: str, *, strike: float = 115_000.0) -> dict:
    return {
        "candidate_id": candidate_id,
        "structure_type": "naked_short_call",
        "expiry_date": EXPIRY,
        "underlying_price": 100_000.0,
        "premium_unit": "quote_currency",
        "market_bid": 500.0,
        "structure_legs": [
            {
                "option_type": "call",
                "strike": strike,
                "quantity": -1.0,
                "expiry_date": EXPIRY,
            }
        ],
        "position_greeks": {
            "status": "aggregated",
            "delta": -0.11,
            "gamma": -1e-6,
            "theta": 70.0,
            "vega": -48.0,
        },
    }


def _report(candidates: list[dict]) -> dict:
    return build_combination_risk_report(
        candidates=candidates, generated_at="2026-07-26T00:00:00Z"
    )


class SingleExpiryBookTests(unittest.TestCase):
    def test_two_sided_book_has_a_joint_payoff_not_a_sum(self) -> None:
        report = _report(
            [
                _spread("call-side", short=110_000.0, long=120_000.0, credit=2_000.0),
                _spread(
                    "put-side",
                    short=90_000.0,
                    long=80_000.0,
                    option_type="put",
                    credit=1_800.0,
                ),
            ]
        )

        joint = report["book"]["joint_terminal_risk"]
        self.assertEqual(joint["status"], "evaluated")
        # Only one side can finish in obligation, so the joint worst case is the
        # wider wing minus the *total* credit: 10_000 - 3_800.
        self.assertEqual(joint["max_loss_usdc"], 6_200.0)
        # Adding the two standalone worst cases (8_000 and 8_200) claims 16_200
        # of risk, most of which cannot occur at once.
        self.assertEqual(report["book"]["max_loss_upper_bound_usdc"], 16_200.0)
        self.assertLess(
            joint["max_loss_usdc"], report["book"]["max_loss_upper_bound_usdc"]
        )

    def test_the_upper_bound_declares_that_it_is_a_bound(self) -> None:
        report = _report(
            [
                _spread("a", short=110_000.0, long=120_000.0),
                _spread("b", short=115_000.0, long=125_000.0),
            ]
        )

        self.assertEqual(
            report["book"]["max_loss_upper_bound_basis"],
            "sum_of_independent_member_worst_cases",
        )

    def test_greeks_are_netted_across_members(self) -> None:
        report = _report(
            [
                _spread("a", short=110_000.0, long=120_000.0, vega=-26.0),
                _spread("b", short=115_000.0, long=125_000.0, vega=-14.0),
            ]
        )

        greeks = report["book"]["greeks"]
        self.assertEqual(greeks["status"], "aggregated")
        self.assertAlmostEqual(greeks["net"]["vega"], -40.0, places=8)
        self.assertAlmostEqual(greeks["net"]["theta"], 80.0, places=8)


class MultiExpiryRefusalTests(unittest.TestCase):
    """A joint terminal payoff needs one expiry, so it is refused, not faked."""

    def test_a_book_spanning_expiries_refuses_a_joint_max_loss(self) -> None:
        report = _report(
            [
                _spread("august", short=110_000.0, long=120_000.0),
                _spread("september", short=110_000.0, long=120_000.0, expiry=LATER),
            ]
        )

        joint = report["book"]["joint_terminal_risk"]
        self.assertEqual(joint["status"], "not_jointly_evaluable")
        self.assertEqual(joint["reason_code"], MULTI_EXPIRY_BOOK)
        self.assertIsNone(joint["max_loss_usdc"])
        # The bound is still available, clearly labelled as a bound.
        self.assertEqual(report["book"]["max_loss_upper_bound_usdc"], 16_000.0)

    def test_net_vega_is_published_beside_its_per_expiry_composition(self) -> None:
        report = _report(
            [
                _spread("august", short=110_000.0, long=120_000.0, vega=-30.0),
                _spread(
                    "september",
                    short=110_000.0,
                    long=120_000.0,
                    expiry=LATER,
                    vega=20.0,
                ),
            ]
        )

        greeks = report["book"]["greeks"]
        self.assertAlmostEqual(greeks["net"]["vega"], -10.0, places=8)
        self.assertEqual(
            greeks["net_assumes"], "parallel_volatility_move_across_expiries"
        )
        # A net of -10 hides a -30 / +20 calendar spread, which is a different
        # position from a flat -10 in one expiry.
        self.assertAlmostEqual(greeks["by_expiry"][EXPIRY]["vega"], -30.0, places=8)
        self.assertAlmostEqual(greeks["by_expiry"][LATER]["vega"], 20.0, places=8)


class UnboundedMemberTests(unittest.TestCase):
    def test_one_unbounded_member_makes_the_book_unbounded(self) -> None:
        report = _report(
            [
                _spread("defined", short=110_000.0, long=120_000.0),
                _naked("naked"),
            ]
        )

        self.assertIs(report["book"]["loss_is_bounded"], False)
        self.assertEqual(report["book"]["unbounded_members"], ["naked"])
        self.assertIsNone(report["book"]["max_loss_upper_bound_usdc"])
        self.assertIs(
            report["book"]["joint_terminal_risk"]["loss_is_bounded"], False
        )


class MarginalContributionTests(unittest.TestCase):
    """A candidate's own worst case is not what it adds to a book."""

    def test_an_offsetting_candidate_adds_less_than_it_is_worth_alone(self) -> None:
        report = _report(
            [
                _spread("call-side", short=110_000.0, long=120_000.0, credit=2_000.0),
                _spread(
                    "put-side",
                    short=90_000.0,
                    long=80_000.0,
                    option_type="put",
                    credit=1_800.0,
                ),
            ]
        )

        rows = {row["candidate_id"]: row for row in report["marginal_contributions"]}
        put_side = rows["put-side"]
        self.assertEqual(put_side["status"], "evaluated")
        self.assertEqual(put_side["standalone_max_loss_usdc"], 8_200.0)
        # Added to a book already short the upside, the put wing only brings its
        # own credit into play: the worst case stays on the call side.
        self.assertLess(
            put_side["marginal_max_loss_usdc"], put_side["standalone_max_loss_usdc"]
        )

    def test_marginal_is_unavailable_when_the_book_has_no_joint_payoff(self) -> None:
        report = _report(
            [
                _spread("august", short=110_000.0, long=120_000.0),
                _spread("september", short=110_000.0, long=120_000.0, expiry=LATER),
            ]
        )

        for row in report["marginal_contributions"]:
            self.assertEqual(row["status"], "unavailable")
            self.assertIsNone(row["marginal_max_loss_usdc"])


class ConcentrationTests(unittest.TestCase):
    def test_repeated_strikes_are_surfaced(self) -> None:
        report = _report(
            [
                _spread("a", short=110_000.0, long=120_000.0),
                _spread("b", short=110_000.0, long=125_000.0),
            ]
        )

        shared = report["concentration"]["shared_strikes"]
        self.assertEqual(shared, [{"strike": 110_000.0, "leg_count": 2}])

    def test_a_one_expiry_book_is_flagged_as_a_single_term_bet(self) -> None:
        report = _report(
            [
                _spread("a", short=110_000.0, long=120_000.0),
                _spread("b", short=115_000.0, long=125_000.0),
            ]
        )

        concentration = report["concentration"]
        self.assertEqual(concentration["expiry_count"], 1)
        self.assertEqual(concentration["largest_expiry_vega_share"], 1.0)
        self.assertIs(concentration["single_expiry_concentrated"], True)

    def test_a_spread_book_is_not_flagged(self) -> None:
        report = _report(
            [
                _spread("a", short=110_000.0, long=120_000.0, vega=-25.0),
                _spread("b", short=110_000.0, long=120_000.0, expiry=LATER, vega=-25.0),
            ]
        )

        self.assertIs(
            report["concentration"]["single_expiry_concentrated"], False
        )


class FailClosedTests(unittest.TestCase):
    def test_a_candidate_without_legs_is_excluded_and_named(self) -> None:
        report = _report([{"candidate_id": "legless", "structure_type": "mystery"}])

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["reason_code"], "NO_EVALUABLE_CANDIDATES")
        self.assertEqual(
            report["excluded_candidates"],
            [
                {
                    "candidate_id": "legless",
                    "reason_code": "CANDIDATE_HAS_NO_STRUCTURE_LEGS",
                }
            ],
        )

    def test_an_undeclared_premium_unit_excludes_rather_than_assumes(self) -> None:
        candidate = _spread("a", short=110_000.0, long=120_000.0)
        candidate["premium_unit"] = None

        report = _report([candidate])

        self.assertEqual(
            report["excluded_candidates"][0]["reason_code"], "PREMIUM_UNIT_UNKNOWN"
        )

    def test_the_report_never_carries_a_size(self) -> None:
        report = _report([_spread("a", short=110_000.0, long=120_000.0)])

        self.assertEqual(report["schema_version"], COMBINATION_RISK_SCHEMA_VERSION)
        self.assertIs(report["recommended_size_allowed"], False)
        self.assertIs(report["trade_instruction_allowed"], False)
        self.assertEqual(report["basis"], "one_contract_per_structure")


if __name__ == "__main__":
    unittest.main()
