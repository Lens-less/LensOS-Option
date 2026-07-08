"""Account-risk replay helpers for ISSUE-004."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

ACCOUNT_MARGIN_GREEN = "GREEN"
ACCOUNT_MARGIN_YELLOW = "YELLOW"
ACCOUNT_MARGIN_RED = "RED"
ACCOUNT_MARGIN_HALT = "HALT"

ACCOUNT_GATE_ALLOW_NEW = "ALLOW_NEW"
ACCOUNT_GATE_NO_NEW_TRADES = "NO_NEW_TRADES"
ACCOUNT_GATE_REDUCE_EXISTING = "REDUCE_EXISTING"
ACCOUNT_GATE_NO_TRADE = "NO_TRADE"

FRESHNESS_LIMIT_MS = 120_000
EPSILON = 1e-12

AVAILABLE_ACCOUNT_SCENARIOS = (
    "auth_failed",
    "green",
    "red",
    "simulation_unavailable",
    "stale",
    "yellow",
)

ACCOUNT_SCENARIOS: dict[str, dict[str, Any]] = {
    "green": {
        "account": {
            "status": "available",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-07T09:50:30Z",
            "data_age_ms": 30000,
            "currency": "USD",
            "equity": 5000.0,
            "balance": 4800.0,
            "margin_balance": 5000.0,
            "available_funds": 3600.0,
            "initial_margin": 1200.0,
            "maintenance_margin": 700.0,
            "margin_model": "portfolio_margin",
        },
        "positions": [
            {
                "instrument_name": "BTC-14JUL26-90000-C",
                "direction": "short",
                "size": -1.0,
                "mark_price": 0.031,
                "index_price": 88250.0,
                "floating_pnl": -120.0,
                "initial_margin": 500.0,
                "maintenance_margin": 280.0,
                "delta": 0.11,
                "gamma": 0.003,
                "theta": 7.2,
                "vega": 25.5,
                "source_endpoint": "private/get_positions",
            }
        ],
        "simulation": {
            "status": "available",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "projected_initial_margin": 1400.0,
            "projected_maintenance_margin": 820.0,
            "projected_nav_usd": 5000.0,
            "projected_im_nav": 0.28,
            "projected_nav_to_mm": 6.10,
            "delta_initial_margin": 200.0,
            "delta_maintenance_margin": 120.0,
        },
    },
    "yellow": {
        "account": {
            "status": "available",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-07T09:50:20Z",
            "data_age_ms": 40000,
            "currency": "USD",
            "equity": 5000.0,
            "balance": 5000.0,
            "margin_balance": 5000.0,
            "available_funds": 1600.0,
            "initial_margin": 1800.0,
            "maintenance_margin": 2900.0,
            "margin_model": "portfolio_margin",
        },
        "positions": [
            {
                "instrument_name": "BTC-14JUL26-85000-C",
                "direction": "short",
                "size": -2.0,
                "mark_price": 0.044,
                "index_price": 88250.0,
                "floating_pnl": -310.0,
                "initial_margin": 970.0,
                "maintenance_margin": 1440.0,
                "delta": 0.18,
                "gamma": 0.005,
                "theta": 9.8,
                "vega": 31.2,
                "source_endpoint": "private/get_positions",
            }
        ],
        "simulation": {
            "status": "available",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "projected_initial_margin": 1940.0,
            "projected_maintenance_margin": 2960.0,
            "projected_nav_usd": 5000.0,
            "projected_im_nav": 0.388,
            "projected_nav_to_mm": 1.69,
            "delta_initial_margin": 140.0,
            "delta_maintenance_margin": 60.0,
        },
    },
    "red": {
        "account": {
            "status": "available",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-07T09:50:10Z",
            "data_age_ms": 50000,
            "currency": "USD",
            "equity": 5000.0,
            "balance": 5000.0,
            "margin_balance": 5000.0,
            "available_funds": 700.0,
            "initial_margin": 2800.0,
            "maintenance_margin": 3500.0,
            "margin_model": "portfolio_margin",
        },
        "positions": [
            {
                "instrument_name": "BTC-14JUL26-82000-C",
                "direction": "short",
                "size": -3.0,
                "mark_price": 0.065,
                "index_price": 88250.0,
                "floating_pnl": -740.0,
                "initial_margin": 1810.0,
                "maintenance_margin": 2300.0,
                "delta": 0.29,
                "gamma": 0.009,
                "theta": 11.4,
                "vega": 44.1,
                "source_endpoint": "private/get_positions",
            }
        ],
        "simulation": {
            "status": "available",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "projected_initial_margin": 3025.0,
            "projected_maintenance_margin": 3610.0,
            "projected_nav_usd": 5000.0,
            "projected_im_nav": 0.605,
            "projected_nav_to_mm": 1.38,
            "delta_initial_margin": 225.0,
            "delta_maintenance_margin": 110.0,
        },
    },
    "stale": {
        "account": {
            "status": "available",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-07T09:40:00Z",
            "data_age_ms": 300000,
            "currency": "USD",
            "equity": 5000.0,
            "balance": 4800.0,
            "margin_balance": 5000.0,
            "available_funds": 3600.0,
            "initial_margin": 1200.0,
            "maintenance_margin": 700.0,
            "margin_model": "portfolio_margin",
        },
        "positions": [
            {
                "instrument_name": "BTC-14JUL26-90000-C",
                "direction": "short",
                "size": -1.0,
                "mark_price": 0.031,
                "index_price": 88250.0,
                "floating_pnl": -120.0,
                "initial_margin": 500.0,
                "maintenance_margin": 280.0,
                "delta": 0.11,
                "gamma": 0.003,
                "theta": 7.2,
                "vega": 25.5,
                "source_endpoint": "private/get_positions",
            }
        ],
        "simulation": {
            "status": "available",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "projected_initial_margin": 1400.0,
            "projected_maintenance_margin": 820.0,
            "projected_nav_usd": 5000.0,
            "projected_im_nav": 0.28,
            "projected_nav_to_mm": 6.10,
            "delta_initial_margin": 200.0,
            "delta_maintenance_margin": 120.0,
        },
    },
    "simulation_unavailable": {
        "account": {
            "status": "available",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "observed_at": "2026-07-07T09:50:40Z",
            "data_age_ms": 20000,
            "currency": "USD",
            "equity": 5000.0,
            "balance": 4800.0,
            "margin_balance": 5000.0,
            "available_funds": 3600.0,
            "initial_margin": 1200.0,
            "maintenance_margin": 700.0,
            "margin_model": "portfolio_margin",
        },
        "positions": [
            {
                "instrument_name": "BTC-14JUL26-90000-C",
                "direction": "short",
                "size": -1.0,
                "mark_price": 0.031,
                "index_price": 88250.0,
                "floating_pnl": -120.0,
                "initial_margin": 500.0,
                "maintenance_margin": 280.0,
                "delta": 0.11,
                "gamma": 0.003,
                "theta": 7.2,
                "vega": 25.5,
                "source_endpoint": "private/get_positions",
            }
        ],
        "simulation": {
            "status": "unavailable",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "reason_code": "SIMULATION_UNAVAILABLE",
        },
    },
    "auth_failed": {
        "account": {
            "status": "auth_failed",
            "source": "deribit_replay",
            "source_endpoint": "private/get_account_summary",
            "reason_code": "AUTH_FAILED_ACCOUNT_API",
            "margin_model": "portfolio_margin",
        },
        "positions": [],
        "simulation": {
            "status": "not_requested",
            "attempted": False,
            "source_endpoint": "private/simulate_portfolio",
        },
    },
}


def load_account_scenario(name: str) -> dict[str, Any]:
    if name not in ACCOUNT_SCENARIOS:
        raise ValueError(
            f"unsupported account scenario {name!r}; expected one of {sorted(ACCOUNT_SCENARIOS)}"
        )
    return deepcopy(ACCOUNT_SCENARIOS[name])


def build_account_status(
    *,
    generated_at: str,
    account_payload: dict[str, Any] | None = None,
    freshness_limit_ms: int = FRESHNESS_LIMIT_MS,
) -> dict[str, Any]:
    if not account_payload:
        return _missing_account_status(freshness_limit_ms)

    account = dict(account_payload.get("account") or {})
    positions = list(account_payload.get("positions") or [])
    simulation = dict(account_payload.get("simulation") or {})

    raw_status = str(account.get("status") or "available")
    source = str(account.get("source") or "deribit_replay")
    source_endpoint = str(
        account.get("source_endpoint")
        or account.get("endpoint")
        or "private/get_account_summary"
    )
    margin_model = str(account.get("margin_model") or "unknown")
    currency = str(account.get("currency") or "USD")
    observed_at = account.get("observed_at")
    data_age_ms = account.get("data_age_ms")
    if data_age_ms is None:
        data_age_ms = compute_data_age_ms(observed_at=observed_at, generated_at=generated_at)

    snapshot = normalize_account_snapshot(
        account=account,
        currency=currency,
        margin_model=margin_model,
        source_endpoint=source_endpoint,
        data_age_ms=data_age_ms,
    )
    normalized_positions = [normalize_position_snapshot(item) for item in positions]
    simulation_status = normalize_simulation_status(simulation=simulation)
    projected_margin = normalize_projected_margin(simulation=simulation)

    if raw_status == "missing":
        return _missing_account_status(freshness_limit_ms)
    if raw_status == "auth_failed":
        return {
            "status": "auth_failed",
            "live_snapshot": False,
            "source": source,
            "source_endpoint": source_endpoint,
            "reason_code": "AUTH_FAILED_ACCOUNT_API",
            "margin_light": ACCOUNT_MARGIN_HALT,
            "trade_gate": ACCOUNT_GATE_NO_TRADE,
            "freshness_limit_ms": freshness_limit_ms,
            "data_age_ms": None,
            "margin_model": margin_model,
            "snapshot": None,
            "positions": normalized_positions,
            "simulation_status": simulation_status,
            "projected_margin": projected_margin,
            "private_adapter_contract": _private_adapter_contract(
                source=source,
                source_endpoint=source_endpoint,
                positions=normalized_positions,
                simulation_status=simulation_status,
                data_age_ms=None,
            ),
        }

    if data_age_ms is not None and data_age_ms > freshness_limit_ms:
        return {
            "status": "stale",
            "live_snapshot": False,
            "source": source,
            "source_endpoint": source_endpoint,
            "reason_code": "STALE_ACCOUNT_DATA",
            "margin_light": ACCOUNT_MARGIN_HALT,
            "trade_gate": ACCOUNT_GATE_NO_TRADE,
            "freshness_limit_ms": freshness_limit_ms,
            "data_age_ms": data_age_ms,
            "margin_model": margin_model,
            "snapshot": snapshot,
            "positions": normalized_positions,
            "simulation_status": simulation_status,
            "projected_margin": projected_margin,
            "private_adapter_contract": _private_adapter_contract(
                source=source,
                source_endpoint=source_endpoint,
                positions=normalized_positions,
                simulation_status=simulation_status,
                data_age_ms=data_age_ms,
            ),
        }

    light, gate, light_reason = classify_margin_light(
        im_nav=snapshot["im_nav"],
        nav_to_mm=snapshot["nav_to_mm"],
    )
    reason_code = light_reason

    if simulation_status["blocks_new_trades"]:
        light = ACCOUNT_MARGIN_HALT
        gate = ACCOUNT_GATE_NO_TRADE
        reason_code = simulation_status["reason_code"]

    return {
        "status": "available",
        "live_snapshot": True,
        "source": source,
        "source_endpoint": source_endpoint,
        "reason_code": reason_code,
        "margin_light": light,
        "trade_gate": gate,
        "freshness_limit_ms": freshness_limit_ms,
        "data_age_ms": data_age_ms,
        "margin_model": margin_model,
        "snapshot": snapshot,
        "positions": normalized_positions,
        "simulation_status": simulation_status,
        "projected_margin": projected_margin,
        "private_adapter_contract": _private_adapter_contract(
            source=source,
            source_endpoint=source_endpoint,
            positions=normalized_positions,
            simulation_status=simulation_status,
            data_age_ms=data_age_ms,
        ),
    }


def account_reason_codes(account_status: dict[str, Any]) -> list[str]:
    codes = [str(account_status.get("reason_code") or "MISSING_ACCOUNT_API_SNAPSHOT")]
    simulation_reason = str(
        (account_status.get("simulation_status") or {}).get("reason_code") or ""
    )
    if simulation_reason and simulation_reason not in {"SIMULATION_AVAILABLE", "SIMULATION_NOT_REQUESTED"}:
        codes.append(simulation_reason)
    return _unique_codes(codes)


def compute_data_age_ms(*, observed_at: Any, generated_at: str) -> int | None:
    observed = parse_timestamp(observed_at)
    generated = parse_timestamp(generated_at)
    if observed is None or generated is None:
        return None
    delta = generated - observed
    return max(0, int(delta.total_seconds() * 1000))


def normalize_account_snapshot(
    *,
    account: dict[str, Any],
    currency: str,
    margin_model: str,
    source_endpoint: str,
    data_age_ms: int | None,
) -> dict[str, Any]:
    equity = as_float(account.get("equity"))
    balance = as_float(account.get("balance"), default=equity)
    margin_balance = as_float(account.get("margin_balance"), default=equity)
    available_funds = as_float(account.get("available_funds"))
    initial_margin = as_float(account.get("initial_margin"))
    maintenance_margin = as_float(account.get("maintenance_margin"))
    nav_usd = as_float(account.get("nav_usd"), default=equity)
    im_nav = as_float(account.get("im_nav"), default=initial_margin / max(nav_usd, EPSILON))
    nav_to_mm = as_float(
        account.get("nav_to_mm"),
        default=nav_usd / max(maintenance_margin, EPSILON),
    )

    return {
        "currency": currency,
        "equity": equity,
        "balance": balance,
        "margin_balance": margin_balance,
        "available_funds": available_funds,
        "initial_margin": initial_margin,
        "maintenance_margin": maintenance_margin,
        "nav_usd": nav_usd,
        "im_nav": im_nav,
        "nav_to_mm": nav_to_mm,
        "margin_model": margin_model,
        "source_endpoint": source_endpoint,
        "data_age_ms": data_age_ms,
    }


def normalize_position_snapshot(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "instrument_name": str(position.get("instrument_name") or "unknown"),
        "size": as_float(position.get("size")),
        "direction": normalize_direction(position),
        "mark_price": as_float(position.get("mark_price")),
        "index_price": as_float(position.get("index_price")),
        "pnl": as_float(
            position.get("pnl"),
            default=as_float(position.get("floating_pnl")),
        ),
        "initial_margin": as_float(position.get("initial_margin")),
        "maintenance_margin": as_float(position.get("maintenance_margin")),
        "greeks": {
            "delta": maybe_float(position.get("delta")),
            "gamma": maybe_float(position.get("gamma")),
            "theta": maybe_float(position.get("theta")),
            "vega": maybe_float(position.get("vega")),
        },
        "source_endpoint": str(position.get("source_endpoint") or "private/get_positions"),
    }


def normalize_simulation_status(*, simulation: dict[str, Any]) -> dict[str, Any]:
    status = str(simulation.get("status") or "not_requested")
    attempted = bool(simulation.get("attempted", False))
    source_endpoint = str(
        simulation.get("source_endpoint")
        or simulation.get("endpoint")
        or "private/simulate_portfolio"
    )
    reason_code = str(simulation.get("reason_code") or "")

    if status == "available":
        reason_code = reason_code or "SIMULATION_AVAILABLE"
    elif status == "not_requested":
        reason_code = reason_code or "SIMULATION_NOT_REQUESTED"
    elif status == "auth_failed":
        reason_code = reason_code or "AUTH_FAILED_SIMULATION_API"
    elif status == "unavailable":
        reason_code = reason_code or "SIMULATION_UNAVAILABLE"

    blocks_new_trades = status in {"auth_failed", "unavailable"}

    return {
        "status": status,
        "attempted": attempted,
        "available": status == "available",
        "blocks_new_trades": blocks_new_trades,
        "reason_code": reason_code,
        "source_endpoint": source_endpoint,
    }


def normalize_projected_margin(*, simulation: dict[str, Any]) -> dict[str, Any]:
    status = str(simulation.get("status") or "not_requested")
    if status != "available":
        return {
            "status": status,
            "initial_margin": None,
            "maintenance_margin": None,
            "nav_usd": None,
            "im_nav": None,
            "nav_to_mm": None,
            "delta_initial_margin": None,
            "delta_maintenance_margin": None,
        }

    return {
        "status": "available",
        "initial_margin": as_float(simulation.get("projected_initial_margin")),
        "maintenance_margin": as_float(simulation.get("projected_maintenance_margin")),
        "nav_usd": as_float(simulation.get("projected_nav_usd")),
        "im_nav": as_float(simulation.get("projected_im_nav")),
        "nav_to_mm": as_float(simulation.get("projected_nav_to_mm")),
        "delta_initial_margin": as_float(simulation.get("delta_initial_margin")),
        "delta_maintenance_margin": as_float(simulation.get("delta_maintenance_margin")),
    }


def classify_margin_light(*, im_nav: float, nav_to_mm: float) -> tuple[str, str, str]:
    if im_nav >= 0.50 or nav_to_mm <= 1.50:
        return (
            ACCOUNT_MARGIN_RED,
            ACCOUNT_GATE_REDUCE_EXISTING,
            "ACCOUNT_MARGIN_RED_REDUCE_EXISTING",
        )
    if im_nav >= 0.30 or nav_to_mm <= 2.00:
        return (
            ACCOUNT_MARGIN_YELLOW,
            ACCOUNT_GATE_NO_NEW_TRADES,
            "ACCOUNT_MARGIN_YELLOW_NO_NEW_TRADES",
        )
    return (
        ACCOUNT_MARGIN_GREEN,
        ACCOUNT_GATE_ALLOW_NEW,
        "ACCOUNT_MARGIN_GREEN",
    )


def risk_state_from_account_status(account_status: dict[str, Any]) -> str:
    gate = account_status.get("trade_gate")
    if gate == ACCOUNT_GATE_ALLOW_NEW:
        return ACCOUNT_MARGIN_GREEN
    if gate == ACCOUNT_GATE_NO_NEW_TRADES:
        return ACCOUNT_MARGIN_YELLOW
    if gate == ACCOUNT_GATE_REDUCE_EXISTING:
        return ACCOUNT_MARGIN_RED
    return ACCOUNT_MARGIN_HALT


def _missing_account_status(freshness_limit_ms: int) -> dict[str, Any]:
    simulation_status = {
        "status": "not_requested",
        "attempted": False,
        "available": False,
        "blocks_new_trades": False,
        "reason_code": "SIMULATION_NOT_REQUESTED",
        "source_endpoint": "private/simulate_portfolio",
    }
    return {
        "status": "missing",
        "live_snapshot": False,
        "source": "not_configured",
        "source_endpoint": "private/get_account_summary",
        "reason_code": "MISSING_ACCOUNT_API_SNAPSHOT",
        "margin_light": ACCOUNT_MARGIN_HALT,
        "trade_gate": ACCOUNT_GATE_NO_TRADE,
        "freshness_limit_ms": freshness_limit_ms,
        "data_age_ms": None,
        "margin_model": "unknown",
        "snapshot": None,
        "positions": [],
        "simulation_status": simulation_status,
        "projected_margin": {
            "status": "not_requested",
            "initial_margin": None,
            "maintenance_margin": None,
            "nav_usd": None,
            "im_nav": None,
            "nav_to_mm": None,
            "delta_initial_margin": None,
            "delta_maintenance_margin": None,
        },
        "private_adapter_contract": _private_adapter_contract(
            source="not_configured",
            source_endpoint="private/get_account_summary",
            positions=[],
            simulation_status=simulation_status,
            data_age_ms=None,
        ),
    }


def _private_adapter_contract(
    *,
    source: str,
    source_endpoint: str,
    positions: list[dict[str, Any]],
    simulation_status: dict[str, Any],
    data_age_ms: int | None,
) -> dict[str, Any]:
    endpoints = [source_endpoint, "private/get_positions"]
    simulation_endpoint = simulation_status.get("source_endpoint")
    if simulation_endpoint and simulation_endpoint not in endpoints:
        endpoints.append(str(simulation_endpoint))
    return {
        "schema_version": "private_account_adapter_contract.v1",
        "source": source,
        "auth_safe": True,
        "credential_required_for_tests": False,
        "replay_fixture": source == "deribit_replay",
        "live_order_submission_possible": False,
        "source_endpoints": endpoints,
        "position_count": len(positions),
        "data_age_ms": data_age_ms,
        "failure_policy": "force_no_trade_on_missing_auth_stale_partial_or_malformed",
    }


def parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_direction(position: dict[str, Any]) -> str:
    direction = str(position.get("direction") or "").strip().lower()
    if direction:
        return direction
    size = maybe_float(position.get("size"))
    return "short" if size < 0 else "long"


def as_float(value: Any, *, default: float | None = 0.0) -> float | None:
    maybe = maybe_float(value)
    if maybe is None:
        return default
    return maybe


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
