"""Frozen historical replay protocol for strategy-brief history claims.

This module does not open or infer any real holdout result. It freezes the
protocol, the state machine, and the immutable artifact shape that a later
history run must satisfy before a strategy card may show historical win-rate
numbers.

The important distinction is between *having a protocol* and *having a
validated result*. A strategy can have a fully specified replay boundary today
while still remaining `EXPLORATORY` or `INSUFFICIENT` because no future holdout
has been collected and opened under that boundary yet.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ._canonical import canonical_sha256

STRATEGY_HISTORY_SCHEMA_VERSION = "strategy_brief_history.v1"
DEFAULT_PROTOCOL_DOCUMENT = (
    "docs/product/strategy-brief-historical-protocols-v1.md"
)
LEGACY_BEAR_CALL_PROTOCOL_DOCUMENT = "docs/automation/strategy-eval-spec.md"

SUPPORTED_STRUCTURES = frozenset(
    {
        "BULL_PUT_CREDIT_SPREAD",
        "BEAR_CALL_CREDIT_SPREAD",
        "IRON_CONDOR",
    }
)
STATUS_VALUES = frozenset({"INSUFFICIENT", "EXPLORATORY", "VALIDATED", "FAILED"})
ENTRY_ROLE_VALUES = frozenset({"development", "holdout"})
ENTRY_SOURCE_VALUES = frozenset({"development_inventory", "future_holdout"})

EXIT_BASIS = "hold_to_expiry"
MIN_INDEPENDENT_COHORTS = 8
MIN_OBSERVATIONS = 100
MAX_REGIME_SHARE = 0.60
BOOTSTRAP_SEED = 20260812
BOOTSTRAP_CONFIDENCE_LEVEL = 0.95
COST_STRESS_MULTIPLIER = 1.5
EMBARGO_DAYS = 35
ENTRY_COST_BASIS = "SHORT_BID_LONG_ASK_WITH_ADVERSE_TICK"

_SUMMARY_KEYS = (
    "status",
    "win_rate",
    "mean_net_r",
    "independent_cohorts",
    "observation_count",
    "structure_type",
    "direction",
    "dte_band_days",
    "entry_cost_basis",
    "exit_basis",
    "protocol_hash",
    "scope_verified",
    "artifact_id",
)

_SUFFICIENCY_REASON_CODES = {
    "cohorts": "INSUFFICIENT_INDEPENDENT_COHORTS",
    "observations": "INSUFFICIENT_STRATEGY_OBSERVATIONS",
    "regime_coverage": "INSUFFICIENT_REGIME_COVERAGE",
}
_GATE_REASON_CODES = {
    "bounded_loss": "UNBOUNDED_OR_UNKNOWN_MAX_LOSS",
    "unit_consistency": "UNKNOWN_PREMIUM_OR_PAYOFF_UNIT",
    "bootstrap_positive": "BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE",
    "same_structure_comparator_positive": "SAME_STRUCTURE_COMPARATOR_NOT_POSITIVE",
    "cost_stress_positive": "COST_STRESS_NOT_POSITIVE",
    "no_trade_positive": "NO_TRADE_BASELINE_NOT_BEATEN",
    "drawdown_limit": "MAX_DRAWDOWN_LIMIT_BREACH",
    "cvar_limit": "CVAR_LIMIT_BREACH",
    "single_cohort_concentration": "SINGLE_COHORT_CONCENTRATION_BREACH",
    "single_month_concentration": "SINGLE_MONTH_CONCENTRATION_BREACH",
    "per_trade_risk_budget": "PER_TRADE_RISK_BUDGET_BREACH",
    "same_expiry_risk_budget": "SAME_EXPIRY_RISK_BUDGET_BREACH",
    "margin_budget": "MARGIN_BUDGET_BREACH",
}
_AUDIT_REASON_CODES = {
    "missing_preregistered_protocol": "MISSING_PREREGISTERED_PROTOCOL",
    "protocol_frozen_too_late": "PROTOCOL_FROZEN_AFTER_HOLDOUT_CAPTURE",
    "missing_access_receipt": "MISSING_HOLDOUT_ACCESS_RECEIPT",
    "access_receipt_invalid": "INVALID_HOLDOUT_ACCESS_RECEIPT",
}


def build_strategy_history_protocol(
    *,
    structure_type: str,
    frozen_at: str,
    protocol_document: str = DEFAULT_PROTOCOL_DOCUMENT,
) -> dict[str, Any]:
    """Freeze the replay boundary for one supported strategy family."""

    metadata = _structure_metadata(structure_type)
    return {
        "frozen": True,
        "frozen_at": frozen_at,
        "protocol_document": protocol_document,
        "structure_alignment": {
            "structure_type": structure_type,
            "direction": metadata["direction"],
            "dte_band_days": [7, 35],
            "exit_basis": EXIT_BASIS,
            "same_live_and_replay_semantics": True,
        },
        "selection_policy": {
            "registered_strategy": metadata["registered_strategy"],
            "simple_same_structure_comparator": metadata["simple_comparator"],
            "tie_break_order": [
                "lower_combined_spread_ratio",
                "narrower_total_width",
                "instrument_name",
            ],
        },
        "fill_policy": {
            "short_legs": "bid_minus_one_adverse_tick",
            "long_legs": "ask_plus_one_adverse_tick",
            "fees_included": True,
            "slippage_included": True,
            "unfillable_if_missing_positive_two_sided_quotes": True,
            "unfillable_if_missing_tick_size": True,
        },
        "settlement_policy": {
            "settlement_basis": "official_expiry_settlement",
            "settlement_clock": "08:00 UTC",
            "fees_model": "deribit_base_fee_schedule",
            "delivery_fee_model": "official_delivery_fee_schedule",
        },
        "sample_exclusion_policy": {
            "drop_duplicates": True,
            "drop_overlapping_label_intervals": True,
            "drop_invalid_or_stale_quotes": True,
            "drop_incomplete_settlement": True,
            "drop_quarantined_rows": True,
        },
        "walk_forward": {
            "method": "purged_expiry_cohort_walk_forward",
            "purge_basis": "overlapping_label_intervals",
            "embargo_days": EMBARGO_DAYS,
            "fold_style": "expanding_chronological",
        },
        "comparators": [
            {
                "name": "no_trade",
                "definition": (
                    "Flat NAV, zero turnover, zero drawdown, zero tail loss, and "
                    "zero realized PnL."
                ),
            },
            {
                "name": "same_structure_simple",
                "definition": metadata["same_structure_comparator_definition"],
            },
        ],
        "bootstrap": {
            "unit": "independent_expiry_cohorts",
            "seed": BOOTSTRAP_SEED,
            "resamples": 10_000,
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
        },
        "cost_stress": {
            "mode": "multiply_all_modeled_costs",
            "multiplier": COST_STRESS_MULTIPLIER,
        },
        "regime_and_risk_gates": {
            "min_independent_cohorts": MIN_INDEPENDENT_COHORTS,
            "min_observations": MIN_OBSERVATIONS,
            "min_unique_regimes_per_dimension": 2,
            "max_regime_share": MAX_REGIME_SHARE,
            "max_drawdown_pct_nav": 0.10,
            "max_cvar_95_pct_nav": 0.03,
            "max_single_cohort_profit_share": 0.40,
            "max_single_month_profit_share": 0.40,
            "max_loss_per_trade_pct_nav": 0.015,
            "max_same_expiry_loss_pct_nav": 0.03,
            "max_new_margin_pct_nav": 0.08,
            "require_bounded_loss": True,
            "require_known_margin": True,
            "require_consistent_units": True,
        },
        "boundary_reference": metadata["boundary_reference"],
    }


def build_strategy_history_artifact(
    *,
    structure_type: str,
    generated_at: str,
    cohort_ledger: list[dict[str, Any]],
    exploratory_metrics: dict[str, Any] | None = None,
    holdout_status: str = "pending",
    holdout_metrics: dict[str, Any] | None = None,
    walk_forward_folds: list[dict[str, Any]] | None = None,
    frozen_protocol: dict[str, Any] | None = None,
    access_receipt: dict[str, Any] | None = None,
    protocol_document: str = DEFAULT_PROTOCOL_DOCUMENT,
) -> dict[str, Any]:
    """Build an immutable history artifact and derive the public state."""

    protocol = deepcopy(frozen_protocol) if isinstance(frozen_protocol, dict) else None
    if protocol is None:
        protocol = build_strategy_history_protocol(
            structure_type=structure_type,
            frozen_at=generated_at,
            protocol_document=protocol_document,
        )
    entries = _normalize_cohort_ledger(cohort_ledger)
    ledger_summary = _summarize_ledger(entries)
    normalized_receipt = _normalize_access_receipt(access_receipt)
    holdout = _holdout_metadata(
        holdout_status=holdout_status,
        entries=entries,
        protocol=protocol,
        access_receipt=normalized_receipt,
        protocol_was_supplied=isinstance(frozen_protocol, dict),
    )
    development_regimes = _regime_summary(
        ledger_entries=entries,
        sample_role="development",
    )
    holdout_regimes = _regime_summary(
        ledger_entries=entries,
        sample_role="holdout",
    )
    active_counts = (
        holdout["settled_independent_cohorts"],
        holdout["observation_count"],
        holdout_regimes,
    )
    if holdout["status"] != "evaluated":
        active_counts = (
            ledger_summary["development_independent_cohorts"],
            ledger_summary["development_observation_count"],
            development_regimes,
        )

    sufficiency = _sufficiency(
        independent_cohorts=active_counts[0],
        observation_count=active_counts[1],
        regimes=active_counts[2],
    )
    gates = _gate_report(holdout_metrics)
    status, reason_codes = _derive_status(
        holdout=holdout,
        sufficiency=sufficiency,
        gates=gates,
    )
    walk_forward = {
        "method": protocol["walk_forward"]["method"],
        "purge_basis": protocol["walk_forward"]["purge_basis"],
        "embargo_days": protocol["walk_forward"]["embargo_days"],
        "fold_style": protocol["walk_forward"]["fold_style"],
        "folds": _normalize_walk_forward_folds(walk_forward_folds or []),
        "metadata_status": (
            "frozen_pending_future_holdout"
            if holdout["status"] != "evaluated"
            else "recorded"
        ),
    }
    performance = {
        "exploratory": _normalize_metrics(exploratory_metrics),
        "holdout": _normalize_metrics(holdout_metrics),
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
            "lower_mean_net_r": _metric_value(
                holdout_metrics, "bootstrap_lower_mean_net_r"
            ),
        },
        "cost_stress": {
            "multiplier": COST_STRESS_MULTIPLIER,
            "mean_net_r_after_stress": _metric_value(
                holdout_metrics, "cost_stress_mean_net_r"
            ),
        },
        "comparators": {
            "no_trade_mean_net_r": 0.0,
            "same_structure_paired_mean_net_r_diff": _metric_value(
                holdout_metrics, "paired_comparator_mean_net_r_diff"
            ),
        },
    }
    artifact = {
        "schema_version": STRATEGY_HISTORY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "structure_type": structure_type,
        "direction": protocol["structure_alignment"]["direction"],
        "status": status,
        "exit_basis": EXIT_BASIS,
        "protocol": protocol,
        "cohort_ledger": {
            "entries": entries,
            "summary": ledger_summary,
        },
        "walk_forward": walk_forward,
        "holdout": holdout,
        "regime_coverage": {
            "development": development_regimes,
            "holdout": holdout_regimes,
            "active_sample": (
                "holdout" if holdout["status"] == "evaluated" else "development"
            ),
        },
        "performance": performance,
        "gates": gates,
        "reason_codes": reason_codes,
        "access_receipt": normalized_receipt,
        "notes": _notes_for_state(
            status=status,
            structure_type=structure_type,
            holdout=holdout,
        ),
        "manifest": _manifest(
            protocol=protocol,
            entries=entries,
            walk_forward=walk_forward,
            exploratory_metrics=exploratory_metrics,
            holdout_metrics=holdout_metrics,
            access_receipt=normalized_receipt,
        ),
    }
    artifact["public_summary"] = project_strategy_history_summary(artifact)
    artifact["manifest"]["content_addressed"] = True
    artifact["result_hash"] = _result_hash(artifact)
    artifact["artifact_id"] = f"strategy-history:{artifact['result_hash']}"
    artifact["public_summary"]["artifact_id"] = artifact["artifact_id"]
    artifact["manifest"]["result_hash"] = artifact["result_hash"]
    return artifact


def project_strategy_history_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    """Project the strategy-card history slice.

    Only `VALIDATED` may expose win-rate or mean net-R to the ordinary card.
    """

    status = str(artifact.get("status") or "")
    holdout = artifact.get("holdout") or {}
    ledger = ((artifact.get("cohort_ledger") or {}).get("summary")) or {}

    if holdout.get("status") == "evaluated":
        independent_cohorts = int(holdout.get("settled_independent_cohorts") or 0)
        observation_count = int(holdout.get("observation_count") or 0)
    else:
        independent_cohorts = int(ledger.get("development_independent_cohorts") or 0)
        observation_count = int(ledger.get("development_observation_count") or 0)

    performance = (artifact.get("performance") or {}).get("holdout") or {}
    win_rate = performance.get("win_rate") if status == "VALIDATED" else None
    mean_net_r = performance.get("mean_net_r") if status == "VALIDATED" else None
    protocol_hash = (
        ((artifact.get("manifest") or {}).get("component_hashes") or {}).get(
            "protocol_payload"
        )
    )
    history_binding_key = _history_binding_key_from_artifact(artifact)

    return {
        "status": status,
        "win_rate": win_rate,
        "mean_net_r": mean_net_r,
        "independent_cohorts": independent_cohorts,
        "observation_count": observation_count,
        "structure_type": artifact.get("structure_type"),
        "direction": artifact.get("direction"),
        "dte_band_days": [7, 35],
        "entry_cost_basis": ENTRY_COST_BASIS,
        "exit_basis": EXIT_BASIS,
        "protocol_hash": protocol_hash,
        "history_binding_key": history_binding_key,
        "scope_verified": status == "VALIDATED",
        "artifact_id": artifact.get("artifact_id"),
    }


def validate_strategy_history_artifact(value: Any) -> list[str]:
    """Validate the frozen history artifact and its public invariants."""

    if not isinstance(value, dict):
        return ["strategy_history artifact must be a dict"]

    errors: list[str] = []
    if value.get("schema_version") != STRATEGY_HISTORY_SCHEMA_VERSION:
        errors.append(
            "strategy_history.schema_version must be strategy_brief_history.v1"
        )
    if value.get("structure_type") not in SUPPORTED_STRUCTURES:
        errors.append("strategy_history.structure_type is invalid")
    if value.get("status") not in STATUS_VALUES:
        errors.append("strategy_history.status is invalid")
    if value.get("exit_basis") != EXIT_BASIS:
        errors.append("strategy_history.exit_basis must be hold_to_expiry")

    protocol = value.get("protocol")
    if not isinstance(protocol, dict):
        errors.append("strategy_history.protocol must be a dict")
    else:
        errors.extend(_validate_protocol(protocol, value.get("structure_type")))

    public_summary = value.get("public_summary")
    if not isinstance(public_summary, dict):
        errors.append("strategy_history.public_summary must be a dict")
    else:
        errors.extend(_validate_public_summary(value, public_summary))

    holdout = value.get("holdout")
    if not isinstance(holdout, dict):
        errors.append("strategy_history.holdout must be a dict")
    else:
        errors.extend(_validate_holdout(value, holdout))

    access_receipt = value.get("access_receipt")
    if access_receipt is not None and not isinstance(access_receipt, dict):
        errors.append("strategy_history.access_receipt must be a dict when present")

    ledger = value.get("cohort_ledger")
    if not isinstance(ledger, dict):
        errors.append("strategy_history.cohort_ledger must be a dict")
    else:
        errors.extend(_validate_ledger(ledger))

    gates = value.get("gates")
    if not isinstance(gates, dict):
        errors.append("strategy_history.gates must be a dict")
    else:
        errors.extend(_validate_gates(value, gates))

    if value.get("artifact_id") != f"strategy-history:{value.get('result_hash')}":
        errors.append("strategy_history.artifact_id must match the result hash")
    if value.get("result_hash") != _result_hash(value):
        errors.append("strategy_history.result_hash must match the canonical payload")

    return errors


def _structure_metadata(structure_type: str) -> dict[str, Any]:
    if structure_type not in SUPPORTED_STRUCTURES:
        raise ValueError(f"unsupported strategy history structure: {structure_type!r}")

    if structure_type == "BEAR_CALL_CREDIT_SPREAD":
        return {
            "direction": "bearish",
            "registered_strategy": (
                "Sell the call closest to absolute delta 0.10 inside 7-35 DTE and "
                "buy the nearest higher listed call up to USD 5,000 wider."
            ),
            "simple_comparator": "legacy_call_credit_spread_boundary",
            "same_structure_comparator_definition": (
                "Use the existing CALL_CREDIT_SPREAD frozen boundary as the same-"
                "economics defined-risk comparator for the bear-call direction."
            ),
            "boundary_reference": {
                "inherits_legacy_bear_call_boundary": True,
                "legacy_structure": "CALL_CREDIT_SPREAD",
                "legacy_protocol_document": LEGACY_BEAR_CALL_PROTOCOL_DOCUMENT,
                "note": (
                    "The currently frozen CALL_CREDIT_SPREAD boundary is the bear-"
                    "call direction and may be referenced here, but not borrowed by "
                    "bull-put or iron-condor histories."
                ),
            },
        }
    if structure_type == "BULL_PUT_CREDIT_SPREAD":
        return {
            "direction": "bullish",
            "registered_strategy": (
                "Sell the put closest to absolute delta 0.10 inside 7-35 DTE and "
                "buy the nearest lower listed put up to USD 5,000 wider."
            ),
            "simple_comparator": "same_structure_simple_bull_put",
            "same_structure_comparator_definition": (
                "Use the same expiry universe and quote gates, then select the bull "
                "put spread with the short put closest to absolute delta 0.10 and "
                "the nearest lower listed long put."
            ),
            "boundary_reference": {
                "inherits_legacy_bear_call_boundary": False,
                "legacy_structure": None,
                "legacy_protocol_document": None,
                "note": (
                    "Bull-put history must keep its own aligned replay, protocol, "
                    "and future holdout. It may not borrow bear-call validation."
                ),
            },
        }
    return {
        "direction": "neutral",
        "registered_strategy": (
            "Select the put spread and call spread legs independently inside 7-35 "
            "DTE, each with a short leg closest to absolute delta 0.10, then join "
            "them into one defined-risk iron condor."
        ),
        "simple_comparator": "same_structure_simple_iron_condor",
        "same_structure_comparator_definition": (
            "Use the same expiry universe and quote gates, then choose the simplest "
            "same-expiry iron condor assembled from one short put, one long put, "
            "one short call, and one long call under the frozen tie-break rules."
        ),
        "boundary_reference": {
            "inherits_legacy_bear_call_boundary": False,
            "legacy_structure": None,
            "legacy_protocol_document": None,
            "note": (
                "Iron-condor history must keep its own aligned replay, protocol, "
                "and future holdout. It may not borrow bear-call validation."
            ),
        },
    }


def _normalize_cohort_ledger(cohort_ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(cohort_ledger, list):
        raise ValueError("cohort_ledger must be a list")
    normalized: list[dict[str, Any]] = []
    for entry in cohort_ledger:
        if not isinstance(entry, dict):
            raise ValueError("cohort_ledger entries must be objects")
        sample_role = str(entry.get("sample_role") or "")
        source_classification = str(entry.get("source_classification") or "")
        if sample_role not in ENTRY_ROLE_VALUES:
            raise ValueError("cohort_ledger.sample_role is invalid")
        if source_classification not in ENTRY_SOURCE_VALUES:
            raise ValueError("cohort_ledger.source_classification is invalid")
        observation_count = _required_int(
            entry.get("observation_count"), "cohort_ledger.observation_count"
        )
        duplicate_dropped = _non_negative_int(
            entry.get("duplicate_observations_dropped"), default=0
        )
        overlap_dropped = _non_negative_int(
            entry.get("overlap_observations_dropped"), default=0
        )
        purged_training = _non_negative_int(
            entry.get("purged_training_observations"), default=0
        )
        normalized.append(
            {
                "cohort_id": str(
                    entry.get("cohort_id")
                    or f"{sample_role}:{entry.get('expiry_date') or len(normalized)}"
                ),
                "expiry_date": str(entry.get("expiry_date") or ""),
                "sample_role": sample_role,
                "source_classification": source_classification,
                "settled": entry.get("settled") is True,
                "observation_count": observation_count,
                "duplicate_observations_dropped": duplicate_dropped,
                "overlap_observations_dropped": overlap_dropped,
                "purged_training_observations": purged_training,
                "captured_at": (
                    str(entry["captured_at"])
                    if entry.get("captured_at") is not None
                    else None
                ),
                "settled_at": (
                    str(entry["settled_at"])
                    if entry.get("settled_at") is not None
                    else None
                ),
                "embargoed_until": (
                    str(entry["embargoed_until"])
                    if entry.get("embargoed_until") is not None
                    else None
                ),
                "volatility_regime": str(entry.get("volatility_regime") or "unknown"),
                "trend_regime": str(entry.get("trend_regime") or "unknown"),
                "liquidity_regime": str(entry.get("liquidity_regime") or "unknown"),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            item["sample_role"],
            item["expiry_date"],
            item["cohort_id"],
        ),
    )


def _summarize_ledger(entries: list[dict[str, Any]]) -> dict[str, Any]:
    development = [
        entry
        for entry in entries
        if entry["sample_role"] == "development" and entry["settled"]
    ]
    holdout = [
        entry
        for entry in entries
        if entry["sample_role"] == "holdout" and entry["settled"]
    ]
    return {
        "development_independent_cohorts": len({entry["cohort_id"] for entry in development}),
        "development_observation_count": sum(
            entry["observation_count"] for entry in development
        ),
        "holdout_independent_cohorts": len({entry["cohort_id"] for entry in holdout}),
        "holdout_observation_count": sum(entry["observation_count"] for entry in holdout),
        "duplicate_observations_dropped": sum(
            entry["duplicate_observations_dropped"] for entry in entries
        ),
        "overlap_observations_dropped": sum(
            entry["overlap_observations_dropped"] for entry in entries
        ),
        "purged_training_observations": sum(
            entry["purged_training_observations"] for entry in entries
        ),
        "embargo_days": EMBARGO_DAYS,
    }


def _holdout_metadata(
    *,
    holdout_status: str,
    entries: list[dict[str, Any]],
    protocol: dict[str, Any],
    access_receipt: dict[str, Any] | None,
    protocol_was_supplied: bool,
) -> dict[str, Any]:
    if holdout_status not in {"pending", "sealed", "evaluated"}:
        raise ValueError("holdout_status must be pending, sealed, or evaluated")
    holdout_entries = [
        entry for entry in entries if entry["sample_role"] == "holdout" and entry["settled"]
    ]
    source_values = sorted({entry["source_classification"] for entry in holdout_entries})
    future_only = all(
        entry["source_classification"] == "future_holdout" for entry in holdout_entries
    )
    preregistered = protocol_was_supplied and _protocol_predates_holdout(
        protocol=protocol,
        holdout_entries=holdout_entries,
    )
    audit = _holdout_audit(
        holdout_status=holdout_status,
        protocol_was_supplied=protocol_was_supplied,
        preregistered=preregistered,
        access_receipt=access_receipt,
    )
    return {
        "status": holdout_status,
        "outcomes_inspected": holdout_status == "evaluated",
        "settled_independent_cohorts": len({entry["cohort_id"] for entry in holdout_entries}),
        "observation_count": sum(entry["observation_count"] for entry in holdout_entries),
        "source_classifications": source_values,
        "future_only": future_only if holdout_entries else False,
        "protocol_preregistered": preregistered,
        "audit": audit,
        "eligible_for_validation": (
            holdout_status == "evaluated"
            and future_only
            and preregistered
            and audit["passed"]
        ),
    }


def _regime_summary(
    *,
    ledger_entries: list[dict[str, Any]],
    sample_role: str,
) -> dict[str, Any]:
    relevant = [
        entry
        for entry in ledger_entries
        if entry["sample_role"] == sample_role and entry["settled"]
    ]
    return {
        "volatility": _dimension_regime_summary(relevant, "volatility_regime"),
        "trend": _dimension_regime_summary(relevant, "trend_regime"),
        "liquidity": _dimension_regime_summary(relevant, "liquidity_regime"),
    }


def _dimension_regime_summary(
    entries: list[dict[str, Any]],
    field_name: str,
) -> dict[str, Any]:
    labels = [str(entry.get(field_name) or "unknown") for entry in entries]
    if not labels:
        return {
            "labels": [],
            "unique_count": 0,
            "max_share": None,
            "passes_diversity": False,
            "passes_concentration": False,
        }
    counts = Counter(labels)
    total = sum(counts.values())
    max_share = max(count / total for count in counts.values()) if total else None
    return {
        "labels": sorted(counts),
        "unique_count": len(counts),
        "max_share": round(max_share, 6) if max_share is not None else None,
        "passes_diversity": len(counts) >= 2,
        "passes_concentration": max_share is not None and max_share <= MAX_REGIME_SHARE,
    }


def _sufficiency(
    *,
    independent_cohorts: int,
    observation_count: int,
    regimes: dict[str, Any],
) -> dict[str, Any]:
    regime_ok = all(
        isinstance(regimes.get(name), dict)
        and regimes[name].get("passes_diversity") is True
        and regimes[name].get("passes_concentration") is True
        for name in ("volatility", "trend", "liquidity")
    )
    reasons: list[str] = []
    if independent_cohorts < MIN_INDEPENDENT_COHORTS:
        reasons.append(_SUFFICIENCY_REASON_CODES["cohorts"])
    if observation_count < MIN_OBSERVATIONS:
        reasons.append(_SUFFICIENCY_REASON_CODES["observations"])
    if not regime_ok:
        reasons.append(_SUFFICIENCY_REASON_CODES["regime_coverage"])
    return {
        "passed": not reasons,
        "reason_codes": reasons,
        "independent_cohorts": independent_cohorts,
        "observation_count": observation_count,
    }


def _gate_report(holdout_metrics: dict[str, Any] | None) -> dict[str, Any]:
    metrics = _normalize_metrics(holdout_metrics)
    checks = {
        "bounded_loss": (
            metrics.get("loss_is_bounded") is True
            and metrics.get("max_loss_known") is True
            and metrics.get("margin_known") is True
        ),
        "unit_consistency": (
            metrics.get("premium_unit_consistent") is True
            and metrics.get("payoff_currency_consistent") is True
        ),
        "bootstrap_positive": _greater_than_zero(
            metrics.get("bootstrap_lower_mean_net_r")
        ),
        "same_structure_comparator_positive": _greater_than_zero(
            metrics.get("paired_comparator_mean_net_r_diff")
        ),
        "cost_stress_positive": _greater_than_zero(
            metrics.get("cost_stress_mean_net_r")
        ),
        "no_trade_positive": _greater_than_zero(metrics.get("mean_net_r")),
        "drawdown_limit": _at_most(metrics.get("max_drawdown_pct_nav"), 0.10),
        "cvar_limit": _at_most(metrics.get("cvar_95_pct_nav"), 0.03),
        "single_cohort_concentration": _at_most(
            metrics.get("max_single_cohort_profit_share"), 0.40
        ),
        "single_month_concentration": _at_most(
            metrics.get("max_single_month_profit_share"), 0.40
        ),
        "per_trade_risk_budget": _at_most(
            metrics.get("max_loss_per_trade_pct_nav"), 0.015
        ),
        "same_expiry_risk_budget": _at_most(
            metrics.get("same_expiry_max_loss_pct_nav"), 0.03
        ),
        "margin_budget": _at_most(metrics.get("new_margin_pct_nav"), 0.08),
    }
    failures = [
        reason_code
        for gate_name, reason_code in _GATE_REASON_CODES.items()
        if checks[gate_name] is False
    ]
    return {
        "checks": checks,
        "reason_codes": failures,
    }


def _derive_status(
    *,
    holdout: dict[str, Any],
    sufficiency: dict[str, Any],
    gates: dict[str, Any],
) -> tuple[str, list[str]]:
    if holdout["status"] != "evaluated":
        if sufficiency["passed"]:
            return "EXPLORATORY", ["FUTURE_HOLDOUT_NOT_YET_AVAILABLE"]
        return "INSUFFICIENT", list(sufficiency["reason_codes"])

    if not holdout.get("future_only"):
        return "FAILED", ["HOLDOUT_SOURCE_NOT_FUTURE_ONLY"]
    audit = holdout.get("audit") or {}
    if audit.get("passed") is not True:
        return "FAILED", list(audit.get("reason_codes") or [])
    if not holdout.get("protocol_preregistered"):
        return "FAILED", [_AUDIT_REASON_CODES["protocol_frozen_too_late"]]
    if not sufficiency["passed"]:
        return "INSUFFICIENT", list(sufficiency["reason_codes"])
    if gates["reason_codes"]:
        return "FAILED", list(gates["reason_codes"])
    return "VALIDATED", []


def _normalize_walk_forward_folds(
    walk_forward_folds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for fold in walk_forward_folds:
        if not isinstance(fold, dict):
            raise ValueError("walk_forward_folds entries must be objects")
        normalized.append(
            {
                "fold_id": str(fold.get("fold_id") or f"fold-{len(normalized) + 1}"),
                "train_end": (
                    str(fold["train_end"]) if fold.get("train_end") is not None else None
                ),
                "validation_start": (
                    str(fold["validation_start"])
                    if fold.get("validation_start") is not None
                    else None
                ),
                "validation_end": (
                    str(fold["validation_end"])
                    if fold.get("validation_end") is not None
                    else None
                ),
                "embargo_days": _non_negative_int(
                    fold.get("embargo_days"), default=EMBARGO_DAYS
                ),
            }
        )
    return normalized


def _normalize_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if metrics is None:
        return {}
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a dict when provided")
    normalized: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            normalized[key] = value
        elif isinstance(value, (int, float)):
            normalized[key] = float(value)
        else:
            normalized[key] = value
    return normalized


def _metric_value(metrics: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _manifest(
    *,
    protocol: dict[str, Any],
    entries: list[dict[str, Any]],
    walk_forward: dict[str, Any],
    exploratory_metrics: dict[str, Any] | None,
    holdout_metrics: dict[str, Any] | None,
    access_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "content_addressed": False,
        "protocol_document": protocol["protocol_document"],
        "component_hashes": {
            "protocol_document": _file_sha256(_repo_path(protocol["protocol_document"])),
            "implementation_module": _file_sha256(Path(__file__)),
            "protocol_payload": canonical_sha256(protocol),
            "cohort_ledger": canonical_sha256(entries),
            "walk_forward": canonical_sha256(walk_forward),
            "exploratory_metrics": canonical_sha256(
                _normalize_metrics(exploratory_metrics)
            ),
            "holdout_metrics": canonical_sha256(_normalize_metrics(holdout_metrics)),
            "access_receipt": canonical_sha256(access_receipt or {}),
        },
    }


def build_holdout_access_receipt(
    *,
    accessed_at: str,
    command_hash: str,
    input_hash: str,
    result_hash: str,
    verified_source: str,
) -> dict[str, Any]:
    return {
        "accessed_at": accessed_at,
        "command_hash": str(command_hash),
        "input_hash": str(input_hash),
        "result_hash": str(result_hash),
        "access_count": 1,
        "rerun_count": 0,
        "previously_viewed": False,
        "tuned_after": False,
        "verified_source": str(verified_source),
    }


def _normalize_access_receipt(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("access_receipt must be a dict when provided")
    return {
        "accessed_at": str(value.get("accessed_at") or ""),
        "command_hash": str(value.get("command_hash") or ""),
        "input_hash": str(value.get("input_hash") or ""),
        "result_hash": str(value.get("result_hash") or ""),
        "access_count": _required_int(
            value.get("access_count"), "access_receipt.access_count"
        ),
        "rerun_count": _required_int(
            value.get("rerun_count"), "access_receipt.rerun_count"
        ),
        "previously_viewed": value.get("previously_viewed") is True,
        "tuned_after": value.get("tuned_after") is True,
        "verified_source": str(value.get("verified_source") or ""),
    }


def _protocol_predates_holdout(
    *,
    protocol: dict[str, Any],
    holdout_entries: list[dict[str, Any]],
) -> bool:
    frozen_at = _maybe_parse_datetime(protocol.get("frozen_at"))
    if frozen_at is None or not holdout_entries:
        return False
    for entry in holdout_entries:
        captured_at = _maybe_parse_datetime(entry.get("captured_at"))
        settled_at = _maybe_parse_datetime(entry.get("settled_at"))
        if captured_at is None or settled_at is None:
            expiry_date = str(entry.get("expiry_date") or "")
            try:
                expiry_anchor = datetime.fromisoformat(
                    f"{expiry_date}T00:00:00+00:00"
                ).astimezone(UTC)
            except ValueError:
                return False
            captured_at = captured_at or expiry_anchor
            settled_at = settled_at or expiry_anchor
        if not (frozen_at < captured_at and frozen_at < settled_at):
            return False
    return True


def _holdout_audit(
    *,
    holdout_status: str,
    protocol_was_supplied: bool,
    preregistered: bool,
    access_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    if holdout_status != "evaluated":
        return {"passed": False, "reason_codes": []}
    reasons: list[str] = []
    if not protocol_was_supplied:
        reasons.append(_AUDIT_REASON_CODES["missing_preregistered_protocol"])
    elif not preregistered:
        reasons.append(_AUDIT_REASON_CODES["protocol_frozen_too_late"])
    if access_receipt is None:
        reasons.append(_AUDIT_REASON_CODES["missing_access_receipt"])
    elif not _is_valid_access_receipt(access_receipt):
        reasons.append(_AUDIT_REASON_CODES["access_receipt_invalid"])
    return {"passed": not reasons, "reason_codes": reasons}


def _is_valid_access_receipt(access_receipt: dict[str, Any]) -> bool:
    if _maybe_parse_datetime(access_receipt.get("accessed_at")) is None:
        return False
    if not all(
        isinstance(access_receipt.get(field), str) and access_receipt[field]
        for field in ("command_hash", "input_hash", "result_hash", "verified_source")
    ):
        return False
    if access_receipt.get("access_count") != 1:
        return False
    if access_receipt.get("rerun_count") != 0:
        return False
    if access_receipt.get("previously_viewed") is not False:
        return False
    if access_receipt.get("tuned_after") is not False:
        return False
    return access_receipt.get("verified_source") == "future_holdout"


def _notes_for_state(
    *,
    status: str,
    structure_type: str,
    holdout: dict[str, Any],
) -> list[str]:
    metadata = _structure_metadata(structure_type)
    notes = [metadata["boundary_reference"]["note"]]
    if status in {"INSUFFICIENT", "EXPLORATORY"} and holdout["status"] != "evaluated":
        notes.append(
            "The protocol is frozen, but no future aligned holdout has been opened "
            "for this strategy family yet."
        )
    if status == "FAILED":
        notes.append(
            "The holdout was sufficient to judge, but at least one frozen protocol "
            "gate failed or the holdout source was not future-only."
        )
    return notes


def _validate_protocol(protocol: dict[str, Any], structure_type: Any) -> list[str]:
    errors: list[str] = []
    alignment = protocol.get("structure_alignment") or {}
    if alignment.get("structure_type") != structure_type:
        errors.append(
            "strategy_history.protocol.structure_alignment.structure_type must match the artifact structure"
        )
    if alignment.get("dte_band_days") != [7, 35]:
        errors.append("strategy_history.protocol must freeze the 7-35 DTE band")
    if alignment.get("exit_basis") != EXIT_BASIS:
        errors.append("strategy_history.protocol must freeze hold_to_expiry")
    fill_policy = protocol.get("fill_policy") or {}
    if fill_policy.get("short_legs") != "bid_minus_one_adverse_tick":
        errors.append("strategy_history.protocol short fills must use bid minus adverse tick")
    if fill_policy.get("long_legs") != "ask_plus_one_adverse_tick":
        errors.append("strategy_history.protocol long fills must use ask plus adverse tick")
    walk_forward = protocol.get("walk_forward") or {}
    if walk_forward.get("embargo_days") != EMBARGO_DAYS:
        errors.append("strategy_history.protocol embargo must stay at 35 days")
    bootstrap = protocol.get("bootstrap") or {}
    if bootstrap.get("seed") != BOOTSTRAP_SEED:
        errors.append("strategy_history.protocol bootstrap seed must remain 20260812")
    cost_stress = protocol.get("cost_stress") or {}
    if cost_stress.get("multiplier") != COST_STRESS_MULTIPLIER:
        errors.append("strategy_history.protocol cost stress must remain 1.5x")
    boundary_reference = protocol.get("boundary_reference") or {}
    if structure_type == "BEAR_CALL_CREDIT_SPREAD":
        if boundary_reference.get("legacy_structure") != "CALL_CREDIT_SPREAD":
            errors.append(
                "bear-call strategy history must reference the CALL_CREDIT_SPREAD legacy boundary"
            )
    elif boundary_reference.get("legacy_structure") is not None:
        errors.append(
            "bull-put and iron-condor strategy histories must not borrow the bear-call legacy boundary"
        )
    return errors


def _validate_public_summary(
    artifact: dict[str, Any],
    public_summary: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    missing = [key for key in _SUMMARY_KEYS if key not in public_summary]
    if missing:
        errors.append(
            f"strategy_history.public_summary is missing {missing[0]}"
        )
        return errors
    if public_summary.get("status") != artifact.get("status"):
        errors.append("strategy_history.public_summary.status must match artifact status")
    if public_summary.get("structure_type") != artifact.get("structure_type"):
        errors.append(
            "strategy_history.public_summary.structure_type must match artifact structure_type"
        )
    if public_summary.get("direction") != artifact.get("direction"):
        errors.append(
            "strategy_history.public_summary.direction must match artifact direction"
        )
    if public_summary.get("dte_band_days") != [7, 35]:
        errors.append(
            "strategy_history.public_summary.dte_band_days must remain [7, 35]"
        )
    if public_summary.get("entry_cost_basis") != ENTRY_COST_BASIS:
        errors.append(
            "strategy_history.public_summary.entry_cost_basis must remain SHORT_BID_LONG_ASK_WITH_ADVERSE_TICK"
        )
    if public_summary.get("exit_basis") != EXIT_BASIS:
        errors.append("strategy_history.public_summary.exit_basis must be hold_to_expiry")
    protocol_hash = (
        ((artifact.get("manifest") or {}).get("component_hashes") or {}).get(
            "protocol_payload"
        )
    )
    if public_summary.get("protocol_hash") != protocol_hash:
        errors.append(
            "strategy_history.public_summary.protocol_hash must match the protocol payload hash"
        )
    history_binding_key = _history_binding_key_from_artifact(artifact)
    if (
        public_summary.get("history_binding_key") is not None
        and public_summary.get("history_binding_key") != history_binding_key
    ):
        errors.append(
            "strategy_history.public_summary.history_binding_key must match the stable protocol binding"
        )
    if public_summary.get("scope_verified") is not (artifact.get("status") == "VALIDATED"):
        errors.append(
            "strategy_history.public_summary.scope_verified must be true only for validated artifacts"
        )
    if artifact.get("status") != "VALIDATED":
        if public_summary.get("win_rate") is not None:
            errors.append(
                "non-validated strategy history must not expose public win_rate"
            )
        if public_summary.get("mean_net_r") is not None:
            errors.append(
                "non-validated strategy history must not expose public mean_net_r"
            )
    else:
        if not _is_probability(public_summary.get("win_rate")):
            errors.append("validated strategy history must expose a probability win_rate")
        if not _is_number(public_summary.get("mean_net_r")):
            errors.append("validated strategy history must expose mean_net_r")
    return errors


def _validate_holdout(artifact: dict[str, Any], holdout: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if holdout.get("status") not in {"pending", "sealed", "evaluated"}:
        errors.append("strategy_history.holdout.status is invalid")
    if holdout.get("status") == "evaluated":
        if holdout.get("outcomes_inspected") is not True:
            errors.append(
                "evaluated strategy_history.holdout must record outcomes_inspected=true"
            )
        if holdout.get("future_only") is not True:
            errors.append(
                "evaluated strategy_history.holdout must be sourced only from future holdout cohorts"
            )
        if holdout.get("protocol_preregistered") is not True:
            errors.append(
                "evaluated strategy_history.holdout must use a protocol frozen before every future holdout cohort"
            )
        audit = holdout.get("audit") or {}
        if audit.get("passed") is not True:
            errors.append(
                "evaluated strategy_history.holdout must provide one-time audited access receipt evidence"
            )
    if artifact.get("status") == "EXPLORATORY" and holdout.get("status") == "evaluated":
        errors.append(
            "exploratory strategy history cannot claim an evaluated holdout"
        )
    return errors


def _validate_ledger(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ["strategy_history.cohort_ledger.entries must be a list"]
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("strategy_history.cohort_ledger entries must be dicts")
            continue
        if entry.get("sample_role") not in ENTRY_ROLE_VALUES:
            errors.append("strategy_history.cohort_ledger entry sample_role is invalid")
        if entry.get("source_classification") not in ENTRY_SOURCE_VALUES:
            errors.append(
                "strategy_history.cohort_ledger entry source_classification is invalid"
            )
        if _non_negative_int(entry.get("observation_count"), default=-1) < 0:
            errors.append("strategy_history.cohort_ledger entry observation_count is invalid")
        if entry.get("sample_role") == "holdout" and (
            not entry.get("captured_at") or not entry.get("settled_at")
        ):
            errors.append(
                "holdout strategy_history.cohort_ledger entries must record captured_at and settled_at"
            )
    return errors


def _validate_gates(artifact: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checks = gates.get("checks")
    if not isinstance(checks, dict):
        return ["strategy_history.gates.checks must be a dict"]
    if artifact.get("status") == "VALIDATED" and not all(
        value is True for value in checks.values()
    ):
        errors.append("validated strategy history must pass every frozen gate")
    if artifact.get("status") == "FAILED" and all(value is True for value in checks.values()):
        holdout = artifact.get("holdout") or {}
        if holdout.get("eligible_for_validation") is True:
            errors.append(
                "failed strategy history must record a gate failure or invalid holdout source"
            )
    return errors


def _result_hash(artifact: dict[str, Any]) -> str:
    payload = deepcopy(artifact)
    payload.pop("artifact_id", None)
    payload.pop("result_hash", None)
    summary = payload.get("public_summary")
    if isinstance(summary, dict):
        summary["artifact_id"] = None
        summary.pop("history_binding_key", None)
    manifest = payload.get("manifest")
    if isinstance(manifest, dict):
        manifest.pop("result_hash", None)
    return canonical_sha256(payload)


def expected_history_binding_key(structure_type: str) -> str:
    protocol = build_strategy_history_protocol(
        structure_type=structure_type,
        frozen_at="2000-01-01T00:00:00Z",
    )
    return history_binding_key_from_protocol(protocol)


def history_binding_key_from_protocol(protocol: Any) -> str:
    if not isinstance(protocol, dict):
        raise ValueError("strategy history protocol must be a dict")
    payload = deepcopy(protocol)
    payload.pop("frozen_at", None)
    return f"history-binding:{canonical_sha256(payload)}"


def _history_binding_key_from_artifact(artifact: dict[str, Any]) -> str | None:
    protocol = artifact.get("protocol")
    if not isinstance(protocol, dict):
        return None
    try:
        return history_binding_key_from_protocol(protocol)
    except ValueError:
        return None


def _repo_path(relative_path: str) -> Path:
    return Path(__file__).resolve().parent.parent / relative_path


def _file_sha256(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _maybe_parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _non_negative_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected a non-negative integer")
    return value


def _greater_than_zero(value: Any) -> bool:
    return _is_number(value) and float(value) > 0.0


def _at_most(value: Any, ceiling: float) -> bool:
    return _is_number(value) and float(value) <= ceiling


def _is_probability(value: Any) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
