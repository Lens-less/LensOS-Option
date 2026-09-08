"""Public artifact contracts exercised against producers, including empty states."""

from copy import deepcopy

import pytest
from test_signal_validation import _build_series

from crypto_options_report.public_api_contract import (
    PublicContractError,
    validate_public_projection,
)
from crypto_options_report.publication import (
    _annotate_numeric_field_evidence,
    _project_series_artifact,
    _project_signal_artifact,
)
from crypto_options_report.series_history import build_series_history_report
from crypto_options_report.signal_validation import (
    build_signal_preflight_report,
    build_signal_validation_report,
)

GENERATED_AT = "2026-12-01T00:00:00Z"


@pytest.fixture(scope="module")
def capture_series():
    return _build_series(richness_reaches_quote=True)


@pytest.fixture(scope="module")
def projected_preflight(capture_series):
    snapshots, history = capture_series
    source = build_signal_preflight_report(
        snapshots=snapshots,
        underlying_history=history,
        generated_at=GENERATED_AT,
    )
    return _project_signal_artifact(source)


@pytest.fixture(scope="module")
def projected_series(capture_series):
    snapshots, _ = capture_series
    source = build_series_history_report(
        snapshots=snapshots,
        generated_at=GENERATED_AT,
    )
    assert source["status"] == "measured"
    return _project_series_artifact(source)


def _signal_wrapper_artifact(value):
    return _annotate_numeric_field_evidence(
        value, evidence_class="research_signal_artifact"
    )


def test_blocked_signal_producer_projects_nullable_missing_sample_fields():
    source = build_signal_validation_report(
        snapshots=[], underlying_history=None, generated_at=GENERATED_AT
    )
    assert source["status"] == "blocked"
    projected = _project_signal_artifact(source)
    assert projected["sample"]["snapshot_count"] is None
    assert projected["summary"]["pre_registered_axis_verdict"] is None
    assert projected["signals"] == {}
    validate_public_projection("ResearchSignal", projected)
    validate_public_projection("ResearchSignal", _signal_wrapper_artifact(projected))


def test_preflight_producer_accepts_recursive_numeric_annotations(projected_preflight):
    assert projected_preflight["status"] == "projected"
    assert projected_preflight["cohorts"]
    validate_public_projection("ResearchSignal", projected_preflight)
    wrapped = _signal_wrapper_artifact(projected_preflight)
    assert wrapped["config"]["field_evidence"]["bucket_count"]["unit"] == "count"
    assert wrapped["pre_registration"]["field_evidence"]["threshold"]["unit"] == "scalar"
    validate_public_projection("ResearchSignal", wrapped)


def test_measured_signal_producer_projects_without_stripping_evidence(capture_series):
    snapshots, history = capture_series
    source = build_signal_validation_report(
        snapshots=snapshots,
        underlying_history=history,
        generated_at=GENERATED_AT,
    )
    assert source["status"] == "measured"
    assert source["signals"]["smile_residual_iv_points"]["status"] == "measured"
    projected = _project_signal_artifact(source)
    assert projected["cannot_tell"] == source["cannot_tell"]
    assert projected["collinearity"]["pairs"]
    assert len(projected["collinearity"]["pairs"]) == len(source["collinearity"]["pairs"])
    validate_public_projection("ResearchSignal", projected)
    wrapped = _signal_wrapper_artifact(projected)
    assert wrapped["collinearity"]["field_evidence"]["equivalence_threshold"]
    assert wrapped["collinearity"]["pairs"][0]["field_evidence"]["mean_rank_correlation"]
    validate_public_projection("ResearchSignal", wrapped)

    mutations = (
        (("observation_count",), "100"),
        (("information_coefficient", "mean"), "0.2"),
        (("information_coefficient", "private_notes"), "not public"),
        (("raw_information_coefficient", "mean"), True),
        (("buckets", 0, "win_rate"), "0.5"),
        (("buckets", 0, "unexpected"), 1),
        (("per_date", 0, "information_coefficient"), "0.3"),
        (("per_date", 0, "snapshot_date"), "2026-02-30"),
    )
    for path, replacement in mutations:
        bad = deepcopy(projected)
        row = bad["signals"]["smile_residual_iv_points"]
        for key in path[:-1]:
            row = row[key]
        row[path[-1]] = replacement
        with pytest.raises(PublicContractError, match=str(path[-1])):
            validate_public_projection("ResearchSignal", bad)
    bad = deepcopy(projected)
    del bad["signals"]["smile_residual_iv_points"]["definition"]
    with pytest.raises(PublicContractError, match="definition is required"):
        validate_public_projection("ResearchSignal", bad)

    for path, replacement in (
        (("cannot_tell", 0), {"private_notes": "not public"}),
        (("collinearity", "equivalence_threshold"), "0.95"),
        (("collinearity", "pairs", 0, "signals"), ["only_one_signal"]),
        (("collinearity", "pairs", 0, "mean_rank_correlation"), "0.98"),
        (("collinearity", "pairs", 0, "mean_rank_correlation"), 1.1),
        (("collinearity", "pairs", 0, "unexpected"), 1),
        (("collinearity", "private_notes"), "not public"),
    ):
        bad = deepcopy(projected)
        row = bad
        for key in path[:-1]:
            row = row[key]
        row[path[-1]] = replacement
        with pytest.raises(PublicContractError):
            validate_public_projection("ResearchSignal", bad)
    bad = deepcopy(projected)
    del bad["collinearity"]["pairs"][0]["mean_rank_correlation"]
    with pytest.raises(PublicContractError, match="mean_rank_correlation is required"):
        validate_public_projection("ResearchSignal", bad)


def test_blocked_series_producer_projects_empty_instruments():
    source = build_series_history_report(snapshots=[], generated_at=GENERATED_AT)
    assert source["status"] == "blocked"
    projected = _project_series_artifact(source)
    assert projected["instruments"] == []
    validate_public_projection("ResearchSeries", projected)


def test_measured_series_preserves_absent_points_and_nullable_quote_context(projected_series):
    assert any(
        not point["present"]
        for instrument in projected_series["instruments"]
        for point in instrument["points"]
    )
    validate_public_projection("ResearchSeries", projected_series)
    nullable = deepcopy(projected_series)
    first = nullable["instruments"][0]
    for field in ("bid_usdc", "dte_days", "model_delta"):
        first["latest"][field] = None
    validate_public_projection("ResearchSeries", nullable)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("capture_count",), "59"),
        (("instruments", 0, "strike_price"), "100000"),
        (("instruments", 0, "latest", "model_delta"), True),
        (("instruments", 0, "latest", "unexpected"), 1),
        (("instruments", 0, "points", 0, "present"), "false"),
        (("instruments", 0, "points", 0, "private_notes"), "not public"),
        (("instruments", 0, "points", 0, "date"), "2026-02-30"),
        (("instruments", 0, "expiry_date"), "2026-13-01"),
        (("instruments", 0, "persistence", "shrunk_mean"), "0.2"),
    ],
)
def test_series_rejects_wrong_nested_types_and_unknown_fields(projected_series, path, replacement):
    bad = deepcopy(projected_series)
    row = bad
    for key in path[:-1]:
        row = row[key]
    row[path[-1]] = replacement
    with pytest.raises(PublicContractError, match=str(path[-1])):
        validate_public_projection("ResearchSeries", bad)


def test_series_requires_point_presence_and_instrument_identity(projected_series):
    for path in (("instrument_name",), ("points", 0, "present")):
        bad = deepcopy(projected_series)
        row = bad["instruments"][0]
        for key in path[:-1]:
            row = row[key]
        del row[path[-1]]
        with pytest.raises(PublicContractError, match=f"{path[-1]} is required"):
            validate_public_projection("ResearchSeries", bad)


@pytest.mark.parametrize("component", ["ResearchSignal", "ResearchSeries"])
@pytest.mark.parametrize("timestamp_field", ["captured_at", "generated_at"])
def test_artifact_requires_valid_timestamp_and_schema_version(component, timestamp_field):
    version = {
        "ResearchSignal": "signal_validation_report.v1",
        "ResearchSeries": "instrument_series_history.v1",
    }[component]
    valid = {"schema_version": version, timestamp_field: GENERATED_AT}
    validate_public_projection(component, valid)
    with pytest.raises(PublicContractError, match="schema_version is required"):
        validate_public_projection(component, {timestamp_field: GENERATED_AT})
    with pytest.raises(PublicContractError, match="matches no allowed variant"):
        validate_public_projection(component, {"schema_version": version})
    for invalid in ("2026-12-01", "2026-13-01T00:00:00Z", "2026-12-01T00:00:00"):
        with pytest.raises(PublicContractError, match=timestamp_field):
            validate_public_projection(component, {**valid, timestamp_field: invalid})


def test_registration_supports_date_and_historical_timestamp(projected_preflight):
    for registered_at in ("2026-07-27", "2026-07-27T00:00:00Z"):
        value = deepcopy(projected_preflight)
        value["pre_registration"]["registered_at"] = registered_at
        validate_public_projection("ResearchSignal", value)
    value["pre_registration"]["registered_at"] = "2026-02-30"
    with pytest.raises(PublicContractError, match="registered_at"):
        validate_public_projection("ResearchSignal", value)


def test_preflight_rejects_wrong_band_reason_count_and_evidence_types(projected_preflight):
    for mutate, field in (
        (lambda value: value["bands"]["research_window"].update(cohorts_seen="1"), "cohorts_seen"),
        (lambda value: value["cohorts"][0]["blocking_reasons"].update(MISSING_GREEKS="1"), "MISSING_GREEKS"),
        (lambda value: value["config"]["field_evidence"]["bucket_count"].update(unit=3), "unit"),
        (lambda value: value["config"]["field_evidence"]["bucket_count"].update(secret="private"), "secret"),
    ):
        value = _signal_wrapper_artifact(deepcopy(projected_preflight))
        mutate(value)
        with pytest.raises(PublicContractError, match=field):
            validate_public_projection("ResearchSignal", value)


def test_invalid_capture_diagnostic_is_retained_as_evidence():
    source = build_series_history_report(
        snapshots=[{"captured_at": "invalid upstream timestamp"}],
        generated_at=GENERATED_AT,
    )
    projected = _project_series_artifact(source)
    assert projected["excluded_captures"][0]["reason_code"] == "UNPARSEABLE_CAPTURED_AT"
    validate_public_projection("ResearchSeries", projected)
