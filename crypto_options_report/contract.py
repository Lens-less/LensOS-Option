"""Shared report contract and product-mode gate.

ISSUE-001 established the initial fail-closed `research_report.v1` shape.
ISSUE-002 extends the market-data quality slice, ISSUE-004 extends the
account-risk slice, ISSUE-005 adds a deterministic PnL evidence slice,
ISSUE-007 adds the surface/candidate slice, ISSUE-008 adds research-only
regime permission caps, and ISSUE-011 through ISSUE-015 add the remaining
risk, replay, calibration, surface, and paper-ledger tracers while preserving
no-trade safeguards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .account_risk import (
    ACCOUNT_GATE_NO_TRADE,
    ACCOUNT_MARGIN_HALT,
    account_reason_codes,
    build_account_status,
    load_account_scenario,
    risk_state_from_account_status,
)
from .market_data import build_market_data_status, parse_timestamp_ms
from .pnl import build_pnl_evidence_report
from .ev_scanner import build_ev_candidate_scanner
from .calibration import (
    build_walk_forward_calibration_report,
    validate_walk_forward_calibration_report,
)
from .full_surface import (
    build_full_system_surface_report,
    validate_full_system_surface_report,
)
from .regime import build_regime_permission_state
from .paper_ledger import (
    build_paper_proposal_ledger,
    validate_paper_proposal_ledger,
)
from .portfolio_risk import (
    build_portfolio_risk_report,
    validate_portfolio_risk_report,
)
from .position_management import (
    build_position_management_report,
    validate_position_management_report,
)
from .surface import build_vol_surface_and_candidate_research

SCHEMA_VERSION = "research_report.v1"
SUPPORTED_MODES = {"research_only", "paper", "manual_execution"}
SAFE_ACTIONS = {"RESEARCH_ONLY", "RESEARCH_ONLY_NO_TRADE", "NO_TRADE"}

REQUIRED_REPORT_KEYS = {
    "schema_version",
    "generated_at",
    "mode",
    "effective_mode",
    "action",
    "confidence",
    "risk_state",
    "permission_state",
    "reason_codes",
    "data_trust",
    "data_status",
    "account_status",
    "calibration_status",
    "backtest_status",
    "mode_gate",
    "blocked_outputs",
    "pnl_evidence",
    "vol_surface_status",
    "candidate_research",
    "ev_candidate_scanner",
    "portfolio_risk",
    "position_management",
    "walk_forward_calibration",
    "full_system_surface",
    "paper_proposal_ledger",
}

FORBIDDEN_RESEARCH_ONLY_KEYS = {
    "recommended_size",
    "size_contracts",
    "order_instructions",
    "order_template",
    "trade_instruction",
    "trade_instructions",
    "trade_candidates",
    "paper_trade_candidates",
    "manual_trade_candidates",
    "paper_manual_trade_candidates",
    "entry_rule",
    "exit_rule",
    "suggested_size",
    "take_profit",
    "risk_exit",
    "quantity",
    "qty",
    "contracts",
    "symbol",
    "side",
    "strike",
    "expiry",
    "limit_price",
    "post_only_price",
}

DEFAULT_REASON_CODES = [
    "MISSING_VALIDATED_MARKET_DATA",
    "MISSING_ACCOUNT_API_SNAPSHOT",
    "MISSING_CALIBRATED_MODEL",
    "MISSING_BACKTEST_ALIGNMENT",
]


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def generate_research_report(
    *,
    mode: str = "research_only",
    generated_at: str | None = None,
    market_snapshot: dict[str, Any] | None = None,
    account_payload: dict[str, Any] | None = None,
    account_scenario: str | None = None,
) -> dict[str, Any]:
    """Build the shared report payload for CLI/API/dashboard consumers."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"unsupported mode {mode!r}; expected one of {sorted(SUPPORTED_MODES)}"
        )

    generated = generated_at or utc_timestamp()
    evaluation_now_ms = parse_timestamp_ms(generated)
    if account_payload is not None and account_scenario is not None:
        raise ValueError("pass account_payload or account_scenario, not both")
    if account_scenario is not None:
        account_payload = load_account_scenario(account_scenario)

    data_status = (
        build_market_data_status(market_snapshot, now_ms=evaluation_now_ms)
        if market_snapshot is not None
        else {
            "status": "missing",
            "validated": False,
            "source": "not_configured",
            "reason_code": "MISSING_VALIDATED_MARKET_DATA",
        }
    )
    account_status = build_account_status(
        generated_at=generated,
        account_payload=account_payload,
    )

    reason_codes: list[str] = []
    if data_status["status"] == "missing":
        reason_codes.append("MISSING_VALIDATED_MARKET_DATA")
    elif data_status["status"] == "blocked":
        reason_codes.extend(data_status["quality_gate"]["reason_codes"])

    reason_codes.extend(account_reason_codes(account_status))
    reason_codes.extend(["MISSING_CALIBRATED_MODEL", "MISSING_BACKTEST_ALIGNMENT"])

    data_trust = _build_data_trust_summary(data_status)

    action = "RESEARCH_ONLY"
    if mode != "research_only":
        action = "NO_TRADE"
        reason_codes.insert(0, "MODE_NOT_ENABLED")
    elif data_status["status"] == "blocked":
        action = "RESEARCH_ONLY_NO_TRADE"
    elif (
        account_status["status"] != "missing"
        and account_status["trade_gate"] == ACCOUNT_GATE_NO_TRADE
    ):
        action = "NO_TRADE"

    risk_state = risk_state_from_account_status(account_status)
    if data_status["status"] == "blocked":
        risk_state = ACCOUNT_MARGIN_HALT

    pnl_evidence = build_pnl_evidence_report()
    vol_surface_status, candidate_research = build_vol_surface_and_candidate_research(
        market_snapshot=market_snapshot,
        generated_at=generated,
        data_status=data_status,
        pnl_evidence=pnl_evidence,
    )

    permission_state = build_regime_permission_state(
        market_snapshot=market_snapshot,
        data_status=data_status,
        vol_surface_status=vol_surface_status,
    )
    reason_codes.extend(permission_state["reason_codes"])

    calibration_status = {
        "status": "missing",
        "calibrated": False,
        "model_version": None,
        "reason_code": "MISSING_CALIBRATED_MODEL",
    }
    ev_candidate_scanner = build_ev_candidate_scanner(
        generated_at=generated,
        data_status=data_status,
        account_status=account_status,
        calibration_status=calibration_status,
        permission_state=permission_state,
        candidate_research=candidate_research,
    )
    portfolio_risk = build_portfolio_risk_report(
        generated_at=generated,
        data_status=data_status,
        account_status=account_status,
        permission_state=permission_state,
        ev_candidate_scanner=ev_candidate_scanner,
    )
    position_management = build_position_management_report(
        generated_at=generated,
        account_status=account_status,
        portfolio_risk=portfolio_risk,
        permission_state=permission_state,
    )
    walk_forward_calibration = build_walk_forward_calibration_report(
        generated_at=generated,
        portfolio_risk=portfolio_risk,
        position_management=position_management,
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "mode": mode,
        "effective_mode": "research_only",
        "action": action,
        "confidence": "UNCALIBRATED",
        "risk_state": risk_state,
        "permission_state": {
            **permission_state,
            "account_margin_light": account_status["margin_light"],
            "account_trade_gate": account_status["trade_gate"],
        },
        "reason_codes": _unique_codes(reason_codes),
        "data_trust": data_trust,
        "data_status": data_status,
        "account_status": account_status,
        "calibration_status": calibration_status,
        "backtest_status": {
            "status": "missing",
            "aligned": False,
            "reason_code": "MISSING_BACKTEST_ALIGNMENT",
        },
        "mode_gate": {
            "trade_recommendation_allowed": False,
            "recommended_size_allowed": False,
            "order_instructions_allowed": False,
            "paper_manual_candidates_allowed": False,
            "reason_codes": _unique_codes(reason_codes),
        },
        "blocked_outputs": [
            "trade_recommendation",
            "recommended_size",
            "order_instructions",
            "paper_manual_trade_candidates",
        ],
        "pnl_evidence": pnl_evidence,
        "vol_surface_status": vol_surface_status,
        "candidate_research": candidate_research,
        "ev_candidate_scanner": ev_candidate_scanner,
        "portfolio_risk": portfolio_risk,
        "position_management": position_management,
        "walk_forward_calibration": walk_forward_calibration,
    }
    report["paper_proposal_ledger"] = build_paper_proposal_ledger(
        generated_at=generated,
        report=report,
        allow_paper=False,
    )
    report["full_system_surface"] = build_full_system_surface_report(
        generated_at=generated,
        report=report,
    )

    errors = validate_report_contract(report)
    if errors:
        raise ValueError("; ".join(errors))
    return report


def report_shape(value: Any) -> Any:
    """Return a comparable shape with values replaced by type names."""

    if isinstance(value, dict):
        return {key: report_shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [report_shape(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def validate_report_contract(report: dict[str, Any]) -> list[str]:
    """Validate the small schema contract without adding a JSON Schema dep."""

    errors: list[str] = []
    missing = REQUIRED_REPORT_KEYS.difference(report)
    if missing:
        errors.append(f"missing required keys: {sorted(missing)}")

    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be research_report.v1")
    if report.get("mode") not in SUPPORTED_MODES:
        errors.append("mode must be a supported product mode")
    if report.get("effective_mode") != "research_only":
        errors.append("effective_mode must remain research_only")
    if report.get("action") not in SAFE_ACTIONS:
        errors.append(
            "action must be RESEARCH_ONLY, RESEARCH_ONLY_NO_TRADE, or NO_TRADE"
        )
    if report.get("confidence") != "UNCALIBRATED":
        errors.append("confidence must be UNCALIBRATED for the current slices")
    if report.get("risk_state") not in {"GREEN", "YELLOW", "RED", "HALT"}:
        errors.append("risk_state must be GREEN, YELLOW, RED, or HALT")

    data_status = report.get("data_status", {})
    errors.extend(_validate_data_trust(report.get("data_trust"), data_status))
    if data_status.get("status") == "missing":
        if "MISSING_VALIDATED_MARKET_DATA" not in report.get("reason_codes", []):
            errors.append("missing reason code: MISSING_VALIDATED_MARKET_DATA")
    elif data_status.get("status") == "blocked":
        for code in data_status.get("quality_gate", {}).get("reason_codes", []):
            if code not in report.get("reason_codes", []):
                errors.append(f"missing quality reason code: {code}")
    for code in ("MISSING_CALIBRATED_MODEL", "MISSING_BACKTEST_ALIGNMENT"):
        if code not in report.get("reason_codes", []):
            errors.append(f"missing reason code: {code}")

    account_reason_code = (report.get("account_status", {}) or {}).get("reason_code")
    if account_reason_code and account_reason_code not in report.get("reason_codes", []):
        errors.append("account_status reason_code must appear in report reason_codes")

    mode = report.get("mode")
    action = report.get("action")
    if mode != "research_only" and action != "NO_TRADE":
        errors.append("non-research modes must stay NO_TRADE")
    if mode == "research_only" and data_status.get("status") == "blocked":
        if action != "RESEARCH_ONLY_NO_TRADE":
            errors.append("blocked market data must force RESEARCH_ONLY_NO_TRADE")

    mode_gate = report.get("mode_gate", {})
    if mode_gate.get("trade_recommendation_allowed") is not False:
        errors.append("mode gate must block trade recommendations")
    if mode_gate.get("recommended_size_allowed") is not False:
        errors.append("mode gate must block recommended size")
    if mode_gate.get("order_instructions_allowed") is not False:
        errors.append("mode gate must block order instructions")
    if mode_gate.get("paper_manual_candidates_allowed") is not False:
        errors.append("mode gate must block paper/manual candidates")
    if mode_gate.get("reason_codes") != report.get("reason_codes"):
        errors.append("mode gate reason_codes must match report reason_codes")

    errors.extend(_validate_data_status(data_status))
    errors.extend(_validate_account_status(report.get("account_status", {})))
    errors.extend(_validate_permission_state(report.get("permission_state", {})))

    calibration_status = report.get("calibration_status", {})
    if calibration_status.get("status") != "missing":
        errors.append("calibration_status.status must be missing")
    if calibration_status.get("calibrated") is not False:
        errors.append("calibration_status.calibrated must be false")
    if calibration_status.get("model_version") is not None:
        errors.append("calibration_status.model_version must be null")
    if calibration_status.get("reason_code") != "MISSING_CALIBRATED_MODEL":
        errors.append("calibration_status.reason_code must be MISSING_CALIBRATED_MODEL")

    backtest_status = report.get("backtest_status", {})
    if backtest_status.get("status") != "missing":
        errors.append("backtest_status.status must be missing")
    if backtest_status.get("aligned") is not False:
        errors.append("backtest_status.aligned must be false")
    if backtest_status.get("reason_code") != "MISSING_BACKTEST_ALIGNMENT":
        errors.append("backtest_status.reason_code must be MISSING_BACKTEST_ALIGNMENT")

    errors.extend(_validate_pnl_evidence(report.get("pnl_evidence")))
    errors.extend(_validate_vol_surface_status(report.get("vol_surface_status")))
    errors.extend(_validate_candidate_research(report.get("candidate_research")))
    errors.extend(_validate_ev_candidate_scanner(report.get("ev_candidate_scanner")))
    errors.extend(validate_portfolio_risk_report(report.get("portfolio_risk")))
    errors.extend(validate_position_management_report(report.get("position_management")))
    errors.extend(
        validate_walk_forward_calibration_report(
            report.get("walk_forward_calibration")
        )
    )
    errors.extend(validate_paper_proposal_ledger(report.get("paper_proposal_ledger")))
    errors.extend(validate_full_system_surface_report(report.get("full_system_surface")))

    forbidden = _find_forbidden_keys(report)
    if forbidden:
        errors.append(f"forbidden research-only keys present: {sorted(forbidden)}")
    return errors


def _validate_data_status(data_status: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = data_status.get("status")
    validated = data_status.get("validated")

    if status == "missing":
        if validated is not False:
            errors.append("data_status.validated must be false")
        if data_status.get("source") != "not_configured":
            errors.append("missing data_status.source must be not_configured")
        if data_status.get("reason_code") != "MISSING_VALIDATED_MARKET_DATA":
            errors.append("data_status reason_code must be MISSING_VALIDATED_MARKET_DATA")
        return errors

    if status not in {"validated", "blocked"}:
        errors.append("data_status.status must be missing, validated, or blocked")
        return errors

    if not data_status.get("source") or data_status.get("source") == "not_configured":
        errors.append("market data status must include a source")
    if not data_status.get("snapshot_captured_at"):
        errors.append("market data status must include snapshot_captured_at")
    if not isinstance(data_status.get("market_data_age_sec"), (int, float)):
        errors.append("market data status must include numeric market_data_age_sec")

    gate = data_status.get("quality_gate", {})
    if gate.get("action_if_fail") != "RESEARCH_ONLY_NO_TRADE":
        errors.append("quality gate action_if_fail must be RESEARCH_ONLY_NO_TRADE")
    if not isinstance(gate.get("reason_codes"), list):
        errors.append("quality gate reason_codes must be a list")
    if not isinstance(gate.get("per_expiry"), list) or not gate.get("per_expiry"):
        errors.append("quality gate must include per_expiry summaries")
    if not isinstance(gate.get("summary"), dict):
        errors.append("quality gate must include a summary object")
    if not isinstance(gate.get("thresholds"), dict):
        errors.append("quality gate must include thresholds")

    if status == "validated":
        if validated is not True:
            errors.append("validated data_status.validated must be true")
        if gate.get("passed") is not True:
            errors.append("validated quality gate must pass")
        if data_status.get("reason_code") not in (None, "MARKET_DATA_QUALITY_PASS"):
            errors.append("validated data_status.reason_code must be null or pass")
    else:
        if validated is not False:
            errors.append("blocked data_status.validated must be false")
        if gate.get("passed") is not False:
            errors.append("blocked quality gate must fail")
        if data_status.get("reason_code") != "MARKET_DATA_QUALITY_FAIL":
            errors.append("blocked data_status.reason_code must be MARKET_DATA_QUALITY_FAIL")
        if not gate.get("reason_codes"):
            errors.append("blocked quality gate must include reason_codes")

    return errors


def _validate_account_status(account_status: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = account_status.get("status")
    live_snapshot = account_status.get("live_snapshot")
    margin_light = account_status.get("margin_light")
    trade_gate = account_status.get("trade_gate")
    source_endpoint = account_status.get("source_endpoint")
    simulation_status = account_status.get("simulation_status", {})
    projected_margin = account_status.get("projected_margin", {})
    positions = account_status.get("positions", [])
    snapshot = account_status.get("snapshot")

    if status not in {"missing", "available", "stale", "auth_failed"}:
        errors.append(
            "account_status.status must be missing, available, stale, or auth_failed"
        )
    if live_snapshot not in {True, False}:
        errors.append("account_status.live_snapshot must be a bool")
    if margin_light not in {"GREEN", "YELLOW", "RED", "HALT"}:
        errors.append("account_status.margin_light must be GREEN, YELLOW, RED, or HALT")
    if trade_gate not in {
        "ALLOW_NEW",
        "NO_NEW_TRADES",
        "REDUCE_EXISTING",
        "NO_TRADE",
    }:
        errors.append(
            "account_status.trade_gate must be ALLOW_NEW, NO_NEW_TRADES, REDUCE_EXISTING, or NO_TRADE"
        )
    if not source_endpoint:
        errors.append("account_status.source_endpoint is required")

    if status == "missing":
        if account_status.get("reason_code") != "MISSING_ACCOUNT_API_SNAPSHOT":
            errors.append("missing account_status must use MISSING_ACCOUNT_API_SNAPSHOT")
        if live_snapshot is not False:
            errors.append("missing account_status.live_snapshot must be false")
        if margin_light != ACCOUNT_MARGIN_HALT:
            errors.append("missing account_status.margin_light must be HALT")
        if trade_gate != ACCOUNT_GATE_NO_TRADE:
            errors.append("missing account_status.trade_gate must be NO_TRADE")
        if snapshot is not None:
            errors.append("missing account_status.snapshot must be null")

    if status == "auth_failed":
        if account_status.get("reason_code") != "AUTH_FAILED_ACCOUNT_API":
            errors.append("auth_failed account_status must use AUTH_FAILED_ACCOUNT_API")
        if live_snapshot is not False:
            errors.append("auth_failed account_status.live_snapshot must be false")

    if status == "stale":
        if account_status.get("reason_code") != "STALE_ACCOUNT_DATA":
            errors.append("stale account_status must use STALE_ACCOUNT_DATA")
        if live_snapshot is not False:
            errors.append("stale account_status.live_snapshot must be false")

    if status == "available":
        if live_snapshot is not True:
            errors.append("available account_status.live_snapshot must be true")
        if snapshot is None:
            errors.append("available account_status.snapshot is required")
            errors.append("account_status.live_snapshot must be false")

    if snapshot is not None:
        snapshot_required = {
            "currency",
            "equity",
            "balance",
            "margin_balance",
            "available_funds",
            "initial_margin",
            "maintenance_margin",
            "nav_usd",
            "im_nav",
            "nav_to_mm",
            "margin_model",
            "source_endpoint",
            "data_age_ms",
        }
        missing_snapshot = snapshot_required.difference(snapshot)
        if missing_snapshot:
            errors.append(
                f"account_status.snapshot missing required keys: {sorted(missing_snapshot)}"
            )

    if not isinstance(positions, list):
        errors.append("account_status.positions must be a list")
    else:
        for position in positions:
            if not isinstance(position, dict):
                errors.append("account_status.positions entries must be objects")
                break
            missing_position = {
                "instrument_name",
                "size",
                "direction",
                "mark_price",
                "index_price",
                "pnl",
                "initial_margin",
                "maintenance_margin",
                "greeks",
                "source_endpoint",
            }.difference(position)
            if missing_position:
                errors.append(
                    f"account_status.positions entry missing keys: {sorted(missing_position)}"
                )
                break

    if simulation_status.get("status") not in {
        "available",
        "not_requested",
        "unavailable",
        "auth_failed",
    }:
        errors.append(
            "account_status.simulation_status.status must be available, not_requested, unavailable, or auth_failed"
        )
    for key in {
        "attempted",
        "available",
        "blocks_new_trades",
        "reason_code",
        "source_endpoint",
    }:
        if key not in simulation_status:
            errors.append(f"account_status.simulation_status missing key: {key}")

    if projected_margin.get("status") not in {
        "available",
        "not_requested",
        "unavailable",
        "auth_failed",
    }:
        errors.append(
            "account_status.projected_margin.status must be available, not_requested, unavailable, or auth_failed"
        )
    for key in {
        "initial_margin",
        "maintenance_margin",
        "nav_usd",
        "im_nav",
        "nav_to_mm",
        "delta_initial_margin",
        "delta_maintenance_margin",
    }:
        if key not in projected_margin:
            errors.append(f"account_status.projected_margin missing key: {key}")

    return errors


def _validate_pnl_evidence(pnl_evidence: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(pnl_evidence, dict):
        return ["pnl_evidence must be a dict"]

    if pnl_evidence.get("status") not in {"pass", "fail"}:
        errors.append("pnl_evidence.status must be pass or fail")
    if pnl_evidence.get("formula_source") != "audited_spec_and_deribit_docs":
        errors.append("pnl_evidence.formula_source must match the audited source tag")

    defaults = pnl_evidence.get("conservative_defaults")
    if not isinstance(defaults, dict):
        errors.append("pnl_evidence.conservative_defaults must be a dict")
    else:
        required_default_keys = {
            "combo_discount_default",
            "inverse_trade_fee_rule",
            "inverse_delivery_fee_rule",
            "linear_trade_fee_rule",
            "linear_delivery_fee_rule",
            "delivery_price_rule",
        }
        missing_defaults = required_default_keys.difference(defaults)
        if missing_defaults:
            errors.append(
                f"pnl_evidence.conservative_defaults missing keys: {sorted(missing_defaults)}"
            )

    checks = pnl_evidence.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("pnl_evidence.checks must be a non-empty list")
        return errors

    found_known_settlement = False
    for check in checks:
        if not isinstance(check, dict):
            errors.append("pnl_evidence checks must be dict items")
            continue
        for key in ("id", "product", "status", "inputs", "outputs"):
            if key not in check:
                errors.append(f"pnl_evidence check missing key: {key}")
        if check.get("status") not in {"pass", "fail"}:
            errors.append("pnl_evidence check status must be pass or fail")
        if not isinstance(check.get("inputs"), dict):
            errors.append("pnl_evidence check inputs must be a dict")
        if not isinstance(check.get("outputs"), dict):
            errors.append("pnl_evidence check outputs must be a dict")
        if check.get("id") == "inverse-known-long-call-settlement":
            found_known_settlement = True
            outputs = check.get("outputs", {})
            if outputs.get("actual_settlement_coin") != outputs.get("expected_settlement_coin"):
                errors.append("known inverse settlement example must match expected output")

    if not found_known_settlement:
        errors.append("pnl_evidence must include inverse-known-long-call-settlement")
    return errors


def _validate_permission_state(permission_state: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(permission_state, dict):
        return ["permission_state must be a dict"]

    if permission_state.get("status") not in {"blocked", "validated"}:
        errors.append("permission_state.status must be blocked or validated")
    sell_permission = permission_state.get("sell_permission")
    if not isinstance(sell_permission, (int, float)) or not 0.0 <= float(sell_permission) <= 1.0:
        errors.append("sell_permission must be a number between 0.0 and 1.0")
    if permission_state.get("naked_permission") not in {True, False}:
        errors.append("naked_permission must be a bool")
    if permission_state.get("spread_permission") not in {True, False}:
        errors.append("spread_permission must be a bool")
    if permission_state.get("paper_trading_allowed") is not False:
        errors.append("paper_trading_allowed must be false")
    if permission_state.get("manual_execution_allowed") is not False:
        errors.append("manual_execution_allowed must be false")
    if permission_state.get("label_is_report_only") is not True:
        errors.append("permission_state.label_is_report_only must be true")
    if not isinstance(permission_state.get("primary_regime_label"), str):
        errors.append("permission_state.primary_regime_label must be a string")
    if not isinstance(permission_state.get("reason_codes"), list):
        errors.append("permission_state.reason_codes must be a list")
    if not isinstance(permission_state.get("regime_scores"), dict):
        errors.append("permission_state.regime_scores must be a dict")
    if not isinstance(permission_state.get("volatility_inputs"), dict):
        errors.append("permission_state.volatility_inputs must be a dict")
    if not isinstance(permission_state.get("ignored_inputs"), list):
        errors.append("permission_state.ignored_inputs must be a list")
    if not isinstance(permission_state.get("cap_details"), list):
        errors.append("permission_state.cap_details must be a list")

    if permission_state.get("status") == "blocked":
        if float(sell_permission or 0.0) != 0.0:
            errors.append("blocked permission_state must keep sell_permission at 0.0")
        if permission_state.get("naked_permission") is not False:
            errors.append("blocked permission_state must keep naked_permission false")
        if permission_state.get("spread_permission") is not False:
            errors.append("blocked permission_state must keep spread_permission false")
    if float(sell_permission or 0.0) == 0.0:
        if permission_state.get("naked_permission") is not False:
            errors.append("zero sell_permission must keep naked_permission false")
        if permission_state.get("spread_permission") is not False:
            errors.append("zero sell_permission must keep spread_permission false")
    if permission_state.get("naked_permission") is True and permission_state.get("spread_permission") is not True:
        errors.append("naked_permission true requires spread_permission true")

    required_scores = {
        "bear_trend",
        "range",
        "squeeze",
        "slow_bull",
        "fast_bull_breakout",
        "event",
        "volatility_stress",
        "data_quality",
    }
    scores = permission_state.get("regime_scores", {})
    if isinstance(scores, dict):
        missing_scores = required_scores.difference(scores)
        if missing_scores:
            errors.append(
                f"permission_state.regime_scores missing keys: {sorted(missing_scores)}"
            )

    volatility_inputs = permission_state.get("volatility_inputs", {})
    if isinstance(volatility_inputs, dict):
        for key in ("dvol_percentile", "atm_iv_percentile"):
            if key not in volatility_inputs:
                errors.append(f"permission_state.volatility_inputs missing key: {key}")

    cap_details = permission_state.get("cap_details", [])
    if isinstance(cap_details, list):
        for detail in cap_details:
            if not isinstance(detail, dict):
                errors.append("permission_state.cap_details entries must be dicts")
                continue
            for key in ("dimension", "score", "cap", "active", "kill", "reason_codes"):
                if key not in detail:
                    errors.append(f"permission_state.cap_detail missing key: {key}")
            if detail.get("cap") is not None and (
                not isinstance(detail.get("cap"), (int, float))
                or not 0.0 <= float(detail["cap"]) <= 1.0
            ):
                errors.append("permission_state.cap_detail cap must stay in [0.0, 1.0]")
            if not isinstance(detail.get("reason_codes"), list):
                errors.append("permission_state.cap_detail reason_codes must be a list")

    return errors


def _validate_vol_surface_status(vol_surface_status: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(vol_surface_status, dict):
        return ["vol_surface_status must be a dict"]

    if vol_surface_status.get("status") not in {"missing", "blocked", "validated"}:
        errors.append("vol_surface_status.status must be missing, blocked, or validated")
    if vol_surface_status.get("validated") not in {True, False}:
        errors.append("vol_surface_status.validated must be a bool")
    if vol_surface_status.get("fit_model") != "linear_iv_vs_log_moneyness":
        errors.append("vol_surface_status.fit_model must match the supported model")
    if not isinstance(vol_surface_status.get("thresholds"), dict):
        errors.append("vol_surface_status.thresholds must be a dict")
    expiries = vol_surface_status.get("expiries")
    if not isinstance(expiries, list):
        errors.append("vol_surface_status.expiries must be a list")
        return errors

    for expiry in expiries:
        if not isinstance(expiry, dict):
            errors.append("vol_surface_status expiry entries must be dicts")
            continue
        for key in (
            "expiry_date",
            "dte_days",
            "fit_quality_score",
            "fit_quality_pass",
            "no_arb_pass",
            "no_arb_error",
            "candidate_eligible",
            "reason_codes",
            "surface_points",
        ):
            if key not in expiry:
                errors.append(f"vol_surface_status expiry missing key: {key}")
        if not isinstance(expiry.get("surface_points"), list):
            errors.append("vol_surface_status expiry surface_points must be a list")
            continue
        for point in expiry["surface_points"]:
            for key in (
                "instrument_name",
                "expiry_date",
                "strike_price",
                "surface_fitted_iv",
                "model_delta",
                "model_gamma",
                "model_theta",
                "model_vega",
                "risk_neutral_p_itm",
                "greek_consistency",
            ):
                if key not in point:
                    errors.append(f"vol_surface_status surface point missing key: {key}")

    return errors


def _validate_candidate_research(candidate_research: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(candidate_research, dict):
        return ["candidate_research must be a dict"]

    if candidate_research.get("status") not in {"blocked", "validated"}:
        errors.append("candidate_research.status must be blocked or validated")
    if not isinstance(candidate_research.get("filter_thresholds"), dict):
        errors.append("candidate_research.filter_thresholds must be a dict")
    for table_name in ("naked_short_calls", "call_credit_spreads"):
        table = candidate_research.get(table_name)
        if not isinstance(table, dict):
            errors.append(f"{table_name} must be a dict")
            continue
        for bucket in ("eligible", "review", "rejected"):
            if not isinstance(table.get(bucket), list):
                errors.append(f"{table_name}.{bucket} must be a list")
    if not isinstance(candidate_research.get("summary"), dict):
        errors.append("candidate_research.summary must be a dict")
    return errors


def _validate_ev_candidate_scanner(ev_candidate_scanner: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(ev_candidate_scanner, dict):
        return ["ev_candidate_scanner must be a dict"]

    if ev_candidate_scanner.get("status") not in {"blocked", "validated"}:
        errors.append("ev_candidate_scanner.status must be blocked or validated")
    if ev_candidate_scanner.get("score_status") != "UNCALIBRATED_RESEARCH_ONLY":
        errors.append(
            "ev_candidate_scanner.score_status must be UNCALIBRATED_RESEARCH_ONLY"
        )
    for key in (
        "recommended_size_allowed",
        "trade_instruction_allowed",
        "paper_manual_candidates_allowed",
    ):
        if ev_candidate_scanner.get(key) is not False:
            errors.append(f"ev_candidate_scanner.{key} must be false")

    ranked_candidates = ev_candidate_scanner.get("ranked_candidates")
    if not isinstance(ranked_candidates, list):
        errors.append("ev_candidate_scanner.ranked_candidates must be a list")
    else:
        for candidate in ranked_candidates:
            if not isinstance(candidate, dict):
                errors.append("ev_candidate_scanner candidate entries must be dicts")
                continue
            for key in (
                "candidate_id",
                "structure_type",
                "action",
                "score_status",
                "ranking_score",
                "premium_usdc",
                "executable_credit_usdc",
                "fair_value_usdc",
                "ev_after_cost_usdc",
                "fair_iv_diagnostics",
                "path_risk",
                "margin_snapshot",
                "hazard_zone",
                "kill_conditions",
                "reason_codes",
            ):
                if key not in candidate:
                    errors.append(f"ev_candidate_scanner candidate missing key: {key}")
            if candidate.get("action") not in {"RESEARCH_ONLY", "REVIEW", "REJECT"}:
                errors.append("ev_candidate_scanner candidate action must be RESEARCH_ONLY, REVIEW, or REJECT")
            if candidate.get("score_status") != "UNCALIBRATED_RESEARCH_ONLY":
                errors.append("ev_candidate_scanner candidate score_status must stay UNCALIBRATED_RESEARCH_ONLY")
            if not isinstance(candidate.get("kill_conditions"), list):
                errors.append("ev_candidate_scanner candidate kill_conditions must be a list")
            if not isinstance(candidate.get("reason_codes"), list):
                errors.append("ev_candidate_scanner candidate reason_codes must be a list")
            if not isinstance(candidate.get("fair_iv_diagnostics"), dict):
                errors.append("ev_candidate_scanner candidate fair_iv_diagnostics must be a dict")
            if not isinstance(candidate.get("path_risk"), dict):
                errors.append("ev_candidate_scanner candidate path_risk must be a dict")
            if not isinstance(candidate.get("margin_snapshot"), dict):
                errors.append("ev_candidate_scanner candidate margin_snapshot must be a dict")
            if not isinstance(candidate.get("hazard_zone"), dict):
                errors.append("ev_candidate_scanner candidate hazard_zone must be a dict")

    if not isinstance(ev_candidate_scanner.get("summary"), dict):
        errors.append("ev_candidate_scanner.summary must be a dict")
    return errors


def _validate_data_trust(
    data_trust: Any,
    data_status: dict[str, Any],
) -> list[str]:
    if not isinstance(data_trust, dict):
        return ["data_trust must be a dict"]

    errors: list[str] = []
    verdict = data_trust.get("verdict")
    if verdict not in {"trusted", "degraded", "untrusted"}:
        errors.append("data_trust.verdict must be trusted, degraded, or untrusted")

    reason_codes = data_trust.get("reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(code, str) or not code for code in reason_codes
    ):
        errors.append("data_trust.reason_codes must be a list of strings")
    elif verdict in {"degraded", "untrusted"} and not reason_codes:
        errors.append(f"{verdict} data_trust.reason_codes must not be empty")

    source_class = data_trust.get("source_class")
    if source_class not in {"live", "fixture", "replay", "missing"}:
        errors.append(
            "data_trust.source_class must be live, fixture, replay, or missing"
        )

    status = data_status.get("status")
    if status in {"missing", "blocked", "validated"}:
        expected_data_trust = _build_data_trust_summary(data_status)
        if data_trust != expected_data_trust:
            errors.append(
                "data_trust must exactly match canonical projection from data_status "
                f"(expected {expected_data_trust!r})"
            )

    if status == "missing":
        if verdict != "untrusted":
            errors.append(
                "missing market data must have untrusted data_trust.verdict"
            )
        if source_class != "missing":
            errors.append(
                "missing market data must have missing data_trust.source_class"
            )
        if not isinstance(reason_codes, list) or (
            "MISSING_VALIDATED_MARKET_DATA" not in reason_codes
        ):
            errors.append(
                "missing market data trust must include MISSING_VALIDATED_MARKET_DATA"
            )
    elif status in {"blocked", "validated"}:
        if verdict != "untrusted":
            if status == "validated":
                errors.append(
                    "validated market data must remain untrusted until promotion policy exists"
                )
            else:
                errors.append(
                    "blocked market data must have untrusted data_trust.verdict"
                )

        expected_source_class = _data_trust_source_class(data_status)
        if source_class != expected_source_class:
            errors.append(
                f"{status} market data must have {expected_source_class} "
                "data_trust.source_class"
            )

        if status == "validated":
            if not isinstance(reason_codes, list) or (
                "DATA_TRUST_PROMOTION_PENDING" not in reason_codes
            ):
                errors.append(
                    "validated market data trust must include "
                    "DATA_TRUST_PROMOTION_PENDING"
                )
    return errors


def _build_data_trust_summary(data_status: dict[str, Any]) -> dict[str, Any]:
    status = data_status.get("status")
    if status == "missing":
        reason_codes = ["MISSING_VALIDATED_MARKET_DATA"]
    else:
        reason_codes = list(
            (data_status.get("quality_gate") or {}).get("reason_codes") or []
        )
        if status == "validated":
            reason_codes = ["DATA_TRUST_PROMOTION_PENDING"]
        elif not reason_codes:
            reason_codes = [str(data_status.get("reason_code") or "MARKET_DATA_QUALITY_FAIL")]

    # ISSUE-DT-002 owns any promotion of present market data to trusted/degraded.
    return {
        "verdict": "untrusted",
        "reason_codes": _unique_codes(reason_codes),
        "source_class": _data_trust_source_class(data_status),
    }


def _data_trust_source_class(data_status: dict[str, Any]) -> str:
    if data_status.get("status") == "missing":
        return "missing"

    source = str(data_status.get("source") or "").lower()
    if "replay" in source:
        return "replay"
    if source.startswith("deribit_live:"):
        return "live"
    return "fixture"


def _find_forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value).intersection(FORBIDDEN_RESEARCH_ONLY_KEYS)
        for nested in value.values():
            found.update(_find_forbidden_keys(nested))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(_find_forbidden_keys(item))
        return found
    return set()


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
