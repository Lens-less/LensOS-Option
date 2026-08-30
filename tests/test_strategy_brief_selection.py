from __future__ import annotations

import unittest

from crypto_options_report.strategy_brief import (
    build_strategy_brief,
    validate_strategy_brief,
)
from crypto_options_report.strategy_forecast import selection_binding_key_from_scope
from crypto_options_report.strategy_history import expected_history_binding_key
from tests.test_strategy_brief_contract import (
    _candidate,
    _forecast,
    _history,
    _leg,
    _market,
)


def _candidate_with_family(
    candidate_id: str,
    *,
    structure_type: str,
    ev_after_cost: float,
    cvar_95: float,
    legs: list[dict],
    history_status: str = "EXPLORATORY",
    forecast_status: str = "UNAVAILABLE",
    net_r: float | None = None,
    **overrides,
) -> tuple[dict, dict, dict]:
    normalized_structure = {
        "call_credit_spread": "BEAR_CALL_CREDIT_SPREAD",
        "put_credit_spread": "BULL_PUT_CREDIT_SPREAD",
        "iron_condor": "IRON_CONDOR",
    }[structure_type]
    normalized_direction = {
        "call_credit_spread": "BEARISH",
        "put_credit_spread": "BULLISH",
        "iron_condor": "RANGE",
    }[structure_type]
    candidate = _candidate(
        candidate_id,
        structure_type,
        ev_after_cost=ev_after_cost,
        cvar_95=cvar_95,
        structure_legs=legs,
        net_r=net_r,
        **overrides,
    )
    selection_scope = {
        "underlying": "BTC",
        "structure": normalized_structure,
        "direction": normalized_direction,
        "dte": {"min": 7, "max": 35},
        "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
        "exit_basis": "hold_to_expiry_cash_settlement",
        "selection": {
            "expiry_date": str(legs[0]["expiry_date"]),
            "legs": [
                {
                    "instrument_name": leg["instrument_name"],
                    "option_type": leg["option_type"],
                    "strike": leg["strike"],
                    "quantity": leg["quantity"],
                }
                for leg in legs
            ],
        },
    }
    history = {
        "status": history_status,
        "win_rate": 0.70,
        "mean_net_r": 0.20,
        "independent_cohorts": 10,
        "observation_count": 120,
        "exit_basis": "hold_to_expiry",
        "artifact_id": f"history:{candidate_id}",
        "history_binding_key": expected_history_binding_key(normalized_structure),
        "scope_verified": True,
        "scope": {
            "underlying": "BTC",
            "structure_type": normalized_structure,
            "direction": normalized_direction,
            "dte_band_days": [7, 35],
            "entry_cost_basis": "SHORT_BID_LONG_ASK",
            "exit_basis": "hold_to_expiry",
        },
    }
    forecast = {
        "schema_version": "strategy_forecast.v1",
        "status": forecast_status,
        "win_rate_low": 0.58,
        "win_rate_high": 0.64,
        "confidence": "MEDIUM",
        "scope": {
            "underlying": "BTC",
            "structure_type": normalized_structure,
            "direction": normalized_direction,
            "dte_band_days": [7, 35],
            "entry_cost_basis": "SHORT_BID_LONG_ASK",
            "exit_basis": "hold_to_expiry",
        },
        "artifact_id": f"forecast:{candidate_id}",
        "selection_binding_key": selection_binding_key_from_scope(selection_scope),
    }
    return candidate, history, forecast


class StrategyBriefSelectionTests(unittest.TestCase):
    def test_post_gate_ranking_dedupes_by_family_and_caps_at_three(self) -> None:
        bear_best, bear_best_history, bear_best_forecast = _candidate_with_family(
            "bear-best",
            structure_type="call_credit_spread",
            ev_after_cost=240.0,
            cvar_95=1_700.0,
            history_status="VALIDATED",
            forecast_status="UNAVAILABLE",
            net_r=0.09,
            legs=[
                _leg(
                    "BTC-25SEP26-128000-C",
                    option_type="call",
                    strike=128_000.0,
                    quantity=-1.0,
                    bid=1_100.0,
                    ask=1_150.0,
                ),
                _leg(
                    "BTC-25SEP26-132000-C",
                    option_type="call",
                    strike=132_000.0,
                    quantity=1.0,
                    bid=650.0,
                    ask=700.0,
                ),
            ],
        )
        bear_weaker, bear_weaker_history, bear_weaker_forecast = _candidate_with_family(
            "bear-weaker",
            structure_type="call_credit_spread",
            ev_after_cost=120.0,
            cvar_95=2_200.0,
            history_status="EXPLORATORY",
            forecast_status="UNAVAILABLE",
            net_r=0.03,
            legs=[
                _leg(
                    "BTC-25SEP26-129000-C",
                    option_type="call",
                    strike=129_000.0,
                    quantity=-1.0,
                    bid=1_050.0,
                    ask=1_100.0,
                ),
                _leg(
                    "BTC-25SEP26-133000-C",
                    option_type="call",
                    strike=133_000.0,
                    quantity=1.0,
                    bid=700.0,
                    ask=770.0,
                ),
            ],
        )
        bull, bull_history, bull_forecast = _candidate_with_family(
            "bull-one",
            structure_type="put_credit_spread",
            ev_after_cost=160.0,
            cvar_95=1_500.0,
            history_status="EXPLORATORY",
            forecast_status="CALIBRATED",
            net_r=0.05,
            legs=[
                _leg(
                    "BTC-25SEP26-115000-P",
                    option_type="put",
                    strike=115_000.0,
                    quantity=-1.0,
                    bid=980.0,
                    ask=1_020.0,
                ),
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=1.0,
                    bid=550.0,
                    ask=610.0,
                ),
            ],
        )
        condor, condor_history, condor_forecast = _candidate_with_family(
            "condor-one",
            structure_type="iron_condor",
            ev_after_cost=150.0,
            cvar_95=2_000.0,
            history_status="EXPLORATORY",
            forecast_status="UNAVAILABLE",
            net_r=0.04,
            legs=[
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=-1.0,
                    bid=820.0,
                    ask=860.0,
                ),
                _leg(
                    "BTC-25SEP26-105000-P",
                    option_type="put",
                    strike=105_000.0,
                    quantity=1.0,
                    bid=520.0,
                    ask=560.0,
                ),
                _leg(
                    "BTC-25SEP26-130000-C",
                    option_type="call",
                    strike=130_000.0,
                    quantity=-1.0,
                    bid=980.0,
                    ask=1_040.0,
                ),
                _leg(
                    "BTC-25SEP26-135000-C",
                    option_type="call",
                    strike=135_000.0,
                    quantity=1.0,
                    bid=620.0,
                    ask=680.0,
                ),
            ],
        )

        history = {
            "bear-best": bear_best_history,
            "bear-weaker": bear_weaker_history,
            "bull-one": bull_history,
            "condor-one": condor_history,
        }
        forecast = {
            "bear-best": bear_best_forecast,
            "bear-weaker": bear_weaker_forecast,
            "bull-one": bull_forecast,
            "condor-one": condor_forecast,
        }
        brief = build_strategy_brief(
            analysis_run_id="analysis:selection",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[bear_weaker, condor, bear_best, bull],
            history_by_candidate=history,
            forecast_by_candidate=forecast,
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("STRATEGIES_AVAILABLE", brief["action"])
        self.assertEqual(3, len(brief["strategies"]))
        self.assertEqual(
            [
                "BEAR_CALL_CREDIT_SPREAD",
                "BULL_PUT_CREDIT_SPREAD",
                "IRON_CONDOR",
            ],
            [item["structure_type"] for item in brief["strategies"]],
        )
        self.assertEqual(
            ["RECOMMENDED", "RECOMMENDED", "WATCH"],
            [item["recommendation_status"] for item in brief["strategies"]],
        )
        self.assertEqual(
            {
                "candidate_count": 4,
                "hard_gate_pass_count": 4,
                "selected_count": 3,
                "recommended_count": 2,
                "watch_count": 1,
            },
            {
                key: brief["evidence_summary"][key]
                for key in (
                    "candidate_count",
                    "hard_gate_pass_count",
                    "selected_count",
                    "recommended_count",
                    "watch_count",
                )
            },
        )

    def test_hard_gates_remove_negative_ev_robustness_and_stale_quotes(self) -> None:
        base_history = _history()
        base_forecast = _forecast()
        stale = _candidate(
            "stale-one",
            "call_credit_spread",
            ev_after_cost=140.0,
            cvar_95=1_700.0,
            max_quote_age_seconds=30,
            structure_legs=[
                _leg(
                    "BTC-25SEP26-128000-C",
                    option_type="call",
                    strike=128_000.0,
                    quantity=-1.0,
                    bid=1_100.0,
                    ask=1_150.0,
                    observed_at="2026-08-30T14:20:01Z",
                ),
                _leg(
                    "BTC-25SEP26-132000-C",
                    option_type="call",
                    strike=132_000.0,
                    quantity=1.0,
                    bid=650.0,
                    ask=700.0,
                    observed_at="2026-08-30T14:20:02Z",
                ),
            ],
        )
        negative_ev = _candidate(
            "negative-ev",
            "put_credit_spread",
            ev_after_cost=-5.0,
            cvar_95=1_300.0,
            structure_legs=[
                _leg(
                    "BTC-25SEP26-115000-P",
                    option_type="put",
                    strike=115_000.0,
                    quantity=-1.0,
                    bid=900.0,
                    ask=950.0,
                ),
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=1.0,
                    bid=500.0,
                    ask=560.0,
                ),
            ],
        )
        wrong_direction = _candidate(
            "wrong-direction",
            "iron_condor",
            ev_after_cost=160.0,
            cvar_95=1_900.0,
            robustness={"verdict": {"code": "other_direction_is_positive"}},
            structure_legs=[
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=-1.0,
                    bid=820.0,
                    ask=860.0,
                ),
                _leg(
                    "BTC-25SEP26-105000-P",
                    option_type="put",
                    strike=105_000.0,
                    quantity=1.0,
                    bid=520.0,
                    ask=560.0,
                ),
                _leg(
                    "BTC-25SEP26-130000-C",
                    option_type="call",
                    strike=130_000.0,
                    quantity=-1.0,
                    bid=980.0,
                    ask=1_040.0,
                ),
                _leg(
                    "BTC-25SEP26-135000-C",
                    option_type="call",
                    strike=135_000.0,
                    quantity=1.0,
                    bid=620.0,
                    ask=680.0,
                ),
            ],
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:no-trade",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[stale, negative_ev, wrong_direction],
            history_by_candidate=base_history,
            forecast_by_candidate=base_forecast,
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertTrue(brief["no_trade"]["active"])
        self.assertIn(
            brief["no_trade"]["primary_reason_codes"][0],
            {"STALE_MARKET_DATA", "NEGATIVE_EV_AFTER_COST", "OTHER_DIRECTION_IS_POSITIVE"},
        )

    def test_exact_scope_is_required_for_recommended_history_and_forecast(self) -> None:
        candidate, history, forecast = _candidate_with_family(
            "scope-check",
            structure_type="put_credit_spread",
            ev_after_cost=175.0,
            cvar_95=1_450.0,
            history_status="VALIDATED",
            forecast_status="CALIBRATED",
            legs=[
                _leg(
                    "BTC-25SEP26-115000-P",
                    option_type="put",
                    strike=115_000.0,
                    quantity=-1.0,
                    bid=980.0,
                    ask=1_020.0,
                ),
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=1.0,
                    bid=550.0,
                    ask=610.0,
                ),
            ],
        )
        history["scope"]["structure_type"] = "BEAR_CALL_CREDIT_SPREAD"
        forecast["scope"]["dte_band_days"] = [36, 60]

        brief = build_strategy_brief(
            analysis_run_id="analysis:scope-check",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            history_by_candidate={"scope-check": history},
            forecast_by_candidate={"scope-check": forecast},
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        strategy = brief["strategies"][0]
        self.assertEqual("WATCH", strategy["recommendation_status"])
        self.assertEqual("FAILED", strategy["history"]["status"])
        self.assertIsNone(strategy["history"]["win_rate"])
        self.assertEqual("RETIRED", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])

    def test_same_family_different_card_forecast_cannot_cross_bind(self) -> None:
        candidate, history, forecast = _candidate_with_family(
            "selection-check",
            structure_type="put_credit_spread",
            ev_after_cost=175.0,
            cvar_95=1_450.0,
            history_status="VALIDATED",
            forecast_status="CALIBRATED",
            legs=[
                _leg(
                    "BTC-25SEP26-115000-P",
                    option_type="put",
                    strike=115_000.0,
                    quantity=-1.0,
                    bid=980.0,
                    ask=1_020.0,
                ),
                _leg(
                    "BTC-25SEP26-110000-P",
                    option_type="put",
                    strike=110_000.0,
                    quantity=1.0,
                    bid=550.0,
                    ask=610.0,
                ),
            ],
        )
        forecast["selection_binding_key"] = selection_binding_key_from_scope(
            {
                "underlying": "BTC",
                "structure": "BULL_PUT_CREDIT_SPREAD",
                "direction": "BULLISH",
                "dte": {"min": 7, "max": 35},
                "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
                "exit_basis": "hold_to_expiry_cash_settlement",
                "selection": {
                    "expiry_date": "2026-09-25",
                    "legs": [
                        {
                            "instrument_name": "BTC-25SEP26-116000-P",
                            "option_type": "put",
                            "strike": 116_000.0,
                            "quantity": -1.0,
                        },
                        {
                            "instrument_name": "BTC-25SEP26-111000-P",
                            "option_type": "put",
                            "strike": 111_000.0,
                            "quantity": 1.0,
                        },
                    ],
                },
            }
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:selection-mismatch",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            history_by_candidate={"selection-check": history},
            forecast_by_candidate={"selection-check": forecast},
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        strategy = brief["strategies"][0]
        self.assertEqual("RECOMMENDED", strategy["recommendation_status"])
        self.assertEqual("RETIRED", strategy["forecast"]["status"])
        self.assertIn("FORECAST_SELECTION_MISMATCH", strategy["primary_reason_codes"])

    def test_validated_history_requires_bound_protocol_identity(self) -> None:
        candidate, history, forecast = _candidate_with_family(
            "history-binding-check",
            structure_type="call_credit_spread",
            ev_after_cost=190.0,
            cvar_95=1_700.0,
            history_status="VALIDATED",
            forecast_status="UNAVAILABLE",
            legs=[
                _leg(
                    "BTC-25SEP26-128000-C",
                    option_type="call",
                    strike=128_000.0,
                    quantity=-1.0,
                    bid=1_100.0,
                    ask=1_150.0,
                ),
                _leg(
                    "BTC-25SEP26-132000-C",
                    option_type="call",
                    strike=132_000.0,
                    quantity=1.0,
                    bid=650.0,
                    ask=700.0,
                ),
            ],
        )
        history["history_binding_key"] = expected_history_binding_key(
            "BULL_PUT_CREDIT_SPREAD"
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:history-binding",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            history_by_candidate={"history-binding-check": history},
            forecast_by_candidate={"history-binding-check": forecast},
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        strategy = brief["strategies"][0]
        self.assertEqual("FAILED", strategy["history"]["status"])
        self.assertIsNone(strategy["history"]["win_rate"])
        self.assertEqual("WATCH", strategy["recommendation_status"])

    def test_inverse_unit_candidates_fail_closed_without_verified_unit_safe_risk(self) -> None:
        candidate = _candidate(
            "inverse-reject",
            "call_credit_spread",
            premium_currency="BTC",
            premium_unit="inverse_base_currency",
            settlement_currency="USD",
            payoff_currency="USD",
            ev_after_cost=210.0,
            cvar_95=1_600.0,
            structure_legs=[
                _leg(
                    "BTC-25SEP26-128000-C",
                    option_type="call",
                    strike=128_000.0,
                    quantity=-1.0,
                    bid=0.011,
                    ask=0.0115,
                    premium_unit="inverse_base_currency",
                ),
                _leg(
                    "BTC-25SEP26-132000-C",
                    option_type="call",
                    strike=132_000.0,
                    quantity=1.0,
                    bid=0.0065,
                    ask=0.007,
                    premium_unit="inverse_base_currency",
                ),
            ],
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:inverse",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            policy_ttl_seconds=600,
        )

        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual(1, brief["evidence_summary"]["rejection_counts"]["UNIT_MISMATCH"])

    def test_triggered_kills_reject_but_untriggered_conditions_still_display(self) -> None:
        accepted, history, forecast = _candidate_with_family(
            "kill-display",
            structure_type="call_credit_spread",
            ev_after_cost=190.0,
            cvar_95=1_800.0,
            history_status="VALIDATED",
            forecast_status="UNAVAILABLE",
            legs=[
                _leg(
                    "BTC-25SEP26-128000-C",
                    option_type="call",
                    strike=128_000.0,
                    quantity=-1.0,
                    bid=1_100.0,
                    ask=1_150.0,
                ),
                _leg(
                    "BTC-25SEP26-132000-C",
                    option_type="call",
                    strike=132_000.0,
                    quantity=1.0,
                    bid=650.0,
                    ask=700.0,
                ),
            ],
            kill_conditions=[
                {"condition": "spot breaks 126k", "triggered": False},
                {"condition": "term structure flattens", "triggered": False},
                {"condition": "third condition", "triggered": False},
            ],
        )
        blocked = {
            **accepted,
            "candidate_id": "kill-triggered",
            "triggered_kill_conditions": ["support already broke"],
        }

        brief = build_strategy_brief(
            analysis_run_id="analysis:kill-display",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[accepted, blocked],
            history_by_candidate={
                "kill-display": history,
                "kill-triggered": history,
            },
            forecast_by_candidate={
                "kill-display": forecast,
                "kill-triggered": forecast,
            },
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual(1, len(brief["strategies"]))
        self.assertEqual(
            ["spot breaks 126k", "term structure flattens"],
            brief["strategies"][0]["kill_conditions"],
        )

    def test_grammar_hard_gates_reject_wrong_size_expiry_dte_and_units(self) -> None:
        cases = {
            "wrong-size": _candidate(
                "wrong-size",
                "call_credit_spread",
                ev_after_cost=120.0,
                cvar_95=1_600.0,
                structure_legs=[
                    _leg(
                        "BTC-25SEP26-128000-C",
                        option_type="call",
                        strike=128_000.0,
                        quantity=-5.0,
                        bid=1_100.0,
                        ask=1_150.0,
                    ),
                    _leg(
                        "BTC-25SEP26-132000-C",
                        option_type="call",
                        strike=132_000.0,
                        quantity=1.0,
                        bid=650.0,
                        ask=700.0,
                    ),
                ],
            ),
            "mixed-expiry": _candidate(
                "mixed-expiry",
                "put_credit_spread",
                ev_after_cost=120.0,
                cvar_95=1_200.0,
                structure_legs=[
                    _leg(
                        "BTC-25SEP26-115000-P",
                        option_type="put",
                        strike=115_000.0,
                        quantity=-1.0,
                        bid=980.0,
                        ask=1_020.0,
                        expiry_date="2026-09-25",
                    ),
                    _leg(
                        "BTC-02OCT26-110000-P",
                        option_type="put",
                        strike=110_000.0,
                        quantity=1.0,
                        bid=550.0,
                        ask=610.0,
                        expiry_date="2026-10-02",
                    ),
                ],
            ),
            "dte-out": _candidate(
                "dte-out",
                "iron_condor",
                ev_after_cost=130.0,
                cvar_95=2_000.0,
                dte_days=5.0,
                structure_legs=[
                    _leg("BTC-05SEP26-110000-P", option_type="put", strike=110_000.0, quantity=-1.0, bid=820.0, ask=860.0, expiry_date="2026-09-05"),
                    _leg("BTC-05SEP26-105000-P", option_type="put", strike=105_000.0, quantity=1.0, bid=520.0, ask=560.0, expiry_date="2026-09-05"),
                    _leg("BTC-05SEP26-130000-C", option_type="call", strike=130_000.0, quantity=-1.0, bid=980.0, ask=1040.0, expiry_date="2026-09-05"),
                    _leg("BTC-05SEP26-135000-C", option_type="call", strike=135_000.0, quantity=1.0, bid=620.0, ask=680.0, expiry_date="2026-09-05"),
                ],
            ),
            "unit-mismatch": _candidate(
                "unit-mismatch-legs",
                "call_credit_spread",
                ev_after_cost=120.0,
                cvar_95=1_600.0,
                structure_legs=[
                    _leg(
                        "BTC-25SEP26-128000-C",
                        option_type="call",
                        strike=128_000.0,
                        quantity=-1.0,
                        bid=1_100.0,
                        ask=1_150.0,
                        premium_unit="quote_currency",
                    ),
                    _leg(
                        "BTC-25SEP26-132000-C",
                        option_type="call",
                        strike=132_000.0,
                        quantity=1.0,
                        bid=650.0,
                        ask=700.0,
                        premium_unit="inverse_base_currency",
                    ),
                ],
            ),
        }

        expected = {
            "wrong-size": "ONE_UNIT_ONLY",
            "mixed-expiry": "MIXED_EXPIRY",
            "dte-out": "DTE_OUT_OF_RANGE",
            "unit-mismatch": "UNIT_MISMATCH",
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                brief = build_strategy_brief(
                    analysis_run_id="analysis:grammar",
                    generated_at="2026-08-30T14:30:05Z",
                    market=_market(),
                    candidates=[candidate],
                    policy_ttl_seconds=600,
                )
                self.assertEqual("NO_TRADE", brief["action"])
                self.assertEqual(1, brief["evidence_summary"]["rejection_counts"][expected[label]])


if __name__ == "__main__":
    unittest.main()
