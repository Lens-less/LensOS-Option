"""Shared UTC timestamp formatting for persisted research artifacts."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_timestamp() -> str:
    """Return the current UTC instant at the contract-wide second precision."""
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
