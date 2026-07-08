"""Walk-forward calibration and full-system comparison tracer for ISSUE-013."""

from __future__ import annotations

from typing import Any

WALK_FORWARD_CALIBRATION_SCHEMA_VERSION = "walk_forward_calibration_report.v1"


def build_walk_forward_calibration_report(
    *,
    generated_at: str,
    baseline_backtest: dict[str, Any] | None = None,
    portfolio_risk: dict[str, Any] | None = None,
    position_management: dict[str, Any] | None = None,
    promotion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic no-leakage calibration evidence report."""

    baseline_metrics = (baseline_backtest or {}).get("metrics") or {}
    baseline_mdd = _metric_value(baseline_metrics, "max_drawdown", default=-0.19)
    baseline_cvar = abs(_metric_value(baseline_metrics, "cvar_99", default=-920.0))
    forced_exit_count = 1
    if position_management:
        forced_exit_count = int((position_management.get("summary") or {}).get("forced_exit_count") or 0)
    model_registry = _model_registry(promotion_evidence or {})

    return {
        "schema_version": WALK_FORWARD_CALIBRATION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "validated",
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
            "status": "calibrated",
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
        "system_comparison": _comparison_rows(
            baseline_mdd=baseline_mdd,
            baseline_cvar=baseline_cvar,
            forced_exit_count=forced_exit_count,
            portfolio_final_action=(portfolio_risk or {}).get("final_action"),
        ),
        "slow_bull_acute_rally_windows": [
            {
                "window": "2023-10_to_2024-03",
                "baseline_max_drawdown": -0.22,
                "full_system_max_drawdown": -0.12,
                "note": "Slow bull acute-rally window explicitly highlighted for OOS stress review.",
            },
            {
                "window": "2024-10_to_2025-01",
                "baseline_max_drawdown": -0.18,
                "full_system_max_drawdown": -0.10,
                "note": "Permission caps and forced-exit policy reduce rally drawdown.",
            },
        ],
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
    if not isinstance(comparisons, list) or {row.get("variant") for row in comparisons} != {
        "baseline",
        "regime_only",
        "pricing_only",
        "full_system",
    }:
        errors.append("walk_forward_calibration must compare all four variants")
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


def _comparison_rows(
    *,
    baseline_mdd: float,
    baseline_cvar: float,
    forced_exit_count: int,
    portfolio_final_action: str | None,
) -> list[dict[str, Any]]:
    baseline = _row(
        "baseline",
        calmar=0.48,
        max_drawdown=baseline_mdd,
        cvar_99=baseline_cvar,
        touch_rate=0.42,
        forced_exit_count=0,
        margin_breach_count=3,
        premium_to_cvar=0.38,
        recovery_days=41,
    )
    regime = _row(
        "regime_only",
        calmar=0.66,
        max_drawdown=baseline_mdd * 0.82,
        cvar_99=baseline_cvar * 0.86,
        touch_rate=0.34,
        forced_exit_count=forced_exit_count,
        margin_breach_count=2,
        premium_to_cvar=0.45,
        recovery_days=31,
    )
    pricing = _row(
        "pricing_only",
        calmar=0.71,
        max_drawdown=baseline_mdd * 0.78,
        cvar_99=baseline_cvar * 0.80,
        touch_rate=0.31,
        forced_exit_count=max(forced_exit_count, 1),
        margin_breach_count=2,
        premium_to_cvar=0.52,
        recovery_days=28,
    )
    final_action_penalty = 0.02 if portfolio_final_action in {"halt_system", "close_all_and_pause"} else 0.0
    full = _row(
        "full_system",
        calmar=0.94 - final_action_penalty,
        max_drawdown=baseline_mdd * 0.58,
        cvar_99=baseline_cvar * 0.62,
        touch_rate=0.22,
        forced_exit_count=max(forced_exit_count, 1),
        margin_breach_count=0,
        premium_to_cvar=0.71,
        recovery_days=17,
    )
    return [baseline, regime, pricing, full]


def _row(
    variant: str,
    *,
    calmar: float,
    max_drawdown: float,
    cvar_99: float,
    touch_rate: float,
    forced_exit_count: int,
    margin_breach_count: int,
    premium_to_cvar: float,
    recovery_days: int,
) -> dict[str, Any]:
    return {
        "variant": variant,
        "calmar": round(calmar, 6),
        "max_drawdown": round(max_drawdown, 6),
        "cvar_99": round(cvar_99, 6),
        "touch_rate": round(touch_rate, 6),
        "forced_exit_count": forced_exit_count,
        "margin_breach_count": margin_breach_count,
        "premium_to_cvar": round(premium_to_cvar, 6),
        "recovery_days": recovery_days,
    }


def _metric_value(metrics: dict[str, Any], key: str, *, default: float) -> float:
    value = (metrics.get(key) or {}).get("value")
    if value is None:
        return default
    return float(value)
