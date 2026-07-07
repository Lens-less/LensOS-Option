"""Position-management state machine and hedge replay helpers for ISSUE-012."""

from __future__ import annotations

from typing import Any

POSITION_MANAGEMENT_SCHEMA_VERSION = "position_management_report.v1"

POSITION_STATES = [
    "NORMAL",
    "CAUTION",
    "DEFENSE",
    "EXIT_REQUIRED",
    "FORCE_CLOSE",
    "PAUSED",
]


def build_position_management_report(
    *,
    generated_at: str,
    account_status: dict[str, Any],
    portfolio_risk: dict[str, Any],
    permission_state: dict[str, Any],
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    replay_positions = positions if positions is not None else _default_positions(account_status)
    replays = [
        evaluate_position_replay(
            position=position,
            portfolio_risk=portfolio_risk,
            permission_state=permission_state,
        )
        for position in replay_positions
    ]
    return {
        "schema_version": POSITION_MANAGEMENT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "state_definitions": list(POSITION_STATES),
        "replays": replays,
        "summary": {
            "positions_evaluated": len(replays),
            "highest_state": _highest_state(replays),
            "forced_exit_count": sum(bool(item["forced_exit_events"]) for item in replays),
            "hedge_reevaluation_count": sum(
                any(event["reevaluation_required"] for event in item["hedge_events"])
                for item in replays
            ),
            "research_only": True,
        },
    }


def evaluate_position_replay(
    *,
    position: dict[str, Any],
    portfolio_risk: dict[str, Any],
    permission_state: dict[str, Any],
) -> dict[str, Any]:
    state = classify_position_state(
        current_delta=abs(float(position.get("current_delta") or position.get("delta") or 0.0)),
        loss_multiple=float(position.get("loss_multiple") or 0.0),
        breakout_kill=bool(position.get("breakout_kill", False))
        or "BREAKOUT_KILL" in permission_state.get("reason_codes", []),
        portfolio_final_action=str(portfolio_risk.get("final_action") or "allow_new"),
    )
    protective_exception = _protective_spread_exception(position)
    active_roll = _active_roll_allowed(position, state)
    defensive_action = _defensive_action_allowed(position, state)
    hedge_event = _hedge_event(position)
    allowed_actions = _allowed_actions(
        state=state,
        active_roll=active_roll,
        defensive_action=defensive_action,
        protective_exception=protective_exception,
        hedge_event=hedge_event,
    )
    forbidden_actions = _forbidden_actions(
        state=state,
        active_roll=active_roll,
        defensive_action=defensive_action,
    )
    forced_exit_events = []
    if state in {"EXIT_REQUIRED", "FORCE_CLOSE", "PAUSED"}:
        forced_exit_events.append(
            {
                "event_type": "force_close" if state == "FORCE_CLOSE" else "exit_required",
                "reason_codes": _state_reason_codes(state),
            }
        )

    return {
        "position_id": str(position.get("position_id") or position.get("instrument_name") or "position-1"),
        "instrument_name": position.get("instrument_name"),
        "state": state,
        "state_reason_codes": _state_reason_codes(state),
        "current_delta": abs(float(position.get("current_delta") or position.get("delta") or 0.0)),
        "loss_multiple": float(position.get("loss_multiple") or 0.0),
        "allowed_actions": allowed_actions,
        "forbidden_actions": forbidden_actions,
        "hedge_events": [hedge_event],
        "roll_events": [
            {
                "roll_type": "active",
                "allowed": active_roll,
                "reason": "Active roll is allowed only in NORMAL/CAUTION and must improve EV, P_Touch, and stress loss.",
            },
            {
                "roll_type": "defensive",
                "allowed": defensive_action,
                "reason": "Defensive action must reduce total stress loss and must not increase net short gamma.",
            },
        ],
        "protective_spread_exception": protective_exception,
        "forced_exit_events": forced_exit_events,
        "research_only": True,
    }


def classify_position_state(
    *,
    current_delta: float,
    loss_multiple: float,
    breakout_kill: bool = False,
    portfolio_final_action: str = "allow_new",
) -> str:
    if portfolio_final_action in {"halt_system", "close_all_and_pause"}:
        return "PAUSED"
    if breakout_kill or current_delta > 0.40:
        return "FORCE_CLOSE"
    if current_delta > 0.35 or loss_multiple > 3.0:
        return "EXIT_REQUIRED"
    if current_delta > 0.25 or loss_multiple >= 2.0:
        return "DEFENSE"
    if current_delta > 0.20 or loss_multiple >= 1.0:
        return "CAUTION"
    return "NORMAL"


def validate_position_management_report(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["position_management must be a dict"]
    if report.get("schema_version") != POSITION_MANAGEMENT_SCHEMA_VERSION:
        errors.append("position_management.schema_version must be position_management_report.v1")
    if set(report.get("state_definitions") or []) != set(POSITION_STATES):
        errors.append("position_management.state_definitions must include all states")
    replays = report.get("replays")
    if not isinstance(replays, list):
        errors.append("position_management.replays must be a list")
    else:
        for replay in replays:
            if not isinstance(replay, dict):
                errors.append("position_management replay entries must be dicts")
                continue
            for key in (
                "state",
                "allowed_actions",
                "forbidden_actions",
                "hedge_events",
                "roll_events",
                "forced_exit_events",
            ):
                if key not in replay:
                    errors.append(f"position_management replay missing key: {key}")
            if replay.get("state") not in POSITION_STATES:
                errors.append("position_management replay has unknown state")
    return errors


def _default_positions(account_status: dict[str, Any]) -> list[dict[str, Any]]:
    account_positions = account_status.get("positions") or []
    if account_positions:
        normalized = []
        for index, position in enumerate(account_positions, start=1):
            greeks = position.get("greeks") or {}
            normalized.append(
                {
                    "position_id": f"account-position-{index}",
                    "instrument_name": position.get("instrument_name"),
                    "current_delta": abs(float(greeks.get("delta") or 0.0)),
                    "loss_multiple": _loss_multiple(position),
                    "collected_premium_usdc": max(abs(float(position.get("pnl") or 0.0)), 100.0),
                    "hedge": {
                        "realized_funding_usdc": 8.0,
                        "trading_fee_usdc": 3.5,
                        "slippage_usdc": 4.0,
                    },
                    "roll_candidate": {
                        "ev_before": 10.0,
                        "ev_after": 12.0,
                        "p_touch_before": 0.30,
                        "p_touch_after": 0.27,
                        "stress_loss_before": 400.0,
                        "stress_loss_after": 350.0,
                    },
                    "protective_spread": {
                        "stress_loss_before": 400.0,
                        "stress_loss_after": 250.0,
                        "net_short_gamma_before": 0.003,
                        "net_short_gamma_after": 0.001,
                    },
                }
            )
        return normalized
    return [
        {
            "position_id": "empty-book-placeholder",
            "instrument_name": None,
            "current_delta": 0.0,
            "loss_multiple": 0.0,
            "collected_premium_usdc": 100.0,
            "hedge": {"realized_funding_usdc": 0.0, "trading_fee_usdc": 0.0, "slippage_usdc": 0.0},
            "roll_candidate": {},
            "protective_spread": {},
        }
    ]


def _loss_multiple(position: dict[str, Any]) -> float:
    pnl = float(position.get("pnl") or 0.0)
    mark = abs(float(position.get("mark_price") or 0.0))
    if pnl >= 0:
        return 0.0
    return round(abs(pnl) / max(mark * 1000.0, 100.0), 6)


def _active_roll_allowed(position: dict[str, Any], state: str) -> bool:
    candidate = position.get("roll_candidate") or {}
    if state not in {"NORMAL", "CAUTION"}:
        return False
    return (
        float(candidate.get("ev_after") or 0.0) > float(candidate.get("ev_before") or 0.0)
        and float(candidate.get("p_touch_after") or 1.0) < float(candidate.get("p_touch_before") or 1.0)
        and float(candidate.get("stress_loss_after") or 1e18) < float(candidate.get("stress_loss_before") or 0.0)
    )


def _defensive_action_allowed(position: dict[str, Any], state: str) -> bool:
    if state not in {"DEFENSE", "EXIT_REQUIRED"}:
        return False
    return _protective_spread_exception(position)["allowed"]


def _protective_spread_exception(position: dict[str, Any]) -> dict[str, Any]:
    spread = position.get("protective_spread") or {}
    before = float(spread.get("stress_loss_before") or 0.0)
    after = float(spread.get("stress_loss_after") or before)
    gamma_before = float(spread.get("net_short_gamma_before") or 0.0)
    gamma_after = float(spread.get("net_short_gamma_after") or gamma_before)
    allowed = before > 0.0 and after < before and gamma_after <= gamma_before
    return {
        "allowed": allowed,
        "stress_loss_before": before,
        "stress_loss_after": after,
        "net_short_gamma_before": gamma_before,
        "net_short_gamma_after": gamma_after,
        "reason_code": "PROTECTIVE_SPREAD_REDUCES_STRESS" if allowed else "PROTECTIVE_SPREAD_NOT_IMPROVING",
    }


def _hedge_event(position: dict[str, Any]) -> dict[str, Any]:
    hedge = position.get("hedge") or {}
    funding = float(hedge.get("realized_funding_usdc") or 0.0)
    fee = float(hedge.get("trading_fee_usdc") or 0.0)
    slippage = float(hedge.get("slippage_usdc") or 0.0)
    collected = max(float(position.get("collected_premium_usdc") or 0.0), 1.0)
    total = funding + fee + slippage
    return {
        "funding_usdc": round(funding, 6),
        "fees_usdc": round(fee, 6),
        "slippage_usdc": round(slippage, 6),
        "total_hedge_cost_usdc": round(total, 6),
        "cost_to_premium_ratio": round(total / collected, 6),
        "reevaluation_required": total / collected > 0.20,
    }


def _allowed_actions(
    *,
    state: str,
    active_roll: bool,
    defensive_action: bool,
    protective_exception: dict[str, Any],
    hedge_event: dict[str, Any],
) -> list[str]:
    allowed_by_state = {
        "NORMAL": ["hold", "take_profit"],
        "CAUTION": ["hold", "prepare_defense"],
        "DEFENSE": ["reduce", "buy_protection", "hedge"],
        "EXIT_REQUIRED": ["exit_required"],
        "FORCE_CLOSE": ["force_close"],
        "PAUSED": ["pause"],
    }
    actions = list(allowed_by_state[state])
    if active_roll:
        actions.append("active_roll")
    if defensive_action or protective_exception["allowed"]:
        actions.append("convert_to_defined_risk_spread")
    if hedge_event["reevaluation_required"] and "reevaluate_position" not in actions:
        actions.append("reevaluate_position")
    return actions


def _forbidden_actions(*, state: str, active_roll: bool, defensive_action: bool) -> list[str]:
    forbidden = []
    if state not in {"NORMAL", "CAUTION"} or not active_roll:
        forbidden.append("active_roll")
    if state in {"EXIT_REQUIRED", "FORCE_CLOSE", "PAUSED"}:
        forbidden.extend(["risk_expanding_roll", "increase_size"])
    if state in {"DEFENSE", "EXIT_REQUIRED"} and not defensive_action:
        forbidden.append("defensive_roll_without_stress_reduction")
    return sorted(set(forbidden))


def _state_reason_codes(state: str) -> list[str]:
    return {
        "NORMAL": ["POSITION_NORMAL"],
        "CAUTION": ["POSITION_CAUTION"],
        "DEFENSE": ["POSITION_DEFENSE"],
        "EXIT_REQUIRED": ["POSITION_EXIT_REQUIRED"],
        "FORCE_CLOSE": ["POSITION_FORCE_CLOSE"],
        "PAUSED": ["POSITION_PAUSED"],
    }[state]


def _highest_state(replays: list[dict[str, Any]]) -> str | None:
    if not replays:
        return None
    rank = {state: index for index, state in enumerate(POSITION_STATES)}
    return max(replays, key=lambda replay: rank[replay["state"]])["state"]
