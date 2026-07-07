"""Minimal stdlib HTTP API for the shared research report."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .account_risk import AVAILABLE_ACCOUNT_SCENARIOS
from .contract import generate_research_report
from .full_surface import build_recommendation_projection
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
)

REPORT_PATH = "/research/report"
REPORT_ALIASES = {REPORT_PATH, "/report"}
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
SMOKE_SERVER_START_GRACE_SEC = 0.05
SMOKE_SERVER_READY_DEADLINE_SEC = 15.0
SMOKE_SERVER_REQUEST_TIMEOUT_SEC = 2.0


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
) -> dict[str, Any]:
    if snapshot_fixture and live_deribit:
        raise ValueError("choose snapshot_fixture or live_deribit, not both")

    market_snapshot = None
    if snapshot_fixture:
        market_snapshot = load_snapshot_fixture(snapshot_fixture)
    elif live_deribit:
        market_snapshot = fetch_deribit_option_chain_snapshot(
            currency=currency,
            base_url=deribit_base_url,
            instrument_limit=instrument_limit,
        )
    return generate_research_report(
        mode=mode,
        market_snapshot=market_snapshot,
        account_scenario=account_scenario,
        generated_at=generated_at,
    )


class ResearchReportHandler(BaseHTTPRequestHandler):
    server_version = "CryptoOptionsReport/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path not in REPORT_ALIASES and parsed.path not in GET_SURFACE_PATHS:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            payload = _payload_for_path(parsed.path, parsed.query)
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._write_json(HTTPStatus.OK, payload)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in POST_SURFACE_PATHS:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            report = _report_from_query(parsed.query)
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
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

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), ResearchReportHandler)
    try:
        print(f"serving {REPORT_PATH} on http://{host}:{server.server_port}", file=sys.stderr)
        server.serve_forever()
    finally:
        server.server_close()


def _payload_for_path(path: str, query: str) -> dict[str, Any]:
    if path == "/health":
        return {"status": "ok"}
    report = _report_from_query(query)
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


def _report_from_query(query: str) -> dict[str, Any]:
    params = parse_qs(query)
    mode = params.get("mode", ["research_only"])[0]
    snapshot_fixture = params.get("snapshot_fixture", [None])[0]
    live_deribit = params.get("live_deribit", ["0"])[0].lower() in {
        "1",
        "true",
        "yes",
    }
    currency = params.get("currency", ["BTC"])[0]
    deribit_base_url = params.get("deribit_base_url", [DEFAULT_DERIBIT_BASE_URL])[0]
    account_scenario = params.get("account_scenario", [None])[0]
    generated_at = params.get("generated_at", [None])[0]
    instrument_limit = _parse_optional_int(
        params.get("instrument_limit", [None])[0],
        name="instrument_limit",
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), ResearchReportHandler)
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
            query["deribit_base_url"] = deribit_base_url
            if instrument_limit is not None:
                query["instrument_limit"] = instrument_limit
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
                        "/health",
                        timeout=SMOKE_SERVER_REQUEST_TIMEOUT_SEC,
                    )["status"]
                    != "ok"
                ):
                    raise RuntimeError("local research-report server failed health check")
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
    if args.smoke:
        json.dump(
            smoke_once(account_scenario=args.account_scenario),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    serve(args.host, args.port)
    return 0


def _parse_optional_int(value: str | None, *, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


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
