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
]

API_ROUTES = [
    "GET /health",
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
            "routes": [{"route": route, "status": "available"} for route in API_ROUTES],
            "paper_manual_actions_visible": False,
        },
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
    prerequisites = [
        _gate("data_quality", (report.get("data_status") or {}).get("status") == "validated"),
        _gate("pnl_evidence", (report.get("pnl_evidence") or {}).get("status") == "pass"),
        _gate("vol_surface", (report.get("vol_surface_status") or {}).get("status") == "validated"),
        _gate("portfolio_risk", (report.get("portfolio_risk") or {}).get("schema_version") is not None),
        _gate("position_management", (report.get("position_management") or {}).get("schema_version") is not None),
        _gate("walk_forward_calibration", (report.get("walk_forward_calibration") or {}).get("status") == "validated"),
        _gate("paper_ledger_reconciliation", False),
        _gate("manual_approval_runbook", False),
    ]
    missing = [item["name"] for item in prerequisites if not item["satisfied"]]
    return {
        "status": "GO" if not missing else "NO-GO",
        "paper_mode_allowed": not missing,
        "manual_execution_allowed": False,
        "prerequisites": prerequisites,
        "missing_prerequisites": missing,
    }


def _gate(name: str, satisfied: bool) -> dict[str, Any]:
    return {
        "name": name,
        "satisfied": bool(satisfied),
    }
