"""Canonical JSON encoding shared by every digest and signature in the project.

The evidence model binds reports, backtest artifacts, and sidecar snapshots by
SHA-256 over their JSON encoding. Those digests are only comparable if every
producer and verifier encodes bytes identically, so the encoding lives here once
rather than being restated at each call site.

The encoding is fixed and must not be changed casually: altering `sort_keys`,
`separators`, `ensure_ascii`, or `allow_nan` silently invalidates every digest
recorded before the change.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from enum import Enum
from typing import Any

__all__ = [
    "canonical_json_bytes",
    "canonical_json_text",
    "canonical_sha256",
    "to_jsonable",
]


def to_jsonable(value: Any) -> Any:
    """Reduce domain objects to plain JSON types without changing their meaning.

    Plain JSON input passes through structurally unchanged, so this is safe to
    apply before encoding payloads that are already JSON-shaped.
    """
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical JSON cannot encode non-finite numbers")
    return value


def canonical_json_text(value: Any) -> str:
    """Encode `value` as canonical JSON text."""
    return json.dumps(
        to_jsonable(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode `value` as canonical JSON bytes, the input to every digest."""
    return canonical_json_text(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the hex SHA-256 of `value`'s canonical JSON encoding."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
