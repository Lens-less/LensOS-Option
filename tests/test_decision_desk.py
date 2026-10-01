"""Deterministic decision-desk contract, quote gates and currency math checks."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from crypto_options_report.decision_desk import (
    build_desk,
    compare_candidates,
    enumerate_provisional,
    evaluate_exact,
    validate_criteria,
    validate_exact_candidate,
)

CLOCK = "2026-10-01T00:00:00Z"
NOW = datetime.fromisoformat(CLOCK.replace("Z", "+00:00"))
EXPIRY = int((NOW + timedelta(days=14)).timestamp() * 1000)
SCENARIO = {"price_change_pct": 0, "time_days": 0, "iv_shift_points": 0}


def snapshot(*, asset: str = "BTC", size: float = 1, settlement: str = "month") -> dict:
    value = {
        "schema_version": "desk_market.v1", "snapshot_id": "fixture:linear:1",
        "asset": asset, "contract_family": "LINEAR_USDC", "captured_at": CLOCK,
        "expires_at": (NOW + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
        "source": {"mode": "demo", "provider": "synthetic fixture", "captured_at": CLOCK},
        "index": {"price": 100, "currency": "USDC", "name": f"{asset.lower()}_usdc", "observed_at": CLOCK},
        "instruments": {}, "summaries": {}, "quotes": {},
        "coverage": {"registry_count": 4, "summary_count": 4, "scan_complete": True, "inverse_excluded_count": 30, "eligible_instrument_count": 4, "deepened_count": 4, "failures": [], "exclusions": {}, "expiry_counts": [{"expiry_date": "2026-10-15", "count": 4}]},
    }
    for option_type, strike, bid, ask in (("put", 90, 1.9, 2), ("put", 95, 3, 3.1), ("call", 105, 3, 3.1), ("call", 110, 1.9, 2)):
        add_leg(value, option_type, strike, bid, ask, size=size, settlement=settlement)
    return value


def add_leg(value: dict, option_type: str, strike: float, bid: float, ask: float, *, size: float = 1, settlement: str = "month", expiry: int = EXPIRY) -> str:
    name = f"{value['asset']}_USDC-{expiry}-{strike}-{option_type[0].upper()}"
    value["instruments"][name] = {
        "instrument_name": name, "asset": value["asset"], "option_type": option_type,
        "strike": strike, "expiration_timestamp": expiry, "contract_size": size,
        "instrument_type": "linear", "price_currency": "USDC", "settlement_currency": "USDC",
        "active": True, "eligible": True, "validation_errors": [], "raw_settlement_period": settlement,
        "tick_size": 0.01, "min_trade_amount": 0.1, "index_name": f"{value['asset'].lower()}_usdc",
    }
    value["summaries"][name] = {"bid": bid, "ask": ask, "mark_iv": 50, "iv_unit": "percent_points", "observed_at": CLOCK}
    value["quotes"][name] = {"bid": bid, "ask": ask, "bid_size": 10, "ask_size": 10, "mark_iv": 50, "iv_unit": "percent_points", "exchange_timestamp": int(NOW.timestamp() * 1000), "observed_at": CLOCK, "state": "open", "valid": True, "validation_errors": []}
    return name


def candidates_by_family(desk: dict) -> dict:
    return {item["structure"]: item for item in desk["candidates"]}


def comparison(desk: dict, scenario: dict | None = None) -> dict:
    return compare_candidates(desk, [item["candidate_id"] for item in desk["candidates"]], scenario or SCENARIO, evaluation_clock=CLOCK)


@pytest.mark.parametrize("asset", ["BTC", "ETH"])
def test_complete_touch_structures_share_frozen_units_and_standard_costs(asset: str) -> None:
    value = snapshot(asset=asset, size=0.5)
    first = build_desk(value, evaluation_clock=CLOCK)
    assert first == build_desk(deepcopy(value), evaluation_clock=CLOCK)
    assert first["qualification"] == {"data_status": "current", "opportunity_status": "available", "exclusion_counts": {}, "execution_allowed": False}
    assert first["research_only"] is True
    assert first["coverage"]["inverse_excluded_count"] == 30
    assert first["coverage"]["formed_structure_count"] == 3
    families = candidates_by_family(first)
    for family, gross, fees, bound in (("BULL_PUT_CREDIT", 0.5, 0.03, 2), ("BEAR_CALL_CREDIT", 0.5, 0.03, 2), ("IRON_CONDOR", 1, 0.06, 1.5)):
        item = families[family]
        assert item["status"] == "comparable"
        assert item["economics"]["entry_cash"] == gross
        assert item["economics"]["entry_fees"] == fees
        assert item["economics"]["net_entry_cash"] == gross - fees
        assert item["economics"]["option_payoff_loss_bound"] == bound
        assert item["economics"]["mid_to_touch_drag"] == pytest.approx(0.05 if family != "IRON_CONDOR" else 0.1)
        assert len({leg["contract_size"] for leg in item["legs"]}) == 1
        assert all(leg["ratio"] == 1 and leg["price_currency"] == leg["settlement_currency"] == "USDC" for leg in item["legs"])
    assert len({item["assumptions_id"] for item in first["candidates"]}) == 1
    altered = deepcopy(value)
    altered["quotes"][next(iter(altered["quotes"]))]["bid"] -= 0.01
    new = build_desk(altered, evaluation_clock=CLOCK)
    assert first["analysis_id"] != new["analysis_id"]
    assert first["assumptions_id"] != new["assumptions_id"]


def test_expiry_curve_and_time_iv_stress_use_same_scenario_without_probability() -> None:
    desk = build_desk(snapshot(), evaluation_clock=CLOCK)
    result = comparison(desk, {"price_change_pct": 5, "time_days": 2, "iv_shift_points": 5})
    grids = [[point["price"] for point in member["expiry_points"]] for member in result["members"]]
    assert grids[0] == grids[1] == grids[2]
    assert {90, 95, 100, 105, 110}.issubset(grids[0])
    assert result["scenario"] == {"price_change_pct": 5, "time_days": 2, "iv_shift_points": 5}
    assert result["execution_allowed"] is False
    assert result["analysis_id"] == desk["analysis_id"]
    assert "probability" not in result and "score" not in result
    assert all(member["stress"] and math.isfinite(member["stress"]["hypothetical_pnl"]) for member in result["members"])
    bull_id = candidates_by_family(desk)["BULL_PUT_CREDIT"]["candidate_id"]
    bull = next(member for member in result["members"] if member["candidate_id"] == bull_id)
    pnl = {point["price"]: point["pnl"] for point in bull["expiry_points"]}
    assert pnl[100] == 0.94  # touch credit 1 minus two standard entry fees
    assert pnl[90] == pytest.approx(-4.0735)  # exact put payoff minus entry and delivery fees
    expiry = comparison(desk, {"price_change_pct": -10, "time_days": 14, "iv_shift_points": 0})
    expiry_bull = next(member for member in expiry["members"] if member["candidate_id"] == bull_id)
    assert expiry_bull["stress"]["hypothetical_pnl"] == pnl[90]
    assert expiry_bull["stress"]["basis"] == "EXPIRY_INTRINSIC_AND_DELIVERY_FEES"
    assert result["scenario_id"] != expiry["scenario_id"]


def test_daily_delivery_exemption_is_explicit_and_not_an_absolute_loss_bound() -> None:
    monthly = comparison(build_desk(snapshot(), evaluation_clock=CLOCK))
    daily = comparison(build_desk(snapshot(settlement="day"), evaluation_clock=CLOCK))
    for month_member, daily_member in zip(monthly["members"], daily["members"]):
        at90_month = next(point["pnl"] for point in month_member["expiry_points"] if point["price"] == 90)
        at90_daily = next(point["pnl"] for point in daily_member["expiry_points"] if point["price"] == 90)
        assert at90_daily >= at90_month
    desk = build_desk(snapshot(), evaluation_clock=CLOCK)
    assert candidates_by_family(desk)["BULL_PUT_CREDIT"]["economics"]["option_payoff_loss_bound"] == 4
    assert any("not an absolute" in item for item in desk["assumptions"])


@pytest.mark.parametrize("mutation,code", [
    (lambda q: q.update(bid=None), "MISSING_POSITIVE_TWO_SIDED_QUOTES"),
    (lambda q: q.update(bid=4, ask=3), "CROSSED_QUOTES"),
    (lambda q: q.update(ask=20), "SPREAD_TOO_WIDE"),
    (lambda q: q.update(bid_size=0.01, ask_size=0.01), "INSUFFICIENT_QUOTE_DEPTH"),
    (lambda q: q.update(state="closed"), "INSTRUMENT_NOT_OPEN"),
    (lambda q: q.update(exchange_timestamp=None), "MISSING_EXCHANGE_QUOTE_TIME"),
    (lambda q: q.update(exchange_timestamp=int((NOW - timedelta(seconds=61)).timestamp() * 1000)), "STALE_OR_FUTURE_QUOTE"),
    (lambda q: q.update(exchange_timestamp=int((NOW + timedelta(seconds=6)).timestamp() * 1000)), "STALE_OR_FUTURE_QUOTE"),
    (lambda q: q.update(exchange_timestamp=int((NOW - timedelta(seconds=3)).timestamp() * 1000)), "LEGS_NOT_SYNCHRONIZED"),
    (lambda q: q.update(bid=float("nan")), "MISSING_POSITIVE_TWO_SIDED_QUOTES"),
    (lambda q: q.update(bid=True), "MISSING_POSITIVE_TWO_SIDED_QUOTES"),
])
def test_bad_deep_quote_never_falls_back_to_discovery_summary(mutation, code: str) -> None:
    value = snapshot()
    name = next(iter(value["quotes"]))
    mutation(value["quotes"][name])
    desk = build_desk(value, evaluation_clock=CLOCK)
    for candidate in desk["candidates"]:
        if any(leg["instrument_name"] == name for leg in candidate["legs"]):
            assert candidate["status"] == "research_only"
            assert code in {reason["code"] for reason in candidate["reasons"]}
            assert candidate["economics"]["entry_cash"] is None
    assert desk["qualification"]["data_status"] == "partial"


def test_missing_deep_quotes_and_iv_have_distinct_honest_results() -> None:
    value = snapshot()
    value["quotes"] = {}
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["qualification"]["opportunity_status"] == "data_blocked"
    assert all(item["status"] == "research_only" for item in desk["candidates"])
    with pytest.raises(ValueError, match="complete current"):
        comparison(desk)
    value = snapshot()
    for quote in value["quotes"].values():
        quote["mark_iv"] = None
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert all(item["status"] == "comparable" for item in desk["candidates"])
    result = comparison(desk)
    assert all(member["stress"] is None and member["stress_reason"] for member in result["members"])
    assert all(member["expiry_points"] for member in result["members"])
    # Intrinsic settlement needs no IV; it remains an explicit expiry scenario.
    at_expiry = comparison(desk, {"price_change_pct": 0, "time_days": 14, "iv_shift_points": -30})
    assert all(member["stress"] is not None for member in at_expiry["members"])


def test_full_registry_scan_discloses_formed_vs_bounded_shortlist() -> None:
    value = snapshot()
    value["instruments"], value["summaries"], value["quotes"] = {}, {}, {}
    for i in range(100):
        strike = 80 + i * 0.2
        add_leg(value, "put", strike, 1 + i * 0.1, 1.01 + i * 0.1)
        add_leg(value, "call", 100.2 + i * 0.2, 11 - i * 0.1, 11.01 - i * 0.1)
    scan = enumerate_provisional(value, evaluation_clock=CLOCK)
    assert scan["counts"]["scanned_instrument_count"] == 200
    assert scan["counts"]["filter_matched_instrument_count"] == 200
    assert scan["counts"]["formed_structure_count"] > 10000
    assert scan["counts"]["shortlisted_count"] == scan["counts"]["shortlist_limit"] == 48
    assert len(scan["candidates"]) == 48
    assert {item["structure"] for item in scan["candidates"]} == {"BULL_PUT_CREDIT", "BEAR_CALL_CREDIT", "IRON_CONDOR"}
    for item in scan["candidates"]:
        if item["structure"] == "IRON_CONDOR":
            puts = [leg for leg in item["legs"] if leg["option_type"] == "put"]
            calls = [leg for leg in item["legs"] if leg["option_type"] == "call"]
            assert max(leg["strike"] for leg in puts) < min(leg["strike"] for leg in calls)


def test_atm_overlap_and_mixed_contract_multipliers_do_not_form_condors() -> None:
    value = snapshot()
    add_leg(value, "put", 100, 4, 4.1)
    add_leg(value, "call", 100, 4, 4.1)
    add_leg(value, "call", 102, 3.5, 3.6, size=2)
    add_leg(value, "call", 108, 2.5, 2.6, size=2)
    scan = enumerate_provisional(value, evaluation_clock=CLOCK)
    for item in scan["candidates"]:
        assert len({leg["contract_size"] for leg in item["legs"]}) == 1
        if item["structure"] == "IRON_CONDOR":
            shorts = sorted(leg["strike"] for leg in item["legs"] if leg["side"] == "SELL")
            assert shorts[0] < shorts[1]


def test_missing_summary_invalid_metadata_and_inverse_are_counted_without_invention() -> None:
    value = snapshot()
    names = list(value["instruments"])
    value["instruments"][names[0]]["instrument_type"] = "reversed"
    value["instruments"][names[1]]["validation_errors"] = ["missing tick size"]
    value["summaries"].pop(names[2])
    scan = enumerate_provisional(value, evaluation_clock=CLOCK)
    assert scan["counts"]["scanned_instrument_count"] == 4
    assert scan["exclusion_counts"]["UNSUPPORTED_CONTRACT_FAMILY"] == 1
    assert scan["exclusion_counts"]["INCOMPLETE_INSTRUMENT_METADATA"] == 1
    assert scan["exclusion_counts"]["MISSING_POSITIVE_TWO_SIDED_QUOTES"] == 1
    assert scan["candidates"] == []


def test_fee_cap_can_remove_apparent_credit() -> None:
    value = snapshot()
    for name, metadata in value["instruments"].items():
        short = metadata["strike"] in {95, 105}
        bid, ask = (0.01, 0.01001) if short else (0.00989, 0.0099)
        value["summaries"][name].update(bid=bid, ask=ask)
        value["quotes"][name].update(bid=bid, ask=ask)
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["qualification"]["opportunity_status"] == "risk_blocked"
    assert all(item["status"] == "excluded" for item in desk["candidates"])
    bull = candidates_by_family(desk)["BULL_PUT_CREDIT"]
    assert bull["economics"]["entry_fees"] == pytest.approx((0.01 + 0.0099) * 0.125)


def test_compare_requires_original_identity_shared_expiry_and_unexpired_quotes() -> None:
    value = snapshot()
    add_leg(value, "put", 92, 2.2, 2.3, expiry=EXPIRY + 86400000)
    add_leg(value, "put", 97, 3.2, 3.3, expiry=EXPIRY + 86400000)
    desk = build_desk(value, evaluation_clock=CLOCK)
    first = desk["candidates"][0]
    later = next(item for item in desk["candidates"] if item["expiration_timestamp"] != first["expiration_timestamp"])
    with pytest.raises(ValueError, match="shared expiration"):
        compare_candidates(desk, [first["candidate_id"], later["candidate_id"]], SCENARIO, evaluation_clock=CLOCK)
    tampered = deepcopy(desk)
    tampered["candidates"][0]["economics"]["entry_cash"] = 1000
    with pytest.raises(ValueError, match="identity"):
        compare_candidates(tampered, [item["candidate_id"] for item in desk["candidates"][:2]], SCENARIO, evaluation_clock=CLOCK)
    with pytest.raises(ValueError, match="expired"):
        compare_candidates(desk, [item["candidate_id"] for item in desk["candidates"][:2]], SCENARIO, evaluation_clock=(NOW + timedelta(seconds=61)).isoformat())
    with pytest.raises(ValueError, match="two or three"):
        compare_candidates(desk, [first["candidate_id"]] * 2, SCENARIO, evaluation_clock=CLOCK)


@pytest.mark.parametrize("scenario", [
    {"price_change_pct": -51, "time_days": 0, "iv_shift_points": 0},
    {"price_change_pct": 0, "time_days": 15, "iv_shift_points": 0},
    {"price_change_pct": 0, "time_days": 0, "iv_shift_points": 31},
    {"price_change_pct": True, "time_days": 0, "iv_shift_points": 0},
])
def test_scenario_bounds_fail_closed(scenario: dict) -> None:
    with pytest.raises(ValueError):
        comparison(build_desk(snapshot(), evaluation_clock=CLOCK), scenario)


def test_expired_snapshot_or_index_clock_does_not_return_current_candidates() -> None:
    value = snapshot()
    value["expires_at"] = CLOCK
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["qualification"]["data_status"] == "unavailable"  # invalid capture/expiry relation
    assert desk["candidates"] == []
    value = snapshot()
    value["captured_at"] = (NOW - timedelta(seconds=61)).isoformat()
    value["expires_at"] = CLOCK
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["qualification"]["data_status"] == "stale"
    value = snapshot()
    value["index"].pop("observed_at")
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["qualification"]["opportunity_status"] == "data_blocked"
    assert desk["candidates"] == []


def test_exact_review_ignores_saved_costs_and_preserves_missing_or_changed_names() -> None:
    value = snapshot()
    original = candidates_by_family(build_desk(value, evaluation_clock=CLOCK))["BULL_PUT_CREDIT"]
    original["economics"]["entry_cash"] = 9999
    original["status"] = "excluded"
    reviewed = evaluate_exact(value, original, evaluation_clock=CLOCK)
    assert len(reviewed["candidates"]) == 1
    assert reviewed["candidates"][0]["economics"]["entry_cash"] == 1
    assert reviewed["candidates"][0]["status"] == "comparable"
    saved_names = {leg["instrument_name"] for leg in original["legs"]}
    name = next(iter(saved_names))
    value["instruments"][name]["strike"] += 1
    changed = evaluate_exact(value, original, evaluation_clock=CLOCK)["candidates"][0]
    assert changed["status"] == "research_only"
    assert changed["economics"]["entry_cash"] is None
    assert "EXACT_METADATA_CHANGED_OR_INVALID" in {reason["code"] for reason in changed["reasons"]}
    value["instruments"].pop(name)
    missing = evaluate_exact(value, original, evaluation_clock=CLOCK)["candidates"][0]
    assert {leg["instrument_name"] for leg in missing["legs"]} == saved_names
    assert "EXACT_INSTRUMENT_UNAVAILABLE" in {reason["code"] for reason in missing["reasons"]}


def test_exact_review_cannot_change_family_ratios_or_make_expired_leg_current() -> None:
    value = snapshot()
    original = candidates_by_family(build_desk(value, evaluation_clock=CLOCK))["IRON_CONDOR"]
    forged = deepcopy(original)
    forged["legs"][0]["ratio"] = 2
    with pytest.raises(ValueError, match="fixed ratios"):
        evaluate_exact(value, forged, evaluation_clock=CLOCK)
    forged = deepcopy(original)
    forged["structure"] = "BULL_PUT_CREDIT"
    with pytest.raises(ValueError, match="all legs"):
        evaluate_exact(value, forged, evaluation_clock=CLOCK)
    past = (NOW + timedelta(days=15)).isoformat()
    reviewed = evaluate_exact(value, original, evaluation_clock=past)
    candidate = reviewed["candidates"][0]
    assert candidate["status"] == "research_only"
    assert candidate["economics"]["entry_cash"] is None
    assert "EXACT_EXPIRY_PASSED" in {reason["code"] for reason in candidate["reasons"]}


def test_coverage_failures_remain_visible_and_partial() -> None:
    value = snapshot()
    value["coverage"]["failures"] = [{"code": "RATE_LIMITED", "scope": "USDC", "message": "retry later"}]
    value["coverage"]["scan_complete"] = False
    desk = build_desk(value, evaluation_clock=CLOCK)
    assert desk["coverage"]["failures"] == ["RATE_LIMITED (USDC): retry later"]
    assert desk["qualification"]["data_status"] == "partial"
    assert desk["qualification"]["opportunity_status"] == "available"


def test_preflight_rejects_json_types_before_any_source_is_required() -> None:
    with pytest.raises(ValueError, match="viewpoint"):
        validate_criteria({"viewpoint": []})
    with pytest.raises(ValueError, match="positive and finite"):
        validate_criteria({"max_spread_ratio": True})
    with pytest.raises(ValueError, match="supported complete"):
        validate_exact_candidate({"structure": [], "legs": []})
    original = candidates_by_family(build_desk(snapshot(), evaluation_clock=CLOCK))["BULL_PUT_CREDIT"]
    clean = validate_exact_candidate(original)
    assert set(clean) == {"structure", "expiration_timestamp", "legs"}
    assert "economics" not in clean and "status" not in clean and "candidate_id" not in clean
    original["legs"][0]["side"] = []
    with pytest.raises(ValueError, match="valid USDC leg metadata"):
        validate_exact_candidate(original)
