"""Read-only Deribit account snapshot sidecar.

Credentials are read only from the process environment and are never returned,
persisted, or interpolated into structured logs.
"""

from __future__ import annotations

import argparse
import json
from math import isfinite
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    utc_timestamp,
    validate_deribit_base_url,
)
from .storage import atomic_write_json


DEFAULT_REFRESH_INTERVAL_SECONDS = 15.0
EXIT_OK = 0
EXIT_REFRESH_FAILED = 1
REQUIRED_SCOPES = ("account:read", "trade:read")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-account-snapshot-sidecar",
        description=(
            "Refresh one sanitized Deribit read-only account snapshot for the "
            "research-only API process."
        ),
    )
    parser.add_argument("--output", required=True, help="account snapshot JSON path")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_REFRESH_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--currency",
        default=os.environ.get("DERIBIT_ACCOUNT_CURRENCY", "BTC"),
    )
    parser.add_argument(
        "--base-url",
        "--deribit-base-url",
        dest="base_url",
        default=DEFAULT_DERIBIT_BASE_URL,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        base_url = validate_deribit_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    currency = str(args.currency).strip().upper()
    if not currency or not currency.isascii() or not currency.isalnum():
        parser.error("currency must contain only letters and digits")
    if not isfinite(args.interval) or args.interval <= 0:
        parser.error("interval must be finite and greater than zero")

    output = Path(args.output).expanduser().resolve()
    client_id = os.environ.get("DERIBIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("DERIBIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        payload = _not_configured_snapshot(currency=currency, base_url=base_url)
        atomic_write_json(output, payload)
        _log_json(
            "account_snapshot_not_configured",
            output=str(output),
            currency=currency,
            reason_code="MISSING_ACCOUNT_API_SNAPSHOT",
        )
        return EXIT_OK

    try:
        while True:
            try:
                payload = fetch_deribit_account_snapshot(
                    client_id=client_id,
                    client_secret=client_secret,
                    currency=currency,
                    base_url=base_url,
                )
            except Exception as exc:  # noqa: BLE001 - redact and fail closed
                payload = _failed_snapshot(currency=currency, base_url=base_url)
                atomic_write_json(output, payload)
                _log_json(
                    "account_snapshot_refresh_failed",
                    output=str(output),
                    currency=currency,
                    reason_code="AUTH_FAILED_ACCOUNT_API",
                    error_type=type(exc).__name__,
                    retrying=not args.once,
                )
                if args.once:
                    return EXIT_REFRESH_FAILED
            else:
                atomic_write_json(output, payload)
                _log_json(
                    "account_snapshot_written",
                    output=str(output),
                    currency=currency,
                    captured_at=payload.get("captured_at"),
                    position_count=len(payload.get("positions") or []),
                    open_order_count=len(payload.get("open_orders") or []),
                )
                if args.once:
                    return EXIT_OK
            time.sleep(args.interval)
    except KeyboardInterrupt:
        _log_json(
            "account_snapshot_sidecar_stopped",
            output=str(output),
            currency=currency,
            reason="keyboard_interrupt",
        )
        return EXIT_OK


def fetch_deribit_account_snapshot(
    *,
    client_id: str,
    client_secret: str,
    currency: str = "BTC",
    base_url: str = DEFAULT_DERIBIT_BASE_URL,
    timeout: int = 20,
) -> dict[str, Any]:
    safe_base = validate_deribit_base_url(base_url)
    normalized_currency = str(currency).strip().upper()
    if not client_id or not client_secret:
        raise ValueError("read-only Deribit credentials are required")

    auth = _rpc_get(
        safe_base,
        "public/auth",
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": " ".join(REQUIRED_SCOPES),
        },
        timeout,
    )
    if not isinstance(auth, dict):
        raise ValueError("authentication result must be an object")
    access_token = str(auth.get("access_token") or "")
    granted_scope = str(auth.get("scope") or "")
    if not access_token:
        raise ValueError("authentication response omitted access token")
    granted_tokens = {
        token.strip() for token in granted_scope.split() if token.strip()
    }
    if granted_tokens != set(REQUIRED_SCOPES):
        raise ValueError("authentication must grant the exact read-only scopes")

    common = {"access_token": access_token}
    account_result = _rpc_get(
        safe_base,
        "private/get_account_summary",
        {**common, "currency": normalized_currency, "extended": "false"},
        timeout,
    )
    positions_result = _rpc_get(
        safe_base,
        "private/get_positions",
        {**common, "currency": normalized_currency},
        timeout,
    )
    orders_result = _rpc_get(
        safe_base,
        "private/get_open_orders_by_currency",
        {**common, "currency": normalized_currency, "kind": "option"},
        timeout,
    )
    if not isinstance(account_result, dict):
        raise ValueError("account summary result must be an object")
    if not isinstance(positions_result, list) or not isinstance(orders_result, list):
        raise ValueError("positions and open orders results must be lists")

    observed_at = utc_timestamp()
    return {
        "schema_version": "deribit_account_snapshot.v1",
        "captured_at": observed_at,
        "source_endpoints": [
            "private/get_account_summary",
            "private/get_positions",
            "private/get_open_orders_by_currency",
        ],
        "account": _sanitize_account_summary(
            account_result,
            currency=normalized_currency,
            observed_at=observed_at,
        ),
        "positions": [_sanitize_position(item) for item in positions_result if isinstance(item, dict)],
        "open_orders": [_sanitize_open_order(item) for item in orders_result if isinstance(item, dict)],
        "simulation": {
            "status": "not_requested",
            "attempted": False,
            "source_endpoint": "private/simulate_portfolio",
            "reason_code": "SIMULATION_NOT_REQUESTED",
        },
        "replay_metadata": {
            "source": "live_deribit_private_read_only",
            "captured_shape_only": False,
            "credentials_persisted": False,
            "raw_identifiers_persisted": False,
            "required_scopes": list(REQUIRED_SCOPES),
        },
    }


def _sanitize_account_summary(
    payload: Mapping[str, Any],
    *,
    currency: str,
    observed_at: str,
) -> dict[str, Any]:
    result = {
        "status": "available",
        "configuration_status": "configured",
        "source": "deribit_live_private_read_only",
        "source_endpoint": "private/get_account_summary",
        "observed_at": observed_at,
        "currency": currency,
        "margin_model": (
            "portfolio_margin"
            if payload.get("portfolio_margining_enabled") is True
            else "standard_margin"
        ),
    }
    for field in (
        "equity",
        "balance",
        "margin_balance",
        "available_funds",
        "initial_margin",
        "maintenance_margin",
    ):
        result[field] = _safe_number(payload.get(field))
    return result


def _sanitize_position(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instrument_name": str(payload.get("instrument_name") or "unknown"),
        "kind": str(payload.get("kind") or "unknown"),
        "direction": str(payload.get("direction") or "unknown"),
        "size": _safe_number(payload.get("size")),
        "mark_price": _safe_number(payload.get("mark_price")),
        "index_price": _safe_number(payload.get("index_price")),
        "floating_pnl": _safe_number(
            payload.get("floating_profit_loss", payload.get("floating_pnl"))
        ),
        "initial_margin": _safe_number(payload.get("initial_margin")),
        "maintenance_margin": _safe_number(payload.get("maintenance_margin")),
        "delta": _safe_number(payload.get("delta")),
        "gamma": _safe_number(payload.get("gamma")),
        "theta": _safe_number(payload.get("theta")),
        "vega": _safe_number(payload.get("vega")),
        "source_endpoint": "private/get_positions",
    }


def _sanitize_open_order(payload: Mapping[str, Any]) -> dict[str, Any]:
    # Deliberately omit order_id, label, account identifiers and API metadata.
    return {
        "instrument_name": str(payload.get("instrument_name") or "unknown"),
        "direction": str(payload.get("direction") or "unknown"),
        "amount": _safe_number(payload.get("amount")),
        "filled_amount": _safe_number(payload.get("filled_amount")),
        "price": _safe_number(payload.get("price")),
        "order_state": str(payload.get("order_state") or "unknown"),
        "order_type": str(payload.get("order_type") or "unknown"),
        "creation_timestamp": _safe_integer(payload.get("creation_timestamp")),
        "last_update_timestamp": _safe_integer(payload.get("last_update_timestamp")),
        "source_endpoint": "private/get_open_orders_by_currency",
    }


def _not_configured_snapshot(*, currency: str, base_url: str) -> dict[str, Any]:
    observed_at = utc_timestamp()
    return {
        "schema_version": "deribit_account_snapshot.v1",
        "captured_at": observed_at,
        "source_endpoints": [],
        "account": {
            "status": "missing",
            "configuration_status": "not_configured",
            "source": "not_configured",
            "source_endpoint": "private/get_account_summary",
            "reason_code": "MISSING_ACCOUNT_API_SNAPSHOT",
            "detail_reason_code": "MISSING_DERIBIT_READ_ONLY_CREDENTIALS",
            "currency": currency,
            "margin_model": "unknown",
        },
        "positions": [],
        "open_orders": [],
        "simulation": {
            "status": "not_requested",
            "attempted": False,
            "reason_code": "SIMULATION_NOT_REQUESTED",
            "source_endpoint": "private/simulate_portfolio",
        },
        "replay_metadata": {
            "source": "not_configured",
            "captured_shape_only": True,
            "credentials_persisted": False,
            "raw_identifiers_persisted": False,
            "base_url_origin": base_url,
        },
    }


def _failed_snapshot(*, currency: str, base_url: str) -> dict[str, Any]:
    observed_at = utc_timestamp()
    return {
        "schema_version": "deribit_account_snapshot.v1",
        "captured_at": observed_at,
        "source_endpoints": ["public/auth"],
        "account": {
            "status": "auth_failed",
            "configuration_status": "configured",
            "source": "deribit_live_private_read_only",
            "source_endpoint": "private/get_account_summary",
            "reason_code": "AUTH_FAILED_ACCOUNT_API",
            "currency": currency,
            "margin_model": "unknown",
        },
        "positions": [],
        "open_orders": [],
        "simulation": {
            "status": "not_requested",
            "attempted": False,
            "reason_code": "SIMULATION_NOT_REQUESTED",
            "source_endpoint": "private/simulate_portfolio",
        },
        "replay_metadata": {
            "source": "live_deribit_private_read_only",
            "captured_shape_only": True,
            "credentials_persisted": False,
            "raw_identifiers_persisted": False,
            "base_url_origin": base_url,
        },
    }


def _rpc_get(
    base_url: str,
    method: str,
    params: Mapping[str, Any],
    timeout: int,
) -> Any:
    request = Request(
        f"{base_url}/api/v2/{method}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "codex-option-research-account/0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"deribit http status {exc.code}") from exc
    except URLError as exc:
        raise ValueError("deribit network failure") from exc
    if not isinstance(payload, dict):
        raise ValueError("Deribit response is not a JSON object")
    if payload.get("error"):
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise ValueError(f"Deribit RPC failure {code}")
    if "result" not in payload:
        raise ValueError("Deribit response omitted result")
    return payload["result"]


def _safe_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _safe_integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _log_json(event: str, **fields: Any) -> None:
    payload = {
        "timestamp": utc_timestamp(),
        "event": event,
        "research_only": True,
        "credentials_logged": False,
    }
    payload.update(fields)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
