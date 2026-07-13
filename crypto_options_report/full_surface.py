"""CLI/API/dashboard surface descriptors for ISSUE-014."""

from __future__ import annotations

from typing import Any

FULL_SYSTEM_SURFACE_SCHEMA_VERSION = "full_system_surface_report.v1"

CLI_COMMANDS = [
    "ingest",
    "ingestion-status",
    "fit-surface",
    "surface-status",
    "build-features",
    "feature-status",
    "backtest",
    "calibrate",
    "scan",
    "recommend",
    "pull-snapshot",
    "alert-eval",
]

# Trading remains a first-class product spine but lower priority and fail-closed.
TRADING_SPINE_STATUS = {
    "paper_mode": "NO-GO",
    "manual_execution": "NO-GO",
    "live_order_adapter": "not_implemented",
    "priority": "lower_than_analysis_and_alerts",
    "unlock_policy": "external_definition_of_done_required",
}

API_ROUTES = [
    "GET /health",
    "GET /livez",
    "GET /readyz",
    "GET /research/report",
    "GET /dashboard.html",
    "GET /dashboard",
    "GET /market/chain",
    "GET /surface",
    "GET /regime",
    "GET /account/risk",
    "GET /portfolio/risk",
    "GET /candidates",
    "GET /recommendation",
    "POST /backtest/run",
    "GET /backtest/report/default",
]

DASHBOARD_VIEWS = [
    "today_overview",
    "vol_surface",
    "regime",
    "candidate_ranking",
    "portfolio_risk",
    "backtest",
    "data_quality",
]


def build_full_system_surface_report(
    *,
    generated_at: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    readiness = _release_readiness(report)
    return {
        "schema_version": FULL_SYSTEM_SURFACE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "cli": {
            "commands": [{"name": name, "status": "available"} for name in CLI_COMMANDS],
            "paper_manual_actions_visible": False,
        },
        "api": {
            "routes": [
                {
                    "route": route,
                    "status": (
                        "not_implemented"
                        if route == "POST /backtest/run"
                        else "available"
                    ),
                }
                for route in API_ROUTES
            ],
            "paper_manual_actions_visible": False,
        },
        "alerts": {
            "status": "available",
            "surface": "cli alert-eval",
            "default_policy": "risk_degradation_only",
            "opportunity_alerts_default": False,
            "automatic_live_submission_possible": False,
        },
        "trading_spine": dict(TRADING_SPINE_STATUS),
        "dashboard": {
            "views": [
                {
                    "name": name,
                    "status": "available",
                    "shared_schema_keys": _view_keys(name),
                }
                for name in DASHBOARD_VIEWS
            ],
            "paper_manual_actions_visible": False,
        },
        "shared_schema_projection": {
            "schema_version": report.get("schema_version"),
            "action": report.get("action"),
            "risk_state": report.get("risk_state"),
            "reason_codes": report.get("reason_codes"),
            "calibration_status": report.get("calibration_status"),
            "mode_gate": report.get("mode_gate"),
            "portfolio_final_action": (report.get("portfolio_risk") or {}).get("final_action"),
        },
        "backtest_comparison": (report.get("walk_forward_calibration") or {}).get("system_comparison", []),
        "release_readiness": readiness,
    }


def build_recommendation_projection(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "recommendation_projection.v1",
        "action": report.get("action"),
        "confidence": report.get("confidence"),
        "risk_state": report.get("risk_state"),
        "permission_state": report.get("permission_state"),
        "reason_codes": report.get("reason_codes"),
        "portfolio_risk": report.get("portfolio_risk"),
        "mode_gate": report.get("mode_gate"),
        "paper_manual_actions_visible": False,
    }


def validate_full_system_surface_report(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["full_system_surface must be a dict"]
    if report.get("schema_version") != FULL_SYSTEM_SURFACE_SCHEMA_VERSION:
        errors.append("full_system_surface.schema_version must be full_system_surface_report.v1")
    commands = {item.get("name") for item in (report.get("cli") or {}).get("commands", [])}
    if commands != set(CLI_COMMANDS):
        errors.append("full_system_surface.cli.commands must include the full command set")
    routes = {item.get("route") for item in (report.get("api") or {}).get("routes", [])}
    if routes != set(API_ROUTES):
        errors.append("full_system_surface.api.routes must include the full route set")
    views = {item.get("name") for item in (report.get("dashboard") or {}).get("views", [])}
    if views != set(DASHBOARD_VIEWS):
        errors.append("full_system_surface.dashboard.views must include all required views")
    for surface_name in ("cli", "api", "dashboard"):
        if (report.get(surface_name) or {}).get("paper_manual_actions_visible") is not False:
            errors.append(f"full_system_surface.{surface_name} must hide paper/manual actions")
    readiness = report.get("release_readiness") or {}
    if readiness.get("status") not in {"GO", "NO-GO"}:
        errors.append("full_system_surface.release_readiness.status must be GO or NO-GO")
    prerequisites = readiness.get("prerequisites") or []
    missing = [
        item.get("name")
        for item in prerequisites
        if item.get("satisfied") is not True
    ]
    if readiness.get("missing_prerequisites") != missing:
        errors.append("release_readiness missing_prerequisites must match unsatisfied gates")
    expected_status = "GO" if not missing else "NO-GO"
    if readiness.get("status") != expected_status:
        errors.append("release_readiness status must match prerequisite states")
    for item in prerequisites:
        required = {
            "name",
            "satisfied",
            "evidence_state",
            "release_state",
            "evidence_class",
            "release_blocking",
            "reason_codes",
        }
        if not required.issubset(item):
            errors.append("release readiness gate is missing evidence-state fields")
            continue
        if item.get("evidence_state") not in {
            "not_configured",
            "not_run",
            "verified_local",
            "blocked",
            "invalid",
        }:
            errors.append("release readiness gate evidence_state is invalid")
        if item.get("release_state") not in {
            "not_ready",
            "awaiting_external",
            "awaiting_calendar",
            "ready",
        }:
            errors.append("release readiness gate release_state is invalid")
        satisfied = item.get("satisfied")
        if not isinstance(satisfied, bool):
            errors.append("release readiness gate satisfied must be a bool")
        expected_blocking = satisfied is not True
        if item.get("release_blocking") is not expected_blocking:
            errors.append("release readiness gate blocking flag must invert satisfied")
        reason_codes = item.get("reason_codes")
        if not isinstance(reason_codes, list):
            errors.append("release readiness gate reason_codes must be a list")
        if satisfied is True:
            if item.get("release_state") != "ready":
                errors.append("satisfied release readiness gate must be ready")
            if item.get("evidence_state") != "verified_local":
                errors.append(
                    "satisfied release readiness gate must have verified local evidence"
                )
            if isinstance(reason_codes, list) and reason_codes:
                errors.append(
                    "satisfied release readiness gate must not retain blocking reasons"
                )
        else:
            if item.get("release_state") == "ready":
                errors.append("unsatisfied release readiness gate must not be ready")
            if isinstance(reason_codes, list) and not reason_codes:
                errors.append(
                    "unsatisfied release readiness gate must include blocking reasons"
                )
    return errors


def _view_keys(name: str) -> list[str]:
    return {
        "today_overview": ["risk_state", "permission_state", "reason_codes", "mode_gate"],
        "vol_surface": ["vol_surface_status"],
        "regime": ["permission_state"],
        "candidate_ranking": ["candidate_research", "ev_candidate_scanner"],
        "portfolio_risk": ["account_status", "portfolio_risk", "position_management"],
        "backtest": ["backtest_status", "walk_forward_calibration"],
        "data_quality": ["data_status"],
    }[name]


def _release_readiness(report: dict[str, Any]) -> dict[str, Any]:
    data_status = report.get("data_status") or {}
    data_trust = report.get("data_trust") or {}
    account_status = report.get("account_status") or {}
    calibration = report.get("walk_forward_calibration") or {}
    paper_ledger = report.get("paper_proposal_ledger") or {}
    feed_coverage = data_status.get("feed_coverage") or {}
    private_contract = account_status.get("private_adapter_contract") or {}
    model_registry = calibration.get("model_registry") or {}
    persistence = paper_ledger.get("persistence") or {}
    source_class = str(data_trust.get("source_class") or "missing")
    data_present = data_status.get("status") == "validated"
    data_release_ready = data_present and data_trust.get("verdict") == "trusted"
    data_evidence_state = (
        "not_configured"
        if data_status.get("status") == "missing"
        else "blocked"
        if data_status.get("status") == "blocked"
        else "verified_local"
    )
    data_reason_codes = list(data_trust.get("reason_codes") or [])

    response_contract = data_status.get("public_response_contract") or {}
    response_present = bool(response_contract)
    response_release_ready = (
        response_present
        and response_contract.get("overall_status") == "pass"
        and source_class == "live"
        and data_release_ready
    )
    feed_complete = bool(feed_coverage) and not feed_coverage.get("missing_feeds")
    feed_release_ready = feed_complete and data_release_ready

    private_replay = (
        private_contract.get("auth_safe") is True
        and private_contract.get("replay_fixture") is True
        and private_contract.get("live_order_submission_possible") is False
    )
    private_live = (
        private_contract.get("auth_safe") is True
        and private_contract.get("replay_fixture") is False
        and account_status.get("live_snapshot") is True
        and account_status.get("status") == "available"
        and private_contract.get("live_order_submission_possible") is False
    )
    portfolio_ready = (
        private_live
        and data_release_ready
        and (report.get("portfolio_risk") or {}).get("final_action") != "halt_system"
    )
    position_ready = (
        portfolio_ready
        and (report.get("position_management") or {}).get("schema_version") is not None
    )
    model_promoted = model_registry.get("promoted_for_sizing") is True
    calibration_local = calibration.get("status") == "research_fixture"
    calibration_ready = calibration.get("status") == "validated" and model_promoted
    persistence_ready = persistence.get("mode") == "persistent_json"

    prerequisites = [
        _gate(
            "data_quality",
            data_release_ready,
            evidence_state=data_evidence_state,
            release_state=(
                "ready"
                if data_release_ready
                else "awaiting_external"
                if data_present
                else "not_ready"
            ),
            evidence_class=source_class,
            reason_codes=data_reason_codes,
        ),
        _gate(
            "public_response_contract",
            response_release_ready,
            evidence_state="verified_local" if response_present else "not_configured",
            release_state=(
                "ready"
                if response_release_ready
                else "awaiting_external"
                if response_present
                else "not_ready"
            ),
            evidence_class=source_class if response_present else None,
            reason_codes=(
                []
                if response_release_ready
                else ["PUBLIC_RESPONSE_PRODUCTION_EVIDENCE_PENDING"]
                if response_present
                else ["MISSING_PUBLIC_RESPONSE_CONTRACT"]
            ),
        ),
        _gate(
            "public_feed_graph_complete",
            feed_release_ready,
            evidence_state=(
                "verified_local" if feed_complete else "blocked" if feed_coverage else "not_configured"
            ),
            release_state="ready" if feed_release_ready else "awaiting_external" if feed_coverage else "not_ready",
            evidence_class=source_class if feed_coverage else None,
            reason_codes=(
                []
                if feed_release_ready
                else list(feed_coverage.get("missing_feeds") or ["PUBLIC_FEED_TRUST_PENDING"])
            ),
        ),
        _gate(
            "pnl_evidence",
            (report.get("pnl_evidence") or {}).get("status") == "pass",
            evidence_state="verified_local",
            release_state="ready",
            evidence_class="deterministic_unit_evidence",
            reason_codes=[],
        ),
        _gate(
            "vol_surface",
            (report.get("vol_surface_status") or {}).get("status") == "validated"
            and data_release_ready,
            evidence_state=(
                "verified_local"
                if (report.get("vol_surface_status") or {}).get("status") == "validated"
                else "blocked"
            ),
            release_state=(
                "ready"
                if (report.get("vol_surface_status") or {}).get("status") == "validated"
                and data_release_ready
                else "awaiting_external"
                if (report.get("vol_surface_status") or {}).get("status") == "validated"
                else "not_ready"
            ),
            evidence_class=source_class,
            reason_codes=(
                []
                if (report.get("vol_surface_status") or {}).get("status") == "validated"
                and data_release_ready
                else [
                    str(
                        (report.get("vol_surface_status") or {}).get("reason_code")
                        or "VOL_SURFACE_TRUST_PROMOTION_PENDING"
                    )
                ]
            ),
        ),
        _gate(
            "private_account_replay_contract",
            private_live,
            evidence_state=(
                "verified_local" if private_replay else "verified_local" if private_live else "not_configured"
            ),
            release_state="ready" if private_live else "awaiting_external" if private_replay else "not_ready",
            evidence_class="live_read_only" if private_live else "sanitized_replay" if private_replay else None,
            reason_codes=[] if private_live else ["MISSING_LIVE_PRIVATE_ACCOUNT_EVIDENCE"],
        ),
        _gate(
            "portfolio_risk",
            portfolio_ready,
            evidence_state="verified_local" if (report.get("portfolio_risk") or {}).get("schema_version") else "not_run",
            release_state="ready" if portfolio_ready else "awaiting_external",
            evidence_class="runtime_projection",
            reason_codes=[] if portfolio_ready else ["PORTFOLIO_RELEASE_INPUTS_NOT_READY"],
        ),
        _gate(
            "position_management",
            position_ready,
            evidence_state="verified_local" if (report.get("position_management") or {}).get("schema_version") else "not_run",
            release_state="ready" if position_ready else "awaiting_external",
            evidence_class="runtime_projection",
            reason_codes=[] if position_ready else ["POSITION_RELEASE_INPUTS_NOT_READY"],
        ),
        _gate(
            "walk_forward_calibration",
            calibration_ready,
            evidence_state="verified_local" if calibration_local or calibration_ready else "not_run",
            release_state="ready" if calibration_ready else "awaiting_external" if calibration_local else "not_ready",
            evidence_class=calibration.get("evidence_class"),
            reason_codes=[] if calibration_ready else list(model_registry.get("blocking_reasons") or ["MISSING_CALIBRATION_EVIDENCE"]),
        ),
        _gate(
            "calibration_model_promoted",
            model_promoted,
            evidence_state="verified_local" if model_registry else "not_configured",
            release_state="ready" if model_promoted else "awaiting_external" if model_registry else "not_ready",
            evidence_class="calibration_model_registry" if model_registry else None,
            reason_codes=[] if model_promoted else list(model_registry.get("blocking_reasons") or ["MISSING_PROMOTED_MODEL"]),
        ),
        _gate(
            "paper_ledger_persistence",
            persistence_ready,
            evidence_state="verified_local" if persistence_ready else "not_configured",
            release_state="ready" if persistence_ready else "not_ready",
            evidence_class=str(persistence.get("mode") or "ephemeral_memory"),
            reason_codes=[] if persistence_ready else ["MISSING_PERSISTENT_PAPER_LEDGER"],
        ),
        _gate(
            "paper_ledger_reconciliation",
            False,
            evidence_state="not_run",
            release_state="awaiting_calendar",
            evidence_class="30_to_60_day_observation",
            reason_codes=["MISSING_30_60_DAY_RECONCILIATION"],
        ),
        _gate(
            "manual_approval_runbook",
            False,
            evidence_state="not_configured",
            release_state="not_ready",
            evidence_class=None,
            reason_codes=["MISSING_MANUAL_APPROVAL_RUNBOOK"],
        ),
    ]
    missing = [item["name"] for item in prerequisites if not item["satisfied"]]
    return {
        "status": "GO" if not missing else "NO-GO",
        "paper_mode_allowed": not missing,
        "manual_execution_allowed": False,
        "prerequisites": prerequisites,
        "missing_prerequisites": missing,
        "blocking_prerequisites": missing,
        "evidence_summary": {
            state: sum(item["evidence_state"] == state for item in prerequisites)
            for state in (
                "not_configured",
                "not_run",
                "verified_local",
                "blocked",
                "invalid",
            )
        },
    }


def _gate(
    name: str,
    satisfied: bool,
    *,
    evidence_state: str,
    release_state: str,
    evidence_class: str | None,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "satisfied": bool(satisfied),
        "evidence_state": evidence_state,
        "release_state": release_state,
        "evidence_class": evidence_class,
        "release_blocking": not bool(satisfied),
        "reason_codes": [str(code) for code in reason_codes],
    }
