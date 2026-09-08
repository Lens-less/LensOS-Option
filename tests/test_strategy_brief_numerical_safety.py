"""Regression checks for exact one-unit strategy-card economics."""

from copy import deepcopy

import pytest

from crypto_options_report.strategy_brief import validate_strategy_brief
from crypto_options_report.structures import build_structure
from tests.test_strategy_brief_contract import _bear_call, _condor
from tests.test_strategy_brief_hard_gates import _build_brief
from tests.test_strategy_brief_selection import _candidate_with_family


def test_crossed_condor_wings_cannot_understate_loss_as_one_wing() -> None:
    candidate = _condor()
    put_short, put_long, _, _ = candidate["structure_legs"]
    put_short.update(strike=140_000.0, instrument_name="BTC-25SEP26-140000-P")
    put_long.update(strike=135_000.0, instrument_name="BTC-25SEP26-135000-P")
    structure = build_structure(
        structure_type="iron_condor", legs=candidate["structure_legs"]
    )
    # Both 5,000-wide wings lose together here. The old brief used only
    # max(put_width, call_width), understating the terminal loss by 5,000.
    assert structure.amount_owed_at(135_000.0) == 10_000.0

    brief = _build_brief(candidates=[candidate])

    assert brief["strategies"] == []
    assert "UNBOUNDED_LOSS_STRUCTURE" in brief["no_trade"]["primary_reason_codes"]
    assert validate_strategy_brief(brief) == []


@pytest.mark.parametrize("field", ["contract_size", "contract_scale"])
@pytest.mark.parametrize("scale", [0.1, 10.0, 0.0, -1.0, "unknown"])
@pytest.mark.parametrize("location", ["candidate", "leg"])
def test_brief_rejects_contract_multiplier_it_cannot_publish(
    field: str, scale: object, location: str
) -> None:
    candidate = deepcopy(_bear_call())
    target = candidate if location == "candidate" else candidate["structure_legs"][0]
    target[field] = scale

    brief = _build_brief(candidates=[candidate])

    assert brief["strategies"] == []
    assert "UNIT_MISMATCH" in brief["no_trade"]["primary_reason_codes"]


def test_explicit_one_underlying_unit_remains_supported() -> None:
    candidate = _bear_call()
    candidate["contract_scale"] = 1.0
    for leg in candidate["structure_legs"]:
        leg["contract_size"] = 1.0

    brief = _build_brief(candidates=[candidate])

    assert len(brief["strategies"]) == 1
    assert validate_strategy_brief(brief) == []


def test_cost_amounts_change_net_credit_loss_budget_and_breakeven() -> None:
    candidate = _bear_call()
    strategy = _build_brief(candidates=[candidate])["strategies"][0]

    assert strategy["entry"]["minimum_net_credit"] == 400 - 72 - 20 - 10
    assert strategy["risk"]["max_loss_per_unit"] == 4_000 - 298 + 40
    assert strategy["risk"]["breakevens"] == [128_258.0]
    assert strategy["economics"]["net_r"] == round(210 / 3_742, 6)
    assert "MODELLED LOSS BUDGET PER UNIT: 3742 USD" in strategy["copy_recipe"]
    assert "ACTUAL LOSS MAY EXCEED BUDGET" in strategy["copy_recipe"]


@pytest.mark.parametrize("amount", [None, -1.0, float("nan"), float("inf"), True, "72", 10**1000])
@pytest.mark.parametrize("field", ["entry_fees", "slippage_reserve", "legging_reserve", "settlement_reserve"])
def test_included_flags_never_replace_finite_nonnegative_cost_amounts(field, amount) -> None:
    candidate = _bear_call()
    candidate["cost_breakdown"][field] = amount
    brief = _build_brief(candidates=[candidate])
    assert brief["strategies"] == []
    assert "MISSING_COST_COMPONENTS" in brief["no_trade"]["primary_reason_codes"]


def test_no_cost_breakdown_rejects_even_when_every_included_flag_is_true() -> None:
    candidate = _bear_call()
    candidate.pop("cost_breakdown")
    assert _build_brief(candidates=[candidate])["strategies"] == []


@pytest.mark.parametrize("field", ["entry_fees", "slippage_reserve", "legging_reserve", "settlement_reserve"])
def test_missing_cost_component_does_not_default_to_zero(field: str) -> None:
    candidate = _bear_call()
    candidate["cost_breakdown"].pop(field)
    assert _build_brief(candidates=[candidate])["strategies"] == []


def test_public_validator_rejects_forged_promotion_and_inconsistent_net_r() -> None:
    brief = _build_brief(candidates=[_bear_call()])
    brief["strategies"][0]["recommendation_status"] = "RECOMMENDED"
    brief["strategies"][0]["economics"]["net_r"] = 1.0
    errors = validate_strategy_brief(brief)
    assert "strategy without a verified delivery fee upper bound must remain WATCH" in errors
    assert "strategy.economics.net_r must use the stated model loss budget" in errors


def test_public_validator_rejects_model_budget_without_any_profitable_settlement() -> None:
    brief = _build_brief(candidates=[_bear_call()])
    strategy = brief["strategies"][0]
    strategy["entry"]["cost_breakdown"]["settlement_reserve"] = 400
    strategy["risk"]["max_loss_per_unit"] = 4_102
    strategy["risk"]["breakevens"] = [127_898]
    strategy["economics"]["net_r"] = round(210 / 4_102, 6)
    assert "strategy structure must have bounded positive max loss" in validate_strategy_brief(brief)


def test_forecast_binding_rejects_overflowing_cost_amount_without_crashing() -> None:
    from crypto_options_report.strategy_forecast import selection_binding_key_from_scope
    from tests.test_strategy_brief_contract import _entry_cost_identity

    candidate = _bear_call()
    entry_costs = _entry_cost_identity(candidate)
    entry_costs["cost_breakdown"]["entry_fees"] = 10**1000
    scope = {
        "underlying": "BTC", "structure": "BEAR_CALL_CREDIT_SPREAD", "direction": "BEARISH",
        "dte": {"min": 7, "max": 35},
        "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
        "exit_basis": "hold_to_expiry_cash_settlement",
        "selection": {
            "expiry_date": "2026-09-25", "legs": candidate["structure_legs"], "entry_costs": entry_costs,
        },
    }
    assert selection_binding_key_from_scope(scope) is None


@pytest.mark.parametrize("change", ["quotes", "config", "model", "budget", "legacy"])
def test_forecast_cannot_survive_entry_economics_drift(change: str) -> None:
    original = _bear_call()
    candidate, history, forecast = _candidate_with_family(
        original["candidate_id"], structure_type="call_credit_spread",
        ev_after_cost=210, cvar_95=1_900, legs=original["structure_legs"],
        history_status="VALIDATED", forecast_status="CALIBRATED",
    )
    before = _build_brief(
        candidates=[candidate], history_by_candidate={candidate["candidate_id"]: history},
        forecast_by_candidate={candidate["candidate_id"]: forecast},
    )["strategies"][0]
    assert before["forecast"]["status"] == "CALIBRATED"
    assert before["recommendation_status"] == "WATCH"
    if change == "quotes":
        candidate["structure_legs"][0]["market_bid"] -= 1
    elif change == "config":
        candidate["cost_config_hash"] += "-changed"
    elif change == "model":
        candidate["cost_model_id"] += "-changed"
    elif change == "budget":
        candidate["cost_breakdown"]["settlement_reserve"] += 1
    else:
        from crypto_options_report.strategy_forecast import (
            selection_binding_key_from_scope,
        )
        scope = {
            "underlying": "BTC", "structure": "BEAR_CALL_CREDIT_SPREAD", "direction": "BEARISH",
            "dte": {"min": 7, "max": 35},
            "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
            "exit_basis": "hold_to_expiry_cash_settlement",
            "selection": {"expiry_date": "2026-09-25", "legs": candidate["structure_legs"]},
        }
        forecast["selection_binding_key"] = selection_binding_key_from_scope(scope)
    after = _build_brief(
        candidates=[candidate], forecast_by_candidate={candidate["candidate_id"]: forecast}
    )["strategies"][0]
    assert after["forecast"]["status"] == "RETIRED"
    assert after["forecast"]["win_rate_low"] is None


def test_caller_claim_cannot_promote_a_cost_budget_to_an_absolute_bound() -> None:
    candidate = _bear_call()
    candidate["delivery_fee_upper_bound_verified"] = True
    strategy = _build_brief(candidates=[candidate])["strategies"][0]
    assert strategy["risk"]["delivery_fee_upper_bound_verified"] is False
    assert strategy["recommendation_status"] == "WATCH"


def test_settlement_budget_exhausting_credit_cannot_publish_a_fake_breakeven() -> None:
    candidate = _bear_call()
    candidate["cost_breakdown"]["settlement_reserve"] = 400
    assert _build_brief(candidates=[candidate])["strategies"] == []


def test_credit_rounding_to_zero_cannot_escape_positive_net_credit_gate() -> None:
    candidate = _bear_call()
    candidate["cost_breakdown"] = {
        "entry_fees": 399.9999999, "slippage_reserve": 0.0,
        "legging_reserve": 0.0, "settlement_reserve": 0.0,
    }
    assert _build_brief(candidates=[candidate])["strategies"] == []


@pytest.mark.parametrize("currency", ["BTC", "ETH"])
def test_coin_currency_cannot_be_subtracted_from_dollar_strike_width(currency) -> None:
    candidate = _bear_call()
    for field in ("premium_currency", "settlement_currency", "payoff_currency", "risk_currency"):
        candidate[field] = currency
    assert _build_brief(candidates=[candidate])["strategies"] == []
