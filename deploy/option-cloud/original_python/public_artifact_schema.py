"""Explicit public signal and instrument-history contracts.

These definitions describe the allowlisted publication projections, not inferred
examples. Optional members cover the producer's blocked/projected/measured
branches and the small historical public fixtures. Numeric annotations can be
added recursively by the public signal wrapper without widening the payload.
"""

from __future__ import annotations

from typing import Any


def _ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/components/schemas/{name}"}


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _object(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    evidence: bool = False,
) -> dict[str, Any]:
    fields = dict(properties)
    if evidence:
        fields["field_evidence"] = _ref("ArtifactFieldEvidenceMap")
    result: dict[str, Any] = {
        "type": "object",
        "properties": fields,
        "additionalProperties": False,
    }
    if required:
        result["required"] = list(required)
    return result


def artifact_schemas() -> dict[str, dict[str, Any]]:
    """Return fresh component definitions for ResearchSignal and ResearchSeries."""
    text = {"type": "string"}
    maybe_text = {"type": ["string", "null"]}
    timestamp = {"type": "string", "format": "date-time"}
    date = {"type": "string", "format": "date"}
    maybe_date = {"type": ["string", "null"], "format": "date"}
    registration_date = {"anyOf": [date, timestamp]}
    number = {"type": "number"}
    maybe_number = {"type": ["number", "null"]}
    count = {"type": "integer", "minimum": 0}
    maybe_count = {"type": ["integer", "null"], "minimum": 0}
    boolean = {"type": "boolean"}
    strings = _array(text)
    dates = _array(date)
    verdicts = [
        "insufficient_sample",
        "no_detectable_edge",
        "positive_ic",
        "negative_ic",
    ]
    schemas = {
        "ArtifactFieldEvidence": _object(
            {"evidence_class": text, "unit": maybe_text},
            required=("evidence_class", "unit"),
        ),
        "ArtifactFieldEvidenceMap": {
            "type": "object",
            "additionalProperties": _ref("ArtifactFieldEvidence"),
        },
        "ArtifactExpiryExclusion": _object(
            {
                "captured_at": timestamp,
                "expiry_date": date,
                "reason_codes": strings,
            },
            required=("captured_at", "expiry_date", "reason_codes"),
        ),
        "ArtifactCaptureExclusion": _object(
            # This is the rejected input, including missing/unparseable clocks.
            {"captured_at": maybe_text, "reason_code": text},
        ),
        "SignalConfig": _object(
            {
                "bucket_count": count,
                "max_dte_days": number,
                "min_dte_days": number,
                "min_independent_cohorts": count,
                "min_observations": count,
                "min_observations_per_date": count,
                "trailing_vol_window_days": count,
            },
            evidence=True,
        ),
        "SignalSummary": _object(
            {
                "best_exploratory_signal": maybe_text,
                "pre_registered_axis": text,
                "pre_registered_axis_verdict": {
                    "type": ["string", "null"],
                    "enum": [*verdicts, None],
                },
                "promotion_eligible": boolean,
                "promotion_eligibility_basis": text,
                "signals_measured": count,
                "signals_with_detectable_ic": count,
            },
            evidence=True,
        ),
        "SignalPreRegistration": _object(
            {
                "axis": text,
                "document": text,
                "note": text,
                "registered_at": registration_date,
                "threshold": number,
            },
            evidence=True,
        ),
        "SignalSample": _object(
            {
                "duplicate_observations_dropped": maybe_count,
                "excluded_expiries": _array(_ref("ArtifactExpiryExclusion")),
                "excluded_snapshot_count": maybe_count,
                "excluded_snapshots": _array(_ref("ArtifactCaptureExclusion")),
                "expiry_cohorts": dates,
                "independent_expiry_cohorts": count,
                "observation_count": count,
                "sample_size_basis": text,
                "settlement_basis": maybe_text,
                "settlement_note": maybe_text,
                "snapshot_count": maybe_count,
                "snapshot_date_count": maybe_count,
                "validated_snapshot_count": maybe_count,
            },
            required=(
                "duplicate_observations_dropped",
                "excluded_expiries",
                "excluded_snapshot_count",
                "excluded_snapshots",
                "expiry_cohorts",
                "independent_expiry_cohorts",
                "observation_count",
                "sample_size_basis",
                "settlement_basis",
                "settlement_note",
                "snapshot_count",
                "snapshot_date_count",
                "validated_snapshot_count",
            ),
            evidence=True,
        ),
        "SignalBand": _object(
            {
                "cohorts_required": count,
                "cohorts_seen": count,
                "cohorts_short_by": count,
                "next_pending_expiry": maybe_date,
                "pending_cohorts": count,
                "pending_observation_count": count,
                "settled_cohorts": count,
                "settled_observation_count": count,
                "would_be_ready_after_expiry": maybe_date,
            },
            evidence=True,
        ),
        "SignalBlockingReasonCounts": {
            "type": "object",
            "properties": {"field_evidence": _ref("ArtifactFieldEvidenceMap")},
            "additionalProperties": count,
        },
        "SignalCohort": _object(
            {
                "band": {"type": "string", "enum": ["research_window", "short_dated"]},
                "blocking_reasons": _ref("SignalBlockingReasonCounts"),
                "capture_date_count": count,
                "dte_days_max": maybe_number,
                "dte_days_min": maybe_number,
                "expiry_date": date,
                "first_capture_date": maybe_date,
                "fitted_capture_count": count,
                "last_capture_date": maybe_date,
                "name": text,
                "observation_count": count,
                "prospective_observation_count": count,
                "registered_at": registration_date,
                "settlement_close_available": boolean,
                "status": text,
            },
            evidence=True,
        ),
        "SignalInformationCoefficient": _object(
            {
                "mean": number,
                "method": text,
                "neutralization": text,
                "stdev_across_dates": number,
                "t_stat": maybe_number,
            },
            evidence=True,
        ),
        "SignalRawInformationCoefficient": _object(
            {
                "mean": number,
                "measured_date_count": count,
                "method": text,
                "warning": text,
            },
            evidence=True,
        ),
        "SignalBucket": _object(
            {
                "bucket": count,
                "expired_itm_rate": number,
                "independent_expiry_cohorts": count,
                "mean_pnl_per_vega_iv_points": number,
                "mean_pnl_usd": number,
                "median_pnl_per_vega_iv_points": number,
                "observation_count": count,
                "signal_max": number,
                "signal_min": number,
                "win_rate": number,
            },
            evidence=True,
        ),
        "SignalPerDate": _object(
            {
                "information_coefficient": number,
                "observation_count": count,
                "raw_information_coefficient": maybe_number,
                "snapshot_date": date,
            },
            evidence=True,
        ),
        "SignalMeasurement": _object(
            {
                "buckets": _array(_ref("SignalBucket")),
                "definition": text,
                "effective_sample_basis": maybe_text,
                "effective_sample_size": maybe_count,
                "evidence_verdict": {"type": "string", "enum": verdicts},
                "independent_expiry_cohorts": count,
                "information_coefficient": _ref("SignalInformationCoefficient"),
                "measured_date_count": maybe_count,
                "observation_count": count,
                "per_date": _array(_ref("SignalPerDate")),
                "raw_information_coefficient": _ref("SignalRawInformationCoefficient"),
                "reason_code": maybe_text,
                "status": {"type": "string", "enum": ["blocked", "measured"]},
            },
            required=(
                "status",
                "reason_code",
                "definition",
                "observation_count",
                "independent_expiry_cohorts",
                "measured_date_count",
                "effective_sample_size",
                "effective_sample_basis",
                "evidence_verdict",
            ),
            evidence=True,
        ),
        "SignalCollinearityPair": _object(
            {
                "signals": {"type": "array", "items": text, "minItems": 2, "maxItems": 2},
                "mean_rank_correlation": {"type": "number", "minimum": -1, "maximum": 1},
                "measured_date_count": count,
            },
            required=("signals", "mean_rank_correlation", "measured_date_count"),
            evidence=True,
        ),
        "SignalCollinearity": _object(
            {
                "method": text,
                "equivalence_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "pairs": _array(_ref("SignalCollinearityPair")),
                "rank_equivalent_pairs": _array(_ref("SignalCollinearityPair")),
                "distinct_signal_estimate": count,
                "note": text,
            },
            required=(
                "method",
                "equivalence_threshold",
                "pairs",
                "rank_equivalent_pairs",
                "distinct_signal_estimate",
                "note",
            ),
            evidence=True,
        ),
        "SeriesConfig": _object(
            {"max_instruments": count, "min_capture_dates": count},
            evidence=True,
        ),
        "SeriesLatest": _object(
            {
                "bid_usdc": maybe_number,
                "date": date,
                "dte_days": maybe_number,
                "model_delta": maybe_number,
                "residual_z": number,
            },
            evidence=True,
        ),
        "SeriesResidualSummary": _object(
            {
                "max": maybe_number,
                "mean": maybe_number,
                "min": maybe_number,
                "observation_count": count,
                "positive_share": maybe_number,
            },
            evidence=True,
        ),
        "SeriesPersistence": _object(
            {
                "basis": text,
                "coverage": maybe_number,
                "not_a_significance_test": text,
                "prior_observations": number,
                "raw_mean": maybe_number,
                "shrinkage_weight": number,
                "shrunk_mean": maybe_number,
            },
            evidence=True,
        ),
        "SeriesInstrumentPoint": _object(
            {
                "bid_usdc": maybe_number,
                "date": date,
                "dte_days": maybe_number,
                "mark_iv": maybe_number,
                "model_delta": maybe_number,
                "open_interest": maybe_number,
                "present": boolean,
                "residual_iv_points": maybe_number,
                "residual_z": number,
                "underlying_price": maybe_number,
            },
            required=("date", "present"),
            evidence=True,
        ),
        "SeriesInstrument": _object(
            {
                "capture_date_count": count,
                "expiry_date": date,
                "instrument_name": text,
                "latest": _ref("SeriesLatest"),
                "missing_date_count": count,
                "option_type": {"type": ["string", "null"], "enum": ["call", "put", None]},
                "persistence": _ref("SeriesPersistence"),
                "points": _array(_ref("SeriesInstrumentPoint")),
                "residual_z": _ref("SeriesResidualSummary"),
                "strike_price": maybe_number,
            },
            required=(
                "capture_date_count",
                "expiry_date",
                "instrument_name",
                "latest",
                "missing_date_count",
                "option_type",
                "persistence",
                "points",
                "residual_z",
                "strike_price",
            ),
            evidence=True,
        ),
        "SeriesLegacyPoint": _object(
            {
                "observed_at": timestamp,
                "smile_residual_z": maybe_number,
                "model_delta": maybe_number,
            },
            evidence=True,
        ),
    }
    schemas["ResearchSignal"] = _object(
        {
            "schema_version": {
                "type": "string",
                "enum": ["signal_validation_report.v1", "signal_preflight.v1"],
            },
            "captured_at": timestamp,
            "generated_at": timestamp,
            "research_only": {"type": "boolean", "const": True},
            "status": {"type": "string", "enum": ["blocked", "projected", "measured"]},
            "headline": text,
            "note": text,
            "cannot_tell": strings,
            "collinearity": _ref("SignalCollinearity"),
            "snapshot_count": count,
            "t_stat_threshold": number,
            "usable_capture_dates": dates,
            "reason_codes": strings,
            "config": _ref("SignalConfig"),
            "summary": _ref("SignalSummary"),
            "pre_registration": _ref("SignalPreRegistration"),
            "signal_definitions": {"type": "object", "additionalProperties": text},
            "excluded_snapshots": _array(_ref("ArtifactCaptureExclusion")),
            "excluded_expiries": _array(_ref("ArtifactExpiryExclusion")),
            "sample": _ref("SignalSample"),
            "bands": {"type": "object", "additionalProperties": _ref("SignalBand")},
            "cohorts": _array(_ref("SignalCohort")),
            "signals": {"type": "object", "additionalProperties": _ref("SignalMeasurement")},
        },
        required=("schema_version",),
        evidence=True,
    )
    schemas["ResearchSeries"] = _object(
        {
            "schema_version": {
                "type": "string",
                "enum": ["instrument_series_history.v1", "series_history.v1"],
            },
            "captured_at": timestamp,
            "generated_at": timestamp,
            "research_only": {"type": "boolean", "const": True},
            "status": {"type": "string", "enum": ["blocked", "measured"]},
            "primary_series": {"type": "string", "const": "residual_z"},
            "primary_series_reason": text,
            "instrument_count": count,
            "capture_count": count,
            "truncated_instruments": count,
            "usable_capture_dates": dates,
            "reason_codes": strings,
            "capture_dates": dates,
            "cannot_tell": strings,
            "config": _ref("SeriesConfig"),
            "excluded_captures": _array(_ref("ArtifactCaptureExclusion")),
            "excluded_expiries": _array(_ref("ArtifactExpiryExclusion")),
            "instruments": _array(_ref("SeriesInstrument")),
            "points": _array(_ref("SeriesLegacyPoint")),
        },
        required=("schema_version",),
        evidence=True,
    )
    for name in ("ResearchSignal", "ResearchSeries"):
        schemas[name]["anyOf"] = [
            {"required": ["captured_at"]},
            {"required": ["generated_at"]},
        ]
    return schemas
