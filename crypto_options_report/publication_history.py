"""Validated projection of durable publication receipts for the public status page."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ._canonical import canonical_sha256
from .public_origin import validate_public_site_origin

PUBLICATION_HISTORY_SCHEMA = "publication_history.v1"
PUBLICATION_HISTORY_WINDOW_DAYS = 30

_ROOT_FIELDS = {"schema_version", "generated_at", "entries"}
_ENTRY_FIELDS = {
    "date",
    "captured_at",
    "published_at",
    "status",
    "research_publication_status",
    "capture_row_count",
    "quality_gate_blocked_count",
    "excluded_snapshot_count",
    "manifest_sha256",
    "reason_code",
    "monitoring_proof",
}
_ENTRY_REQUIRED_FIELDS = _ENTRY_FIELDS - {"monitoring_proof"}
_MONITORING_PROOF_FIELDS = {"schema_version", "projection", "projection_sha256"}
_MONITORING_PROJECTION_FIELDS = {
    "attestation_schema_version",
    "check_interval_seconds",
    "checked_at",
    "contract",
    "failure_delivery_drill_at",
    "failure_webhook_sha256",
    "health_url",
    "monitor_id",
    "site_origin",
    "status",
    "success_heartbeat_sha256",
}
_MANIFEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_MONITOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def build_publication_history(
    payload: Any,
    *,
    published_at: str,
) -> dict[str, Any]:
    """Validate private receipts and return a narrow 30-day public projection."""
    if not isinstance(payload, dict):
        raise ValueError("publication history must be a JSON object")
    unexpected_root = sorted(set(payload) - _ROOT_FIELDS)
    if unexpected_root:
        raise ValueError(
            f"publication history contains unapproved root field {unexpected_root[0]}"
        )
    missing_root = sorted(_ROOT_FIELDS - set(payload))
    if missing_root:
        raise ValueError(f"publication history missing root field {missing_root[0]}")
    if payload.get("schema_version") != PUBLICATION_HISTORY_SCHEMA:
        raise ValueError("publication history schema_version is unsupported")

    publication_dt = _parse_timestamp(published_at, field="published_at")
    generated_dt = _parse_timestamp(
        payload.get("generated_at"),
        field="publication history generated_at",
    )
    if generated_dt > publication_dt:
        raise ValueError("publication history generated_at exceeds published_at")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("publication history entries must be a list")

    validated: list[dict[str, Any]] = []
    seen_dates: set[date] = set()
    for index, entry in enumerate(entries):
        validated_entry = _validate_entry(entry, index=index)
        entry_date = date.fromisoformat(validated_entry["date"])
        if entry_date in seen_dates:
            raise ValueError(
                f"duplicate publication history date {validated_entry['date']}"
            )
        seen_dates.add(entry_date)
        if entry_date > publication_dt.date():
            raise ValueError("publication history contains a future receipt")
        if _parse_timestamp(
            validated_entry["published_at"],
            field=f"publication history entry {index} published_at",
        ) > publication_dt:
            raise ValueError("publication history receipt published_at exceeds publication")
        validated.append(validated_entry)

    first_in_window = publication_dt.date() - timedelta(
        days=PUBLICATION_HISTORY_WINDOW_DAYS - 1
    )
    public_entries = [
        _project_entry(entry)
        for entry in sorted(validated, key=lambda item: item["date"])
        if first_in_window <= date.fromisoformat(entry["date"]) <= publication_dt.date()
    ]
    if not public_entries:
        return {
            "status": "collecting",
            "window_days": PUBLICATION_HISTORY_WINDOW_DAYS,
            "history": [],
            "reason": "No durable publication receipts are available in the 30-day window.",
        }
    return {
        "status": "available",
        "window_days": PUBLICATION_HISTORY_WINDOW_DAYS,
        "history": public_entries,
        "reason": None,
    }


def _validate_entry(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"publication history entry {index} must be an object")
    unexpected = sorted(set(value) - _ENTRY_FIELDS)
    if unexpected:
        raise ValueError(
            f"publication history contains unapproved entry field {unexpected[0]}"
        )
    missing = sorted(_ENTRY_REQUIRED_FIELDS - set(value))
    if missing:
        raise ValueError(f"publication history entry {index} missing field {missing[0]}")

    published_dt = _parse_timestamp(
        value.get("published_at"),
        field=f"publication history entry {index} published_at",
    )
    if "monitoring_proof" in value:
        _validate_monitoring_proof(
            value.get("monitoring_proof"),
            index=index,
            published_at=published_dt,
        )
    date_value = value.get("date")
    if not isinstance(date_value, str):
        raise ValueError(f"publication history entry {index} date must be YYYY-MM-DD")
    try:
        parsed_date = date.fromisoformat(date_value)
    except ValueError as exc:
        raise ValueError(
            f"publication history entry {index} date must be YYYY-MM-DD"
        ) from exc
    if parsed_date != published_dt.date():
        raise ValueError(
            f"publication history entry {index} date must match published_at"
        )

    captured_at = value.get("captured_at")
    if captured_at is not None:
        captured_dt = _parse_timestamp(
            captured_at,
            field=f"publication history entry {index} captured_at",
        )
        if captured_dt > published_dt:
            raise ValueError(
                f"publication history entry {index} captured_at exceeds published_at"
            )

    status = value.get("status")
    research_status = value.get("research_publication_status")
    manifest_sha = value.get("manifest_sha256")
    reason_code = value.get("reason_code")
    if status == "success":
        if research_status != "GO":
            raise ValueError("successful publication receipt requires research GO")
        if not isinstance(manifest_sha, str) or _MANIFEST_RE.fullmatch(manifest_sha) is None:
            raise ValueError(
                "successful publication receipt requires manifest_sha256"
            )
        if reason_code is not None:
            raise ValueError("successful publication receipt must not carry reason_code")
    elif status == "failed":
        if research_status != "NO-GO":
            raise ValueError("failed publication receipt requires research NO-GO")
        if manifest_sha is not None:
            raise ValueError("failed publication receipt must not carry manifest_sha256")
        if not isinstance(reason_code, str) or _REASON_CODE_RE.fullmatch(reason_code) is None:
            raise ValueError("failed publication receipt requires reason_code")
    else:
        raise ValueError("publication history entry status must be success or failed")

    for field in (
        "capture_row_count",
        "quality_gate_blocked_count",
        "excluded_snapshot_count",
    ):
        count = value.get(field)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(
                f"publication history entry {index} {field} must be a non-negative integer"
            )

    return dict(value)


def _validate_monitoring_proof(
    value: Any,
    *,
    index: int,
    published_at: datetime,
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(
            f"publication history entry {index} monitoring_proof must be an object"
        )
    unexpected = sorted(set(value) - _MONITORING_PROOF_FIELDS)
    if unexpected:
        raise ValueError(
            f"unapproved monitoring proof field {unexpected[0]}"
        )
    missing = sorted(_MONITORING_PROOF_FIELDS - set(value))
    if missing:
        raise ValueError(f"monitoring proof missing field {missing[0]}")
    if value.get("schema_version") != "monitoring_admission_evidence.v1":
        raise ValueError("monitoring proof schema_version is unsupported")

    projection = value.get("projection")
    if not isinstance(projection, dict):
        raise ValueError("monitoring proof projection must be an object")
    unexpected_projection = sorted(set(projection) - _MONITORING_PROJECTION_FIELDS)
    if unexpected_projection:
        raise ValueError(
            "unapproved monitoring projection field "
            f"{unexpected_projection[0]}"
        )
    missing_projection = sorted(_MONITORING_PROJECTION_FIELDS - set(projection))
    if missing_projection:
        raise ValueError(
            f"monitoring projection missing field {missing_projection[0]}"
        )

    if (
        projection.get("attestation_schema_version")
        != "lensos_stale_monitor_attestation.v1"
    ):
        raise ValueError("monitoring projection attestation_schema_version is invalid")
    monitor_id = projection.get("monitor_id")
    if not isinstance(monitor_id, str) or _MONITOR_ID_RE.fullmatch(monitor_id) is None:
        raise ValueError("monitoring projection monitor_id is invalid")
    check_interval = projection.get("check_interval_seconds")
    if (
        not isinstance(check_interval, int)
        or isinstance(check_interval, bool)
        or not 60 <= check_interval <= 3600
    ):
        raise ValueError("monitoring projection check_interval_seconds is invalid")
    if projection.get("contract") != "compare_current_time_to_stale_after":
        raise ValueError("monitoring projection contract is invalid")
    if projection.get("status") not in {"armed", "healthy"}:
        raise ValueError("monitoring projection status is invalid")

    site_origin = projection.get("site_origin")
    if not isinstance(site_origin, str):
        raise ValueError("monitoring projection site_origin is invalid")
    try:
        normalized_origin = validate_public_site_origin(site_origin)
    except ValueError as exc:
        raise ValueError("monitoring projection site_origin is invalid") from exc
    if site_origin != normalized_origin:
        raise ValueError("monitoring projection site_origin is invalid")
    if projection.get("health_url") != f"{site_origin}/api/v1/health.json":
        raise ValueError("monitoring projection health_url is invalid")

    for field in ("failure_webhook_sha256", "success_heartbeat_sha256"):
        fingerprint = projection.get(field)
        if not isinstance(fingerprint, str) or _MANIFEST_RE.fullmatch(fingerprint) is None:
            raise ValueError(f"monitoring projection {field} is invalid")

    checked_at = _parse_timestamp(
        projection.get("checked_at"),
        field="monitoring projection checked_at",
    )
    failure_drill_at = _parse_timestamp(
        projection.get("failure_delivery_drill_at"),
        field="monitoring projection failure_delivery_drill_at",
    )
    if checked_at > published_at + timedelta(minutes=5):
        raise ValueError("monitoring projection checked_at exceeds receipt published_at")
    if failure_drill_at > checked_at + timedelta(minutes=5):
        raise ValueError("monitoring projection failure_delivery_drill_at exceeds checked_at")

    projection_sha = value.get("projection_sha256")
    if not isinstance(projection_sha, str) or _MANIFEST_RE.fullmatch(projection_sha) is None:
        raise ValueError("monitoring proof projection_sha256 is invalid")
    if projection_sha != canonical_sha256(projection):
        raise ValueError("monitoring proof projection_sha256 does not match projection")


def _project_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": entry["date"],
        "captured_at": entry["captured_at"],
        "published_at": entry["published_at"],
        "status": entry["status"],
        "research_publication_status": entry["research_publication_status"],
        "capture_row_count": entry["capture_row_count"],
        "quality_gate_blocked_count": entry["quality_gate_blocked_count"],
        "excluded_snapshot_count": entry["excluded_snapshot_count"],
        "reason_code": entry["reason_code"],
    }


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)
