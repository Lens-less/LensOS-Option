"""Path-risk distribution tracer for ISSUE-009."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from ._time import utc_timestamp
from .structures import Structure, build_structure, call_credit_spread, naked_short_call

PATH_RISK_REPORT_SCHEMA_VERSION = "path_risk_distribution_report.v1"
DEFAULT_PATH_RISK_CONFIG = {
    "similarity_bandwidth": 0.08,
    "min_effective_sample_size": 2.0,
    "historical_group_weight": 0.75,
    "bootstrap_group_weight": 0.20,
    "stress_group_weight": 0.05,
    "stress_mixture_min_weight": 0.10,
    "confidence_penalty_multiplier": 0.50,
}
PATH_RISK_CONFIG_FIELDS = frozenset(DEFAULT_PATH_RISK_CONFIG)


# Volatility-scaling modes for the historical path set.
#
# `none` replays each historical window at the volatility it actually had. It is
# the default because rescaling every window to one target removes volatility
# clustering and cross-window volatility dispersion — precisely the structure
# that produces a short-volatility seller's tail losses — and would therefore
# understate CVaR while looking more precise.
#
# `evidence_target` rescales to a measured current volatility. Conditioning on
# today's volatility level is legitimate, but only against a stated measurement,
# so the target must arrive with evidence naming its source and as-of time.
VOL_SCALING_NONE = "none"
VOL_SCALING_EVIDENCE_TARGET = "evidence_target"
VOL_SCALING_MODES = frozenset({VOL_SCALING_NONE, VOL_SCALING_EVIDENCE_TARGET})

# A target supplied the legacy way — a bare number with nothing behind it — is
# still honoured so recorded fixtures keep replaying, but it is labelled in the
# report rather than passing as a measurement.
UNEVIDENCED_VOL_SCALING_TARGET = "UNEVIDENCED_VOL_SCALING_TARGET"


@dataclass(frozen=True)
class CandidateSpec:
    instrument_name: str
    structure: str
    current_spot: float
    strike: float
    long_strike: float | None
    horizon_days: int
    entry_credit_usdc: float
    contract_size: float
    starting_nav_usdc: float
    current_abs_delta: float
    delta_cross_up_return: float
    vega_usdc_per_abs_vol: float
    target_realized_vol: float | None
    vol_scaling_mode: str
    vol_scaling_evidence: dict[str, Any]
    regime_scores: dict[str, float]
    feature_vector: dict[str, float]
    # The legs behind `structure`. Every terminal-payoff question routes through
    # this rather than through a branch on the structure name, so a put spread
    # or a condor is priced by the same code that prices a short call.
    structure_legs: Structure = None  # type: ignore[assignment]


def load_path_risk_fixture(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_path_risk_report_from_fixture(
    fixture_path: str | Path,
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_path_risk_distribution_report(
        load_path_risk_fixture(fixture_path),
        generated_at=generated_at,
        config=config,
    )


def build_path_risk_report_from_historical_report(
    historical_report: dict[str, Any],
    candidate: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build path-risk evidence from eligible historical rows, never placeholders."""

    candidate_spec = _candidate_spec(candidate)
    eligible_quotes = list(
        (historical_report.get("canonical_data") or {}).get("eligible_quotes") or []
    )
    eligibility = historical_report.get("aggregate_eligibility") or historical_report.get("eligibility") or {}
    if eligibility.get("decision") != "ELIGIBLE":
        return _blocked_historical_path_report(
            candidate=candidate_spec,
            historical_report=historical_report,
            generated_at=generated_at,
            reason_codes=["HISTORICAL_RECONCILIATION_NOT_ELIGIBLE"],
        )

    paths = _historical_paths_from_quotes(
        eligible_quotes,
        candidate=candidate_spec,
    )
    if len(paths) < 2:
        return _blocked_historical_path_report(
            candidate=candidate_spec,
            historical_report=historical_report,
            generated_at=generated_at,
            reason_codes=["INSUFFICIENT_VALIDATED_HISTORICAL_PATHS"],
        )

    all_returns = [
        value
        for path in paths
        for value in path["returns"]
    ]
    payload = {
        "source": "validated_historical_reconciliation",
        "input_evidence": {
            "status": "validated_historical",
            "placeholder_data": False,
            "readiness_contribution": "validated_historical_path_risk",
            "historical_report_schema_version": historical_report.get("schema_version"),
            "historical_eligibility_decision": eligibility.get("decision"),
            "eligible_quote_count": len(eligible_quotes),
            "eligible_path_count": len(paths),
            "stress_window_coverage": "deterministic_shock_overlay",
            "sample_coverage": {
                "eligible_quotes": len(eligible_quotes),
                "eligible_paths": len(paths),
                "horizon_days": candidate_spec.horizon_days,
            },
        },
        "candidate": candidate,
        "historical_paths": paths,
        "fallback_pool": [],
        "bootstrap_source_returns": all_returns,
        "bootstrap_block_length": min(2, max(1, len(all_returns))),
        "bootstrap_path_count": min(3, max(1, len(paths))),
        "bootstrap_source_realized_vol": _realized_vol(all_returns),
        "random_seed": 17,
        "stress_mixture_min_weight": 0.10,
        "stress_scenarios": _default_stress_scenarios(candidate_spec),
    }
    return build_path_risk_distribution_report(
        payload,
        generated_at=generated_at,
        config=config,
    )


UNDERLYING_HISTORY_SOURCE = "validated_underlying_price_history"

# Below this many *independent* (non-overlapping) horizon windows the sample
# cannot support a distribution claim. Overlapping windows inflate the apparent
# count by roughly the horizon length, so they are never the basis for this gate.
MIN_INDEPENDENT_UNDERLYING_WINDOWS = 20


def build_path_risk_report_from_underlying_history(
    history: dict[str, Any],
    candidate: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build path-risk evidence from public underlying price history.

    This is a *different and weaker* evidence class than
    `build_path_risk_report_from_historical_report`. That one rests on
    reconciled option quotes that passed payoff-replay and cross-vendor gates.
    This one rests only on the underlying's own candles, which the project can
    fetch itself. That is sufficient to characterise the underlying's realized
    return distribution — which is what an expected-value claim needs — but it
    says nothing about historical option pricing or executable fills, so it is
    labelled `validated_underlying_price_history` and never claims to be
    reconciliation evidence.
    """
    candidate_spec = _candidate_spec(candidate)
    observations = (history or {}).get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        return _blocked_underlying_path_report(
            candidate=candidate_spec,
            history=history,
            generated_at=generated_at,
            reason_codes=["INVALID_UNDERLYING_HISTORY"],
            independent_windows=0,
        )
    if (history or {}).get("resolution_seconds") != 86400:
        return _blocked_underlying_path_report(
            candidate=candidate_spec,
            history=history,
            generated_at=generated_at,
            reason_codes=["NON_DAILY_UNDERLYING_RESOLUTION"],
            independent_windows=0,
        )

    quotes = [
        {"ts": row.get("observed_at"), "underlying_price": row.get("close")}
        for row in observations
    ]
    horizon = candidate_spec.horizon_days
    # A non-overlapping window spans `horizon` daily steps (horizon + 1
    # quotes), so stride the valid start range the same way realized_vol does.
    # This can trail `len(observations) // horizon` by one when the observation
    # count is an exact multiple of the horizon; both modules must report the
    # strided count so the same history yields the same sample size.
    independent_windows = (
        len(range(0, len(observations) - horizon, horizon)) if horizon > 0 else 0
    )
    if independent_windows < MIN_INDEPENDENT_UNDERLYING_WINDOWS:
        return _blocked_underlying_path_report(
            candidate=candidate_spec,
            history=history,
            generated_at=generated_at,
            reason_codes=["INSUFFICIENT_INDEPENDENT_UNDERLYING_WINDOWS"],
            independent_windows=independent_windows,
        )

    paths = _historical_paths_from_quotes(quotes, candidate=candidate_spec)
    if len(paths) < 2:
        return _blocked_underlying_path_report(
            candidate=candidate_spec,
            history=history,
            generated_at=generated_at,
            reason_codes=["INSUFFICIENT_VALIDATED_HISTORICAL_PATHS"],
            independent_windows=independent_windows,
        )

    all_returns = [value for path in paths for value in path["returns"]]
    payload = {
        "source": UNDERLYING_HISTORY_SOURCE,
        "input_evidence": {
            "status": "validated_historical",
            "evidence_class": UNDERLYING_HISTORY_SOURCE,
            "placeholder_data": False,
            "readiness_contribution": "validated_underlying_history_path_risk",
            "underlying_instrument": (history or {}).get("instrument_name"),
            "underlying_source": (history or {}).get("source"),
            "first_observed_at": (history or {}).get("first_observed_at"),
            "last_observed_at": (history or {}).get("last_observed_at"),
            "observation_count": len(observations),
            "eligible_path_count": len(paths),
            "stress_window_coverage": "deterministic_shock_overlay",
            # Overlapping windows are reported separately from the independent
            # count so neither can be mistaken for the other.
            "sample_coverage": {
                "overlapping_paths": len(paths),
                "independent_windows": independent_windows,
                "sample_size_basis": "independent_non_overlapping_windows",
                "horizon_days": horizon,
            },
            "excludes": [
                "historical option quotes",
                "historical executable fills",
            ],
        },
        "candidate": candidate,
        "historical_paths": paths,
        "fallback_pool": [],
        "bootstrap_source_returns": all_returns,
        "bootstrap_block_length": min(5, max(1, len(all_returns))),
        "bootstrap_path_count": min(64, max(1, len(paths))),
        "bootstrap_source_realized_vol": _realized_vol(all_returns),
        "random_seed": 17,
        "stress_mixture_min_weight": 0.10,
        "stress_scenarios": _default_stress_scenarios(candidate_spec),
    }
    report = build_path_risk_distribution_report(
        payload,
        generated_at=generated_at,
        config=config,
    )
    return _annotate_independent_sample_bound(
        report,
        independent_windows=independent_windows,
        overlapping_paths=len(paths),
        horizon_days=horizon,
    )


def _annotate_independent_sample_bound(
    report: dict[str, Any],
    *,
    independent_windows: int,
    overlapping_paths: int,
    horizon_days: int,
) -> dict[str, Any]:
    """Publish the overlap-adjusted ceiling on how much this sample can support.

    The similarity-weighted effective sample size reported under
    `path_sampling` measures how concentrated the weights are; it does not know
    that windows overlap. Over a daily series with a `horizon_days` horizon,
    consecutive windows share all but one observation, so the real independent
    count is about `observations / horizon_days` — often an order of magnitude
    smaller than the ESS. Publishing only the ESS would overstate confidence in
    exactly the way this project exists to avoid, so the ceiling travels with
    the report.
    """
    sampling = report.get("path_sampling")
    applied_ess = None
    if isinstance(sampling, dict):
        weighted = sampling.get("similarity_weighted")
        if isinstance(weighted, dict):
            applied_ess = weighted.get("applied_effective_sample_size")

    report["independent_sample_bound"] = {
        "independent_windows": independent_windows,
        "overlapping_paths": overlapping_paths,
        "horizon_days": horizon_days,
        "sample_size_basis": "independent_non_overlapping_windows",
        "similarity_effective_sample_size": applied_ess,
        "effective_sample_size_accounts_for_overlap": False,
        "authoritative_sample_size": independent_windows,
        "note": (
            "Overlapping windows inflate the apparent sample by roughly the "
            "horizon length. Use independent_windows, not the similarity "
            "effective sample size, when judging confidence."
        ),
    }
    return report


def _blocked_underlying_path_report(
    *,
    candidate: CandidateSpec,
    history: dict[str, Any] | None,
    generated_at: str | None,
    reason_codes: list[str],
    independent_windows: int,
) -> dict[str, Any]:
    return {
        "schema_version": PATH_RISK_REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or utc_timestamp(),
        "input_evidence": {
            "status": "blocked",
            "source": UNDERLYING_HISTORY_SOURCE,
            "evidence_class": UNDERLYING_HISTORY_SOURCE,
            "placeholder_data": False,
            "readiness_contribution": "blocked_insufficient_underlying_history",
            "no_lookahead_declared": True,
            "underlying_source": (history or {}).get("source"),
            "observation_count": len((history or {}).get("observations") or []),
            "eligible_path_count": 0,
            "sample_coverage": {
                "independent_windows": independent_windows,
                "minimum_independent_windows": MIN_INDEPENDENT_UNDERLYING_WINDOWS,
                "sample_size_basis": "independent_non_overlapping_windows",
                "horizon_days": candidate.horizon_days,
            },
            "reason_codes": reason_codes,
        },
        "candidate": {
            "instrument_name": candidate.instrument_name,
            "structure": candidate.structure,
            "current_spot": candidate.current_spot,
            "strike": candidate.strike,
            "horizon_days": candidate.horizon_days,
        },
        "naked_short_allowed": False,
        "spread_only_required": True,
        "reason_codes": reason_codes,
    }


def _merge_path_risk_config(
    payload_config: Any,
    explicit_config: Any,
) -> dict[str, float]:
    merged: dict[str, Any] = dict(DEFAULT_PATH_RISK_CONFIG)
    for config_source, optional in (
        (payload_config, False),
        (explicit_config, True),
    ):
        if config_source is None and optional:
            continue
        if not isinstance(config_source, Mapping):
            raise ValueError("path risk config must be a mapping")
        unknown_fields = set(config_source) - PATH_RISK_CONFIG_FIELDS
        if unknown_fields:
            raise ValueError(
                "unknown path risk config fields: "
                + ", ".join(sorted(str(field) for field in unknown_fields))
            )
        merged.update(config_source)

    validated = {
        "similarity_bandwidth": _finite_positive_float(
            merged["similarity_bandwidth"],
            "similarity_bandwidth",
        ),
        "min_effective_sample_size": _strict_finite_at_least_one_float(
            merged["min_effective_sample_size"],
            "min_effective_sample_size",
        ),
    }
    for field_name in (
        "historical_group_weight",
        "bootstrap_group_weight",
        "stress_group_weight",
        "stress_mixture_min_weight",
        "confidence_penalty_multiplier",
    ):
        validated[field_name] = _unit_interval_float(
            merged[field_name],
            field_name,
        )
    return validated


def build_path_risk_distribution_report(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_config = _merge_path_risk_config(payload.get("config", {}), config)
    payload_stress_floor = _unit_interval_float(
        payload.get("stress_mixture_min_weight", 0.0),
        "stress_mixture_min_weight",
    )
    applied_stress_weight = max(
        merged_config["stress_group_weight"],
        merged_config["stress_mixture_min_weight"],
        payload_stress_floor,
    )
    if (
        merged_config["historical_group_weight"]
        + merged_config["bootstrap_group_weight"]
        + applied_stress_weight
        <= 0.0
    ):
        raise ValueError("mixture group weights must contain positive mass")

    candidate = _candidate_spec(payload["candidate"])
    report_generated_at = generated_at or utc_timestamp()

    historical_paths = payload.get("historical_paths")
    if not isinstance(historical_paths, list) or not historical_paths:
        raise ValueError("historical_paths must contain at least one path")
    base_paths = [
        _prepare_path_record(path_payload, candidate)
        for path_payload in historical_paths
    ]
    initial_similarity_weights = _similarity_weights(
        candidate.feature_vector,
        [path["feature_vector"] for path in base_paths],
        bandwidth=merged_config["similarity_bandwidth"],
    )
    initial_ess = _effective_sample_size(initial_similarity_weights)

    applied_paths = list(base_paths)
    applied_weights = list(initial_similarity_weights)
    fallback_triggered = initial_ess < merged_config["min_effective_sample_size"]
    if fallback_triggered:
        pooled_paths = [
            _prepare_path_record(path_payload, candidate)
            for path_payload in payload.get("fallback_pool", [])
        ]
        applied_paths.extend(pooled_paths)
        applied_weights = [1.0 / len(applied_paths)] * len(applied_paths)

    applied_ess = _effective_sample_size(applied_weights)

    bootstrap_report = _build_circular_block_bootstrap(
        payload=payload,
        candidate=candidate,
        config=merged_config,
    )
    stress_report = _build_stress_scenarios(
        payload=payload,
        candidate=candidate,
    )
    group_weights = _mixture_group_weights(
        historical_weight=merged_config["historical_group_weight"],
        bootstrap_weight=merged_config["bootstrap_group_weight"],
        stress_weight=merged_config["stress_group_weight"],
        stress_floor=max(
            merged_config["stress_mixture_min_weight"],
            payload_stress_floor,
        ),
    )

    all_scenarios = []
    for path, weight in zip(applied_paths, applied_weights, strict=True):
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = path["path_id"]
        scenario["source_group"] = "historical_similarity"
        scenario["weight"] = weight * group_weights["historical"]
        all_scenarios.append(scenario)

    bootstrap_paths = bootstrap_report["paths"]
    bootstrap_count = len(bootstrap_paths) or 1
    for index, path in enumerate(bootstrap_paths):
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = f"bootstrap-{index + 1}"
        scenario["source_group"] = "circular_block_bootstrap"
        scenario["weight"] = group_weights["bootstrap"] / bootstrap_count
        all_scenarios.append(scenario)

    stress_paths = stress_report["paths"]
    stress_total = stress_report["raw_weight_total"]
    stress_weights = [
        group_weights["stress"] * path["raw_weight"] / stress_total
        for path in stress_paths
    ]
    correction_index = max(
        range(len(stress_paths)),
        key=lambda index: stress_paths[index]["raw_weight"],
    )
    stress_weights[correction_index] += (
        group_weights["stress"] - math.fsum(stress_weights)
    )
    if (
        any(not math.isfinite(weight) or weight < 0.0 for weight in stress_weights)
        or not math.isclose(
            math.fsum(stress_weights),
            group_weights["stress"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("normalized stress scenario weights must preserve applied mass")
    for path, scenario_weight in zip(stress_paths, stress_weights, strict=True):
        path["mixture_weight"] = scenario_weight
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = path["path_id"]
        scenario["source_group"] = "stress_mixture"
        scenario["weight"] = scenario_weight
        scenario["stress_inputs"] = {
            "iv_jump": path["iv_jump"],
            "liquidity_exit_cost_usdc": path["liquidity_exit_cost_usdc"],
        }
        all_scenarios.append(scenario)

    metrics = _weighted_path_metrics(
        scenarios=all_scenarios,
        candidate=candidate,
    )
    historical_touch = sum(
        weight
        for path, weight in zip(applied_paths, applied_weights, strict=True)
        if path["path_touch"]
    )
    historical_itm = sum(
        weight
        for path, weight in zip(applied_paths, applied_weights, strict=True)
        if path["path_itm"]
    )

    restrictions = {
        "naked_short_allowed": not fallback_triggered,
        "spread_only_required": fallback_triggered,
        "recommended_structure": "spread_only" if fallback_triggered else candidate.structure,
        "confidence_penalty_applied": fallback_triggered,
        "confidence_penalty_multiplier": merged_config["confidence_penalty_multiplier"]
        if fallback_triggered
        else 1.0,
        "reason_codes": (
            ["SPARSE_EFFECTIVE_SAMPLE_SIZE", "SPREAD_ONLY_FALLBACK"]
            if fallback_triggered
            else []
        ),
    }

    evidence_override = dict(payload.get("input_evidence") or {})
    evidence_status = str(evidence_override.get("status") or "research_only_fixture")
    placeholder_data = bool(
        evidence_override.get("placeholder_data", evidence_status != "validated_historical")
    )
    report = {
        "schema_version": PATH_RISK_REPORT_SCHEMA_VERSION,
        "generated_at": report_generated_at,
        "input_evidence": {
            "status": evidence_status,
            "source": str(payload.get("source", "path_risk_fixture")),
            "eligible_path_count": len(applied_paths),
            "historical_path_count": len(base_paths),
            "fallback_path_count": max(len(applied_paths) - len(base_paths), 0),
            "stress_scenario_count": len(stress_report["paths"]),
            "bootstrap_path_count": len(bootstrap_report["paths"]),
            "no_lookahead_declared": True,
            "placeholder_data": placeholder_data,
            "readiness_contribution": evidence_override.get(
                "readiness_contribution",
                "placeholder_research_only",
            ),
            **{
                key: value
                for key, value in evidence_override.items()
                if key not in {"status", "placeholder_data", "readiness_contribution"}
            },
        },
        "candidate": {
            "instrument_name": candidate.instrument_name,
            "structure": candidate.structure,
            "current_spot": candidate.current_spot,
            "strike": candidate.strike,
            "long_strike": candidate.long_strike,
            "horizon_days": candidate.horizon_days,
            "entry_credit_usdc": candidate.entry_credit_usdc,
            "contract_size": candidate.contract_size,
            "starting_nav_usdc": candidate.starting_nav_usdc,
            "current_abs_delta": candidate.current_abs_delta,
            "delta_cross_up_return": candidate.delta_cross_up_return,
            "vega_usdc_per_abs_vol": candidate.vega_usdc_per_abs_vol,
            "target_realized_vol": candidate.target_realized_vol,
            "vol_scaling_mode": candidate.vol_scaling_mode,
            "vol_scaling_evidence": dict(candidate.vol_scaling_evidence),
            "regime_scores": candidate.regime_scores,
            "feature_vector": candidate.feature_vector,
        },
        "historical_path_records": applied_paths,
        "path_sampling": {
            "method": "similarity_weighted_plus_circular_block_bootstrap",
            "similarity_weighted": {
                "bandwidth": merged_config["similarity_bandwidth"],
                "initial_effective_sample_size": round(initial_ess, 8),
                "minimum_effective_sample_size": merged_config[
                    "min_effective_sample_size"
                ],
                "fallback_triggered": fallback_triggered,
                "fallback_mode": "hierarchical_pooling" if fallback_triggered else None,
                "applied_effective_sample_size": round(applied_ess, 8),
                "normalized_weights": [
                    {"path_id": path["path_id"], "weight": round(weight, 8)}
                    for path, weight in zip(applied_paths, applied_weights, strict=True)
                ],
                "restrictions": restrictions,
            },
            "bootstrap": bootstrap_report,
            "volatility_scaling": {
                "mode": candidate.vol_scaling_mode,
                "evidence": dict(candidate.vol_scaling_evidence),
                "target_realized_vol": candidate.target_realized_vol,
                "removes_volatility_dispersion": (
                    candidate.vol_scaling_mode != VOL_SCALING_NONE
                ),
                "observed_source_vol_dispersion": _source_vol_dispersion(applied_paths),
                "per_path_scale_factors": [
                    {
                        "path_id": path["path_id"],
                        "source_realized_vol": path["source_realized_vol"],
                        "scale_factor": path["scale_factor"],
                    }
                    for path in applied_paths
                ],
            },
        },
        "stress_mixture": {
            "configured_min_weight": max(
                merged_config["stress_mixture_min_weight"],
                payload_stress_floor,
            ),
            "applied_weight": round(group_weights["stress"], 8),
            "raw_weight_total": stress_total,
            "group_weights": group_weights,
            "scenarios": stress_report["paths"],
        },
        "distributions": metrics,
        "diagnostics": {
            "terminal_only_touch_proxy": round(historical_itm, 8),
            "historical_touch_probability_before_bootstrap": round(historical_touch, 8),
            "path_maximum_touch": True,
        },
        "report_flags": {
            "path_maximum_touch": True,
            "sparse_regime_confidence_penalty": fallback_triggered,
            "naked_short_allowed": restrictions["naked_short_allowed"],
            "spread_only_required": restrictions["spread_only_required"],
        },
    }
    _assert_finite_json_numbers(report)
    return report


def _candidate_spec(payload: dict[str, Any]) -> CandidateSpec:
    structure = payload["structure"]
    if not isinstance(structure, str) or not structure:
        raise ValueError("structure must be a non-empty name")
    explicit_legs = payload.get("legs")
    if explicit_legs is None and structure not in _LEGACY_STRUCTURES:
        # A named structure with no legs can only be evaluated if this module
        # already knows its shape. Accepting an unknown name would mean guessing
        # a payoff, so it is refused in favour of an explicit leg list.
        raise ValueError(
            f"structure {structure!r} requires an explicit legs list; only "
            + ", ".join(sorted(_LEGACY_STRUCTURES))
            + " are known by name"
        )

    contract_size = _finite_positive_float(
        payload.get("contract_size", 1.0),
        "contract_size",
    )
    entry_credit_usdc = _finite_nonnegative_float(
        payload["entry_credit_usdc"],
        "entry_credit_usdc",
    )

    if explicit_legs is not None:
        structure_legs = build_structure(
            structure_type=structure,
            legs=explicit_legs,
            contract_size=contract_size,
        )
        strike = min(structure_legs.strikes)
        long_strike = max(structure_legs.strikes) if len(structure_legs.strikes) > 1 else None
        _validate_credit_against_risk(structure_legs, entry_credit_usdc)
        return _build_candidate_spec(
            payload=payload,
            structure=structure,
            structure_legs=structure_legs,
            strike=strike,
            long_strike=long_strike,
            entry_credit_usdc=entry_credit_usdc,
            contract_size=contract_size,
        )

    strike = _finite_positive_float(payload["strike"], "strike")
    raw_long_strike = payload.get("long_strike")
    long_strike = (
        None
        if raw_long_strike is None
        else _finite_positive_float(raw_long_strike, "long_strike")
    )
    if structure == "call_credit_spread":
        if long_strike is None:
            raise ValueError("call_credit_spread requires long_strike")
        if long_strike <= strike:
            raise ValueError(
                "call_credit_spread long_strike must be greater than strike"
            )
        maximum_credit_usdc = _finite_positive_float(
            (long_strike - strike) * contract_size,
            "call_credit_spread width",
        )
        if entry_credit_usdc > maximum_credit_usdc:
            raise ValueError(
                "call_credit_spread entry_credit_usdc must not exceed spread width"
            )

    return _build_candidate_spec(
        payload=payload,
        structure=structure,
        structure_legs=_legacy_structure(
            structure,
            strike=strike,
            long_strike=long_strike,
            contract_size=contract_size,
        ),
        strike=strike,
        long_strike=long_strike,
        entry_credit_usdc=entry_credit_usdc,
        contract_size=contract_size,
    )


_LEGACY_STRUCTURES = frozenset({"naked_short_call", "call_credit_spread"})


def _legacy_structure(
    structure: str,
    *,
    strike: float,
    long_strike: float | None,
    contract_size: float,
) -> Structure:
    """Build the legs for the two structures that were once named-only."""
    if structure == "call_credit_spread":
        return call_credit_spread(
            short_strike=strike,
            long_strike=long_strike or 0.0,
            contract_size=contract_size,
        )
    return naked_short_call(strike=strike, contract_size=contract_size)


def _validate_credit_against_risk(
    structure_legs: Structure, entry_credit_usdc: float
) -> None:
    """Refuse a credit larger than the structure's own worst case.

    On a defined-risk structure this is an arbitrage claim, and it is far more
    often a unit mismatch — a coin-quoted credit compared against a USD width.
    """
    if structure_legs.is_multi_expiry:
        return
    profile = structure_legs.risk_profile(entry_cash=0.0)
    if profile.max_loss is not None and entry_credit_usdc > profile.max_loss:
        raise ValueError(
            f"{structure_legs.structure_type} entry_credit_usdc must not exceed "
            "the structure's maximum loss"
        )


def _build_candidate_spec(
    *,
    payload: dict[str, Any],
    structure: str,
    structure_legs: Structure,
    strike: float,
    long_strike: float | None,
    entry_credit_usdc: float,
    contract_size: float,
) -> CandidateSpec:
    return CandidateSpec(
        instrument_name=payload["instrument_name"],
        structure=structure,
        current_spot=_finite_positive_float(payload["current_spot"], "current_spot"),
        strike=strike,
        long_strike=long_strike,
        horizon_days=_positive_int(payload["horizon_days"], "horizon_days"),
        entry_credit_usdc=entry_credit_usdc,
        contract_size=contract_size,
        starting_nav_usdc=_finite_positive_float(
            payload.get("starting_nav_usdc", 100000.0),
            "starting_nav_usdc",
        ),
        current_abs_delta=_unit_interval_float(
            payload["current_abs_delta"],
            "current_abs_delta",
        ),
        delta_cross_up_return=_finite_nonnegative_float(
            payload["delta_cross_up_return"],
            "delta_cross_up_return",
        ),
        vega_usdc_per_abs_vol=_finite_nonnegative_float(
            payload.get("vega_usdc_per_abs_vol", 0.0),
            "vega_usdc_per_abs_vol",
        ),
        **_vol_scaling_spec(payload),
        regime_scores=_validated_numeric_mapping(
            payload.get("regime_scores"),
            "candidate regime_scores",
        ),
        feature_vector=_validated_numeric_mapping(
            payload.get("feature_vector"),
            "candidate feature_vector",
        ),
        structure_legs=structure_legs,
    )


def _source_vol_dispersion(paths: list[dict[str, Any]]) -> dict[str, Any]:
    """How much realized-volatility spread the path set actually contains.

    This is the quantity rescaling destroys. Reporting it lets a reader see
    what a scaled run gave up: a set whose windows ranged from 20% to 150%
    annualized is a different piece of evidence from one flattened to a single
    level, even when both produce the same mean payoff.
    """
    values = [
        float(path["source_realized_vol"])
        for path in paths
        if isinstance(path.get("source_realized_vol"), (int, float))
        and not isinstance(path.get("source_realized_vol"), bool)
    ]
    if len(values) < 2:
        return {"status": "unavailable", "path_count": len(values)}
    ordered = sorted(values)
    mean = sum(ordered) / len(ordered)
    variance = sum((value - mean) ** 2 for value in ordered) / (len(ordered) - 1)
    return {
        "status": "observed",
        "path_count": len(ordered),
        "min": round(ordered[0], 8),
        "median": round(ordered[len(ordered) // 2], 8),
        "max": round(ordered[-1], 8),
        "stdev": round(math.sqrt(variance), 8),
    }


def _vol_scaling_spec(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve how the historical paths may be rescaled, and on whose authority.

    Three shapes are accepted, and they are not equivalent:

    * nothing — no rescaling, which is the default and preserves the realized
      volatility of every window;
    * a `vol_scaling` block declaring `evidence_target` — rescaling to a stated
      measurement, which must name its source and as-of time or be rejected;
    * a bare legacy `target_realized_vol` — honoured so recorded fixtures still
      replay, but marked unevidenced so no reader mistakes it for a measurement.
    """
    block = payload.get("vol_scaling")
    if block is not None:
        if not isinstance(block, dict):
            raise ValueError("vol_scaling must be an object")
        mode = str(block.get("mode") or VOL_SCALING_NONE)
        if mode not in VOL_SCALING_MODES:
            raise ValueError(
                "vol_scaling mode must be one of " + ", ".join(sorted(VOL_SCALING_MODES))
            )
        if mode == VOL_SCALING_NONE:
            return {
                "target_realized_vol": None,
                "vol_scaling_mode": VOL_SCALING_NONE,
                "vol_scaling_evidence": {"status": "not_applicable"},
            }
        evidence = block.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("vol_scaling evidence_target requires an evidence object")
        source = evidence.get("source")
        as_of = evidence.get("as_of")
        if not isinstance(source, str) or not source:
            raise ValueError("vol_scaling evidence requires a source")
        if not isinstance(as_of, str) or not as_of:
            raise ValueError("vol_scaling evidence requires an as_of timestamp")
        return {
            "target_realized_vol": _finite_positive_float(
                block.get("target_realized_vol"),
                "vol_scaling target_realized_vol",
            ),
            "vol_scaling_mode": VOL_SCALING_EVIDENCE_TARGET,
            "vol_scaling_evidence": {
                "status": "measured",
                "source": source,
                "as_of": as_of,
                "measure": str(evidence.get("measure") or "realized_volatility"),
            },
        }

    legacy_target = payload.get("target_realized_vol")
    if legacy_target is None:
        return {
            "target_realized_vol": None,
            "vol_scaling_mode": VOL_SCALING_NONE,
            "vol_scaling_evidence": {"status": "not_applicable"},
        }
    return {
        "target_realized_vol": _finite_positive_float(
            legacy_target,
            "target_realized_vol",
        ),
        "vol_scaling_mode": VOL_SCALING_EVIDENCE_TARGET,
        "vol_scaling_evidence": {
            "status": "unevidenced",
            "reason_code": UNEVIDENCED_VOL_SCALING_TARGET,
            "detail": (
                "target_realized_vol was supplied as a bare number with no "
                "source behind it. Every distribution below is conditional on "
                "that assumption."
            ),
        },
    }


def _blocked_historical_path_report(
    *,
    candidate: CandidateSpec,
    historical_report: dict[str, Any],
    generated_at: str | None,
    reason_codes: list[str],
) -> dict[str, Any]:
    report = {
        "schema_version": PATH_RISK_REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or utc_timestamp(),
        "input_evidence": {
            "status": "blocked",
            "source": "validated_historical_reconciliation",
            "placeholder_data": False,
            "readiness_contribution": "blocked_insufficient_historical_path_risk",
            "no_lookahead_declared": True,
            "eligible_path_count": 0,
            "historical_path_count": 0,
            "fallback_path_count": 0,
            "stress_scenario_count": 0,
            "bootstrap_path_count": 0,
            "historical_report_schema_version": historical_report.get("schema_version"),
            "historical_eligibility_decision": (
                (historical_report.get("aggregate_eligibility") or historical_report.get("eligibility") or {}).get("decision")
            ),
            "reason_codes": reason_codes,
        },
        "candidate": {
            "instrument_name": candidate.instrument_name,
            "structure": candidate.structure,
            "current_spot": candidate.current_spot,
            "strike": candidate.strike,
            "long_strike": candidate.long_strike,
            "horizon_days": candidate.horizon_days,
        },
        "historical_path_records": [],
        "path_sampling": {
            "method": "validated_historical_rows",
            "similarity_weighted": {
                "fallback_triggered": False,
                "restrictions": {
                    "naked_short_allowed": False,
                    "spread_only_required": True,
                    "confidence_penalty_applied": True,
                    "reason_codes": reason_codes,
                },
            },
        },
        "stress_mixture": {
            "configured_min_weight": 0.0,
            "applied_weight": 0.0,
            "group_weights": {"historical": 0.0, "bootstrap": 0.0, "stress": 0.0},
            "scenarios": [],
        },
        "distributions": {
            "p_touch": 0.0,
            "p_itm": 0.0,
            "adverse_excursion": {"mean": 0.0, "p95": 0.0, "max": 0.0},
            "delta_cross_probability": 0.0,
            "expected_payoff_usdc": 0.0,
            "expected_loss_usdc": 0.0,
            "cvar_95_usdc": 0.0,
            "cvar_99_usdc": 0.0,
            "stress_loss_usdc": 0.0,
            "stress_loss_nav_pct": 0.0,
        },
        "diagnostics": {
            "terminal_only_touch_proxy": 0.0,
            "historical_touch_probability_before_bootstrap": 0.0,
            "path_maximum_touch": True,
        },
        "report_flags": {
            "path_maximum_touch": True,
            "sparse_regime_confidence_penalty": True,
            "naked_short_allowed": False,
            "spread_only_required": True,
        },
    }
    _assert_finite_json_numbers(report)
    return report


def _historical_paths_from_quotes(
    quotes: list[dict[str, Any]],
    *,
    candidate: CandidateSpec,
) -> list[dict[str, Any]]:
    sorted_quotes = sorted(quotes, key=lambda item: str(item.get("ts") or ""))
    prices = [
        _finite_positive_float(
            item["underlying_price"],
            "historical quote underlying_price",
        )
        for item in sorted_quotes
    ]
    timestamps = [str(item.get("ts")) for item in sorted_quotes]
    paths = []
    for start in range(0, len(prices) - candidate.horizon_days):
        window = prices[start : start + candidate.horizon_days + 1]
        returns = [
            round((right / left) - 1.0, 8)
            for left, right in pairwise(window)
            if left > 0
        ]
        if len(returns) != candidate.horizon_days:
            continue
        paths.append(
            {
                "path_id": f"validated-history-{start + 1}",
                "start_time": timestamps[start],
                "horizon_days": candidate.horizon_days,
                "source_realized_vol": _realized_vol(returns),
                "regime_scores": dict(candidate.regime_scores),
                "feature_vector": {
                    **candidate.feature_vector,
                    "trend_7d": round((window[-1] / window[0]) - 1.0, 8),
                },
                "returns": returns,
            }
        )
    return paths


def _realized_vol(returns: list[float]) -> float:
    if not returns:
        return 0.01
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / max(len(returns), 1)
    return round(max(math.sqrt(variance) * math.sqrt(365), 0.01), 8)


def _default_stress_scenarios(candidate: CandidateSpec) -> list[dict[str, Any]]:
    return [
        {
            "name": "synthetic-stress-spot-up-10-iv-jump",
            "path_returns": [0.10] + [0.0] * max(candidate.horizon_days - 1, 0),
            "iv_jump": 0.15,
            "liquidity_exit_cost_usdc": 120.0,
            "weight": 0.03,
        },
        {
            "name": "synthetic-stress-spot-up-20-iv-jump",
            "path_returns": [0.12, 0.08] + [0.0] * max(candidate.horizon_days - 2, 0),
            "iv_jump": 0.25,
            "liquidity_exit_cost_usdc": 250.0,
            "weight": 0.01,
        },
        {
            "name": "synthetic-stress-liquidity-gap",
            "path_returns": [0.05, 0.03] + [0.0] * max(candidate.horizon_days - 2, 0),
            "iv_jump": 0.10,
            "liquidity_exit_cost_usdc": 400.0,
            "weight": 0.01,
        },
    ]


def _prepare_path_record(
    payload: dict[str, Any],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    raw_returns = _validated_path_returns(payload["returns"])
    path_horizon_days = _positive_int(
        payload.get("horizon_days", candidate.horizon_days),
        "historical path horizon_days",
    )
    if path_horizon_days != candidate.horizon_days:
        raise ValueError(
            "historical path horizon_days must equal candidate horizon_days"
        )
    if len(raw_returns) != path_horizon_days:
        raise ValueError("historical path returns length must equal horizon_days")
    if candidate.vol_scaling_mode == VOL_SCALING_NONE:
        # The window is replayed exactly as it happened. Its own realized
        # volatility is still recorded so the dispersion that scaling would have
        # removed stays visible in the artifact.
        raw_source_vol = payload.get("source_realized_vol")
        source_vol = (
            float(raw_source_vol)
            if isinstance(raw_source_vol, (int, float))
            and not isinstance(raw_source_vol, bool)
            and math.isfinite(raw_source_vol)
            and raw_source_vol > 0
            else None
        )
        scale_factor = 1.0
        scaled_returns = list(raw_returns)
    else:
        source_vol = _finite_positive_float(
            payload["source_realized_vol"],
            "source_realized_vol",
        )
        scale_factor = _finite_positive_float(
            candidate.target_realized_vol / source_vol,
            "scale_factor",
        )
        try:
            scaled_returns = [
                round(math.expm1(math.log1p(value) * scale_factor), 8)
                for value in raw_returns
            ]
        except OverflowError as exc:
            raise ValueError(
                "scaled path returns must remain finite and greater than -1"
            ) from exc
    if any(
        not math.isfinite(value) or value <= -1.0
        for value in scaled_returns
    ):
        raise ValueError("scaled path returns must remain finite and greater than -1")
    normalized_spot_path = _normalized_path_from_returns(scaled_returns)
    rounded_spot_path = [round(value, 8) for value in normalized_spot_path]
    if any(
        not math.isfinite(level) or level <= 0.0
        for level in rounded_spot_path
    ):
        raise ValueError("normalized spot path must remain finite and positive")
    max_up_return = max(normalized_spot_path) - 1.0
    terminal_return = normalized_spot_path[-1] - 1.0
    return {
        "path_id": payload["path_id"],
        "start_time": payload["start_time"],
        "horizon_days": path_horizon_days,
        "regime_scores": _validated_numeric_mapping(
            payload.get("regime_scores"),
            "historical path regime_scores",
        ),
        "feature_vector": _validated_numeric_mapping(
            payload.get("feature_vector"),
            "historical path feature_vector",
        ),
        "returns": raw_returns,
        "scaled_returns": scaled_returns,
        "normalized_spot_path": rounded_spot_path,
        "max_up_return": round(max_up_return, 8),
        "terminal_return": round(terminal_return, 8),
        "source_realized_vol": source_vol,
        "scale_factor": scale_factor,
        # "Touched" generalizes from "spot reached the strike" to "the position
        # would have owed something at some point along the path", which is the
        # same statement for a short call and the correct one for a structure
        # whose risk is on the downside or on both sides.
        "path_touch": any(
            candidate.structure_legs.finishes_in_obligation(
                candidate.current_spot * level
            )
            for level in normalized_spot_path
        ),
        "path_itm": candidate.structure_legs.finishes_in_obligation(
            candidate.current_spot * normalized_spot_path[-1]
        ),
    }


def _build_circular_block_bootstrap(
    *,
    payload: dict[str, Any],
    candidate: CandidateSpec,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_returns = _validated_path_returns(
        payload["bootstrap_source_returns"],
        field_name="bootstrap_source_returns",
    )
    block_length = _positive_int(
        payload["bootstrap_block_length"],
        "bootstrap_block_length",
    )
    path_count = _positive_int(
        payload["bootstrap_path_count"],
        "bootstrap_path_count",
    )
    random_seed = _integer(payload.get("random_seed", 0), "random_seed")
    raw_source_vol = payload.get(
        "bootstrap_source_realized_vol", candidate.target_realized_vol
    )
    source_vol = (
        None
        if raw_source_vol is None and candidate.vol_scaling_mode == VOL_SCALING_NONE
        else _finite_positive_float(raw_source_vol, "bootstrap_source_realized_vol")
    )
    rng = random.Random(random_seed)
    paths = []
    for index in range(path_count):
        sampled_returns = []
        sampled_blocks = []
        while len(sampled_returns) < candidate.horizon_days:
            start_index = rng.randrange(len(source_returns))
            block = [
                source_returns[(start_index + offset) % len(source_returns)]
                for offset in range(block_length)
            ]
            sampled_blocks.append(
                {
                    "start_index": start_index,
                    "returns": [round(value, 8) for value in block],
                }
            )
            sampled_returns.extend(block)
        path_payload = {
            "path_id": f"bootstrap-{index + 1}",
            "start_time": f"bootstrap-seed-{random_seed}-{index + 1}",
            "horizon_days": candidate.horizon_days,
            "regime_scores": candidate.regime_scores,
            "feature_vector": candidate.feature_vector,
            "returns": sampled_returns[: candidate.horizon_days],
            "source_realized_vol": source_vol,
        }
        path_record = _prepare_path_record(path_payload, candidate)
        path_record["sampled_blocks"] = sampled_blocks
        paths.append(path_record)
    return {
        "method": "circular_block_bootstrap",
        "block_length": block_length,
        "path_count": path_count,
        "random_seed": random_seed,
        "source_returns": [round(value, 8) for value in source_returns],
        "paths": paths,
    }


def _build_stress_scenarios(
    *,
    payload: dict[str, Any],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    scenarios = payload.get("stress_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("stress_scenarios must contain at least one scenario")
    paths = []
    for scenario in scenarios:
        path_payload = {
            "path_id": scenario["name"],
            "start_time": scenario["name"],
            "horizon_days": candidate.horizon_days,
            "regime_scores": candidate.regime_scores,
            "feature_vector": candidate.feature_vector,
            "returns": scenario["path_returns"],
            # Stress paths are authored at the severity they are meant to
            # represent, so they are never rescaled: passing the target as the
            # source makes the factor exactly one under either mode.
            "source_realized_vol": candidate.target_realized_vol,
        }
        path_record = _prepare_path_record(path_payload, candidate)
        path_record["raw_weight"] = _finite_nonnegative_float(
            scenario["weight"],
            "stress scenario weight",
        )
        path_record["iv_jump"] = _finite_nonnegative_float(
            scenario["iv_jump"],
            "stress scenario iv_jump",
        )
        path_record["liquidity_exit_cost_usdc"] = _finite_nonnegative_float(
            scenario["liquidity_exit_cost_usdc"],
            "stress scenario liquidity_exit_cost_usdc",
        )
        paths.append(path_record)
    raw_weight_total = sum(path["raw_weight"] for path in paths)
    if not math.isfinite(raw_weight_total):
        raise ValueError(
            "stress scenario weight total must remain finite and positive"
        )
    if raw_weight_total <= 0.0:
        raise ValueError("stress scenario weights must contain positive mass")
    return {"paths": paths, "raw_weight_total": raw_weight_total}


def _scenario_from_record(
    path_record: dict[str, Any],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    normalized_path = [float(value) for value in path_record["normalized_spot_path"]]
    max_up_return = max(normalized_path) - 1.0
    terminal_return = normalized_path[-1] - 1.0
    terminal_spot = candidate.current_spot * normalized_path[-1]
    # The obligation is read off the legs, so a put spread or a condor settles
    # through the same expression as a short call rather than needing a branch.
    intrinsic_value_usdc = candidate.structure_legs.amount_owed_at(terminal_spot)
    iv_jump = float(path_record.get("iv_jump", 0.0))
    liquidity_exit_cost_usdc = float(path_record.get("liquidity_exit_cost_usdc", 0.0))
    iv_jump_cost_usdc = iv_jump * candidate.vega_usdc_per_abs_vol
    payoff_usdc = intrinsic_value_usdc + iv_jump_cost_usdc + liquidity_exit_cost_usdc
    loss_usdc = max(
        payoff_usdc - candidate.entry_credit_usdc,
        0.0,
    )
    return {
        "max_up_return": round(max_up_return, 8),
        "terminal_return": round(terminal_return, 8),
        "touched": bool(path_record["path_touch"]),
        "itm": bool(path_record["path_itm"]),
        "delta_crossed": max_up_return >= candidate.delta_cross_up_return,
        "loss_usdc": round(loss_usdc, 8),
        "payoff_usdc": round(payoff_usdc, 8),
        "intrinsic_value_usdc": round(intrinsic_value_usdc, 8),
        "iv_jump_cost_usdc": round(iv_jump_cost_usdc, 8),
        "liquidity_exit_cost_usdc": round(liquidity_exit_cost_usdc, 8),
        "terminal_spot": round(terminal_spot, 8),
    }


def _similarity_weights(
    target: dict[str, float],
    feature_vectors: Iterable[dict[str, float]],
    *,
    bandwidth: float,
) -> list[float]:
    vectors = list(feature_vectors)
    log_weights = []
    for vector in vectors:
        keys = sorted(set(target) | set(vector))
        scaled_distance = 0.0
        for key in keys:
            left = target.get(key, 0.0)
            right = vector.get(key, 0.0)
            if left == right:
                scaled_delta = 0.0
            else:
                magnitude = max(abs(left), abs(right))
                normalized_delta = (left / magnitude) - (right / magnitude)
                magnitude_to_bandwidth = magnitude / bandwidth
                if not math.isfinite(magnitude_to_bandwidth):
                    scaled_distance = math.inf
                    break
                scaled_delta = normalized_delta * magnitude_to_bandwidth
                if not math.isfinite(scaled_delta):
                    scaled_distance = math.inf
                    break
            scaled_distance = math.hypot(scaled_distance, scaled_delta)
        if not math.isfinite(scaled_distance):
            log_weights.append(-math.inf)
            continue
        squared_distance = scaled_distance * scaled_distance
        log_weights.append(-0.5 * squared_distance)

    finite_logs = [weight for weight in log_weights if math.isfinite(weight)]
    if not finite_logs:
        return [0.0] * len(vectors)
    max_log_weight = max(finite_logs)
    raw_weights = [
        math.exp(weight - max_log_weight) if math.isfinite(weight) else 0.0
        for weight in log_weights
    ]
    total = math.fsum(raw_weights)
    if not math.isfinite(total) or total <= 0.0:
        return [0.0] * len(vectors)
    normalized = [weight / total for weight in raw_weights]
    correction_index = max(range(len(normalized)), key=normalized.__getitem__)
    normalized[correction_index] += 1.0 - math.fsum(normalized)
    return normalized


def _effective_sample_size(weights: list[float]) -> float:
    if not weights or any(
        not math.isfinite(weight) or weight < 0.0 for weight in weights
    ):
        return 0.0
    total = math.fsum(weights)
    if not math.isfinite(total) or total <= 0.0:
        return 0.0
    squared_mass = math.fsum((weight / total) ** 2 for weight in weights)
    if not math.isfinite(squared_mass) or squared_mass <= 0.0:
        return 0.0
    effective_sample_size = 1.0 / squared_mass
    return effective_sample_size if math.isfinite(effective_sample_size) else 0.0


def _mixture_group_weights(
    *,
    historical_weight: float,
    bootstrap_weight: float,
    stress_weight: float,
    stress_floor: float,
) -> dict[str, float]:
    applied_stress = max(stress_weight, stress_floor)
    remaining = max(1.0 - applied_stress, 0.0)
    non_stress = historical_weight + bootstrap_weight
    if non_stress <= 0:
        return {
            "historical": 0.0,
            "bootstrap": 0.0,
            "stress": 1.0 if applied_stress > 0.0 else 0.0,
        }
    historical = remaining * historical_weight / non_stress
    return {
        "historical": historical,
        "bootstrap": remaining - historical,
        "stress": applied_stress,
    }


def _weighted_path_metrics(
    *,
    scenarios: list[dict[str, Any]],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    weights = [float(item["weight"]) for item in scenarios]
    if (
        not weights
        or any(not math.isfinite(weight) or weight < 0.0 for weight in weights)
        or not math.isclose(
            math.fsum(weights),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("path scenario weights must form complete probability mass")
    p_touch = sum(weight for weight, item in zip(weights, scenarios, strict=True) if item["touched"])
    p_itm = sum(weight for weight, item in zip(weights, scenarios, strict=True) if item["itm"])
    delta_cross_probability = sum(
        weight
        for weight, item in zip(weights, scenarios, strict=True)
        if item["delta_crossed"]
    )
    max_up_returns = [float(item["max_up_return"]) for item in scenarios]
    losses = [float(item["loss_usdc"]) for item in scenarios]
    payoffs = [float(item["payoff_usdc"]) for item in scenarios]
    stress_losses = [
        float(item["loss_usdc"])
        for item in scenarios
        if item["source_group"] == "stress_mixture"
    ]
    adverse_excursion_mean = sum(
        weight * max_up_return
        for weight, max_up_return in zip(weights, max_up_returns, strict=True)
    )
    return {
        "p_touch": round(p_touch, 8),
        "p_itm": round(p_itm, 8),
        "adverse_excursion": {
            "mean": round(adverse_excursion_mean, 8),
            "p95": round(_weighted_quantile(max_up_returns, weights, 0.95), 8),
            "max": round(max(max_up_returns) if max_up_returns else 0.0, 8),
        },
        "delta_cross_probability": round(delta_cross_probability, 8),
        "expected_payoff_usdc": round(
            sum(weight * payoff for weight, payoff in zip(weights, payoffs, strict=True)),
            8,
        ),
        "expected_loss_usdc": round(
            sum(weight * loss for weight, loss in zip(weights, losses, strict=True)),
            8,
        ),
        "cvar_95_usdc": round(_weighted_cvar(losses, weights, 0.95), 8),
        "cvar_99_usdc": round(_weighted_cvar(losses, weights, 0.99), 8),
        "stress_loss_usdc": round(max(stress_losses) if stress_losses else 0.0, 8),
        "stress_loss_nav_pct": round(
            (max(stress_losses) / candidate.starting_nav_usdc) if stress_losses else 0.0,
            8,
        ),
    }


def _weighted_quantile(values: list[float], weights: list[float], quantile: float) -> float:
    pairs = sorted(zip(values, weights, strict=True), key=lambda item: item[0])
    threshold = quantile * sum(weights)
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0] if pairs else 0.0


def _weighted_cvar(losses: list[float], weights: list[float], confidence: float) -> float:
    pairs = sorted(zip(losses, weights, strict=True), key=lambda item: item[0], reverse=True)
    tail_weight = max(1.0 - confidence, 1e-12)
    cumulative = 0.0
    weighted_loss = 0.0
    for loss, weight in pairs:
        take = min(weight, tail_weight - cumulative)
        weighted_loss += loss * take
        cumulative += take
        if cumulative >= tail_weight:
            break
    return weighted_loss / tail_weight if cumulative else 0.0


def _normalized_path_from_returns(returns: list[float]) -> list[float]:
    values = []
    level = 1.0
    for value in returns:
        level *= 1.0 + value
        values.append(level)
    return values or [1.0]


def _validated_path_returns(
    values: Iterable[Any],
    *,
    field_name: str = "path returns",
) -> list[float]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"{field_name} must contain at least one return")
    raw_values = list(values)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in raw_values
    ):
        raise ValueError("path returns must be finite and greater than -1")
    returns = [float(value) for value in raw_values]
    if any(not math.isfinite(value) or value <= -1.0 for value in returns):
        raise ValueError("path returns must be finite and greater than -1")
    return returns


def _validated_numeric_mapping(value: Any, field_name: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field_name} must be a non-empty mapping")
    validated = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{field_name}.{key} must be finite numeric")
        number = float(raw_value)
        if not math.isfinite(number):
            raise ValueError(f"{field_name}.{key} must be finite numeric")
        validated[key] = number
    return validated


def _assert_finite_json_numbers(
    value: Any,
    *,
    path: str = "path risk report",
) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"path risk report contains non-finite number at {path}"
            )
        return
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            _assert_finite_json_numbers(
                nested_value,
                path=f"{path}.{key}",
            )
        return
    if isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            _assert_finite_json_numbers(
                nested_value,
                path=f"{path}[{index}]",
            )


def _strict_finite_at_least_one_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be finite and positive (at least 1)"
        )
    number = float(value)
    if not math.isfinite(number) or number < 1.0:
        raise ValueError(
            f"{field_name} must be finite and positive (at least 1)"
        )
    return number


def _finite_positive_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite and positive")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{field_name} must be finite and positive")
    return number


def _finite_nonnegative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite and non-negative")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return number


def _unit_interval_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return number


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value
