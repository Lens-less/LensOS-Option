"""Decision-oriented, research-only strategy synthesis.

This module turns the evidence slices in ``research_report.v1`` into a
complete research loop.  It deliberately stops short of trade
recommendations, contract sizing, and order instructions.
"""

from __future__ import annotations

import math
from typing import Any

from .pnl import trace_inverse_call_credit_spread
from .portfolio_risk import DEFAULT_RISK_BUDGET

STRATEGY_RESEARCH_SCHEMA_VERSION = "strategy_research.v1"

PIPELINE_STAGES = (
    "COLLECT",
    "ANALYZE",
    "SELECT",
    "ENTER",
    "RISK",
    "EXIT",
    "MONITOR",
    "REVIEW",
)

POSITION_STATE_POLICY = (
    {
        "state": "NORMAL",
        "delta_condition": "delta <= 0.20",
        "loss_condition": "loss < 1.0x entry credit",
        "response": "hold_or_take_profit",
    },
    {
        "state": "CAUTION",
        "delta_condition": "0.20 < delta <= 0.25",
        "loss_condition": "1.0x <= loss < 2.0x entry credit",
        "response": "no_additions_and_review",
    },
    {
        "state": "DEFENSE",
        "delta_condition": "0.25 < delta <= 0.35",
        "loss_condition": "2.0x <= loss <= 3.0x entry credit",
        "response": "reduce_or_add_defined_risk_protection",
    },
    {
        "state": "EXIT_REQUIRED",
        "delta_condition": "0.35 < delta <= 0.40",
        "loss_condition": "loss > 3.0x entry credit",
        "response": "close_unless_defined_risk_conversion_reduces_total_stress",
    },
    {
        "state": "FORCE_CLOSE",
        "delta_condition": "delta > 0.40 or breakout kill",
        "loss_condition": "portfolio_close_or_halt_signal",
        "response": "close_and_pause",
    },
)

PROFIT_CAPTURE_POLICY = (
    {
        "trigger": "premium_capture >= 60%",
        "response": "close_50_percent",
        "validated": False,
    },
    {
        "trigger": "premium_capture >= 80%",
        "response": "close_all",
        "validated": False,
    },
    {
        "trigger": "remaining_premium < 3_to_5x_expected_close_cost",
        "response": "close_early",
        "validated": False,
    },
    {
        "trigger": "short_call_delta < 0.03",
        "response": "close_and_rescan",
        "validated": False,
    },
)


def build_strategy_research(
    *,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    vol_surface_status: dict[str, Any],
    candidate_research: dict[str, Any],
    permission_state: dict[str, Any],
    calibration_status: dict[str, Any],
    backtest_status: dict[str, Any],
    ev_candidate_scanner: dict[str, Any],
    portfolio_risk: dict[str, Any],
) -> dict[str, Any]:
    """Build a full collection-to-review strategy research contract."""

    spread_candidates = [
        candidate
        for candidate in (
            (candidate_research.get("call_credit_spreads") or {}).get("eligible")
            or []
        )
        if isinstance(candidate, dict)
    ]
    market = _market_analysis(
        data_status=data_status,
        permission_state=permission_state,
        vol_surface_status=vol_surface_status,
    )
    ranked = _rank_spreads(spread_candidates, market.get("spot_usd"))
    top_candidate = ranked[0] if ranked else None
    volatility = _volatility_analysis(
        vol_surface_status=vol_surface_status,
        top_candidate=top_candidate,
        spot_usd=market.get("spot_usd"),
    )
    collection = _collection_contract(data_status)

    has_research_setup = (
        data_status.get("status") == "validated"
        and vol_surface_status.get("validated") is True
        and top_candidate is not None
    )
    regime_ready = (
        permission_state.get("status") == "validated"
        and permission_state.get("spread_permission") is True
    )
    stance = (
        "NO_RESEARCH_SETUP"
        if not has_research_setup
        else "CONDITIONAL_RESEARCH"
        if regime_ready
        else "MONITOR_ONLY"
    )
    playbook = (
        _build_spread_playbook(
            generated_at=generated_at,
            candidate=top_candidate,
            market=market,
            volatility=volatility,
            data_status=data_status,
            account_status=account_status,
            permission_state=permission_state,
            calibration_status=calibration_status,
            portfolio_risk=portfolio_risk,
        )
        if has_research_setup and top_candidate is not None
        else None
    )
    review = _review_contract(
        account_status=account_status,
        calibration_status=calibration_status,
        backtest_status=backtest_status,
        ev_candidate_scanner=ev_candidate_scanner,
    )
    monitoring = (
        _monitoring_contract(
            candidate=top_candidate,
            market=market,
            data_status=data_status,
            permission_state=permission_state,
            vol_surface_status=vol_surface_status,
            account_status=account_status,
        )
        if top_candidate is not None
        else []
    )

    status = "blocked" if not has_research_setup else "partial"
    decision = {
        "stance": stance,
        "primary_structure": (
            "CALL_CREDIT_SPREAD" if has_research_setup else None
        ),
        "entry_readiness": (
            "CONDITIONAL"
            if playbook
            and all(
                condition["status"] == "pass"
                for condition in playbook["entry_contract"]["conditions"]
                if condition["blocking"]
            )
            else "BLOCKED"
        ),
        "summary": (
            "No validated option structure is available for research."
            if not has_research_setup
            else "A defined-risk call credit spread is the primary screening setup; activation gates remain closed."
        ),
        "why_now": _why_now(
            collection=collection,
            vol_surface_status=vol_surface_status,
            spread_count=len(spread_candidates),
            top_candidate=top_candidate,
        ),
        "why_not": _why_not(
            account_status=account_status,
            permission_state=permission_state,
            calibration_status=calibration_status,
            backtest_status=backtest_status,
            ev_candidate_scanner=ev_candidate_scanner,
        ),
        "rejected_structures": [
            {
                "structure": "NAKED_SHORT_CALL",
                "status": "rejected_for_current_research_plan",
                "reason_codes": [
                    "UNBOUNDED_TAIL_LOSS",
                    "DEFINED_RISK_STRUCTURE_PREFERRED",
                    *(
                        []
                        if permission_state.get("naked_permission") is True
                        else ["NAKED_PERMISSION_FALSE"]
                    ),
                ],
            }
        ],
    }

    pipeline = _pipeline(
        collection=collection,
        vol_surface_status=vol_surface_status,
        playbook=playbook,
        review=review,
    )
    return {
        "schema_version": STRATEGY_RESEARCH_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "advisory_only": True,
        "execution_allowed": False,
        "confidence_ceiling": (
            "insufficient_data" if not has_research_setup else "screening_only"
        ),
        "pipeline": pipeline,
        "decision": decision,
        "collection": collection,
        "analysis": {
            "market": market,
            "volatility": volatility,
            "interpretation_limits": [
                "DVOL and fitted ATM IV are both implied-volatility measures; their gap is not labelled a volatility risk premium.",
                "Expected move is a one-standard-deviation approximation, not a forecast or probability guarantee.",
                "Candidate ranking uses observable screening quality because validated path-risk and EV evidence are unavailable.",
            ],
        },
        "strategy_selection": {
            "selection_method": "screening_rank_no_path_risk",
            "eligible_spread_count": len(spread_candidates),
            "ranked_candidate_ids": [
                str(candidate.get("candidate_id") or "")
                for candidate in ranked[:5]
            ],
            "ranking_dimensions": [
                "surface_fit_quality",
                "no_arbitrage_pass",
                "credit_to_width_shadow",
                "delta_distance_from_0.10",
                "leg_spread_quality",
            ],
        },
        "playbook": playbook,
        "monitoring": monitoring,
        "review": review,
        "degradation": [
            {
                "condition": "validated_path_risk_unavailable",
                "effect": "screening_rank_only_no_ev_or_p_touch_claim",
            },
            {
                "condition": "account_snapshot_missing_or_halted",
                "effect": "risk_budget_formula_only_no_contract_count",
            },
            {
                "condition": "regime_history_not_promoted",
                "effect": "monitor_only_even_when_surface_candidates_exist",
            },
            {
                "condition": "backtest_or_calibration_not_promoted",
                "effect": "exit_policy_remains_template_only",
            },
        ],
    }


def validate_strategy_research(value: Any) -> list[str]:
    """Validate the safety and completeness invariants of the strategy slice."""

    if not isinstance(value, dict):
        return ["strategy_research must be a dict"]
    errors: list[str] = []
    if value.get("schema_version") != STRATEGY_RESEARCH_SCHEMA_VERSION:
        errors.append(
            "strategy_research.schema_version must be strategy_research.v1"
        )
    if value.get("status") not in {"partial", "blocked"}:
        errors.append("strategy_research.status must be partial or blocked")
    if value.get("advisory_only") is not True:
        errors.append("strategy_research.advisory_only must be true")
    if value.get("execution_allowed") is not False:
        errors.append("strategy_research.execution_allowed must be false")
    if value.get("confidence_ceiling") not in {
        "screening_only",
        "insufficient_data",
    }:
        errors.append("strategy_research.confidence_ceiling is invalid")

    pipeline = value.get("pipeline")
    if (
        not isinstance(pipeline, list)
        or [stage.get("stage") for stage in pipeline if isinstance(stage, dict)]
        != list(PIPELINE_STAGES)
    ):
        errors.append(
            "strategy_research.pipeline must contain the complete research loop"
        )
    decision = value.get("decision")
    if not isinstance(decision, dict) or decision.get("stance") not in {
        "NO_RESEARCH_SETUP",
        "MONITOR_ONLY",
        "CONDITIONAL_RESEARCH",
    }:
        errors.append("strategy_research.decision.stance is invalid")

    playbook = value.get("playbook")
    if value.get("status") == "blocked":
        if playbook is not None:
            errors.append("blocked strategy_research.playbook must be null")
    elif not isinstance(playbook, dict):
        errors.append("partial strategy_research.playbook must be a dict")
    else:
        if playbook.get("structure") != "CALL_CREDIT_SPREAD":
            errors.append(
                "strategy_research.playbook.structure must be CALL_CREDIT_SPREAD"
            )
        conditions = (playbook.get("entry_contract") or {}).get("conditions")
        if not isinstance(conditions, list) or len(conditions) < 8:
            errors.append(
                "strategy_research.playbook must include complete entry conditions"
            )
        risk_budget = playbook.get("risk_budget") or {}
        if risk_budget.get("contracts") is not None:
            errors.append(
                "strategy_research.playbook.risk_budget.contracts must remain null"
            )
        position_states = (playbook.get("exit_contract") or {}).get(
            "position_states"
        )
        if not isinstance(position_states, list) or [
            state.get("state") for state in position_states
        ] != [state["state"] for state in POSITION_STATE_POLICY]:
            errors.append(
                "strategy_research.playbook must include the full position-state ladder"
            )

    monitoring = value.get("monitoring")
    if not isinstance(monitoring, list):
        errors.append("strategy_research.monitoring must be a list")
    review = value.get("review")
    if not isinstance(review, dict):
        errors.append("strategy_research.review must be a dict")
    return errors


def _collection_contract(data_status: dict[str, Any]) -> dict[str, Any]:
    scope = (
        data_status.get("collection_scope")
        or (data_status.get("public_response_contract") or {}).get(
            "collection_scope"
        )
        or {}
    )
    quality = (data_status.get("quality_gate") or {}).get("summary") or {}
    feed_graph = (
        data_status.get("feed_coverage")
        or data_status.get("feed_graph")
        or {}
    )
    return {
        "status": str(data_status.get("status") or "missing"),
        "source": str(data_status.get("source") or "not_configured"),
        "captured_at": data_status.get("snapshot_captured_at"),
        "market_data_age_sec": _finite(data_status.get("market_data_age_sec")),
        "coverage": {
            "scope": scope.get("scope"),
            "selected_instrument_count": int(
                _finite(scope.get("selected_instrument_count")) or 0
            ),
            "upstream_instrument_count": int(
                _finite(scope.get("upstream_instrument_count")) or 0
            ),
            "coverage_ratio": _finite(scope.get("coverage_ratio")),
            "is_research_sample": scope.get("scope") == "research_sample",
        },
        "quality": {
            "valid_quotes": int(_finite(quality.get("valid_quotes")) or 0),
            "total_quotes": int(_finite(quality.get("total_quotes")) or 0),
            "invalid_quotes": int(_finite(quality.get("invalid_quotes")) or 0),
            "fetch_errors": int(_finite(quality.get("fetch_errors")) or 0),
            "expiries_evaluated": int(
                _finite(quality.get("expiries_evaluated")) or 0
            ),
        },
        "feed_graph": {
            "complete": feed_graph.get("graph_complete") is True,
            "missing_required_feeds": list(
                feed_graph.get("missing_required_feeds") or []
            ),
        },
    }


def _market_analysis(
    *,
    data_status: dict[str, Any],
    permission_state: dict[str, Any],
    vol_surface_status: dict[str, Any],
) -> dict[str, Any]:
    measurements = permission_state.get("current_measurements") or {}
    spot = _finite(measurements.get("index_price"))
    if spot is None:
        spot = _surface_spot(vol_surface_status)
    dvol = _percent_value(measurements.get("dvol"))
    if dvol is None:
        dvol = _percent_value(
            (
                (
                    data_status.get("public_response_contract") or {}
                ).get("endpoints")
                or {}
            ).get("vol_index", {}).get("volatility")
        )
    atm_iv = _percent_value(measurements.get("atm_iv"))
    return {
        "spot_usd": _rounded(spot, 2),
        "dvol_percent": _rounded(dvol, 2),
        "near_term_atm_iv_percent": _rounded(atm_iv, 2),
        "dvol_minus_atm_iv_points": _rounded(
            dvol - atm_iv if dvol is not None and atm_iv is not None else None,
            2,
        ),
        "funding_rate": _rounded(_finite(measurements.get("funding_rate")), 10),
        "basis_rate": _rounded(_finite(measurements.get("basis_rate")), 8),
        "event_score": _rounded(_finite(measurements.get("event_score")), 4),
        "regime_label": str(
            permission_state.get("primary_regime_label") or "Unavailable"
        ),
        "regime_status": str(permission_state.get("status") or "blocked"),
        "sell_permission": _rounded(
            _finite(permission_state.get("sell_permission")), 2
        ),
        "spread_permission": permission_state.get("spread_permission") is True,
        "naked_permission": permission_state.get("naked_permission") is True,
    }


def _volatility_analysis(
    *,
    vol_surface_status: dict[str, Any],
    top_candidate: dict[str, Any] | None,
    spot_usd: float | None,
) -> dict[str, Any]:
    expiries = [
        expiry
        for expiry in (vol_surface_status.get("expiries") or [])
        if isinstance(expiry, dict) and (expiry.get("surface_points") or [])
    ]
    expiries.sort(key=lambda expiry: _finite(expiry.get("dte_days")) or math.inf)
    snapshots = [_expiry_snapshot(expiry) for expiry in expiries]
    snapshots = [snapshot for snapshot in snapshots if snapshot is not None]
    front = snapshots[0] if snapshots else None
    next_expiry = snapshots[1] if len(snapshots) > 1 else None
    term_slope = None
    if front and next_expiry:
        front_iv = _finite(front.get("atm_fitted_iv_percent"))
        next_iv = _finite(next_expiry.get("atm_fitted_iv_percent"))
        if front_iv is not None and next_iv is not None:
            term_slope = next_iv - front_iv

    candidate_expiry = None
    if top_candidate is not None:
        candidate_expiry = next(
            (
                expiry
                for expiry in expiries
                if expiry.get("expiry_date") == top_candidate.get("expiry_date")
            ),
            None,
        )
    candidate_snapshot = (
        _expiry_snapshot(candidate_expiry) if candidate_expiry else front
    )
    dte = (
        _finite(top_candidate.get("dte_days"))
        if top_candidate is not None
        else None
    )
    atm_iv = (
        _finite(candidate_snapshot.get("atm_fitted_iv_percent"))
        if candidate_snapshot
        else None
    )
    expected_move = None
    if (
        spot_usd is not None
        and atm_iv is not None
        and dte is not None
        and dte > 0
    ):
        expected_move = spot_usd * (atm_iv / 100.0) * math.sqrt(dte / 365.0)

    wing_richness = None
    if top_candidate is not None and atm_iv is not None:
        sell_iv = _finite(top_candidate.get("sell_leg_surface_fitted_iv"))
        if sell_iv is not None:
            wing_richness = sell_iv - atm_iv
    return {
        "surface_status": str(vol_surface_status.get("status") or "missing"),
        "fit_model": vol_surface_status.get("fit_model"),
        "front_expiry": front,
        "next_expiry": next_expiry,
        "term_slope_iv_points": _rounded(term_slope, 2),
        "candidate_expiry_atm_iv_percent": _rounded(atm_iv, 2),
        "expected_move_usd": _rounded(expected_move, 2),
        "expected_move_percent": _rounded(
            expected_move / spot_usd * 100.0
            if expected_move is not None and spot_usd
            else None,
            2,
        ),
        "call_wing_richness_iv_points": _rounded(wing_richness, 2),
    }


def _expiry_snapshot(expiry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not expiry:
        return None
    points = [
        point
        for point in (expiry.get("surface_points") or [])
        if isinstance(point, dict)
    ]
    if not points:
        return None
    spot = _finite(points[0].get("underlying_price"))
    atm_point = min(
        points,
        key=lambda point: abs(
            (_finite(point.get("strike_price")) or math.inf)
            - (spot if spot is not None else 0.0)
        ),
    )
    return {
        "expiry_date": expiry.get("expiry_date"),
        "dte_days": _rounded(_finite(expiry.get("dte_days")), 2),
        "atm_strike_usd": _rounded(
            _finite(atm_point.get("strike_price")), 2
        ),
        "atm_fitted_iv_percent": _rounded(
            _finite(atm_point.get("surface_fitted_iv")), 2
        ),
        "fit_quality_score": _rounded(
            _finite(expiry.get("fit_quality_score")), 4
        ),
        "no_arbitrage_pass": expiry.get("no_arb_pass") is True,
        "candidate_eligible": expiry.get("candidate_eligible") is True,
    }


def _rank_spreads(
    candidates: list[dict[str, Any]],
    spot_usd: float | None,
) -> list[dict[str, Any]]:
    spot = spot_usd or 0.0

    def ranking(candidate: dict[str, Any]) -> tuple[Any, ...]:
        credit = _finite(candidate.get("net_credit")) or 0.0
        width = _finite(candidate.get("spread_width")) or math.inf
        efficiency = credit * spot / width if width > 0 else 0.0
        delta = _finite(candidate.get("model_delta"))
        leg_spread = max(
            _finite(candidate.get("sell_leg_spread_ratio")) or 1.0,
            _finite(candidate.get("buy_leg_spread_ratio")) or 1.0,
        )
        quality = _finite(
            (candidate.get("surface_quality") or {}).get("fit_quality_score")
        ) or 0.0
        return (
            -efficiency,
            abs((delta if delta is not None else 1.0) - 0.10),
            leg_spread,
            -quality,
            width,
            str(candidate.get("candidate_id") or ""),
        )

    return sorted(candidates, key=ranking)


def _build_spread_playbook(
    *,
    generated_at: str,
    candidate: dict[str, Any],
    market: dict[str, Any],
    volatility: dict[str, Any],
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    permission_state: dict[str, Any],
    calibration_status: dict[str, Any],
    portfolio_risk: dict[str, Any],
) -> dict[str, Any]:
    spot = _finite(candidate.get("underlying_price")) or _finite(
        market.get("spot_usd")
    )
    sell_strike = _finite(candidate.get("sell_leg_strike_price"))
    buy_strike = _finite(candidate.get("buy_leg_strike_price"))
    expected_move = _finite(volatility.get("expected_move_usd"))
    economics = _spread_economics(
        candidate=candidate,
        spot_usd=spot,
        expected_move_usd=expected_move,
    )
    account_available = account_status.get("status") == "available"
    account_gate = str(account_status.get("trade_gate") or "NO_TRADE")
    max_age = _finite(
        (data_status.get("quality_gate") or {})
        .get("thresholds", {})
        .get("market_data_max_age_sec")
    ) or 60.0
    market_age = _finite(data_status.get("market_data_age_sec"))
    event_score = _finite(market.get("event_score"))
    delta = _finite(candidate.get("model_delta"))
    delta_min = 0.03
    delta_max = 0.15
    settlement_window = _is_settlement_window(generated_at)
    conditions = [
        _condition(
            "market_quality",
            "Market snapshot passes the quality gate",
            data_status.get("status"),
            "validated",
            data_status.get("status") == "validated",
        ),
        _condition(
            "market_freshness",
            "Market snapshot remains inside its freshness limit",
            market_age,
            f"<= {max_age:.0f} sec",
            market_age is not None and market_age <= max_age,
        ),
        _condition(
            "candidate_eligibility",
            "Candidate remains eligible after refresh",
            candidate.get("decision"),
            "eligible",
            candidate.get("decision") == "eligible",
        ),
        _condition(
            "surface_fit",
            "Surface fit quality remains at or above 0.90",
            (candidate.get("surface_quality") or {}).get("fit_quality_score"),
            ">= 0.90",
            (
                _finite(
                    (candidate.get("surface_quality") or {}).get(
                        "fit_quality_score"
                    )
                )
                or 0.0
            )
            >= 0.90,
        ),
        _condition(
            "no_arbitrage",
            "No-arbitrage check remains clear",
            (candidate.get("surface_quality") or {}).get("no_arb_pass"),
            "true",
            (candidate.get("surface_quality") or {}).get("no_arb_pass") is True,
        ),
        _condition(
            "delta_band",
            "Spread model delta remains inside the research band",
            delta,
            "0.03 to 0.15",
            delta is not None and delta_min <= delta <= delta_max,
        ),
        _condition(
            "leg_liquidity",
            "Both leg spread ratios remain at or below 0.25",
            {
                "sell": _finite(candidate.get("sell_leg_spread_ratio")),
                "buy": _finite(candidate.get("buy_leg_spread_ratio")),
            },
            "<= 0.25 each",
            all(
                ratio is not None and ratio <= 0.25
                for ratio in (
                    _finite(candidate.get("sell_leg_spread_ratio")),
                    _finite(candidate.get("buy_leg_spread_ratio")),
                )
            ),
        ),
        _condition(
            "regime_permission",
            "Promoted regime evidence permits credit spreads",
            {
                "status": permission_state.get("status"),
                "spread_permission": permission_state.get("spread_permission"),
            },
            "validated and true",
            permission_state.get("status") == "validated"
            and permission_state.get("spread_permission") is True,
        ),
        _condition(
            "event_gate",
            "Event-risk score stays below the kill threshold",
            event_score,
            "<= 0.75",
            event_score is not None and event_score <= 0.75,
        ),
        _condition(
            "settlement_window",
            "Entry is outside the 07:30-08:00 UTC settlement window",
            "inside" if settlement_window else "outside",
            "outside",
            not settlement_window,
        ),
        _condition(
            "account_gate",
            "Read-only account snapshot allows new risk",
            account_gate,
            "ALLOW_NEW",
            account_available and account_gate == "ALLOW_NEW",
        ),
        {
            "id": "cost_coverage",
            "label": "Net premium remains above five times fees and slippage",
            "observed": None,
            "requirement": "net premium > 5x total expected costs",
            "status": "unknown",
            "blocking": True,
            "reason": "live slippage estimate unavailable",
        },
        _condition(
            "calibrated_path_risk",
            "Validated path-risk and calibration evidence is promoted",
            calibration_status.get("status"),
            "calibrated",
            calibration_status.get("status") == "calibrated",
        ),
    ]
    return {
        "playbook_id": str(candidate.get("candidate_id") or ""),
        "structure": "CALL_CREDIT_SPREAD",
        "candidate": {
            "candidate_id": candidate.get("candidate_id"),
            "expiry_date": candidate.get("expiry_date"),
            "dte_days": _rounded(_finite(candidate.get("dte_days")), 2),
            "sell_leg": candidate.get("sell_leg_instrument_name"),
            "buy_leg": candidate.get("buy_leg_instrument_name"),
            "sell_strike_usd": _rounded(sell_strike, 2),
            "buy_strike_usd": _rounded(buy_strike, 2),
            "model_delta": _rounded(delta, 4),
            "risk_neutral_p_itm": _rounded(
                _finite(candidate.get("risk_neutral_p_itm")), 4
            ),
            "surface_fit_quality": _rounded(
                _finite(
                    (candidate.get("surface_quality") or {}).get(
                        "fit_quality_score"
                    )
                ),
                4,
            ),
        },
        "economics": economics,
        "entry_contract": {
            "status": (
                "ready"
                if all(
                    condition["status"] == "pass"
                    for condition in conditions
                    if condition["blocking"]
                )
                else "blocked"
            ),
            "revalidate_on_refresh": True,
            "price_basis": "sell_bid_minus_buy_ask",
            "execution_assumption": "post_only_limit_research_assumption",
            "conditions": conditions,
        },
        "risk_budget": {
            **DEFAULT_RISK_BUDGET,
            "sizing_status": (
                "research_shadow_only"
                if account_available
                else "account_input_missing"
            ),
            "contracts": None,
            "formula": (
                "floor((NAV * max_single_spread_loss_nav) / "
                "reference_max_loss_usd_shadow), then apply margin, depth, "
                "delta and inverse-position caps"
            ),
            "portfolio_final_action": portfolio_risk.get("final_action"),
            "note": "No contract count is emitted in research-only mode.",
        },
        "exit_contract": {
            "policy_status": "template_only_uncalibrated",
            "profit_capture": [dict(rule) for rule in PROFIT_CAPTURE_POLICY],
            "position_states": [dict(state) for state in POSITION_STATE_POLICY],
            "time_management": {
                "review_below_dte_days": 7,
                "roll_allowed_states": ["NORMAL", "CAUTION"],
                "roll_delta_band": [0.05, 0.20],
                "roll_must_improve": [
                    "expected_value",
                    "p_touch",
                    "total_stress_loss",
                ],
                "defensive_roll_minimum_stress_reduction": 0.30,
                "loss_deferral_alone_is_forbidden": True,
            },
            "kill_switches": [
                "expected_value <= 0 when validated EV becomes available",
                "bid IV <= calibrated physical fair IV",
                "leg spread ratio > 0.25",
                "displayed depth < 3x intended size",
                "breakout score > 0.70",
                "event score > 0.75",
                "market data age > 60 sec",
                "account data age > 30 sec",
                "portfolio risk is RED or HALT",
                "07:30-08:00 UTC settlement window for short-dated entry",
            ],
        },
    }


def _spread_economics(
    *,
    candidate: dict[str, Any],
    spot_usd: float | None,
    expected_move_usd: float | None,
) -> dict[str, Any]:
    sell_strike = _finite(candidate.get("sell_leg_strike_price"))
    buy_strike = _finite(candidate.get("buy_leg_strike_price"))
    sell_bid = _finite(candidate.get("sell_leg_market_bid"))
    buy_ask = _finite(candidate.get("buy_leg_market_ask"))
    credit_coin = _finite(candidate.get("net_credit"))
    reference_max_loss = None
    estimated_total_fees_usd = None
    if all(
        value is not None and value > 0
        for value in (
            spot_usd,
            sell_strike,
            buy_strike,
            sell_bid,
            buy_ask,
        )
    ):
        trace = trace_inverse_call_credit_spread(
            contract_count=1.0,
            short_strike_price=float(sell_strike),
            long_strike_price=float(buy_strike),
            entry_reference_price=float(spot_usd),
            delivery_price=float(buy_strike),
            sell_leg_bid_coin=float(sell_bid),
            buy_leg_ask_coin=float(buy_ask),
        )
        reference_max_loss = _finite(
            trace.get("reference_max_loss_usd_shadow")
        )
        total_fee_coin = _finite(trace.get("total_fees_coin"))
        if total_fee_coin is not None and spot_usd is not None:
            estimated_total_fees_usd = total_fee_coin * spot_usd
    credit_usd = (
        credit_coin * spot_usd
        if credit_coin is not None and spot_usd is not None
        else None
    )
    breakeven = (
        sell_strike + credit_usd
        if sell_strike is not None and credit_usd is not None
        else None
    )
    strike_distance = (
        sell_strike - spot_usd
        if sell_strike is not None and spot_usd is not None
        else None
    )
    return {
        "premium_currency": candidate.get("premium_currency"),
        "credit_coin": _rounded(credit_coin, 6),
        "credit_usd_shadow": _rounded(credit_usd, 2),
        "spread_width_usd": _rounded(
            _finite(candidate.get("spread_width")), 2
        ),
        "reference_max_loss_usd_shadow": _rounded(reference_max_loss, 2),
        "estimated_total_fees_usd_shadow": _rounded(
            estimated_total_fees_usd, 2
        ),
        "breakeven_usd_shadow": _rounded(breakeven, 2),
        "sell_strike_distance_usd": _rounded(strike_distance, 2),
        "sell_strike_distance_percent": _rounded(
            strike_distance / spot_usd * 100.0
            if strike_distance is not None and spot_usd
            else None,
            2,
        ),
        "sell_strike_expected_move_multiple": _rounded(
            strike_distance / expected_move_usd
            if strike_distance is not None
            and expected_move_usd is not None
            and expected_move_usd > 0
            else None,
            2,
        ),
        "credit_to_max_loss_ratio": _rounded(
            credit_usd / reference_max_loss
            if credit_usd is not None
            and reference_max_loss is not None
            and reference_max_loss > 0
            else None,
            4,
        ),
        "assumption": (
            "One-contract inverse-option USD shadow at entry reference price; "
            "fees use audited conservative defaults and slippage is not included."
        ),
    }


def _condition(
    condition_id: str,
    label: str,
    observed: Any,
    requirement: str,
    passed: bool,
) -> dict[str, Any]:
    return {
        "id": condition_id,
        "label": label,
        "observed": observed,
        "requirement": requirement,
        "status": "pass" if passed else "block",
        "blocking": True,
    }


def _monitoring_contract(
    *,
    candidate: dict[str, Any],
    market: dict[str, Any],
    data_status: dict[str, Any],
    permission_state: dict[str, Any],
    vol_surface_status: dict[str, Any],
    account_status: dict[str, Any],
) -> list[dict[str, Any]]:
    quality_threshold = (
        (vol_surface_status.get("thresholds") or {}).get(
            "fit_quality_threshold"
        )
        or 0.90
    )
    account_age_ms = _finite(account_status.get("data_age_ms"))
    return [
        _watch(
            "market_age_sec",
            data_status.get("market_data_age_sec"),
            "> 60 sec",
            "pause_research_setup",
        ),
        _watch(
            "surface_fit_quality",
            (candidate.get("surface_quality") or {}).get("fit_quality_score"),
            f"< {quality_threshold}",
            "remove_candidate",
        ),
        _watch(
            "no_arbitrage_pass",
            (candidate.get("surface_quality") or {}).get("no_arb_pass"),
            "false",
            "remove_candidate",
        ),
        _watch(
            "spread_permission",
            permission_state.get("spread_permission"),
            "false_or_unpromoted",
            "keep_monitor_only",
        ),
        _watch(
            "event_score",
            market.get("event_score"),
            "> 0.75",
            "kill_new_entry",
        ),
        _watch(
            "candidate_delta",
            candidate.get("model_delta"),
            "> 0.20 after entry",
            "move_to_caution",
        ),
        _watch(
            "sell_leg_spread_ratio",
            candidate.get("sell_leg_spread_ratio"),
            "> 0.25",
            "remove_candidate",
        ),
        _watch(
            "buy_leg_spread_ratio",
            candidate.get("buy_leg_spread_ratio"),
            "> 0.25",
            "remove_candidate",
        ),
        _watch(
            "dte_days",
            candidate.get("dte_days"),
            "<= 7",
            "time_management_review",
        ),
        _watch(
            "account_age_sec",
            account_age_ms / 1000.0 if account_age_ms is not None else None,
            "> 30 sec or missing",
            "no_contract_sizing",
        ),
        _watch(
            "position_loss_multiple",
            None,
            ">= 2.0x",
            "move_to_defense",
        ),
    ]


def _watch(
    metric: str,
    current: Any,
    trigger: str,
    response: str,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "current": current,
        "trigger": trigger,
        "response": response,
        "cadence": "each_refresh",
    }


def _review_contract(
    *,
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    backtest_status: dict[str, Any],
    ev_candidate_scanner: dict[str, Any],
) -> dict[str, Any]:
    missing_evidence = _unique(
        [
            value
            for value in (
                account_status.get("reason_code"),
                calibration_status.get("reason_code"),
                backtest_status.get("reason_code"),
                ev_candidate_scanner.get("reason_code"),
            )
            if isinstance(value, str) and value
        ]
    )
    return {
        "status": "blocked" if missing_evidence else "ready",
        "backtest_status": backtest_status.get("status"),
        "calibration_status": calibration_status.get("status"),
        "path_risk_status": ev_candidate_scanner.get("status"),
        "missing_evidence": missing_evidence,
        "promotion_conditions": [
            "Persist enough rolling observations to promote regime evidence.",
            "Run an aligned bounded backtest on licensed historical data.",
            "Promote walk-forward calibration and validated path-risk outputs.",
            "Reconcile paper observations, fees, slippage, and forced-exit behavior.",
            "Attach a fresh read-only account snapshot before any sizing study.",
        ],
        "journal_template": [
            "market_thesis_and_invalidation",
            "selected_structure_and_rejected_alternatives",
            "entry_gate_snapshot",
            "risk_budget_assumptions",
            "exit_state_transitions",
            "post_observation_review",
        ],
    }


def _pipeline(
    *,
    collection: dict[str, Any],
    vol_surface_status: dict[str, Any],
    playbook: dict[str, Any] | None,
    review: dict[str, Any],
) -> list[dict[str, Any]]:
    collect_ready = collection.get("status") == "validated"
    analyze_ready = vol_surface_status.get("validated") is True
    select_ready = playbook is not None
    entry_ready = (
        playbook is not None
        and (playbook.get("entry_contract") or {}).get("status") == "ready"
    )
    risk_ready = (
        playbook is not None
        and (playbook.get("risk_budget") or {}).get("sizing_status")
        == "research_shadow_only"
    )
    statuses = {
        "COLLECT": "ready" if collect_ready else "blocked",
        "ANALYZE": "ready" if analyze_ready else "blocked",
        "SELECT": "ready" if select_ready else "blocked",
        "ENTER": "ready" if entry_ready else "blocked",
        "RISK": "ready" if risk_ready else "partial" if playbook else "blocked",
        "EXIT": "partial" if playbook else "blocked",
        "MONITOR": "ready" if playbook else "blocked",
        "REVIEW": "ready" if review.get("status") == "ready" else "blocked",
    }
    outputs = {
        "COLLECT": "source_freshness_coverage_quality",
        "ANALYZE": "market_regime_term_structure_skew_expected_move",
        "SELECT": "defined_risk_structure_and_ranked_candidate",
        "ENTER": "conditional_gate_checklist",
        "RISK": "nav_relative_budget_and_one_contract_shadow",
        "EXIT": "profit_time_and_position_state_policy",
        "MONITOR": "refresh_triggers_and_responses",
        "REVIEW": "journal_backtest_calibration_and_promotion",
    }
    return [
        {
            "stage": stage,
            "status": statuses[stage],
            "output": outputs[stage],
        }
        for stage in PIPELINE_STAGES
    ]


def _why_now(
    *,
    collection: dict[str, Any],
    vol_surface_status: dict[str, Any],
    spread_count: int,
    top_candidate: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    quality = collection.get("quality") or {}
    if collection.get("status") == "validated":
        reasons.append(
            f"{quality.get('valid_quotes', 0)}/{quality.get('total_quotes', 0)} sampled quotes pass the market-data gate."
        )
    if vol_surface_status.get("validated") is True:
        reasons.append(
            f"{(vol_surface_status.get('summary') or {}).get('eligible_expiries', 0)} expiry surfaces are candidate-eligible."
        )
    if spread_count:
        reasons.append(
            f"{spread_count} defined-risk call credit spreads pass observable screening."
        )
    if top_candidate:
        reasons.append(
            f"{top_candidate.get('candidate_id')} leads the observable screening rank."
        )
    return reasons


def _why_not(
    *,
    account_status: dict[str, Any],
    permission_state: dict[str, Any],
    calibration_status: dict[str, Any],
    backtest_status: dict[str, Any],
    ev_candidate_scanner: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if permission_state.get("status") != "validated":
        reasons.append("Regime evidence has not been promoted.")
    if account_status.get("status") != "available":
        reasons.append("A fresh read-only account snapshot is unavailable.")
    # The scanner's vocabulary is blocked/validated/unavailable. Comparing
    # against "available" (the account_status vocabulary above) never matched,
    # so this reason was reported unconditionally.
    if ev_candidate_scanner.get("status") != "validated":
        reasons.append("Validated path-risk and EV ranking are unavailable.")
    if calibration_status.get("status") != "calibrated":
        reasons.append("Walk-forward calibration is not promoted.")
    if backtest_status.get("status") != "completed":
        reasons.append("The bounded historical backtest has not run.")
    return reasons


def _surface_spot(vol_surface_status: dict[str, Any]) -> float | None:
    for expiry in vol_surface_status.get("expiries") or []:
        for point in (expiry or {}).get("surface_points") or []:
            spot = _finite((point or {}).get("underlying_price"))
            if spot is not None:
                return spot
    return None


def _is_settlement_window(generated_at: str) -> bool:
    try:
        time_part = generated_at.split("T", 1)[1].replace("Z", "").split("+", 1)[0]
        hour, minute = (int(part) for part in time_part.split(":")[:2])
    except (IndexError, TypeError, ValueError):
        return False
    minutes = hour * 60 + minute
    return 7 * 60 + 30 <= minutes <= 8 * 60


def _percent_value(value: Any) -> float | None:
    number = _finite(value)
    if number is None:
        return None
    return number * 100.0 if abs(number) <= 3.0 else number


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rounded(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
