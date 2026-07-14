"""Portfolio-risk arbiter and research-mode sizing helpers for ISSUE-011."""

from __future__ import annotations

import math
from typing import Any

PORTFOLIO_RISK_SCHEMA_VERSION = "portfolio_risk_report.v1"

SEVERITY_ORDER = {
    "allow_new": 0,
    "reduce_size": 1,
    "spread_only": 2,
    "no_new_trades": 3,
    "reduce_existing": 4,
    "close_batch": 5,
    "close_all_and_pause": 6,
    "halt_system": 7,
}

DEFAULT_RISK_BUDGET = {
    "max_single_spread_loss_nav": 0.015,
    "max_single_naked_stress_loss_nav": 0.0075,
    "max_new_margin_nav": 0.08,
    "max_net_delta_nav": 0.08,
    "max_depth_fraction": 0.10,
    "inverse_position_size_multiplier": 0.70,
}


def build_portfolio_risk_report(
    *,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    permission_state: dict[str, Any],
    ev_candidate_scanner: dict[str, Any],
    risk_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a unified risk-arbiter report and shadow sizing table."""

    overrides = risk_overrides or {}
    signals = []
    signals.extend(_account_signals(account_status))
    signals.extend(_data_quality_signals(data_status))
    signals.extend(_permission_signals(permission_state))
    signals.extend(_mdd_signals(overrides.get("mdd_circuit")))
    signals.extend(_event_signals(overrides.get("event_risk")))
    signals.extend(_liquidity_signals(overrides.get("liquidity_state")))
    signals.extend(_exchange_signals(overrides.get("exchange_status")))
    signals.extend(_position_signals(overrides.get("position_state")))

    final_signal = max(
        signals,
        key=lambda signal: SEVERITY_ORDER[signal["severity"]],
    )
    candidates = (
        []
        if final_signal["severity"] == "halt_system"
        else ev_candidate_scanner.get("ranked_candidates") or []
    )
    size_caps = [
        _candidate_size_cap(
            candidate=candidate,
            account_status=account_status,
            permission_state=permission_state,
        )
        for candidate in candidates[:5]
    ]

    return {
        "schema_version": PORTFOLIO_RISK_SCHEMA_VERSION,
        "generated_at": generated_at,
        "severity_order": dict(SEVERITY_ORDER),
        "signals": signals,
        "final_signal": final_signal,
        "final_action": final_signal["severity"],
        "research_only": True,
        "size_caps": size_caps,
        "summary": {
            "signal_count": len(signals),
            "highest_severity": final_signal["severity"],
            "candidate_caps_evaluated": len(size_caps),
            "trade_sizing_allowed": False,
            "reason_codes": _unique_codes(
                [
                    code
                    for signal in signals
                    for code in signal.get("reason_codes", [])
                ]
                + ["RESEARCH_ONLY_SIZE_CAPS", "MISSING_PROMOTED_SCORE_MODEL"]
            ),
        },
    }


def validate_portfolio_risk_report(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["portfolio_risk must be a dict"]
    if report.get("schema_version") != PORTFOLIO_RISK_SCHEMA_VERSION:
        errors.append("portfolio_risk.schema_version must be portfolio_risk_report.v1")
    if report.get("final_action") not in SEVERITY_ORDER:
        errors.append("portfolio_risk.final_action must be a known severity")
    signals = report.get("signals")
    if not isinstance(signals, list) or not signals:
        errors.append("portfolio_risk.signals must be a non-empty list")
    else:
        for signal in signals:
            if not isinstance(signal, dict):
                errors.append("portfolio_risk signal entries must be dicts")
                continue
            for key in ("source", "severity", "reason", "reason_codes", "expires_at"):
                if key not in signal:
                    errors.append(f"portfolio_risk signal missing key: {key}")
            if signal.get("severity") not in SEVERITY_ORDER:
                errors.append("portfolio_risk signal has unknown severity")
    final_signal = report.get("final_signal")
    if not isinstance(final_signal, dict):
        errors.append("portfolio_risk.final_signal must be a dict")
    elif signals:
        expected = max(
            signals,
            key=lambda signal: SEVERITY_ORDER.get(signal.get("severity"), -1),
        )
        if final_signal != expected:
            errors.append(
                "portfolio_risk.final_signal must match the highest-severity signal"
            )
        if report.get("final_action") != final_signal.get("severity"):
            errors.append(
                "portfolio_risk.final_action must match final_signal.severity"
            )
    if not isinstance(report.get("size_caps"), list):
        errors.append("portfolio_risk.size_caps must be a list")
    return errors


def _account_signals(account_status: dict[str, Any]) -> list[dict[str, Any]]:
    light = account_status.get("margin_light")
    gate = account_status.get("trade_gate")
    if light == "GREEN" and gate == "ALLOW_NEW":
        return [
            _signal(
                source="margin_light",
                severity="allow_new",
                reason="Account margin light is green and projected margin allows new trades.",
                reason_codes=["ACCOUNT_MARGIN_GREEN"],
            )
        ]
    if light == "YELLOW" or gate == "NO_NEW_TRADES":
        return [
            _signal(
                source="margin_light",
                severity="no_new_trades",
                reason="Yellow margin state blocks new positions but permits reductions.",
                reason_codes=["ACCOUNT_MARGIN_YELLOW_NO_NEW_TRADES"],
            )
        ]
    if light == "RED" or gate == "REDUCE_EXISTING":
        return [
            _signal(
                source="margin_light",
                severity="reduce_existing",
                reason="Red margin state requires existing risk reduction.",
                reason_codes=["ACCOUNT_MARGIN_RED_REDUCE_EXISTING"],
            )
        ]
    return [
        _signal(
            source="margin_light",
            severity="halt_system",
            reason="Account state is missing, stale, auth-failed, or otherwise halted.",
            reason_codes=[str(account_status.get("reason_code") or "ACCOUNT_MARGIN_HALT")],
        )
    ]


def _data_quality_signals(data_status: dict[str, Any]) -> list[dict[str, Any]]:
    status = data_status.get("status")
    if status == "validated":
        return [
            _signal(
                source="data_quality",
                severity="allow_new",
                reason="Market data quality gate is validated.",
                reason_codes=["MARKET_DATA_QUALITY_PASS"],
            )
        ]
    if status == "blocked":
        return [
            _signal(
                source="data_quality",
                severity="halt_system",
                reason="Blocked market data quality fails closed for new and existing decisions.",
                reason_codes=list(
                    (data_status.get("quality_gate") or {}).get("reason_codes")
                    or ["MARKET_DATA_QUALITY_FAIL"]
                ),
            )
        ]
    return [
        _signal(
            source="data_quality",
            severity="halt_system",
            reason="Validated market data is missing.",
            reason_codes=["MISSING_VALIDATED_MARKET_DATA"],
        )
    ]


def _permission_signals(permission_state: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(permission_state, dict):
        return [_malformed_permission_signal()]

    raw_sell_permission = permission_state.get("sell_permission")
    naked_permission = permission_state.get("naked_permission")
    spread_permission = permission_state.get("spread_permission")
    if (
        isinstance(raw_sell_permission, bool)
        or not isinstance(raw_sell_permission, (int, float))
        or not math.isfinite(raw_sell_permission)
        or not 0.0 <= raw_sell_permission <= 1.0
        or not isinstance(naked_permission, bool)
        or not isinstance(spread_permission, bool)
    ):
        return [_malformed_permission_signal()]

    sell_permission = float(raw_sell_permission)
    if sell_permission <= 0.0:
        return [
            _signal(
                source="permission_cap",
                severity="no_new_trades",
                reason="Regime or volatility cap sets sell permission to zero.",
                reason_codes=list(permission_state.get("reason_codes") or ["PERMISSION_ZERO"]),
            )
        ]
    if not naked_permission and not spread_permission:
        return [_malformed_permission_signal()]
    if not naked_permission and spread_permission:
        return [
            _signal(
                source="permission_cap",
                severity="spread_only",
                reason="Permission cap blocks naked calls but allows defined-risk spreads.",
                reason_codes=list(permission_state.get("reason_codes") or ["SPREAD_ONLY"]),
            )
        ]
    return [
        _signal(
            source="permission_cap",
            severity="allow_new",
            reason="Permission cap allows research-mode candidate evaluation.",
            reason_codes=list(permission_state.get("reason_codes") or ["PERMISSION_ACTIVE"]),
        )
    ]


def _malformed_permission_signal() -> dict[str, Any]:
    return _signal(
        source="permission_cap",
        severity="halt_system",
        reason="Permission state is malformed or internally inconsistent.",
        reason_codes=["MALFORMED_PERMISSION_STATE"],
    )


def _mdd_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return [_signal(source="mdd_circuit", severity="allow_new", reason="No MDD circuit is active.", reason_codes=["MDD_CLEAR"])]
    if not isinstance(state, dict):
        return [_malformed_mdd_signal()]
    status = state.get("status")
    if status == "clear":
        return [_signal(source="mdd_circuit", severity="allow_new", reason="MDD circuit is clear.", reason_codes=["MDD_CLEAR"])]
    if status == "halt":
        return [_signal(source="mdd_circuit", severity="halt_system", reason="MDD circuit breaker is halted.", reason_codes=["MDD_HALT"], expires_at=state.get("expires_at"))]
    if status == "close_all_and_pause":
        return [_signal(source="mdd_circuit", severity="close_all_and_pause", reason="MDD circuit requires closing all risk and pausing.", reason_codes=["MDD_CLOSE_ALL_PAUSE"], expires_at=state.get("expires_at"))]
    if status == "close_batch":
        return [_signal(source="mdd_circuit", severity="close_batch", reason="MDD circuit requires closing the affected batch.", reason_codes=["MDD_CLOSE_BATCH"], expires_at=state.get("expires_at"))]
    return [_malformed_mdd_signal()]


def _malformed_mdd_signal() -> dict[str, Any]:
    return _signal(
        source="mdd_circuit",
        severity="halt_system",
        reason="MDD circuit state is missing a recognized status.",
        reason_codes=["MDD_STATE_MALFORMED"],
    )


def _event_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return [_signal(source="event_risk", severity="allow_new", reason="No blocking event window is active.", reason_codes=["EVENT_CLEAR"])]
    if not isinstance(state, dict):
        return [_malformed_override_signal("event_risk", "EVENT_RISK_STATE_MALFORMED")]
    status = state.get("status")
    if status == "clear":
        return [_signal(source="event_risk", severity="allow_new", reason="No blocking event window is active.", reason_codes=["EVENT_CLEAR"])]
    if status not in {"active", "high"}:
        return [_malformed_override_signal("event_risk", "EVENT_RISK_STATE_MALFORMED")]
    severity = "close_all_and_pause" if status == "high" else "no_new_trades"
    return [_signal(source="event_risk", severity=severity, reason=str(state.get("reason") or "Event risk window is active."), reason_codes=[str(state.get("reason_code") or "EVENT_RISK_ACTIVE")], expires_at=state.get("expires_at"))]


def _liquidity_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return [_signal(source="liquidity_state", severity="allow_new", reason="Liquidity state is normal.", reason_codes=["LIQUIDITY_NORMAL"])]
    if not isinstance(state, dict):
        return [_malformed_override_signal("liquidity_state", "LIQUIDITY_STATE_MALFORMED")]
    status = state.get("status")
    if status == "normal":
        return [_signal(source="liquidity_state", severity="allow_new", reason="Liquidity state is normal.", reason_codes=["LIQUIDITY_NORMAL"])]
    if status == "thin":
        severity = "reduce_size"
    elif status == "spread_only":
        severity = "spread_only"
    elif status == "blocked":
        severity = "no_new_trades"
    else:
        return [_malformed_override_signal("liquidity_state", "LIQUIDITY_STATE_MALFORMED")]
    return [_signal(source="liquidity_state", severity=severity, reason=str(state.get("reason") or "Liquidity state limits new risk."), reason_codes=[str(state.get("reason_code") or "LIQUIDITY_LIMIT")])]


def _exchange_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return [_signal(source="exchange_status", severity="allow_new", reason="Exchange status is online.", reason_codes=["EXCHANGE_ONLINE"])]
    if not isinstance(state, dict):
        return [_malformed_override_signal("exchange_status", "EXCHANGE_STATUS_MALFORMED")]
    status = state.get("status")
    if status == "online":
        return [_signal(source="exchange_status", severity="allow_new", reason="Exchange status is online.", reason_codes=["EXCHANGE_ONLINE"])]
    if status not in {"offline", "degraded", "maintenance"}:
        return [_malformed_override_signal("exchange_status", "EXCHANGE_STATUS_MALFORMED")]
    return [_signal(source="exchange_status", severity="halt_system", reason=str(state.get("reason") or "Exchange status is not safe for research replay."), reason_codes=[str(state.get("reason_code") or "EXCHANGE_STATUS_BLOCK")], expires_at=state.get("expires_at"))]


def _position_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return [_signal(source="position_state", severity="allow_new", reason="No position-state blocker is active.", reason_codes=["POSITION_NORMAL"])]
    if not isinstance(state, dict):
        return [_malformed_override_signal("position_state", "POSITION_STATE_MALFORMED")]
    position_state = state.get("state")
    if position_state == "NORMAL":
        return [_signal(source="position_state", severity="allow_new", reason="No position-state blocker is active.", reason_codes=["POSITION_NORMAL"])]
    mapping = {
        "CAUTION": "reduce_size",
        "DEFENSE": "reduce_existing",
        "EXIT_REQUIRED": "close_batch",
        "FORCE_CLOSE": "close_batch",
        "PAUSED": "close_all_and_pause",
    }
    severity = mapping.get(str(position_state))
    if severity is None:
        return [_malformed_override_signal("position_state", "POSITION_STATE_MALFORMED")]
    return [_signal(source="position_state", severity=severity, reason=str(state.get("reason") or f"Position state is {position_state}."), reason_codes=[str(state.get("reason_code") or f"POSITION_{position_state}")])]


def _malformed_override_signal(source: str, reason_code: str) -> dict[str, Any]:
    return _signal(
        source=source,
        severity="halt_system",
        reason=f"{source} override is malformed or has an unknown state.",
        reason_codes=[reason_code],
    )


def _candidate_size_cap(
    *,
    candidate: dict[str, Any],
    account_status: dict[str, Any],
    permission_state: dict[str, Any],
) -> dict[str, Any]:
    snapshot = account_status.get("snapshot") or {}
    projected = account_status.get("projected_margin") or {}
    # Risk-budget dimensions are USD-denominated. Never reinterpret a BTC (or
    # unknown-currency) account equity value as USD when conversion evidence is
    # absent. The action output is already zero without a promoted model; the
    # shadow cap must remain zero rather than fabricate a USD NAV.
    nav = float(snapshot.get("nav_usd") or projected.get("nav_usd") or 0.0)
    path_risk = candidate.get("path_risk") or {}
    margin = candidate.get("margin_snapshot") or {}
    liquidity_depth = _candidate_depth(candidate)
    abs_delta = abs(float(candidate.get("model_delta") or 0.0))
    underlying = float(candidate.get("underlying_price") or 1.0)
    delta_usdc = max(abs_delta * underlying, 1.0)
    cvar = max(float(path_risk.get("cvar_99_usdc") or 0.0), 1.0)
    stress = max(float(path_risk.get("stress_loss_usdc") or cvar), 1.0)
    delta_margin = max(float(margin.get("delta_initial_margin") or 0.0), 1.0)
    permission_cap = float(permission_state.get("sell_permission") or 0.0)
    volatility_cap = _volatility_size_multiplier(permission_state.get("volatility_inputs") or {})
    score_placeholder = 0.0
    inverse_multiplier = DEFAULT_RISK_BUDGET["inverse_position_size_multiplier"]

    dimensions = [
        _dimension("cvar", nav * DEFAULT_RISK_BUDGET["max_single_spread_loss_nav"] / cvar),
        _dimension("stress", nav * DEFAULT_RISK_BUDGET["max_single_naked_stress_loss_nav"] / stress),
        _dimension("delta", nav * DEFAULT_RISK_BUDGET["max_net_delta_nav"] / delta_usdc),
        _dimension("margin", nav * DEFAULT_RISK_BUDGET["max_new_margin_nav"] / delta_margin),
        _dimension("liquidity", liquidity_depth * DEFAULT_RISK_BUDGET["max_depth_fraction"]),
        _dimension("score_placeholder", score_placeholder),
    ]
    raw_cap = min(item["cap_units"] for item in dimensions)
    multiplier_dimensions = [
        _dimension("permission", permission_cap),
        _dimension("volatility", volatility_cap),
        _dimension("inverse_multiplier", inverse_multiplier),
    ]
    if_calibrated_raw = min(
        item["cap_units"]
        for item in dimensions
        if item["dimension"] != "score_placeholder"
    )
    calibrated_shadow_cap = if_calibrated_raw * min(
        item["cap_units"] for item in multiplier_dimensions
    )
    final_cap = raw_cap * min(item["cap_units"] for item in multiplier_dimensions)
    all_dimensions = dimensions + multiplier_dimensions
    limiting = min(all_dimensions, key=lambda item: item["cap_units"])
    return {
        "candidate_id": candidate.get("candidate_id"),
        "structure_type": candidate.get("structure_type"),
        "raw_cap_units": round(raw_cap, 6),
        "calibrated_shadow_cap_units": round(calibrated_shadow_cap, 6),
        "final_cap_units": round(final_cap, 6),
        "limiting_dimension": limiting["dimension"],
        "dimensions": all_dimensions,
        "research_only_reason": "Score calibration is not promoted into sizing, so final actionable size remains zero.",
        "size_output_allowed": False,
        "reason_codes": [
            "RESEARCH_ONLY_SIZE_CAPS",
            "MISSING_PROMOTED_SCORE_MODEL",
            *([] if nav > 0.0 else ["MISSING_USD_NAV_CONVERSION"]),
        ],
    }


def _volatility_size_multiplier(inputs: dict[str, Any]) -> float:
    percentile = max(
        float(inputs.get("dvol_percentile") or 0.0),
        float(inputs.get("atm_iv_percentile") or 0.0),
    )
    if percentile >= 0.98:
        return 0.0
    if percentile >= 0.95:
        return 0.20
    if percentile >= 0.80:
        return 0.40
    if percentile >= 0.60:
        return 0.65
    return 1.0


def _candidate_depth(candidate: dict[str, Any]) -> float:
    if candidate.get("structure_type") == "call_credit_spread":
        return min(
            float(candidate.get("sell_leg_depth") or 0.0),
            float(candidate.get("buy_leg_depth") or 0.0),
        )
    return float(candidate.get("depth") or 0.0)


def _dimension(name: str, value: float) -> dict[str, Any]:
    return {
        "dimension": name,
        "cap_units": round(max(float(value), 0.0), 6),
    }


def _signal(
    *,
    source: str,
    severity: str,
    reason: str,
    reason_codes: list[str],
    expires_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "severity": severity,
        "reason": reason,
        "reason_codes": _unique_codes(reason_codes),
        "expires_at": expires_at,
    }


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
