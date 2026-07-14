"""Minimal stdlib HTTP API for the shared research report."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .account_risk import (
    AVAILABLE_ACCOUNT_SCENARIOS,
    build_account_status,
)
from .contract import generate_research_report
from .evidence_store import (
    BacktestIdempotencyConflict,
    BacktestJobSubmissionFailed,
    BacktestJobService,
    BacktestQueueFull,
    empty_backtest_lookup,
    load_backtest_evidence,
)
from .full_surface import build_recommendation_projection
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    HTTP_MAX_INSTRUMENT_LIMIT,
    default_http_fixture_roots,
    build_market_data_status,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
    validate_deribit_base_url,
    utc_timestamp as market_utc_timestamp,
)
from .sidecar_auth import (
    authenticate_sidecar_payload,
    authenticated_projection,
    is_authenticated_sidecar_payload,
)
from .storage import read_json_object_from_regular_file

REPORT_PATH = "/research/report"
REPORT_ALIASES = {REPORT_PATH, "/report"}
DASHBOARD_PAGE_PATH = "/dashboard.html"
DASHBOARD_PAGE_ALIASES = {"/", DASHBOARD_PAGE_PATH, "/dashboard/page"}
GET_SURFACE_PATHS = {
    "/market/chain",
    "/surface",
    "/regime",
    "/account/risk",
    "/portfolio/risk",
    "/candidates",
    "/recommendation",
    "/backtest/report/default",
    "/backtest/report/{id}",
    "/dashboard",
}
POST_SURFACE_PATHS = {"/backtest/run"}
LIVENESS_PATHS = {"/health", "/livez"}
READINESS_PATH = "/readyz"
ALLOWED_HOSTS_ENV = "CRYPTO_OPTIONS_API_ALLOWED_HOSTS"
TRUSTED_ORIGINS_ENV = "CRYPTO_OPTIONS_API_TRUSTED_ORIGINS"
DERIBIT_POSITION_KINDS = frozenset(
    {"future", "option", "spot", "future_combo", "option_combo"}
)
BACKTEST_REPORT_PREFIX = "/backtest/report/"
BACKTEST_JOB_PREFIX = "/backtest/jobs/"
BACKTEST_REQUEST_SCHEMA_VERSION = "backtest_run_request.v1"
MAX_BACKTEST_REQUEST_BYTES = 16 * 1024
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
SMOKE_SERVER_START_GRACE_SEC = 0.05
SMOKE_SERVER_READY_DEADLINE_SEC = 15.0
SMOKE_SERVER_REQUEST_TIMEOUT_SEC = 2.0
DEFAULT_MAX_WORKERS = 8
DEFAULT_REQUEST_TIMEOUT_SEC = 15.0
MAX_REQUEST_TIMEOUT_SEC = 120.0
PRODUCTION_ALLOWED_QUERY_KEYS = {"mode"}
OVERLOAD_DRAIN_TIMEOUT_SEC = 0.05
OVERLOAD_DRAIN_LIMIT_BYTES = 64 * 1024


class _RequestContractError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _validate_backtest_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _RequestContractError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "backtest request must be a JSON object",
        )
    allowed = {"schema_version", "generated_at"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _RequestContractError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"unknown backtest request fields: {', '.join(unknown)}",
        )
    if value.get("schema_version") != BACKTEST_REQUEST_SCHEMA_VERSION:
        raise _RequestContractError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"schema_version must be {BACKTEST_REQUEST_SCHEMA_VERSION}",
        )
    generated_at = value.get("generated_at")
    if generated_at is not None:
        if not isinstance(generated_at, str):
            raise _RequestContractError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "generated_at must be an RFC3339 string",
            )
        if not _RFC3339_TIMESTAMP.fullmatch(generated_at):
            raise _RequestContractError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "generated_at must be an RFC3339 string",
            )
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _RequestContractError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "generated_at must be an RFC3339 string",
            ) from exc
        if parsed.tzinfo is None:
            raise _RequestContractError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "generated_at must include a timezone",
            )
    return {key: value[key] for key in ("schema_version", "generated_at") if key in value}


def _validate_idempotency_key(value: str | None) -> str:
    if value is None or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise _RequestContractError(
            HTTPStatus.BAD_REQUEST,
            "Idempotency-Key must be 1-128 safe ASCII characters",
        )
    return value


def _parse_backtest_job_path(path: str) -> tuple[str, bool] | None:
    if not path.startswith(BACKTEST_JOB_PREFIX):
        return None
    remainder = path.removeprefix(BACKTEST_JOB_PREFIX)
    wants_result = remainder.endswith("/result")
    job_id = remainder.removesuffix("/result") if wants_result else remainder
    if "/" in job_id or not re.fullmatch(r"job-[0-9a-f]{64}", job_id):
        return None
    return job_id, wants_result


@dataclass(frozen=True)
class RuntimeConfig:
    """HTTP runtime policy, deliberately separate from the product mode."""

    profile: str = "development"
    max_workers: int = DEFAULT_MAX_WORKERS
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SEC
    snapshot_fixture: str | None = None
    account_snapshot_fixture: str | None = None
    allow_live_fetch: bool = False
    access_log: bool | None = None
    historical_fixture: str | None = None
    backtest_artifact_dir: str | None = None
    paper_ledger_path: str | None = None
    manual_approval_runbook_path: str | None = None

    @property
    def production(self) -> bool:
        return self.profile == "production"

    @property
    def access_logging(self) -> bool:
        return self.production if self.access_log is None else self.access_log

    def validate(self, *, check_inputs: bool = True) -> "RuntimeConfig":
        if self.profile not in {"development", "production"}:
            raise ValueError("runtime profile must be development or production")
        if isinstance(self.max_workers, bool) or not 1 <= self.max_workers <= 64:
            raise ValueError("max_workers must be between 1 and 64")
        if not 1.0 <= float(self.request_timeout) <= MAX_REQUEST_TIMEOUT_SEC:
            raise ValueError(
                f"request_timeout must be between 1 and {MAX_REQUEST_TIMEOUT_SEC:g} seconds"
            )
        if self.production and self.allow_live_fetch:
            raise ValueError(
                "production HTTP live fetch is unsupported; capture a snapshot with the CLI"
            )
        if check_inputs and self.snapshot_fixture:
            load_snapshot_fixture(self.snapshot_fixture)
        if check_inputs and self.account_snapshot_fixture:
            _load_account_snapshot(self.account_snapshot_fixture)
        if self.historical_fixture and not Path(self.historical_fixture).expanduser().is_file():
            raise ValueError("historical_fixture not found")
        if self.backtest_artifact_dir:
            artifact_path = Path(self.backtest_artifact_dir).expanduser()
            if artifact_path.exists() and not artifact_path.is_dir():
                raise ValueError("backtest_artifact_dir must be a directory")
        return self


class ResearchHTTPServer(ThreadingHTTPServer):
    """Bounded stdlib server for the research-only HTTP surface."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        runtime: RuntimeConfig | None = None,
    ) -> None:
        self.runtime = (runtime or RuntimeConfig()).validate()
        self._worker_slots = threading.BoundedSemaphore(self.runtime.max_workers)
        try:
            if ipaddress.ip_address(server_address[0]).version == 6:
                self.address_family = socket.AF_INET6
        except ValueError:
            pass
        super().__init__(server_address, handler_class)
        self.backtest_jobs = (
            BacktestJobService(
                fixture_path=self.runtime.historical_fixture,
                artifact_dir=self.runtime.backtest_artifact_dir,
            )
            if self.runtime.historical_fixture and self.runtime.backtest_artifact_dir
            else None
        )

    def server_close(self) -> None:
        try:
            if self.backtest_jobs is not None:
                self.backtest_jobs.close()
        finally:
            super().server_close()

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self._reject_overloaded(request, client_address)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        error = sys.exception()
        event = (
            "client_disconnected"
            if isinstance(
                error,
                (
                    BrokenPipeError,
                    ConnectionAbortedError,
                    ConnectionResetError,
                    TimeoutError,
                    socket.timeout,
                ),
            )
            else "server_error"
        )
        _log_json(
            event,
            client=client_address[0] if client_address else None,
            error=type(error).__name__ if error else "unknown",
        )

    @staticmethod
    def _reject_overloaded(request: socket.socket, client_address: Any) -> None:
        body = b'{"error":"overloaded"}'
        request_id = uuid.uuid4().hex
        _log_json(
            "overload_rejected",
            request_id=request_id,
            client=client_address[0] if client_address else None,
            status=int(HTTPStatus.SERVICE_UNAVAILABLE),
        )
        headers = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Server: CryptoOptionsResearch\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Cache-Control: no-store, max-age=0\r\n"
            b"X-Content-Type-Options: nosniff\r\n"
            b"X-Frame-Options: DENY\r\n"
            b"Referrer-Policy: no-referrer\r\n"
            b"Permissions-Policy: camera=(), microphone=(), geolocation=()\r\n"
            b"Cross-Origin-Resource-Policy: same-origin\r\n"
            b"Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'\r\n"
            + f"X-Request-ID: {request_id}\r\n".encode("ascii")
            + b"Retry-After: 1\r\n"
            b"Connection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        try:
            request.sendall(headers)
            # A Windows socket closed with unread request bytes may send a TCP RST
            # and discard this small 503 response. Half-close the response first,
            # then drain only a bounded amount of already-arriving request data.
            request.shutdown(socket.SHUT_WR)
            request.settimeout(OVERLOAD_DRAIN_TIMEOUT_SEC)
            remaining = OVERLOAD_DRAIN_LIMIT_BYTES
            while remaining > 0:
                chunk = request.recv(min(4096, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            return


def build_api_report(
    *,
    mode: str = "research_only",
    snapshot_fixture: str | None = None,
    live_deribit: bool = False,
    currency: str = "BTC",
    deribit_base_url: str = DEFAULT_DERIBIT_BASE_URL,
    instrument_limit: int | None = None,
    account_scenario: str | None = None,
    account_snapshot_fixture: str | None = None,
    generated_at: str | None = None,
    sandbox_fixtures: bool = False,
    backtest_artifact_dir: str | None = None,
    paper_ledger_path: str | None = None,
    manual_approval_runbook_path: str | None = None,
) -> dict[str, Any]:
    if snapshot_fixture and live_deribit:
        raise ValueError("choose snapshot_fixture or live_deribit, not both")

    market_snapshot = None
    if snapshot_fixture:
        allowed_roots = default_http_fixture_roots() if sandbox_fixtures else None
        try:
            market_snapshot = load_snapshot_fixture(
                snapshot_fixture,
                allowed_roots=allowed_roots,
            )
        except FileNotFoundError as exc:
            raise ValueError("snapshot_fixture not found") from exc
        except OSError as exc:
            raise ValueError("snapshot_fixture could not be read") from exc
    elif live_deribit:
        safe_base = validate_deribit_base_url(deribit_base_url)
        market_snapshot = fetch_deribit_option_chain_snapshot(
            currency=currency,
            base_url=safe_base,
            instrument_limit=instrument_limit,
            include_feed_graph=True,
        )
    backtest_artifact = None
    if backtest_artifact_dir:
        try:
            backtest_artifact = load_backtest_evidence(backtest_artifact_dir)
        except FileNotFoundError:
            backtest_artifact = None
    account_payload = (
        _load_account_snapshot(account_snapshot_fixture)
        if account_snapshot_fixture
        else None
    )
    if account_payload is not None and account_scenario is not None:
        raise ValueError("operator account snapshot cannot be combined with account_scenario")
    return generate_research_report(
        mode=mode,
        market_snapshot=market_snapshot,
        account_scenario=account_scenario,
        account_payload=account_payload,
        generated_at=generated_at,
        backtest_artifact=backtest_artifact,
        paper_ledger_path=paper_ledger_path,
        manual_approval_runbook_path=manual_approval_runbook_path,
        persist_paper_ledger=False,
    )


class ResearchReportHandler(BaseHTTPRequestHandler):
    server_version = "CryptoOptionsResearch"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self._runtime().request_timeout)

    def version_string(self) -> str:
        return self.server_version

    def do_GET(self) -> None:
        if not self._start_request():
            return
        parsed = urlparse(self.path)
        if parsed.path in DASHBOARD_PAGE_ALIASES:
            self._write_html(HTTPStatus.OK, dashboard_page_html())
            return
        if parsed.path in LIVENESS_PATHS:
            payload = {"status": "ok"} if parsed.path == "/health" else {"status": "alive"}
            self._write_json(HTTPStatus.OK, payload)
            return
        if parsed.path == READINESS_PATH:
            payload = readiness_payload(
                self._runtime(),
                job_service=getattr(self.server, "backtest_jobs", None),
            )
            status = HTTPStatus.OK if payload["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._write_json(status, payload)
            return
        job_route = _parse_backtest_job_path(parsed.path)
        if job_route is not None:
            if parsed.query:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "job lookup rejects query parameters"})
                return
            service = getattr(self.server, "backtest_jobs", None)
            if service is None:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "backtest_job_not_found"})
                return
            job_id, wants_result = job_route
            try:
                if wants_result:
                    job_status, payload = service.result(job_id)
                    status = (
                        HTTPStatus.OK
                        if job_status == "succeeded"
                        else HTTPStatus.ACCEPTED
                        if job_status in {"queued", "running"}
                        else HTTPStatus.CONFLICT
                    )
                else:
                    payload = service.get(job_id)
                    status = HTTPStatus.OK
            except (FileNotFoundError, ValueError):
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "backtest_job_not_found"})
                return
            except OSError as exc:
                self._write_job_store_unavailable(exc)
                return
            self._write_json(status, payload)
            return
        backtest_lookup = _is_backtest_report_path(parsed.path)
        if (
            parsed.path not in REPORT_ALIASES
            and parsed.path not in GET_SURFACE_PATHS
            and not backtest_lookup
        ):
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            payload = _payload_for_path(
                parsed.path,
                parsed.query,
                runtime=self._runtime(),
            )
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except FileNotFoundError:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "backtest_report_not_found"})
            return
        except OSError as exc:
            self._write_job_store_unavailable(exc)
            return
        except Exception as exc:  # noqa: BLE001 - map unexpected failures to JSON 500
            _log_json(
                "request_error",
                request_id=self._request_id,
                method="GET",
                path=parsed.path,
                error_type=type(exc).__name__,
            )
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal"})
            return
        self._write_json(HTTPStatus.OK, payload)

    def do_POST(self) -> None:
        if not self._start_request():
            return
        parsed = urlparse(self.path)
        if parsed.path not in POST_SURFACE_PATHS:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if parsed.query:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "backtest run accepts JSON body fields, not query parameters"},
            )
            return
        try:
            request = self._read_backtest_request()
            idempotency_key = _validate_idempotency_key(
                self.headers.get("Idempotency-Key")
            )
        except _RequestContractError as exc:
            self._write_json(exc.status, {"error": str(exc)})
            return
        runtime = self._runtime()
        if not runtime.historical_fixture or not runtime.backtest_artifact_dir:
            self._write_json(
                HTTPStatus.CONFLICT,
                {
                    "schema_version": "backtest_run_response.v1",
                    "status": "historical_data_not_configured",
                    "reason_code": "MISSING_HISTORICAL_FIXTURE",
                    "action": "CONFIGURE_HISTORICAL_FIXTURE",
                    "report_id": None,
                    "backtest_comparison": [],
                    "research_only": True,
                },
            )
            return
        service = getattr(self.server, "backtest_jobs", None)
        if service is None:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "backtest_job_service_unavailable"})
            return
        try:
            job = service.submit(
                idempotency_key=idempotency_key,
                request=request,
            )
        except BacktestIdempotencyConflict:
            self._write_json(
                HTTPStatus.CONFLICT,
                {
                    "schema_version": "backtest_run_response.v1",
                    "status": "idempotency_conflict",
                    "reason_code": "IDEMPOTENCY_KEY_REUSE_CONFLICT",
                    "research_only": True,
                },
            )
            return
        except BacktestQueueFull:
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "schema_version": "backtest_run_response.v1",
                    "status": "queue_full",
                    "reason_code": "BACKTEST_QUEUE_FULL",
                    "research_only": True,
                },
                extra_headers={"Retry-After": "1"},
            )
            return
        except BacktestJobSubmissionFailed as exc:
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                exc.job,
                extra_headers={"Retry-After": "1"},
            )
            return
        except (FileNotFoundError, ValueError) as exc:
            _log_json(
                "backtest_job_rejected",
                request_id=self._request_id,
                error_type=type(exc).__name__,
            )
            self._write_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "schema_version": "backtest_run_response.v1",
                    "status": "invalid_historical_fixture",
                    "reason_code": "HISTORICAL_FIXTURE_REJECTED",
                    "action": "VALIDATE_HISTORICAL_FIXTURE",
                    "report_id": None,
                    "backtest_comparison": [],
                    "research_only": True,
                },
            )
            return
        except OSError as exc:
            self._write_job_store_unavailable(exc)
            return
        if (
            job.get("status") == "failed"
            and job.get("reason_code") == "BACKTEST_JOB_SUBMISSION_FAILED"
        ):
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                job,
                extra_headers={"Retry-After": "1"},
            )
            return
        self._write_json(
            HTTPStatus.ACCEPTED,
            job,
            extra_headers={"Location": str(job["status_url"])},
        )

    def do_HEAD(self) -> None:
        self._method_not_allowed(write_body=False)

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        if not self._start_request():
            return
        parsed = urlparse(self.path)
        route = _parse_backtest_job_path(parsed.path)
        if route is None or route[1] or parsed.query:
            self._method_not_allowed()
            return
        service = getattr(self.server, "backtest_jobs", None)
        if service is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "backtest_job_not_found"})
            return
        try:
            payload = service.cancel(route[0])
        except FileNotFoundError:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "backtest_job_not_found"})
            return
        except OSError as exc:
            self._write_job_store_unavailable(exc)
            return
        except (RuntimeError, ValueError) as exc:
            self._write_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        self._write_json(HTTPStatus.OK, payload)

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        try:
            body = json.dumps(
                payload,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            _log_json(
                "response_serialization_failed",
                request_id=self._request_id,
                error_type=type(exc).__name__,
            )
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = json.dumps(
                {
                    "error": "response_serialization_failed",
                    "reason_code": "NON_JSON_RESPONSE_PAYLOAD",
                    "research_only": True,
                },
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        self._write_response(
            status,
            body,
            content_type="application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _write_job_store_unavailable(self, exc: OSError) -> None:
        _log_json(
            "backtest_job_store_unavailable",
            request_id=self._request_id,
            error_type=type(exc).__name__,
        )
        self._write_json(
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "error": "backtest_job_store_unavailable",
                "reason_code": "BACKTEST_JOB_STORE_UNAVAILABLE",
                "research_only": True,
            },
            extra_headers={"Retry-After": "1"},
        )

    def _write_html(self, status: HTTPStatus, body: str) -> None:
        encoded = body.encode("utf-8")
        self._write_response(
            status,
            encoded,
            content_type="text/html; charset=utf-8",
            content_security_policy=(
                "default-src 'self'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                "form-action 'none'"
            ),
        )

    def _write_response(
        self,
        status: HTTPStatus,
        body: bytes,
        *,
        content_type: str,
        content_security_policy: str | None = None,
        write_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._ensure_request_context()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Request-ID", self._request_id)
        if content_security_policy:
            self.send_header("Content-Security-Policy", content_security_policy)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            if write_body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            _log_json(
                "client_disconnected",
                request_id=self._request_id,
                method=self.command,
                path=urlparse(self.path).path,
            )
        finally:
            self.close_connection = True
            self._log_access(status)

    def _read_backtest_request(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise _RequestContractError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Content-Type must be application/json",
            )
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "")
        except ValueError as exc:
            raise _RequestContractError(
                HTTPStatus.BAD_REQUEST,
                "Content-Length must be a positive integer",
            ) from exc
        if content_length < 1:
            raise _RequestContractError(
                HTTPStatus.BAD_REQUEST,
                "JSON request body is required",
            )
        if content_length > MAX_BACKTEST_REQUEST_BYTES:
            raise _RequestContractError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"JSON request body exceeds {MAX_BACKTEST_REQUEST_BYTES} bytes",
            )
        raw = self.rfile.read(content_length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _RequestContractError(
                HTTPStatus.BAD_REQUEST,
                "request body must be valid UTF-8 JSON",
            ) from exc
        return _validate_backtest_request(value)

    def _method_not_allowed(self, *, write_body: bool = True) -> None:
        if not self._start_request():
            return
        body = json.dumps({"error": "method_not_allowed"}, sort_keys=True).encode("utf-8")
        self._write_response(
            HTTPStatus.METHOD_NOT_ALLOWED,
            body,
            content_type="application/json; charset=utf-8",
            write_body=write_body,
        )

    def _runtime(self) -> RuntimeConfig:
        return getattr(self.server, "runtime", RuntimeConfig())

    def _start_request(self) -> bool:
        self._request_id = uuid.uuid4().hex
        self._request_started_at = time.monotonic()
        host_header = self.headers.get("Host")
        if not _request_host_allowed(host_header):
            self._write_json(
                HTTPStatus.MISDIRECTED_REQUEST,
                {"error": "untrusted_host"},
            )
            return False
        origin = self.headers.get("Origin")
        if (
            self.command in {"POST", "DELETE"}
            and origin
            and not _origin_matches_host(origin, host_header)
        ):
            self._write_json(
                HTTPStatus.FORBIDDEN,
                {"error": "cross_origin_request_rejected"},
            )
            return False
        return True

    def _ensure_request_context(self) -> None:
        if not hasattr(self, "_request_id"):
            self._start_request()

    def _log_access(self, status: HTTPStatus) -> None:
        if not self._runtime().access_logging:
            return
        _log_json(
            "access",
            request_id=self._request_id,
            method=self.command,
            path=urlparse(self.path).path,
            status=int(status),
            duration_ms=round((time.monotonic() - self._request_started_at) * 1000, 3),
            client=self.client_address[0] if self.client_address else None,
        )


def serve(
    host: str,
    port: int,
    *,
    runtime: RuntimeConfig | None = None,
) -> None:
    runtime = (runtime or RuntimeConfig()).validate()
    if runtime.production and port == 0:
        raise SystemExit("production requires an explicit non-zero port")
    bind_host, loopback_bind = _bind_target(host)
    if not loopback_bind and not _remote_bind_allowed():
        raise SystemExit(
            "refusing non-loopback bind without CRYPTO_OPTIONS_API_ALLOW_REMOTE=1 "
            f"(got host={host!r})"
        )
    if not loopback_bind:
        print(
            "warning: binding research API on non-loopback interface; "
            "fixture sandbox and live-fetch controls still apply",
            file=sys.stderr,
        )
    if runtime.production and not readiness_payload(runtime)["service_ready"]:
        raise SystemExit(
            "production runtime preflight failed: dashboard/report is not ready"
        )
    server = ResearchHTTPServer(
        (bind_host, port),
        ResearchReportHandler,
        runtime=runtime,
    )
    try:
        _log_json(
            "startup",
            profile=runtime.profile,
            host=bind_host,
            port=server.server_port,
            max_workers=runtime.max_workers,
            request_timeout=runtime.request_timeout,
            research_only=True,
            product_release="NO-GO",
        )
        server.serve_forever()
    finally:
        server.server_close()


def dashboard_page_html() -> str:
    return (
        files("crypto_options_report")
        .joinpath("static", "dashboard.html")
        .read_text(encoding="utf-8")
    )


def readiness_payload(
    runtime: RuntimeConfig,
    *,
    job_service: BacktestJobService | Any | None = None,
) -> dict[str, Any]:
    service_ready = False
    market_provider_ready = False
    last_trusted_snapshot_ready = False
    market_data_ready = False
    account_data_ready = False
    store_ready = False
    queue_ready = False
    model_ready = False
    reason_codes: list[str] = []
    try:
        runtime.validate(check_inputs=False)
        dashboard_page_html()
        service_ready = True
    except Exception as exc:
        _log_json("readiness_check_failed", error=type(exc).__name__)
        reason_codes.append("SERVICE_VALIDATION_FAILED")

    generated_at = market_utc_timestamp()
    if runtime.snapshot_fixture:
        try:
            snapshot = load_snapshot_fixture(runtime.snapshot_fixture)
            market_status = build_market_data_status(snapshot)
            trust_evidence = market_status.get("trust_evidence") or {}
            market_provider_ready = market_status.get("status") == "validated"
            last_trusted_snapshot_ready = (
                market_provider_ready
                and trust_evidence.get("status") == "promoted"
            )
            market_data_ready = (
                market_provider_ready and last_trusted_snapshot_ready
            )
        except Exception as exc:
            _log_json("market_readiness_check_failed", error=type(exc).__name__)
            reason_codes.append("MARKET_DATA_CHECK_FAILED")

    if runtime.account_snapshot_fixture:
        try:
            account_payload = _load_account_snapshot(
                runtime.account_snapshot_fixture
            )
            account_status = build_account_status(
                generated_at=generated_at,
                account_payload=account_payload,
            )
            account_data_ready = _account_dependency_ready(
                account_payload,
                account_status,
            )
        except Exception as exc:
            _log_json("account_readiness_check_failed", error=type(exc).__name__)
            reason_codes.append("ACCOUNT_DATA_CHECK_FAILED")
    job_readiness = _job_service_readiness(job_service)
    store_ready = _store_dependency_ready(
        runtime,
        job_service=job_service,
        job_readiness=job_readiness,
    )
    queue_ready = _queue_dependency_ready(
        job_service,
        job_readiness=job_readiness,
    )
    model_ready = _model_dependency_ready(runtime)

    if not market_provider_ready:
        reason_codes.append("MARKET_PROVIDER_NOT_READY")
    if market_provider_ready and not last_trusted_snapshot_ready:
        reason_codes.append("TRUSTED_MARKET_SNAPSHOT_NOT_READY")
    if not market_data_ready:
        reason_codes.append("MARKET_DATA_NOT_READY")
    if not account_data_ready:
        reason_codes.append("ACCOUNT_DATA_NOT_READY")
    if not store_ready:
        reason_codes.append("BACKTEST_STORE_NOT_READY")
    if not queue_ready:
        reason_codes.append("BACKTEST_QUEUE_NOT_READY")
    if not model_ready:
        reason_codes.append("MODEL_NOT_READY")
    dependencies_ready = all(
        (
            market_data_ready,
            account_data_ready,
            store_ready,
            queue_ready,
            model_ready,
        )
    )
    ready = service_ready and (dependencies_ready if runtime.production else True)
    return {
        "ready": ready,
        "service_ready": service_ready,
        "dependencies_ready": dependencies_ready,
        "market_provider_ready": market_provider_ready,
        "last_trusted_snapshot_ready": last_trusted_snapshot_ready,
        "market_data_ready": market_data_ready,
        "account_data_ready": account_data_ready,
        "store_ready": store_ready,
        "queue_ready": queue_ready,
        "model_ready": model_ready,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "research_only": True,
        "product_release": "NO-GO",
        "live_order_adapter_available": False,
        "runtime_profile": runtime.profile,
    }


def _account_dependency_ready(
    account_payload: dict[str, Any],
    account_status: dict[str, Any],
) -> bool:
    account = account_payload.get("account") or {}
    replay = account_payload.get("replay_metadata") or {}
    private_contract = account_status.get("private_adapter_contract") or {}
    data_age_ms = account_status.get("data_age_ms")
    freshness_limit_ms = account_status.get("freshness_limit_ms")
    source_endpoints = set(account_payload.get("source_endpoints") or [])
    return (
        is_authenticated_sidecar_payload(account_payload)
        and _account_snapshot_shape_ready(account_payload)
        and account_payload.get("schema_version") == "deribit_account_snapshot.v1"
        and account_status.get("status") == "available"
        and account.get("source") == "deribit_live_private_read_only"
        and replay.get("source") == "live_deribit_private_read_only"
        and replay.get("captured_shape_only") is False
        and {
            "private/get_account_summary",
            "private/get_positions",
            "private/get_open_orders_by_currency",
        }.issubset(source_endpoints)
        and private_contract.get("schema_version")
        == "private_account_adapter_contract.v1"
        and private_contract.get("source") == "deribit_live_private_read_only"
        and private_contract.get("auth_safe") is True
        and private_contract.get("replay_fixture") is False
        and private_contract.get("live_order_submission_possible") is False
        and isinstance(data_age_ms, (int, float))
        and not isinstance(data_age_ms, bool)
        and isinstance(freshness_limit_ms, (int, float))
        and not isinstance(freshness_limit_ms, bool)
        and 0 <= data_age_ms <= freshness_limit_ms
    )


def _account_snapshot_shape_ready(payload: dict[str, Any]) -> bool:
    account = payload.get("account")
    positions = payload.get("positions")
    open_orders = payload.get("open_orders")
    if (
        not isinstance(account, dict)
        or not isinstance(positions, list)
        or not isinstance(open_orders, list)
    ):
        return False
    if not isinstance(account.get("currency"), str) or not account["currency"].strip():
        return False
    if any(
        not _finite_economic_number(account.get(field))
        for field in (
            "equity",
            "balance",
            "margin_balance",
            "available_funds",
            "initial_margin",
            "maintenance_margin",
        )
    ):
        return False
    if (
        float(account["equity"]) <= 0.0
        or float(account["balance"]) <= 0.0
        or float(account["margin_balance"]) <= 0.0
        or any(
            float(account[field]) < 0.0
            for field in ("available_funds", "initial_margin", "maintenance_margin")
        )
    ):
        return False
    for position in positions:
        if not isinstance(position, dict):
            return False
        if any(
            not isinstance(position.get(field), str)
            or not str(position[field]).strip()
            or str(position[field]).strip().lower() == "unknown"
            for field in ("instrument_name", "kind", "direction")
        ):
            return False
        if str(position["kind"]).strip().lower() not in DERIBIT_POSITION_KINDS:
            return False
        if str(position["direction"]).strip().lower() not in {"buy", "sell"}:
            return False
        if any(
            not _finite_economic_number(position.get(field))
            for field in (
                "size",
                "mark_price",
                "index_price",
                "floating_pnl",
                "initial_margin",
                "maintenance_margin",
                "delta",
            )
        ):
            return False
        if (
            float(position["size"]) <= 0.0
            or float(position["mark_price"]) <= 0.0
            or float(position["index_price"]) <= 0.0
            or float(position["initial_margin"]) < 0.0
            or float(position["maintenance_margin"]) < 0.0
            or not -1.0 <= float(position["delta"]) <= 1.0
        ):
            return False
    for order in open_orders:
        if not isinstance(order, dict):
            return False
        if any(
            not isinstance(order.get(field), str)
            or not str(order[field]).strip()
            or str(order[field]).strip().lower() == "unknown"
            for field in (
                "instrument_name",
                "direction",
                "order_state",
                "order_type",
            )
        ):
            return False
        if str(order["direction"]).strip().lower() not in {"buy", "sell"}:
            return False
        if any(
            not _finite_economic_number(order.get(field))
            for field in ("amount", "filled_amount", "price")
        ) or any(
            not isinstance(order.get(field), int)
            or isinstance(order.get(field), bool)
            for field in ("creation_timestamp", "last_update_timestamp")
        ):
            return False
        if (
            float(order["amount"]) <= 0.0
            or not 0.0
            <= float(order["filled_amount"])
            <= float(order["amount"])
            or float(order["price"]) < 0.0
            or int(order["creation_timestamp"]) < 0
            or int(order["last_update_timestamp"]) < 0
        ):
            return False
    return True


def _finite_economic_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _store_dependency_ready(
    runtime: RuntimeConfig,
    *,
    job_service: BacktestJobService | Any | None,
    job_readiness: dict[str, bool] | None = None,
) -> bool:
    if not runtime.historical_fixture or not runtime.backtest_artifact_dir:
        return False
    try:
        historical = Path(runtime.historical_fixture).expanduser().resolve()
        artifacts = Path(runtime.backtest_artifact_dir).expanduser().resolve()
        return (
            historical.is_file()
            and artifacts.is_dir()
            and (
                job_readiness is None
                or job_readiness.get("store_ready") is True
            )
            and (
                job_service is None
                or Path(job_service.jobs_dir).is_dir()
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _queue_dependency_ready(
    job_service: BacktestJobService | Any | None,
    *,
    job_readiness: dict[str, bool] | None = None,
) -> bool:
    try:
        return (
            job_service is not None
            and getattr(job_service, "_closed", True) is False
            and Path(job_service.jobs_dir).is_dir()
            and (
                job_readiness is None
                or job_readiness.get("queue_ready") is True
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _job_service_readiness(
    job_service: BacktestJobService | Any | None,
) -> dict[str, bool] | None:
    if job_service is None or not callable(
        getattr(job_service, "readiness_status", None)
    ):
        return None
    try:
        result = job_service.readiness_status()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {"store_ready": False, "queue_ready": False}
    if not isinstance(result, dict):
        return {"store_ready": False, "queue_ready": False}
    return {
        "store_ready": result.get("store_ready") is True,
        "queue_ready": result.get("queue_ready") is True,
    }


def _model_dependency_ready(runtime: RuntimeConfig) -> bool:
    # The Fable review removed fabricated calibration/model evidence. Until a
    # content-addressed promoted model artifact exists, production readiness is
    # deliberately false rather than inferred from fixture constants.
    return False


def _payload_for_path(
    path: str,
    query: str,
    *,
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    if path in LIVENESS_PATHS:
        return {"status": "ok"}
    if _is_backtest_report_path(path):
        _report_options_from_query(query, runtime=runtime)
        configured_dir = (runtime or RuntimeConfig()).backtest_artifact_dir
        report_id = path.removeprefix(BACKTEST_REPORT_PREFIX)
        if not configured_dir:
            if report_id == "default":
                return empty_backtest_lookup()
            raise FileNotFoundError("backtest report store is not configured")
        try:
            return load_backtest_evidence(configured_dir, report_id)
        except FileNotFoundError:
            if report_id == "default":
                return empty_backtest_lookup()
            raise
    report = _report_from_query(query, runtime=runtime)
    if path in REPORT_ALIASES:
        return report
    if path == "/market/chain":
        return report["data_status"]
    if path == "/surface":
        return report["vol_surface_status"]
    if path == "/regime":
        return report["permission_state"]
    if path == "/account/risk":
        return report["account_status"]
    if path == "/portfolio/risk":
        return report["portfolio_risk"]
    if path == "/candidates":
        return report["ev_candidate_scanner"]
    if path == "/recommendation":
        return build_recommendation_projection(report)
    if path == "/dashboard":
        return report["full_system_surface"]["dashboard"]
    raise ValueError(f"unsupported path: {path}")


def _report_from_query(
    query: str,
    *,
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    return build_api_report(**_report_options_from_query(query, runtime=runtime))


def _report_options_from_query(
    query: str,
    *,
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    runtime = (runtime or RuntimeConfig()).validate(check_inputs=False)
    params = parse_qs(query)
    if runtime.production:
        rejected = sorted(set(params) - PRODUCTION_ALLOWED_QUERY_KEYS)
        mode = params.get("mode", ["research_only"])[0]
        if rejected or mode != "research_only":
            details = ", ".join(rejected or ["mode"])
            raise ValueError(
                f"production profile rejects browser-controlled parameters: {details}"
            )
        return {
            "mode": "research_only",
            "snapshot_fixture": runtime.snapshot_fixture,
            "account_snapshot_fixture": runtime.account_snapshot_fixture,
            "backtest_artifact_dir": runtime.backtest_artifact_dir,
            "paper_ledger_path": runtime.paper_ledger_path,
            "manual_approval_runbook_path": runtime.manual_approval_runbook_path,
        }

    # HTTP always stays research_only for display/action consistency.
    mode = "research_only"
    snapshot_fixture = params.get("snapshot_fixture", [None])[0]
    live_deribit = params.get("live_deribit", ["0"])[0].lower() in {
        "1",
        "true",
        "yes",
    }
    currency = params.get("currency", ["BTC"])[0]
    # Client-supplied deribit_base_url is ignored on HTTP to prevent SSRF.
    deribit_base_url = DEFAULT_DERIBIT_BASE_URL
    if params.get("deribit_base_url"):
        raise ValueError("deribit_base_url query override is not allowed over HTTP")
    account_scenario = params.get("account_scenario", [None])[0]
    generated_at = params.get("generated_at", [None])[0]
    instrument_limit = _parse_optional_int(
        params.get("instrument_limit", [None])[0],
        name="instrument_limit",
    )
    if instrument_limit is not None and instrument_limit < 1:
        raise ValueError("instrument_limit must be >= 1 over HTTP")
    if instrument_limit is not None and instrument_limit > HTTP_MAX_INSTRUMENT_LIMIT:
        raise ValueError(
            f"instrument_limit must be <= {HTTP_MAX_INSTRUMENT_LIMIT} over HTTP"
        )
    if live_deribit and not runtime.allow_live_fetch:
        raise ValueError(
            "live_deribit HTTP fetch is disabled; capture a snapshot with the CLI"
        )
    return {
        "mode": mode,
        "snapshot_fixture": snapshot_fixture,
        "live_deribit": live_deribit,
        "currency": currency,
        "deribit_base_url": deribit_base_url,
        "instrument_limit": instrument_limit,
        "account_scenario": account_scenario,
        "account_snapshot_fixture": runtime.account_snapshot_fixture,
        "generated_at": generated_at,
        "sandbox_fixtures": True,
        "backtest_artifact_dir": runtime.backtest_artifact_dir,
        "paper_ledger_path": runtime.paper_ledger_path,
        "manual_approval_runbook_path": runtime.manual_approval_runbook_path,
    }


def smoke_once(
    *,
    snapshot_fixture: str | None = None,
    live_deribit: bool = False,
    currency: str = "BTC",
    deribit_base_url: str = DEFAULT_DERIBIT_BASE_URL,
    instrument_limit: int | None = None,
    account_scenario: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    server = ResearchHTTPServer(
        ("127.0.0.1", 0),
        ResearchReportHandler,
        runtime=RuntimeConfig(
            profile="development",
            allow_live_fetch=live_deribit,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(SMOKE_SERVER_START_GRACE_SEC)
        query: dict[str, Any] = {"mode": "research_only"}
        if snapshot_fixture:
            query["snapshot_fixture"] = snapshot_fixture
        if account_scenario:
            query["account_scenario"] = account_scenario
        if generated_at:
            query["generated_at"] = generated_at
        if live_deribit:
            query["live_deribit"] = "1"
            query["currency"] = currency
            # Do not put deribit_base_url in the HTTP query: the handler rejects
            # client overrides (SSRF). Non-default bases use the direct API path.
            if instrument_limit is not None:
                query["instrument_limit"] = instrument_limit
        if live_deribit and deribit_base_url.rstrip("/") != DEFAULT_DERIBIT_BASE_URL.rstrip("/"):
            # Trusted local smoke path for allowlisted non-default hosts only.
            return build_api_report(
                mode="research_only",
                live_deribit=True,
                currency=currency,
                deribit_base_url=deribit_base_url,
                instrument_limit=instrument_limit,
                account_scenario=account_scenario,
                generated_at=generated_at,
            )
        url = (
            f"{REPORT_PATH}?{urlencode(query)}"
        )
        deadline = time.monotonic() + SMOKE_SERVER_READY_DEADLINE_SEC
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if (
                    _request_json(
                        server.server_port,
                        "/readyz",
                        timeout=SMOKE_SERVER_REQUEST_TIMEOUT_SEC,
                    )["service_ready"]
                    is not True
                ):
                    raise RuntimeError("local research-report server failed readiness check")
                return _request_json(
                    server.server_port,
                    url,
                    timeout=SMOKE_SERVER_REQUEST_TIMEOUT_SEC,
                )
            except (TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(0.05)
        if last_error is not None:
            raise last_error
        raise TimeoutError("smoke_once timed out before the local HTTP server responded")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-options-report-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--runtime-profile",
        choices=("development", "production"),
        default=os.environ.get("CRYPTO_OPTIONS_RUNTIME_PROFILE", "development"),
        help="HTTP runtime policy; product output remains research_only",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=_environment_number("CRYPTO_OPTIONS_API_MAX_WORKERS", DEFAULT_MAX_WORKERS, int),
        help="maximum concurrent HTTP requests",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=_environment_number(
            "CRYPTO_OPTIONS_API_REQUEST_TIMEOUT",
            DEFAULT_REQUEST_TIMEOUT_SEC,
            float,
        ),
        help="per-connection socket timeout in seconds",
    )
    parser.add_argument(
        "--snapshot-fixture",
        default=os.environ.get("CRYPTO_OPTIONS_API_SNAPSHOT_FIXTURE"),
        help="operator-controlled snapshot used by the production profile",
    )
    parser.add_argument(
        "--account-snapshot-fixture",
        default=os.environ.get("CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_FIXTURE"),
        help="operator-owned read-only account sidecar snapshot",
    )
    parser.add_argument(
        "--allow-live-fetch",
        action="store_true",
        default=_environment_flag("CRYPTO_OPTIONS_API_ALLOW_LIVE_FETCH"),
        help="development-only HTTP live fetch gate",
    )
    parser.add_argument(
        "--historical-fixture",
        default=os.environ.get("CRYPTO_OPTIONS_HISTORICAL_FIXTURE"),
        help="operator-controlled local historical fixture used by POST /backtest/run",
    )
    parser.add_argument(
        "--backtest-artifact-dir",
        default=os.environ.get("CRYPTO_OPTIONS_BACKTEST_ARTIFACT_DIR"),
        help="directory for immutable content-addressed backtest artifacts",
    )
    parser.add_argument(
        "--paper-ledger-path",
        default=os.environ.get("CRYPTO_OPTIONS_PAPER_LEDGER_PATH"),
        help="durable JSON path for the paper proposal ledger",
    )
    parser.add_argument(
        "--manual-approval-runbook",
        default=os.environ.get("CRYPTO_OPTIONS_MANUAL_APPROVAL_RUNBOOK"),
        help="versioned RESEARCH_ONLY manual approval runbook",
    )
    parser.add_argument(
        "--access-log",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="structured access logging (defaults on in production)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="start the HTTP endpoint, request one report, print JSON, and exit",
    )
    parser.add_argument(
        "--account-scenario",
        choices=AVAILABLE_ACCOUNT_SCENARIOS,
        help="optional replayable account scenario name for smoke runs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = RuntimeConfig(
        profile=args.runtime_profile,
        max_workers=args.max_workers,
        request_timeout=args.request_timeout,
        snapshot_fixture=args.snapshot_fixture,
        account_snapshot_fixture=args.account_snapshot_fixture,
        allow_live_fetch=args.allow_live_fetch,
        access_log=args.access_log,
        historical_fixture=args.historical_fixture,
        backtest_artifact_dir=args.backtest_artifact_dir,
        paper_ledger_path=args.paper_ledger_path,
        manual_approval_runbook_path=args.manual_approval_runbook,
    ).validate()
    if args.smoke:
        if runtime.production:
            raise SystemExit("--smoke cannot be combined with the production profile")
        json.dump(
            smoke_once(account_scenario=args.account_scenario),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    serve(args.host, args.port, runtime=runtime)
    return 0


def _parse_optional_int(value: str | None, *, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _is_backtest_report_path(path: str) -> bool:
    if not path.startswith(BACKTEST_REPORT_PREFIX):
        return False
    suffix = path.removeprefix(BACKTEST_REPORT_PREFIX)
    return bool(suffix) and "/" not in suffix


def _load_account_snapshot(path: str | Path) -> dict[str, Any]:
    candidate = Path(path).expanduser().resolve()
    try:
        value = read_json_object_from_regular_file(
            candidate,
            max_bytes=4 * 1024 * 1024,
            description="account_snapshot_fixture",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("account_snapshot_fixture must be valid JSON") from exc
    authenticated_value = authenticate_sidecar_payload(candidate, value)
    payload = authenticated_value.get(
        "account_snapshot",
        authenticated_value.get("payload", authenticated_value),
    )
    if not isinstance(payload, dict):
        raise ValueError("account_snapshot_fixture payload must be a JSON object")
    normalized = dict(payload)
    account = dict(normalized.get("account") or {})
    if str(account.get("status") or "").lower() == "not_configured":
        account["status"] = "missing"
        account["source"] = "not_configured"
        normalized["account"] = account
    if (
        not is_authenticated_sidecar_payload(authenticated_value)
        and str(account.get("status") or "").lower() != "missing"
    ):
        normalized = {
            "schema_version": "deribit_account_snapshot.v1",
            "captured_at": normalized.get("captured_at"),
            "source_endpoints": [],
            "account": {
                "status": "auth_failed",
                "configuration_status": "configured",
                "source": "unauthenticated_account_snapshot",
                "source_endpoint": "private/get_account_summary",
                "reason_code": "AUTH_FAILED_ACCOUNT_API",
                "currency": "UNKNOWN",
                "margin_model": "unknown",
            },
            "positions": [],
            "open_orders": [],
            "simulation": {
                "status": "auth_failed",
                "attempted": False,
                "reason_code": "AUTH_FAILED_SIMULATION_API",
                "source_endpoint": "private/simulate_portfolio",
            },
            "replay_metadata": {
                "source": "unauthenticated_account_snapshot",
                "captured_shape_only": True,
                "credentials_persisted": False,
                "raw_identifiers_persisted": False,
                "sidecar_authenticated": False,
            },
        }
    return authenticated_projection(
        normalized,
        authenticated_source=authenticated_value,
    )


def _remote_bind_allowed() -> bool:
    return _environment_flag("CRYPTO_OPTIONS_API_ALLOW_REMOTE")


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _environment_number(name: str, default: Any, converter: Any) -> Any:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return converter(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc


def _log_json(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)


def _is_loopback_host(host: str) -> bool:
    return _bind_target(host)[1]


def _bind_target(host: str) -> tuple[str, bool]:
    candidate = (host or "").strip().lower()
    if candidate == "localhost":
        # Never resolve an attacker-controlled hostname on the trust path. A
        # literal localhost request is pinned to IPv4 loopback before bind, so
        # DNS/hosts-file changes cannot race the authorization check.
        return "127.0.0.1", True
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate, False
    return str(address), address.is_loopback


def _request_host_allowed(value: str | None) -> bool:
    hostname = _header_hostname(value)
    if hostname is None:
        return False
    allowed = {"127.0.0.1", "::1", "localhost"}
    for configured in os.environ.get(ALLOWED_HOSTS_ENV, "").split(","):
        candidate = _header_hostname(configured.strip())
        if candidate is not None:
            allowed.add(candidate)
    return hostname in allowed


def _origin_matches_host(origin: str, host_header: str | None) -> bool:
    origin_authority = _origin_authority(origin)
    host_authority = _header_authority(host_header)
    if (
        origin_authority is None
        or host_authority is None
        or origin_authority[1:] != host_authority
    ):
        return False
    if origin_authority[0] == "http" and origin_authority[1] in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        return True
    return origin_authority in _trusted_origins()


def _origin_authority(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlparse(value)
        origin_port = parsed.port
    except ValueError:
        return None
    if (
        not parsed.scheme
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), origin_port


def _trusted_origins() -> frozenset[tuple[str, str, int | None]]:
    trusted: set[tuple[str, str, int | None]] = set()
    for configured in os.environ.get(TRUSTED_ORIGINS_ENV, "").split(","):
        candidate = _origin_authority(configured.strip())
        if candidate is not None and (
            candidate[0] == "https"
            or candidate[1] in {"127.0.0.1", "::1", "localhost"}
        ):
            trusted.add(candidate)
    return frozenset(trusted)


def _header_hostname(value: str | None) -> str | None:
    authority = _header_authority(value)
    return authority[0] if authority is not None else None


def _header_authority(value: str | None) -> tuple[str, int | None] | None:
    raw = str(value or "").strip()
    if not raw or any(character in raw for character in ",/@?#"):
        return None
    try:
        parsed = urlparse(f"//{raw}")
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.hostname.lower(), parsed.port


def _request_json(port: int, path: str, *, timeout: float) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        if response.status != HTTPStatus.OK:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        return json.loads(payload)
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
