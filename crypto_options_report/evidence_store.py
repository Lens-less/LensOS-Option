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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backtest import build_fixed_baseline_backtest_report
from .storage import atomic_write_json

BACKTEST_ARTIFACT_SCHEMA_VERSION = "backtest_evidence_artifact.v1"
BACKTEST_LOOKUP_SCHEMA_VERSION = "backtest_report_lookup.v1"
MAX_HISTORICAL_FIXTURE_BYTES = 32 * 1024 * 1024
MAX_BACKTEST_ROWS = 50_000
MAX_BACKTEST_WINDOWS = 5_000
MAX_BACKTEST_PATH_STEPS = 100_000
_REPORT_ID = re.compile(r"^bt-[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^job-[0-9a-f]{64}$")
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
        self._closed = False
        self.job_timeout_seconds = float(job_timeout_seconds)
        self.use_subprocess = bool(use_subprocess)
        self._recover_interrupted_jobs()
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
            if mapping_path.exists():
                mapping = _read_json_object(mapping_path)
                if (
                    mapping.get("request_sha256") != request_sha256
                    or mapping.get("fixture_sha256") != fixture_sha256
                ):
                    raise BacktestIdempotencyConflict(
                        "idempotency key was already used for another request"
                    )
                return self._public_job(
                    self._read_job(str(mapping.get("job_id") or "")),
                    replayed=True,
                )

            if not self._slots.acquire(blocking=False):
                raise BacktestQueueFull("backtest queue is full")

            job_digest = hashlib.sha256(
                f"{key_sha256}:{request_sha256}:{fixture_sha256}".encode("ascii")
            ).hexdigest()
            job_id = f"job-{job_digest}"
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
                atomic_write_json(
                    mapping_path,
                    {
                        "schema_version": "backtest_idempotency_record.v1",
                        "job_id": job_id,
                        "request_sha256": request_sha256,
                        "fixture_sha256": fixture_sha256,
                    },
                )
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
                atomic_write_json(self._job_path(job_id), job)
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
            report_id = str(job.get("report_id") or "")
        return status, load_backtest_evidence(self.artifact_dir, report_id)

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
        job = _read_json_object(path)
        if (
            job.get("schema_version") != BACKTEST_JOB_SCHEMA_VERSION
            or job.get("job_id") != job_id
        ):
            raise ValueError("invalid backtest job record")
        return job

    @staticmethod
    def _public_job(job: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
        private_fields = {"fixture_sha256", "idempotency_key_sha256"}
        return {
            key: value
            for key, value in {**job, "replayed": replayed}.items()
            if key not in private_fields
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
    """Promote a validated immutable result only after its job succeeds."""

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
    if selected == "default":
        pointer = _read_json_object(directory / "default.json")
        if pointer.get("schema_version") not in {
            LEGACY_BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
            BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported backtest default pointer")
        selected = str(pointer.get("report_id") or "")
    if not _REPORT_ID.fullmatch(selected):
        raise ValueError("invalid backtest report id")
    artifact = _read_json_object(directory / f"{selected}.json")
    if artifact.get("schema_version") != BACKTEST_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported backtest evidence artifact")
    if artifact.get("report_id") != selected:
        raise ValueError("backtest artifact id does not match lookup id")
    core = {key: value for key, value in artifact.items() if key != "report_id"}
    expected = "bt-" + hashlib.sha256(_canonical_json(core)).hexdigest()
    if expected != selected:
        raise ValueError("backtest artifact content hash mismatch")
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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


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
    return parsed.astimezone(timezone.utc), job_id


def _succeeded_job_promotion_order(
    job: dict[str, Any],
) -> tuple[datetime, str] | None:
    if (
        job.get("schema_version") != BACKTEST_JOB_SCHEMA_VERSION
        or job.get("status") != "succeeded"
        or not _REPORT_ID.fullmatch(str(job.get("report_id") or ""))
    ):
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
        pointer = _read_json_object(directory / "default.json")
        schema_version = pointer.get("schema_version")
        if schema_version not in {
            LEGACY_BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
            BACKTEST_DEFAULT_POINTER_SCHEMA_VERSION,
        }:
            return False, None, None
        report_id = str(pointer.get("report_id") or "")
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
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON evidence artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence artifact must be an object: {path.name}")
    return value
