"""Deterministic, account-free comparison of complete USDC option structures.

Discovery is a bounded structural shortlist, not a profitability screen. This
module never changes admission decisions, produces probabilities, or sizes an
account. The quote payoff bound deliberately excludes trading and delivery fees.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from heapq import nsmallest
from typing import Any

from ._canonical import canonical_sha256
from .pnl import delivery_fee_linear, option_fee_linear
from .structures import Structure, build_structure
from .surface import black_scholes_price

DESK_SCHEMA_VERSION = "decision_desk.v1"
COMPARISON_SCHEMA_VERSION = "research_comparison.v1"
FEE_POLICY_ID = "deribit:standard-linear-options:2026-09-25:no-discounts"
MODEL_ID = "decision-desk:linear-usdc:touch:zero-rate-carry:v1"
LOSS_BOUND_SCOPE = "OPTION_PAYOFF_EXCLUDING_DYNAMIC_DELIVERY_FEES"
QUOTE_MAX_AGE_SECONDS = 60.0
QUOTE_FUTURE_TOLERANCE_SECONDS = 5.0
QUOTE_SYNC_SECONDS = 2.0
SHORTLIST_LIMIT = 48
DEFAULT_CRITERIA = {
    "viewpoint": "all", "dte_min": 7.0, "dte_max": 45.0,
    "max_width_pct": 0.1, "max_spread_ratio": 0.5,
}
STRUCTURE_VIEWPOINTS = {
    "BULL_PUT_CREDIT": "bullish",
    "BEAR_CALL_CREDIT": "bearish",
    "IRON_CONDOR": "range",
}


def validate_criteria(criteria: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate filters without fetching public data or evaluating quotes."""
    return _criteria(criteria)


def validate_exact_candidate(original_candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return only valid saved structure metadata; ignore all claimed economics."""
    family, raw_legs = original_candidate.get("structure"), original_candidate.get("legs")
    if not isinstance(family, str) or family not in STRUCTURE_VIEWPOINTS or not isinstance(raw_legs, list):
        raise ValueError("exact review requires a supported complete structure")
    if len(raw_legs) != (4 if family == "IRON_CONDOR" else 2):
        raise ValueError("exact review requires all legs of the saved structure")
    if _milliseconds(original_candidate.get("expiration_timestamp")) is None:
        raise ValueError("exact review requires the original expiration timestamp")
    legs = []
    for raw_value in raw_legs:
        raw = _mapping(raw_value)
        name, strike, size = raw.get("instrument_name"), _number(raw.get("strike")), _number(raw.get("contract_size"))
        if not isinstance(name, str) or not 0 < len(name) <= 128 or not name.isascii() or any(not (char.isalnum() or char in "_.-") for char in name):
            raise ValueError("exact review requires valid saved instrument names")
        if strike is None or strike <= 0 or size is None or size <= 0 or raw.get("ratio") != 1 or isinstance(raw.get("ratio"), bool) or not isinstance(raw.get("side"), str) or raw.get("side") not in {"BUY", "SELL"} or not isinstance(raw.get("option_type"), str) or raw.get("option_type") not in {"call", "put"} or raw.get("price_currency") != "USDC" or raw.get("settlement_currency") != "USDC":
            raise ValueError("exact review requires explicit valid USDC leg metadata and fixed ratios")
        legs.append({"instrument_name": name, "strike": strike, "contract_size": size, "option_type": raw["option_type"], "side": raw["side"], "ratio": 1, "price_currency": "USDC", "settlement_currency": "USDC"})
    _validate_exact_structure(legs, str(family))
    return {"structure": family, "expiration_timestamp": original_candidate["expiration_timestamp"], "legs": legs}


def enumerate_provisional(
    snapshot: Mapping[str, Any],
    criteria: Mapping[str, Any] | None = None,
    *,
    evaluation_clock: str | None = None,
) -> dict[str, Any]:
    """Scan all summaries, retain a disclosed deterministic structural shortlist.

    All eligible vertical pairs are counted. Condor counts cover every pairing
    of eligible wings, while only the best bounded wing pairs are materialized.
    This avoids an unbounded four-leg payload without truncating the scan.
    """
    clock = _clock(evaluation_clock)
    filters = _criteria(criteria)
    exclusions: Counter[str] = Counter()
    instruments = _mapping(snapshot.get("instruments"))
    summaries = _mapping(snapshot.get("summaries"))
    index = _number(_mapping(snapshot.get("index")).get("price"))
    base_errors = _snapshot_errors(snapshot, clock)
    counts: dict[str, Any] = {
        "scanned_instrument_count": len(instruments),
        "summary_count": len(summaries), "filter_matched_instrument_count": 0,
        "formed_structure_count": 0, "shortlisted_count": 0,
        "shortlist_limit": SHORTLIST_LIMIT, "structure_counts": {},
        "enumeration_policy": "OTM_SHORT_VERTICAL_PAIRS_AND_ORDERED_CONDOR_WINGS",
    }
    if base_errors:
        exclusions.update(reason["code"] for reason in base_errors)
        return {"candidates": [], "counts": counts, "exclusion_counts": dict(exclusions)}
    assert index is not None
    by_expiry: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for name, metadata_value in instruments.items():
        metadata = _mapping(metadata_value)
        summary = _mapping(summaries.get(name))
        leg, code = _provisional_leg(str(name), metadata, summary, snapshot, clock, filters)
        if code:
            exclusions[code] += 1
        elif leg is not None:
            by_expiry[leg["expiration_timestamp"]].append(leg)
            counts["filter_matched_instrument_count"] += 1

    families = [
        family for family, viewpoint in STRUCTURE_VIEWPOINTS.items()
        if filters["viewpoint"] in {"all", viewpoint}
    ]
    family_limit = max(1, SHORTLIST_LIMIT // len(families))
    retained: dict[str, list[dict[str, Any]]] = {family: [] for family in families}
    totals: Counter[str] = Counter()
    for expiry, legs in sorted(by_expiry.items()):
        calls = sorted((leg for leg in legs if leg["option_type"] == "call"), key=_strike_key)
        puts = sorted((leg for leg in legs if leg["option_type"] == "put"), key=_strike_key)
        call_wings = _verticals(calls, "BEAR_CALL_CREDIT", index, filters, exclusions)
        put_wings = _verticals(puts, "BULL_PUT_CREDIT", index, filters, exclusions)
        for family, wings in (("BULL_PUT_CREDIT", put_wings), ("BEAR_CALL_CREDIT", call_wings)):
            if family in families:
                totals[family] += len(wings)
                retained[family].extend(_provisional_candidate(snapshot, family, wing, index, filters) for wing in nsmallest(family_limit, wings, key=lambda item: _wing_rank(item, index)))
                retained[family] = nsmallest(family_limit, retained[family], key=_candidate_rank)
        if "IRON_CONDOR" in families:
            # All valid ordered wing pairs are counted; only top-k payloads
            # are formed. Restrict matching multipliers and exclude two ATM
            # shorts at the same strike (an iron butterfly, not a condor).
            valid_pairs = _condor_pairs(put_wings, call_wings, index, family_limit)
            totals["IRON_CONDOR"] += valid_pairs["count"]
            combinations = (_provisional_candidate(snapshot, "IRON_CONDOR", [*put, *call], index, filters) for put, call in valid_pairs["pairs"])
            retained["IRON_CONDOR"].extend(nsmallest(family_limit, combinations, key=_candidate_rank))
            retained["IRON_CONDOR"] = nsmallest(family_limit, retained["IRON_CONDOR"], key=_candidate_rank)
        # Expiry groups remain separate throughout; no calendar is synthesized.
        assert all(leg["expiration_timestamp"] == expiry for leg in legs)
    candidates = sorted((item for family in families for item in retained[family]), key=_candidate_rank)
    for rank, candidate in enumerate(candidates, 1):
        candidate["rank"] = rank
    counts.update(
        formed_structure_count=sum(totals.values()),
        shortlisted_count=len(candidates), structure_counts=dict(totals),
    )
    return {"candidates": candidates, "counts": counts, "exclusion_counts": dict(exclusions)}


def build_desk(
    snapshot: Mapping[str, Any],
    criteria: Mapping[str, Any] | None = None,
    *,
    evaluation_clock: str | None = None,
) -> dict[str, Any]:
    """Project one immutable snapshot into quote comparison eligibility."""
    clock = _clock(evaluation_clock)
    filters = _criteria(criteria)
    provisional = enumerate_provisional(snapshot, filters, evaluation_clock=_iso(clock))
    return _project_desk(snapshot, filters, clock, provisional)


def evaluate_exact(
    snapshot: Mapping[str, Any], original_candidate: Mapping[str, Any],
    criteria: Mapping[str, Any] | None = None, *, evaluation_clock: str | None = None,
) -> dict[str, Any]:
    """Recheck saved exact legs against current registry; never substitute a leg.

    The caller's quotes, economics, eligibility and IDs are ignored. Only a
    structurally valid set of metadata expectations survives, and any mismatch
    with the current public registry blocks all economics for that structure.
    """
    clock, filters = _clock(evaluation_clock), _criteria(criteria)
    original_candidate = validate_exact_candidate(original_candidate)
    family, original_legs = original_candidate["structure"], original_candidate["legs"]
    expiry = _milliseconds(original_candidate["expiration_timestamp"])
    assert expiry is not None
    instruments = _mapping(snapshot.get("instruments"))
    legs: list[dict[str, Any]] = []
    reasons: list[dict[str, str]] = []
    for raw_value in original_legs:
        raw = _mapping(raw_value)
        name = str(raw["instrument_name"])
        strike, size = float(raw["strike"]), float(raw["contract_size"])
        metadata = _mapping(instruments.get(name))
        if not metadata:
            reasons.append(_reason("EXACT_INSTRUMENT_UNAVAILABLE", f"{name}: original instrument is absent from the current registry; no replacement was made."))
        else:
            expected = {
                "option_type": raw["option_type"], "strike": strike,
                "contract_size": size, "expiration_timestamp": original_candidate["expiration_timestamp"],
                "asset": snapshot.get("asset"), "instrument_type": "linear",
                "price_currency": "USDC", "settlement_currency": "USDC",
                "index_name": _mapping(snapshot.get("index")).get("name"), "instrument_name": name,
            }
            if any(metadata.get(key) != value for key, value in expected.items()) or any(_number(metadata.get(key)) is None for key in ("strike", "contract_size", "expiration_timestamp")) or metadata.get("active") is not True or metadata.get("eligible") is False or metadata.get("validation_errors"):
                reasons.append(_reason("EXACT_METADATA_CHANGED_OR_INVALID", f"{name}: current registry does not confirm the saved asset, type, strike, expiry, multiplier and USDC currencies."))
        legs.append({
            "instrument_name": name, "strike": strike, "contract_size": size,
            "option_type": raw["option_type"], "side": raw["side"], "ratio": 1,
            "expiration_timestamp": original_candidate["expiration_timestamp"],
            "expiry_date": expiry.date().isoformat(), "dte_days": (expiry - clock).total_seconds() / 86400,
            "price_currency": "USDC", "settlement_currency": "USDC",
            "settlement_period": metadata.get("settlement_period", metadata.get("raw_settlement_period")),
            "tick_size": _number(metadata.get("tick_size")),
            "bid": None, "ask": None, "spread_ratio": 0.0,
        })
    if expiry <= clock:
        reasons.append(_reason("EXACT_EXPIRY_PASSED", "The original structure has expired; its exact legs are retained as historical research only."))
    identity = {"snapshot_id": snapshot.get("snapshot_id"), "structure": family, "criteria": filters, "legs": [{key: leg[key] for key in ("instrument_name", "side", "ratio", "contract_size", "strike", "expiration_timestamp")} for leg in sorted(legs, key=lambda leg: (leg["option_type"], leg["strike"], leg["side"], leg["instrument_name"]))]}
    candidate_id = "candidate:" + canonical_sha256(identity)
    candidate = {
        "candidate_id": candidate_id, "structure": family,
        "viewpoint": STRUCTURE_VIEWPOINTS[str(family)], "expiry_date": expiry.date().isoformat(),
        "expiration_timestamp": original_candidate["expiration_timestamp"],
        "dte_days": (expiry - clock).total_seconds() / 86400, "rank": 1,
        "discovery_score": 0.0, "discovery_basis": "EXACT_SAVED_LEGS_METADATA_REVERIFIED", "legs": legs,
    }
    provisional = {
        "candidates": [candidate], "exclusion_counts": {},
        "counts": {"scanned_instrument_count": len(instruments), "summary_count": len(_mapping(snapshot.get("summaries"))), "filter_matched_instrument_count": 0, "formed_structure_count": 1, "shortlisted_count": 1, "shortlist_limit": 1, "structure_counts": {family: 1}, "enumeration_policy": "EXACT_SAVED_STRUCTURE_NO_RANKING_OR_SUBSTITUTION"},
    }
    return _project_desk(snapshot, filters, clock, provisional, {candidate_id: reasons})


def _validate_exact_structure(legs: list[dict[str, Any]], family: str) -> None:
    if len({leg["instrument_name"] for leg in legs}) != len(legs) or len({leg["contract_size"] for leg in legs}) != 1:
        raise ValueError("exact structure requires distinct legs and one verified multiplier")
    puts = sorted((leg for leg in legs if leg["option_type"] == "put"), key=_strike_key)
    calls = sorted((leg for leg in legs if leg["option_type"] == "call"), key=_strike_key)
    put_ok = len(puts) == 2 and puts[0]["strike"] < puts[1]["strike"] and [leg["side"] for leg in puts] == ["BUY", "SELL"]
    call_ok = len(calls) == 2 and calls[0]["strike"] < calls[1]["strike"] and [leg["side"] for leg in calls] == ["SELL", "BUY"]
    valid = (family == "BULL_PUT_CREDIT" and put_ok and not calls) or (family == "BEAR_CALL_CREDIT" and call_ok and not puts) or (family == "IRON_CONDOR" and put_ok and call_ok and puts[1]["strike"] < calls[0]["strike"])
    if not valid:
        raise ValueError("saved legs do not form the declared complete credit structure")


def _project_desk(
    snapshot: Mapping[str, Any], filters: Mapping[str, Any], clock: datetime,
    provisional: Mapping[str, Any], exact_errors: Mapping[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    frozen_inputs = {
        "snapshot_id": snapshot.get("snapshot_id"), "criteria": filters,
        "model_id": MODEL_ID, "fee_policy_id": FEE_POLICY_ID,
        "candidates": provisional["candidates"],
        "quotes": _identity_quotes(_mapping(snapshot.get("quotes"))),
        "evaluation_clock": _iso(clock),
    }
    assumptions_id = "assumptions:" + canonical_sha256(frozen_inputs)
    candidates = [
        _candidate(snapshot, item, clock, assumptions_id, filters, (exact_errors or {}).get(item["candidate_id"], []))
        for item in provisional["candidates"]
    ]
    exclusion_counts = Counter(provisional["exclusion_counts"])
    for candidate in candidates:
        if candidate["status"] != "comparable":
            exclusion_counts.update(reason["code"] for reason in candidate["reasons"])
    errors = _snapshot_errors(snapshot, clock)
    comparable = [candidate for candidate in candidates if candidate["status"] == "comparable"]
    coverage = deepcopy(dict(_mapping(snapshot.get("coverage"))))
    coverage["failures"] = [
        f"{item.get('code', 'PUBLIC_DATA_UNAVAILABLE')} ({item.get('scope', 'unknown')}): {item.get('message', '')}" if isinstance(item, Mapping) else str(item)
        for item in coverage.get("failures", [])
    ]
    coverage["discovery"] = provisional["counts"]
    coverage.update({key: provisional["counts"][key] for key in ("scanned_instrument_count", "formed_structure_count", "shortlisted_count", "shortlist_limit")})
    coverage["matched_count"] = provisional["counts"]["filter_matched_instrument_count"]
    coverage["deep_candidate_count"] = sum(all(leg["quote_time"] is not None for leg in item["legs"]) for item in candidates)
    data_status = "current"
    if errors:
        data_status = "stale" if any(reason["code"] == "SNAPSHOT_EXPIRED" for reason in errors) else "unavailable"
    elif coverage.get("scan_complete") is not True or coverage.get("failures") or any(item["status"] != "comparable" for item in candidates):
        data_status = "partial"
    if comparable:
        opportunity_status = "available"
    elif errors:
        opportunity_status = "data_blocked"
    elif candidates:
        codes = {reason["code"] for item in candidates for reason in item["reasons"]}
        if codes & {"INSUFFICIENT_QUOTE_DEPTH", "SPREAD_TOO_WIDE"}:
            opportunity_status = "liquidity_blocked"
        elif codes & {"NO_NET_CREDIT_AFTER_STANDARD_FEES", "UNBOUNDED_OPTION_PAYOFF"}:
            opportunity_status = "risk_blocked"
        else:
            opportunity_status = "data_blocked"
    else:
        opportunity_status = "no_match"
        if exclusion_counts.get("SPREAD_TOO_WIDE"):
            opportunity_status = "liquidity_blocked"
        elif any(exclusion_counts.get(code) for code in ("MISSING_POSITIVE_TWO_SIDED_QUOTES", "CROSSED_QUOTES", "INCOMPLETE_INSTRUMENT_METADATA", "MISSING_SUMMARY", "UNDERLYING_MISMATCH", "INSTRUMENT_INDEX_OR_IDENTITY_MISMATCH")) or coverage.get("scan_complete") is not True or coverage.get("failures"):
            opportunity_status = "data_blocked"
    desk = {
        "schema_version": DESK_SCHEMA_VERSION, "generated_at": _iso(clock),
        "captured_at": snapshot.get("captured_at"), "expires_at": snapshot.get("expires_at"),
        "snapshot_id": snapshot.get("snapshot_id"), "analysis_id": None,
        "asset": snapshot.get("asset"), "venue": "DERIBIT", "contract_family": "LINEAR_USDC",
        "source": deepcopy(snapshot.get("source")),
        "market": {"index_price": _number(_mapping(snapshot.get("index")).get("price")), "index_currency": "USDC", "settlement_currency": "USDC"},
        "coverage": coverage, "criteria": filters,
        "qualification": {
            "data_status": data_status, "opportunity_status": opportunity_status,
            "exclusion_counts": dict(sorted(exclusion_counts.items())), "execution_allowed": False,
        },
        "research_only": True, "assumptions_id": assumptions_id,
        "assumptions": _assumptions(), "candidates": candidates,
    }
    desk["analysis_id"] = "analysis:" + canonical_sha256(desk)
    return desk


def compare_candidates(
    desk: Mapping[str, Any],
    ids: Sequence[str],
    scenario: Mapping[str, Any],
    *,
    evaluation_clock: str | None = None,
) -> dict[str, Any]:
    """Compare two or three alternatives, never sum them into an account book."""
    if desk.get("schema_version") != DESK_SCHEMA_VERSION or desk.get("research_only") is not True or _mapping(desk.get("qualification")).get("execution_allowed") is not False:
        raise ValueError("comparison requires a research-only decision desk")
    if desk.get("analysis_id") != "analysis:" + canonical_sha256({**desk, "analysis_id": None}):
        raise ValueError("decision desk identity no longer matches its frozen inputs")
    if not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
        raise ValueError("comparison requires two or three distinct candidate ids")
    clock = _clock(evaluation_clock)
    expires = _timestamp(desk.get("expires_at"))
    if expires is None or expires <= clock or _mapping(desk.get("qualification")).get("data_status") in {"stale", "unavailable"}:
        raise ValueError("snapshot expired or unavailable; re-fetch and re-evaluate before comparison")
    candidate_map = {item["candidate_id"]: item for item in desk.get("candidates", []) if isinstance(item, Mapping)}
    if any(candidate_id not in candidate_map for candidate_id in ids):
        raise ValueError("selected candidate does not belong to this snapshot")
    selected = [candidate_map[candidate_id] for candidate_id in ids]
    if any(item.get("status") != "comparable" for item in selected):
        raise ValueError("selected candidate lacks complete current comparison quotes")
    if len({item["expiration_timestamp"] for item in selected}) != 1:
        raise ValueError("comparison requires a shared expiration timestamp")
    if len({item["assumptions_id"] for item in selected}) != 1 or selected[0]["assumptions_id"] != desk.get("assumptions_id"):
        raise ValueError("comparison requires shared frozen assumptions")
    if any((_timestamp(item.get("recheck_at")) or clock) <= clock for item in selected):
        raise ValueError("candidate quotes expired; re-fetch before comparison")
    shock = _scenario(scenario)
    index = _number(_mapping(desk.get("market")).get("index_price"))
    if index is None or index <= 0:
        raise ValueError("comparison requires a positive USDC index price")
    expiry = _milliseconds(selected[0]["expiration_timestamp"])
    assert expiry is not None
    dte = (expiry - _clock(str(desk["generated_at"]))).total_seconds() / 86400
    if shock["time_days"] > dte:
        raise ValueError("scenario time cannot extend past the common expiry")
    # All members use one grid containing every strike, not individual grids.
    strikes = sorted({float(leg["strike"]) for item in selected for leg in item["legs"]})
    lower = max(0.0, min(index * 0.6, strikes[0] * 0.8))
    upper = max(index * 1.4, strikes[-1] * 1.2)
    grid = sorted({round(lower + (upper - lower) * i / 80, 8) for i in range(81)} | set(strikes) | {index})
    members = []
    for item in selected:
        stress = _stress(item, index, dte, shock)
        members.append({
            "candidate_id": item["candidate_id"],
            "expiry_points": [{"price": price, "pnl": _expiry_pnl(item, price)} for price in grid],
            "stress": stress,
            "stress_reason": None if stress is not None else "IV unavailable, shifted IV non-positive, or no finite model valuation; no theoretical pre-expiry value is shown.",
            "entry_cash": item["economics"]["entry_cash"],
            "net_entry_cash": item["economics"]["net_entry_cash"],
            "entry_fees": item["economics"]["entry_fees"], "currency": "USDC",
        })
    binding = {
        "snapshot_id": desk.get("snapshot_id"), "analysis_id": desk.get("analysis_id"),
        "candidate_ids": sorted(ids), "assumptions_id": selected[0]["assumptions_id"],
        "scenario": shock, "expiry_grid": grid,
    }
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION, "snapshot_id": desk.get("snapshot_id"),
        "analysis_id": desk.get("analysis_id"), "scenario_id": "scenario:" + canonical_sha256(binding),
        "assumptions_id": selected[0]["assumptions_id"], "asset": desk.get("asset"),
        "currency": "USDC", "generated_at": desk.get("generated_at"),
        "expires_at": desk.get("expires_at"), "scenario": shock,
        "assumptions": _assumptions(), "execution_allowed": False,
        "research_only": True, "members": members,
    }


def _provisional_leg(
    name: str, metadata: Mapping[str, Any], summary: Mapping[str, Any],
    snapshot: Mapping[str, Any], clock: datetime, criteria: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if metadata.get("instrument_type") != "linear" or metadata.get("price_currency") != "USDC" or metadata.get("settlement_currency") != "USDC":
        return None, "UNSUPPORTED_CONTRACT_FAMILY"
    if metadata.get("eligible") is False or metadata.get("validation_errors"):
        return None, "INCOMPLETE_INSTRUMENT_METADATA"
    if metadata.get("instrument_name", name) != name or metadata.get("index_name", _mapping(snapshot.get("index")).get("name")) != _mapping(snapshot.get("index")).get("name"):
        return None, "INSTRUMENT_INDEX_OR_IDENTITY_MISMATCH"
    if metadata.get("asset", metadata.get("base_currency")) != snapshot.get("asset"):
        return None, "UNDERLYING_MISMATCH"
    if metadata.get("active") is not True:
        return None, "INSTRUMENT_NOT_ACTIVE"
    strike = _number(metadata.get("strike"))
    size = _number(metadata.get("contract_size"))
    expiry = _milliseconds(metadata.get("expiration_timestamp"))
    if strike is None or strike <= 0 or size is None or size <= 0 or expiry is None or metadata.get("option_type") not in {"call", "put"}:
        return None, "INCOMPLETE_INSTRUMENT_METADATA"
    dte = (expiry - clock).total_seconds() / 86400
    if not criteria["dte_min"] <= dte <= criteria["dte_max"]:
        return None, "OUTSIDE_DTE_FILTER"
    bid, ask = _number(summary.get("bid")), _number(summary.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None, "MISSING_POSITIVE_TWO_SIDED_QUOTES"
    if bid > ask:
        return None, "CROSSED_QUOTES"
    spread = (ask - bid) / (bid + (ask - bid) / 2)
    if spread > criteria["max_spread_ratio"]:
        return None, "SPREAD_TOO_WIDE"
    return {
        "instrument_name": name, "strike": strike, "option_type": metadata["option_type"],
        "contract_size": size, "expiration_timestamp": metadata["expiration_timestamp"],
        "expiry_date": expiry.date().isoformat(), "dte_days": dte,
        "bid": bid, "ask": ask, "spread_ratio": spread,
        "price_currency": "USDC", "settlement_currency": "USDC",
        "settlement_period": metadata.get("settlement_period", metadata.get("raw_settlement_period")),
        "tick_size": _number(metadata.get("tick_size")),
    }, None


def _verticals(
    legs: list[dict[str, Any]], family: str, index: float,
    criteria: Mapping[str, Any], exclusions: Counter[str],
) -> list[list[dict[str, Any]]]:
    result = []
    for left_index, lower in enumerate(legs):
        for upper in legs[left_index + 1:]:
            short, long = (upper, lower) if family == "BULL_PUT_CREDIT" else (lower, upper)
            if (family == "BULL_PUT_CREDIT" and short["strike"] > index) or (family == "BEAR_CALL_CREDIT" and short["strike"] < index):
                continue
            width = upper["strike"] - lower["strike"]
            if width <= 0 or width / index > criteria["max_width_pct"]:
                exclusions["OUTSIDE_WIDTH_FILTER"] += 1
                continue
            if short["contract_size"] != long["contract_size"]:
                exclusions["CONTRACT_SIZE_MISMATCH"] += 1
                continue
            if short["bid"] <= long["ask"]:
                exclusions["NO_CREDIT_AT_CONSERVATIVE_TOUCH"] += 1
                continue
            result.append([{**short, "side": "SELL", "ratio": 1}, {**long, "side": "BUY", "ratio": 1}])
    return result


def _provisional_candidate(
    snapshot: Mapping[str, Any], family: str, legs: list[dict[str, Any]],
    index: float, criteria: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = sorted(legs, key=lambda leg: (leg["option_type"], leg["strike"], leg["side"], leg["instrument_name"]))
    identity = {
        "snapshot_id": snapshot.get("snapshot_id"), "structure": family,
        "criteria": dict(criteria),
        "legs": [{key: leg[key] for key in ("instrument_name", "side", "ratio", "contract_size", "strike", "expiration_timestamp")} for leg in ordered],
    }
    wings = [ordered] if family != "IRON_CONDOR" else [[leg for leg in ordered if leg["option_type"] == kind] for kind in ("put", "call")]
    return {
        "candidate_id": "candidate:" + canonical_sha256(identity), "structure": family,
        "viewpoint": STRUCTURE_VIEWPOINTS[family], "expiry_date": ordered[0]["expiry_date"],
        "expiration_timestamp": ordered[0]["expiration_timestamp"], "dte_days": ordered[0]["dte_days"],
        "legs": ordered, "discovery_score": sum(_wing_rank(wing, index)[0] for wing in wings) / len(wings),
        "discovery_basis": "moneyness_width_spread_and_dte; no_EV_or_probability",
    }


def _condor_pairs(
    puts: list[list[dict[str, Any]]], calls: list[list[dict[str, Any]]],
    index: float, limit: int,
) -> dict[str, Any]:
    pairs: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    count = 0
    sizes = sorted({wing[0]["contract_size"] for wing in puts} & {wing[0]["contract_size"] for wing in calls})
    for size in sizes:
        matching_calls = [wing for wing in calls if wing[0]["contract_size"] == size]
        matching_puts = [wing for wing in puts if wing[0]["contract_size"] == size]
        for atm in (False, True):
            put_group = [wing for wing in matching_puts if (wing[0]["strike"] == index) == atm]
            call_group = [wing for wing in matching_calls if not atm or wing[0]["strike"] > index]
            count += len(put_group) * len(call_group)
            # Within a group every combination is valid and the score is
            # additive. Either wing outside top-k cannot enter its top-k pairs.
            pairs.extend((put, call) for put in nsmallest(limit, put_group, key=lambda wing: _wing_rank(wing, index)) for call in nsmallest(limit, call_group, key=lambda wing: _wing_rank(wing, index)))
    return {"count": count, "pairs": pairs}


def _candidate(
    snapshot: Mapping[str, Any], provisional: Mapping[str, Any], clock: datetime,
    assumptions_id: str, criteria: Mapping[str, Any], pre_reasons: list[dict[str, str]],
) -> dict[str, Any]:
    quotes = _mapping(snapshot.get("quotes"))
    expiry = _milliseconds(provisional["expiration_timestamp"])
    assert expiry is not None
    limits = [_timestamp(snapshot.get("expires_at")) or clock, expiry]
    reasons = [*pre_reasons, *_snapshot_errors(snapshot, clock)]
    legs = []
    observed_times = []
    for raw in provisional["legs"]:
        quote = _mapping(quotes.get(raw["instrument_name"]))
        bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
        bid_size, ask_size = _number(quote.get("bid_size")), _number(quote.get("ask_size"))
        quote_time = _milliseconds(quote.get("exchange_timestamp"))
        observed_at = _timestamp(quote.get("observed_at"))
        leg_reasons = []
        if not quote:
            leg_reasons.append("DEEP_QUOTE_NOT_FETCHED")
        elif quote.get("valid") is False or quote.get("validation_errors"):
            leg_reasons.append("INVALID_DEEP_QUOTE")
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            leg_reasons.append("MISSING_POSITIVE_TWO_SIDED_QUOTES")
        elif bid > ask:
            leg_reasons.append("CROSSED_QUOTES")
        elif (ask - bid) / (bid + (ask - bid) / 2) > criteria["max_spread_ratio"]:
            leg_reasons.append("SPREAD_TOO_WIDE")
        if bid_size is None or ask_size is None or bid_size <= 0 or ask_size <= 0:
            leg_reasons.append("MISSING_POSITIVE_QUOTE_DEPTH")
        elif (bid_size if raw["side"] == "SELL" else ask_size) < raw["contract_size"]:
            leg_reasons.append("INSUFFICIENT_QUOTE_DEPTH")
        if quote.get("state") != "open":
            leg_reasons.append("INSTRUMENT_NOT_OPEN")
        if quote_time is None or observed_at is None:
            leg_reasons.append("MISSING_EXCHANGE_QUOTE_TIME")
        else:
            age = (clock - quote_time).total_seconds()
            if age > QUOTE_MAX_AGE_SECONDS or age < -QUOTE_FUTURE_TOLERANCE_SECONDS:
                leg_reasons.append("STALE_OR_FUTURE_QUOTE")
            if observed_at < quote_time - timedelta(seconds=QUOTE_FUTURE_TOLERANCE_SECONDS) or observed_at > clock + timedelta(seconds=QUOTE_FUTURE_TOLERANCE_SECONDS):
                leg_reasons.append("INVALID_OBSERVATION_CLOCK")
            observed_times.append(quote_time)
            limits.append(quote_time + timedelta(seconds=QUOTE_MAX_AGE_SECONDS))
        reasons.extend(_reason(code, f"{raw['instrument_name']}: {code}") for code in dict.fromkeys(leg_reasons))
        iv = _number(quote.get("mark_iv"))
        iv_decimal = iv / 100 if iv is not None and iv > 0 and quote.get("iv_unit") == "percent_points" else None
        legs.append({
            **{key: raw[key] for key in ("instrument_name", "side", "ratio", "contract_size", "strike", "option_type", "price_currency", "settlement_currency")},
            "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size,
            "quote_time": _iso(quote_time) if quote_time is not None else None,
            "observed_at": _iso(observed_at) if observed_at is not None else None,
            "iv_decimal": iv_decimal,
            "delivery_fee_applies": raw["settlement_period"] != "day",
        })
    span = (max(observed_times) - min(observed_times)).total_seconds() if observed_times else None
    if span is not None and span > QUOTE_SYNC_SECONDS:
        reasons.append(_reason("LEGS_NOT_SYNCHRONIZED", "Exchange quote clocks differ by more than two seconds."))
    economics: dict[str, Any] = {
        "entry_cash": None, "net_entry_cash": None, "premium_kind": "credit",
        "entry_fees": None, "mid_to_touch_drag": None, "option_payoff_loss_bound": None,
        "loss_bound_scope": LOSS_BOUND_SCOPE, "currency": "USDC", "fee_policy_id": FEE_POLICY_ID,
    }
    if not reasons:
        try:
            index = float(_mapping(snapshot.get("index"))["price"])
            gross = math.fsum((-1 if leg["side"] == "BUY" else 1) * (leg["ask"] if leg["side"] == "BUY" else leg["bid"]) * leg["contract_size"] for leg in legs)
            fees = math.fsum(option_fee_linear(leg["ask"] if leg["side"] == "BUY" else leg["bid"], index, 1.0, leg["contract_size"]) for leg in legs)
            mid_cash = math.fsum((-1 if leg["side"] == "BUY" else 1) * (leg["bid"] + (leg["ask"] - leg["bid"]) / 2) * leg["contract_size"] for leg in legs)
            profile = _structure(legs, str(provisional["structure"])).risk_profile(entry_cash=gross)
            economics.update(entry_cash=_rounded(gross), net_entry_cash=_rounded(gross - fees), entry_fees=_rounded(fees), mid_to_touch_drag=_rounded(mid_cash - gross), option_payoff_loss_bound=_rounded(profile.max_loss) if profile.max_loss is not None else None)
            if gross - fees <= 0:
                reasons.append(_reason("NO_NET_CREDIT_AFTER_STANDARD_FEES", "Conservative quoted credit does not cover standard entry fees."))
            if profile.max_loss is None:
                reasons.append(_reason("UNBOUNDED_OPTION_PAYOFF", "The exact option payoff has no finite quote-currency loss bound."))
        except (ValueError, OverflowError):
            reasons.append(_reason("NON_FINITE_ECONOMICS", "Verified units and quote values cannot yield a finite calculation."))
    status = "comparable" if not reasons else "research_only"
    if any(reason["code"] in {"NO_NET_CREDIT_AFTER_STANDARD_FEES", "UNBOUNDED_OPTION_PAYOFF", "NON_FINITE_ECONOMICS"} for reason in reasons):
        status = "excluded"
    if not reasons and any(leg["iv_decimal"] is None for leg in legs):
        reasons.append(_reason("IV_UNAVAILABLE", "Expiry payoff remains comparable; theoretical time/IV stress is unavailable."))
    return {
        **{key: provisional[key] for key in ("candidate_id", "structure", "viewpoint", "expiry_date", "expiration_timestamp", "dte_days", "rank", "discovery_basis")},
        "status": status, "reasons": reasons, "legs": legs, "economics": economics, "quote_span_seconds": span,
        "invalidation": [
            _reason("QUOTE_OR_DEPTH_CHANGED", "Re-fetch exact legs if prices, depth, instrument state, or currency metadata changes."),
            _reason("RECHECK_DEADLINE", "After recheck_at, current comparison eligibility expires."),
            _reason("DELIVERY_COST_NOT_ABSOLUTE_BOUND", "Option payoff loss bound excludes fees and is not an absolute total loss bound."),
        ],
        "recheck_at": _iso(min(limits)), "assumptions_id": assumptions_id,
    }


def _expiry_pnl(candidate: Mapping[str, Any], price: float) -> float:
    value = _structure(candidate["legs"], candidate["structure"]).value_at(price)
    delivery = math.fsum(
        delivery_fee_linear(_intrinsic(leg, price), price, 1.0, leg["contract_size"], delivery_fee_applies=leg["delivery_fee_applies"])
        for leg in candidate["legs"]
    )
    return _rounded(candidate["economics"]["net_entry_cash"] + value - delivery)


def _stress(candidate: Mapping[str, Any], index: float, dte: float, scenario: Mapping[str, float]) -> dict[str, Any] | None:
    try:
        return _stress_checked(candidate, index, dte, scenario)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _stress_checked(candidate: Mapping[str, Any], index: float, dte: float, scenario: Mapping[str, float]) -> dict[str, Any] | None:
    price = index * (1 + scenario["price_change_pct"] / 100)
    remaining = dte - scenario["time_days"]
    if remaining <= 1e-10:
        return {"theoretical_value": _structure(candidate["legs"], candidate["structure"]).value_at(price), "hypothetical_pnl": _expiry_pnl(candidate, price), "basis": "EXPIRY_INTRINSIC_AND_DELIVERY_FEES", "reason": None}
    valuations = []
    exit_cash = []
    exit_fees = []
    for leg in candidate["legs"]:
        iv = leg["iv_decimal"]
        if iv is None:
            return None
        shifted_iv = iv * 100 + scenario["iv_shift_points"]
        if shifted_iv <= 0:
            return None
        theoretical = black_scholes_price(underlying_price=price, strike=leg["strike"], iv_percent=shifted_iv, dte_days=remaining, option_type=leg["option_type"])
        if theoretical is None or not math.isfinite(theoretical):
            return None
        half_spread = (leg["ask"] - leg["bid"]) / 2
        close_reference = max(theoretical - half_spread, 0) if leg["side"] == "BUY" else theoretical + half_spread
        sign = 1 if leg["side"] == "BUY" else -1
        valuations.append(sign * theoretical * leg["contract_size"])
        exit_cash.append(sign * close_reference * leg["contract_size"])
        exit_fees.append(option_fee_linear(close_reference, price, 1.0, leg["contract_size"]))
    return {
        "theoretical_value": _rounded(math.fsum(valuations)),
        "hypothetical_pnl": _rounded(candidate["economics"]["net_entry_cash"] + math.fsum(exit_cash) - math.fsum(exit_fees)),
        "hypothetical_exit_fees": _rounded(math.fsum(exit_fees)),
        "basis": "ZERO_RATE_CARRY_MODEL_FROZEN_CURRENT_HALF_SPREAD_STANDARD_EXIT_FEES",
        "reason": None,
    }


def _structure(legs: Sequence[Mapping[str, Any]], family: str) -> Structure:
    size = float(legs[0]["contract_size"])
    if any(leg["contract_size"] != size for leg in legs):
        raise ValueError("complete structure requires a shared verified contract multiplier")
    return build_structure(structure_type=family, contract_size=size, legs=[
        {"option_type": leg["option_type"], "strike": leg["strike"], "quantity": 1 if leg["side"] == "BUY" else -1, "instrument_name": leg["instrument_name"]}
        for leg in legs
    ])


def _wing_rank(legs: Sequence[Mapping[str, Any]], index: float) -> tuple[float, str]:
    short = next(leg for leg in legs if leg["side"] == "SELL")
    width = abs(legs[0]["strike"] - legs[1]["strike"]) / index
    score = abs(short["strike"] / index - 1) + 0.25 * width + 0.1 * sum(leg["spread_ratio"] for leg in legs) / 2 + 0.001 * short["dte_days"]
    return score, ":".join(sorted(str(leg["instrument_name"]) for leg in legs))


def _candidate_rank(candidate: Mapping[str, Any]) -> tuple[float, int, str]:
    return candidate["discovery_score"], candidate["expiration_timestamp"], candidate["candidate_id"]


def _strike_key(leg: Mapping[str, Any]) -> tuple[float, str]:
    return leg["strike"], leg["instrument_name"]


def _snapshot_errors(snapshot: Mapping[str, Any], clock: datetime) -> list[dict[str, str]]:
    errors = []
    asset = snapshot.get("asset")
    if not isinstance(snapshot.get("snapshot_id"), str) or not snapshot.get("snapshot_id"):
        errors.append(_reason("MISSING_SNAPSHOT_IDENTITY", "Snapshot identity is missing."))
    if not isinstance(asset, str) or asset not in {"BTC", "ETH"} or snapshot.get("contract_family") != "LINEAR_USDC":
        errors.append(_reason("UNSUPPORTED_MARKET", "This comparison supports only BTC/ETH linear USDC options."))
    source = _mapping(snapshot.get("source"))
    if not isinstance(source.get("mode"), str) or source.get("mode") not in {"live", "demo", "replay"} or not isinstance(source.get("provider"), str) or not source.get("provider"):
        errors.append(_reason("MISSING_SOURCE_PROVENANCE", "Explicit source mode and provider are required."))
    index = _mapping(snapshot.get("index"))
    price = _number(index.get("price"))
    if price is None or price <= 0 or index.get("currency") != "USDC":
        errors.append(_reason("MISSING_USDC_INDEX", "A positive, explicit USDC index price is required."))
    if not isinstance(asset, str) or index.get("name") != f"{asset.lower()}_usdc":
        errors.append(_reason("INDEX_IDENTITY_MISMATCH", "The index must match the asset's explicit linear USDC registry index."))
    index_time = _timestamp(index.get("observed_at"))
    if index_time is None or not -QUOTE_FUTURE_TOLERANCE_SECONDS <= (clock - index_time).total_seconds() <= QUOTE_MAX_AGE_SECONDS:
        errors.append(_reason("STALE_OR_MISSING_INDEX_CLOCK", "Explicit current USDC index observation clock is required."))
    captured, expires = _timestamp(snapshot.get("captured_at")), _timestamp(snapshot.get("expires_at"))
    if captured is None or expires is None or expires <= captured:
        errors.append(_reason("INVALID_SNAPSHOT_CLOCK", "Explicit capture and expiry clocks are required."))
    elif expires <= clock:
        errors.append(_reason("SNAPSHOT_EXPIRED", "Snapshot expired; re-fetch before current comparison."))
    elif captured > clock + timedelta(seconds=QUOTE_FUTURE_TOLERANCE_SECONDS):
        errors.append(_reason("FUTURE_SNAPSHOT", "Snapshot capture clock is in the future."))
    return errors


def _criteria(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is not None and not isinstance(value, Mapping):
        raise ValueError("research criteria must be an object")
    result = {**DEFAULT_CRITERIA, **dict(value or {})}
    if not isinstance(result["viewpoint"], str) or result["viewpoint"] not in {"all", "bullish", "bearish", "range"}:
        raise ValueError("unsupported research viewpoint")
    for key in ("dte_min", "dte_max", "max_width_pct", "max_spread_ratio"):
        number = _number(result[key])
        if number is None or number <= 0:
            raise ValueError(f"{key} must be positive and finite")
        result[key] = number
    if result["dte_min"] > result["dte_max"] or result["dte_max"] > 365 or result["max_width_pct"] > 1 or result["max_spread_ratio"] > 2:
        raise ValueError("research filters have invalid or excessive bounds")
    return {key: result[key] for key in DEFAULT_CRITERIA}


def _scenario(value: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("scenario must be an object")
    result = {}
    for key in ("price_change_pct", "time_days", "iv_shift_points"):
        number = _number(value.get(key))
        if number is None:
            raise ValueError(f"scenario {key} must be finite")
        result[key] = number
    if not -50 <= result["price_change_pct"] <= 50 or not 0 <= result["time_days"] <= 365 or not -30 <= result["iv_shift_points"] <= 30:
        raise ValueError("scenario outside supported deterministic bounds")
    return result


def _identity_quotes(quotes: Mapping[str, Any]) -> dict[str, Any]:
    # Invalid raw numeric values remain unavailable; canonical hashing must not
    # crash or turn NaN into an identity for a supposedly valid quote.
    return {str(name): {
        **{key: _number(_mapping(quote).get(key)) for key in ("bid", "ask", "bid_size", "ask_size", "mark_iv", "exchange_timestamp")},
        **{key: _mapping(quote).get(key) if isinstance(_mapping(quote).get(key), (str, bool)) else None for key in ("observed_at", "state", "iv_unit", "valid")},
    } for name, quote in sorted(quotes.items())}


def _assumptions() -> list[str]:
    return [
        "One fixed ratio unit per leg with explicit venue contract multiplier; no account sizing or execution authorization.",
        "Entry references sell bid / buy ask, with standard per-leg fees and no account or combo discounts; spread drag is already included, not deducted twice.",
        "Option payoff loss bound excludes all trading and dynamic delivery fees; it is not an absolute total-loss guarantee.",
        "Expiry values use hypothetical USDC settlement index values and per-leg delivery fees; daily exemption requires explicit registry settlement_period=day.",
        "Pre-expiry stress uses a zero-rate, zero-carry model with scenario index treated as forward and frozen current half-spreads; future executable quotes are unknown.",
        "Scenario values are conditional calculations, not probabilities, expected returns, historical evidence or recommendation scores.",
    ]


def _intrinsic(leg: Mapping[str, Any], price: float) -> float:
    strike = float(leg["strike"])
    return max(price - strike, 0) if leg["option_type"] == "call" else max(strike - price, 0)


def _reason(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _milliseconds(value: Any) -> datetime | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    try:
        return datetime.fromtimestamp(number / 1000, UTC)
    except (OverflowError, ValueError, OSError):
        return None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:]):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _clock(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = _timestamp(value)
    if parsed is None:
        raise ValueError("evaluation_clock must be an explicit UTC-offset timestamp")
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _rounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("calculation produced a non-finite result")
    return round(value, 8)
