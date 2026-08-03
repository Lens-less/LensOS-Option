"""OpenAPI contract generated from the already-sanitized public projections."""

from __future__ import annotations

import json
import re
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def build_public_openapi(
    *,
    summary: dict[str, Any],
    thermo: dict[str, Any],
    thermo_recent: dict[str, Any],
    thermo_years: list[dict[str, Any]],
    candidates: dict[str, Any],
    signal: dict[str, Any],
    health: dict[str, Any],
    research_report: dict[str, Any],
    research_signal: dict[str, Any],
    research_series: dict[str, Any],
) -> dict[str, Any]:
    """Return a concrete OpenAPI 3.1 document for every published JSON route.

    Schema inference runs only over explicit public projections.  Object key sets
    are closed at every observed level, so adding a field to a projection changes
    the contract and its deterministic publication hash in the same build.
    """
    components = {
        "Summary": _schema_for_value(summary),
        "Thermo": _schema_for_value(thermo),
        "ThermoRecent": _schema_for_value(thermo_recent),
        "ThermoYear": _schema_for_sequence(thermo_years),
        "Candidates": _schema_for_value(candidates),
        "Signal": _schema_for_value(signal),
        "Health": _schema_for_value(health),
        "Manifest": _manifest_schema(),
        "ResearchReport": _schema_for_value(research_report),
        "ResearchSignal": _schema_for_value(research_signal),
        "ResearchSeries": _schema_for_value(research_series),
    }
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
        "info": {
            "title": "LensOS Option Public API",
            "version": "1.0.0",
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


def _schema_for_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        schema: dict[str, Any] = {"type": "string"}
        if _DATE_TIME_RE.fullmatch(value):
            schema["format"] = "date-time"
        elif _DATE_RE.fullmatch(value):
            schema["format"] = "date"
        return schema
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _schema_for_sequence(value),
        }
    if isinstance(value, dict):
        properties = {
            str(key): _schema_for_value(nested)
            for key, nested in sorted(value.items())
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    raise TypeError(f"unsupported public API value type: {type(value).__name__}")


def _schema_for_sequence(values: list[Any]) -> dict[str, Any]:
    if not values:
        return {}
    if all(isinstance(value, dict) for value in values):
        rows = [value for value in values if isinstance(value, dict)]
        keys = sorted({str(key) for row in rows for key in row})
        required = [key for key in keys if all(key in row for row in rows)]
        properties = {
            key: _merge_schemas(
                [_schema_for_value(row[key]) for row in rows if key in row]
            )
            for key in keys
        }
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
    return _merge_schemas([_schema_for_value(value) for value in values])


def _merge_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        candidates = schema["anyOf"] if set(schema) == {"anyOf"} else [schema]
        for candidate in candidates:
            key = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            unique[key] = candidate
    if len(unique) == 1:
        return next(iter(unique.values()))
    return {"anyOf": [unique[key] for key in sorted(unique)]}


def _manifest_schema() -> dict[str, Any]:
    string = {"type": "string"}
    timestamp = {"type": "string", "format": "date-time"}
    properties: dict[str, Any] = {
        "schema_version": string,
        "analysis_run_id": string,
        "analysis_record_sha256": string,
        "captured_at": timestamp,
        "published_at": timestamp,
        "evaluation_clock": timestamp,
        "next_expected_at": timestamp,
        "stale_after": timestamp,
        "cadence": string,
        "engine_version": string,
        "git_sha": {"anyOf": [string, {"type": "null"}]},
        "git_provenance": {"type": "object"},
        "web_build_source": {"type": "object"},
        "input_hashes": {"type": "object"},
        "artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": string,
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "bytes": {"type": "integer", "minimum": 0},
                },
                "required": ["path", "sha256", "bytes"],
                "additionalProperties": False,
            },
        },
        "manifest_verification": {"type": "object"},
        "manifest_policy": {"type": "object"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
