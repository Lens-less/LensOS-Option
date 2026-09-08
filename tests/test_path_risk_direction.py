"""Path diagnostics must follow the actual short legs and disclose proxies."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from crypto_options_report.path_risk import (
    _candidate_spec,
    _default_stress_scenarios,
    _directional_risk_spec,
    _scenario_from_record,
    _weighted_path_metrics,
    build_path_risk_distribution_report,
    load_path_risk_fixture,
)


def _leg(option_type, strike, quantity):
    return {
        "option_type": option_type,
        "strike": strike,
        "quantity": quantity,
        "expiry_date": "2026-10-01",
    }


def _candidate_payload(shape="condor"):
    call = [_leg("call", 110.0, -1.0), _leg("call", 120.0, 1.0)]
    put = [_leg("put", 90.0, -1.0), _leg("put", 80.0, 1.0)]
    return {
        "instrument_name": "RESEARCH-STRUCTURE",
        "structure": shape,
        "legs": {
            "naked_call": call[:1],
            "naked_put": put[:1],
            "call": call,
            "put": put,
            "condor": put + call,
        }[shape],
        "current_spot": 100.0,
        "horizon_days": 2,
        "entry_credit_usdc": 1.0,
        "current_abs_delta": 0.13,
        "delta_cross_up_return": 0.12,
        "vol_scaling": {"mode": "none"},
        "regime_scores": {"range": 0.5},
        "feature_vector": {"trend_7d": 0.0},
    }


def _scenario(candidate, levels):
    structure = candidate.structure_legs
    return _scenario_from_record(
        {
            "normalized_spot_path": levels,
            "path_touch": any(
                structure.finishes_in_obligation(candidate.current_spot * level)
                for level in levels
            ),
            "path_itm": structure.finishes_in_obligation(
                candidate.current_spot * levels[-1]
            ),
        },
        candidate,
    )


@pytest.mark.parametrize(
    ("shape", "direction", "up_strike", "down_strike"),
    [
        ("naked_call", "up", 110.0, None),
        ("naked_put", "down", None, 90.0),
        ("call", "up", 110.0, None),
        ("put", "down", None, 90.0),
        ("condor", "both", 110.0, 90.0),
    ],
)
def test_credit_direction_and_boundaries_follow_actual_short_legs(
    shape, direction, up_strike, down_strike
):
    spec = _directional_risk_spec(_candidate_spec(_candidate_payload(shape)))

    assert spec["status"] == "available"
    assert spec["direction"] == direction
    assert spec["up_short_strike"] == up_strike
    assert spec["down_short_strike"] == down_strike
    assert spec["up_return_threshold"] == (pytest.approx(0.1) if up_strike else None)
    assert spec["down_return_threshold"] == (
        pytest.approx(0.1) if down_strike else None
    )


@pytest.mark.parametrize(
    ("shape", "levels", "adverse", "up_crossed", "down_crossed"),
    [
        ("call", [1.05, 1.155], 0.155, True, None),
        ("put", [1.05, 1.155], 0.0, None, False),
        ("condor", [1.05, 1.155], 0.155, True, False),
        ("call", [0.95, 0.855], 0.0, False, None),
        ("put", [0.95, 0.855], 0.145, None, True),
        ("condor", [0.95, 0.855], 0.145, False, True),
    ],
)
def test_excursion_and_crossing_respect_each_adverse_direction(
    shape, levels, adverse, up_crossed, down_crossed
):
    result = _scenario(_candidate_spec(_candidate_payload(shape)), levels)

    assert result["adverse_excursion_return"] == pytest.approx(adverse)
    assert result["max_up_return"] == pytest.approx(max(0.0, max(levels) - 1.0))
    assert result["max_down_return"] == pytest.approx(max(0.0, 1.0 - min(levels)))
    assert result["up_short_strike_crossed"] is up_crossed
    assert result["down_short_strike_crossed"] is down_crossed
    assert result["short_strike_crossed"] is bool(up_crossed or down_crossed)


@pytest.mark.parametrize("shape", ["call", "put", "condor"])
def test_flat_path_has_zero_adverse_excursion_and_no_crossing(shape):
    result = _scenario(_candidate_spec(_candidate_payload(shape)), [1.0, 1.0])

    assert result["adverse_excursion_return"] == 0.0
    assert result["max_up_return"] == result["max_down_return"] == 0.0
    assert result["short_strike_crossed"] is False


def test_condor_records_both_wing_crossings_even_when_terminal_spot_recovers():
    result = _scenario(_candidate_spec(_candidate_payload()), [0.85, 1.15, 1.0])

    assert result["adverse_excursion_return"] == pytest.approx(0.15)
    assert result["up_short_strike_crossed"] is True
    assert result["down_short_strike_crossed"] is True
    assert result["short_strike_crossed"] is True
    assert result["intrinsic_value_usdc"] == 0.0
    assert result["itm"] is False


@pytest.mark.parametrize(("shape", "level"), [("call", 1.1), ("put", 0.9)])
def test_exact_short_strike_is_reached_without_expiry_obligation(shape, level):
    result = _scenario(_candidate_spec(_candidate_payload(shape)), [level])

    assert result["short_strike_crossed"] is True
    assert result["intrinsic_value_usdc"] == pytest.approx(0.0)
    assert result["itm"] is False


@pytest.mark.parametrize(
    ("shape", "initial_spot", "next_level"),
    [("call", 115.0, 0.8), ("put", 85.0, 1.2)],
)
def test_initial_spot_already_beyond_short_strike_counts_as_reached(
    shape, initial_spot, next_level
):
    payload = _candidate_payload(shape)
    payload["current_spot"] = initial_spot
    result = _scenario(_candidate_spec(payload), [next_level])

    assert result["short_strike_crossed"] is True
    assert result["adverse_excursion_return"] == 0.0


def test_call_keeps_legacy_up_move_proxy_distinct_from_short_strike_crossing():
    result = _scenario(_candidate_spec(_candidate_payload("call")), [1.11])

    assert result["short_strike_crossed"] is True
    assert result["delta_crossed"] is False


@pytest.mark.parametrize(
    ("shape", "level"), [("put", 0.89), ("condor", 0.89), ("condor", 1.11)]
)
def test_put_and_condor_do_not_mirror_or_reuse_legacy_up_move_threshold(shape, level):
    payload = _candidate_payload(shape)
    payload["delta_cross_up_return"] = 0.3
    result = _scenario(_candidate_spec(payload), [level])

    assert result["short_strike_crossed"] is True
    assert result["delta_crossed"] is True


@pytest.mark.parametrize(
    "legs",
    [
        [_leg("call", 110.0, 1.0)],
        [_leg("call", 120.0, -1.0), _leg("call", 110.0, 1.0)],
        [_leg("call", 110.0, -2.0), _leg("call", 120.0, 1.0)],
        [_leg("put", 90.0, -1.0), _leg("put", 90.0, 1.0)],
    ],
    ids=["long_only", "debit_geometry", "unbalanced_ratio", "fully_offset"],
)
def test_unproven_credit_geometry_cannot_invent_direction_or_probability(legs):
    payload = _candidate_payload()
    payload.update(legs=legs, entry_credit_usdc=0.0)
    candidate = _candidate_spec(payload)
    spec = _directional_risk_spec(candidate)
    scenario = _scenario(candidate, [0.8, 1.2])
    metrics = _weighted_path_metrics(
        scenarios=[{**scenario, "weight": 1.0, "source_group": "historical"}],
        candidate=candidate,
    )

    assert spec["status"] == "unavailable"
    assert spec["direction"] is None
    assert scenario["adverse_excursion_return"] is None
    assert scenario["short_strike_crossed"] is None
    assert scenario["delta_crossed"] is None
    assert {
        key: metrics["adverse_excursion"][key]
        for key in ("status", "direction", "mean", "p95", "max")
    } == {
        "status": "unavailable",
        "direction": None,
        "mean": None,
        "p95": None,
        "max": None,
    }
    assert metrics["short_strike_cross_probability"] is None
    assert metrics["delta_cross_probability"] is None


def test_weighted_metrics_use_adverse_side_and_preserve_probability_mass():
    candidate = _candidate_spec(_candidate_payload("put"))
    scenarios = [
        {**_scenario(candidate, [0.85]), "weight": 0.25, "source_group": "historical"},
        {**_scenario(candidate, [1.3]), "weight": 0.75, "source_group": "historical"},
    ]
    metrics = _weighted_path_metrics(scenarios=scenarios, candidate=candidate)

    assert {
        key: metrics["adverse_excursion"][key]
        for key in ("status", "direction", "mean", "p95", "max")
    } == {
        "status": "available",
        "direction": "down",
        "mean": 0.0375,
        "p95": 0.15,
        "max": 0.15,
    }
    assert metrics["short_strike_cross_probability"] == 0.25
    assert metrics["delta_cross_probability"] == 0.25


@pytest.mark.parametrize("horizon", [1, 2, 7])
def test_default_stress_covers_both_directions_at_every_supported_horizon(horizon):
    payload = _candidate_payload()
    payload["horizon_days"] = horizon
    scenarios = _default_stress_scenarios(_candidate_spec(payload))
    terminal_returns = [
        math.prod(1.0 + value for value in row["path_returns"]) - 1.0
        for row in scenarios
    ]

    assert len(scenarios) == 6
    assert all(len(row["path_returns"]) == horizon for row in scenarios)
    assert sum(value > 0 for value in terminal_returns) == 3
    assert sum(value < 0 for value in terminal_returns) == 3
    assert min(terminal_returns) < -0.1
    assert max(terminal_returns) > 0.2


@pytest.mark.parametrize(
    ("shape", "proxy_basis"),
    [
        ("call", "legacy_up_return_proxy"),
        ("put", "short_leg_strike_boundary_proxy"),
        ("condor", "short_leg_strike_boundary_proxy"),
    ],
)
def test_report_discloses_authored_stress_and_unavailable_dynamic_delta(
    shape, proxy_basis
):
    fixture = Path(__file__).parent / "fixtures" / "path_risk_distribution_fixture.json"
    payload = load_path_risk_fixture(fixture)
    candidate = _candidate_payload(shape)
    candidate["horizon_days"] = payload["candidate"]["horizon_days"]
    payload["candidate"] = candidate
    payload["stress_scenarios"] = _default_stress_scenarios(_candidate_spec(candidate))
    report = build_path_risk_distribution_report(payload)
    stress = report["stress_mixture"]

    assert stress["scenario_basis"] == "authored_deterministic_shocks"
    assert stress["weights_are_calibrated_probabilities"] is False
    assert stress["statistical_confidence_available"] is False
    assert report["distributions"]["delta_cross_probability_basis"] == proxy_basis
    assert report["diagnostics"]["dynamic_delta_crossing"]["status"] == "unavailable"
