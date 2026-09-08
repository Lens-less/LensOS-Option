"""Fixed public schemas describe states, rather than the current sample."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from crypto_options_report.public_api_contract import (
    PublicContractError,
    build_public_openapi,
    validate_public_projection,
)

FIXTURES = Path(__file__).parent / "fixtures/public_contract"



@pytest.mark.parametrize("state", ["ready", "missing", "degraded"])
def test_every_shared_state_uses_the_same_contract(state):
    values = json.loads((FIXTURES / f"{state}.json").read_text(encoding="utf-8"))
    for component, value in values.items():
        validate_public_projection(component, value)
    assert build_public_openapi(
        summary=values["Summary"], health=values["Health"],
        research_report=values["ResearchReport"], research_signal=values["ResearchSignal"],
        research_series=values["ResearchSeries"],
    ) == build_public_openapi()


@pytest.mark.parametrize("case", json.loads((FIXTURES / "mutations.json").read_text(encoding="utf-8")), ids=lambda case: case["name"])
def test_shared_invalid_mutations_fail_closed(case):
    values = json.loads((FIXTURES / "ready.json").read_text(encoding="utf-8"))
    value = values[case["component"]]
    parent = value
    for key in case["path"][:-1]:
        parent = parent[key]
    if case["op"] == "delete":
        del parent[case["path"][-1]]
    else:
        parent[case["path"][-1]] = case["value"]
    with pytest.raises(PublicContractError):
        validate_public_projection(case["component"], value)


def test_versioned_schema_snapshot_is_compatible():
    snapshot = Path(__file__).parents[1] / "crypto_options_report/resources/public-openapi-v1.json"
    assert build_public_openapi() == json.loads(snapshot.read_text(encoding="utf-8"))


def test_empty_arrays_and_objects_have_explicit_fixed_contracts():
    def inspect(schema):
        assert schema, "unconstrained schema would hide missing producer variants"
        kind = schema.get("type")
        if kind == "array":
            assert "items" in schema
            inspect(schema["items"])
        if kind == "object":
            additional = schema.get("additionalProperties")
            assert additional is False or isinstance(additional, dict)
            if isinstance(additional, dict):
                inspect(additional)
            properties = schema.get("properties", {})
            assert set(schema.get("required", [])) <= set(properties)
            for nested in properties.values():
                inspect(nested)
        for nested in schema.get("anyOf", []):
            inspect(nested)

    for schema in build_public_openapi()["components"]["schemas"].values():
        inspect(schema)


def test_openapi_without_samples_is_stable_and_returns_an_isolated_document():
    first = build_public_openapi()
    second = build_public_openapi()
    assert first == second
    first["components"]["schemas"]["Summary"]["required"].clear()
    assert build_public_openapi() == second


def test_strategy_brief_populated_fixture_and_empty_projection_share_contract():
    fixture = Path(__file__).parent / "fixtures/strategy_brief/golden_strategy_brief_v1.json"
    ready = json.loads(fixture.read_text(encoding="utf-8"))
    validate_public_projection("StrategyBrief", ready)
    empty = deepcopy(ready)
    empty["strategies"] = []
    empty["action"] = "NO_TRADE"
    validate_public_projection("StrategyBrief", empty)
    invalid = deepcopy(ready)
    invalid["strategies"][0]["entry"]["minimum_net_credit"] = "400"
    with pytest.raises(PublicContractError, match="minimum_net_credit"):
        validate_public_projection("StrategyBrief", invalid)


def test_public_strategy_schema_rejects_recommendation_without_verified_cost_bound():
    fixture = Path(__file__).parent / "fixtures/strategy_brief/golden_strategy_brief_v1.json"
    value = json.loads(fixture.read_text(encoding="utf-8"))
    assert value["strategies"][0]["risk"]["delivery_fee_upper_bound_verified"] is False
    value["strategies"][0]["recommendation_status"] = "RECOMMENDED"
    with pytest.raises(PublicContractError, match="recommendation_status"):
        validate_public_projection("StrategyBrief", value)


def test_contract_rejects_missing_required_and_extra_private_field():
    fixture = Path(__file__).parent / "fixtures/strategy_brief/golden_strategy_brief_v1.json"
    value = json.loads(fixture.read_text(encoding="utf-8"))
    del value["research_only"]
    with pytest.raises(PublicContractError, match="research_only"):
        validate_public_projection("StrategyBrief", value)
    value["research_only"] = True
    value["api_key"] = "never-publish"
    with pytest.raises(PublicContractError, match="api_key"):
        validate_public_projection("StrategyBrief", value)


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf")])
def test_numbers_reject_boolean_and_nonfinite_json_values(invalid):
    fixture = Path(__file__).parent / "fixtures/strategy_brief/golden_strategy_brief_v1.json"
    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["strategies"][0]["entry"]["minimum_net_credit"] = invalid
    with pytest.raises(PublicContractError, match="minimum_net_credit"):
        validate_public_projection("StrategyBrief", value)


@pytest.mark.parametrize("offset", ["+00:60", "+01:99", "-00:60", "+24:00"])
def test_date_time_rejects_offsets_that_python_would_normalize(offset):
    with pytest.raises(PublicContractError, match="valid date-time"):
        validate_public_projection("ResearchSignal", {
            "schema_version": "signal_preflight.v1",
            "captured_at": f"2026-09-08T00:00:00{offset}",
        })


@pytest.mark.parametrize("offset", ["Z", "z", "+08:00", "-03:30", "+23:59"])
def test_date_time_accepts_valid_rfc3339_offsets(offset):
    validate_public_projection("ResearchSignal", {
        "schema_version": "signal_preflight.v1",
        "captured_at": f"2026-09-08T00:00:00{offset}",
    })
