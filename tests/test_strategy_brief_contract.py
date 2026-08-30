from __future__ import annotations

import json
import unittest
from pathlib import Path

from crypto_options_report.strategy_brief import (
    build_strategy_brief,
    validate_strategy_brief,
)
from crypto_options_report.strategy_history import expected_history_binding_key


def _market() -> dict:
    return {
        "as_of": "2026-08-30T14:30:05Z",
        "expires_at": "2026-08-30T14:35:05Z",
        "direction": "RANGE",
        "volatility": "RICH",
        "liquidity": "EXECUTABLE",
        "confidence": "HIGH",
    }


def _candidate(
    candidate_id: str,
    structure_type: str,
    *,
    settlement_currency: str = "USD",
    premium_currency: str = "USD",
    premium_unit: str = "quote_currency",
    ev_after_cost: float,
    cvar_95: float | None = None,
    cvar_95_usdc: float | None = None,
    valid_until: str = "2026-08-30T14:34:55Z",
    cost_components_complete: bool = True,
    relative_value_status: str = "AVAILABLE",
    **overrides,
) -> dict:
    path_risk = {"status": "validated_historical"}
    if cvar_95 is not None:
        path_risk["cvar_95"] = cvar_95
    if cvar_95_usdc is not None:
        path_risk["cvar_95_usdc"] = cvar_95_usdc
    base = {
        "candidate_id": candidate_id,
        "structure_type": structure_type,
        "underlying_price": 120_000.0,
        "dte_days": 26.0,
        "premium_unit": premium_unit,
        "premium_currency": premium_currency,
        "settlement_currency": settlement_currency,
        "payoff_currency": settlement_currency,
        "risk_currency": settlement_currency,
        "valid_until": valid_until,
        "cost_components_complete": cost_components_complete,
        "fees_included": True,
        "slippage_included": True,
        "legging_included": True,
        "settlement_included": True,
        "cost_model_id": "cost-model:v1",
        "cost_config_hash": "cost-config:abc123",
        "margin_known": True,
        "relative_value_status": relative_value_status,
        "ev_after_cost": ev_after_cost,
        "robustness": {"verdict": {"code": "positive_across_periods_and_execution"}},
        "path_risk": path_risk,
    }
    base.update(overrides)
    return base


def _leg(
    instrument_name: str,
    *,
    option_type: str,
    strike: float,
    quantity: float,
    bid: float,
    ask: float,
    observed_at: str = "2026-08-30T14:30:01Z",
    expiry_date: str = "2026-09-25",
    premium_unit: str = "quote_currency",
) -> dict:
    return {
        "instrument_name": instrument_name,
        "option_type": option_type,
        "strike": strike,
        "quantity": quantity,
        "market_bid": bid,
        "market_ask": ask,
        "observed_at": observed_at,
        "expiry_date": expiry_date,
        "premium_unit": premium_unit,
    }


def _bear_call() -> dict:
    return _candidate(
        "bear-call-1",
        "call_credit_spread",
        ev_after_cost=210.0,
        cvar_95=1_900.0,
        structure_legs=[
            _leg(
                "BTC-25SEP26-128000-C",
                option_type="call",
                strike=128_000.0,
                quantity=-1.0,
                bid=1_200.0,
                ask=1_250.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-132000-C",
                option_type="call",
                strike=132_000.0,
                quantity=1.0,
                bid=700.0,
                ask=800.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
        ],
    )


def _condor() -> dict:
    return _candidate(
        "condor-1",
        "iron_condor",
        ev_after_cost=180.0,
        cvar_95=2_500.0,
        structure_legs=[
            _leg(
                "BTC-25SEP26-110000-P",
                option_type="put",
                strike=110_000.0,
                quantity=-1.0,
                bid=800.0,
                ask=900.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-105000-P",
                option_type="put",
                strike=105_000.0,
                quantity=1.0,
                bid=500.0,
                ask=550.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
            _leg(
                "BTC-25SEP26-130000-C",
                option_type="call",
                strike=130_000.0,
                quantity=-1.0,
                bid=1_000.0,
                ask=1_100.0,
                observed_at="2026-08-30T14:30:01Z",
            ),
            _leg(
                "BTC-25SEP26-135000-C",
                option_type="call",
                strike=135_000.0,
                quantity=1.0,
                bid=650.0,
                ask=700.0,
                observed_at="2026-08-30T14:30:02Z",
            ),
        ],
    )


def _history() -> dict[str, dict]:
    return {
        "bear-call-1": {
            "status": "VALIDATED",
            "win_rate": 0.68,
            "mean_net_r": 0.21,
            "independent_cohorts": 12,
            "observation_count": 118,
            "exit_basis": "hold_to_expiry",
            "artifact_id": "history:bear-call-validated",
            "history_binding_key": expected_history_binding_key(
                "BEAR_CALL_CREDIT_SPREAD"
            ),
            "scope_verified": True,
            "scope": {
                "underlying": "BTC",
                "structure_type": "BEAR_CALL_CREDIT_SPREAD",
                "direction": "BEARISH",
                "dte_band_days": [7, 35],
                "entry_cost_basis": "SHORT_BID_LONG_ASK",
                "exit_basis": "hold_to_expiry",
            },
        },
        "condor-1": {
            "status": "EXPLORATORY",
            "win_rate": 0.61,
            "mean_net_r": 0.12,
            "independent_cohorts": 5,
            "observation_count": 44,
            "exit_basis": "hold_to_expiry",
            "artifact_id": "history:condor-exploratory",
        },
    }


def _forecast() -> dict[str, dict]:
    return {
        "bear-call-1": {
            "schema_version": "strategy_forecast.v1",
            "status": "SCREENING_ONLY",
            "win_rate_low": 0.55,
            "win_rate_high": 0.62,
            "confidence": "MEDIUM",
            "scope": {
                "underlying": "BTC",
                "structure_type": "BEAR_CALL_CREDIT_SPREAD",
                "direction": "BEARISH",
                "dte_band_days": [7, 35],
                "entry_cost_basis": "SHORT_BID_LONG_ASK",
                "exit_basis": "hold_to_expiry",
            },
            "artifact_id": "forecast:screening-only",
        },
        "condor-1": {
            "schema_version": "strategy_forecast.v1",
            "status": "UNAVAILABLE",
            "win_rate_low": 0.40,
            "win_rate_high": 0.50,
            "confidence": "LOW",
            "scope": {
                "underlying": "BTC",
                "structure_type": "IRON_CONDOR",
                "direction": "RANGE",
                "dte_band_days": [7, 35],
                "entry_cost_basis": "SHORT_BID_LONG_ASK",
                "exit_basis": "hold_to_expiry",
            },
            "artifact_id": "forecast:unavailable",
        },
    }


def _selection_scope(
    *,
    structure: str,
    direction: str,
    expiry_date: str,
    legs: list[dict],
) -> dict[str, object]:
    return {
        "underlying": "BTC",
        "structure": structure,
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


class StrategyBriefContractTests(unittest.TestCase):
    def test_golden_contract_is_stable_and_valid(self) -> None:
        brief = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[_bear_call(), _condor()],
            history_by_candidate=_history(),
            forecast_by_candidate=_forecast(),
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual(
            brief,
            json.loads(self._fixture_path().read_text(encoding="utf-8")),
        )

    def test_brief_id_is_deterministic_for_the_same_payload(self) -> None:
        left = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[_bear_call(), _condor()],
            history_by_candidate=_history(),
            forecast_by_candidate=_forecast(),
            policy_ttl_seconds=600,
        )
        right = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[_bear_call(), _condor()],
            history_by_candidate=_history(),
            forecast_by_candidate=_forecast(),
            policy_ttl_seconds=600,
        )

        self.assertEqual(left["brief_id"], right["brief_id"])
        self.assertEqual(left, right)

    def test_non_promoted_history_and_forecast_are_null_suppressed(self) -> None:
        brief = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[_condor()],
            history_by_candidate=_history(),
            forecast_by_candidate=_forecast(),
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        strategy = brief["strategies"][0]
        self.assertEqual("WATCH", strategy["recommendation_status"])
        self.assertEqual("EXPLORATORY", strategy["history"]["status"])
        self.assertIsNone(strategy["history"]["win_rate"])
        self.assertIsNone(strategy["history"]["mean_net_r"])
        self.assertEqual("UNAVAILABLE", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])
        self.assertIsNone(strategy["forecast"]["win_rate_high"])

    def test_absolute_ev_path_risk_accepts_production_cvar_95_usdc_shape(self) -> None:
        candidate = _candidate(
            "bear-call-prod-shape",
            "call_credit_spread",
            ev_after_cost=210.0,
            cvar_95_usdc=1_900.0,
            structure_legs=_bear_call()["structure_legs"],
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            history_by_candidate={},
            forecast_by_candidate={},
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("WATCH", brief["action"])
        self.assertEqual(1_900.0, brief["strategies"][0]["risk"]["cvar_95"])

    def test_path_risk_cvar_conflict_rejects_candidate_fail_closed(self) -> None:
        candidate = _candidate(
            "bear-call-conflict",
            "call_credit_spread",
            ev_after_cost=210.0,
            cvar_95=1_900.0,
            cvar_95_usdc=1_901.0,
            structure_legs=_bear_call()["structure_legs"],
        )

        brief = build_strategy_brief(
            analysis_run_id="analysis:brief-contract",
            generated_at="2026-08-30T14:30:05Z",
            market=_market(),
            candidates=[candidate],
            history_by_candidate={},
            forecast_by_candidate={},
            policy_ttl_seconds=600,
        )

        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual([], brief["strategies"])
        self.assertIn(
            "MISSING_VALIDATED_PATH_RISK",
            brief["no_trade"]["primary_reason_codes"],
        )

    @staticmethod
    def _fixture_path() -> Path:
        return (
            Path(__file__).with_name("fixtures")
            / "strategy_brief"
            / "golden_strategy_brief_v1.json"
        )


if __name__ == "__main__":
    unittest.main()
