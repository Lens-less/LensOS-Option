"""Path-risk distribution tracer for ISSUE-009."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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
    target_realized_vol: float
    regime_scores: dict[str, float]
    feature_vector: dict[str, float]


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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


def build_path_risk_distribution_report(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_config = dict(DEFAULT_PATH_RISK_CONFIG)
    merged_config.update(payload.get("config", {}))
    if config:
        merged_config.update(config)

    candidate = _candidate_spec(payload["candidate"])
    report_generated_at = generated_at or utc_timestamp()

    base_paths = [
        _prepare_path_record(path_payload, candidate)
        for path_payload in payload["historical_paths"]
    ]
    initial_similarity_weights = _similarity_weights(
        candidate.feature_vector,
        [path["feature_vector"] for path in base_paths],
        bandwidth=float(merged_config["similarity_bandwidth"]),
    )
    initial_ess = _effective_sample_size(initial_similarity_weights)

    applied_paths = list(base_paths)
    applied_weights = list(initial_similarity_weights)
    fallback_triggered = initial_ess < float(merged_config["min_effective_sample_size"])
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
        historical_weight=float(merged_config["historical_group_weight"]),
        bootstrap_weight=float(merged_config["bootstrap_group_weight"]),
        stress_weight=float(merged_config["stress_group_weight"]),
        stress_floor=max(
            float(merged_config["stress_mixture_min_weight"]),
            float(payload.get("stress_mixture_min_weight", 0.0)),
        ),
    )

    all_scenarios = []
    for path, weight in zip(applied_paths, applied_weights, strict=True):
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = path["path_id"]
        scenario["source_group"] = "historical_similarity"
        scenario["weight"] = round(weight * group_weights["historical"], 8)
        all_scenarios.append(scenario)

    bootstrap_paths = bootstrap_report["paths"]
    bootstrap_count = len(bootstrap_paths) or 1
    for index, path in enumerate(bootstrap_paths):
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = f"bootstrap-{index + 1}"
        scenario["source_group"] = "circular_block_bootstrap"
        scenario["weight"] = round(group_weights["bootstrap"] / bootstrap_count, 8)
        all_scenarios.append(scenario)

    stress_paths = stress_report["paths"]
    stress_total = sum(path["raw_weight"] for path in stress_paths) or 1.0
    for path in stress_paths:
        scenario = _scenario_from_record(path, candidate)
        scenario["scenario_id"] = path["path_id"]
        scenario["source_group"] = "stress_mixture"
        scenario["weight"] = round(
            group_weights["stress"] * path["raw_weight"] / stress_total,
            8,
        )
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
        "confidence_penalty_multiplier": float(
            merged_config["confidence_penalty_multiplier"]
        )
        if fallback_triggered
        else 1.0,
        "reason_codes": (
            ["SPARSE_EFFECTIVE_SAMPLE_SIZE", "SPREAD_ONLY_FALLBACK"]
            if fallback_triggered
            else []
        ),
    }

    return {
        "schema_version": PATH_RISK_REPORT_SCHEMA_VERSION,
        "generated_at": report_generated_at,
        "input_evidence": {
            "status": "research_only_fixture",
            "source": str(payload.get("source", "path_risk_fixture")),
            "eligible_path_count": len(applied_paths),
            "historical_path_count": len(base_paths),
            "fallback_path_count": max(len(applied_paths) - len(base_paths), 0),
            "stress_scenario_count": len(stress_report["paths"]),
            "bootstrap_path_count": len(bootstrap_report["paths"]),
            "no_lookahead_declared": True,
            "placeholder_data": True,
            "readiness_contribution": "placeholder_research_only",
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
            "regime_scores": candidate.regime_scores,
            "feature_vector": candidate.feature_vector,
        },
        "historical_path_records": applied_paths,
        "path_sampling": {
            "method": "similarity_weighted_plus_circular_block_bootstrap",
            "similarity_weighted": {
                "bandwidth": float(merged_config["similarity_bandwidth"]),
                "initial_effective_sample_size": round(initial_ess, 8),
                "minimum_effective_sample_size": float(
                    merged_config["min_effective_sample_size"]
                ),
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
                "target_realized_vol": candidate.target_realized_vol,
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
                float(merged_config["stress_mixture_min_weight"]),
                float(payload.get("stress_mixture_min_weight", 0.0)),
            ),
            "applied_weight": round(group_weights["stress"], 8),
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


def _candidate_spec(payload: dict[str, Any]) -> CandidateSpec:
    return CandidateSpec(
        instrument_name=payload["instrument_name"],
        structure=payload["structure"],
        current_spot=float(payload["current_spot"]),
        strike=float(payload["strike"]),
        long_strike=(
            None
            if payload.get("long_strike") in (None, "")
            else float(payload["long_strike"])
        ),
        horizon_days=int(payload["horizon_days"]),
        entry_credit_usdc=float(payload["entry_credit_usdc"]),
        contract_size=float(payload.get("contract_size", 1.0)),
        starting_nav_usdc=float(payload.get("starting_nav_usdc", 100000.0)),
        current_abs_delta=float(payload["current_abs_delta"]),
        delta_cross_up_return=float(payload["delta_cross_up_return"]),
        vega_usdc_per_abs_vol=float(payload.get("vega_usdc_per_abs_vol", 0.0)),
        target_realized_vol=float(payload["target_realized_vol"]),
        regime_scores=dict(payload["regime_scores"]),
        feature_vector={key: float(value) for key, value in payload["feature_vector"].items()},
    )


def _prepare_path_record(
    payload: dict[str, Any],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    raw_returns = [float(value) for value in payload["returns"]]
    source_vol = float(payload["source_realized_vol"])
    scale_factor = candidate.target_realized_vol / source_vol if source_vol else 1.0
    scaled_returns = [round(value * scale_factor, 8) for value in raw_returns]
    normalized_spot_path = _normalized_path_from_returns(scaled_returns)
    max_up_return = max(normalized_spot_path) - 1.0
    terminal_return = normalized_spot_path[-1] - 1.0
    return {
        "path_id": payload["path_id"],
        "start_time": payload["start_time"],
        "horizon_days": int(payload.get("horizon_days", candidate.horizon_days)),
        "regime_scores": {
            key: float(value) for key, value in payload["regime_scores"].items()
        },
        "feature_vector": {
            key: float(value) for key, value in payload["feature_vector"].items()
        },
        "returns": raw_returns,
        "scaled_returns": scaled_returns,
        "normalized_spot_path": [round(value, 8) for value in normalized_spot_path],
        "max_up_return": round(max_up_return, 8),
        "terminal_return": round(terminal_return, 8),
        "source_realized_vol": source_vol,
        "scale_factor": round(scale_factor, 8),
        "path_touch": candidate.current_spot * max(normalized_spot_path) >= candidate.strike,
        "path_itm": candidate.current_spot * normalized_spot_path[-1] >= candidate.strike,
    }


def _build_circular_block_bootstrap(
    *,
    payload: dict[str, Any],
    candidate: CandidateSpec,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_returns = [float(value) for value in payload["bootstrap_source_returns"]]
    block_length = int(payload["bootstrap_block_length"])
    path_count = int(payload["bootstrap_path_count"])
    random_seed = int(payload.get("random_seed", 0))
    source_vol = float(payload.get("bootstrap_source_realized_vol", candidate.target_realized_vol))
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
    paths = []
    for scenario in payload["stress_scenarios"]:
        path_payload = {
            "path_id": scenario["name"],
            "start_time": scenario["name"],
            "horizon_days": candidate.horizon_days,
            "regime_scores": candidate.regime_scores,
            "feature_vector": candidate.feature_vector,
            "returns": scenario["path_returns"],
            "source_realized_vol": candidate.target_realized_vol,
        }
        path_record = _prepare_path_record(path_payload, candidate)
        path_record["raw_weight"] = float(scenario["weight"])
        path_record["iv_jump"] = float(scenario["iv_jump"])
        path_record["liquidity_exit_cost_usdc"] = float(
            scenario["liquidity_exit_cost_usdc"]
        )
        paths.append(path_record)
    return {"paths": paths}


def _scenario_from_record(
    path_record: dict[str, Any],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    normalized_path = [float(value) for value in path_record["normalized_spot_path"]]
    max_up_return = max(normalized_path) - 1.0
    terminal_return = normalized_path[-1] - 1.0
    terminal_spot = candidate.current_spot * normalized_path[-1]
    if candidate.structure == "call_credit_spread" and candidate.long_strike is not None:
        short_intrinsic = max(terminal_spot - candidate.strike, 0.0)
        long_intrinsic = max(terminal_spot - candidate.long_strike, 0.0)
        intrinsic_value_usdc = max(short_intrinsic - long_intrinsic, 0.0) * candidate.contract_size
    else:
        intrinsic_value_usdc = max(terminal_spot - candidate.strike, 0.0) * candidate.contract_size
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
    raw_weights = []
    for vector in feature_vectors:
        keys = sorted(set(target) | set(vector))
        squared_distance = 0.0
        for key in keys:
            squared_distance += (target.get(key, 0.0) - vector.get(key, 0.0)) ** 2
        raw_weights.append(math.exp(-squared_distance / max(2.0 * bandwidth * bandwidth, 1e-12)))
    total = sum(raw_weights) or 1.0
    return [weight / total for weight in raw_weights]


def _effective_sample_size(weights: list[float]) -> float:
    return 1.0 / sum(weight * weight for weight in weights) if weights else 0.0


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
            "stress": round(applied_stress, 8),
        }
    scale = remaining / non_stress
    return {
        "historical": round(historical_weight * scale, 8),
        "bootstrap": round(bootstrap_weight * scale, 8),
        "stress": round(applied_stress, 8),
    }


def _weighted_path_metrics(
    *,
    scenarios: list[dict[str, Any]],
    candidate: CandidateSpec,
) -> dict[str, Any]:
    weights = [float(item["weight"]) for item in scenarios]
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
