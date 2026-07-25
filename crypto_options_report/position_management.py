"""Position-management state machine and hedge replay helpers for ISSUE-012."""

from __future__ import annotations

import math
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

_PORTFOLIO_ACTION_MINIMUM_STATE: dict[str, str | None] = {
    "allow_new": None,
    "reduce_size": None,
    "spread_only": None,
    "no_new_trades": None,
    "reduce_existing": "DEFENSE",
    "close_batch": "FORCE_CLOSE",
    "close_all_and_pause": "PAUSED",
    "halt_system": "PAUSED",
}

_REQUIRED_POSITION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "hedge": (
        "realized_funding_usdc",
        "trading_fee_usdc",
        "slippage_usdc",
    ),
    "roll_candidate": (
        "ev_before",
        "ev_after",
        "p_touch_before",
        "p_touch_after",
        "stress_loss_before",
        "stress_loss_after",
    ),
    "protective_spread": (
        "stress_loss_before",
        "stress_loss_after",
        "net_short_gamma_before",
        "net_short_gamma_after",
    ),
}


def build_position_management_report(
    *,
    generated_at: str,
    account_status: dict[str, Any],
    portfolio_risk: dict[str, Any],
    permission_state: dict[str, Any],
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    account_positions = account_status.get("positions")
    account_position_count = (
        len(account_positions) if isinstance(account_positions, list) else 0
    )
    missing_evidence: list[str] = []
    if positions is None:
        # Account snapshots do not carry premium cost basis, hedge ledgers, or
        # evaluated roll alternatives. Treating PnL as premium and inventing
        # those missing values would mix observed and synthetic evidence.
        replay_positions: list[dict[str, Any]] = []
        observed_positions = account_position_count
        status = "unavailable" if observed_positions else "empty"
        reason_code = (
            "MISSING_POSITION_MANAGEMENT_EVIDENCE"
            if observed_positions
            else "NO_OPEN_POSITIONS"
        )
        if observed_positions:
            missing_evidence = _required_evidence_paths()
    else:
        observed_positions = len(positions)
        missing_evidence = sorted(
            {
                path
                for position in positions
                for path in _position_evidence_gaps(position)
            }
        )
        replay_positions = [] if missing_evidence else positions
        status = (
            "unavailable"
            if missing_evidence
            else "available"
            if replay_positions
            else "empty"
        )
        reason_code = (
            "MISSING_POSITION_MANAGEMENT_EVIDENCE"
            if missing_evidence
            else None
            if replay_positions
            else "NO_POSITIONS_PROVIDED"
        )
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
        "status": status,
        "reason_code": reason_code,
        "missing_evidence": missing_evidence,
        "state_definitions": list(POSITION_STATES),
        "replays": replays,
        "summary": {
            "positions_observed": observed_positions,
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
    missing_evidence = _position_evidence_gaps(position)
    if missing_evidence:
        raise ValueError(
            "position management evidence is incomplete: "
            + ", ".join(missing_evidence)
        )
    current_delta = abs(
        float(
            position["current_delta"]
            if "current_delta" in position
            else position["delta"]
        )
    )
    loss_multiple = float(position["loss_multiple"])
    state = classify_position_state(
        current_delta=current_delta,
        loss_multiple=loss_multiple,
        breakout_kill=bool(position.get("breakout_kill", False))
        or "BREAKOUT_KILL" in permission_state.get("reason_codes", []),
        portfolio_final_action=str(portfolio_risk.get("final_action") or "halt_system"),
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
        "current_delta": current_delta,
        "loss_multiple": loss_multiple,
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
    minimum_state = _PORTFOLIO_ACTION_MINIMUM_STATE.get(portfolio_final_action)
    if portfolio_final_action not in _PORTFOLIO_ACTION_MINIMUM_STATE:
        return "PAUSED"
    if minimum_state == "PAUSED":
        return "PAUSED"
    if minimum_state == "FORCE_CLOSE" or breakout_kill or current_delta > 0.40:
        return "FORCE_CLOSE"
    if current_delta > 0.35 or loss_multiple > 3.0:
        return "EXIT_REQUIRED"
    if minimum_state == "DEFENSE" or current_delta > 0.25 or loss_multiple >= 2.0:
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
    if report.get("status") not in {"available", "empty", "unavailable"}:
        errors.append("position_management.status is invalid")
    status = report.get("status")
    if status == "unavailable" and report.get("replays") != []:
        errors.append("unavailable position management must not expose replays")
    if status == "empty" and report.get("replays") != []:
        errors.append("empty position management must not expose replays")
    missing_evidence = report.get("missing_evidence")
    if not isinstance(missing_evidence, list) or any(
        not isinstance(item, str) or not item for item in (missing_evidence or [])
    ):
        errors.append("position_management.missing_evidence must be a list of paths")
    if report.get("status") == "available" and missing_evidence:
        errors.append("available position management must not have missing evidence")
    if report.get("status") == "unavailable" and not missing_evidence:
        errors.append("unavailable position management must identify missing evidence")
    if report.get("status") == "empty" and missing_evidence:
        errors.append("empty position management must not claim missing evidence")
    if set(report.get("state_definitions") or []) != set(POSITION_STATES):
        errors.append("position_management.state_definitions must include all states")
    replays = report.get("replays")
    if not isinstance(replays, list):
        errors.append("position_management.replays must be a list")
    elif status == "available":
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


def _active_roll_allowed(position: dict[str, Any], state: str) -> bool:
    candidate = position["roll_candidate"]
    if state not in {"NORMAL", "CAUTION"}:
        return False
    return (
        float(candidate["ev_after"]) > float(candidate["ev_before"])
        and float(candidate["p_touch_after"]) < float(candidate["p_touch_before"])
        and float(candidate["stress_loss_after"])
        < float(candidate["stress_loss_before"])
    )


def _defensive_action_allowed(position: dict[str, Any], state: str) -> bool:
    if state not in {"DEFENSE", "EXIT_REQUIRED"}:
        return False
    return _protective_spread_exception(position)["allowed"]


def _protective_spread_exception(position: dict[str, Any]) -> dict[str, Any]:
    spread = position["protective_spread"]
    before = float(spread["stress_loss_before"])
    after = float(spread["stress_loss_after"])
    gamma_before = float(spread["net_short_gamma_before"])
    gamma_after = float(spread["net_short_gamma_after"])
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
    hedge = position["hedge"]
    funding = float(hedge["realized_funding_usdc"])
    fee = float(hedge["trading_fee_usdc"])
    slippage = float(hedge["slippage_usdc"])
    collected = float(position["collected_premium_usdc"])
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


def _position_evidence_gaps(position: Any) -> list[str]:
    if not isinstance(position, dict):
        return ["position"]
    gaps: list[str] = []
    delta_key = (
        "current_delta"
        if "current_delta" in position
        else "delta"
        if "delta" in position
        else None
    )
    if delta_key is None or not _is_finite_number(position.get(delta_key)):
        gaps.append("current_delta")
    elif abs(float(position[delta_key])) > 1.0:
        gaps.append("current_delta")
    if not _is_finite_number(position.get("loss_multiple")) or (
        _is_finite_number(position.get("loss_multiple"))
        and float(position["loss_multiple"]) < 0.0
    ):
        gaps.append("loss_multiple")
    premium = position.get("collected_premium_usdc")
    if not _is_finite_number(premium) or float(premium) <= 0.0:
        gaps.append("collected_premium_usdc")
    for section, keys in _REQUIRED_POSITION_EVIDENCE.items():
        evidence = position.get(section)
        if not isinstance(evidence, dict):
            gaps.extend(f"{section}.{key}" for key in keys)
            continue
        for key in keys:
            value = evidence.get(key)
            if not _is_finite_number(value):
                gaps.append(f"{section}.{key}")
                continue
            if key in {"p_touch_before", "p_touch_after"} and not (
                0.0 <= float(value) <= 1.0
            ):
                gaps.append(f"{section}.{key}")
            elif key in {
                "stress_loss_before",
                "stress_loss_after",
                "trading_fee_usdc",
                "slippage_usdc",
            } and float(value) < 0.0:
                gaps.append(f"{section}.{key}")
    return gaps


def _required_evidence_paths() -> list[str]:
    return [
        "current_delta",
        "loss_multiple",
        "collected_premium_usdc",
        *(
            f"{section}.{key}"
            for section, keys in _REQUIRED_POSITION_EVIDENCE.items()
            for key in keys
        ),
    ]


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
