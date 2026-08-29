"""CLI/API/dashboard surface descriptors for ISSUE-014."""

from __future__ import annotations

from typing import Any

FULL_SYSTEM_SURFACE_SCHEMA_VERSION = "full_system_surface_report.v1"

CLI_COMMANDS = [
    "analysis",
    "demo",
    "report",
    "ingest",
    "ingestion-status",
    "fit-surface",
    "surface-status",
    "build-features",
    "feature-status",
    "baseline-backtest",
    "backtest",
    "path-risk",
    "validate-signal",
    "ev-robustness",
    "series-history",
    "calibrate",
    "scan",
    "recommend",
    "pull-snapshot",
    "alert-eval",
    "publish",
    "dashboard",
]

# These are capability declarations, not runtime probes or release evidence.
TRADING_SPINE_STATUS = {
    "paper_mode": "unsupported",
    "manual_execution": "unsupported",
    "live_order_adapter": "not_implemented",
    "priority": "lower_than_analysis_and_alerts",
    "unlock_policy": "external_definition_of_done_required",
}

API_ROUTES = [
    "GET /health",
    "GET /livez",
    "GET /readyz",
    "GET /analysis/result",
    "GET /research/report",
    "GET /dashboard.html",
    "GET /evidence",
    "GET /dashboard",
    "GET /market/chain",
    "GET /surface",
    "GET /regime",
    "GET /account/risk",
    "GET /portfolio/risk",
    "GET /candidates",
    "GET /recommendation",
    "GET /research/signal",
    "GET /research/series",
    "POST /backtest/run",
    "GET /backtest/jobs/{id}",
    "GET /backtest/jobs/{id}/result",
    "DELETE /backtest/jobs/{id}",
    "GET /backtest/report/default",
    "GET /backtest/report/{id}",
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

_EXTERNAL_RELEASE_GATE_NAME = "external_release_authorization"
_RESEARCH_PUBLICATION_GATE_NAME = "research_publication"
_EXECUTION_AUTHORIZATION_GATE_NAME = "execution_authorization"
_EXTERNAL_RELEASE_REASON = "EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED"
_RESEARCH_PUBLICATION_REASON = "RESEARCH_PUBLICATION_EVIDENCE_INCOMPLETE"
_EXECUTION_BOUNDARY_REASON = "EXECUTION_DISABLED_BY_PRODUCT_DEFINITION"

_PUBLICATION_EVIDENCE_REQUIREMENTS = {
    "data_quality": {"trusted", "validated"},
    "publish_manifest": {"verified"},
    "methodology": {"present"},
    "disclaimer": {"present"},
}


def build_full_system_surface_report(
    *,
    generated_at: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": FULL_SYSTEM_SURFACE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "declared_not_probed",
        "cli": {
            "commands": [
                {"name": name, "status": "declared_not_probed"}
                for name in CLI_COMMANDS
            ],
            "paper_manual_actions_visible": False,
        },
        "api": {
            "routes": [
                {"route": route, "status": "declared_not_probed"}
                for route in API_ROUTES
            ],
            "paper_manual_actions_visible": False,
        },
        "alerts": {
            "status": "declared_not_probed",
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
                    "status": "declared_not_probed",
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
            "portfolio_final_action": (report.get("portfolio_risk") or {}).get(
                "final_action"
            ),
        },
        "backtest_comparison": (report.get("walk_forward_calibration") or {}).get(
            "system_comparison", []
        ),
        "release_readiness": _release_readiness(),
        # Append-only public-product projection. The legacy key above remains
        # byte-for-byte compatible for existing local/extension consumers.
        "release_gates": build_release_gates(),
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
        errors.append(
            "full_system_surface.schema_version must be full_system_surface_report.v1"
        )
    if report.get("status") != "declared_not_probed":
        errors.append("full_system_surface.status must be declared_not_probed")

    cli = _surface_section(report, "cli", errors)
    api = _surface_section(report, "api", errors)
    dashboard = _surface_section(report, "dashboard", errors)
    alerts = _surface_section(report, "alerts", errors)
    readiness = _surface_section(report, "release_readiness", errors)

    command_items, commands = _declared_items(
        cli,
        path="full_system_surface.cli.commands",
        key="commands",
        identity_field="name",
        errors=errors,
    )
    if commands != set(CLI_COMMANDS):
        errors.append("full_system_surface.cli.commands must include the full command set")
    route_items, routes = _declared_items(
        api,
        path="full_system_surface.api.routes",
        key="routes",
        identity_field="route",
        errors=errors,
    )
    if routes != set(API_ROUTES):
        errors.append("full_system_surface.api.routes must include the full route set")
    view_items, views = _declared_items(
        dashboard,
        path="full_system_surface.dashboard.views",
        key="views",
        identity_field="name",
        errors=errors,
    )
    if views != set(DASHBOARD_VIEWS):
        errors.append("full_system_surface.dashboard.views must include all required views")
    declared_items = command_items + route_items + view_items
    if any(item.get("status") != "declared_not_probed" for item in declared_items):
        errors.append("static full-system surfaces must remain declared_not_probed")
    if alerts.get("status") != "declared_not_probed":
        errors.append("static alert surface must remain declared_not_probed")
    for surface_name, section in (("cli", cli), ("api", api), ("dashboard", dashboard)):
        if section.get("paper_manual_actions_visible") is not False:
            errors.append(f"full_system_surface.{surface_name} must hide paper/manual actions")

    if readiness.get("status") != "NO-GO":
        errors.append("runtime release readiness must remain NO-GO")
    if readiness.get("paper_mode_allowed") is not False:
        errors.append("runtime release readiness must not allow paper mode")
    if readiness.get("manual_execution_allowed") is not False:
        errors.append("runtime release readiness must not allow manual execution")
    prerequisites = readiness.get("prerequisites")
    if not isinstance(prerequisites, list):
        errors.append("release_readiness.prerequisites must be a list")
        prerequisites = []
    gate_names = [
        item.get("name") for item in prerequisites if isinstance(item, dict)
    ]
    if gate_names != [_EXTERNAL_RELEASE_GATE_NAME] or len(prerequisites) != 1:
        errors.append(
            "release readiness must contain only external release authorization"
        )
    missing = [
        item.get("name")
        for item in prerequisites
        if isinstance(item, dict) and item.get("satisfied") is not True
    ]
    if readiness.get("missing_prerequisites") != missing:
        errors.append(
            "release_readiness missing_prerequisites must match unsatisfied gates"
        )
    if readiness.get("blocking_prerequisites") != missing:
        errors.append(
            "release_readiness blocking_prerequisites must match unsatisfied gates"
        )

    for item in prerequisites:
        if not isinstance(item, dict):
            errors.append("release readiness gate must be a dict")
            continue
        required = {
            "name",
            "satisfied",
            "evidence_state",
            "release_state",
            "evidence_class",
            "release_blocking",
            "reason_codes",
            "owner",
            "action",
            "root_cause",
        }
        if not required.issubset(item):
            errors.append("release readiness gate is missing evidence-state fields")
            continue
        if item.get("name") == _EXTERNAL_RELEASE_GATE_NAME and item.get(
            "satisfied"
        ) is not False:
            errors.append("runtime report cannot satisfy external release authorization")
        if item.get("evidence_state") != "not_configured":
            errors.append("external release authorization is not runtime evidence")
        if item.get("release_state") != "awaiting_external":
            if item.get("satisfied") is not True:
                errors.append("unsatisfied release readiness gate must not be ready")
            errors.append("external release authorization must await external evidence")
        if item.get("evidence_class") != "manual_external_authorization":
            errors.append("external release authorization evidence class is invalid")
        if item.get("release_blocking") is not True:
            errors.append("external release authorization must remain release blocking")
        if item.get("reason_codes") != [_EXTERNAL_RELEASE_REASON]:
            errors.append("external release authorization reason is invalid")
        if item.get("owner") != "external_operator":
            errors.append("external release authorization owner is invalid")
        if not isinstance(item.get("action"), str) or not item.get("action"):
            errors.append("release readiness gate action must be a non-empty string")
        if item.get("root_cause") != _EXTERNAL_RELEASE_REASON:
            errors.append("external release authorization root cause is invalid")
    _validate_release_gates(report.get("release_gates"), errors)
    return errors


def _surface_section(
    report: dict[str, Any],
    key: str,
    errors: list[str],
) -> dict[str, Any]:
    section = report.get(key)
    if not isinstance(section, dict):
        errors.append(f"full_system_surface.{key} must be a dict")
        return {}
    return section


def _declared_items(
    section: dict[str, Any],
    *,
    path: str,
    key: str,
    identity_field: str,
    errors: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    raw_items = section.get(key)
    if not isinstance(raw_items, list):
        errors.append(f"{path} must be a list")
        return [], set()

    items: list[dict[str, Any]] = []
    identities: set[str] = set()
    saw_non_dict = False
    for item in raw_items:
        if not isinstance(item, dict):
            saw_non_dict = True
            continue
        items.append(item)
        identity = item.get(identity_field)
        if isinstance(identity, str):
            identities.add(identity)
    if saw_non_dict:
        errors.append(f"{path} entries must be dicts")
    return items, identities


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


def _release_readiness() -> dict[str, Any]:
    gate = {
        "name": _EXTERNAL_RELEASE_GATE_NAME,
        "satisfied": False,
        "evidence_state": "not_configured",
        "release_state": "awaiting_external",
        "evidence_class": "manual_external_authorization",
        "release_blocking": True,
        "reason_codes": [_EXTERNAL_RELEASE_REASON],
        "owner": "external_operator",
        "action": (
            "Obtain separately authorized manual/external release evidence; "
            "this research runtime cannot grant it."
        ),
        "root_cause": _EXTERNAL_RELEASE_REASON,
    }
    return {
        "status": "NO-GO",
        "paper_mode_allowed": False,
        "manual_execution_allowed": False,
        "prerequisites": [gate],
        "missing_prerequisites": [_EXTERNAL_RELEASE_GATE_NAME],
        "blocking_prerequisites": [_EXTERNAL_RELEASE_GATE_NAME],
    }


def build_release_gates(
    *,
    research_publication_ready: bool = False,
    publication_evidence: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Separate a publishable research edition from executable authority.

    Publication may become ready only from explicit, inspectable evidence.
    Execution has no input because it is a product boundary, not a deploy-time
    setting. Keeping that omission in the function signature makes attempts to
    configure execution fail before any report can be produced.
    """
    evidence = dict(publication_evidence or {})
    missing = [
        name
        for name, accepted in _PUBLICATION_EVIDENCE_REQUIREMENTS.items()
        if evidence.get(name) not in accepted
    ]
    publication_ready = bool(research_publication_ready and not missing)
    publication = {
        "name": _RESEARCH_PUBLICATION_GATE_NAME,
        "status": "GO" if publication_ready else "NO-GO",
        "satisfied": publication_ready,
        "evidence_state": "verified" if publication_ready else "incomplete",
        "evidence_class": "published_research_manifest",
        "reason_codes": [] if publication_ready else [_RESEARCH_PUBLICATION_REASON],
        "missing_prerequisites": missing,
        "publication_evidence": evidence,
        "owner": "research_team",
        "execution_allowed": False,
    }
    execution = {
        "name": _EXECUTION_AUTHORIZATION_GATE_NAME,
        "status": "NO-GO",
        "satisfied": False,
        "evidence_state": "product_boundary",
        "evidence_class": "hard_coded_product_boundary",
        "reason_codes": [_EXECUTION_BOUNDARY_REASON],
        "owner": "system",
        "configurable": False,
        "execution_allowed": False,
    }
    return [publication, execution]


def _validate_release_gates(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("full_system_surface.release_gates must be a list")
        return
    gates = {
        gate.get("name"): gate
        for gate in value
        if isinstance(gate, dict) and isinstance(gate.get("name"), str)
    }
    if set(gates) != {
        _RESEARCH_PUBLICATION_GATE_NAME,
        _EXECUTION_AUTHORIZATION_GATE_NAME,
    } or len(value) != 2:
        errors.append("release_gates must contain publication and execution gates")
        return
    publication = gates[_RESEARCH_PUBLICATION_GATE_NAME]
    publication_ready = publication.get("satisfied") is True
    if publication.get("status") != ("GO" if publication_ready else "NO-GO"):
        errors.append("research publication status must match its evidence state")
    if publication.get("execution_allowed") is not False:
        errors.append("research publication must not authorize execution")
    publication_evidence = publication.get("publication_evidence")
    if not isinstance(publication_evidence, dict):
        publication_evidence = {}
    missing_evidence = [
        name
        for name, accepted in _PUBLICATION_EVIDENCE_REQUIREMENTS.items()
        if publication_evidence.get(name) not in accepted
    ]
    if set(publication.get("missing_prerequisites") or []) != set(missing_evidence):
        errors.append("research publication missing prerequisites are inconsistent")
    if publication_ready and missing_evidence:
        errors.append("research publication GO requires complete evidence")
    if publication_ready and (
        publication.get("evidence_state") != "verified"
        or publication.get("reason_codes") != []
    ):
        errors.append("research publication GO must declare verified evidence")

    execution = gates[_EXECUTION_AUTHORIZATION_GATE_NAME]
    if execution.get("status") != "NO-GO" or execution.get("satisfied") is not False:
        errors.append("execution authorization must remain NO-GO")
    if execution.get("execution_allowed") is not False:
        errors.append("execution authorization must not allow execution")
    if execution.get("configurable") is not False:
        errors.append("execution authorization must be non-configurable")
    if execution.get("reason_codes") != [_EXECUTION_BOUNDARY_REASON]:
        errors.append("execution authorization reason is invalid")
