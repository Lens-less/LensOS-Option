"""Fixed OpenAPI 3.1 public contract and dependency-free structural validation.

Only the explicitly listed JSON Schema 2020-12 keywords are supported here; this
is a validator for our contract, not a general JSON Schema implementation.
Domain evidence/clock/privacy validators remain separate publication gates.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime
from functools import lru_cache
from math import isfinite
from typing import Any

from .public_artifact_schema import artifact_schemas
from .public_schema import public_schemas

PUBLIC_API_VERSION = "1.0.0"


class PublicContractError(ValueError):
    """A public projection violates its fixed structural contract."""


def build_public_openapi(
    *,
    summary: dict[str, Any] | None = None,
    thermo: dict[str, Any] | None = None,
    thermo_recent: dict[str, Any] | None = None,
    thermo_years: list[dict[str, Any]] | None = None,
    candidates: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    research_report: dict[str, Any] | None = None,
    research_signal: dict[str, Any] | None = None,
    research_series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the same v1 contract for every data state.

    Legacy sample arguments are accepted and validated, never used to derive a
    schema. Callers generating documentation need not supply samples.
    """
    projections = {
        "Summary": summary, "Thermo": thermo, "ThermoRecent": thermo_recent,
        "Candidates": candidates, "Signal": signal, "Health": health,
        "ResearchReport": research_report, "ResearchSignal": research_signal,
        "ResearchSeries": research_series,
    }
    for component, value in projections.items():
        if value is not None:
            validate_public_projection(component, value)
    for value in thermo_years or []:
        validate_public_projection("ThermoYear", value)
    return deepcopy(_checked_document())


@lru_cache(maxsize=1)
def _openapi_document() -> dict[str, Any]:
    components = {**public_schemas(), **artifact_schemas()}
    paths = {
        "/api/v1/summary.json": _get("Summary", "Public VRP headline summary."),
        "/api/v1/thermo.json": _get("Thermo", "Complete published VRP series."),
        "/api/v1/thermo/recent.json": _get(
            "ThermoRecent",
            "Most recent published VRP observations.",
        ),
        "/api/v1/thermo/by-year/{year}.json": {
            "get": {
                "summary": "Calendar-year VRP shard",
                "parameters": [
                    {
                        "name": "year",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": r"^\d{4}$",
                        },
                    }
                ],
                **_responses("ThermoYear", "One calendar year of published VRP data."),
            }
        },
        "/api/v1/candidates.json": _get(
            "Candidates",
            "Position-independent candidate research projection.",
        ),
        "/api/v1/signal.json": _get(
            "Signal",
            "Public signal artifact wrapper with evidence annotations.",
        ),
        "/api/v1/health.json": _get(
            "Health",
            "Static publication health and durable receipt history.",
        ),
        "/api/v1/manifest.json": _get(
            "Manifest",
            "Canonical publication manifest and artifact hashes.",
        ),
        "/.well-known/publish-manifest.json": _get(
            "Manifest",
            "Byte-identical public publication manifest mirror.",
        ),
        "/research/report": _get(
            "ResearchReport",
            "Sanitized public research report projection.",
        ),
        "/research/signal": _get(
            "ResearchSignal",
            "Sanitized public signal artifact projection.",
        ),
        "/research/series": _get(
            "ResearchSeries",
            "Sanitized public longitudinal series projection.",
        ),
    }
    return {
        "openapi": "3.1.0",
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "info": {
            "title": "LensOS Option Public API",
            "version": PUBLIC_API_VERSION,
            "description": (
                "Static, read-only research publication endpoints. Values are "
                "evidence, not trade instructions or execution authorization."
            ),
        },
        "paths": paths,
        "components": {"schemas": components},
    }


def _get(component: str, description: str) -> dict[str, Any]:
    return {
        "get": {
            "summary": description.rstrip("."),
            **_responses(component, description),
        }
    }


def _responses(component: str, description: str) -> dict[str, Any]:
    return {
        "responses": {
            "200": {
                "description": description,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{component}"}
                    }
                },
            }
        }
    }


_SUPPORTED_KEYWORDS = frozenset({
    "$ref", "type", "properties", "required", "additionalProperties", "items",
    "anyOf", "enum", "const", "minimum", "maximum", "minItems", "maxItems",
    "minLength", "maxLength", "pattern", "format", "description", "title",
})
_TYPES = frozenset({"null", "boolean", "number", "integer", "string", "array", "object"})


def _check_schema(schema: dict[str, Any], document: dict[str, Any]) -> None:
    unsupported = set(schema) - _SUPPORTED_KEYWORDS
    if unsupported:
        raise ValueError(f"unsupported public schema keywords: {sorted(unsupported)}")
    if "$ref" in schema:
        _resolve_ref(schema["$ref"], document)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not types or set(types) - _TYPES:
            raise ValueError("unsupported public schema type")
    if schema.get("format") not in {None, "date", "date-time"}:
        raise ValueError("unsupported public schema format")
    for child in schema.get("properties", {}).values():
        _check_schema(child, document)
    for key in ("items", "additionalProperties"):
        child = schema.get(key)
        if isinstance(child, dict):
            _check_schema(child, document)
    for child in schema.get("anyOf", []):
        _check_schema(child, document)


@lru_cache(maxsize=1)
def _checked_document() -> dict[str, Any]:
    document = _openapi_document()
    for schema in document["components"]["schemas"].values():
        _check_schema(schema, document)
    return document


def _resolve_ref(reference: str, document: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/components/schemas/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValueError("public contract only supports local component references")
    name = reference[len(prefix):]
    try:
        component = document["components"]["schemas"][name]
    except KeyError as exc:
        raise ValueError(f"unknown public contract component: {name}") from exc
    if not isinstance(component, dict):
        raise ValueError(f"invalid public contract component: {name}")
    return component


def validate_public_projection(component: str, value: object) -> None:
    """Raise before publishing any data not accepted by this version's schema.

    Checks structure and finite JSON numbers; it does not claim to establish
    market freshness, statistical validity, or any execution authorization.
    Error messages contain property paths, never the rejected data values.
    """
    document = _checked_document()
    schema = _resolve_ref(f"#/components/schemas/{component}", document)
    _validate(value, schema, document=document, path=f"$.{component}")


def _matches_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected in {"integer", "number"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if isinstance(value, float) and not isfinite(value):
            return False
        return expected == "number" or isinstance(value, int) or value.is_integer()
    return isinstance(value, {"string": str, "array": list, "object": dict}[expected])


def _json_equal(left: object, right: object) -> bool:
    # Python considers True == 1; JSON Schema distinguishes booleans/numbers.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _validate(value: object, schema: dict[str, Any], *, document: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        _validate(value, _resolve_ref(schema["$ref"], document), document=document, path=path)
    if "anyOf" in schema:
        failures = []
        for branch in schema["anyOf"]:
            try:
                _validate(value, branch, document=document, path=path)
                break
            except PublicContractError as exc:
                failures.append(str(exc))
        else:
            # Preserve the nested field failure so publishers can fix its cause.
            raise PublicContractError(f"{path} matches no allowed variant: {'; '.join(failures)}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_matches_type(value, expected) for expected in types):
            raise PublicContractError(f"{path} must be {' or '.join(types)}")
    if "enum" in schema and not any(_json_equal(value, member) for member in schema["enum"]):
        raise PublicContractError(f"{path} has an unsupported enum member")
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise PublicContractError(f"{path} violates its fixed value")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise PublicContractError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if not isinstance(key, str):
                raise PublicContractError(f"{path} requires string object keys")
            child = properties.get(key)
            if child is None and additional is False:
                raise PublicContractError(f"{path}.{key} is not a public contract field")
            if child is None and isinstance(additional, dict):
                child = additional
            if child is not None:
                _validate(item, child, document=document, path=f"{path}.{key}")
    elif isinstance(value, list):
        for bound, predicate in (("minItems", len(value) < schema.get("minItems", 0)), ("maxItems", len(value) > schema.get("maxItems", len(value)))):
            if predicate:
                raise PublicContractError(f"{path} violates {bound}")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], document=document, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise PublicContractError(f"{path} violates string length")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise PublicContractError(f"{path} violates its string pattern")
        try:
            if schema.get("format") == "date":
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
                    raise ValueError
                date.fromisoformat(value)
            elif schema.get("format") == "date-time":
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value) is None:
                    raise ValueError
                datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
        except ValueError as exc:
            raise PublicContractError(f"{path} must be a valid {schema['format']}") from exc
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not isfinite(value):
            raise PublicContractError(f"{path} must be a finite JSON number")
        if "minimum" in schema and value < schema["minimum"]:
            raise PublicContractError(f"{path} violates minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise PublicContractError(f"{path} violates maximum")
