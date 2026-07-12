"""Minimal stdlib HTTP API for the shared research report."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .account_risk import AVAILABLE_ACCOUNT_SCENARIOS
from .contract import generate_research_report
from .full_surface import build_recommendation_projection
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    HTTP_MAX_INSTRUMENT_LIMIT,
    default_http_fixture_roots,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
    validate_deribit_base_url,
)

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
    "/dashboard",
}
POST_SURFACE_PATHS = {"/backtest/run"}
LIVENESS_PATHS = {"/health", "/livez"}
READINESS_PATH = "/readyz"
SMOKE_SERVER_START_GRACE_SEC = 0.05
SMOKE_SERVER_READY_DEADLINE_SEC = 15.0
SMOKE_SERVER_REQUEST_TIMEOUT_SEC = 2.0
DEFAULT_MAX_WORKERS = 8
DEFAULT_REQUEST_TIMEOUT_SEC = 15.0
MAX_REQUEST_TIMEOUT_SEC = 120.0
PRODUCTION_ALLOWED_QUERY_KEYS = {"mode"}
OVERLOAD_DRAIN_TIMEOUT_SEC = 0.05
OVERLOAD_DRAIN_LIMIT_BYTES = 64 * 1024


@dataclass(frozen=True)
class RuntimeConfig:
    """HTTP runtime policy, deliberately separate from the product mode."""

    profile: str = "development"
    max_workers: int = DEFAULT_MAX_WORKERS
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SEC
    snapshot_fixture: str | None = None
    allow_live_fetch: bool = False
    access_log: bool | None = None

    @property
    def production(self) -> bool:
        return self.profile == "production"

    @property
    def access_logging(self) -> bool:
        return self.production if self.access_log is None else self.access_log

    def validate(self) -> "RuntimeConfig":
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
        if self.snapshot_fixture:
            load_snapshot_fixture(self.snapshot_fixture)
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
        super().__init__(server_address, handler_class)

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
    generated_at: str | None = None,
    sandbox_fixtures: bool = False,
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
        )
    return generate_research_report(
        mode=mode,
        market_snapshot=market_snapshot,
        account_scenario=account_scenario,
        generated_at=generated_at,
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
        self._start_request()
        parsed = urlparse(self.path)
        if parsed.path in DASHBOARD_PAGE_ALIASES:
            self._write_html(HTTPStatus.OK, dashboard_page_html())
            return
        if parsed.path in LIVENESS_PATHS:
            payload = {"status": "ok"} if parsed.path == "/health" else {"status": "alive"}
            self._write_json(HTTPStatus.OK, payload)
            return
        if parsed.path == READINESS_PATH:
            payload = readiness_payload(self._runtime())
            status = HTTPStatus.OK if payload["service_ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._write_json(status, payload)
            return
        if parsed.path not in REPORT_ALIASES and parsed.path not in GET_SURFACE_PATHS:
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
        self._start_request()
        parsed = urlparse(self.path)
        if parsed.path not in POST_SURFACE_PATHS:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            report = _report_from_query(parsed.query, runtime=self._runtime())
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - map unexpected failures to JSON 500
            _log_json(
                "request_error",
                request_id=self._request_id,
                method="POST",
                path=parsed.path,
                error_type=type(exc).__name__,
            )
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal"})
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "schema_version": "backtest_run_response.v1",
                "status": "completed",
                "report_id": "default",
                "backtest_comparison": report["walk_forward_calibration"][
                    "system_comparison"
                ],
                "research_only": True,
            },
        )

    def do_HEAD(self) -> None:
        self._method_not_allowed(write_body=False)

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._write_response(
            status,
            body,
            content_type="application/json; charset=utf-8",
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

    def _method_not_allowed(self, *, write_body: bool = True) -> None:
        self._start_request()
        body = json.dumps({"error": "method_not_allowed"}, sort_keys=True).encode("utf-8")
        self._write_response(
            HTTPStatus.METHOD_NOT_ALLOWED,
            body,
            content_type="application/json; charset=utf-8",
            write_body=write_body,
        )

    def _runtime(self) -> RuntimeConfig:
        return getattr(self.server, "runtime", RuntimeConfig())

    def _start_request(self) -> None:
        self._request_id = uuid.uuid4().hex
        self._request_started_at = time.monotonic()

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
    if not _is_loopback_host(host) and not _remote_bind_allowed():
        raise SystemExit(
            "refusing non-loopback bind without CRYPTO_OPTIONS_API_ALLOW_REMOTE=1 "
            f"(got host={host!r})"
        )
    if not _is_loopback_host(host):
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
        (host, port),
        ResearchReportHandler,
        runtime=runtime,
    )
    try:
        _log_json(
            "startup",
            profile=runtime.profile,
            host=host,
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


def readiness_payload(runtime: RuntimeConfig) -> dict[str, Any]:
    try:
        runtime.validate()
        dashboard_page_html()
        report = build_api_report(
            mode="research_only",
            snapshot_fixture=runtime.snapshot_fixture,
        )
        ready = (
            report.get("schema_version") == "research_report.v1"
            and report.get("effective_mode") == "research_only"
            and report.get("mode_gate", {}).get("order_instructions_allowed") is False
        )
    # Readiness is an availability boundary: unexpected validation failures must
    # become a structured 503 contract instead of dropping the HTTP connection.
    except Exception as exc:
        _log_json("readiness_check_failed", error=type(exc).__name__)
        ready = False
    return {
        "service_ready": ready,
        "research_only": True,
        "product_release": "NO-GO",
        "live_order_adapter_available": False,
        "runtime_profile": runtime.profile,
    }


def _payload_for_path(
    path: str,
    query: str,
    *,
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    if path in LIVENESS_PATHS:
        return {"status": "ok"}
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
    if path == "/backtest/report/default":
        return {
            "schema_version": "backtest_report_lookup.v1",
            "report_id": "default",
            "backtest_comparison": report["walk_forward_calibration"][
                "system_comparison"
            ],
        }
    if path == "/dashboard":
        return report["full_system_surface"]["dashboard"]
    raise ValueError(f"unsupported path: {path}")


def _report_from_query(
    query: str,
    *,
    runtime: RuntimeConfig | None = None,
) -> dict[str, Any]:
    runtime = (runtime or RuntimeConfig()).validate()
    params = parse_qs(query)
    if runtime.production:
        rejected = sorted(set(params) - PRODUCTION_ALLOWED_QUERY_KEYS)
        mode = params.get("mode", ["research_only"])[0]
        if rejected or mode != "research_only":
            details = ", ".join(rejected or ["mode"])
            raise ValueError(
                f"production profile rejects browser-controlled parameters: {details}"
            )
        return build_api_report(
            mode="research_only",
            snapshot_fixture=runtime.snapshot_fixture,
        )

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
    return build_api_report(
        mode=mode,
        snapshot_fixture=snapshot_fixture,
        live_deribit=live_deribit,
        currency=currency,
        deribit_base_url=deribit_base_url,
        instrument_limit=instrument_limit,
        account_scenario=account_scenario,
        generated_at=generated_at,
        sandbox_fixtures=True,
    )


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
        "--allow-live-fetch",
        action="store_true",
        default=_environment_flag("CRYPTO_OPTIONS_API_ALLOW_LIVE_FETCH"),
        help="development-only HTTP live fetch gate",
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
        allow_live_fetch=args.allow_live_fetch,
        access_log=args.access_log,
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
    candidate = (host or "").strip().lower()
    if candidate in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        infos = socket.getaddrinfo(candidate, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            if not ipaddress.ip_address(address).is_loopback:
                return False
        except ValueError:
            return False
    return bool(infos)


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
