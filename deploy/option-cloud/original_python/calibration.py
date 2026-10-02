"""Honest calibration availability for the research-only report."""

from __future__ import annotations

from typing import Any

WALK_FORWARD_CALIBRATION_SCHEMA_VERSION = "walk_forward_calibration_report.v1"
CALIBRATION_NOT_IMPLEMENTED = "CALIBRATION_NOT_IMPLEMENTED"
CALIBRATION_POLICY_DOC = (
    "docs/research/deribit-options-intelligence-platform-prd.md"
)


def build_walk_forward_calibration_report(
    *,
    generated_at: str,
    baseline_backtest: dict[str, Any] | None = None,
    portfolio_risk: dict[str, Any] | None = None,
    position_management: dict[str, Any] | None = None,
    promotion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report that calibration evidence is unavailable.

    The accepted parameters are retained for call-site compatibility. None of
    them is a trained model, fold ledger, or promotion record, so they must not
    be converted into plausible calibration statistics.
    """

    return {
        "schema_version": WALK_FORWARD_CALIBRATION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "not_implemented",
        "evidence_class": "unavailable",
        "reason_code": CALIBRATION_NOT_IMPLEMENTED,
        "policy_doc": CALIBRATION_POLICY_DOC,
        "model_registry": {
            "status": "unavailable",
            "model_version": None,
            "artifact_id": None,
            "promotion_status": "not_implemented",
            "promoted_for_sizing": False,
            "blocking_reasons": [CALIBRATION_NOT_IMPLEMENTED],
        },
        "comparison_status": {
            "status": "unavailable",
            "reason_code": CALIBRATION_NOT_IMPLEMENTED,
            "metrics_source": None,
            "artifact_id": None,
        },
        "system_comparison": [],
        "slow_bull_acute_rally_windows": [],
        "paper_manual_release_gated": True,
    }


def validate_walk_forward_calibration_report(report: Any) -> list[str]:
    """Validate the honest unavailable-calibration contract."""

    if not isinstance(report, dict):
        return ["walk_forward_calibration must be a dict"]

    errors: list[str] = []
    if report.get("schema_version") != WALK_FORWARD_CALIBRATION_SCHEMA_VERSION:
        errors.append(
            "walk_forward_calibration.schema_version must be "
            "walk_forward_calibration_report.v1"
        )
    if report.get("status") != "not_implemented":
        errors.append("walk_forward_calibration.status must be not_implemented")
    if report.get("evidence_class") != "unavailable":
        errors.append("walk_forward_calibration.evidence_class must be unavailable")
    if report.get("reason_code") != CALIBRATION_NOT_IMPLEMENTED:
        errors.append(
            "walk_forward_calibration.reason_code must be "
            "CALIBRATION_NOT_IMPLEMENTED"
        )
    if report.get("system_comparison") != []:
        errors.append("unimplemented calibration must not expose comparison rows")
    if report.get("slow_bull_acute_rally_windows") != []:
        errors.append("unimplemented calibration must not expose rally windows")

    registry = report.get("model_registry")
    if not isinstance(registry, dict):
        errors.append("walk_forward_calibration.model_registry must be a dict")
        registry = {}
    if registry.get("status") != "unavailable":
        errors.append("calibration model registry must be unavailable")
    if registry.get("model_version") is not None:
        errors.append("unimplemented calibration must not name a model version")
    if registry.get("artifact_id") is not None:
        errors.append("unimplemented calibration must not name a model artifact")
    if registry.get("promotion_status") != "not_implemented":
        errors.append(
            "calibration model registry promotion status must be not_implemented"
        )
    if registry.get("promoted_for_sizing") is not False:
        errors.append("unimplemented calibration must not be promoted for sizing")
    if registry.get("blocking_reasons") != [CALIBRATION_NOT_IMPLEMENTED]:
        errors.append(
            "calibration model registry must remain blocked by "
            "CALIBRATION_NOT_IMPLEMENTED"
        )

    comparison = report.get("comparison_status")
    if not isinstance(comparison, dict):
        errors.append("walk_forward_calibration.comparison_status must be a dict")
        comparison = {}
    if comparison.get("status") != "unavailable":
        errors.append("unimplemented calibration comparison must be unavailable")
    if comparison.get("reason_code") != CALIBRATION_NOT_IMPLEMENTED:
        errors.append(
            "unimplemented calibration comparison must remain blocked by "
            "CALIBRATION_NOT_IMPLEMENTED"
        )
    if comparison.get("metrics_source") is not None:
        errors.append("unimplemented calibration must not name a metrics source")
    if comparison.get("artifact_id") is not None:
        errors.append("unimplemented calibration comparison must not name an artifact")
    if report.get("paper_manual_release_gated") is not True:
        errors.append("unimplemented calibration must keep paper/manual release gated")
    return errors
