"""Exact-strategy forecast lifecycle for strategy brief projections.

Ranking promotion, aligned strategy history, and exact-strategy forecast
calibration are separate claims. This module only governs the final one: when a
strategy brief may expose a calibrated win-rate interval for one exact strategy
scope, and when that claim must be retired.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ._canonical import canonical_sha256

STRATEGY_FORECAST_SCHEMA_VERSION = "strategy_forecast.v1"
STRATEGY_FORECAST_ARTIFACT_SCHEMA_VERSION = "exact_strategy_forecast_artifact.v1"
STRATEGY_FORECAST_RUNTIME_EVIDENCE_SCHEMA_VERSION = (
    "strategy_forecast_runtime_evidence.v1"
)
FORECAST_STATUSES = ("UNAVAILABLE", "SCREENING_ONLY", "CALIBRATED", "RETIRED")
FORECAST_SCOPE_FIELDS = (
    "underlying",
    "structure",
    "direction",
    "dte",
    "entry_cost_basis",
    "exit_basis",
)

MAX_FORECAST_ARTIFACT_AGE_DAYS = 90
MAX_DATA_CONTINUITY_GAP_DAYS = 3
SELECTION_SCOPE_FIELD = "selection"


def build_unavailable_strategy_forecast(
    *,
    as_of: str,
    scope: dict[str, Any] | None = None,
    reason_code: str = "FORECAST_NOT_CALIBRATED",
) -> dict[str, Any]:
    """Return the production default: no calibrated forecast is available."""

    projection = {
        "schema_version": STRATEGY_FORECAST_SCHEMA_VERSION,
        "as_of": as_of,
        "status": "UNAVAILABLE",
        "win_rate_low": None,
        "win_rate_high": None,
        "confidence": None,
        "scope": _normalize_scope(scope) if scope is not None else None,
        "artifact_id": None,
        "reason_codes": [reason_code],
    }
    return projection


def build_screening_only_strategy_forecast(
    *,
    as_of: str,
    scope: dict[str, Any],
    reason_code: str = "FORECAST_SCREENING_ONLY",
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Return a screening-only forecast that never exposes probabilities."""

    projection = {
        "schema_version": STRATEGY_FORECAST_SCHEMA_VERSION,
        "as_of": as_of,
        "status": "SCREENING_ONLY",
        "win_rate_low": None,
        "win_rate_high": None,
        "confidence": None,
        "scope": _normalize_scope(scope),
        "artifact_id": artifact_id,
        "reason_codes": [reason_code],
    }
    return projection


def build_calibrated_strategy_forecast_artifact(
    *,
    promoted_at: str,
    scope: dict[str, Any],
    preregistration: dict[str, Any],
    holdout_access: dict[str, Any],
    model: dict[str, Any],
    calibrator: dict[str, Any],
    validation: dict[str, Any],
    input_fingerprint: dict[str, Any],
    lineage: dict[str, Any],
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Build one content-addressed calibrated forecast artifact.

    The payload is validated against the frozen promotion contract before it can
    exist. The artifact id is the SHA-256 of the canonical JSON encoding of the
    artifact body with ``artifact_id`` omitted.
    """

    promoted_dt = _parse_timestamp(promoted_at)
    if expires_at is None:
        expires_at = _format_timestamp(
            promoted_dt + timedelta(days=MAX_FORECAST_ARTIFACT_AGE_DAYS)
        )
    artifact = {
        "schema_version": STRATEGY_FORECAST_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": None,
        "promoted_at": promoted_at,
        "expires_at": expires_at,
        "status": "CALIBRATED",
        "scope": _artifact_scope(scope),
        "selection_binding_key": _required_selection_binding_key(scope),
        "preregistration": dict(preregistration),
        "holdout_access": (
            dict(holdout_access) if isinstance(holdout_access, dict) else holdout_access
        ),
        "model": dict(model),
        "calibrator": dict(calibrator),
        "validation": dict(validation),
        "input_fingerprint": dict(input_fingerprint),
        "lineage": dict(lineage),
    }
    errors = _validate_strategy_forecast_artifact(artifact, allow_missing_id=True)
    if errors:
        raise ValueError("; ".join(errors))
    artifact["artifact_id"] = _expected_artifact_id(artifact)
    errors = validate_strategy_forecast_artifact(artifact)
    if errors:
        raise ValueError("; ".join(errors))
    return artifact


def build_strategy_forecast_runtime_evidence(
    *,
    artifact: dict[str, Any],
    current_input_fingerprint: dict[str, Any] | None,
    current_lineage: dict[str, Any] | None,
    current_oos_monitor: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind a promoted artifact to independently refreshed runtime evidence.

    The promotion artifact is immutable.  Input/lineage/OOS observations are a
    separate deployment-time envelope so an old artifact cannot certify its own
    continued validity.  Missing or malformed current evidence remains a valid
    envelope and is projected as ``RETIRED`` by :func:`project_strategy_forecast`.
    """

    value = {
        "schema_version": STRATEGY_FORECAST_RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "artifact": dict(artifact),
        "current_input_fingerprint": (
            dict(current_input_fingerprint)
            if isinstance(current_input_fingerprint, dict)
            else current_input_fingerprint
        ),
        "current_lineage": (
            dict(current_lineage)
            if isinstance(current_lineage, dict)
            else current_lineage
        ),
        "current_oos_monitor": (
            dict(current_oos_monitor)
            if isinstance(current_oos_monitor, dict)
            else current_oos_monitor
        ),
    }
    errors = validate_strategy_forecast_runtime_evidence(value)
    if errors:
        raise ValueError("; ".join(errors))
    return value


def validate_strategy_forecast_runtime_evidence(value: Any) -> list[str]:
    """Validate the immutable artifact portion of one runtime envelope.

    Current observations are deliberately allowed to be absent or invalid: the
    lifecycle projector must turn those conditions into ``RETIRED`` rather than
    letting an operator parse failure preserve a stale probability.
    """

    if not isinstance(value, dict):
        return ["strategy_forecast runtime evidence must be a dict"]
    errors: list[str] = []
    if value.get("schema_version") != STRATEGY_FORECAST_RUNTIME_EVIDENCE_SCHEMA_VERSION:
        errors.append(
            "strategy_forecast runtime evidence schema_version must be "
            "strategy_forecast_runtime_evidence.v1"
        )
    artifact_errors = validate_strategy_forecast_artifact(value.get("artifact"))
    errors.extend(f"artifact: {error}" for error in artifact_errors)
    return errors


def project_strategy_forecast(
    *,
    as_of: str,
    scope: dict[str, Any],
    artifact: dict[str, Any] | None = None,
    current_input_fingerprint: dict[str, Any] | None = None,
    current_lineage: dict[str, Any] | None = None,
    current_oos_monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the user-facing forecast status for one exact strategy scope."""

    normalized_scope = _normalize_scope(scope)
    expected_selection_binding_key = selection_binding_key_from_scope(scope)
    if artifact is None:
        return build_unavailable_strategy_forecast(as_of=as_of, scope=normalized_scope)

    errors = validate_strategy_forecast_artifact(artifact)
    if errors:
        return _retired_projection(
            as_of=as_of,
            scope=normalized_scope,
            artifact_id=artifact.get("artifact_id"),
            reason_codes=["FORECAST_ARTIFACT_INVALID", *errors],
        )

    lifecycle_reasons = _lifecycle_reason_codes(
        as_of=as_of,
        scope=normalized_scope,
        expected_selection_binding_key=expected_selection_binding_key,
        artifact=artifact,
        current_input_fingerprint=current_input_fingerprint,
        current_lineage=current_lineage,
        current_oos_monitor=current_oos_monitor,
    )
    if lifecycle_reasons:
        return _retired_projection(
            as_of=as_of,
            scope=normalized_scope,
            artifact_id=artifact["artifact_id"],
            reason_codes=lifecycle_reasons,
        )

    interval = artifact["validation"]["interval"]
    projection = {
        "schema_version": STRATEGY_FORECAST_SCHEMA_VERSION,
        "as_of": as_of,
        "status": "CALIBRATED",
        "win_rate_low": float(interval["win_rate_low"]),
        "win_rate_high": float(interval["win_rate_high"]),
        "confidence": interval["confidence"],
        "scope": normalized_scope,
        "artifact_id": artifact["artifact_id"],
        "reason_codes": [],
    }
    return projection


def validate_strategy_forecast_projection(projection: Any) -> list[str]:
    """Validate the user-facing strategy forecast projection."""

    if not isinstance(projection, dict):
        return ["strategy_forecast must be a dict"]

    errors: list[str] = []
    if projection.get("schema_version") != STRATEGY_FORECAST_SCHEMA_VERSION:
        errors.append(
            "strategy_forecast.schema_version must be strategy_forecast.v1"
        )
    status = projection.get("status")
    if status not in FORECAST_STATUSES:
        errors.append("strategy_forecast.status must use the canonical vocabulary")
        status = None
    try:
        _parse_timestamp(projection.get("as_of"))
    except ValueError:
        errors.append("strategy_forecast.as_of must be an ISO-8601 timestamp")

    scope = projection.get("scope")
    if scope is not None:
        try:
            _normalize_scope(scope)
        except ValueError as exc:
            errors.append(f"strategy_forecast.scope {exc}")

    low = projection.get("win_rate_low")
    high = projection.get("win_rate_high")
    confidence = projection.get("confidence")
    if status == "CALIBRATED":
        if not _is_probability(low) or not _is_probability(high):
            errors.append(
                "calibrated strategy_forecast must expose win_rate_low/high probabilities"
            )
        elif float(low) > float(high):
            errors.append("strategy_forecast.win_rate_low must not exceed win_rate_high")
        if not isinstance(confidence, str) or not confidence:
            errors.append("calibrated strategy_forecast.confidence must be present")
    else:
        if low is not None or high is not None:
            errors.append(
                "strategy_forecast probabilities must be null unless status is CALIBRATED"
            )
        if confidence is not None:
            errors.append(
                "strategy_forecast.confidence must be null unless status is CALIBRATED"
            )

    reason_codes = projection.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) and item for item in reason_codes
    ):
        errors.append("strategy_forecast.reason_codes must be a list of strings")
    return errors


def validate_strategy_forecast_artifact(artifact: Any) -> list[str]:
    """Validate a calibrated exact-strategy forecast artifact."""

    return _validate_strategy_forecast_artifact(artifact, allow_missing_id=False)


def _validate_strategy_forecast_artifact(
    artifact: Any,
    *,
    allow_missing_id: bool,
) -> list[str]:
    """Validate a calibrated exact-strategy forecast artifact."""

    if not isinstance(artifact, dict):
        return ["strategy_forecast artifact must be a dict"]

    errors: list[str] = []
    if artifact.get("schema_version") != STRATEGY_FORECAST_ARTIFACT_SCHEMA_VERSION:
        errors.append(
            "strategy_forecast artifact schema_version must be "
            "exact_strategy_forecast_artifact.v1"
        )
    if artifact.get("status") != "CALIBRATED":
        errors.append("strategy_forecast artifact status must be CALIBRATED")

    artifact_id = artifact.get("artifact_id")
    expected_id = _expected_artifact_id(artifact)
    if not isinstance(artifact_id, str) or not artifact_id:
        if not allow_missing_id:
            errors.append("strategy_forecast artifact_id must be present")
    elif artifact_id != expected_id:
        errors.append("strategy_forecast artifact_id must match the canonical payload")

    try:
        promoted_at = _parse_timestamp(artifact.get("promoted_at"))
    except ValueError:
        errors.append("strategy_forecast promoted_at must be an ISO-8601 timestamp")
        promoted_at = None
    try:
        expires_at = _parse_timestamp(artifact.get("expires_at"))
    except ValueError:
        errors.append("strategy_forecast expires_at must be an ISO-8601 timestamp")
        expires_at = None
    if promoted_at is not None and expires_at is not None:
        if expires_at <= promoted_at:
            errors.append("strategy_forecast expires_at must be after promoted_at")
        if expires_at - promoted_at > timedelta(days=MAX_FORECAST_ARTIFACT_AGE_DAYS):
            errors.append("strategy_forecast artifact expiry must not exceed 90 days")

    try:
        _normalize_scope(artifact.get("scope"))
    except ValueError as exc:
        errors.append(f"strategy_forecast.scope {exc}")
    selection_binding_key = artifact.get("selection_binding_key")
    derived_selection_binding_key = selection_binding_key_from_scope(artifact.get("scope"))
    if selection_binding_key is not None:
        if not isinstance(selection_binding_key, str) or not selection_binding_key:
            errors.append("strategy_forecast.selection_binding_key must be a non-empty string")
        elif derived_selection_binding_key is None:
            errors.append(
                "strategy_forecast.selection_binding_key requires exact selection scope"
            )
        elif selection_binding_key != derived_selection_binding_key:
            errors.append(
                "strategy_forecast.selection_binding_key must match the exact selection scope"
            )

    preregistration = artifact.get("preregistration")
    errors.extend(_validate_preregistration(preregistration))
    errors.extend(
        _validate_holdout_access(
            artifact.get("holdout_access"),
            preregistration=preregistration,
            promoted_at=promoted_at,
        )
    )
    errors.extend(_validate_model_claim(artifact.get("model"), label="model"))
    errors.extend(
        _validate_model_claim(artifact.get("calibrator"), label="calibrator")
    )
    errors.extend(_validate_validation_block(artifact.get("validation")))
    errors.extend(
        _validate_input_fingerprint(
            artifact.get("input_fingerprint"),
            context="artifact",
        )
    )
    errors.extend(_validate_lineage(artifact.get("lineage")))
    return errors


def _validate_preregistration(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["strategy_forecast.preregistration must be a dict"]
    errors: list[str] = []
    if value.get("pre_registered") is not True:
        errors.append("strategy_forecast must be pre-registered before holdout access")
    if value.get("holdout_status_at_freeze") != "sealed":
        errors.append("strategy_forecast final holdout must be sealed at freeze")
    if not isinstance(value.get("protocol_document"), str) or not value["protocol_document"]:
        errors.append("strategy_forecast preregistration must name its frozen protocol")
    try:
        _parse_timestamp(value.get("frozen_at"))
    except ValueError:
        errors.append("strategy_forecast preregistration.frozen_at must be a timestamp")
    return errors


def _validate_holdout_access(
    value: Any,
    *,
    preregistration: Any,
    promoted_at: datetime | None,
) -> list[str]:
    if not isinstance(value, dict):
        return ["strategy_forecast.holdout_access must be a dict"]

    errors: list[str] = []
    try:
        accessed_at = _parse_timestamp(value.get("accessed_at"))
    except ValueError:
        errors.append("strategy_forecast holdout_access.accessed_at must be a timestamp")
        accessed_at = None
    if _coerce_int(value.get("access_count")) != 1:
        errors.append("strategy_forecast holdout_access.access_count must be exactly 1")
    if _coerce_int(value.get("rerun_count")) != 0:
        errors.append("strategy_forecast holdout_access.rerun_count must be 0")
    if value.get("invalidated") is not False:
        errors.append("strategy_forecast holdout_access.invalidated must be false")
    for field in ("command_hash", "input_hash", "result_hash"):
        field_value = value.get(field)
        if not isinstance(field_value, str) or not field_value:
            errors.append(f"strategy_forecast holdout_access.{field} must be present")
    if value.get("previously_viewed") is not False:
        errors.append(
            "strategy_forecast holdout evidence must not come from a previously viewed holdout"
        )
    if value.get("tuned_after_access") is not False:
        errors.append(
            "strategy_forecast holdout evidence must not come from post-access tuning"
        )

    if isinstance(preregistration, dict):
        try:
            frozen_at = _parse_timestamp(preregistration.get("frozen_at"))
        except ValueError:
            frozen_at = None
        if accessed_at is not None and frozen_at is not None and accessed_at <= frozen_at:
            errors.append(
                "strategy_forecast holdout_access.accessed_at must be after preregistration freeze"
            )
    if accessed_at is not None and promoted_at is not None and promoted_at < accessed_at:
        errors.append(
            "strategy_forecast promoted_at must be at or after holdout_access.accessed_at"
        )
    return errors


def _validate_model_claim(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"strategy_forecast.{label} must be a dict"]
    errors: list[str] = []
    if not isinstance(value.get("id"), str) or not value["id"]:
        errors.append(f"strategy_forecast.{label}.id must be present")
    if value.get("frozen") is not True:
        errors.append(f"strategy_forecast.{label} must be frozen before holdout access")
    if not isinstance(value.get("digest"), str) or not value["digest"]:
        errors.append(f"strategy_forecast.{label}.digest must be present")
    return errors


def _validate_validation_block(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["strategy_forecast.validation must be a dict"]
    errors: list[str] = []
    walk_forward = value.get("walk_forward")
    if not isinstance(walk_forward, dict):
        errors.append("strategy_forecast.validation.walk_forward must be a dict")
        walk_forward = {}
    if walk_forward.get("purged") is not True:
        errors.append("strategy_forecast walk-forward must be purged")
    if walk_forward.get("embargoed") is not True:
        errors.append("strategy_forecast walk-forward must be embargoed")
    if _coerce_int(walk_forward.get("independent_future_cohorts")) < 8:
        errors.append(
            "strategy_forecast requires at least 8 independent future cohorts"
        )
    if _coerce_int(walk_forward.get("observation_count")) < 100:
        errors.append("strategy_forecast requires at least 100 observations")
    if _coerce_int(walk_forward.get("regime_count")) < 2:
        errors.append("strategy_forecast requires at least 2 regimes")
    if _coerce_float(walk_forward.get("max_regime_share")) > 0.60:
        errors.append("strategy_forecast no regime may supply more than 60%")

    performance = value.get("performance")
    if not isinstance(performance, dict):
        errors.append("strategy_forecast.validation.performance must be a dict")
        performance = {}
    brier = _coerce_float(performance.get("brier_score"))
    base_brier = _coerce_float(performance.get("base_rate_brier_score"))
    if not (0.0 <= brier < base_brier):
        errors.append("strategy_forecast Brier score must beat the base-rate model")
    if performance.get("reliability_pass") is not True:
        errors.append("strategy_forecast reliability gate must pass")

    interval = value.get("interval")
    if not isinstance(interval, dict):
        errors.append("strategy_forecast.validation.interval must be a dict")
        interval = {}
    low = interval.get("win_rate_low")
    high = interval.get("win_rate_high")
    if not _is_probability(low) or not _is_probability(high):
        errors.append("strategy_forecast interval must contain valid probabilities")
    elif float(low) > float(high):
        errors.append("strategy_forecast interval low must not exceed high")
    if interval.get("decision_width_pass") is not True:
        errors.append("strategy_forecast interval must pass the decision-width gate")
    if _is_probability(low) and _is_probability(high):
        max_width = _coerce_float(interval.get("max_width"))
        if float(high) - float(low) > max_width:
            errors.append("strategy_forecast interval width exceeds its max_width")
    if not isinstance(interval.get("confidence"), str) or not interval["confidence"]:
        errors.append("strategy_forecast interval confidence must be present")

    aligned_support = value.get("aligned_support")
    if not isinstance(aligned_support, dict):
        errors.append("strategy_forecast.validation.aligned_support must be a dict")
        aligned_support = {}
    if aligned_support.get("history_status") != "VALIDATED":
        errors.append("strategy_forecast aligned history must be VALIDATED")
    if aligned_support.get("risk_status") != "PASS":
        errors.append("strategy_forecast risk gate must pass")

    oos_monitor = value.get("oos_monitor")
    if not isinstance(oos_monitor, dict):
        errors.append("strategy_forecast.validation.oos_monitor must be a dict")
        oos_monitor = {}
    if _coerce_int(oos_monitor.get("consecutive_adverse_cohorts")) >= 3:
        errors.append(
            "strategy_forecast must demote after 3 consecutive adverse OOS cohorts"
        )
    return errors


def _validate_input_fingerprint(value: Any, *, context: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"strategy_forecast.{context}_input_fingerprint must be a dict"]
    errors: list[str] = []
    for field in (
        "dataset_hash",
        "config_hash",
        "feature_schema_version",
        "unit_semantics_version",
    ):
        if not isinstance(value.get(field), str) or not value[field]:
            errors.append(
                f"strategy_forecast.{context}_input_fingerprint.{field} must be present"
            )
    if _coerce_int(value.get("continuity_max_gap_days")) > MAX_DATA_CONTINUITY_GAP_DAYS:
        errors.append(
            f"strategy_forecast {context} data continuity gap must be 3 days or less"
        )
    source_class = value.get("source_class")
    if source_class != "live":
        errors.append(
            f"strategy_forecast {context} evidence must come from live evidence"
        )
    return errors


def _validate_lineage(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["strategy_forecast.lineage must be a dict"]
    errors: list[str] = []
    if value.get("verified") is not True:
        errors.append("strategy_forecast lineage must be verified")
    for field in ("history_artifact_id", "risk_artifact_id", "ranking_artifact_id"):
        if not isinstance(value.get(field), str) or not value[field]:
            errors.append(f"strategy_forecast.lineage.{field} must be present")
    return errors


def _lifecycle_reason_codes(
    *,
    as_of: str,
    scope: dict[str, Any],
    expected_selection_binding_key: str | None,
    artifact: dict[str, Any],
    current_input_fingerprint: dict[str, Any] | None,
    current_lineage: dict[str, Any] | None,
    current_oos_monitor: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    as_of_dt = _parse_timestamp(as_of)
    expires_at = _parse_timestamp(artifact["expires_at"])
    if as_of_dt > expires_at:
        reasons.append("PROMOTION_EXPIRED")

    if scope != _normalize_scope(artifact["scope"]):
        reasons.append("FORECAST_SCOPE_MISMATCH")
    artifact_selection_binding_key = artifact.get("selection_binding_key")
    if (
        not isinstance(artifact_selection_binding_key, str)
        or not artifact_selection_binding_key
        or expected_selection_binding_key is None
    ):
        reasons.append("FORECAST_SELECTION_UNBOUND")
    elif artifact_selection_binding_key != expected_selection_binding_key:
        reasons.append("FORECAST_SELECTION_MISMATCH")

    reasons.extend(
        _current_input_fingerprint_reason_codes(
            artifact=artifact,
            current_input_fingerprint=current_input_fingerprint,
        )
    )
    reasons.extend(
        _current_lineage_reason_codes(
            artifact=artifact,
            current_lineage=current_lineage,
        )
    )
    reasons.extend(
        _current_oos_monitor_reason_codes(
            current_oos_monitor=current_oos_monitor,
        )
    )

    return reasons


def _current_input_fingerprint_reason_codes(
    *,
    artifact: dict[str, Any],
    current_input_fingerprint: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(current_input_fingerprint, dict):
        return ["FORECAST_CURRENT_EVIDENCE_UNAVAILABLE"]
    reasons: list[str] = []
    validation_errors = _validate_input_fingerprint(
        current_input_fingerprint,
        context="current",
    )
    if validation_errors:
        reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
        if any("live evidence" in error for error in validation_errors):
            reasons.append("FORECAST_CURRENT_SOURCE_NOT_LIVE")
        if any("continuity gap" in error for error in validation_errors):
            reasons.append("FORECAST_DATA_CONTINUITY_BROKEN")
        if any("dataset_hash" in error for error in validation_errors):
            reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
        if any("config_hash" in error for error in validation_errors):
            reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
        if any("feature_schema_version" in error for error in validation_errors):
            reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
        if any("unit_semantics_version" in error for error in validation_errors):
            reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
    fingerprint = artifact["input_fingerprint"]
    if current_input_fingerprint.get("dataset_hash") != fingerprint["dataset_hash"]:
        reasons.append("FORECAST_INPUT_DRIFT")
    if current_input_fingerprint.get("config_hash") != fingerprint["config_hash"]:
        reasons.append("FORECAST_CONFIG_DRIFT")
    if (
        current_input_fingerprint.get("feature_schema_version")
        != fingerprint["feature_schema_version"]
    ):
        reasons.append("FORECAST_SCHEMA_DRIFT")
    if (
        current_input_fingerprint.get("unit_semantics_version")
        != fingerprint["unit_semantics_version"]
    ):
        reasons.append("FORECAST_UNIT_DRIFT")
    return _dedupe_reason_codes(reasons)


def _current_lineage_reason_codes(
    *,
    artifact: dict[str, Any],
    current_lineage: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(current_lineage, dict):
        return ["FORECAST_CURRENT_EVIDENCE_UNAVAILABLE"]
    reasons: list[str] = []
    validation_errors = _validate_lineage(current_lineage)
    if validation_errors:
        reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
    if current_lineage.get("verified") is not True:
        reasons.append("FORECAST_LINEAGE_UNVERIFIED")
    expected_lineage = artifact["lineage"]
    for field in ("history_artifact_id", "risk_artifact_id", "ranking_artifact_id"):
        if current_lineage.get(field) != expected_lineage.get(field):
            reasons.append("FORECAST_LINEAGE_DRIFT")
            break
    return _dedupe_reason_codes(reasons)


def _current_oos_monitor_reason_codes(
    *,
    current_oos_monitor: dict[str, Any] | None,
) -> list[str]:
    if current_oos_monitor is None:
        return ["FORECAST_CURRENT_EVIDENCE_UNAVAILABLE"]
    reasons: list[str] = []
    if not isinstance(current_oos_monitor, dict):
        return ["FORECAST_CURRENT_EVIDENCE_UNAVAILABLE"]
    required_pass_flags = (
        "adverse_pass",
        "directional_pass",
        "base_rate_quality_pass",
    )
    missing_flags = [
        field for field in required_pass_flags if field not in current_oos_monitor
    ]
    if missing_flags:
        reasons.append("FORECAST_CURRENT_EVIDENCE_UNAVAILABLE")
    if _coerce_int(current_oos_monitor.get("consecutive_adverse_cohorts")) >= 3:
        reasons.append("FORECAST_OOS_ADVERSE")
    if current_oos_monitor.get("adverse_pass") is False:
        reasons.append("FORECAST_OOS_ADVERSE")
    if current_oos_monitor.get("directional_pass") is False:
        reasons.append("FORECAST_OOS_DIRECTIONAL_FAIL")
    if current_oos_monitor.get("base_rate_quality_pass") is False:
        reasons.append("FORECAST_OOS_BASE_RATE_FAIL")
    return _dedupe_reason_codes(reasons)


def _retired_projection(
    *,
    as_of: str,
    scope: dict[str, Any],
    artifact_id: Any,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": STRATEGY_FORECAST_SCHEMA_VERSION,
        "as_of": as_of,
        "status": "RETIRED",
        "win_rate_low": None,
        "win_rate_high": None,
        "confidence": None,
        "scope": scope,
        "artifact_id": artifact_id if isinstance(artifact_id, str) else None,
        "reason_codes": reason_codes,
    }


def _normalize_scope(scope: Any) -> dict[str, Any]:
    if not isinstance(scope, dict):
        raise ValueError("must be a dict")
    normalized: dict[str, Any] = {}
    missing = [field for field in FORECAST_SCOPE_FIELDS if field not in scope]
    if missing:
        raise ValueError(f"must include {', '.join(missing)}")
    for field in ("underlying", "structure", "direction", "entry_cost_basis", "exit_basis"):
        value = scope.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty string")
        normalized[field] = value
    dte = scope.get("dte")
    if not isinstance(dte, dict):
        raise ValueError("dte must be a dict")
    minimum = _coerce_int(dte.get("min"))
    maximum = _coerce_int(dte.get("max"))
    if minimum <= 0 or maximum < minimum:
        raise ValueError("dte must contain positive min/max with min <= max")
    normalized["dte"] = {"min": minimum, "max": maximum}
    return normalized


def _artifact_scope(scope: Any) -> dict[str, Any]:
    normalized = _normalize_scope(scope)
    selection = _normalize_selection_identity(scope)
    if selection is not None:
        normalized[SELECTION_SCOPE_FIELD] = selection
    return normalized


def selection_binding_key_from_scope(scope: Any) -> str | None:
    try:
        public_scope = _normalize_scope(scope)
    except ValueError:
        return None
    selection = _normalize_selection_identity(scope)
    if selection is None:
        return None
    payload = {
        **public_scope,
        SELECTION_SCOPE_FIELD: selection,
    }
    return f"forecast-selection:{canonical_sha256(payload)}"


def _required_selection_binding_key(scope: Any) -> str:
    selection_binding_key = selection_binding_key_from_scope(scope)
    if selection_binding_key is None:
        raise ValueError(
            "strategy_forecast scope must include exact selection expiry_date and stable legs"
        )
    return selection_binding_key


def _normalize_selection_identity(scope: Any) -> dict[str, Any] | None:
    if not isinstance(scope, dict):
        return None
    selection = scope.get(SELECTION_SCOPE_FIELD)
    if not isinstance(selection, dict):
        return None
    expiry_date = selection.get("expiry_date")
    legs = selection.get("legs")
    if not isinstance(expiry_date, str) or not expiry_date:
        return None
    if not isinstance(legs, list) or not legs:
        return None
    normalized_legs: list[dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, dict):
            return None
        instrument_name = leg.get("instrument_name")
        option_type = leg.get("option_type")
        if not isinstance(instrument_name, str) or not instrument_name:
            return None
        if not isinstance(option_type, str) or not option_type:
            return None
        try:
            strike = float(leg.get("strike"))
            quantity = float(leg.get("quantity"))
        except (TypeError, ValueError):
            return None
        normalized_legs.append(
            {
                "instrument_name": instrument_name,
                "option_type": option_type.upper(),
                "strike": strike,
                "quantity": quantity,
            }
        )
    normalized_legs.sort(
        key=lambda item: (
            item["option_type"],
            item["strike"],
            item["quantity"],
            item["instrument_name"],
        )
    )
    return {
        "expiry_date": expiry_date,
        "legs": normalized_legs,
    }


def _expected_artifact_id(artifact: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_id", "selection_binding_key"}
    }
    return f"strategy_forecast:{canonical_sha256(payload)}"


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp missing")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_probability(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= number <= 1.0


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _dedupe_reason_codes(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
