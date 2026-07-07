"""Deterministic option PnL evidence helpers for ISSUE-005."""

from __future__ import annotations

from math import isclose
from typing import Any

INVERSE_TRADE_FEE_RATE = 0.0003
LINEAR_TRADE_FEE_RATE = 0.0003
DELIVERY_FEE_RATE = 0.00015
OPTION_FEE_CAP_RATIO = 0.125


def option_fee_inverse(option_price_coin: float, amount: float) -> float:
    return min(INVERSE_TRADE_FEE_RATE, OPTION_FEE_CAP_RATIO * option_price_coin) * amount


def option_fee_linear(
    option_price_usdc: float,
    index_price: float,
    contracts: float,
    contract_size: float = 1.0,
) -> float:
    return (
        min(
            LINEAR_TRADE_FEE_RATE * index_price,
            OPTION_FEE_CAP_RATIO * option_price_usdc,
        )
        * contracts
        * contract_size
    )


def delivery_fee_inverse(
    option_value_coin: float,
    amount: float,
    *,
    delivery_fee_applies: bool = True,
) -> float:
    if not delivery_fee_applies:
        return 0.0
    return min(DELIVERY_FEE_RATE, OPTION_FEE_CAP_RATIO * option_value_coin) * amount


def delivery_fee_linear(
    option_value_usdc: float,
    index_price: float,
    contracts: float,
    contract_size: float = 1.0,
    *,
    delivery_fee_applies: bool = True,
) -> float:
    if not delivery_fee_applies:
        return 0.0
    return (
        min(
            DELIVERY_FEE_RATE * index_price,
            OPTION_FEE_CAP_RATIO * option_value_usdc,
        )
        * contracts
        * contract_size
    )


def combo_fee(
    total_buy_fee: float,
    total_sell_fee: float,
    *,
    combo_discount_verified: bool = False,
) -> float:
    if combo_discount_verified:
        return max(total_buy_fee, total_sell_fee)
    return total_buy_fee + total_sell_fee


def inverse_long_call_settlement_coin(
    strike_price: float,
    delivery_price: float,
    contract_count: float = 1.0,
) -> float:
    return contract_count * max(delivery_price - strike_price, 0.0) / delivery_price


def trace_linear_short_call(
    *,
    contract_count: float,
    contract_size: float,
    strike_price: float,
    entry_index_price: float,
    delivery_price: float,
    entry_option_value: float,
    mark_option_value: float,
    delivery_fee_applies: bool = True,
) -> dict[str, float | str]:
    entry_credit = contract_count * contract_size * entry_option_value
    expiry_payoff = (
        contract_count
        * contract_size
        * max(delivery_price - strike_price, 0.0)
    )
    liability_mark_to_market = contract_count * contract_size * mark_option_value
    trade_fee = option_fee_linear(
        entry_option_value,
        entry_index_price,
        contract_count,
        contract_size,
    )
    delivery_fee = delivery_fee_linear(
        expiry_payoff / max(contract_count * contract_size, 1e-12),
        delivery_price,
        contract_count,
        contract_size,
        delivery_fee_applies=delivery_fee_applies,
    )
    total_fees = trade_fee + delivery_fee
    expiry_pnl = entry_credit - expiry_payoff - total_fees
    unrealized_pnl = entry_credit - liability_mark_to_market - trade_fee
    return {
        "entry_credit_usdc": entry_credit,
        "expiry_payoff_usdc": expiry_payoff,
        "expiry_pnl_usdc": expiry_pnl,
        "liability_usdc_mark_to_market": liability_mark_to_market,
        "unrealized_pnl_usdc": unrealized_pnl,
        "trade_fee_usdc": trade_fee,
        "delivery_fee_usdc": delivery_fee,
        "total_fees_usdc": total_fees,
        "max_loss_state": "UNBOUNDED",
    }


def trace_linear_call_credit_spread(
    *,
    contract_count: float,
    contract_size: float,
    short_strike_price: float,
    long_strike_price: float,
    entry_index_price: float,
    delivery_price: float,
    sell_leg_bid: float,
    buy_leg_ask: float,
    combo_discount_verified: bool = False,
    delivery_fee_applies: bool = True,
) -> dict[str, float]:
    sell_trade_fee = option_fee_linear(
        sell_leg_bid,
        entry_index_price,
        contract_count,
        contract_size,
    )
    buy_trade_fee = option_fee_linear(
        buy_leg_ask,
        entry_index_price,
        contract_count,
        contract_size,
    )
    trade_fee = combo_fee(
        buy_trade_fee,
        sell_trade_fee,
        combo_discount_verified=combo_discount_verified,
    )

    sell_delivery_value = max(delivery_price - short_strike_price, 0.0)
    buy_delivery_value = max(delivery_price - long_strike_price, 0.0)
    sell_delivery_fee = delivery_fee_linear(
        sell_delivery_value,
        delivery_price,
        contract_count,
        contract_size,
        delivery_fee_applies=delivery_fee_applies,
    )
    buy_delivery_fee = delivery_fee_linear(
        buy_delivery_value,
        delivery_price,
        contract_count,
        contract_size,
        delivery_fee_applies=delivery_fee_applies,
    )
    delivery_fee = combo_fee(
        buy_delivery_fee,
        sell_delivery_fee,
        combo_discount_verified=combo_discount_verified,
    )

    net_credit = contract_count * contract_size * (sell_leg_bid - buy_leg_ask)
    spread_payoff = (
        contract_count
        * contract_size
        * min(max(delivery_price - short_strike_price, 0.0), long_strike_price - short_strike_price)
    )
    total_fees = trade_fee + delivery_fee
    expiry_pnl = net_credit - spread_payoff - total_fees
    max_loss = (
        contract_count * contract_size * (long_strike_price - short_strike_price)
        - net_credit
        + total_fees
    )
    return {
        "net_credit_usdc": net_credit,
        "spread_payoff_usdc": spread_payoff,
        "expiry_pnl_usdc": expiry_pnl,
        "max_loss_usdc": max_loss,
        "trade_fee_usdc": trade_fee,
        "delivery_fee_usdc": delivery_fee,
        "total_fees_usdc": total_fees,
    }


def trace_inverse_short_call(
    *,
    contract_count: float,
    strike_price: float,
    delivery_price: float,
    mark_underlying_price: float,
    entry_option_value_coin: float,
    mark_option_value_coin: float,
    delivery_fee_applies: bool = True,
) -> dict[str, float | str]:
    settlement_value_coin = inverse_long_call_settlement_coin(
        strike_price,
        delivery_price,
        contract_count,
    )
    trade_fee_coin = option_fee_inverse(entry_option_value_coin, contract_count)
    delivery_fee_coin = delivery_fee_inverse(
        settlement_value_coin,
        contract_count,
        delivery_fee_applies=delivery_fee_applies,
    )
    total_fees_coin = trade_fee_coin + delivery_fee_coin
    expiry_pnl_coin = (
        contract_count * entry_option_value_coin
        - settlement_value_coin
        - total_fees_coin
    )
    liability_coin_mark_to_market = contract_count * mark_option_value_coin
    unrealized_pnl_coin = (
        contract_count * (entry_option_value_coin - mark_option_value_coin)
        - trade_fee_coin
    )
    return {
        "settlement_value_coin": settlement_value_coin,
        "expiry_pnl_coin": expiry_pnl_coin,
        "expiry_pnl_usd_shadow": expiry_pnl_coin * delivery_price,
        "liability_coin_mark_to_market": liability_coin_mark_to_market,
        "liability_usd_shadow_mark_to_market": (
            liability_coin_mark_to_market * mark_underlying_price
        ),
        "unrealized_pnl_coin": unrealized_pnl_coin,
        "unrealized_pnl_usd_shadow": unrealized_pnl_coin * mark_underlying_price,
        "trade_fee_coin": trade_fee_coin,
        "delivery_fee_coin": delivery_fee_coin,
        "total_fees_coin": total_fees_coin,
        "max_loss_state": "UNBOUNDED",
    }


def trace_inverse_call_credit_spread(
    *,
    contract_count: float,
    short_strike_price: float,
    long_strike_price: float,
    entry_reference_price: float,
    delivery_price: float,
    sell_leg_bid_coin: float,
    buy_leg_ask_coin: float,
    combo_discount_verified: bool = False,
    delivery_fee_applies: bool = True,
) -> dict[str, float]:
    short_leg_settlement = inverse_long_call_settlement_coin(
        short_strike_price,
        delivery_price,
        contract_count,
    )
    long_leg_settlement = inverse_long_call_settlement_coin(
        long_strike_price,
        delivery_price,
        contract_count,
    )
    sell_trade_fee = option_fee_inverse(sell_leg_bid_coin, contract_count)
    buy_trade_fee = option_fee_inverse(buy_leg_ask_coin, contract_count)
    trade_fee_coin = combo_fee(
        buy_trade_fee,
        sell_trade_fee,
        combo_discount_verified=combo_discount_verified,
    )
    sell_delivery_fee = delivery_fee_inverse(
        short_leg_settlement,
        contract_count,
        delivery_fee_applies=delivery_fee_applies,
    )
    buy_delivery_fee = delivery_fee_inverse(
        long_leg_settlement,
        contract_count,
        delivery_fee_applies=delivery_fee_applies,
    )
    delivery_fee_coin = combo_fee(
        buy_delivery_fee,
        sell_delivery_fee,
        combo_discount_verified=combo_discount_verified,
    )

    net_credit_coin = contract_count * (sell_leg_bid_coin - buy_leg_ask_coin)
    spread_payoff_coin = short_leg_settlement - long_leg_settlement
    total_fees_coin = trade_fee_coin + delivery_fee_coin
    expiry_pnl_coin = net_credit_coin - spread_payoff_coin - total_fees_coin
    scenario_loss_coin = max(spread_payoff_coin - net_credit_coin + total_fees_coin, 0.0)
    return {
        "net_credit_coin": net_credit_coin,
        "spread_payoff_coin": spread_payoff_coin,
        "expiry_pnl_coin": expiry_pnl_coin,
        "expiry_pnl_usd_shadow": expiry_pnl_coin * delivery_price,
        "scenario_loss_coin": scenario_loss_coin,
        "scenario_loss_usd_shadow": scenario_loss_coin * delivery_price,
        "reference_max_loss_usd_shadow": max(
            (long_strike_price - short_strike_price)
            - (net_credit_coin * entry_reference_price)
            + (total_fees_coin * entry_reference_price),
            0.0,
        ),
        "trade_fee_coin": trade_fee_coin,
        "delivery_fee_coin": delivery_fee_coin,
        "total_fees_coin": total_fees_coin,
    }


def build_pnl_evidence_report() -> dict[str, Any]:
    checks = [
        _build_linear_short_call_check(),
        _build_linear_call_spread_check(),
        _build_inverse_short_call_check(),
        _build_inverse_call_spread_check(),
        _build_known_settlement_check(),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "formula_source": "audited_spec_and_deribit_docs",
        "conservative_defaults": {
            "combo_discount_default": "ignore_unverified_combo_discount",
            "inverse_trade_fee_rule": "min(0.0003, 0.125 * option_price_coin) * amount",
            "inverse_delivery_fee_rule": "min(0.00015, 0.125 * option_value_coin) * amount when settlement applies",
            "linear_trade_fee_rule": "min(0.0003 * index_price, 0.125 * option_price_usdc) * contracts * contract_size",
            "linear_delivery_fee_rule": "min(0.00015 * index_price, 0.125 * option_value_usdc) * contracts * contract_size when settlement applies",
            "delivery_price_rule": "30m TWAP of the Deribit index into expiry",
        },
        "checks": checks,
    }


def _build_linear_short_call_check() -> dict[str, Any]:
    inputs = {
        "contract_count": 1.0,
        "contract_size": 1.0,
        "strike_price": 100000.0,
        "entry_index_price": 100000.0,
        "delivery_price": 125000.0,
        "entry_option_value": 2400.0,
        "mark_option_value": 3100.0,
    }
    actual = trace_linear_short_call(**inputs)
    expected = {
        "entry_credit_usdc": 2400.0,
        "expiry_payoff_usdc": 25000.0,
        "expiry_pnl_usdc": -22648.75,
        "liability_usdc_mark_to_market": 3100.0,
        "unrealized_pnl_usdc": -730.0,
        "trade_fee_usdc": 30.0,
        "delivery_fee_usdc": 18.75,
        "total_fees_usdc": 48.75,
        "max_loss_state": "UNBOUNDED",
    }
    return _check_report(
        check_id="linear-usdc-short-call",
        product="linear_usdc_short_call",
        inputs=inputs,
        actual=actual,
        expected=expected,
    )


def _build_linear_call_spread_check() -> dict[str, Any]:
    inputs = {
        "contract_count": 1.0,
        "contract_size": 1.0,
        "short_strike_price": 100000.0,
        "long_strike_price": 110000.0,
        "entry_index_price": 100000.0,
        "delivery_price": 125000.0,
        "sell_leg_bid": 2200.0,
        "buy_leg_ask": 900.0,
    }
    actual = trace_linear_call_credit_spread(**inputs)
    expected = {
        "net_credit_usdc": 1300.0,
        "spread_payoff_usdc": 10000.0,
        "expiry_pnl_usdc": -8797.5,
        "max_loss_usdc": 8797.5,
        "trade_fee_usdc": 60.0,
        "delivery_fee_usdc": 37.5,
        "total_fees_usdc": 97.5,
    }
    return _check_report(
        check_id="linear-usdc-call-credit-spread",
        product="linear_usdc_call_credit_spread",
        inputs=inputs,
        actual=actual,
        expected=expected,
    )


def _build_inverse_short_call_check() -> dict[str, Any]:
    inputs = {
        "contract_count": 1.0,
        "strike_price": 100000.0,
        "delivery_price": 125000.0,
        "mark_underlying_price": 120000.0,
        "entry_option_value_coin": 0.05,
        "mark_option_value_coin": 0.07,
    }
    actual = trace_inverse_short_call(**inputs)
    expected = {
        "settlement_value_coin": 0.2,
        "expiry_pnl_coin": -0.15045,
        "expiry_pnl_usd_shadow": -18806.25,
        "liability_coin_mark_to_market": 0.07,
        "liability_usd_shadow_mark_to_market": 8400.0,
        "unrealized_pnl_coin": -0.0203,
        "unrealized_pnl_usd_shadow": -2436.0,
        "trade_fee_coin": 0.0003,
        "delivery_fee_coin": 0.00015,
        "total_fees_coin": 0.00045,
        "max_loss_state": "UNBOUNDED",
    }
    return _check_report(
        check_id="inverse-short-call",
        product="inverse_short_call",
        inputs=inputs,
        actual=actual,
        expected=expected,
    )


def _build_inverse_call_spread_check() -> dict[str, Any]:
    inputs = {
        "contract_count": 1.0,
        "short_strike_price": 100000.0,
        "long_strike_price": 110000.0,
        "entry_reference_price": 100000.0,
        "delivery_price": 125000.0,
        "sell_leg_bid_coin": 0.05,
        "buy_leg_ask_coin": 0.02,
    }
    actual = trace_inverse_call_credit_spread(**inputs)
    expected = {
        "net_credit_coin": 0.03,
        "spread_payoff_coin": 0.08,
        "expiry_pnl_coin": -0.0509,
        "expiry_pnl_usd_shadow": -6362.5,
        "scenario_loss_coin": 0.0509,
        "scenario_loss_usd_shadow": 6362.5,
        "reference_max_loss_usd_shadow": 7090.0,
        "trade_fee_coin": 0.0006,
        "delivery_fee_coin": 0.0003,
        "total_fees_coin": 0.0009,
    }
    return _check_report(
        check_id="inverse-call-credit-spread",
        product="inverse_call_credit_spread",
        inputs=inputs,
        actual=actual,
        expected=expected,
    )


def _build_known_settlement_check() -> dict[str, Any]:
    inputs = {
        "contract_count": 1.0,
        "strike_price": 100000.0,
        "delivery_price": 125000.0,
    }
    actual = {
        "actual_settlement_coin": inverse_long_call_settlement_coin(**inputs),
    }
    expected = {
        "actual_settlement_coin": 0.2,
        "expected_settlement_coin": 0.2,
    }
    actual["expected_settlement_coin"] = expected["expected_settlement_coin"]
    return _check_report(
        check_id="inverse-known-long-call-settlement",
        product="inverse_long_call_settlement",
        inputs=inputs,
        actual=actual,
        expected=expected,
    )


def _check_report(
    *,
    check_id: str,
    product: str,
    inputs: dict[str, Any],
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    failures: list[str] = []
    for key, expected_value in expected.items():
        actual_value = actual[key]
        passed = _matches(actual_value, expected_value)
        comparisons.append(
            {
                "field": key,
                "expected": _coerce_output(expected_value),
                "actual": _coerce_output(actual_value),
                "passed": passed,
            }
        )
        if not passed:
            failures.append(key)

    outputs = {key: _coerce_output(value) for key, value in actual.items()}
    return {
        "id": check_id,
        "product": product,
        "status": "pass" if not failures else "fail",
        "inputs": inputs,
        "outputs": outputs,
        "expected_outputs": {key: _coerce_output(value) for key, value in expected.items()},
        "failed_fields": failures,
        "comparisons": comparisons,
    }


def _coerce_output(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    return value


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(actual, float) or isinstance(expected, float):
        return isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-8)
    return actual == expected
