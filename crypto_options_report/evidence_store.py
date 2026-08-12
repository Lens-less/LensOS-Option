"""Immutable, content-addressed evidence artifacts for local research jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._canonical import canonical_json_bytes
from .backtest import (
    BASELINE_BACKTEST_SCHEMA_VERSION,
    build_fixed_baseline_backtest_report,
)
from .historical import FAILURE_CODES
from .storage import atomic_write_json, read_json_object_from_regular_file

BACKTEST_ARTIFACT_SCHEMA_VERSION = "backtest_evidence_artifact.v1"
BACKTEST_LOOKUP_SCHEMA_VERSION = "backtest_report_lookup.v1"
MAX_HISTORICAL_FIXTURE_BYTES = 32 * 1024 * 1024
MAX_BACKTEST_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_BACKTEST_JOB_RECORD_BYTES = 1024 * 1024
MAX_BACKTEST_ROWS = 50_000
MAX_BACKTEST_WINDOWS = 5_000
MAX_BACKTEST_PATH_STEPS = 100_000
_REPORT_ID = re.compile(r"^bt-[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^job-[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_FILENAME = re.compile(r"^idempotency-([0-9a-f]{64})\.json$")
_IDEMPOTENCY_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "job_id",
        "request_sha256",
        "fixture_sha256",
    }
)
_CURRENT_JOB_KEYS = frozenset(
    {
        "schema_version",
        "job_id",
        "status",
        "submitted_at",
        "started_at",
        "completed_at",
        "request_sha256",
        "fixture_sha256",
        "idempotency_key_sha256",
        "status_url",
        "result_url",
        "report_id",
        "report_url",
        "default_promotion_status",
        "reason_code",
        "research_only",
    }
)
_LEGACY_PROMOTION_JOB_KEYS = frozenset(
    {
        "schema_version",
        "job_id",
        "status",
        "completed_at",
        "report_id",
        "default_promotion_status",
    }
)
_PUBLIC_JOB_KEYS = _CURRENT_JOB_KEYS - {
    "fixture_sha256",
    "idempotency_key_sha256",
}
_BACKTEST_ARTIFACT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "aligned",
        "reason_code",
        "generated_at",
        "source_fixture",
        "backtest_report",
        "backtest_comparison",
        "research_only",
        "report_id",
    }
)
_BASELINE_BACKTEST_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "generated_at",
        "fixture_window",
        "baseline_policy",
        "historical_reconciliation",
        "selection_log",
        "fill_audit",
        "trades",
        "replay_points",
        "metrics",
        "summary",
        "window_summary",
        "execution_audit",
        "aggregate_metrics",
    }
)
_BASELINE_BACKTEST_DICT_FIELDS = frozenset(
    {
        "fixture_window",
        "baseline_policy",
        "historical_reconciliation",
        "fill_audit",
        "metrics",
        "summary",
        "window_summary",
        "execution_audit",
        "aggregate_metrics",
    }
)
_BASELINE_BACKTEST_LIST_FIELDS = frozenset(
    {"selection_log", "trades", "replay_points"}
)
# Every mapping shape emitted by baseline_backtest_report.v1 is versioned here.
# This is intentionally exact: a valid content hash proves immutability, not that
# an unexpected persisted field is safe to expose through the public result API.
_BASELINE_BACKTEST_OBJECT_KEYSETS = frozenset(
    frozenset(keys)
    for keys in (
        ("bid",),
        ("decision",),
        ("ask", "expiry_settlement"),
        ("considered_candidates", "selected_is_closest_to_target"),
        ("entry_fee_usdc", "hypothetical_exit_fee_usdc"),
        ("reason", "status"),
        ("status", "value"),
        ("basis", "status", "value"),
        ("cagr_pct", "margin_breach_count", "total_return_proxy_pct"),
        ("metric", "reason", "status"),
        ("starting_nav_usdc", "touch_event_count", "trade_count"),
        (
            "disallowed_fill_sources",
            "entry_fill_source_counts",
            "exit_fill_source_counts",
            "optimistic_fill_detected",
        ),
        (
            "dte_tolerance_days",
            "max_abs_delta",
            "target_abs_delta",
            "target_dte_days",
        ),
        ("ended_at", "name", "snapshot_count", "started_at"),
        (
            "entry_fill_sources",
            "exit_fill_sources",
            "optimistic_fill_sources_present",
            "passed",
        ),
        ("fills", "research_only", "selection", "structure"),
        (
            "ranked_candidates",
            "selected_instrument_name",
            "snapshot_key",
            "timestamp",
        ),
        ("abs_delta", "ask", "bid", "dte_days", "instrument_name"),
        (
            "backtest_allowed",
            "eligible_quotes",
            "failure_counts",
            "quarantined_quotes",
            "status",
        ),
        ("entry", "exit_buyback", "expiry", "forbidden", "mark_to_market"),
        (
            "realized_pnl_usdc",
            "total_fees_usdc",
            "touch_event_count",
            "trade_count",
            "unavailable_metrics",
        ),
        (
            "ask",
            "bid",
            "contract_size",
            "contracts",
            "entry_credit_usdc",
            "entry_fee_usdc",
            "fill_source",
            "underlying_price",
        ),
        (
            "buyback_ask_usdc",
            "buyback_cost_usdc",
            "close_timestamp",
            "exit_fee_usdc",
            "expiry_outcome",
            "fees_total_usdc",
            "fill_source",
            "premium_retained_usdc",
            "realized_pnl_usdc",
        ),
        (
            "close_timestamp",
            "delivery_fee_usdc",
            "delivery_price",
            "expiry_outcome",
            "fees_total_usdc",
            "fill_source",
            "payoff_usdc",
            "premium_retained_usdc",
            "realized_pnl_usdc",
        ),
        (
            "cagr",
            "cvar_95",
            "cvar_99",
            "forced_close_count",
            "margin_breach_count",
            "max_drawdown",
            "premium_captured_ratio",
            "total_return_proxy",
            "touch_rate",
            "worst_month",
            "worst_week",
        ),
        tuple(sorted(_BASELINE_BACKTEST_REPORT_KEYS)),
        (
            "ask",
            "bid",
            "coin_pnl",
            "expiry_outcome",
            "fees_usdc",
            "fill_reference",
            "forced_close_placeholder",
            "instrument_name",
            "mtm_pnl_usdc",
            "snapshot_key",
            "timestamp",
            "touch_event",
            "underlying_price",
            "usd_shadow_pnl_usdc",
        ),
        (
            "ask",
            "bid",
            "close_event",
            "coin_pnl",
            "expiry_outcome",
            "fees_usdc",
            "fill_reference",
            "forced_close_placeholder",
            "instrument_name",
            "mtm_pnl_usdc",
            "snapshot_key",
            "timestamp",
            "touch_event",
            "underlying_price",
            "usd_shadow_pnl_usdc",
        ),
        (
            "abs_delta",
            "close",
            "close_reason",
            "closed_at",
            "dte_days",
            "entry",
            "entry_snapshot_eligibility",
            "entry_snapshot_key",
            "entry_timestamp",
            "expiry",
            "fees_total_usdc",
            "forced_close_placeholder",
            "instrument_name",
            "premium_retained_usdc",
            "realized_pnl_usdc",
            "replay_points",
            "selected_dte_days",
            "selected_model_delta",
            "selection",
            "settlement_currency",
            "status",
            "strike",
            "touched",
        ),
        (
            "abs_delta",
            "close",
            "close_reason",
            "closed_at",
            "dte_days",
            "entry",
            "entry_snapshot_eligibility",
            "entry_snapshot_key",
            "entry_timestamp",
            "expiry",
            "fees_total_usdc",
            "forced_close_placeholder",
            "instrument_name",
            "premium_retained_usdc",
            "realized_pnl_usdc",
            "replay_points",
            "selected_dte_days",
            "selected_model_delta",
            "selection",
            "settlement_currency",
            "status",
            "strike",
            "touched",
            "window_id",
        ),
    )
)
# The global registry above prevents unknown shapes. This path registry prevents a
# known shape from being moved to an unrelated public field and reflected as if it
# carried that field's semantics.
_BASELINE_BACKTEST_OBJECT_PATH_KEYSETS = {
    (): (_BASELINE_BACKTEST_REPORT_KEYS,),
    ("fixture_window",): (
        frozenset({"ended_at", "name", "snapshot_count", "started_at"}),
    ),
    ("baseline_policy",): (
        frozenset({"fills", "research_only", "selection", "structure"}),
    ),
    ("baseline_policy", "selection"): (
        frozenset(
            {
                "dte_tolerance_days",
                "max_abs_delta",
                "target_abs_delta",
                "target_dte_days",
            }
        ),
    ),
    ("baseline_policy", "fills"): (
        frozenset({"entry", "exit_buyback", "expiry", "forbidden", "mark_to_market"}),
    ),
    ("historical_reconciliation",): (
        frozenset(
            {
                "backtest_allowed",
                "eligible_quotes",
                "failure_counts",
                "quarantined_quotes",
                "status",
            }
        ),
    ),
    ("selection_log", "[]"): (
        frozenset(
            {
                "ranked_candidates",
                "selected_instrument_name",
                "snapshot_key",
                "timestamp",
            }
        ),
    ),
    ("selection_log", "[]", "ranked_candidates", "[]"): (
        frozenset({"abs_delta", "ask", "bid", "dte_days", "instrument_name"}),
    ),
    ("fill_audit",): (
        frozenset(
            {
                "disallowed_fill_sources",
                "entry_fill_source_counts",
                "exit_fill_source_counts",
                "optimistic_fill_detected",
            }
        ),
    ),
    ("fill_audit", "entry_fill_source_counts"): (frozenset({"bid"}),),
    ("fill_audit", "exit_fill_source_counts"): (
        frozenset({"ask", "expiry_settlement"}),
    ),
    ("trades", "[]"): (
        frozenset(
            {
                "abs_delta",
                "close",
                "close_reason",
                "closed_at",
                "dte_days",
                "entry",
                "entry_snapshot_eligibility",
                "entry_snapshot_key",
                "entry_timestamp",
                "expiry",
                "fees_total_usdc",
                "forced_close_placeholder",
                "instrument_name",
                "premium_retained_usdc",
                "realized_pnl_usdc",
                "replay_points",
                "selected_dte_days",
                "selected_model_delta",
                "selection",
                "settlement_currency",
                "status",
                "strike",
                "touched",
            }
        ),
        frozenset(
            {
                "abs_delta",
                "close",
                "close_reason",
                "closed_at",
                "dte_days",
                "entry",
                "entry_snapshot_eligibility",
                "entry_snapshot_key",
                "entry_timestamp",
                "expiry",
                "fees_total_usdc",
                "forced_close_placeholder",
                "instrument_name",
                "premium_retained_usdc",
                "realized_pnl_usdc",
                "replay_points",
                "selected_dte_days",
                "selected_model_delta",
                "selection",
                "settlement_currency",
                "status",
                "strike",
                "touched",
                "window_id",
            }
        ),
    ),
    ("trades", "[]", "entry_snapshot_eligibility"): (
        frozenset({"decision"}),
    ),
    ("trades", "[]", "selection"): (
        frozenset({"considered_candidates", "selected_is_closest_to_target"}),
    ),
    ("trades", "[]", "selection", "considered_candidates", "[]"): (
        frozenset({"abs_delta", "ask", "bid", "dte_days", "instrument_name"}),
    ),
    ("trades", "[]", "entry"): (
        frozenset(
            {
                "ask",
                "bid",
                "contract_size",
                "contracts",
                "entry_credit_usdc",
                "entry_fee_usdc",
                "fill_source",
                "underlying_price",
            }
        ),
    ),
    ("trades", "[]", "forced_close_placeholder"): (
        frozenset({"reason", "status"}),
    ),
    ("trades", "[]", "replay_points", "[]"): (
        frozenset(
            {
                "ask",
                "bid",
                "coin_pnl",
                "expiry_outcome",
                "fees_usdc",
                "fill_reference",
                "forced_close_placeholder",
                "instrument_name",
                "mtm_pnl_usdc",
                "snapshot_key",
                "timestamp",
                "touch_event",
                "underlying_price",
                "usd_shadow_pnl_usdc",
            }
        ),
        frozenset(
            {
                "ask",
                "bid",
                "close_event",
                "coin_pnl",
                "expiry_outcome",
                "fees_usdc",
                "fill_reference",
                "forced_close_placeholder",
                "instrument_name",
                "mtm_pnl_usdc",
                "snapshot_key",
                "timestamp",
                "touch_event",
                "underlying_price",
                "usd_shadow_pnl_usdc",
            }
        ),
    ),
    ("replay_points", "[]"): (
        frozenset(
            {
                "ask",
                "bid",
                "coin_pnl",
                "expiry_outcome",
                "fees_usdc",
                "fill_reference",
                "forced_close_placeholder",
                "instrument_name",
                "mtm_pnl_usdc",
                "snapshot_key",
                "timestamp",
                "touch_event",
                "underlying_price",
                "usd_shadow_pnl_usdc",
            }
        ),
        frozenset(
            {
                "ask",
                "bid",
                "close_event",
                "coin_pnl",
                "expiry_outcome",
                "fees_usdc",
                "fill_reference",
                "forced_close_placeholder",
                "instrument_name",
                "mtm_pnl_usdc",
                "snapshot_key",
                "timestamp",
                "touch_event",
                "underlying_price",
                "usd_shadow_pnl_usdc",
            }
        ),
    ),
    ("trades", "[]", "replay_points", "[]", "coin_pnl"): (
        frozenset({"status", "value"}),
    ),
    ("replay_points", "[]", "coin_pnl"): (frozenset({"status", "value"}),),
    ("trades", "[]", "replay_points", "[]", "fees_usdc"): (
        frozenset({"entry_fee_usdc", "hypothetical_exit_fee_usdc"}),
    ),
    ("replay_points", "[]", "fees_usdc"): (
        frozenset({"entry_fee_usdc", "hypothetical_exit_fee_usdc"}),
    ),
    ("trades", "[]", "replay_points", "[]", "forced_close_placeholder"): (
        frozenset({"reason", "status"}),
    ),
    ("replay_points", "[]", "forced_close_placeholder"): (
        frozenset({"reason", "status"}),
    ),
    ("trades", "[]", "replay_points", "[]", "close_event"): (
        frozenset(
            {
                "buyback_ask_usdc",
                "buyback_cost_usdc",
                "close_timestamp",
                "exit_fee_usdc",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
        frozenset(
            {
                "close_timestamp",
                "delivery_fee_usdc",
                "delivery_price",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "payoff_usdc",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
    ),
    ("replay_points", "[]", "close_event"): (
        frozenset(
            {
                "buyback_ask_usdc",
                "buyback_cost_usdc",
                "close_timestamp",
                "exit_fee_usdc",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
        frozenset(
            {
                "close_timestamp",
                "delivery_fee_usdc",
                "delivery_price",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "payoff_usdc",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
    ),
    ("trades", "[]", "close"): (
        frozenset(
            {
                "buyback_ask_usdc",
                "buyback_cost_usdc",
                "close_timestamp",
                "exit_fee_usdc",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
        frozenset(
            {
                "close_timestamp",
                "delivery_fee_usdc",
                "delivery_price",
                "expiry_outcome",
                "fees_total_usdc",
                "fill_source",
                "payoff_usdc",
                "premium_retained_usdc",
                "realized_pnl_usdc",
            }
        ),
    ),
    ("metrics",): (
        frozenset(
            {
                "cagr",
                "cvar_95",
                "cvar_99",
                "forced_close_count",
                "margin_breach_count",
                "max_drawdown",
                "premium_captured_ratio",
                "total_return_proxy",
                "touch_rate",
                "worst_month",
                "worst_week",
            }
        ),
    ),
    **{
        ("metrics", metric): (frozenset({"status", "value"}),)
        for metric in (
            "cagr",
            "forced_close_count",
            "margin_breach_count",
            "touch_rate",
            "worst_month",
            "worst_week",
        )
    },
    **{
        ("metrics", metric): (frozenset({"basis", "status", "value"}),)
        for metric in (
            "cvar_95",
            "cvar_99",
            "max_drawdown",
            "premium_captured_ratio",
            "total_return_proxy",
        )
    },
    ("summary",): (
        frozenset(
            {
                "realized_pnl_usdc",
                "total_fees_usdc",
                "touch_event_count",
                "trade_count",
                "unavailable_metrics",
            }
        ),
    ),
    ("summary", "unavailable_metrics", "[]"): (
        frozenset({"metric", "reason", "status"}),
    ),
    ("window_summary",): (
        frozenset({"starting_nav_usdc", "touch_event_count", "trade_count"}),
    ),
    ("execution_audit",): (
        frozenset(
            {
                "entry_fill_sources",
                "exit_fill_sources",
                "optimistic_fill_sources_present",
                "passed",
            }
        ),
    ),
    ("aggregate_metrics",): (
        frozenset({"cagr_pct", "margin_breach_count", "total_return_proxy_pct"}),
    ),
    **{
        ("aggregate_metrics", metric): (frozenset({"status", "value"}),)
        for metric in ("cagr_pct", "margin_breach_count", "total_return_proxy_pct")
    },
}
_LEGACY_DEFAULT_POINTER_KEYS = frozenset({"schema_version", "report_id"})
_CURRENT_DEFAULT_POINTER_KEYS = frozenset(
    {"schema_version", "report_id", "job_id", "completed_at"}
)
_FAILED_JOB_REASON_CODES = frozenset(
    {
        "BACKTEST_JOB_SUBMISSION_FAILED",
        "BACKTEST_JOB_TIMEOUT",
        "HISTORICAL_FIXTURE_CHANGED",
        "HISTORICAL_FIXTURE_REJECTED",
        "BACKTEST_JOB_FAILED",
        "JOB_INTERRUPTED",
    }
)
_STARTED_FAILED_JOB_REASON_CODES = frozenset(
    {
        "BACKTEST_JOB_TIMEOUT",
        "HISTORICAL_FIXTURE_CHANGED",
        "HISTORICAL_FIXTURE_REJECTED",
        "BACKTEST_JOB_FAILED",
    }
)
BACKTEST_JOB_SCHEMA_VERSION = "backtest_job_status.v1"
BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION = "backtest_default_pointer.v2"
LEGACY_BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION = "backtest_default_pointer.v1"
DEFAULT_BACKTEST_JOB_TIMEOUT_SECONDS = 60.0


class BacktestIdempotencyConflict(ValueError):
    """An idempotency key was reused for a different request or fixture."""


class BacktestQueueFull(RuntimeError):
    """The bounded backtest worker pool has no remaining admission slot."""


class BacktestJobSubmissionFailed(RuntimeError):
    """A validated job could not be handed to the bounded executor."""

    def __init__(self, message: str, *, job: dict[str, Any]) -> None:
        super().__init__(message)
        self.job = job


class BacktestJobStoreCorrupt(OSError):
    """A persisted job or idempotency record cannot be trusted or decoded."""


class BacktestArtifactCorrupt(OSError):
    """A persisted content-addressed artifact failed integrity validation."""


class BacktestJobService:
    """Bounded asynchronous jobs with persistent status and immutable results."""

    def __init__(
        self,
        *,
        fixture_path: str | Path,
        artifact_dir: str | Path,
        max_workers: int = 1,
        queue_capacity: int = 8,
        job_timeout_seconds: float = DEFAULT_BACKTEST_JOB_TIMEOUT_SECONDS,
        use_subprocess: bool = True,
    ) -> None:
        if max_workers < 1 or queue_capacity < 0:
            raise ValueError("backtest worker and queue bounds must be non-negative")
        if not 1.0 <= float(job_timeout_seconds) <= 600.0:
            raise ValueError("backtest job timeout must be between 1 and 600 seconds")
        self.fixture_path = _existing_file(fixture_path)
        self.artifact_dir = _artifact_directory(artifact_dir, create=True)
        self.jobs_dir = self.artifact_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_workers + queue_capacity)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="backtest-job",
        )
        self._futures: dict[str, Future[None]] = {}
        self._idempotency_records: dict[str, dict[str, str]] = {}
        self._closed = False
        self.job_timeout_seconds = float(job_timeout_seconds)
        self.use_subprocess = bool(use_subprocess)
        self._recover_interrupted_jobs()
        self._recover_idempotency_records()
        self._recover_default_promotions()

    def submit(
        self,
        *,
        idempotency_key: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        request_sha256 = hashlib.sha256(_canonical_json(request)).hexdigest()
        key_sha256 = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
        fixture_sha256 = self._fixture_sha256()
        mapping_path = self.jobs_dir / f"idempotency-{key_sha256}.json"

        with self._lock:
            if self._closed:
                raise RuntimeError("backtest job service is closed")
            recovered = self._idempotency_records.get(key_sha256)
            if recovered is not None and not mapping_path.exists():
                self._validate_idempotency_mapping(mapping_path, recovered)
                atomic_write_json(mapping_path, recovered)
            if mapping_path.exists():
                mapping, mapped_job = self._read_idempotency_mapping(mapping_path)
                if recovered is not None and recovered != mapping:
                    raise BacktestJobStoreCorrupt(
                        "in-memory idempotency record disagrees with the job store"
                    )
                if (
                    mapping["request_sha256"] != request_sha256
                    or mapping["fixture_sha256"] != fixture_sha256
                ):
                    raise BacktestIdempotencyConflict(
                        "idempotency key was already used for another request"
                    )
                if (
                    mapped_job.get("status") == "failed"
                    and mapped_job.get("reason_code")
                    == "BACKTEST_JOB_SUBMISSION_FAILED"
                ) or (
                    mapped_job.get("status") == "queued"
                    and mapped_job.get("started_at") is None
                    and str(mapped_job.get("job_id") or "") not in self._futures
                ):
                    # Admission never completed, so the exact same request may be
                    # retried. Keep the mapping as a request-hash tombstone so a
                    # different body cannot reuse this key after a transient
                    # executor failure.
                    pass
                else:
                    return self._public_job(mapped_job, replayed=True)

            if not self._slots.acquire(blocking=False):
                raise BacktestQueueFull("backtest queue is full")

            job_id = _current_job_id(
                idempotency_key_sha256=key_sha256,
                request_sha256=request_sha256,
                fixture_sha256=fixture_sha256,
            )
            submitted_at = _utc_timestamp()
            job = {
                "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "status": "queued",
                "submitted_at": submitted_at,
                "started_at": None,
                "completed_at": None,
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
                "idempotency_key_sha256": key_sha256,
                "status_url": f"/backtest/jobs/{job_id}",
                "result_url": f"/backtest/jobs/{job_id}/result",
                "report_id": None,
                "report_url": None,
                "default_promotion_status": "not_started",
                "reason_code": None,
                "research_only": True,
            }
            try:
                atomic_write_json(self._job_path(job_id), job)
                mapping = self._remember_idempotency_record(job)
                if mapping is None:
                    raise BacktestJobStoreCorrupt(
                        "new job omitted its idempotency record"
                    )
                atomic_write_json(mapping_path, mapping)
                future = self._executor.submit(
                    self._execute,
                    job_id=job_id,
                    request=request,
                    expected_fixture_sha256=fixture_sha256,
                )
                self._futures[job_id] = future
                future.add_done_callback(
                    lambda completed, selected=job_id: self._forget_future(
                        selected, completed
                    )
                )
            except BaseException as exc:
                job.update(
                    status="failed",
                    completed_at=_utc_timestamp(),
                    reason_code="BACKTEST_JOB_SUBMISSION_FAILED",
                )
                try:
                    atomic_write_json(self._job_path(job_id), job)
                finally:
                    self._slots.release()
                raise BacktestJobSubmissionFailed(
                    "backtest executor rejected the job",
                    job=self._public_job(job, replayed=False),
                ) from exc
            return self._public_job(job, replayed=False)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public_job(self._read_job(job_id), replayed=False)

    def result(self, job_id: str) -> tuple[str, dict[str, Any]]:
        with self._lock:
            job = self._read_job(job_id)
            status = str(job.get("status") or "")
            if status != "succeeded":
                return status, self._public_job(job, replayed=False)
        return status, _load_succeeded_job_artifact(self.artifact_dir, job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._read_job(job_id)
            if job.get("status") in {"succeeded", "failed", "cancelled"}:
                return self._public_job(job, replayed=False)
            future = self._futures.get(job_id)
            if future is None or not future.cancel():
                raise RuntimeError("backtest job is already running")
            job.update(
                status="cancelled",
                completed_at=_utc_timestamp(),
                reason_code="BACKTEST_JOB_CANCELLED",
            )
            atomic_write_json(self._job_path(job_id), job)
            self._futures.pop(job_id, None)
            self._slots.release()
            return self._public_job(job, replayed=False)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # Bounded jobs are allowed to finish so accepted work is not silently lost
        # during a graceful HTTP shutdown. A process crash is recovered on startup.
        self._executor.shutdown(wait=True, cancel_futures=False)

    def readiness_status(self) -> dict[str, bool]:
        """Probe persistent inputs and one queue slot without consuming it."""

        store_ready = False
        queue_ready = False
        with self._lock:
            if self._closed:
                return {"store_ready": False, "queue_ready": False}
            try:
                fixture_payload = json.loads(
                    _read_bounded_fixture(_existing_file(self.fixture_path)).decode(
                        "utf-8"
                    )
                )
                _validate_backtest_workload(fixture_payload)
                if not self.artifact_dir.is_dir() or not self.jobs_dir.is_dir():
                    raise FileNotFoundError("backtest store directories are unavailable")
                record_count = 0
                for path in self.jobs_dir.glob("*.json"):
                    record_count += 1
                    if record_count > 10_000:
                        raise ValueError(
                            "backtest job store contains too many records"
                        )
                    record = _read_job_store_object(path)
                    if path.name.startswith("job-"):
                        expected_job_id = path.stem
                        record_kind = _validate_job_record(
                            record,
                            expected_job_id=expected_job_id,
                        )
                        if record.get("status") == "succeeded":
                            _load_succeeded_job_artifact(self.artifact_dir, record)
                        if record_kind == "current":
                            mapping_path = self.jobs_dir / (
                                "idempotency-"
                                f"{record['idempotency_key_sha256']}.json"
                            )
                            self._read_idempotency_mapping(mapping_path)
                    elif path.name.startswith("idempotency-"):
                        self._validate_idempotency_mapping(path, record)
                    else:
                        raise BacktestJobStoreCorrupt(
                            "unexpected backtest job store record"
                        )
                if (self.artifact_dir / "default.json").exists():
                    load_backtest_evidence(self.artifact_dir)
                store_ready = True
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                store_ready = False

            acquired = self._slots.acquire(blocking=False)
            if acquired:
                self._slots.release()
                queue_ready = True
        return {"store_ready": store_ready, "queue_ready": queue_ready}

    def _execute(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
        expected_fixture_sha256: str,
    ) -> None:
        try:
            with self._lock:
                job = self._read_job(job_id)
                job.update(status="running", started_at=_utc_timestamp())
                atomic_write_json(self._job_path(job_id), job)
            if self.use_subprocess:
                artifact = _run_backtest_subprocess(
                    fixture_path=self.fixture_path,
                    artifact_dir=self.artifact_dir,
                    generated_at=request.get("generated_at"),
                    expected_fixture_sha256=expected_fixture_sha256,
                    timeout_seconds=self.job_timeout_seconds,
                )
            else:
                artifact = run_backtest_evidence_job(
                    fixture_path=self.fixture_path,
                    artifact_dir=self.artifact_dir,
                    generated_at=request.get("generated_at"),
                    expected_fixture_sha256=expected_fixture_sha256,
                    deadline_monotonic=time.monotonic() + self.job_timeout_seconds,
                    update_default_pointer=False,
                )
            self._finish_succeeded(job_id, artifact=artifact)
        except TimeoutError:
            self._finish_failed(job_id, reason_code="BACKTEST_JOB_TIMEOUT")
        except (FileNotFoundError, ValueError) as exc:
            reason_code = (
                "HISTORICAL_FIXTURE_CHANGED"
                if "changed after job admission" in str(exc)
                else "HISTORICAL_FIXTURE_REJECTED"
            )
            self._finish_failed(job_id, reason_code=reason_code)
        except BaseException:
            self._finish_failed(job_id, reason_code="BACKTEST_JOB_FAILED")
        else:
            self._try_promote_default(job_id, artifact=artifact)
        finally:
            with self._lock:
                self._futures.pop(job_id, None)
            self._slots.release()

    def _finish_failed(self, job_id: str, *, reason_code: str) -> None:
        with self._lock:
            job = self._read_job(job_id)
            job.update(
                status="failed",
                completed_at=_utc_timestamp(),
                report_id=None,
                report_url=None,
                default_promotion_status="not_started",
                reason_code=reason_code,
            )
            atomic_write_json(self._job_path(job_id), job)

    def _finish_succeeded(
        self,
        job_id: str,
        *,
        artifact: dict[str, Any],
    ) -> None:
        with self._lock:
            job = self._read_job(job_id)
            job.update(
                status="succeeded",
                completed_at=_utc_timestamp(),
                report_id=artifact["report_id"],
                report_url=f"/backtest/report/{artifact['report_id']}",
                default_promotion_status="pending",
                reason_code=None,
            )
            atomic_write_json(self._job_path(job_id), job)

    def _try_promote_default(
        self,
        job_id: str,
        *,
        artifact: dict[str, Any],
    ) -> None:
        # A succeeded job is terminal. Pointer promotion is recoverable metadata
        # and must never make an observable terminal state regress to failed.
        try:
            with self._lock:
                job = self._read_job(job_id)
                if job.get("report_id") != artifact.get("report_id"):
                    return
                self._reconcile_default_promotion(
                    allow_unknown_pointer_replacement=True
                )
        except BaseException:
            return

    def _mark_default_promoted(self, job_id: str) -> None:
        with self._lock:
            job = self._read_job(job_id)
            if (
                job.get("status") != "succeeded"
                or job.get("default_promotion_status") == "promoted"
            ):
                return
            job["default_promotion_status"] = "promoted"
            atomic_write_json(self._job_path(job_id), job)

    def _recover_interrupted_jobs(self) -> None:
        for path in self.jobs_dir.glob("job-*.json"):
            try:
                job = _read_json_object(path)
                _validate_job_record(job, expected_job_id=path.stem)
            except (OSError, ValueError):
                continue
            if job.get("status") not in {"queued", "running"}:
                continue
            job.update(
                status="failed",
                completed_at=_utc_timestamp(),
                report_id=None,
                report_url=None,
                reason_code="JOB_INTERRUPTED",
            )
            atomic_write_json(path, job)

    def _recover_idempotency_records(self) -> None:
        for path in self.jobs_dir.glob("job-*.json"):
            try:
                job = _read_job_store_object(path)
                mapping = self._remember_idempotency_record(job)
            except (OSError, ValueError):
                continue
            if mapping is None:
                # Pre-idempotency/synthetic promotion records remain valid for
                # pointer recovery but cannot serve as request-hash tombstones.
                continue
            mapping_path = self.jobs_dir / (
                f"idempotency-{job['idempotency_key_sha256']}.json"
            )
            if mapping_path.exists():
                persisted = _read_job_store_object(mapping_path)
                if persisted != mapping:
                    raise BacktestJobStoreCorrupt(
                        "idempotency mapping disagrees with persisted job"
                    )
            else:
                atomic_write_json(mapping_path, mapping)

    def _read_idempotency_mapping(
        self,
        path: Path,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        if not path.is_file():
            raise BacktestJobStoreCorrupt("backtest idempotency mapping is missing")
        mapping = _read_job_store_object(path)
        job = self._validate_idempotency_mapping(path, mapping)
        return mapping, job

    def _validate_idempotency_mapping(
        self,
        path: Path,
        mapping: dict[str, Any],
    ) -> dict[str, Any]:
        filename_match = _IDEMPOTENCY_FILENAME.fullmatch(path.name)
        job_id = mapping.get("job_id")
        if (
            filename_match is None
            or frozenset(mapping) != _IDEMPOTENCY_RECORD_KEYS
            or mapping.get("schema_version") != "backtest_idempotency_record.v1"
            or not isinstance(job_id, str)
            or not _JOB_ID.fullmatch(job_id)
            or not _is_sha256(mapping.get("request_sha256"))
            or not _is_sha256(mapping.get("fixture_sha256"))
        ):
            raise BacktestJobStoreCorrupt("invalid backtest idempotency record")
        try:
            job = self._read_job(job_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BacktestJobStoreCorrupt(
                "backtest idempotency mapping has no valid job"
            ) from exc
        key_sha256 = filename_match.group(1)
        if (
            job.get("idempotency_key_sha256") != key_sha256
            or job.get("request_sha256") != mapping["request_sha256"]
            or job.get("fixture_sha256") != mapping["fixture_sha256"]
        ):
            raise BacktestJobStoreCorrupt(
                "backtest idempotency mapping disagrees with its job"
            )
        return job

    def _remember_idempotency_record(
        self,
        job: dict[str, Any],
    ) -> dict[str, str] | None:
        if frozenset(job) == _LEGACY_PROMOTION_JOB_KEYS:
            # Legacy promotion-only records predate request hashes. Mapping
            # recovery skips that exact shape; strict reads/readiness still
            # validate its values before exposing or trusting the record.
            return None
        _validate_job_record(job)
        job_id = str(job.get("job_id") or "")
        key_sha256 = str(job.get("idempotency_key_sha256") or "")
        request_sha256 = str(job.get("request_sha256") or "")
        fixture_sha256 = str(job.get("fixture_sha256") or "")
        if (
            not _SHA256.fullmatch(key_sha256)
            or not _SHA256.fullmatch(request_sha256)
            or not _SHA256.fullmatch(fixture_sha256)
        ):
            raise BacktestJobStoreCorrupt(
                "job cannot provide a trustworthy idempotency record"
            )
        mapping = {
            "schema_version": "backtest_idempotency_record.v1",
            "job_id": job_id,
            "request_sha256": request_sha256,
            "fixture_sha256": fixture_sha256,
        }
        existing = self._idempotency_records.get(key_sha256)
        if existing is not None and existing != mapping:
            raise BacktestJobStoreCorrupt(
                "idempotency key maps to conflicting persisted jobs"
            )
        self._idempotency_records[key_sha256] = mapping
        return mapping

    def _recover_default_promotions(self) -> None:
        try:
            with self._lock:
                self._reconcile_default_promotion(
                    allow_unknown_pointer_replacement=False
                )
        except BaseException:
            return

    def _reconcile_default_promotion(
        self,
        *,
        allow_unknown_pointer_replacement: bool,
    ) -> None:
        """Advance the default pointer monotonically across jobs and restarts."""

        succeeded_jobs = self._ordered_succeeded_jobs()
        if not succeeded_jobs:
            return
        candidate_order, candidate = succeeded_jobs[-1]
        pointer_valid, pointer_report_id, pointer_order = _read_valid_default_pointer(
            self.artifact_dir
        )
        current_matches = [
            item
            for item in succeeded_jobs
            if item[1].get("report_id") == pointer_report_id
        ]
        current_order = pointer_order
        if current_order is None and current_matches:
            current_order = current_matches[-1][0]

        if pointer_valid and current_order == candidate_order:
            if pointer_report_id == candidate.get("report_id"):
                self._mark_default_promoted(str(candidate["job_id"]))
            return
        if pointer_valid and current_order is None:
            # A valid legacy/direct pointer has no comparable persisted order.
            # Startup recovery preserves it; a newly completed in-process job may
            # deliberately supersede it and upgrades the pointer to v2.
            if not allow_unknown_pointer_replacement:
                return
        elif pointer_valid and current_order is not None:
            if candidate_order <= current_order:
                return

        promote_backtest_evidence_default(
            self.artifact_dir,
            str(candidate["report_id"]),
            job_id=str(candidate["job_id"]),
            completed_at=str(candidate["completed_at"]),
        )
        self._mark_default_promoted(str(candidate["job_id"]))

    def _ordered_succeeded_jobs(
        self,
    ) -> list[tuple[tuple[datetime, str], dict[str, Any]]]:
        ordered: list[tuple[tuple[datetime, str], dict[str, Any]]] = []
        for path in self.jobs_dir.glob("job-*.json"):
            try:
                job = _read_json_object(path)
            except (OSError, ValueError):
                continue
            if path.name != f"{job.get('job_id')}.json":
                continue
            order = _succeeded_job_promotion_order(job)
            if order is not None:
                ordered.append((order, job))
        ordered.sort(key=lambda item: item[0])
        return ordered

    def _fixture_sha256(self) -> str:
        fixture = _existing_file(self.fixture_path)
        return hashlib.sha256(_read_bounded_fixture(fixture)).hexdigest()

    def _forget_future(self, job_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._futures.get(job_id) is future:
                self._futures.pop(job_id, None)

    def _job_path(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("invalid backtest job id")
        return self.jobs_dir / f"{job_id}.json"

    def _read_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.is_file():
            raise FileNotFoundError("backtest job not found")
        job = _read_job_store_object(path)
        _validate_job_record(job, expected_job_id=job_id)
        return job

    @staticmethod
    def _public_job(job: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
        return {
            key: value
            for key, value in {**job, "replayed": replayed}.items()
            if key in _PUBLIC_JOB_KEYS or key == "replayed"
        }


def run_backtest_evidence_job(
    *,
    fixture_path: str | Path,
    artifact_dir: str | Path,
    generated_at: str | None = None,
    expected_fixture_sha256: str | None = None,
    deadline_monotonic: float | None = None,
    update_default_pointer: bool = True,
) -> dict[str, Any]:
    """Run the bounded baseline replay and persist an immutable artifact."""

    _check_deadline(deadline_monotonic)
    fixture = _existing_file(fixture_path)
    fixture_bytes = _read_bounded_fixture(fixture)
    fixture_size = len(fixture_bytes)
    _check_deadline(deadline_monotonic)
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    if expected_fixture_sha256 and fixture_sha256 != expected_fixture_sha256:
        raise ValueError("historical fixture changed after job admission")
    # Parse before executing so malformed input is rejected without an artifact.
    try:
        fixture_payload = json.loads(fixture_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("historical fixture must be valid UTF-8 JSON") from exc
    _validate_backtest_workload(fixture_payload)
    _check_deadline(deadline_monotonic)

    backtest_report = build_fixed_baseline_backtest_report(
        fixture_payload,
        generated_at=generated_at,
        deadline_monotonic=deadline_monotonic,
    )
    _check_deadline(deadline_monotonic)
    reconciliation = backtest_report.get("historical_reconciliation") or {}
    aligned = (
        reconciliation.get("status") == "ELIGIBLE"
        and reconciliation.get("backtest_allowed") is True
    )
    core = {
        "schema_version": BACKTEST_ARTIFACT_SCHEMA_VERSION,
        "status": "completed",
        "aligned": aligned,
        "reason_code": None if aligned else "BACKTEST_ALIGNMENT_FAIL",
        "generated_at": backtest_report.get("generated_at"),
        "source_fixture": {
            "name": fixture.name,
            "sha256": fixture_sha256,
            "size_bytes": fixture_size,
        },
        "backtest_report": backtest_report,
        # A single baseline replay cannot truthfully manufacture the four-system
        # comparison required by calibration.
        "backtest_comparison": [],
        "research_only": True,
    }
    digest = hashlib.sha256(_canonical_json(core)).hexdigest()
    artifact = {**core, "report_id": f"bt-{digest}"}

    directory = _artifact_directory(artifact_dir, create=True)
    artifact_path = directory / f"{artifact['report_id']}.json"
    if artifact_path.exists():
        existing = _read_json_object(artifact_path)
        if existing != artifact:
            raise ValueError("content-addressed backtest artifact collision")
    else:
        atomic_write_json(artifact_path, artifact)
    if update_default_pointer:
        promote_backtest_evidence_default(directory, artifact["report_id"])
    return artifact


def promote_backtest_evidence_default(
    artifact_dir: str | Path,
    report_id: str,
    *,
    job_id: str | None = None,
    completed_at: str | None = None,
) -> None:
    """Promote a validated immutable result with explicit provenance semantics.

    Supplying ``job_id`` and ``completed_at`` writes the current v2 pointer,
    which is bound to a succeeded persisted job. Omitting both writes the
    strict v1 direct-artifact compatibility pointer used by
    :func:`run_backtest_evidence_job`; that form proves only a validated
    immutable artifact and must not be described as job-backed evidence.
    """

    directory = _artifact_directory(artifact_dir, create=False)
    load_backtest_evidence(directory, report_id)
    if (job_id is None) != (completed_at is None):
        raise ValueError("default pointer job metadata must be complete")
    pointer: dict[str, Any] = {
        "schema_version": LEGACY_BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
        "report_id": report_id,
    }
    if job_id is not None and completed_at is not None:
        order = _promotion_order(job_id=job_id, completed_at=completed_at)
        if order is None:
            raise ValueError("invalid default pointer job metadata")
        pointer = {
            "schema_version": BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
            "report_id": report_id,
            "job_id": job_id,
            "completed_at": completed_at,
        }
        _validate_default_pointer_record(directory, pointer)
    atomic_write_json(
        directory / "default.json",
        pointer,
    )


def load_backtest_evidence(
    artifact_dir: str | Path,
    report_id: str = "default",
) -> dict[str, Any]:
    """Load an immutable artifact without permitting path traversal."""

    directory = _artifact_directory(artifact_dir, create=False)
    selected = report_id
    selected_from_default = selected == "default"
    if selected == "default":
        pointer = _read_default_pointer(directory)
        selected = str(pointer["report_id"])
    if not _REPORT_ID.fullmatch(selected):
        if report_id == "default":
            raise BacktestArtifactCorrupt("invalid default backtest report id")
        raise ValueError("invalid backtest report id")
    try:
        artifact = _read_json_object(directory / f"{selected}.json")
    except FileNotFoundError as exc:
        if selected_from_default:
            raise BacktestArtifactCorrupt(
                "backtest default pointer target is missing"
            ) from exc
        raise
    except ValueError as exc:
        raise BacktestArtifactCorrupt("corrupt backtest evidence artifact") from exc
    if artifact.get("schema_version") != BACKTEST_ARTIFACT_SCHEMA_VERSION:
        raise BacktestArtifactCorrupt("unsupported backtest evidence artifact")
    if artifact.get("report_id") != selected:
        raise BacktestArtifactCorrupt(
            "backtest artifact id does not match lookup id"
        )
    _validate_backtest_artifact(artifact)
    core = {key: value for key, value in artifact.items() if key != "report_id"}
    try:
        expected = "bt-" + hashlib.sha256(_canonical_json(core)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise BacktestArtifactCorrupt(
            "backtest artifact is not canonical JSON"
        ) from exc
    if expected != selected:
        raise BacktestArtifactCorrupt("backtest artifact content hash mismatch")
    return artifact


def empty_backtest_lookup() -> dict[str, Any]:
    return {
        "schema_version": BACKTEST_LOOKUP_SCHEMA_VERSION,
        "status": "not_run",
        "reason_code": "BACKTEST_NOT_RUN",
        "report_id": None,
        "backtest_comparison": [],
        "research_only": True,
    }


def _load_succeeded_job_artifact(
    artifact_dir: str | Path,
    job: dict[str, Any],
) -> dict[str, Any]:
    report_id = str(job.get("report_id") or "")
    try:
        artifact = load_backtest_evidence(artifact_dir, report_id)
    except (FileNotFoundError, ValueError) as exc:
        raise BacktestArtifactCorrupt(
            "succeeded backtest job has no valid immutable artifact"
        ) from exc
    if (
        frozenset(job) == _CURRENT_JOB_KEYS
        and artifact["source_fixture"]["sha256"] != job.get("fixture_sha256")
    ):
        raise BacktestArtifactCorrupt(
            "succeeded backtest job fixture hash disagrees with its artifact"
        )
    return artifact


def _validate_backtest_artifact(artifact: dict[str, Any]) -> None:
    if frozenset(artifact) != _BACKTEST_ARTIFACT_KEYS:
        raise BacktestArtifactCorrupt("invalid backtest evidence artifact schema")
    aligned = artifact.get("aligned")
    generated_at = artifact.get("generated_at")
    source_fixture = artifact.get("source_fixture")
    report = artifact.get("backtest_report")
    if (
        artifact.get("schema_version") != BACKTEST_ARTIFACT_SCHEMA_VERSION
        or artifact.get("status") != "completed"
        or not isinstance(aligned, bool)
        or not _is_aware_timestamp(generated_at)
        or not isinstance(source_fixture, dict)
        or not isinstance(report, dict)
        or artifact.get("backtest_comparison") != []
        or artifact.get("research_only") is not True
    ):
        raise BacktestArtifactCorrupt("invalid backtest evidence artifact")

    fixture_name = source_fixture.get("name")
    fixture_size = source_fixture.get("size_bytes")
    if (
        frozenset(source_fixture) != {"name", "sha256", "size_bytes"}
        or not isinstance(fixture_name, str)
        or not fixture_name
        or "/" in fixture_name
        or "\\" in fixture_name
        or not _is_sha256(source_fixture.get("sha256"))
        or not isinstance(fixture_size, int)
        or isinstance(fixture_size, bool)
        or not 0 < fixture_size <= MAX_HISTORICAL_FIXTURE_BYTES
    ):
        raise BacktestArtifactCorrupt("invalid backtest source fixture metadata")

    if (
        frozenset(report) != _BASELINE_BACKTEST_REPORT_KEYS
        or report.get("schema_version") != BASELINE_BACKTEST_SCHEMA_VERSION
        or report.get("generated_at") != generated_at
        or any(
            not isinstance(report.get(field), dict)
            for field in _BASELINE_BACKTEST_DICT_FIELDS
        )
        or any(
            not isinstance(report.get(field), list)
            for field in _BASELINE_BACKTEST_LIST_FIELDS
        )
        or report["baseline_policy"].get("research_only") is not True
    ):
        raise BacktestArtifactCorrupt("invalid baseline backtest report schema")
    _validate_baseline_report_object_shapes(report)

    reconciliation = report["historical_reconciliation"]
    if (
        frozenset(reconciliation)
        != {
            "status",
            "backtest_allowed",
            "eligible_quotes",
            "quarantined_quotes",
            "failure_counts",
        }
        or reconciliation.get("status") not in {"ELIGIBLE", "PARTIAL", "INELIGIBLE"}
        or not isinstance(reconciliation.get("backtest_allowed"), bool)
        or not _is_nonnegative_int(reconciliation.get("eligible_quotes"))
        or not _is_nonnegative_int(reconciliation.get("quarantined_quotes"))
        or not isinstance(reconciliation.get("failure_counts"), dict)
        or any(
            code not in FAILURE_CODES or not _is_nonnegative_int(count)
            for code, count in reconciliation.get("failure_counts", {}).items()
        )
    ):
        raise BacktestArtifactCorrupt("invalid backtest reconciliation summary")

    expected_aligned = (
        reconciliation["status"] == "ELIGIBLE"
        and reconciliation["backtest_allowed"] is True
    )
    expected_reason = None if expected_aligned else "BACKTEST_ALIGNMENT_FAIL"
    if aligned is not expected_aligned or artifact.get("reason_code") != expected_reason:
        raise BacktestArtifactCorrupt("backtest alignment fields are inconsistent")


def _validate_baseline_report_object_shapes(
    value: Any,
    *,
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, dict):
        if path[-2:] == ("historical_reconciliation", "failure_counts"):
            return
        keyset = frozenset(value)
        expected_keysets = _BASELINE_BACKTEST_OBJECT_PATH_KEYSETS.get(path)
        if (
            keyset not in _BASELINE_BACKTEST_OBJECT_KEYSETS
            or expected_keysets is None
            or keyset not in expected_keysets
        ):
            raise BacktestArtifactCorrupt(
                "baseline backtest report contains an invalid object schema at "
                + ("/".join(path) or "<root>")
            )
        for key, nested in value.items():
            _validate_baseline_report_object_shapes(
                nested,
                path=(*path, key),
            )
    elif isinstance(value, list):
        for nested in value:
            _validate_baseline_report_object_shapes(nested, path=(*path, "[]"))


def _canonical_json(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _utc_timestamp() -> str:
    # Job lifecycle timestamps participate in stored job receipts and retain
    # microseconds intentionally. Do not replace this with the shared
    # second-precision artifact clock without a receipt/hash migration review.
    return (
        datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _validate_job_record(
    record: dict[str, Any],
    *,
    expected_job_id: str | None = None,
) -> str:
    """Validate one persisted job record without coercing untrusted values."""

    job_id = record.get("job_id")
    if (
        record.get("schema_version") != BACKTEST_JOB_SCHEMA_VERSION
        or not isinstance(job_id, str)
        or not _JOB_ID.fullmatch(job_id)
        or (expected_job_id is not None and job_id != expected_job_id)
    ):
        raise BacktestJobStoreCorrupt("invalid backtest job record")

    keys = frozenset(record)
    if keys == _LEGACY_PROMOTION_JOB_KEYS:
        if (
            record.get("status") != "succeeded"
            or not _is_aware_timestamp(record.get("completed_at"))
            or not _is_report_id(record.get("report_id"))
            or record.get("default_promotion_status") not in {"pending", "promoted"}
        ):
            raise BacktestJobStoreCorrupt("invalid legacy backtest job record")
        return "legacy_promotion"

    if keys != _CURRENT_JOB_KEYS:
        raise BacktestJobStoreCorrupt("invalid backtest job record schema")
    if (
        not _is_aware_timestamp(record.get("submitted_at"))
        or not _is_optional_aware_timestamp(record.get("started_at"))
        or not _is_optional_aware_timestamp(record.get("completed_at"))
        or not _is_sha256(record.get("request_sha256"))
        or not _is_sha256(record.get("fixture_sha256"))
        or not _is_sha256(record.get("idempotency_key_sha256"))
        or record.get("status_url") != f"/backtest/jobs/{job_id}"
        or record.get("result_url") != f"/backtest/jobs/{job_id}/result"
        or record.get("research_only") is not True
    ):
        raise BacktestJobStoreCorrupt("invalid backtest job record")
    if job_id != _current_job_id(
        idempotency_key_sha256=str(record["idempotency_key_sha256"]),
        request_sha256=str(record["request_sha256"]),
        fixture_sha256=str(record["fixture_sha256"]),
    ):
        raise BacktestJobStoreCorrupt("backtest job id does not match its hash tuple")

    status = record.get("status")
    started_at = record.get("started_at")
    completed_at = record.get("completed_at")
    report_id = record.get("report_id")
    report_url = record.get("report_url")
    promotion_status = record.get("default_promotion_status")
    reason_code = record.get("reason_code")
    if not _job_timeline_is_monotonic(
        submitted_at=str(record["submitted_at"]),
        started_at=started_at,
        completed_at=completed_at,
    ):
        raise BacktestJobStoreCorrupt("invalid backtest job lifecycle order")
    if status == "queued":
        valid_status = (
            started_at is None
            and completed_at is None
            and report_id is None
            and report_url is None
            and promotion_status == "not_started"
            and reason_code is None
        )
    elif status == "running":
        valid_status = (
            _is_aware_timestamp(started_at)
            and completed_at is None
            and report_id is None
            and report_url is None
            and promotion_status == "not_started"
            and reason_code is None
        )
    elif status == "succeeded":
        valid_status = (
            _is_aware_timestamp(started_at)
            and _is_aware_timestamp(completed_at)
            and _is_report_id(report_id)
            and report_url == f"/backtest/report/{report_id}"
            and promotion_status in {"pending", "promoted"}
            and reason_code is None
        )
    elif status == "failed":
        failure_start_is_coherent = (
            reason_code == "BACKTEST_JOB_SUBMISSION_FAILED" and started_at is None
        ) or reason_code == "JOB_INTERRUPTED" or (
            reason_code in _STARTED_FAILED_JOB_REASON_CODES
            and _is_aware_timestamp(started_at)
        )
        valid_status = (
            _is_aware_timestamp(completed_at)
            and report_id is None
            and report_url is None
            and promotion_status == "not_started"
            and reason_code in _FAILED_JOB_REASON_CODES
            and failure_start_is_coherent
        )
    elif status == "cancelled":
        valid_status = (
            started_at is None
            and
            _is_aware_timestamp(completed_at)
            and report_id is None
            and report_url is None
            and promotion_status == "not_started"
            and reason_code == "BACKTEST_JOB_CANCELLED"
        )
    else:
        valid_status = False
    if not valid_status:
        raise BacktestJobStoreCorrupt("invalid backtest job status record")
    return "current"


def _is_aware_timestamp(value: Any) -> bool:
    return _aware_datetime(value) is not None


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _job_timeline_is_monotonic(
    *,
    submitted_at: str,
    started_at: Any,
    completed_at: Any,
) -> bool:
    submitted = _aware_datetime(submitted_at)
    started = _aware_datetime(started_at) if started_at is not None else None
    completed = _aware_datetime(completed_at) if completed_at is not None else None
    if submitted is None:
        return False
    if started is not None and started < submitted:
        return False
    if completed is not None and completed < submitted:
        return False
    return not (started is not None and completed is not None and completed < started)


def _is_optional_aware_timestamp(value: Any) -> bool:
    return value is None or _is_aware_timestamp(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _current_job_id(
    *,
    idempotency_key_sha256: str,
    request_sha256: str,
    fixture_sha256: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{idempotency_key_sha256}:{request_sha256}:{fixture_sha256}"
        ).encode("ascii")
    ).hexdigest()
    return f"job-{digest}"


def _is_report_id(value: Any) -> bool:
    return isinstance(value, str) and _REPORT_ID.fullmatch(value) is not None


def _promotion_order(
    *,
    job_id: str,
    completed_at: str,
) -> tuple[datetime, str] | None:
    if not _JOB_ID.fullmatch(job_id):
        return None
    try:
        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC), job_id


def _succeeded_job_promotion_order(
    job: dict[str, Any],
) -> tuple[datetime, str] | None:
    try:
        _validate_job_record(job)
    except BacktestJobStoreCorrupt:
        return None
    if job.get("status") != "succeeded":
        return None
    return _promotion_order(
        job_id=str(job.get("job_id") or ""),
        completed_at=str(job.get("completed_at") or ""),
    )


def _read_valid_default_pointer(
    artifact_dir: str | Path,
) -> tuple[bool, str | None, tuple[datetime, str] | None]:
    directory = _artifact_directory(artifact_dir, create=False)
    try:
        pointer = _read_default_pointer(directory)
        schema_version = str(pointer["schema_version"])
        report_id = str(pointer["report_id"])
        load_backtest_evidence(directory, report_id)
    except (OSError, ValueError):
        return False, None, None
    order = None
    if schema_version == BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION:
        order = _promotion_order(
            job_id=str(pointer.get("job_id") or ""),
            completed_at=str(pointer.get("completed_at") or ""),
        )
        if order is None:
            return False, None, None
    return True, report_id, order


def _read_default_pointer(directory: Path) -> dict[str, Any]:
    try:
        pointer = _read_json_object(directory / "default.json")
    except ValueError as exc:
        raise BacktestArtifactCorrupt("corrupt backtest default pointer") from exc
    _validate_default_pointer_record(directory, pointer)
    return pointer


def _validate_default_pointer_record(
    directory: Path,
    pointer: dict[str, Any],
) -> None:
    schema_version = pointer.get("schema_version")
    report_id = pointer.get("report_id")
    if schema_version == LEGACY_BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION:
        if (
            frozenset(pointer) != _LEGACY_DEFAULT_POINTER_KEYS
            or not isinstance(report_id, str)
            or not _REPORT_ID.fullmatch(report_id)
        ):
            raise BacktestArtifactCorrupt("invalid legacy backtest default pointer")
        return
    if schema_version != BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION:
        raise BacktestArtifactCorrupt("unsupported backtest default pointer")

    job_id = pointer.get("job_id")
    completed_at = pointer.get("completed_at")
    if (
        frozenset(pointer) != _CURRENT_DEFAULT_POINTER_KEYS
        or not isinstance(report_id, str)
        or not _REPORT_ID.fullmatch(report_id)
        or not isinstance(job_id, str)
        or not _JOB_ID.fullmatch(job_id)
        or not _is_aware_timestamp(completed_at)
    ):
        raise BacktestArtifactCorrupt("invalid current backtest default pointer")
    try:
        job = _read_job_store_object(directory / "jobs" / f"{job_id}.json")
        _validate_job_record(job, expected_job_id=job_id)
    except (OSError, ValueError) as exc:
        raise BacktestArtifactCorrupt(
            "backtest default pointer has no valid succeeded job"
        ) from exc
    if (
        job.get("status") != "succeeded"
        or job.get("report_id") != report_id
        or job.get("completed_at") != completed_at
    ):
        raise BacktestArtifactCorrupt(
            "backtest default pointer disagrees with its succeeded job"
        )
    _load_succeeded_job_artifact(directory, job)


def _run_backtest_subprocess(
    *,
    fixture_path: str | Path,
    artifact_dir: str | Path,
    generated_at: str | None,
    expected_fixture_sha256: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "crypto_options_report.backtest_worker",
        "--fixture",
        str(Path(fixture_path).resolve()),
        "--artifact-dir",
        str(Path(artifact_dir).resolve()),
        "--expected-fixture-sha256",
        expected_fixture_sha256,
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if generated_at is not None:
        command.extend(["--generated-at", str(generated_at)])
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            env=_backtest_subprocess_environment(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("backtest subprocess deadline exceeded") from exc
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("backtest subprocess returned an invalid response") from exc
    if completed.returncode == 3:
        raise TimeoutError("backtest subprocess deadline exceeded")
    if completed.returncode == 2:
        if response.get("reason_code") == "HISTORICAL_FIXTURE_CHANGED":
            raise ValueError("historical fixture changed after job admission")
        raise ValueError("historical fixture rejected by isolated worker")
    if completed.returncode != 0:
        raise RuntimeError("backtest subprocess failed")
    report_id = str(response.get("report_id") or "")
    return load_backtest_evidence(artifact_dir, report_id)


def _backtest_subprocess_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _check_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
        raise TimeoutError("backtest job deadline exceeded")


def _validate_backtest_workload(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("historical fixture must be a JSON object")
    rows = value.get("rows")
    windows = value.get("windows")
    if isinstance(rows, list):
        if len(rows) > MAX_BACKTEST_ROWS:
            raise ValueError(f"historical fixture exceeds {MAX_BACKTEST_ROWS} rows")
        return
    if isinstance(windows, list):
        if len(windows) > MAX_BACKTEST_WINDOWS:
            raise ValueError(
                f"historical fixture exceeds {MAX_BACKTEST_WINDOWS} windows"
            )
        path_steps = sum(
            len(window.get("path") or [])
            for window in windows
            if isinstance(window, dict)
        )
        if path_steps > MAX_BACKTEST_PATH_STEPS:
            raise ValueError(
                f"historical fixture exceeds {MAX_BACKTEST_PATH_STEPS} path steps"
            )
        return
    raise ValueError("unsupported backtest fixture: expected rows or windows")


def _existing_file(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError("historical fixture not found")
    return candidate


def _read_bounded_fixture(path: Path) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(MAX_HISTORICAL_FIXTURE_BYTES + 1)
    if len(payload) > MAX_HISTORICAL_FIXTURE_BYTES:
        raise ValueError(
            f"historical fixture exceeds {MAX_HISTORICAL_FIXTURE_BYTES} bytes"
        )
    return payload


def _artifact_directory(path: str | Path, *, create: bool) -> Path:
    directory = Path(path).expanduser().resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise FileNotFoundError("backtest artifact directory not found")
    return directory


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = read_json_object_from_regular_file(
            path,
            max_bytes=(
                MAX_BACKTEST_JOB_RECORD_BYTES
                if path.parent.name == "jobs"
                else MAX_BACKTEST_ARTIFACT_BYTES
            ),
            description=f"JSON evidence artifact {path.name}",
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON evidence artifact: {path.name}") from exc
    return value


def _read_job_store_object(path: Path) -> dict[str, Any]:
    try:
        return _read_json_object(path)
    except ValueError as exc:
        raise BacktestJobStoreCorrupt("corrupt backtest job store record") from exc
