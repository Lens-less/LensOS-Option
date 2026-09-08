"""History replay must not match paths using their future returns."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crypto_options_report.path_risk import (
    HISTORICAL_PRE_PATH_FEATURES_UNAVAILABLE,
    build_path_risk_distribution_report,
    build_path_risk_report_from_fixture,
    build_path_risk_report_from_historical_report,
    build_path_risk_report_from_underlying_history,
    load_path_risk_fixture,
)

FIXTURE = Path(__file__).parent / "fixtures" / "path_risk_distribution_fixture.json"
CANDIDATE = {
    "instrument_name": "BTC-RESEARCH-C",
    "structure": "naked_short_call",
    "current_spot": 100.0,
    "strike": 115.0,
    "horizon_days": 2,
    "entry_credit_usdc": 1.0,
    "current_abs_delta": 0.13,
    "delta_cross_up_return": 0.12,
    "vol_scaling": {"mode": "none"},
    "regime_scores": {"squeeze": 0.5},
    "feature_vector": {"trend_7d": 0.0, "dvol_percentile": 0.5},
}


def _history() -> dict:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    observations = [
        {
            "observed_at": (start + timedelta(days=index)).isoformat(),
            "close": 100.0,
        }
        for index in range(61)
    ]
    observations[2]["close"] = 150.0
    return {
        "source": "test_daily_history",
        "instrument_name": "BTC-PERPETUAL",
        "resolution_seconds": 86400,
        "observations": observations,
    }


def _build(history: dict, source: str, candidate: dict | None = None) -> dict:
    spec = candidate or CANDIDATE
    if source == "underlying":
        return build_path_risk_report_from_underlying_history(
            history, spec, generated_at="2026-01-01T00:00:00Z"
        )
    return build_path_risk_report_from_historical_report(
        {
            "aggregate_eligibility": {"decision": "ELIGIBLE"},
            "canonical_data": {
                "eligible_quotes": [
                    {"ts": row["observed_at"], "underlying_price": row["close"]}
                    for row in history["observations"]
                ]
            },
        },
        spec,
        generated_at="2026-01-01T00:00:00Z",
    )


@pytest.mark.parametrize("source", ["underlying", "reconciled_quotes"])
def test_future_price_changes_outcomes_without_changing_history_weights(source):
    original = _history()
    amended = deepcopy(original)
    amended["observations"][2]["close"] = 101.0

    before = _build(original, source)
    after = _build(amended, source)
    before_sampling = before["path_sampling"]["similarity_weighted"]
    after_sampling = after["path_sampling"]["similarity_weighted"]

    # The first window has the same information at its start. Changing its
    # future outcome must change its payoff, never its selection probability.
    assert before_sampling["normalized_weights"] == after_sampling["normalized_weights"]
    assert before["historical_path_records"][0]["terminal_return"] == 0.5
    assert after["historical_path_records"][0]["terminal_return"] == 0.01
    assert before["distributions"]["expected_payoff_usdc"] > after["distributions"]["expected_payoff_usdc"]


@pytest.mark.parametrize("source", ["underlying", "reconciled_quotes"])
def test_missing_pre_path_features_are_unavailable_and_never_fabricated(source):
    report = _build(_history(), source)
    sampling = report["path_sampling"]["similarity_weighted"]
    evidence = report["input_evidence"]

    assert evidence["status"] == "validated_historical"
    assert sampling["applied"] is False
    assert sampling["mode"] == "unconditioned_uniform"
    assert sampling["status"] == "unavailable"
    assert sampling["reason_code"] == HISTORICAL_PRE_PATH_FEATURES_UNAVAILABLE
    assert evidence["conditional_similarity"]["requested_feature_names"] == [
        "dvol_percentile", "trend_7d"
    ]
    assert evidence["conditional_similarity"]["applied"] is False
    assert report["candidate"]["feature_vector"] == CANDIDATE["feature_vector"]
    for record in report["historical_path_records"]:
        assert record["feature_vector"] == {}
        assert record["regime_scores"] == {}
    assert len({row["weight"] for row in sampling["normalized_weights"]}) == 1


@pytest.mark.parametrize("source", ["underlying", "reconciled_quotes"])
def test_current_candidate_features_do_not_invent_historical_regime_matching(source):
    before = _build(_history(), source)
    different_regime = deepcopy(CANDIDATE)
    different_regime["regime_scores"] = {"squeeze": 1.0}
    different_regime["feature_vector"] = {"trend_7d": 0.5, "dvol_percentile": 0.9}
    after = _build(_history(), source, different_regime)

    assert before["distributions"] == after["distributions"]
    assert before["historical_path_records"] == after["historical_path_records"]


def test_explicit_fixture_features_keep_their_existing_similarity_sampler():
    report = build_path_risk_report_from_fixture(FIXTURE)
    sampling = report["path_sampling"]["similarity_weighted"]

    assert sampling["applied"] is True
    assert sampling["mode"] == "similarity_weighted"
    assert report["historical_path_records"][0]["feature_vector"]


def test_similarity_sampling_still_fails_closed_without_input_features():
    payload = load_path_risk_fixture(FIXTURE)
    payload["historical_paths"][0]["feature_vector"] = {}

    with pytest.raises(ValueError, match="historical path feature_vector must be a non-empty mapping"):
        build_path_risk_distribution_report(payload)


def test_unsupported_sampling_mode_is_rejected():
    payload = load_path_risk_fixture(FIXTURE)
    payload["historical_sampling_mode"] = "invented_regime"

    with pytest.raises(ValueError, match="unsupported historical_sampling_mode"):
        build_path_risk_distribution_report(payload)


@pytest.mark.parametrize("source", ["underlying", "reconciled_quotes"])
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("future", "HISTORICAL_TIMESTAMP_AFTER_GENERATED_AT"),
        ("duplicate", "HISTORICAL_TIMESTAMP_NOT_STRICTLY_INCREASING"),
        ("out_of_order", "HISTORICAL_TIMESTAMP_NOT_STRICTLY_INCREASING"),
        ("invalid", "HISTORICAL_TIMESTAMP_INVALID"),
        ("missing", "HISTORICAL_TIMESTAMP_INVALID"),
        ("naive", "HISTORICAL_TIMESTAMP_INVALID"),
        ("gap", "HISTORICAL_DAILY_CADENCE_INVALID"),
    ],
)
def test_invalid_history_time_cannot_validate_paths_or_independent_samples(source, case, reason):
    history = _history()
    rows = history["observations"]
    if case == "future":
        rows[-1]["observed_at"] = "2030-01-01T00:00:00Z"
    elif case == "duplicate":
        rows[1]["observed_at"] = rows[0]["observed_at"]
    elif case == "out_of_order":
        # Keep a daily interval until the backwards jump so this specifically
        # tests chronology, not just the missing-day gate.
        rows[2]["observed_at"] = "2024-12-31T00:00:00Z"
    elif case == "invalid":
        rows[1]["observed_at"] = "not-a-timestamp"
    elif case == "missing":
        rows[1]["observed_at"] = None
    elif case == "naive":
        rows[1]["observed_at"] = "2025-01-02T00:00:00"
    else:
        del rows[2]

    report = _build(history, source)

    assert report["input_evidence"]["status"] == "blocked"
    assert reason in report["input_evidence"]["reason_codes"]
    assert report["input_evidence"]["eligible_path_count"] == 0
    if source == "underlying":
        assert report["input_evidence"]["sample_coverage"]["independent_windows"] == 0


def test_underlying_timestamp_representations_must_agree():
    history = _history()
    history["observations"][1]["timestamp_ms"] = 0

    report = _build(history, "underlying")

    assert report["input_evidence"]["status"] == "blocked"
    assert report["reason_codes"] == ["HISTORICAL_TIMESTAMP_MISMATCH"]


@pytest.mark.parametrize("source", ["underlying", "reconciled_quotes"])
def test_one_day_horizon_preserves_full_default_stress_without_crashing(source):
    report = _build(_history(), source, {**CANDIDATE, "horizon_days": 1})

    assert report["input_evidence"]["status"] == "validated_historical"
    scenarios = report["stress_mixture"]["scenarios"]
    assert [scenario["returns"] for scenario in scenarios] == [
        [0.10], [0.2096], [0.0815], [-0.10], [-0.1904], [-0.0785]
    ]
    assert all(len(scenario["normalized_spot_path"]) == 1 for scenario in scenarios)
