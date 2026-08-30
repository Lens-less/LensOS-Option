"""Deterministic aligned replay primitives for strategy-card history evidence.

These helpers replay one fully specified, same-expiry defined-risk structure
under the frozen history protocol. They do not aggregate into win rates, do not
promote any strategy, and do not inspect any holdout decision by themselves.
They answer the narrower question: given an exact set of quoted legs and an
official expiry settlement, what was the executable one-observation outcome
under the frozen fill, fee, and settlement rules?
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from ._canonical import canonical_sha256
from .pnl import delivery_fee_linear, option_fee_linear
from .strategy_history import (
    EMBARGO_DAYS,
    SUPPORTED_STRUCTURES,
)
from .structures import Structure, build_structure

STRATEGY_REPLAY_OBSERVATION_SCHEMA_VERSION = "strategy_replay_observation.v1"
STRATEGY_REPLAY_LEDGER_SCHEMA_VERSION = "strategy_replay_ledger.v1"
ENTRY_COST_BASIS = "SHORT_BID_LONG_ASK_WITH_ADVERSE_TICK"
SETTLEMENT_BASIS = "official_expiry_settlement"
SYNC_TOLERANCE_SECONDS = 2.0
LINEAR_PREMIUM_UNIT = "quote_currency"
SAMPLE_ROLE_VALUES = frozenset({"development", "holdout"})
SOURCE_CLASSIFICATION_VALUES = frozenset(
    {"development_inventory", "future_holdout"}
)


def build_strategy_replay_observation(
    *,
    structure_type: str,
    protocol: dict[str, Any],
    legs: list[dict[str, Any]],
    settlement: dict[str, Any],
    regimes: dict[str, Any] | None = None,
    selection_slot: str,
    fold_id: str,
    label_window_id: str | None = None,
) -> dict[str, Any]:
    """Replay one structure observation under the frozen aligned protocol."""

    if structure_type not in SUPPORTED_STRUCTURES:
        raise ValueError(f"unsupported strategy replay structure: {structure_type!r}")
    _require_protocol_alignment(protocol, structure_type)

    normalized_legs = _normalize_legs(legs)
    structure = _build_supported_structure(structure_type, normalized_legs)
    normalized_settlement = _normalize_settlement(
        settlement=settlement,
        expiry_date=structure.expiry_date,
        quote_currency=normalized_legs[0]["quote_currency"],
    )
    entry_observed_at = max(leg["observed_at_dt"] for leg in normalized_legs)
    if normalized_settlement["settlement_at_dt"] <= entry_observed_at:
        raise ValueError("settlement must occur after entry observation time")
    if normalized_settlement["published_at_dt"] < normalized_settlement["settlement_at_dt"]:
        raise ValueError("settlement published_at must be at or after settlement_at")
    if normalized_settlement["published_at_dt"] <= entry_observed_at:
        raise ValueError("settlement publication must not be visible at entry selection time")

    synced_seconds = (
        max(leg["observed_at_dt"] for leg in normalized_legs)
        - min(leg["observed_at_dt"] for leg in normalized_legs)
    ).total_seconds()
    if synced_seconds > SYNC_TOLERANCE_SECONDS:
        raise ValueError("legs must be observed within 2 seconds")

    dte_days = (
        normalized_settlement["settlement_at_dt"] - entry_observed_at
    ).total_seconds() / 86400.0
    if not 7.0 <= dte_days <= 35.0:
        raise ValueError("aligned replay only accepts 7-35 DTE structures")

    quote_currency = normalized_legs[0]["quote_currency"]
    settlement_currency = normalized_settlement["settlement_currency"]
    if settlement_currency != quote_currency:
        raise ValueError("settlement currency must match the quote currency")

    entry_credit = round(sum(leg["entry_cashflow"] for leg in normalized_legs), 8)
    entry_fee = round(
        sum(
            option_fee_linear(
                leg["entry_fill_price"],
                leg["underlying_price"],
                1.0,
                leg["contract_size"],
            )
            for leg in normalized_legs
        ),
        8,
    )
    entry_credit_after_cost = round(entry_credit - entry_fee, 8)
    settlement_price = normalized_settlement["settlement_price"]
    terminal_payoff = round(structure.amount_owed_at(settlement_price), 8)
    delivery_fee = round(
        sum(
            _delivery_fee_for_leg(leg=leg, settlement_price=settlement_price)
            for leg in normalized_legs
        ),
        8,
    )
    net_pnl = round(
        entry_credit - entry_fee - terminal_payoff - delivery_fee,
        8,
    )
    max_loss = _max_loss_with_fees(
        structure=structure,
        entry_credit=entry_credit,
        entry_fee=entry_fee,
    )
    if max_loss is None:
        raise ValueError("aligned replay requires a defined-loss structure")
    net_r = round(net_pnl / max_loss, 8) if max_loss > 0 else None
    regime_labels = _normalize_regimes(regimes)
    protocol_hash = canonical_sha256(protocol)
    cohort_id = f"{structure_type}:{structure.expiry_date}"

    normalized_input = {
        "structure_type": structure_type,
        "protocol_hash": protocol_hash,
        "selection_slot": str(selection_slot),
        "fold_id": str(fold_id),
        "label_window_id": str(label_window_id or cohort_id),
        "legs": [_leg_input_for_hash(leg) for leg in normalized_legs],
        "settlement": _settlement_input_for_hash(normalized_settlement),
        "regimes": regime_labels,
    }
    record = {
        "schema_version": STRATEGY_REPLAY_OBSERVATION_SCHEMA_VERSION,
        "structure_type": structure_type,
        "direction": protocol["structure_alignment"]["direction"],
        "protocol_hash": protocol_hash,
        "selection_slot": str(selection_slot),
        "fold_id": str(fold_id),
        "label_window_id": str(label_window_id or cohort_id),
        "scope": {
            "structure_type": structure_type,
            "direction": protocol["structure_alignment"]["direction"],
            "dte_band_days": [7, 35],
            "entry_cost_basis": ENTRY_COST_BASIS,
            "exit_basis": "hold_to_expiry",
            "settlement_basis": SETTLEMENT_BASIS,
        },
        "cohort_id": cohort_id,
        "expiry_date": structure.expiry_date,
        "entry_observed_at": _isoformat(entry_observed_at),
        "settlement_at": normalized_settlement["settlement_at"],
        "dte_days": round(dte_days, 6),
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "entry_credit": entry_credit,
        "entry_credit_after_entry_fee": entry_credit_after_cost,
        "entry_fee": entry_fee,
        "terminal_payoff": terminal_payoff,
        "delivery_fee": delivery_fee,
        "total_costs": round(entry_fee + delivery_fee, 8),
        "net_pnl": net_pnl,
        "max_loss": max_loss,
        "net_r": net_r,
        "won": net_pnl > 0.0,
        "defined_loss": True,
        "unit_known": True,
        "legs": [_leg_output(leg) for leg in normalized_legs],
        "settlement": {
            "settlement_price": settlement_price,
            "expiry_date": structure.expiry_date,
            "settlement_at": normalized_settlement["settlement_at"],
            "published_at": normalized_settlement["published_at"],
            "basis": SETTLEMENT_BASIS,
            "source": normalized_settlement["source"],
            "source_hash": normalized_settlement["source_hash"],
            "receipt_hash": normalized_settlement["receipt_hash"],
        },
        "regimes": regime_labels,
        "input_hash": canonical_sha256(normalized_input),
    }
    record["result_hash"] = _record_hash(record)
    record["replay_id"] = f"strategy-replay:{record['result_hash']}"
    return record


def build_strategy_replay_ledger(
    *,
    records: list[dict[str, Any]],
    sample_role: str,
    source_classification: str,
) -> dict[str, Any]:
    """Group replay observations by expiry cohort with overlap rejection."""

    if sample_role not in SAMPLE_ROLE_VALUES:
        raise ValueError("sample_role must be development or holdout")
    if source_classification not in SOURCE_CLASSIFICATION_VALUES:
        raise ValueError(
            "source_classification must be development_inventory or future_holdout"
        )
    if not isinstance(records, list):
        raise ValueError("records must be a list")

    normalized_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("records must contain replay observation dicts")
        if record.get("schema_version") != STRATEGY_REPLAY_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("records must contain strategy replay observations")
        normalized_records.append(record)

    seen_result_hashes: set[str] = set()
    seen_input_hashes: set[str] = set()
    seen_selection_slots: set[tuple[str, str]] = set()
    label_windows_by_fold: dict[str, str] = {}
    by_cohort: dict[str, list[dict[str, Any]]] = {}
    for record in normalized_records:
        _validate_record_integrity(record)
        result_hash = str(record.get("result_hash") or "")
        if result_hash in seen_result_hashes:
            raise ValueError("duplicate replay observation detected")
        seen_result_hashes.add(result_hash)
        input_hash = str(record.get("input_hash") or "")
        if input_hash in seen_input_hashes:
            raise ValueError("duplicate replay observation detected")
        seen_input_hashes.add(input_hash)
        cohort_id = str(record.get("cohort_id") or "")
        selection_key = (cohort_id, str(record.get("selection_slot") or ""))
        if selection_key in seen_selection_slots:
            raise ValueError("duplicate selection slot detected within one expiry cohort")
        seen_selection_slots.add(selection_key)
        label_window_id = str(record.get("label_window_id") or "")
        fold_id = str(record.get("fold_id") or "")
        prior_fold = label_windows_by_fold.get(label_window_id)
        if prior_fold is None:
            label_windows_by_fold[label_window_id] = fold_id
        elif prior_fold != fold_id:
            raise ValueError("cross-fold label leakage detected")
        by_cohort.setdefault(cohort_id, []).append(record)

    entries: list[dict[str, Any]] = []
    for cohort_id, cohort_records in sorted(by_cohort.items()):
        settlement_times = [
            _parse_datetime(str(record["settlement_at"])) for record in cohort_records
        ]
        capture_times = [
            _parse_datetime(str(record["entry_observed_at"])) for record in cohort_records
        ]
        record_hashes = sorted(str(record["result_hash"]) for record in cohort_records)
        input_hashes = sorted(str(record["input_hash"]) for record in cohort_records)
        wins = [bool(record["won"]) for record in cohort_records]
        net_rs = [float(record["net_r"]) for record in cohort_records if record.get("net_r") is not None]
        net_pnls = [float(record["net_pnl"]) for record in cohort_records]
        first = cohort_records[0]
        entries.append(
            {
                "cohort_id": cohort_id,
                "expiry_date": str(first["expiry_date"]),
                "sample_role": sample_role,
                "source_classification": source_classification,
                "settled": True,
                "captured_at": _isoformat(min(capture_times)),
                "settled_at": _isoformat(max(settlement_times)),
                "observation_count": len(cohort_records),
                "duplicate_observations_dropped": 0,
                "overlap_observations_dropped": 0,
                "purged_training_observations": 0,
                "embargoed_until": _isoformat(
                    max(settlement_times) + timedelta(days=EMBARGO_DAYS)
                ),
                "volatility_regime": str(
                    (first.get("regimes") or {}).get("volatility") or "unknown"
                ),
                "trend_regime": str(
                    (first.get("regimes") or {}).get("trend") or "unknown"
                ),
                "liquidity_regime": str(
                    (first.get("regimes") or {}).get("liquidity") or "unknown"
                ),
                "win_count": sum(1 for won in wins if won),
                "mean_net_r": round(sum(net_rs) / len(net_rs), 8) if net_rs else None,
                "mean_net_pnl": round(sum(net_pnls) / len(net_pnls), 8),
                "record_hashes": record_hashes,
                "input_hashes": input_hashes,
                "selection_slots": sorted(
                    str(record["selection_slot"]) for record in cohort_records
                ),
                "fold_ids": sorted({str(record["fold_id"]) for record in cohort_records}),
            }
        )

    protocol_hashes = sorted({str(record.get("protocol_hash") or "") for record in normalized_records})
    structure_types = sorted({str(record.get("structure_type") or "") for record in normalized_records})
    scopes = {canonical_sha256(record.get("scope") or {}) for record in normalized_records}
    if len(protocol_hashes) > 1:
        raise ValueError("ledger records must share one protocol hash")
    if len(structure_types) > 1:
        raise ValueError("ledger records must share one structure type")
    if len(scopes) > 1:
        raise ValueError("ledger records must share one aligned replay scope")

    ledger = {
        "schema_version": STRATEGY_REPLAY_LEDGER_SCHEMA_VERSION,
        "structure_type": structure_types[0] if structure_types else None,
        "protocol_hash": protocol_hashes[0] if protocol_hashes else None,
        "sample_role": sample_role,
        "source_classification": source_classification,
        "scope": normalized_records[0]["scope"] if normalized_records else None,
        "entries": entries,
    }
    ledger["result_hash"] = canonical_sha256(ledger)
    ledger["ledger_id"] = f"strategy-replay-ledger:{ledger['result_hash']}"
    return ledger


def _require_protocol_alignment(protocol: dict[str, Any], structure_type: str) -> None:
    if not isinstance(protocol, dict) or protocol.get("frozen") is not True:
        raise ValueError("protocol must be a frozen strategy history protocol")
    alignment = protocol.get("structure_alignment") or {}
    if alignment.get("structure_type") != structure_type:
        raise ValueError("protocol structure_type must match replay structure_type")
    if alignment.get("dte_band_days") != [7, 35]:
        raise ValueError("protocol must freeze the 7-35 DTE band")
    if alignment.get("exit_basis") != "hold_to_expiry":
        raise ValueError("protocol must freeze hold_to_expiry")
    fill_policy = protocol.get("fill_policy") or {}
    if fill_policy.get("short_legs") != "bid_minus_one_adverse_tick":
        raise ValueError("protocol must use short bid minus adverse tick fills")
    if fill_policy.get("long_legs") != "ask_plus_one_adverse_tick":
        raise ValueError("protocol must use long ask plus adverse tick fills")
    settlement_policy = protocol.get("settlement_policy") or {}
    if settlement_policy.get("settlement_basis") != SETTLEMENT_BASIS:
        raise ValueError("protocol must require official expiry settlement")


def _normalize_legs(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(legs, list) or len(legs) not in {2, 4}:
        raise ValueError("aligned replay requires exactly 2 or 4 legs")

    normalized: list[dict[str, Any]] = []
    expiries: set[str] = set()
    quote_currencies: set[str] = set()
    premium_units: set[str] = set()
    contract_sizes: set[float] = set()
    underlying_prices: set[float] = set()
    for leg in legs:
        if not isinstance(leg, dict):
            raise ValueError("legs must be objects")
        quantity = _required_float(leg.get("quantity"), "quantity")
        if abs(quantity) != 1.0:
            raise ValueError("aligned replay currently requires unit leg quantities")
        side = "short" if quantity < 0 else "long"
        bid = _required_float(leg.get("bid"), "bid")
        ask = _required_float(leg.get("ask"), "ask")
        tick_size = _required_float(leg.get("tick_size"), "tick_size")
        if bid <= 0 or ask <= 0 or tick_size <= 0:
            raise ValueError("legs require positive bid, ask, and tick_size")
        if ask < bid:
            raise ValueError("ask must be greater than or equal to bid")
        fill_price = round(bid - tick_size, 8) if side == "short" else round(ask + tick_size, 8)
        if fill_price < 0:
            raise ValueError("adverse-tick fill price must remain non-negative")
        expiry_date = str(leg.get("expiry_date") or "")
        if not expiry_date:
            raise ValueError("legs require expiry_date")
        observed_at = str(leg.get("observed_at") or "")
        if not observed_at:
            raise ValueError("legs require observed_at")
        quote_currency = str(leg.get("quote_currency") or "").upper()
        settlement_currency = str(leg.get("settlement_currency") or "").upper()
        premium_unit = str(leg.get("premium_unit") or "")
        if premium_unit != LINEAR_PREMIUM_UNIT:
            raise ValueError("only quote_currency linear premiums are supported")
        if not quote_currency or settlement_currency != quote_currency:
            raise ValueError("legs require explicit matching quote/settlement currency")
        option_type = str(leg.get("option_type") or "")
        if option_type not in {"call", "put"}:
            raise ValueError("legs must declare call or put")
        contract_size = _required_float(leg.get("contract_size", 1.0), "contract_size")
        if contract_size <= 0:
            raise ValueError("contract_size must be positive")
        underlying_price = _required_float(
            leg.get("underlying_price"), "underlying_price"
        )
        if underlying_price <= 0:
            raise ValueError("underlying_price must be positive")

        expiries.add(expiry_date)
        quote_currencies.add(quote_currency)
        premium_units.add(premium_unit)
        contract_sizes.add(contract_size)
        underlying_prices.add(underlying_price)
        normalized.append(
            {
                "instrument_name": str(leg.get("instrument_name") or ""),
                "option_type": option_type,
                "strike": _required_float(leg.get("strike"), "strike"),
                "quantity": quantity,
                "side": side,
                "bid": bid,
                "ask": ask,
                "tick_size": tick_size,
                "entry_fill_price": fill_price,
                "entry_cashflow": round((-quantity) * fill_price * contract_size, 8),
                "observed_at": observed_at,
                "observed_at_dt": _parse_datetime(observed_at),
                "expiry_date": expiry_date,
                "quote_currency": quote_currency,
                "settlement_currency": settlement_currency,
                "premium_unit": premium_unit,
                "contract_size": contract_size,
                "underlying_price": underlying_price,
            }
        )

    if len(expiries) != 1:
        raise ValueError("legs must all share one expiry")
    if len(quote_currencies) != 1 or len(premium_units) != 1 or len(contract_sizes) != 1:
        raise ValueError("legs must share one explicit premium/unit contract basis")
    if len(underlying_prices) != 1:
        raise ValueError("legs must share one underlying price at entry")
    return sorted(
        normalized,
        key=lambda leg: (
            leg["option_type"],
            leg["strike"],
            leg["instrument_name"],
        ),
    )


def _build_supported_structure(
    structure_type: str,
    normalized_legs: list[dict[str, Any]],
) -> Structure:
    if structure_type == "BEAR_CALL_CREDIT_SPREAD":
        _require_two_leg_credit_spread(normalized_legs, option_type="call", bearish=True)
        structure_name = "call_credit_spread"
    elif structure_type == "BULL_PUT_CREDIT_SPREAD":
        _require_two_leg_credit_spread(normalized_legs, option_type="put", bearish=False)
        structure_name = "put_credit_spread"
    else:
        _require_iron_condor(normalized_legs)
        structure_name = "iron_condor"
    return build_structure(
        structure_type=structure_name,
        contract_size=normalized_legs[0]["contract_size"],
        legs=[
            {
                "option_type": leg["option_type"],
                "strike": leg["strike"],
                "quantity": leg["quantity"],
                "expiry_date": leg["expiry_date"],
                "instrument_name": leg["instrument_name"],
            }
            for leg in normalized_legs
        ],
    )


def _require_two_leg_credit_spread(
    normalized_legs: list[dict[str, Any]],
    *,
    option_type: str,
    bearish: bool,
) -> None:
    if len(normalized_legs) != 2:
        raise ValueError("credit spreads require exactly two legs")
    if {leg["option_type"] for leg in normalized_legs} != {option_type}:
        raise ValueError("credit spread legs must share the required option type")
    short_leg = next((leg for leg in normalized_legs if leg["quantity"] < 0), None)
    long_leg = next((leg for leg in normalized_legs if leg["quantity"] > 0), None)
    if short_leg is None or long_leg is None:
        raise ValueError("credit spreads require one short leg and one long leg")
    if bearish:
        if not short_leg["strike"] < long_leg["strike"]:
            raise ValueError("bear call spreads require short lower strike and long higher strike")
    else:
        if not short_leg["strike"] > long_leg["strike"]:
            raise ValueError("bull put spreads require short higher strike and long lower strike")


def _require_iron_condor(normalized_legs: list[dict[str, Any]]) -> None:
    if len(normalized_legs) != 4:
        raise ValueError("iron condors require exactly four legs")
    puts = sorted(
        [leg for leg in normalized_legs if leg["option_type"] == "put"],
        key=lambda leg: leg["strike"],
    )
    calls = sorted(
        [leg for leg in normalized_legs if leg["option_type"] == "call"],
        key=lambda leg: leg["strike"],
    )
    if len(puts) != 2 or len(calls) != 2:
        raise ValueError("iron condors require two puts and two calls")
    if not (puts[0]["quantity"] > 0 and puts[1]["quantity"] < 0):
        raise ValueError("iron condor put wing must be long lower strike and short higher strike")
    if not (calls[0]["quantity"] < 0 and calls[1]["quantity"] > 0):
        raise ValueError("iron condor call wing must be short lower strike and long higher strike")
    if not puts[1]["strike"] < calls[0]["strike"]:
        raise ValueError("iron condor short put strike must stay below short call strike")


def _normalize_settlement(
    *,
    settlement: dict[str, Any],
    expiry_date: str | None,
    quote_currency: str,
) -> dict[str, Any]:
    if not isinstance(settlement, dict):
        raise ValueError("settlement must be an object")
    if str(settlement.get("basis") or "") != SETTLEMENT_BASIS:
        raise ValueError("settlement must be the official expiry settlement")
    if settlement.get("is_price_proxy") is True:
        raise ValueError("proxy settlement is forbidden")
    settlement_currency = str(settlement.get("settlement_currency") or "").upper()
    if settlement_currency != quote_currency:
        raise ValueError("settlement currency must match quote currency")
    settlement_expiry = str(settlement.get("expiry_date") or "")
    if settlement_expiry != expiry_date:
        raise ValueError("settlement expiry_date must match the legs")
    settlement_price = _required_float(
        settlement.get("settlement_price"), "settlement_price"
    )
    if settlement_price <= 0:
        raise ValueError("settlement_price must be positive")
    settlement_at = str(settlement.get("settlement_at") or "")
    published_at = str(settlement.get("published_at") or settlement_at)
    source = str(settlement.get("source") or "")
    source_hash = str(settlement.get("source_hash") or "")
    receipt_hash = str(settlement.get("receipt_hash") or "")
    if not settlement_at or not published_at:
        raise ValueError("settlement_at and published_at are required")
    if not source or not source_hash or not receipt_hash:
        raise ValueError("official settlement source, receipt_hash, and source_hash are required")
    return {
        "settlement_price": settlement_price,
        "settlement_currency": settlement_currency,
        "settlement_at": settlement_at,
        "settlement_at_dt": _parse_datetime(settlement_at),
        "published_at": published_at,
        "published_at_dt": _parse_datetime(published_at),
        "source": source,
        "source_hash": source_hash,
        "receipt_hash": receipt_hash,
    }


def _max_loss_with_fees(
    *,
    structure: Structure,
    entry_credit: float,
    entry_fee: float,
) -> float | None:
    strikes = structure.strikes
    if not strikes:
        return None
    max_payoff = max(
        structure.amount_owed_at(point) for point in (0.0, *strikes, strikes[-1] * 2.0)
    )
    upper_cap_spot = max(
        strikes[-1] * 2.0,
        (0.125 * max_payoff / 0.00015) if max_payoff > 0 else strikes[-1] * 2.0,
    )
    boundaries = sorted({0.0, *strikes, upper_cap_spot})
    candidate_spots: set[float] = set(boundaries)
    for left, right in pairwise(boundaries):
        if right <= left:
            continue
        left_payoff = structure.amount_owed_at(left)
        right_payoff = structure.amount_owed_at(right)
        candidate_spots.add(left)
        candidate_spots.add(right)
        slope = (right_payoff - left_payoff) / (right - left)
        intercept = left_payoff - slope * left
        denominator = 0.00015 - 0.125 * slope
        if denominator != 0:
            switch = (0.125 * intercept) / denominator
            if left <= switch <= right and (slope * switch + intercept) > 0:
                candidate_spots.add(switch)

    worst_pnl = None
    for spot in sorted(candidate_spots):
        payoff = structure.amount_owed_at(spot)
        delivery_fee = sum(
            _delivery_fee_for_leg(leg=leg.to_dict(), settlement_price=spot)
            for leg in structure.legs
        )
        pnl = entry_credit - entry_fee - payoff - delivery_fee
        worst_pnl = pnl if worst_pnl is None else min(worst_pnl, pnl)
    if worst_pnl is None:
        return None
    return round(max(-worst_pnl, 0.0), 8)


def _normalize_regimes(regimes: dict[str, Any] | None) -> dict[str, str]:
    if regimes is None:
        return {
            "volatility": "unknown",
            "trend": "unknown",
            "liquidity": "unknown",
        }
    if not isinstance(regimes, dict):
        raise ValueError("regimes must be a dict when provided")
    return {
        "volatility": str(regimes.get("volatility") or "unknown"),
        "trend": str(regimes.get("trend") or "unknown"),
        "liquidity": str(regimes.get("liquidity") or "unknown"),
    }


def _delivery_fee_for_leg(*, leg: dict[str, Any], settlement_price: float) -> float:
    quantity = float(leg["quantity"])
    option_type = str(leg["option_type"])
    strike = float(leg["strike"])
    if option_type == "call":
        intrinsic = max(settlement_price - strike, 0.0)
    else:
        intrinsic = max(strike - settlement_price, 0.0)
    positive_value = intrinsic * abs(quantity)
    return delivery_fee_linear(
        positive_value / max(float(leg.get("contract_size", 1.0)), 1e-12),
        max(settlement_price, 1e-12),
        1.0,
        float(leg.get("contract_size", 1.0)),
        delivery_fee_applies=positive_value > 0.0,
    )


def _validate_record_integrity(record: dict[str, Any]) -> None:
    expected_hash = _record_hash(record)
    if str(record.get("result_hash") or "") != expected_hash:
        raise ValueError("caller-mutated replay record hash mismatch")
    if str(record.get("replay_id") or "") != f"strategy-replay:{expected_hash}":
        raise ValueError("caller-mutated replay id mismatch")
    expected_input_hash = canonical_sha256(_record_input_from_record(record))
    if str(record.get("input_hash") or "") != expected_input_hash:
        raise ValueError("caller-mutated replay input hash mismatch")


def _record_input_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "structure_type": record["structure_type"],
        "protocol_hash": record["protocol_hash"],
        "selection_slot": record["selection_slot"],
        "fold_id": record["fold_id"],
        "label_window_id": record["label_window_id"],
        "legs": [
            {
                "instrument_name": leg["instrument_name"],
                "option_type": leg["option_type"],
                "strike": leg["strike"],
                "quantity": leg["quantity"],
                "bid": leg["bid"],
                "ask": leg["ask"],
                "tick_size": leg["tick_size"],
                "observed_at": leg["observed_at"],
                "expiry_date": leg["expiry_date"],
                "quote_currency": leg["quote_currency"],
                "settlement_currency": leg["settlement_currency"],
                "premium_unit": leg["premium_unit"],
                "contract_size": leg["contract_size"],
                "underlying_price": leg["underlying_price"],
            }
            for leg in record["legs"]
        ],
        "settlement": {
            "settlement_price": record["settlement"]["settlement_price"],
            "settlement_currency": record["settlement_currency"],
            "settlement_at": record["settlement"]["settlement_at"],
            "published_at": record["settlement"]["published_at"],
            "basis": record["settlement"]["basis"],
            "source": record["settlement"]["source"],
            "source_hash": record["settlement"]["source_hash"],
            "receipt_hash": record["settlement"]["receipt_hash"],
        },
        "regimes": record["regimes"],
    }


def _leg_input_for_hash(leg: dict[str, Any]) -> dict[str, Any]:
    return {
        "instrument_name": leg["instrument_name"],
        "option_type": leg["option_type"],
        "strike": leg["strike"],
        "quantity": leg["quantity"],
        "bid": leg["bid"],
        "ask": leg["ask"],
        "tick_size": leg["tick_size"],
        "observed_at": leg["observed_at"],
        "expiry_date": leg["expiry_date"],
        "quote_currency": leg["quote_currency"],
        "settlement_currency": leg["settlement_currency"],
        "premium_unit": leg["premium_unit"],
        "contract_size": leg["contract_size"],
        "underlying_price": leg["underlying_price"],
    }


def _settlement_input_for_hash(settlement: dict[str, Any]) -> dict[str, Any]:
    return {
        "settlement_price": settlement["settlement_price"],
        "settlement_currency": settlement["settlement_currency"],
        "settlement_at": settlement["settlement_at"],
        "published_at": settlement["published_at"],
        "basis": SETTLEMENT_BASIS,
        "source": settlement["source"],
        "source_hash": settlement["source_hash"],
        "receipt_hash": settlement["receipt_hash"],
    }


def _leg_output(leg: dict[str, Any]) -> dict[str, Any]:
    return {
        "instrument_name": leg["instrument_name"],
        "option_type": leg["option_type"],
        "strike": leg["strike"],
        "quantity": leg["quantity"],
        "side": leg["side"],
        "bid": leg["bid"],
        "ask": leg["ask"],
        "tick_size": leg["tick_size"],
        "entry_fill_price": leg["entry_fill_price"],
        "observed_at": leg["observed_at"],
        "expiry_date": leg["expiry_date"],
        "quote_currency": leg["quote_currency"],
        "settlement_currency": leg["settlement_currency"],
        "premium_unit": leg["premium_unit"],
        "contract_size": leg["contract_size"],
        "underlying_price": leg["underlying_price"],
    }


def _record_hash(record: dict[str, Any]) -> str:
    payload = deepcopy(record)
    payload.pop("replay_id", None)
    payload.pop("result_hash", None)
    return canonical_sha256(payload)


def _required_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{field_name} must be a finite number")
    return number


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(UTC)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
