from __future__ import annotations

import unittest

from crypto_options_report.strategy_brief import (
    build_strategy_brief,
    validate_strategy_brief,
)
from crypto_options_report.strategy_forecast import selection_binding_key_from_scope
from crypto_options_report.strategy_history import expected_history_binding_key
from tests.test_strategy_brief_contract import _candidate, _leg, _market


def _build_brief(
    *,
    candidates: list[dict],
    history_by_candidate: dict[str, dict] | None = None,
    forecast_by_candidate: dict[str, dict] | None = None,
    generated_at: str = "2026-08-30T14:30:05Z",
    market_overrides: dict | None = None,
) -> dict:
    market = _market()
    if market_overrides:
        market.update(market_overrides)
    return build_strategy_brief(
        analysis_run_id="analysis:brief-hard-gates",
        generated_at=generated_at,
        market=market,
        candidates=candidates,
        history_by_candidate=history_by_candidate or {},
        forecast_by_candidate=forecast_by_candidate or {},
        policy_ttl_seconds=600,
    )


def _history(
    status: str,
    structure_type: str = "BEAR_CALL_CREDIT_SPREAD",
) -> dict[str, object]:
    direction = {
        "BEAR_CALL_CREDIT_SPREAD": "BEARISH",
        "BULL_PUT_CREDIT_SPREAD": "BULLISH",
        "IRON_CONDOR": "RANGE",
    }[structure_type]
    return {
        "status": status,
        "win_rate": 0.67,
        "mean_net_r": 0.19,
        "independent_cohorts": 12,
        "observation_count": 118,
        "exit_basis": "hold_to_expiry",
        "artifact_id": f"history:{status.lower()}",
        "history_binding_key": (
            expected_history_binding_key(structure_type)
            if status == "VALIDATED"
            else None
        ),
        "scope_verified": status == "VALIDATED",
        "scope": {
            "underlying": "BTC",
            "structure_type": structure_type,
            "direction": direction,
            "dte_band_days": [7, 35],
            "entry_cost_basis": "SHORT_BID_LONG_ASK",
            "exit_basis": "hold_to_expiry",
        },
    }


def _forecast(
    status: str,
    *,
    structure_type: str = "BEAR_CALL_CREDIT_SPREAD",
    direction: str = "BEARISH",
    expiry_date: str = "2026-09-25",
    legs: list[dict] | None = None,
) -> dict[str, object]:
    selection_binding_key = None
    if status == "CALIBRATED" and legs is not None:
        selection_binding_key = selection_binding_key_from_scope(
            {
                "underlying": "BTC",
                "structure": structure_type,
                "direction": direction,
                "dte": {"min": 7, "max": 35},
                "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
                "exit_basis": "hold_to_expiry_cash_settlement",
                "selection": {
                    "expiry_date": expiry_date,
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
        )
    return {
        "status": status,
        "win_rate_low": 0.58,
        "win_rate_high": 0.65,
        "confidence": "MEDIUM",
        "scope": "BTC · aligned",
        "artifact_id": f"forecast:{status.lower()}",
        "selection_binding_key": selection_binding_key,
    }


def _bear_call(
    candidate_id: str,
    *,
    ev_after_cost: float = 210.0,
    cvar_95: float | None = 1_900.0,
    valid_until: str = "2026-08-30T14:34:55Z",
    structure_legs: list[dict] | None = None,
    **overrides,
) -> dict:
    payload: dict[str, object] = {
        "candidate_id": candidate_id,
        "structure_type": "call_credit_spread",
        "ev_after_cost": ev_after_cost,
        "valid_until": valid_until,
        "structure_legs": structure_legs
        or [
            _leg(
                "BTC-25SEP26-128000-C",
                option_type="call",
                strike=128_000.0,
                quantity=-1.0,
                bid=1_100.0,
                ask=1_150.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-132000-C",
                option_type="call",
                strike=132_000.0,
                quantity=1.0,
                bid=650.0,
                ask=700.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
        ],
    }
    if cvar_95 is not None:
        payload["cvar_95"] = cvar_95
    return _candidate(**payload, **overrides)


def _bull_put(
    candidate_id: str,
    *,
    ev_after_cost: float = 170.0,
    cvar_95: float | None = 1_400.0,
    valid_until: str = "2026-08-30T14:34:55Z",
    structure_legs: list[dict] | None = None,
    **overrides,
) -> dict:
    payload: dict[str, object] = {
        "candidate_id": candidate_id,
        "structure_type": "put_credit_spread",
        "ev_after_cost": ev_after_cost,
        "valid_until": valid_until,
        "structure_legs": structure_legs
        or [
            _leg(
                "BTC-25SEP26-115000-P",
                option_type="put",
                strike=115_000.0,
                quantity=-1.0,
                bid=980.0,
                ask=1_020.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-110000-P",
                option_type="put",
                strike=110_000.0,
                quantity=1.0,
                bid=550.0,
                ask=610.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
        ],
    }
    if cvar_95 is not None:
        payload["cvar_95"] = cvar_95
    return _candidate(**payload, **overrides)


def _condor(
    candidate_id: str,
    *,
    ev_after_cost: float = 160.0,
    cvar_95: float | None = 2_200.0,
    valid_until: str = "2026-08-30T14:34:55Z",
    structure_legs: list[dict] | None = None,
    **overrides,
) -> dict:
    payload: dict[str, object] = {
        "candidate_id": candidate_id,
        "structure_type": "iron_condor",
        "ev_after_cost": ev_after_cost,
        "valid_until": valid_until,
        "structure_legs": structure_legs
        or [
            _leg(
                "BTC-25SEP26-110000-P",
                option_type="put",
                strike=110_000.0,
                quantity=-1.0,
                bid=820.0,
                ask=860.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-105000-P",
                option_type="put",
                strike=105_000.0,
                quantity=1.0,
                bid=520.0,
                ask=560.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
            _leg(
                "BTC-25SEP26-130000-C",
                option_type="call",
                strike=130_000.0,
                quantity=-1.0,
                bid=980.0,
                ask=1_040.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-135000-C",
                option_type="call",
                strike=135_000.0,
                quantity=1.0,
                bid=620.0,
                ask=680.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
        ],
    }
    if cvar_95 is not None:
        payload["cvar_95"] = cvar_95
    return _candidate(**payload, **overrides)


class StrategyBriefHardGateTests(unittest.TestCase):
    def test_hard_gate_rejections_remove_candidates_and_increment_reason_counts(self) -> None:
        cases = (
            (
                "negative_ev",
                _bull_put("negative-ev", ev_after_cost=-1.0),
                None,
                "NEGATIVE_EV_AFTER_COST",
            ),
            (
                "other_direction_is_positive",
                _condor(
                    "wrong-way",
                    robustness={"verdict": {"code": "other_direction_is_positive"}},
                ),
                None,
                "OTHER_DIRECTION_IS_POSITIVE",
            ),
            (
                "no_capturable_edge_at_touch",
                _bear_call(
                    "no-touch-edge",
                    robustness={
                        "verdict": {"code": "no_capturable_edge_at_the_touch"}
                    },
                ),
                None,
                "NO_CAPTURABLE_EDGE_AT_TOUCH",
            ),
            (
                "unbounded_loss",
                _bear_call(
                    "naked-ish",
                    structure_legs=[
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
                            quantity=-1.0,
                            bid=700.0,
                            ask=760.0,
                        ),
                    ],
                ),
                None,
                "UNBOUNDED_LOSS_STRUCTURE",
            ),
            (
                "unknown_path_risk",
                _bull_put(
                    "missing-risk",
                    path_risk={"status": "blocked", "cvar_95": 1_400.0},
                ),
                None,
                "MISSING_VALIDATED_PATH_RISK",
            ),
            (
                "stale_quote",
                _bear_call(
                    "stale-quote",
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
                ),
                None,
                "STALE_MARKET_DATA",
            ),
            (
                "crossed_quotes",
                _bear_call(
                    "crossed",
                    structure_legs=[
                        _leg(
                            "BTC-25SEP26-128000-C",
                            option_type="call",
                            strike=128_000.0,
                            quantity=-1.0,
                            bid=1_200.0,
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
                None,
                "CROSSED_MARKET_QUOTES",
            ),
            (
                "leg_sync_over_2s",
                _bull_put(
                    "unsynced",
                    structure_legs=[
                        _leg(
                            "BTC-25SEP26-115000-P",
                            option_type="put",
                            strike=115_000.0,
                            quantity=-1.0,
                            bid=980.0,
                            ask=1_020.0,
                            observed_at="2026-08-30T14:30:01Z",
                        ),
                        _leg(
                            "BTC-25SEP26-110000-P",
                            option_type="put",
                            strike=110_000.0,
                            quantity=1.0,
                            bid=550.0,
                            ask=610.0,
                            observed_at="2026-08-30T14:30:04Z",
                        ),
                    ],
                ),
                None,
                "LEGS_NOT_SYNCHRONIZED",
            ),
            (
                "market_expired",
                _bear_call("expired-market"),
                {"expires_at": "2026-08-30T14:30:04Z"},
                "STALE_MARKET_DATA",
            ),
            (
                "candidate_expired",
                _condor("expired-candidate", valid_until="2026-08-30T14:30:04Z"),
                None,
                "STRATEGY_EXPIRED",
            ),
            (
                "triggered_kill",
                _bull_put(
                    "kill-hit",
                    kill_conditions=[
                        {"condition": "spot breaks support", "triggered": True}
                    ],
                ),
                None,
                "KILL_CONDITION_HIT",
            ),
            (
                "missing_costs",
                _bear_call("missing-costs", cost_components_complete=False),
                None,
                "MISSING_COST_COMPONENTS",
            ),
        )

        for label, candidate, market_overrides, expected_code in cases:
            with self.subTest(label=label):
                brief = _build_brief(
                    candidates=[candidate],
                    market_overrides=market_overrides,
                )

                self.assertEqual("NO_TRADE", brief["action"])
                self.assertEqual([], brief["strategies"])
                self.assertTrue(brief["no_trade"]["active"])
                self.assertEqual(
                    0,
                    brief["evidence_summary"]["hard_gate_pass_count"],
                )
                self.assertEqual(
                    1,
                    brief["evidence_summary"]["rejection_counts"].get(expected_code),
                )

    def test_zero_cards_shows_no_trade_without_placeholder_cards(self) -> None:
        brief = _build_brief(candidates=[])

        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertTrue(brief["no_trade"]["active"])
        self.assertEqual("今日暂无可靠策略", brief["no_trade"].get("headline_zh"))

    def test_all_watch_cards_produce_watch_action_everywhere(self) -> None:
        brief = _build_brief(candidates=[_condor("watch-only")])

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("WATCH", brief["action"])
        self.assertEqual("WATCH", brief["market"]["action"])
        self.assertEqual("WATCH", brief["strategies"][0]["recommendation_status"])
        self.assertFalse(brief["no_trade"]["active"])

    def test_unclear_or_missing_market_state_fails_closed(self) -> None:
        candidate = _condor("market-fail-closed")
        for label, market in (
            (
                "unclear",
                {
                    **_market(),
                    "direction": "UNCLEAR",
                },
            ),
            (
                "missing",
                {
                    "as_of": "2026-08-30T14:30:05Z",
                    "expires_at": "2026-08-30T14:35:05Z",
                },
            ),
        ):
            with self.subTest(label=label):
                brief = build_strategy_brief(
                    analysis_run_id="analysis:market-fail-closed",
                    generated_at="2026-08-30T14:30:05Z",
                    market=market,
                    candidates=[candidate],
                    policy_ttl_seconds=600,
                )

                self.assertEqual([], validate_strategy_brief(brief))
                self.assertEqual("NO_TRADE", brief["action"])
                self.assertEqual([], brief["strategies"])
                self.assertEqual("UNCLEAR", brief["market"]["direction"])
                if label == "missing":
                    self.assertEqual("UNKNOWN", brief["market"]["volatility"])
                    self.assertEqual("UNAVAILABLE", brief["market"]["liquidity"])
                    self.assertEqual("UNAVAILABLE", brief["market"]["confidence"])
                self.assertEqual(
                    "fallback",
                    brief["evidence_summary"]["surface"]["source_kind"],
                )

    def test_one_card_survives_when_one_family_passes(self) -> None:
        candidate = _bear_call("one-card")
        brief = _build_brief(
            candidates=[candidate],
            history_by_candidate={"one-card": _history("VALIDATED")},
        )

        self.assertEqual(1, len(brief["strategies"]))
        self.assertEqual("STRATEGIES_AVAILABLE", brief["action"])
        self.assertFalse(brief["no_trade"]["active"])
        self.assertIsNone(brief["no_trade"].get("headline_zh"))
        self.assertIsNone(brief["no_trade"].get("summary_zh"))

    def test_two_cards_render_when_two_families_pass(self) -> None:
        brief = _build_brief(
            candidates=[_bear_call("bear-two"), _bull_put("bull-two")],
            history_by_candidate={
                "bear-two": _history("VALIDATED"),
                "bull-two": _history("VALIDATED", "BULL_PUT_CREDIT_SPREAD"),
            },
        )

        self.assertEqual(2, len(brief["strategies"]))

    def test_three_cards_render_when_three_families_pass(self) -> None:
        brief = _build_brief(
            candidates=[
                _bear_call("bear-three"),
                _bull_put("bull-three"),
                _condor("condor-three"),
            ],
            history_by_candidate={
                "bear-three": _history("VALIDATED"),
                "bull-three": _history("VALIDATED", "BULL_PUT_CREDIT_SPREAD"),
                "condor-three": _history("VALIDATED", "IRON_CONDOR"),
            },
        )

        self.assertEqual(3, len(brief["strategies"]))

    def test_same_family_dedup_keeps_only_best_candidate(self) -> None:
        brief = _build_brief(
            candidates=[
                _bear_call("bear-best", ev_after_cost=220.0),
                _bear_call("bear-weaker", ev_after_cost=120.0),
                _bull_put("bull-peer"),
            ],
            history_by_candidate={
                "bear-best": _history("VALIDATED"),
                "bear-weaker": _history("VALIDATED"),
                "bull-peer": _history("VALIDATED", "BULL_PUT_CREDIT_SPREAD"),
            },
        )

        self.assertEqual(2, len(brief["strategies"]))
        self.assertEqual(
            ["BEAR_CALL_CREDIT_SPREAD", "BULL_PUT_CREDIT_SPREAD"],
            [item["structure_type"] for item in brief["strategies"]],
        )
        self.assertEqual(400.0, brief["strategies"][0]["entry"]["minimum_net_credit"])

    def test_missing_bid_ask_rejects_candidate_and_counts_reason(self) -> None:
        brief = _build_brief(
            candidates=[
                _bull_put(
                    "missing-quotes",
                    structure_legs=[
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
                            ask=None,
                        ),
                    ],
                )
            ]
        )

        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get(
                "MISSING_POSITIVE_TWO_SIDED_QUOTES"
            ),
        )

    def test_mid_mark_cannot_replace_executable_quotes(self) -> None:
        brief = _build_brief(
            candidates=[
                _bear_call(
                    "mark-only",
                    structure_legs=[
                        {
                            "instrument_name": "BTC-25SEP26-128000-C",
                            "option_type": "call",
                            "strike": 128_000.0,
                            "quantity": -1.0,
                            "observed_at": "2026-08-30T14:30:01Z",
                            "expiry_date": "2026-09-25",
                            "premium_unit": "quote_currency",
                            "mark_price": 1_125.0,
                            "mid_price": 1_125.0,
                        },
                        {
                            "instrument_name": "BTC-25SEP26-132000-C",
                            "option_type": "call",
                            "strike": 132_000.0,
                            "quantity": 1.0,
                            "observed_at": "2026-08-30T14:30:02Z",
                            "expiry_date": "2026-09-25",
                            "premium_unit": "quote_currency",
                            "mark_price": 675.0,
                            "mid_price": 675.0,
                        },
                    ],
                )
            ]
        )

        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get(
                "MISSING_POSITIVE_TWO_SIDED_QUOTES"
            ),
        )

    def test_unit_mismatch_rejects_mixed_leg_units_and_counts_reason(self) -> None:
        brief = _build_brief(
            candidates=[
                _bear_call(
                    "unit-mismatch",
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
                )
            ]
        )

        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get("UNIT_MISMATCH"),
        )

    def test_execution_allowed_is_always_false_even_with_live_cards(self) -> None:
        brief = _build_brief(
            candidates=[_bear_call("execution-guard")],
            history_by_candidate={"execution-guard": _history("VALIDATED")},
        )

        self.assertFalse(brief["execution_allowed"])

    def test_history_metrics_stay_null_until_history_is_validated(self) -> None:
        candidate = _condor("history-null")
        brief = _build_brief(
            candidates=[candidate],
            history_by_candidate={"history-null": _history("EXPLORATORY")},
            forecast_by_candidate={
                "history-null": _forecast(
                    "CALIBRATED",
                    structure_type="IRON_CONDOR",
                    direction="RANGE",
                    legs=candidate["structure_legs"],
                )
            },
        )

        strategy = brief["strategies"][0]
        self.assertEqual("EXPLORATORY", strategy["history"]["status"])
        self.assertIsNone(strategy["history"]["win_rate"])
        self.assertIsNone(strategy["history"]["mean_net_r"])

    def test_forecast_probabilities_stay_null_until_forecast_is_calibrated(self) -> None:
        brief = _build_brief(
            candidates=[_bear_call("forecast-null")],
            history_by_candidate={"forecast-null": _history("VALIDATED")},
            forecast_by_candidate={"forecast-null": _forecast("SCREENING_ONLY")},
        )

        strategy = brief["strategies"][0]
        self.assertEqual("SCREENING_ONLY", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])
        self.assertIsNone(strategy["forecast"]["win_rate_high"])

    def test_brief_hash_changes_when_payload_is_tampered(self) -> None:
        brief = _build_brief(
            candidates=[_bear_call("tamper-brief")],
            history_by_candidate={"tamper-brief": _history("VALIDATED")},
        )
        brief["action"] = "WATCH"

        errors = validate_strategy_brief(brief)

        self.assertIn(
            "strategy_brief.brief_id must match canonical payload hash",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
