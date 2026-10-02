"""Small structured-logging boundary shared by the API and sidecars."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from ._time import utc_timestamp


def _log_json(
    event: str,
    *,
    constant_fields: Mapping[str, Any] | None = None,
    stream: TextIO | None = None,
    **fields: Any,
) -> None:
    """Write one deterministic JSON event without interpolating field values."""
    payload = {
        "timestamp": utc_timestamp(),
        "event": event,
        **dict(constant_fields or {}),
        **fields,
    }
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=stream or sys.stderr,
    )
