"""Absolute expected value from a realized-return distribution.

The sign convention is the trap this file guards. `path_risk` reports
`expected_payoff_usdc` as the seller's expected *payout*, so expected value is
credit minus payout minus fees. Reading the payout as profit inverts every
conclusion, which is why the arithmetic is pinned here rather than eyeballed.
"""

from __future__ import annotations

import unittest

from crypto_options_report.ev_scanner import (
    MAX_ABSOLUTE_EV_CANDIDATES,
    build_absolute_ev,
    build_ev_candidate_scanner,
)

NAKED = "naked_short_call"
SPREAD = "call_credit_spread"


def history(days: int = 1200, *, drift: float = 0.0) -> dict:
    """Deterministic oscillating series with an optional drift."""
    observations = []
    price = 100_000.0
    for index in range(days):
        price *= 1.0 + drift + (0.010 if index % 2 else -0.0099)
        observations.append(
            {
                "timestamp_ms": 1_700_000_000_000 + index * 86_400_000,
                "observed_at": f"2024-01-01T00:00:{index % 60:02d}Z",
                "close": round(price, 4),
            }
        )
    return {
        "schema_version": "underlying_price_history.v1",
        "source": "deribit_live:https://www.deribit.com",
        "instrument_name": "BTC-PERPETUAL",
        "resolution_seconds": 86400,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def candidate(**overrides) -> dict:
    base = {
        "candidate_id": "naked-1",
        "underlying_price": 100_000.0,
        "strike_price": 115_000.0,
        "dte_days": 18.0,
        "model_delta": 0.13,
        "model_vega": 48.0,
        "premium_unit": "quote_currency",
    }
    base.update(overrides)
    return base


def ev(credit, *, structure=NAKED, hist=None, **overrides):
    return build_absolute_ev(
        candidate=candidate(**overrides),
        structure_type=structure,
        underlying_history=hist or history(),
        entry_credit_usdc=credit,
        permission_state={},
        generated_at="2026-07-26T00:00:00Z",
    )


class ArithmeticTests(unittest.TestCase):
    def test_expected_value_is_credit_minus_payout_minus_fees(self):
        result = ev(500.0)

        self.assertEqual("validated", result["status"])
        expected = (
            result["entry_credit_usdc"]
            - result["expected_payout_usdc"]
            - result["modelled_fees_usdc"]["total_usdc"]
        )
        self.assertAlmostEqual(expected, result["ev_after_cost_usdc"], places=4)

    def test_payout_is_a_cost_so_higher_payout_lowers_expected_value(self):
        near = ev(500.0, strike_price=102_000.0)
        far = ev(500.0, strike_price=160_000.0)

        self.assertGreater(near["expected_payout_usdc"], far["expected_payout_usdc"])
        self.assertLess(near["ev_after_cost_usdc"], far["ev_after_cost_usdc"])

    def test_more_credit_raises_expected_value_one_for_one_before_fees(self):
        low = ev(300.0)
        high = ev(800.0)

        self.assertAlmostEqual(
            low["expected_payout_usdc"], high["expected_payout_usdc"], places=4
        )
        self.assertGreater(high["ev_after_cost_usdc"], low["ev_after_cost_usdc"])

    def test_unreachable_strike_still_carries_the_stress_overlay(self):
        """Payout never collapses to zero: the fat-tail floor always applies.

        Even with no historical path reaching the strike, the mixture reserves a
        minimum weight for stress scenarios, whose IV-jump and exit costs are
        charged against the position's vega. A payout of exactly zero would mean
        the model had concluded a crash is impossible because it has not seen
        one, which is the failure this floor exists to prevent.
        """
        result = ev(500.0, strike_price=10_000_000.0)

        self.assertAlmostEqual(0.0, result["p_itm"], places=6)
        self.assertGreater(result["expected_payout_usdc"], 0.0)
        # Small relative to the credit, but explicitly not nil.
        self.assertLess(result["expected_payout_usdc"], 100.0)
        self.assertGreater(result["ev_after_cost_usdc"], 350.0)

    def test_expected_value_can_be_positive(self):
        """The machinery must be able to report a favourable trade, not only bad ones."""
        result = ev(5_000.0, strike_price=180_000.0)

        self.assertGreater(result["ev_after_cost_usdc"], 0.0)


class FeeTests(unittest.TestCase):
    def test_linear_and_inverse_units_both_produce_fees(self):
        linear = ev(500.0)
        inverse = ev(500.0, premium_unit="inverse_base_currency")

        self.assertEqual("linear", linear["modelled_fees_usdc"]["basis"])
        self.assertEqual("inverse", inverse["modelled_fees_usdc"]["basis"])
        self.assertGreater(linear["modelled_fees_usdc"]["total_usdc"], 0.0)
        self.assertGreater(inverse["modelled_fees_usdc"]["total_usdc"], 0.0)

    def test_undeclared_premium_unit_blocks_rather_than_assuming_a_venue(self):
        result = ev(500.0, premium_unit=None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual("PREMIUM_UNIT_UNKNOWN", result["reason_code"])

    def test_delivery_fee_is_weighted_by_assignment_probability(self):
        result = ev(500.0)
        fees = result["modelled_fees_usdc"]

        self.assertEqual("p_itm", fees["delivery_fee_weighted_by"])
        self.assertGreaterEqual(fees["expected_delivery_fee_usdc"], 0.0)
        self.assertAlmostEqual(
            fees["entry_fee_usdc"] + fees["expected_delivery_fee_usdc"],
            fees["total_usdc"],
            places=6,
        )


class EvidenceTests(unittest.TestCase):
    def test_sample_size_reported_is_the_independent_window_count(self):
        result = ev(500.0)

        self.assertEqual(1200 // 18, result["authoritative_sample_size"])
        self.assertEqual(
            "independent_non_overlapping_windows", result["sample_size_basis"]
        )

    def test_result_names_its_evidence_class_and_measure(self):
        result = ev(500.0)

        self.assertEqual(
            "validated_underlying_price_history", result["evidence_class"]
        )
        self.assertEqual(
            "physical_realized_return_distribution", result["measure"]
        )

    def test_nav_relative_metrics_are_withheld_without_an_account(self):
        """A reference NAV must not be dressed up as the reader's own."""
        result = ev(500.0)

        self.assertIs(False, result["nav_relative_metrics_available"])
        self.assertNotIn("stress_loss_nav_pct", result)


class FailClosedTests(unittest.TestCase):
    def test_thin_history_yields_no_expected_value(self):
        result = ev(500.0, hist=history(120))

        self.assertEqual("unavailable", result["status"])
        self.assertIsNone(result.get("ev_after_cost_usdc"))

    def test_missing_credit_yields_no_expected_value(self):
        result = ev(None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual("MISSING_CANDIDATE_ECONOMICS", result["reason_code"])

    def test_missing_strike_yields_no_expected_value(self):
        result = ev(500.0, strike_price=None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual("MISSING_STRIKE", result["reason_code"])

    def test_candidate_limit_is_bounded(self):
        self.assertGreater(MAX_ABSOLUTE_EV_CANDIDATES, 0)
        self.assertLessEqual(MAX_ABSOLUTE_EV_CANDIDATES, 32)


class SpreadTests(unittest.TestCase):
    def test_spread_payout_is_capped_by_the_long_leg(self):
        """A defined-risk structure cannot pay out more than its width."""
        spread = build_absolute_ev(
            candidate=candidate(
                candidate_id="spread-1",
                sell_leg_strike_price=105_000.0,
                buy_leg_strike_price=115_000.0,
            ),
            structure_type=SPREAD,
            underlying_history=history(),
            entry_credit_usdc=2_000.0,
            permission_state={},
            generated_at="2026-07-26T00:00:00Z",
        )
        naked = ev(2_000.0, strike_price=105_000.0)

        self.assertEqual("validated", spread["status"])
        self.assertLess(
            spread["expected_payout_usdc"], naked["expected_payout_usdc"]
        )
        self.assertLessEqual(spread["expected_payout_usdc"], 10_000.0)


def _surface_point(strike: float, iv_percent: float = 55.0) -> dict:
    return {
        "strike_price": strike,
        "surface_fitted_iv": iv_percent,
        "model_delta": 0.1,
    }


def _vol_surface_status() -> dict:
    return {
        "expiries": [
            {
                "expiry_date": "2026-08-18",
                "surface_points": [
                    _surface_point(80_000.0),
                    _surface_point(100_000.0, iv_percent=50.0),
                    _surface_point(120_000.0),
                ]
            }
        ]
    }


def _call_spread_candidate(
    candidate_id: str,
    *,
    net_credit: float,
    richness: float,
    mid_credit: float | None = None,
    sell_strike: float = 105_000.0,
    buy_strike: float = 115_000.0,
) -> dict:
    sell_iv = 53.0 + richness
    buy_iv = 51.4
    return {
        "candidate_id": candidate_id,
        "structure_type": "call_credit_spread",
        "expiry_date": "2026-08-18",
        "underlying_price": 100_000.0,
        "sell_leg_strike_price": sell_strike,
        "buy_leg_strike_price": buy_strike,
        "spread_width": buy_strike - sell_strike,
        "net_credit": net_credit,
        "mid_credit": mid_credit if mid_credit is not None else net_credit + 200.0,
        "dte_days": 18.0,
        "sell_leg_market_bid": net_credit + 350.0,
        "sell_leg_market_ask": net_credit + 450.0,
        "buy_leg_market_bid": 250.0,
        "buy_leg_market_ask": 450.0,
        "sell_leg_market_mark_iv": sell_iv,
        "sell_leg_surface_fitted_iv": 53.0,
        "buy_leg_market_mark_iv": buy_iv + 0.1,
        "buy_leg_surface_fitted_iv": buy_iv,
        "fit_residual_scale": 1.0,
        "underlying_price_source": "option_forward",
        "model_theta": -50.0,
        "model_vega": 33.0,
        "model_delta": 0.11,
        "risk_neutral_p_itm": 0.11,
        "premium_unit": "quote_currency",
        "surface_quality": {
            "fit_quality_score": 0.999,
            "no_arb_pass": True,
            "no_arb_error": 0.0,
        },
        "structure_legs": [
            {
                "option_type": "call",
                "strike": sell_strike,
                "quantity": -1.0,
                "surface_fitted_iv": 53.0,
            },
            {
                "option_type": "call",
                "strike": buy_strike,
                "quantity": 1.0,
                "surface_fitted_iv": 51.4,
            },
        ],
        "position_greeks": {"status": "aggregated", "theta": 50.0, "vega": -33.0},
        "decision_reason_codes": [],
        "filter_reason_codes": [],
    }


def _put_spread_candidate(candidate_id: str, *, net_credit: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "structure_type": "put_credit_spread",
        "expiry_date": "2026-08-18",
        "underlying_price": 100_000.0,
        "sell_leg_strike_price": 95_000.0,
        "buy_leg_strike_price": 85_000.0,
        "spread_width": 10_000.0,
        "net_credit": net_credit,
        "mid_credit": net_credit + 150.0,
        "dte_days": 18.0,
        "sell_leg_market_bid": net_credit + 350.0,
        "sell_leg_market_ask": net_credit + 430.0,
        "buy_leg_market_bid": 260.0,
        "buy_leg_market_ask": 410.0,
        "sell_leg_market_mark_iv": 58.2,
        "sell_leg_surface_fitted_iv": 57.3,
        "buy_leg_market_mark_iv": 55.9,
        "buy_leg_surface_fitted_iv": 55.8,
        "fit_residual_scale": 1.0,
        "underlying_price_source": "option_forward",
        "model_theta": -47.0,
        "model_vega": 31.0,
        "model_delta": -0.12,
        "risk_neutral_p_itm": 0.12,
        "premium_unit": "quote_currency",
        "surface_quality": {
            "fit_quality_score": 0.999,
            "no_arb_pass": True,
            "no_arb_error": 0.0,
        },
        "structure_legs": [
            {
                "option_type": "put",
                "strike": 95_000.0,
                "quantity": -1.0,
                "surface_fitted_iv": 57.3,
            },
            {
                "option_type": "put",
                "strike": 85_000.0,
                "quantity": 1.0,
                "surface_fitted_iv": 55.8,
            },
        ],
        "position_greeks": {"status": "aggregated", "theta": 47.0, "vega": -31.0},
        "decision_reason_codes": [],
        "filter_reason_codes": [],
    }


def _condor_candidate(candidate_id: str, *, net_credit: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "structure_type": "iron_condor",
        "expiry_date": "2026-08-18",
        "underlying_price": 100_000.0,
        "spread_width": 10_000.0,
        "net_credit": net_credit,
        "mid_credit": net_credit + 150.0,
        "dte_days": 18.0,
        "sell_leg_market_bid": net_credit + 300.0,
        "sell_leg_market_ask": net_credit + 420.0,
        "buy_leg_market_bid": 270.0,
        "buy_leg_market_ask": 420.0,
        "sell_leg_market_mark_iv": 53.8,
        "sell_leg_surface_fitted_iv": 53.0,
        "buy_leg_market_mark_iv": 51.6,
        "buy_leg_surface_fitted_iv": 51.4,
        "fit_residual_scale": 1.0,
        "underlying_price_source": "option_forward",
        "model_theta": -60.0,
        "model_vega": 42.0,
        "model_delta": 0.08,
        "risk_neutral_p_itm": 0.18,
        "premium_unit": "quote_currency",
        "surface_quality": {
            "fit_quality_score": 0.999,
            "no_arb_pass": True,
            "no_arb_error": 0.0,
        },
        "structure_legs": [
            {
                "option_type": "put",
                "strike": 90_000.0,
                "quantity": -1.0,
                "surface_fitted_iv": 56.0,
            },
            {
                "option_type": "put",
                "strike": 80_000.0,
                "quantity": 1.0,
                "surface_fitted_iv": 54.0,
            },
            {
                "option_type": "call",
                "strike": 110_000.0,
                "quantity": -1.0,
                "surface_fitted_iv": 53.0,
            },
            {
                "option_type": "call",
                "strike": 120_000.0,
                "quantity": 1.0,
                "surface_fitted_iv": 51.4,
            },
        ],
        "position_greeks": {"status": "aggregated", "theta": 60.0, "vega": -42.0},
        "decision_reason_codes": [],
        "filter_reason_codes": [],
    }


def _scanner(candidate_research: dict) -> dict:
    return build_ev_candidate_scanner(
        generated_at="2026-07-26T00:00:00Z",
        data_status={"status": "validated"},
        account_status={},
        calibration_status={},
        permission_state={},
        candidate_research=candidate_research,
        vol_surface_status=_vol_surface_status(),
        underlying_history=history(),
    )


class ScannerAbsoluteEvOrderingTests(unittest.TestCase):
    def test_ninth_positive_call_spread_is_promoted_ahead_of_first_eight_negative_ones(self):
        negatives = [
            _call_spread_candidate(
                f"neg-{index}",
                net_credit=500.0,
                richness=12.0 - index,
                mid_credit=1_800.0 - index * 100.0,
            )
            for index in range(MAX_ABSOLUTE_EV_CANDIDATES)
        ]
        positive = _call_spread_candidate(
            "positive-late",
            net_credit=5_000.0,
            richness=1.0,
        )
        scanner = _scanner(
            {
                "status": "validated",
                "structure_types": ["call_credit_spreads"],
                "call_credit_spreads": {
                    "eligible": negatives + [positive],
                    "review": [],
                    "rejected": [],
                },
            }
        )

        rows = scanner["ranked_candidates"]
        self.assertEqual("validated", scanner["status"])
        self.assertIsNone(scanner["reason_code"])
        self.assertEqual("positive-late", rows[0]["candidate_id"])
        self.assertGreater(rows[0]["ev_after_cost_usdc"], 0.0)
        self.assertEqual("validated_historical", rows[0]["path_risk"]["status"])
        for row in rows[1: 1 + MAX_ABSOLUTE_EV_CANDIDATES]:
            with self.subTest(candidate=row["candidate_id"]):
                self.assertEqual("REVIEW", row["action"])
                self.assertIn("NEGATIVE_EV_AFTER_COST", row["kill_conditions"])
                self.assertLess(row["ev_after_cost_usdc"], 0.0)

    def test_put_spreads_and_condors_receive_validated_absolute_ev_without_fake_path_missing_reason(self):
        scanner = _scanner(
            {
                "status": "validated",
                "structure_types": ["put_credit_spreads", "iron_condors"],
                "put_credit_spreads": {
                    "eligible": [_put_spread_candidate("put-positive", net_credit=4_000.0)],
                    "review": [],
                    "rejected": [],
                },
                "iron_condors": {
                    "eligible": [_condor_candidate("condor-positive", net_credit=4_600.0)],
                    "review": [],
                    "rejected": [],
                },
            }
        )

        self.assertEqual("validated", scanner["status"])
        self.assertIsNone(scanner["reason_code"])
        rows = {row["candidate_id"]: row for row in scanner["ranked_candidates"]}
        for candidate_id in ("put-positive", "condor-positive"):
            with self.subTest(candidate=candidate_id):
                row = rows[candidate_id]
                self.assertGreater(row["ev_after_cost_usdc"], 0.0)
                self.assertEqual("validated_historical", row["path_risk"]["status"])
                self.assertIsNone(row["path_risk"]["reason_code"])
                self.assertNotIn("NO_VALIDATED_PATH_RISK", row["kill_conditions"])


if __name__ == "__main__":
    unittest.main()
