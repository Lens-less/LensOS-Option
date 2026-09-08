"""One lazy, detached compatibility output per immutable analysis record."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, cast

from ._canonical import canonical_json_text
from .analysis_inputs import AnalysisInputs, ReportProjectionOptions


@dataclass(frozen=True, slots=True)
class CompatibilityProjection:
    """Cache output-only work; none of its state participates in admission.

    In particular, reading the optional approval runbook must happen only when
    a caller explicitly asks for the legacy report. A lock keeps simultaneous
    HTTP projections on the same record from repeating that read.
    """

    inputs: AnalysisInputs
    options: ReportProjectionOptions
    legacy_json: str = ""
    _cached_json: str | None = field(default=None, init=False, compare=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, compare=False, repr=False)

    def read(self) -> dict[str, Any]:
        if self.legacy_json:
            return cast(dict[str, Any], json.loads(self.legacy_json))
        with self._lock:
            if self._cached_json is None:
                from .contract import project_analysis_inputs

                payload = project_analysis_inputs(self.inputs, self.options)
                object.__setattr__(self, "_cached_json", canonical_json_text(payload))
            encoded = self._cached_json
        assert encoded is not None
        return cast(dict[str, Any], json.loads(encoded))
