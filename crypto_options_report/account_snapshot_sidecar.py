"""Read-only Deribit account snapshot sidecar.

Credentials are read only from the process environment and are never returned,
persisted, or interpolated into structured logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    utc_timestamp,
    validate_deribit_base_url,
)
from .sidecar_auth import (
    SidecarAuthUnavailable,
    sidecar_auth_state_path,
    write_sidecar_auth_state,
)
from .storage import atomic_write_json, read_json_object_from_stream

DEFAULT_REFRESH_INTERVAL_SECONDS = 15.0
MAX_ACCOUNT_HTTP_RESPONSE_BYTES = 4 * 1024 * 1024
EXIT_OK = 0
EXIT_REFRESH_FAILED = 1
REQUIRED_SCOPES = ("account:read", "trade:read")
DERIBIT_POSITION_KINDS = frozenset(
    {"future", "option", "spot", "future_combo", "option_combo"}
)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def urlopen(request: Request, *, timeout: int):
    """Open one Deribit request without following redirects."""
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


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
        authenticated = _persist_snapshot(output, payload)
        _log_json(
            "account_snapshot_not_configured",
            output=str(output),
            currency=currency,
            reason_code="MISSING_ACCOUNT_API_SNAPSHOT",
            sidecar_authenticated=authenticated,
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
            except Exception as exc:
                payload = _failed_snapshot(currency=currency, base_url=base_url)
                authenticated = _persist_snapshot(output, payload)
                _log_json(
                    "account_snapshot_refresh_failed",
                    output=str(output),
                    currency=currency,
                    reason_code="AUTH_FAILED_ACCOUNT_API",
                    error_type=type(exc).__name__,
                    retrying=not args.once,
                    sidecar_authenticated=authenticated,
                )
                if args.once:
                    return EXIT_REFRESH_FAILED
            else:
                authenticated = _persist_snapshot(output, payload)
                _log_json(
                    "account_snapshot_written",
                    output=str(output),
                    currency=currency,
                    captured_at=payload.get("captured_at"),
                    position_count=len(payload.get("positions") or []),
                    open_order_count=len(payload.get("open_orders") or []),
                    sidecar_authenticated=authenticated,
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

    auth = _rpc_post(
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

    account_result = _rpc_post(
        safe_base,
        "private/get_account_summary",
        {"currency": normalized_currency, "extended": "false"},
        timeout,
        access_token=access_token,
    )
    positions_result = _rpc_post(
        safe_base,
        "private/get_positions",
        {"currency": normalized_currency},
        timeout,
        access_token=access_token,
    )
    orders_result = _rpc_post(
        safe_base,
        "private/get_open_orders_by_currency",
        {"currency": normalized_currency, "kind": "option"},
        timeout,
        access_token=access_token,
    )
    if not isinstance(account_result, dict):
        raise ValueError("account summary result must be an object")
    if not isinstance(positions_result, list) or not isinstance(orders_result, list):
        raise ValueError("positions and open orders results must be lists")
    if any(not isinstance(item, Mapping) for item in positions_result):
        raise ValueError("positions result contains a non-object entry")
    if any(not isinstance(item, Mapping) for item in orders_result):
        raise ValueError("open orders result contains a non-object entry")

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
        "positions": [_sanitize_position(item) for item in positions_result],
        "open_orders": [_sanitize_open_order(item) for item in orders_result],
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
    response_currency = _required_text(payload, "currency", context="account summary")
    if response_currency.upper() != currency:
        raise ValueError("account summary currency must match the requested currency")
    portfolio_margining_enabled = payload.get("portfolio_margining_enabled")
    if not isinstance(portfolio_margining_enabled, bool):
        raise ValueError(
            "account summary portfolio_margining_enabled is required as a boolean"
        )
    result = {
        "status": "available",
        "configuration_status": "configured",
        "source": "deribit_live_private_read_only",
        "source_endpoint": "private/get_account_summary",
        "observed_at": observed_at,
        "currency": currency,
        "margin_model": (
            "portfolio_margin"
            if portfolio_margining_enabled
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
        result[field] = _required_finite_number(
            payload,
            field,
            context="account summary",
        )
    if result["equity"] <= 0.0 or result["balance"] <= 0.0 or result["margin_balance"] <= 0.0:
        raise ValueError("account summary equity and balances must be positive")
    if any(
        result[field] < 0.0
        for field in ("available_funds", "initial_margin", "maintenance_margin")
    ):
        raise ValueError("account summary funds and margins must be non-negative")
    return result


def _sanitize_position(payload: Mapping[str, Any]) -> dict[str, Any]:
    floating_pnl_field = (
        "floating_profit_loss"
        if "floating_profit_loss" in payload
        else "floating_pnl"
    )
    kind = _required_position_kind(payload, context="position")
    direction = _required_direction(payload, context="position")
    size = _required_finite_number(payload, "size", context="position")
    mark_price = _required_finite_number(payload, "mark_price", context="position")
    index_price = _required_finite_number(payload, "index_price", context="position")
    initial_margin = _required_finite_number(
        payload, "initial_margin", context="position"
    )
    maintenance_margin = _required_finite_number(
        payload, "maintenance_margin", context="position"
    )
    delta = _required_finite_number(payload, "delta", context="position")
    if size <= 0.0:
        raise ValueError("position size must be positive")
    if mark_price <= 0.0 or index_price <= 0.0:
        raise ValueError("position mark_price and index_price must be positive")
    if initial_margin < 0.0 or maintenance_margin < 0.0:
        raise ValueError("position margins must be non-negative")
    if not -1.0 <= delta <= 1.0:
        raise ValueError("position delta must be within [-1, 1]")
    return {
        "instrument_name": _required_text(
            payload, "instrument_name", context="position"
        ),
        "kind": kind,
        "direction": direction,
        "size": size,
        "mark_price": mark_price,
        "index_price": index_price,
        "floating_pnl": _required_finite_number(
            payload,
            floating_pnl_field,
            context="position",
        ),
        "initial_margin": initial_margin,
        "maintenance_margin": maintenance_margin,
        "delta": delta,
        "gamma": _optional_finite_number(payload, "gamma", context="position"),
        "theta": _optional_finite_number(payload, "theta", context="position"),
        "vega": _optional_finite_number(payload, "vega", context="position"),
        "source_endpoint": "private/get_positions",
    }


def _sanitize_open_order(payload: Mapping[str, Any]) -> dict[str, Any]:
    # Deliberately omit order_id, label, account identifiers and API metadata.
    direction = _required_direction(payload, context="open order")
    amount = _required_finite_number(payload, "amount", context="open order")
    filled_amount = _required_finite_number(
        payload, "filled_amount", context="open order"
    )
    price = _required_finite_number(payload, "price", context="open order")
    creation_timestamp = _required_integer(
        payload, "creation_timestamp", context="open order"
    )
    last_update_timestamp = _required_integer(
        payload, "last_update_timestamp", context="open order"
    )
    if amount <= 0.0:
        raise ValueError("open order amount must be positive")
    if not 0.0 <= filled_amount <= amount:
        raise ValueError("open order filled_amount must be between zero and amount")
    if price < 0.0:
        raise ValueError("open order price must be non-negative")
    if creation_timestamp < 0 or last_update_timestamp < 0:
        raise ValueError("open order timestamps must be non-negative")
    return {
        "instrument_name": _required_text(
            payload, "instrument_name", context="open order"
        ),
        "direction": direction,
        "amount": amount,
        "filled_amount": filled_amount,
        "price": price,
        "order_state": _required_text(
            payload, "order_state", context="open order"
        ),
        "order_type": _required_text(payload, "order_type", context="open order"),
        "creation_timestamp": creation_timestamp,
        "last_update_timestamp": last_update_timestamp,
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


def _rpc_post(
    base_url: str,
    method: str,
    params: Mapping[str, Any],
    timeout: int,
    *,
    access_token: str | None = None,
) -> Any:
    request_id = 1
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "codex-option-research-account/0.1",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(
        f"{base_url}/api/v2",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = read_json_object_from_stream(
                response,
                max_bytes=MAX_ACCOUNT_HTTP_RESPONSE_BYTES,
                description="Deribit account response",
            )
    except HTTPError as exc:
        raise ValueError(f"deribit http status {exc.code}") from exc
    except URLError as exc:
        raise ValueError("deribit network failure") from exc
    if not isinstance(payload, dict):
        raise ValueError("Deribit response is not a JSON object")
    if payload.get("jsonrpc") != "2.0":
        raise ValueError("Deribit response JSON-RPC version mismatch")
    response_id = payload.get("id")
    if (
        not isinstance(response_id, int)
        or isinstance(response_id, bool)
        or response_id != request_id
    ):
        raise ValueError("Deribit response request id mismatch")
    if payload.get("error"):
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise ValueError(f"Deribit RPC failure {code}")
    if "result" not in payload:
        raise ValueError("Deribit response omitted result")
    return payload["result"]


def _safe_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _required_text(
    payload: Mapping[str, Any],
    field: str,
    *,
    context: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} is required as non-empty text")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text when provided")
    return value.strip()


def _required_direction(payload: Mapping[str, Any], *, context: str) -> str:
    direction = _required_text(payload, "direction", context=context).lower()
    if direction not in {"buy", "sell"}:
        raise ValueError(f"{context} direction must be buy or sell")
    return direction


def _required_position_kind(payload: Mapping[str, Any], *, context: str) -> str:
    kind = _required_text(payload, "kind", context=context).lower()
    if kind not in DERIBIT_POSITION_KINDS:
        raise ValueError(f"{context} kind is not allowed")
    return kind


def _required_finite_number(
    payload: Mapping[str, Any],
    field: str,
    *,
    context: str,
) -> float:
    if field not in payload or payload.get(field) is None:
        raise ValueError(f"{context} {field} is required")
    number = _safe_number(payload.get(field))
    if number is None:
        raise ValueError(f"{context} {field} must be finite")
    return number


def _optional_finite_number(
    payload: Mapping[str, Any],
    field: str,
    *,
    context: str,
) -> float | None:
    if field not in payload or payload.get(field) is None:
        return None
    number = _safe_number(payload.get(field))
    if number is None:
        raise ValueError(f"{context} {field} must be finite when provided")
    return number


def _required_integer(
    payload: Mapping[str, Any],
    field: str,
    *,
    context: str,
) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} {field} is required as an integer")
    return value


def _validate_snapshot_before_authentication(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "deribit_account_snapshot.v1":
        raise ValueError("account snapshot schema_version is required")
    _required_text(payload, "captured_at", context="account snapshot")
    account = payload.get("account")
    positions = payload.get("positions")
    open_orders = payload.get("open_orders")
    if not isinstance(account, Mapping) or not account:
        raise ValueError("account snapshot account is required as a non-empty object")
    if not isinstance(positions, list) or any(
        not isinstance(item, Mapping) for item in positions
    ):
        raise ValueError("account snapshot positions must contain only objects")
    if not isinstance(open_orders, list) or any(
        not isinstance(item, Mapping) for item in open_orders
    ):
        raise ValueError("account snapshot open_orders must contain only objects")
    status = _required_text(account, "status", context="account snapshot account")
    if status not in {"available", "missing", "auth_failed"}:
        raise ValueError("account snapshot status is not allowed")
    if status == "available":
        if account.get("configuration_status") != "configured":
            raise ValueError("available account snapshot must be configured")
        if account.get("source") != "deribit_live_private_read_only":
            raise ValueError("available account snapshot source is invalid")
        if account.get("source_endpoint") != "private/get_account_summary":
            raise ValueError("available account snapshot source endpoint is invalid")
        _required_text(account, "observed_at", context="available account snapshot")
        _required_text(account, "currency", context="available account snapshot")
        _required_text(account, "margin_model", context="available account snapshot")
        for field in (
            "equity",
            "balance",
            "margin_balance",
            "available_funds",
            "initial_margin",
            "maintenance_margin",
        ):
            _required_finite_number(
                account,
                field,
                context="available account snapshot",
            )
        if (
            float(account["equity"]) <= 0.0
            or float(account["balance"]) <= 0.0
            or float(account["margin_balance"]) <= 0.0
        ):
            raise ValueError("available account equity and balances must be positive")
        if any(
            float(account[field]) < 0.0
            for field in ("available_funds", "initial_margin", "maintenance_margin")
        ):
            raise ValueError("available account funds and margins must be non-negative")
        for index, item in enumerate(positions):
            context = f"available position {index}"
            if item.get("source_endpoint") != "private/get_positions":
                raise ValueError(f"{context} source endpoint is invalid")
            _required_text(item, "instrument_name", context=context)
            _required_position_kind(item, context=context)
            _required_direction(item, context=context)
            for field in (
                "size",
                "mark_price",
                "index_price",
                "floating_pnl",
                "initial_margin",
                "maintenance_margin",
                "delta",
            ):
                _required_finite_number(item, field, context=context)
            if float(item["size"]) <= 0.0:
                raise ValueError(f"{context} size must be positive")
            if float(item["mark_price"]) <= 0.0 or float(item["index_price"]) <= 0.0:
                raise ValueError(f"{context} prices must be positive")
            if float(item["initial_margin"]) < 0.0 or float(item["maintenance_margin"]) < 0.0:
                raise ValueError(f"{context} margins must be non-negative")
            if not -1.0 <= float(item["delta"]) <= 1.0:
                raise ValueError(f"{context} delta must be within [-1, 1]")
            for field in ("gamma", "theta", "vega"):
                _optional_finite_number(item, field, context=context)
        for index, item in enumerate(open_orders):
            context = f"available open order {index}"
            if item.get("source_endpoint") != "private/get_open_orders_by_currency":
                raise ValueError(f"{context} source endpoint is invalid")
            for field in ("instrument_name", "order_state", "order_type"):
                _required_text(item, field, context=context)
            _required_direction(item, context=context)
            for field in ("amount", "filled_amount", "price"):
                _required_finite_number(item, field, context=context)
            for field in ("creation_timestamp", "last_update_timestamp"):
                _required_integer(item, field, context=context)
            if float(item["amount"]) <= 0.0:
                raise ValueError(f"{context} amount must be positive")
            if not 0.0 <= float(item["filled_amount"]) <= float(item["amount"]):
                raise ValueError(f"{context} filled_amount is outside amount")
            if float(item["price"]) < 0.0:
                raise ValueError(f"{context} price must be non-negative")
            if int(item["creation_timestamp"]) < 0 or int(item["last_update_timestamp"]) < 0:
                raise ValueError(f"{context} timestamps must be non-negative")
    elif positions or open_orders:
        raise ValueError("unavailable account snapshot cannot contain positions or orders")


def _persist_snapshot(output: Path, payload: dict[str, Any]) -> bool:
    _validate_snapshot_before_authentication(payload)
    atomic_write_json(output, payload)
    try:
        write_sidecar_auth_state(output, expected_payload=payload)
    except SidecarAuthUnavailable:
        sidecar_auth_state_path(output).unlink(missing_ok=True)
        return False
    return True


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
