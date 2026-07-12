"""Research-only EV candidate scanner with kill-condition gating for ISSUE-010."""

from __future__ import annotations

from datetime import datetime, time, timezone
from math import sqrt
from typing import Any

from .path_risk import build_path_risk_distribution_report
from .pnl import combo_fee, option_fee_linear

DEFAULT_SCANNER_LIMITS = {
    "max_market_data_age_sec": 60.0,
    "max_account_data_age_ms": 30_000.0,
    "max_spread_ratio": 0.25,
    "min_depth_contracts": 9.0,
    "hazard_atr_buffer": 0.5,
    "hazard_expected_move_floor_pct": 0.10,
    "slippage_half_spread_fraction": 0.50,
    "hedge_cost_delta_fraction": 0.0015,
    "fair_iv_discount": 0.85,
    "score_penalty_reject": 100.0,
    "score_penalty_review": 5.0,
}

_BASE_HISTORICAL_PATHS = [
    {
        "path_id": "touch-revert",
        "start_time": "2026-01-08T00:00:00Z",
        "returns": [0.10, 0.11, -0.12, -0.03, 0.00, 0.00, 0.00],
        "source_realized_vol": 0.60,
        "feature_vector": {
            "dvol_percentile": 0.77,
            "atm_iv_percentile": 0.75,
            "trend_7d": 0.17,
        },
    },
    {
        "path_id": "grind-higher",
        "start_time": "2026-02-05T00:00:00Z",
        "returns": [0.03, 0.02, 0.02, 0.01, 0.01, 0.00, 0.00],
        "source_realized_vol": 0.58,
        "feature_vector": {
            "dvol_percentile": 0.88,
            "atm_iv_percentile": 0.86,
            "trend_7d": 0.22,
        },
    },
    {
        "path_id": "selloff",
        "start_time": "2026-03-05T00:00:00Z",
        "returns": [-0.04, -0.03, 0.01, -0.02, 0.00, 0.01, 0.00],
        "source_realized_vol": 0.50,
        "feature_vector": {
            "dvol_percentile": 0.30,
            "atm_iv_percentile": 0.35,
            "trend_7d": -0.08,
        },
    },
]

_BASE_FALLBACK_POOL = [
    {
        "path_id": "late-breakout",
        "start_time": "2025-11-06T00:00:00Z",
        "returns": [0.02, 0.03, 0.04, 0.06, 0.05, -0.02, -0.01],
        "source_realized_vol": 0.63,
        "feature_vector": {
            "dvol_percentile": 0.71,
            "atm_iv_percentile": 0.69,
            "trend_7d": 0.14,
        },
    },
    {
        "path_id": "deep-itm",
        "start_time": "2025-12-04T00:00:00Z",
        "returns": [0.08, 0.07, 0.04, 0.03, 0.02, 0.01, 0.00],
        "source_realized_vol": 0.66,
        "feature_vector": {
            "dvol_percentile": 0.73,
            "atm_iv_percentile": 0.72,
            "trend_7d": 0.18,
        },
    },
]

_BASE_STRESS_SCENARIOS = [
    {
        "name": "spot-up-10-iv-jump",
        "path_returns": [0.10, 0.02, 0.01, 0.00, 0.00, 0.00, 0.00],
        "iv_jump": 0.15,
        "liquidity_exit_cost_usdc": 120.0,
        "weight": 0.03,
    },
    {
        "name": "spot-up-20-iv-jump",
        "path_returns": [0.12, 0.09, 0.02, 0.00, 0.00, 0.00, 0.00],
        "iv_jump": 0.25,
        "liquidity_exit_cost_usdc": 250.0,
        "weight": 0.01,
    },
    {
        "name": "liquidity-exit-gap",
        "path_returns": [0.05, 0.03, 0.00, -0.01, 0.00, 0.00, 0.00],
        "iv_jump": 0.10,
        "liquidity_exit_cost_usdc": 400.0,
        "weight": 0.01,
    },
]


def build_ev_candidate_scanner(
    *,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    permission_state: dict[str, Any],
    candidate_research: dict[str, Any],
) -> dict[str, Any]:
    if data_status.get("status") != "validated":
        return _blocked_scanner("VENDOR_QUALITY_FAIL")
    if candidate_research.get("status") != "validated":
        return _blocked_scanner(str(candidate_research.get("reason_code") or "NO_CANDIDATE_RESEARCH"))

    items = []
    for table_name in ("naked_short_calls", "call_credit_spreads"):
        table = candidate_research.get(table_name, {})
        for source_bucket in ("eligible", "review", "rejected"):
            for candidate in table.get(source_bucket, []):
                items.append(
                    _score_candidate(
                        candidate=candidate,
                        source_bucket=source_bucket,
                        generated_at=generated_at,
                        data_status=data_status,
                        account_status=account_status,
                        calibration_status=calibration_status,
                        permission_state=permission_state,
                    )
                )

    items.sort(
        key=lambda item: (
            item["ranking_score"],
            item["ev_after_cost_usdc"],
            -item["path_risk"]["p_touch"],
        ),
        reverse=True,
    )
    for index, item in enumerate(items, start=1):
        item["rank"] = index

    return {
        # Pipeline structure is complete, but path risk remains a research placeholder.
        "status": "validated",
        "reason_code": None,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "path_risk_evidence": {
            "status": "research_placeholder",
            "placeholder_data": True,
            "source": "hardcoded_7d_return_templates",
        },
        "recommended_size_allowed": False,
        "trade_instruction_allowed": False,
        "paper_manual_candidates_allowed": False,
        "ranked_candidates": items,
        "summary": {
            "candidates_scanned": len(items),
            "review_candidates": sum(item["action"] == "REVIEW" for item in items),
            "rejected_candidates": sum(item["action"] == "REJECT" for item in items),
            "kill_condition_candidates": sum(bool(item["kill_conditions"]) for item in items),
            "top_candidate_id": items[0]["candidate_id"] if items else None,
            "top_candidate_action": items[0]["action"] if items else None,
        },
    }


def _blocked_scanner(reason_code: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason_code": reason_code,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "path_risk_evidence": {
            "status": "unavailable",
            "placeholder_data": True,
            "source": None,
        },
        "recommended_size_allowed": False,
        "trade_instruction_allowed": False,
        "paper_manual_candidates_allowed": False,
        "ranked_candidates": [],
        "summary": {
            "candidates_scanned": 0,
            "review_candidates": 0,
            "rejected_candidates": 0,
            "kill_condition_candidates": 0,
            "top_candidate_id": None,
            "top_candidate_action": None,
        },
    }


def _score_candidate(
    *,
    candidate: dict[str, Any],
    source_bucket: str,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    permission_state: dict[str, Any],
) -> dict[str, Any]:
    limits = DEFAULT_SCANNER_LIMITS
    structure = str(candidate["structure_type"])
    underlying_price = float(candidate["underlying_price"])
    dte_days = float(candidate["dte_days"])
    surface_fitted_iv = _surface_fitted_iv(candidate)
    fair_physical_iv = round(surface_fitted_iv * limits["fair_iv_discount"], 6)
    executable_credit_usdc = _executable_credit_usdc(candidate)
    fee_usdc = _trade_fee_usdc(candidate, underlying_price)
    slippage_usdc = _slippage_usdc(candidate, underlying_price)
    hedge_cost_placeholder_usdc = round(
        abs(float(candidate["model_delta"])) * underlying_price * limits["hedge_cost_delta_fraction"],
        6,
    )
    path_risk_report = _path_risk_report(
        candidate=candidate,
        permission_state=permission_state,
        account_status=account_status,
    )
    expected_payoff_usdc = float(
        path_risk_report["distributions"]["expected_payoff_usdc"]
    )
    fair_value_usdc = round(
        expected_payoff_usdc
        + fee_usdc
        + slippage_usdc
        + hedge_cost_placeholder_usdc,
        6,
    )
    ev_after_cost_usdc = round(executable_credit_usdc - fair_value_usdc, 6)
    hazard = _hazard_zone(
        candidate=candidate,
        surface_fitted_iv=surface_fitted_iv,
    )
    kill_conditions = _kill_conditions(
        candidate=candidate,
        structure=structure,
        dte_days=dte_days,
        ev_after_cost_usdc=ev_after_cost_usdc,
        fair_physical_iv=fair_physical_iv,
        generated_at=generated_at,
        data_status=data_status,
        account_status=account_status,
        calibration_status=calibration_status,
        permission_state=permission_state,
        hazard=hazard,
    )

    review_flags: list[str] = []
    if source_bucket != "eligible":
        review_flags.append(f"UPSTREAM_{source_bucket.upper()}")
    if structure == "call_credit_spread" and hazard["status"] == "penalize":
        review_flags.append("HAZARD_ZONE_SPREAD_PENALTY")
    if calibration_status.get("calibrated") is False:
        review_flags.append("UNCALIBRATED_SCORE_MODEL")

    action = "REVIEW"
    if kill_conditions:
        action = "REJECT"
    elif not review_flags:
        action = "RESEARCH_ONLY"

    ranking_score = _ranking_score(
        ev_after_cost_usdc=ev_after_cost_usdc,
        path_risk=path_risk_report["distributions"],
        margin_snapshot=account_status.get("projected_margin", {}),
        kill_count=len(kill_conditions),
        review_count=len(review_flags),
        hazard_penalty=(0.30 if "HAZARD_ZONE_SPREAD_PENALTY" in review_flags else 0.0),
    )

    return {
        "candidate_id": candidate["candidate_id"],
        "structure_type": structure,
        "source_bucket": source_bucket,
        "action": action,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "ranking_score": ranking_score,
        "instrument_name": candidate.get("instrument_name"),
        "sell_leg_instrument_name": candidate.get("sell_leg_instrument_name"),
        "buy_leg_instrument_name": candidate.get("buy_leg_instrument_name"),
        "premium_usdc": round(executable_credit_usdc, 6),
        "executable_credit_usdc": round(executable_credit_usdc, 6),
        "fee_usdc": round(fee_usdc, 6),
        "slippage_usdc": round(slippage_usdc, 6),
        "hedge_cost_placeholder_usdc": round(hedge_cost_placeholder_usdc, 6),
        "expected_payoff_usdc": round(expected_payoff_usdc, 6),
        "fair_value_usdc": fair_value_usdc,
        "ev_after_cost_usdc": ev_after_cost_usdc,
        "fair_iv_diagnostics": {
            "bid_iv": _bid_iv(candidate),
            "fair_physical_iv": fair_physical_iv,
            "iv_edge": round(_bid_iv(candidate) - fair_physical_iv, 6),
            "surface_fitted_iv": surface_fitted_iv,
        },
        "path_risk": {
            "p_itm": path_risk_report["distributions"]["p_itm"],
            "p_touch": path_risk_report["distributions"]["p_touch"],
            "cvar_95_usdc": path_risk_report["distributions"]["cvar_95_usdc"],
            "cvar_99_usdc": path_risk_report["distributions"]["cvar_99_usdc"],
            "stress_loss_usdc": path_risk_report["distributions"]["stress_loss_usdc"],
            "stress_loss_nav_pct": path_risk_report["distributions"]["stress_loss_nav_pct"],
            "delta_cross_probability": path_risk_report["distributions"]["delta_cross_probability"],
            "report_flags": path_risk_report["report_flags"],
        },
        "margin_snapshot": {
            "account_margin_light": account_status.get("margin_light"),
            "account_trade_gate": account_status.get("trade_gate"),
            "projected_nav_to_mm": (account_status.get("projected_margin") or {}).get("nav_to_mm"),
            "projected_im_nav": (account_status.get("projected_margin") or {}).get("im_nav"),
            "delta_initial_margin": (account_status.get("projected_margin") or {}).get("delta_initial_margin"),
            "delta_maintenance_margin": (account_status.get("projected_margin") or {}).get("delta_maintenance_margin"),
        },
        "hazard_zone": hazard,
        "kill_conditions": kill_conditions,
        "review_flags": review_flags,
        "reason_codes": _unique_codes(
            list(candidate.get("decision_reason_codes", []))
            + list(candidate.get("filter_reason_codes", []))
            + review_flags
            + kill_conditions
        ),
    }


def _path_risk_report(
    *,
    candidate: dict[str, Any],
    permission_state: dict[str, Any],
    account_status: dict[str, Any],
) -> dict[str, Any]:
    regime_scores = {
        key: float(value)
        for key, value in (permission_state.get("regime_scores") or {}).items()
        if key
    }
    feature_vector = {
        "dvol_percentile": float(
            (permission_state.get("volatility_inputs") or {}).get("dvol_percentile", 0.5)
        ),
        "atm_iv_percentile": float(
            (permission_state.get("volatility_inputs") or {}).get("atm_iv_percentile", 0.5)
        ),
        "trend_7d": round(
            regime_scores.get("fast_bull_breakout", 0.0)
            - regime_scores.get("bear_trend", 0.0),
            6,
        ),
    }
    starting_nav_usdc = float(
        ((account_status.get("snapshot") or {}).get("nav_usd")) or 100000.0
    )
    surface_fitted_iv = _surface_fitted_iv(candidate)
    payload = {
        "candidate": {
            "instrument_name": candidate.get("instrument_name")
            or candidate.get("sell_leg_instrument_name"),
            "structure": candidate["structure_type"],
            "current_spot": float(candidate["underlying_price"]),
            "strike": _short_strike(candidate),
            "long_strike": candidate.get("buy_leg_strike_price"),
            "horizon_days": max(int(round(float(candidate["dte_days"]))), 2),
            "entry_credit_usdc": _executable_credit_usdc(candidate),
            "contract_size": 1.0,
            "starting_nav_usdc": starting_nav_usdc,
            "current_abs_delta": abs(float(candidate["model_delta"])),
            "delta_cross_up_return": round(
                max((_short_strike(candidate) / float(candidate["underlying_price"]) - 1.0) * 0.60, 0.03),
                6,
            ),
            "vega_usdc_per_abs_vol": round(
                abs(float(candidate["model_vega"])) * float(candidate["underlying_price"]),
                6,
            ),
            "target_realized_vol": round(max(surface_fitted_iv * 0.85 / 100.0, 0.05), 6),
            "regime_scores": regime_scores,
            "feature_vector": feature_vector,
        },
        "historical_paths": [
            {
                **path,
                "horizon_days": max(int(round(float(candidate["dte_days"]))), 2),
                "regime_scores": regime_scores,
            }
            for path in _BASE_HISTORICAL_PATHS
        ],
        "fallback_pool": [
            {
                **path,
                "horizon_days": max(int(round(float(candidate["dte_days"]))), 2),
                "regime_scores": regime_scores,
            }
            for path in _BASE_FALLBACK_POOL
        ],
        "bootstrap_source_returns": [
            0.10,
            0.11,
            -0.12,
            -0.03,
            0.02,
            0.03,
            0.04,
            0.06,
            0.05,
            -0.02,
            -0.01,
        ],
        "bootstrap_block_length": 2,
        "bootstrap_path_count": 3,
        "bootstrap_source_realized_vol": 0.58,
        "random_seed": 11,
        "stress_mixture_min_weight": 0.10,
        "stress_scenarios": list(_BASE_STRESS_SCENARIOS),
    }
    return build_path_risk_distribution_report(payload, generated_at="2026-07-07T10:30:00Z")


def _kill_conditions(
    *,
    candidate: dict[str, Any],
    structure: str,
    dte_days: float,
    ev_after_cost_usdc: float,
    fair_physical_iv: float,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    permission_state: dict[str, Any],
    hazard: dict[str, Any],
) -> list[str]:
    kills: list[str] = []
    if ev_after_cost_usdc <= 0:
        kills.append("NON_POSITIVE_EV")
    if _bid_iv(candidate) <= fair_physical_iv:
        kills.append("BID_IV_BELOW_FAIR_PHYSICAL_IV")
    if _worst_spread_ratio(candidate) > DEFAULT_SCANNER_LIMITS["max_spread_ratio"]:
        kills.append("WIDE_SPREAD")
    if _available_depth(candidate) < DEFAULT_SCANNER_LIMITS["min_depth_contracts"]:
        kills.append("INSUFFICIENT_DEPTH")
    if "BREAKOUT_KILL" in permission_state.get("reason_codes", []):
        kills.append("BREAKOUT_KILL")
    if "EVENT_KILL" in permission_state.get("reason_codes", []):
        kills.append("EVENT_KILL")

    risk_state = account_status.get("margin_light")
    trade_gate = account_status.get("trade_gate")
    if risk_state in {"RED", "HALT"} or trade_gate in {"REDUCE_EXISTING", "NO_TRADE"}:
        kills.append("RED_OR_HALT_RISK_STATE")
    elif risk_state == "YELLOW" or trade_gate == "NO_NEW_TRADES":
        kills.append("YELLOW_NO_NEW_TRADES")

    projected_nav_to_mm = (account_status.get("projected_margin") or {}).get("nav_to_mm")
    if projected_nav_to_mm is not None and projected_nav_to_mm < 1.50:
        kills.append("PROJECTED_NAV_TO_MM_BELOW_1_5")
    elif projected_nav_to_mm is not None and projected_nav_to_mm < 2.00:
        kills.append("PROJECTED_NAV_TO_MM_BELOW_2_0")

    if data_status.get("status") != "validated":
        kills.append("VENDOR_QUALITY_FAIL")
    if float(data_status.get("market_data_age_sec") or 0.0) > DEFAULT_SCANNER_LIMITS["max_market_data_age_sec"]:
        kills.append("STALE_MARKET_DATA")
    if float(account_status.get("data_age_ms") or 0.0) > DEFAULT_SCANNER_LIMITS["max_account_data_age_ms"]:
        kills.append("STALE_ACCOUNT_DATA")
    if _settlement_window_active(generated_at):
        kills.append("SETTLEMENT_WINDOW_ACTIVE")
    if structure == "naked_short_call" and hazard["status"] == "reject":
        kills.append("HAZARD_ZONE_NAKED_REJECT")
    if structure == "naked_short_call" and not permission_state.get("naked_permission"):
        kills.append("NAKED_PERMISSION_BLOCKED")
    if structure == "call_credit_spread" and not permission_state.get("spread_permission"):
        kills.append("SPREAD_PERMISSION_BLOCKED")
    if calibration_status.get("calibrated") is False:
        kills.append("UNCALIBRATED_SCORE_MODEL")
    # Default EV path library is hardcoded research placeholders, not validated history.
    kills.append("PLACEHOLDER_PATH_RISK")
    return _unique_codes(kills)


def _hazard_zone(*, candidate: dict[str, Any], surface_fitted_iv: float) -> dict[str, Any]:
    underlying_price = float(candidate["underlying_price"])
    dte_days = float(candidate["dte_days"])
    short_strike = _short_strike(candidate)
    expected_move = underlying_price * max(
        surface_fitted_iv / 100.0 * sqrt(max(dte_days, 1.0) / 365.0),
        DEFAULT_SCANNER_LIMITS["hazard_expected_move_floor_pct"],
    )
    atr_14 = expected_move / 2.0
    hazard_zone_upper = round(
        underlying_price + expected_move + DEFAULT_SCANNER_LIMITS["hazard_atr_buffer"] * atr_14,
        6,
    )
    breached = short_strike <= hazard_zone_upper
    if not breached:
        status = "clear"
    elif candidate["structure_type"] == "naked_short_call":
        status = "reject"
    else:
        status = "penalize"
    return {
        "status": status,
        "hazard_zone_upper": hazard_zone_upper,
        "strike_in_zone": breached,
    }


def _ranking_score(
    *,
    ev_after_cost_usdc: float,
    path_risk: dict[str, Any],
    margin_snapshot: dict[str, Any],
    kill_count: int,
    review_count: int,
    hazard_penalty: float,
) -> float:
    denominator = max(
        float(path_risk["cvar_99_usdc"]) or 0.0,
        float(margin_snapshot.get("delta_initial_margin") or 0.0),
        1.0,
    )
    raw = (
        ev_after_cost_usdc / denominator
        - float(path_risk["p_touch"]) * 2.0
        - float(path_risk["stress_loss_nav_pct"]) * 8.0
        - hazard_penalty
        - kill_count * DEFAULT_SCANNER_LIMITS["score_penalty_reject"]
        - review_count * DEFAULT_SCANNER_LIMITS["score_penalty_review"]
    )
    return round(raw, 6)


def _executable_credit_usdc(candidate: dict[str, Any]) -> float:
    underlying_price = float(candidate["underlying_price"])
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate["market_bid"]) * underlying_price
    return float(candidate["net_credit"]) * underlying_price


def _trade_fee_usdc(candidate: dict[str, Any], underlying_price: float) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return option_fee_linear(
            float(candidate["market_bid"]) * underlying_price,
            underlying_price,
            1.0,
        )

    sell_fee = option_fee_linear(
        float(candidate["sell_leg_market_bid"]) * underlying_price,
        underlying_price,
        1.0,
    )
    buy_fee = option_fee_linear(
        float(candidate["buy_leg_market_ask"]) * underlying_price,
        underlying_price,
        1.0,
    )
    return combo_fee(buy_fee, sell_fee, combo_discount_verified=False)


def _slippage_usdc(candidate: dict[str, Any], underlying_price: float) -> float:
    if candidate["structure_type"] == "naked_short_call":
        spread = max(float(candidate["market_ask"]) - float(candidate["market_bid"]), 0.0)
        return round(
            spread
            * underlying_price
            * DEFAULT_SCANNER_LIMITS["slippage_half_spread_fraction"],
            6,
        )

    sell_spread = max(
        float(candidate["sell_leg_market_ask"]) - float(candidate["sell_leg_market_bid"]),
        0.0,
    )
    buy_spread = max(
        float(candidate["buy_leg_market_ask"]) - float(candidate["buy_leg_market_bid"]),
        0.0,
    )
    return round(
        (sell_spread + buy_spread)
        * underlying_price
        * DEFAULT_SCANNER_LIMITS["slippage_half_spread_fraction"],
        6,
    )


def _surface_fitted_iv(candidate: dict[str, Any]) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate["surface_fitted_iv"])
    sell_leg_iv = float(candidate["sell_leg_surface_fitted_iv"])
    buy_leg_iv = float(candidate["buy_leg_surface_fitted_iv"])
    return round((sell_leg_iv + buy_leg_iv) / 2.0, 6)


def _bid_iv(candidate: dict[str, Any]) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate["market_bid_iv"])
    return float(candidate["sell_leg_market_bid_iv"])


def _available_depth(candidate: dict[str, Any]) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate.get("depth") or 0.0)
    return min(
        float(candidate.get("sell_leg_depth") or 0.0),
        float(candidate.get("buy_leg_depth") or 0.0),
    )


def _worst_spread_ratio(candidate: dict[str, Any]) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate.get("spread_ratio") or 0.0)
    return max(
        float(candidate.get("sell_leg_spread_ratio") or 0.0),
        float(candidate.get("buy_leg_spread_ratio") or 0.0),
    )


def _short_strike(candidate: dict[str, Any]) -> float:
    if candidate["structure_type"] == "naked_short_call":
        return float(candidate["strike_price"])
    return float(candidate["sell_leg_strike_price"])


def _settlement_window_active(generated_at: str) -> bool:
    parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    current = parsed.time()
    return time(7, 30) <= current <= time(8, 0)


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
