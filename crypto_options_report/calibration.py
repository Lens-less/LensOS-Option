"""Walk-forward calibration and full-system comparison tracer for ISSUE-013."""

from __future__ import annotations

from math import isfinite
from typing import Any

WALK_FORWARD_CALIBRATION_SCHEMA_VERSION = "walk_forward_calibration_report.v1"
PERFORMANCE_METRIC_FIELDS = {
    "calmar",
    "max_drawdown",
    "cvar_99",
    "touch_rate",
    "forced_exit_count",
    "margin_breach_count",
    "premium_to_cvar",
    "recovery_days",
}


def build_walk_forward_calibration_report(
    *,
    generated_at: str,
    baseline_backtest: dict[str, Any] | None = None,
    portfolio_risk: dict[str, Any] | None = None,
    position_management: dict[str, Any] | None = None,
    promotion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic no-leakage calibration evidence report."""

    model_registry = _model_registry(promotion_evidence or {})
    comparison_status = {
        "status": "not_run" if baseline_backtest is None else "insufficient_evidence",
        "reason_code": (
            "BACKTEST_NOT_RUN"
            if baseline_backtest is None
            else "BACKTEST_LEDGER_EVIDENCE_REQUIRED"
        ),
        "metrics_source": None,
        "artifact_id": None,
    }
    return {
        "schema_version": WALK_FORWARD_CALIBRATION_SCHEMA_VERSION,
        "generated_at": generated_at,
        # Deterministic tracer only — not out-of-sample production calibration.
        "status": "research_fixture",
        "evidence_class": "deterministic_research_fixture",
        "split_policy": {
            "training_window_months": 24,
            "test_window_months": 3,
            "embargo_days": 35,
            "max_dte_embargo": True,
            "purge_overlapping_labels": True,
            "recalibration_cadence": "monthly",
        },
        "feature_standardization": {
            "method": "robust_z_score",
            "reference_scope": "training_only",
            "separate_buckets": ["currency", "structure", "dte_bucket", "delta_bucket"],
            "future_data_used": False,
        },
        "targets": {
            "realized_utility": "realized_pnl_after_cost / max(initial_margin, stress_loss)",
            "adverse_event": "mark_loss_gt_2x_credit_or_delta_gt_0p35_or_forced_exit",
        },
        "collinearity": {
            "ev_vrp_correlation": 0.84,
            "ev_vrp_vif": 4.76,
            "action": "residualize_vrp",
            "vrp_role": "diagnostic_tiebreaker",
        },
        "score": {
            "status": "research_fixture_uncalibrated",
            "model_version": "walk_forward_fixture_v1",
            "expected_utility": 0.42,
            "adverse_probability": 0.18,
            "lambda_adverse": 0.65,
            "raw_score": 0.303,
            "train_distribution_percentile": 78.0,
            "score": 78.0,
            "decision_bucket": "trade_half_or_spread",
        },
        "model_registry": model_registry,
        "comparison_status": comparison_status,
        # Performance rows must come from an immutable backtest ledger.  The
        # deterministic calibration fixture does not contain that evidence.
        "system_comparison": [],
        "slow_bull_acute_rally_windows": [],
        "leakage_checks": [
            {
                "surface": "standardization",
                "future_data_used": False,
                "evidence": "Robust z references are fit only on training folds.",
            },
            {
                "surface": "feature_generation",
                "future_data_used": False,
                "evidence": "Features are timestamped before label horizon starts.",
            },
            {
                "surface": "label_construction",
                "future_data_used": False,
                "evidence": "Embargo and overlapping-label purge remove lookahead contamination.",
            },
        ],
        "paper_manual_release_gated": True,
    }


def validate_walk_forward_calibration_report(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["walk_forward_calibration must be a dict"]
    if report.get("schema_version") != WALK_FORWARD_CALIBRATION_SCHEMA_VERSION:
        errors.append("walk_forward_calibration.schema_version must be walk_forward_calibration_report.v1")
    split = report.get("split_policy") or {}
    if split.get("training_window_months") != 24:
        errors.append("walk_forward_calibration training window must be 24 months")
    if split.get("test_window_months") != 3:
        errors.append("walk_forward_calibration test window must be 3 months")
    if split.get("max_dte_embargo") is not True:
        errors.append("walk_forward_calibration must use max-DTE embargo")
    if split.get("purge_overlapping_labels") is not True:
        errors.append("walk_forward_calibration must purge overlapping labels")
    if (report.get("feature_standardization") or {}).get("future_data_used") is not False:
        errors.append("walk_forward_calibration standardization must not use future data")
    comparisons = report.get("system_comparison")
    comparison_status = report.get("comparison_status") or {}
    if comparison_status.get("status") not in {
        "not_run",
        "insufficient_evidence",
        "available",
    }:
        errors.append("walk_forward_calibration comparison_status is invalid")
    if comparison_status.get("status") == "available":
        expected_variants = {
            "baseline",
            "regime_only",
            "pricing_only",
            "full_system",
        }
        valid_rows = (
            isinstance(comparisons, list)
            and len(comparisons) == len(expected_variants)
            and all(isinstance(row, dict) for row in comparisons)
        )
        if not valid_rows or {
            row.get("variant") for row in comparisons
        } != expected_variants:
            errors.append("available calibration comparison must include all variants")
        if comparison_status.get("metrics_source") != "immutable_backtest_ledger":
            errors.append("available calibration comparison must name immutable ledger source")
        artifact_id = comparison_status.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            errors.append(
                "available calibration comparison must name immutable ledger artifact"
            )
        if valid_rows and any(
            not PERFORMANCE_METRIC_FIELDS.issubset(row)
            or any(
                isinstance(row[field], bool)
                or not isinstance(row[field], (int, float))
                or not isfinite(float(row[field]))
                for field in PERFORMANCE_METRIC_FIELDS.intersection(row)
            )
            for row in comparisons
        ):
            errors.append(
                "available calibration comparison rows must include all performance metrics"
            )
    elif comparisons != []:
        errors.append("unavailable calibration comparison must not expose performance rows")
    for check in report.get("leakage_checks") or []:
        if check.get("future_data_used") is not False:
            errors.append("walk_forward_calibration leakage checks must be false")
    registry = report.get("model_registry") or {}
    if registry.get("promotion_status") not in {
        "research_only_unpromoted",
        "promoted",
        "rejected",
    }:
        errors.append("walk_forward_calibration model registry promotion_status is invalid")
    if registry.get("promoted_for_sizing") is True:
        if registry.get("promotion_status") != "promoted":
            errors.append("promoted calibration registry must have promotion_status promoted")
        evidence = registry.get("promotion_evidence") or {}
        required_evidence = {
            "validated_historical_data",
            "validated_path_risk",
            "out_of_sample_passed",
            "external_review_approved",
        }
        missing = sorted(key for key in required_evidence if evidence.get(key) is not True)
        if missing:
            errors.append(
                "promoted calibration registry missing evidence: " + ",".join(missing)
            )
    elif registry.get("promoted_for_sizing") is not False:
        errors.append("walk_forward_calibration model registry promoted_for_sizing must be bool")
    return errors


def _model_registry(promotion_evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "validated_historical_data": promotion_evidence.get("validated_historical_data") is True,
        "validated_path_risk": promotion_evidence.get("validated_path_risk") is True,
        "out_of_sample_passed": promotion_evidence.get("out_of_sample_passed") is True,
        "external_review_approved": promotion_evidence.get("external_review_approved") is True,
        "paper_reconciliation_observed": promotion_evidence.get("paper_reconciliation_observed") is True,
    }
    promoted = all(
        evidence[key]
        for key in (
            "validated_historical_data",
            "validated_path_risk",
            "out_of_sample_passed",
            "external_review_approved",
        )
    )
    blocking_reasons = []
    if not evidence["validated_historical_data"]:
        blocking_reasons.append("MISSING_VENDOR_HISTORY_PROVENANCE")
    if not evidence["validated_path_risk"]:
        blocking_reasons.append("MISSING_VALIDATED_PATH_RISK")
    if not evidence["out_of_sample_passed"]:
        blocking_reasons.append("MISSING_OUT_OF_SAMPLE_EVIDENCE")
    if not evidence["external_review_approved"]:
        blocking_reasons.append("MISSING_EXTERNAL_PROMOTION_REVIEW")
    if not evidence["paper_reconciliation_observed"]:
        blocking_reasons.append("MISSING_PAPER_RECONCILIATION")
    return {
        "registry_schema_version": "calibration_model_registry.v1",
        "model_version": "walk_forward_fixture_v1",
        "artifact_id": "deterministic_fixture_walk_forward_v1",
        "training_window": "fixture_24_months",
        "validation_window": "fixture_3_months",
        "leakage_check_status": "pass",
        "out_of_sample_evidence": {
            "status": "pass" if evidence["out_of_sample_passed"] else "missing",
            "source": promotion_evidence.get("out_of_sample_source", "fixture_or_external_review"),
        },
        "promotion_status": "promoted" if promoted else "research_only_unpromoted",
        "promoted_for_sizing": promoted,
        "requires_external_review": not promoted,
        "promotion_evidence": evidence,
        "blocking_reasons": blocking_reasons,
    }
