"""Relative-value edge scoring: component math, fail-closed rules, dominance."""

from __future__ import annotations

import unittest

from crypto_options_report.edge_score import (
    BLOCKED,
    CAUTION,
    OK,
    UNKNOWN,
    build_relative_value_edge_score,
    find_atm_reference,
    normalize_premium_to_usd,
    rank_candidates_by_edge,
)

NAKED = "naked_short_call"
SPREAD = "call_credit_spread"

GOOD_SURFACE = {"fit_quality_score": 0.999, "no_arb_pass": True, "no_arb_error": 0.0}


def naked(**overrides):
    base = {
        "candidate_id": "naked-1",
        "underlying_price": 100_000.0,
        "strike_price": 115_000.0,
        "dte_days": 18.0,
        "market_bid": 0.103,
        "market_ask": 0.111,
        "market_mark_iv": 53.5,
        "surface_fitted_iv": 53.0,
        # A residual scale of exactly one IV point keeps the standardized value
        # numerically equal to the raw residual, so the component tests below
        # read as the arithmetic they are checking rather than as a conversion.
        "fit_residual_scale": 1.0,
        "underlying_price_source": "option_forward",
        "model_theta": -70.0,
        "model_vega": 48.0,
        "risk_neutral_p_itm": 0.11,
        "premium_unit": "quote_currency",
        "surface_quality": dict(GOOD_SURFACE),
    }
    base.update(overrides)
    return base


def spread(**overrides):
    base = {
        "candidate_id": "spread-1",
        "underlying_price": 100_000.0,
        "sell_leg_strike_price": 115_000.0,
        "buy_leg_strike_price": 125_000.0,
        "spread_width": 10_000.0,
        "net_credit": 2_400.0,
        "dte_days": 18.0,
        "sell_leg_market_bid": 2_600.0,
        "sell_leg_market_ask": 2_800.0,
        "buy_leg_market_bid": 300.0,
        "buy_leg_market_ask": 400.0,
        "sell_leg_market_mark_iv": 53.5,
        "sell_leg_surface_fitted_iv": 53.0,
        "buy_leg_market_mark_iv": 51.5,
        "buy_leg_surface_fitted_iv": 51.4,
        "fit_residual_scale": 1.0,
        "underlying_price_source": "option_forward",
        "model_theta": -50.0,
        "model_vega": 33.0,
        "risk_neutral_p_itm": 0.11,
        "premium_unit": "quote_currency",
        "surface_quality": dict(GOOD_SURFACE),
    }
    base.update(overrides)
    return base


ATM = {"strike_price": 100_000.0, "surface_fitted_iv": 50.0}


def score(candidate, structure_type, atm=ATM):
    return build_relative_value_edge_score(
        candidate=candidate, structure_type=structure_type, atm_reference=atm
    )


def component(candidate, structure_type, name, atm=ATM):
    return score(candidate, structure_type, atm)["components"][name]


class PremiumNormalizationTests(unittest.TestCase):
    """The unit trap: a coin-quoted credit is worth ~spot times a USD one."""

    def test_quote_currency_premium_is_taken_at_face_value(self):
        self.assertEqual(
            2_400.0,
            normalize_premium_to_usd(
                2_400.0, premium_unit="quote_currency", underlying_price=100_000.0
            ),
        )

    def test_inverse_premium_is_scaled_by_spot(self):
        self.assertEqual(
            2_400.0,
            normalize_premium_to_usd(
                0.024, premium_unit="inverse_base_currency", underlying_price=100_000.0
            ),
        )

    def test_undeclared_unit_returns_none_rather_than_assuming(self):
        self.assertIsNone(
            normalize_premium_to_usd(
                0.024, premium_unit=None, underlying_price=100_000.0
            )
        )

    def test_inverse_premium_without_spot_returns_none(self):
        self.assertIsNone(
            normalize_premium_to_usd(
                0.024, premium_unit="inverse_base_currency", underlying_price=None
            )
        )


class SmileResidualRichnessTests(unittest.TestCase):
    def test_uses_mark_not_bid(self):
        """bid_iv - fitted_iv collapses to half the spread and is not richness."""
        item = component(naked(), NAKED, "smile_residual_richness")

        self.assertEqual(OK, item["status"])
        self.assertAlmostEqual(0.5, item["value"], places=6)

    def test_spread_richness_is_net_across_legs(self):
        item = component(spread(), SPREAD, "smile_residual_richness")

        self.assertAlmostEqual(0.5 - 0.1, item["value"], places=6)

    def test_missing_mark_iv_is_unknown_not_zero(self):
        item = component(naked(market_mark_iv=None), NAKED, "smile_residual_richness")

        self.assertEqual(UNKNOWN, item["status"])
        self.assertIsNone(item["value"])

    def test_untrusted_surface_blocks_fitted_iv_components(self):
        candidate = naked(surface_quality={"fit_quality_score": 0.4, "no_arb_pass": False})
        scored = score(candidate, NAKED)

        self.assertEqual(BLOCKED, scored["components"]["smile_residual_richness"]["status"])
        self.assertEqual(BLOCKED, scored["components"]["breakeven_cushion"]["status"])
        self.assertEqual("partial", scored["status"])


class ResidualStandardizationTests(unittest.TestCase):
    """Raw IV points are not comparable between chains, so they are not ranked.

    On a scattered smile a 1.5-point residual sits inside the fit's own noise;
    on a tight one it is a large deviation. Ranking raw points therefore
    promotes the thinnest, worst-constrained expiries, which is the opposite of
    what the axis is supposed to find.
    """

    def test_ranked_value_is_the_residual_in_its_own_fit_noise_units(self):
        noisy = component(
            naked(fit_residual_scale=2.5), NAKED, "smile_residual_richness"
        )
        tight = component(
            naked(fit_residual_scale=0.1), NAKED, "smile_residual_richness"
        )

        self.assertEqual("residual_std_errors", noisy["unit"])
        self.assertAlmostEqual(0.5 / 2.5, noisy["value"], places=6)
        self.assertAlmostEqual(0.5 / 0.1, tight["value"], places=6)
        # Same raw richness, opposite conclusions about whether it is signal.
        self.assertGreater(tight["value"], noisy["value"])

    def test_raw_points_are_still_carried_for_display(self):
        item = component(
            naked(fit_residual_scale=2.5), NAKED, "smile_residual_richness"
        )

        self.assertAlmostEqual(0.5, item["raw_iv_points"], places=6)
        self.assertAlmostEqual(2.5, item["residual_scale_iv_points"], places=6)

    def test_a_chain_too_thin_to_scale_blocks_rather_than_falling_back(self):
        """The fallback would flatter exactly the chains that cannot support the fit."""
        item = component(
            naked(fit_residual_scale=None), NAKED, "smile_residual_richness"
        )

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual("RESIDUAL_SCALE_UNAVAILABLE", item["reason_code"])
        self.assertIsNone(item["value"])
        self.assertAlmostEqual(0.5, item["raw_iv_points"], places=6)


class ForwardProvenanceTests(unittest.TestCase):
    """Pricing off spot while calling it a forward manufactures richness.

    The basis between Deribit's per-expiry forward and its spot index reaches
    double-digit annualized rates in a trending market. Substituting one for the
    other shifts every strike's moneyness, moves the fitted smile under the
    mark, and shows up on this axis as edge that is an artefact of the
    substitution.
    """

    def test_index_fallback_downgrades_the_richness_component_to_caution(self):
        item = component(
            naked(underlying_price_source="index_spot_fallback"),
            NAKED,
            "smile_residual_richness",
        )

        self.assertEqual(CAUTION, item["status"])
        self.assertEqual("INDEX_SPOT_SUBSTITUTED_FOR_FORWARD", item["reason_code"])
        # The value is still published: a cautioned axis is comparable, it is
        # just not clean.
        self.assertIsNotNone(item["value"])

    def test_a_declared_forward_scores_without_caution(self):
        item = component(naked(), NAKED, "smile_residual_richness")

        self.assertEqual(OK, item["status"])
        self.assertIsNone(item["reason_code"])


class ThetaEfficiencyTests(unittest.TestCase):
    def test_short_position_greeks_are_sign_flipped(self):
        """model_theta/model_vega are the long option's; the structure is short."""
        item = component(naked(), NAKED, "theta_efficiency")

        self.assertEqual(OK, item["status"])
        # position_theta = +70, |position_vega| = 48
        self.assertAlmostEqual(70.0 / 48.0, item["value"], places=6)

    def test_zero_vega_is_blocked_not_infinite(self):
        item = component(naked(model_vega=0.0), NAKED, "theta_efficiency")

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual("VEGA_ZERO_OR_MISSING", item["reason_code"])

    def test_negative_carry_is_flagged_caution_not_silently_ranked(self):
        item = component(naked(model_theta=70.0), NAKED, "theta_efficiency")

        self.assertEqual(CAUTION, item["status"])
        self.assertEqual("NEGATIVE_THETA_EFFICIENCY", item["reason_code"])


class ReturnOnRiskTests(unittest.TestCase):
    def test_naked_short_has_no_defined_return_on_risk(self):
        """Unbounded loss must block, never yield a small flattering number."""
        item = component(naked(), NAKED, "return_on_risk")

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual(
            "UNBOUNDED_MAX_LOSS_NO_RETURN_ON_RISK_DEFINED", item["reason_code"]
        )
        self.assertIsNone(item["value"])

    def test_spread_return_on_risk_uses_normalized_credit(self):
        item = component(spread(), SPREAD, "return_on_risk")

        self.assertEqual(OK, item["status"])
        self.assertAlmostEqual(2_400.0 / 7_600.0, item["value"], places=6)

    def test_coin_quoted_spread_normalizes_before_dividing(self):
        coin = spread(net_credit=0.024, premium_unit="inverse_base_currency")
        item = component(coin, SPREAD, "return_on_risk")

        self.assertAlmostEqual(2_400.0 / 7_600.0, item["value"], places=6)

    def test_undeclared_premium_unit_blocks_rather_than_guessing(self):
        item = component(spread(premium_unit=None), SPREAD, "return_on_risk")

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual("PREMIUM_UNIT_UNKNOWN", item["reason_code"])

    def test_credit_exceeding_width_blocks(self):
        item = component(spread(net_credit=20_000.0), SPREAD, "return_on_risk")

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual("NON_POSITIVE_MAX_LOSS", item["reason_code"])


class BreakevenCushionTests(unittest.TestCase):
    def test_cushion_is_measured_in_atm_expected_moves(self):
        item = component(naked(), NAKED, "breakeven_cushion")

        self.assertEqual(OK, item["status"])
        # expected move = 100000 * 0.50 * sqrt(18/365) ≈ 11104
        # cushion = (115000 + 0.103) - 100000 = 15000.103
        self.assertAlmostEqual(1.3508, item["value"], places=3)

    def test_missing_atm_reference_is_unknown_not_substituted(self):
        """Using the candidate's own OTM vol would bake the skew into the cushion."""
        item = component(naked(), NAKED, "breakeven_cushion", atm=None)

        self.assertEqual(UNKNOWN, item["status"])
        self.assertEqual("MISSING_ATM_SURFACE_REFERENCE", item["reason_code"])

    def test_find_atm_reference_picks_strike_closest_to_spot(self):
        points = [
            {"strike_price": 90_000.0, "surface_fitted_iv": 55.0},
            {"strike_price": 101_000.0, "surface_fitted_iv": 50.0},
            {"strike_price": 130_000.0, "surface_fitted_iv": 48.0},
        ]

        found = find_atm_reference(points, underlying_price=100_000.0)

        self.assertEqual(101_000.0, found["strike_price"])

    def test_find_atm_reference_without_points_returns_none(self):
        self.assertIsNone(find_atm_reference([], underlying_price=100_000.0))


class AssignmentCostTests(unittest.TestCase):
    def test_probability_is_exposed_as_risk_neutral(self):
        item = component(naked(), NAKED, "assignment_cost")

        self.assertEqual(OK, item["status"])
        self.assertEqual("risk_neutral_probability", item["unit"])

    def test_rejected_greek_consistency_downgrades_to_caution(self):
        candidate = naked(greek_consistency={"status": "reject"})
        item = component(candidate, NAKED, "assignment_cost")

        self.assertEqual(CAUTION, item["status"])

    def test_out_of_range_probability_is_unknown(self):
        item = component(naked(risk_neutral_p_itm=1.4), NAKED, "assignment_cost")

        self.assertEqual(UNKNOWN, item["status"])


class StructureDerivedRiskTests(unittest.TestCase):
    """Risk comes from the legs, not from the structure's name.

    `return_on_risk` used to be blocked for anything that was not literally
    `call_credit_spread`, and the breakeven cushion was measured on the upside
    only. Both encoded "short calls" as the sole shape the product could hold. A
    put credit spread is exactly as defined-risk, and a ratio short more calls
    than it is long is exactly as unbounded, neither of which a type string can
    tell you.
    """

    def _put_spread(self, **overrides):
        base = naked(
            candidate_id="put-spread-1",
            structure_type="put_credit_spread",
            market_bid=2_000.0,
            structure_legs=[
                {"option_type": "put", "strike": 90_000.0, "quantity": -1.0},
                {"option_type": "put", "strike": 80_000.0, "quantity": 1.0},
            ],
        )
        base.update(overrides)
        return base

    def test_a_put_credit_spread_gets_a_defined_return_on_risk(self):
        item = component(self._put_spread(), NAKED, "return_on_risk")

        self.assertEqual(OK, item["status"])
        # Width 10_000, credit 2_000, so max loss is 8_000.
        self.assertAlmostEqual(2_000.0 / 8_000.0, item["value"], places=6)

    def test_a_ratio_short_more_calls_than_it_is_long_is_blocked_as_unbounded(self):
        candidate = naked(
            candidate_id="ratio-1",
            structure_type="call_ratio_spread",
            market_bid=300.0,
            structure_legs=[
                {"option_type": "call", "strike": 110_000.0, "quantity": 1.0},
                {"option_type": "call", "strike": 120_000.0, "quantity": -2.0},
            ],
        )

        item = component(candidate, NAKED, "return_on_risk")

        self.assertEqual(BLOCKED, item["status"])
        self.assertEqual(
            "UNBOUNDED_MAX_LOSS_NO_RETURN_ON_RISK_DEFINED", item["reason_code"]
        )

    def test_downside_cushion_is_measured_toward_the_downside_breakeven(self):
        item = component(self._put_spread(), NAKED, "breakeven_cushion")

        self.assertEqual(OK, item["status"])
        # Breakeven is 90_000 - 2_000 = 88_000, which is 12_000 below spot. A
        # cushion measured upward would have produced a negative number here.
        self.assertGreater(item["value"], 0.0)

    def test_position_greeks_replace_the_caller_side_sign_flip(self):
        candidate = naked(
            position_greeks={
                "status": "aggregated",
                "theta": 70.0,
                "vega": -48.0,
            }
        )

        item = component(candidate, NAKED, "theta_efficiency")

        self.assertEqual(OK, item["status"])
        self.assertAlmostEqual(70.0 / 48.0, item["value"], places=6)

    def test_a_net_long_vol_structure_reports_negative_efficiency(self):
        """The legacy negation would have turned this into a positive score."""
        candidate = naked(
            position_greeks={
                "status": "aggregated",
                "theta": -70.0,
                "vega": 48.0,
            }
        )

        item = component(candidate, NAKED, "theta_efficiency")

        self.assertEqual(CAUTION, item["status"])
        self.assertLess(item["value"], 0.0)


class FrontierOccupancyTests(unittest.TestCase):
    """Pareto dominance can quietly stop discriminating, and must say so.

    Dominance needs a rival at least as good on *every* comparable axis. With
    six axes that is rarely satisfied, so the frontier swallows the field and
    the published order collapses onto the first tie-break axis. The module
    argues that refusing a weighted sum avoids an unstated claim about relative
    importance; when the frontier is degenerate that claim has merely moved into
    the tie-break order, and the reader deserves to see it.
    """

    def test_a_degenerate_frontier_is_reported_as_such(self):
        # Each candidate wins on a different axis, so none dominates any other.
        candidates = [
            score(naked(candidate_id="a", market_mark_iv=54.0), NAKED),
            score(naked(candidate_id="b", model_theta=-95.0), NAKED),
            score(naked(candidate_id="c", risk_neutral_p_itm=0.01), NAKED),
            score(naked(candidate_id="d", strike_price=125_000.0), NAKED),
        ]

        occupancy = rank_candidates_by_edge(candidates)["frontier_occupancy"]

        self.assertEqual(4, occupancy["frontier_candidates"])
        self.assertEqual(1.0, occupancy["frontier_fraction"])
        self.assertIs(False, occupancy["dominance_discriminating"])
        self.assertEqual(
            "lexicographic_on_smile_residual_richness",
            occupancy["effective_ranking_basis"],
        )

    def test_a_discriminating_frontier_keeps_the_pareto_label(self):
        better = score(
            naked(
                candidate_id="better",
                market_mark_iv=54.0,
                model_theta=-90.0,
                strike_price=120_000.0,
                risk_neutral_p_itm=0.05,
            ),
            NAKED,
        )
        others = [
            score(naked(candidate_id=f"worse-{index}"), NAKED) for index in range(4)
        ]

        occupancy = rank_candidates_by_edge([better, *others])["frontier_occupancy"]

        self.assertLess(occupancy["frontier_fraction"], 0.8)
        self.assertIs(True, occupancy["dominance_discriminating"])
        self.assertEqual(
            "pareto_frontier_then_lexicographic",
            occupancy["effective_ranking_basis"],
        )

    def test_occupancy_is_broken_out_per_structure_type(self):
        candidates = [
            score(naked(candidate_id="n1"), NAKED),
            score(naked(candidate_id="n2", market_mark_iv=54.0), NAKED),
            score(spread(candidate_id="s1"), SPREAD),
        ]

        by_structure = rank_candidates_by_edge(candidates)["frontier_occupancy"][
            "by_structure_type"
        ]

        self.assertEqual(2, by_structure[NAKED]["scored_candidates"])
        self.assertEqual(1, by_structure[SPREAD]["scored_candidates"])
        self.assertEqual(1.0, by_structure[SPREAD]["frontier_fraction"])


class DominanceTests(unittest.TestCase):
    def test_strictly_worse_candidate_is_dominated_and_explained(self):
        better = score(
            naked(
                candidate_id="better",
                market_mark_iv=54.0,      # richer
                model_theta=-90.0,        # more carry
                strike_price=120_000.0,   # more cushion
                risk_neutral_p_itm=0.05,  # cheaper assignment
            ),
            NAKED,
        )
        worse = score(naked(candidate_id="worse"), NAKED)

        result = rank_candidates_by_edge([better, worse])

        self.assertEqual(["better"], [f["candidate_id"] for f in result["frontier"]])
        self.assertEqual(1, len(result["dominated"]))
        entry = result["dominated"][0]
        self.assertEqual("worse", entry["candidate_id"])
        self.assertEqual("better", entry["dominated_by"])
        self.assertIn("smile_residual_richness", entry["losing_axes"])
        self.assertIn("theta_efficiency", entry["losing_axes"])

    def test_genuine_tradeoff_keeps_both_on_the_frontier(self):
        rich = score(
            naked(candidate_id="rich", market_mark_iv=54.0, risk_neutral_p_itm=0.20),
            NAKED,
        )
        safe = score(
            naked(candidate_id="safe", market_mark_iv=53.0, risk_neutral_p_itm=0.02),
            NAKED,
        )

        result = rank_candidates_by_edge([rich, safe])

        self.assertEqual(2, len(result["frontier"]))
        self.assertEqual([], result["dominated"])

    def test_naked_and_spread_are_not_compared_across_structures(self):
        """A naked call must not win by lacking a return-on-risk axis."""
        result = rank_candidates_by_edge(
            [score(naked(), NAKED), score(spread(), SPREAD)]
        )

        self.assertEqual("within_structure_type", result["dominance_scope"])
        self.assertEqual(2, len(result["frontier"]))
        self.assertEqual([], result["dominated"])

    def test_partial_candidates_are_separated_from_the_ranking(self):
        incomplete = score(naked(candidate_id="incomplete", model_vega=None), NAKED)

        result = rank_candidates_by_edge([score(naked(), NAKED), incomplete])

        self.assertEqual(
            ["incomplete"],
            [item["candidate_id"] for item in result["partial_evidence"]],
        )
        self.assertNotIn(
            "incomplete", [item["candidate_id"] for item in result["frontier"]]
        )

    def test_tie_break_order_is_published(self):
        result = rank_candidates_by_edge([score(naked(), NAKED)])

        self.assertEqual(
            [
                "smile_residual_richness",
                "return_on_risk",
                "liquidity_cost_ratio",
                "theta_efficiency",
                "breakeven_cushion",
                "assignment_cost",
            ],
            result["tie_break_order"],
        )


class HonestyTests(unittest.TestCase):
    def test_score_states_what_it_cannot_establish(self):
        scored = score(naked(), NAKED)

        joined = " ".join(scored["cannot_tell"]).lower()
        self.assertIn("does not establish", joined)
        self.assertIn("risk-neutral", joined)

    def test_structural_absence_does_not_mark_a_candidate_as_partial(self):
        """A naked call is fully scored even though two axes cannot apply."""
        scored = score(naked(), NAKED)

        self.assertEqual("scored", scored["status"])
        self.assertEqual([], scored["blocked_components"])


if __name__ == "__main__":
    unittest.main()
