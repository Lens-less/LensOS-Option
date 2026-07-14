"""Account-risk replay helpers for ISSUE-004."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

ACCOUNT_MARGIN_GREEN = "GREEN"
ACCOUNT_MARGIN_YELLOW = "YELLOW"
ACCOUNT_MARGIN_RED = "RED"
ACCOUNT_MARGIN_HALT = "HALT"

ACCOUNT_GATE_ALLOW_NEW = "ALLOW_NEW"
ACCOUNT_GATE_NO_NEW_TRADES = "NO_NEW_TRADES"
ACCOUNT_GATE_REDUCE_EXISTING = "REDUCE_EXISTING"
ACCOUNT_GATE_NO_TRADE = "NO_TRADE"

FRESHNESS_LIMIT_MS = 30_000
ACCOUNT_FUTURE_TOLERANCE_MS = 5_000
EPSILON = 1e-12
ACCOUNT_STATUS_VALUES = frozenset(
    {"available", "missing", "partial", "malformed", "schema_drift", "auth_failed"}
)

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
            "observed_at": "2026-07-07T00:01:00Z",
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
            "observed_at": "2026-07-07T00:01:10Z",
            "data_age_ms": 20000,
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
            "observed_at": "2026-07-07T00:01:05Z",
            "data_age_ms": 25000,
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
            "observed_at": "2026-07-06T23:56:30Z",
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
            "observed_at": "2026-07-07T00:01:10Z",
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


def load_private_replay_fixture(path: str | Path, *, scenario: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios") or {}
    if scenario not in scenarios:
        raise ValueError(f"private replay scenario {scenario!r} not found in {path}")
    scenario_payload = deepcopy(scenarios[scenario])
    replay_metadata = dict(payload.get("replay_metadata") or {})
    replay_metadata.update(scenario_payload.get("replay_metadata") or {})
    replay_metadata.setdefault("fixture_name", payload.get("fixture_name"))
    scenario_payload["replay_metadata"] = replay_metadata
    return scenario_payload


def build_account_status(
    *,
    generated_at: str,
    account_payload: dict[str, Any] | None = None,
    freshness_limit_ms: int = FRESHNESS_LIMIT_MS,
) -> dict[str, Any]:
    if not account_payload:
        return _missing_account_status(freshness_limit_ms)

    account_value = account_payload.get("account")
    positions_value = account_payload.get("positions", [])
    simulation_value = account_payload.get("simulation", {})
    replay_value = account_payload.get("replay_metadata", {})
    if (
        not isinstance(account_value, dict)
        or not isinstance(positions_value, list)
        or any(not isinstance(item, Mapping) for item in positions_value)
        or not isinstance(simulation_value, dict)
        or not isinstance(replay_value, dict)
    ):
        return _malformed_account_status(
            freshness_limit_ms=freshness_limit_ms,
            source="unknown",
            source_endpoint="private/get_account_summary",
            margin_model="unknown",
            replay_metadata={},
        )

    account = dict(account_value)
    positions = [dict(item) for item in positions_value]
    simulation = dict(simulation_value)
    replay_metadata = dict(replay_value)

    raw_status_value = account.get("status")
    if (
        not isinstance(raw_status_value, str)
        or raw_status_value not in ACCOUNT_STATUS_VALUES
    ):
        return _malformed_account_status(
            freshness_limit_ms=freshness_limit_ms,
            source="unknown",
            source_endpoint="private/get_account_summary",
            margin_model="unknown",
            replay_metadata=replay_metadata,
        )
    raw_status = raw_status_value
    source = str(account.get("source") or "deribit_replay")
    source_endpoint = str(
        account.get("source_endpoint")
        or account.get("endpoint")
        or "private/get_account_summary"
    )
    margin_model = str(account.get("margin_model") or "unknown")
    currency = str(account.get("currency") or "UNKNOWN").strip().upper()
    observed_at = account.get("observed_at")
    if raw_status in {"malformed", "schema_drift"}:
        if raw_status == "malformed":
            return _malformed_account_status(
                freshness_limit_ms=freshness_limit_ms,
                source=source,
                source_endpoint=source_endpoint,
                margin_model=margin_model,
                replay_metadata=replay_metadata,
            )
        return {
            "status": "schema_drift",
            "live_snapshot": False,
            "source": source,
            "source_endpoint": source_endpoint,
            "reason_code": "ACCOUNT_SCHEMA_DRIFT",
            "margin_light": ACCOUNT_MARGIN_HALT,
            "trade_gate": ACCOUNT_GATE_NO_TRADE,
            "freshness_limit_ms": freshness_limit_ms,
            "data_age_ms": None,
            "margin_model": margin_model,
            "snapshot": None,
            "positions": [],
            "simulation_status": normalize_simulation_status(simulation={}),
            "projected_margin": normalize_projected_margin(simulation={}),
            "private_adapter_contract": _private_adapter_contract(
                source=source,
                source_endpoint=source_endpoint,
                positions=[],
                simulation_status=normalize_simulation_status(simulation={}),
                data_age_ms=None,
                replay_metadata=replay_metadata,
                failure_class="schema_drift",
            ),
        }
    if raw_status == "missing":
        return _missing_account_status(freshness_limit_ms)
    if raw_status == "auth_failed":
        simulation_status = normalize_simulation_status(simulation=simulation)
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
            "positions": [],
            "simulation_status": simulation_status,
            "projected_margin": normalize_projected_margin(simulation=simulation),
            "private_adapter_contract": _private_adapter_contract(
                source=source,
                source_endpoint=source_endpoint,
                positions=[],
                simulation_status=simulation_status,
                data_age_ms=None,
                replay_metadata=replay_metadata,
                failure_class="auth_failed",
            ),
        }
    if raw_status == "available" and any(
        field not in account or account[field] is None
        for field in ("initial_margin", "maintenance_margin")
    ):
        return _malformed_account_status(
            freshness_limit_ms=freshness_limit_ms,
            source=source,
            source_endpoint=source_endpoint,
            margin_model=margin_model,
            replay_metadata=replay_metadata,
        )
    try:
        computed_data_age_ms = compute_data_age_ms(
            observed_at=observed_at,
            generated_at=generated_at,
        )
        declared_data_age_ms = maybe_float(account.get("data_age_ms"))
        if declared_data_age_ms is not None and declared_data_age_ms < 0:
            raise ValueError("account data age must be non-negative")
        data_age_ms = (
            None
            if computed_data_age_ms is None
            else max(0, computed_data_age_ms, int(declared_data_age_ms or 0))
        )
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
    except (ArithmeticError, TypeError, ValueError):
        return _malformed_account_status(
            freshness_limit_ms=freshness_limit_ms,
            source=source,
            source_endpoint=source_endpoint,
            margin_model=margin_model,
            replay_metadata=replay_metadata,
        )

    if raw_status == "partial":
        reason_code = "PARTIAL_ACCOUNT_REPLAY"
        return {
            "status": raw_status,
            "live_snapshot": False,
            "source": source,
            "source_endpoint": source_endpoint,
            "reason_code": reason_code,
            "margin_light": ACCOUNT_MARGIN_HALT,
            "trade_gate": ACCOUNT_GATE_NO_TRADE,
            "freshness_limit_ms": freshness_limit_ms,
            "data_age_ms": data_age_ms,
            "margin_model": margin_model,
            "snapshot": snapshot if raw_status == "partial" else None,
            "positions": normalized_positions,
            "simulation_status": simulation_status,
            "projected_margin": projected_margin,
            "private_adapter_contract": _private_adapter_contract(
                source=source,
                source_endpoint=source_endpoint,
                positions=normalized_positions,
                simulation_status=simulation_status,
                data_age_ms=data_age_ms,
                replay_metadata=replay_metadata,
                failure_class=raw_status,
            ),
        }
    stale_reason = (
        "MISSING_ACCOUNT_OBSERVED_AT"
        if computed_data_age_ms is None
        else "ACCOUNT_OBSERVED_AT_IN_FUTURE"
        if computed_data_age_ms < -ACCOUNT_FUTURE_TOLERANCE_MS
        else "STALE_ACCOUNT_DATA"
        if data_age_ms is not None and data_age_ms > freshness_limit_ms
        else None
    )
    if stale_reason is not None:
        return {
            "status": "stale",
            "live_snapshot": False,
            "source": source,
            "source_endpoint": source_endpoint,
            "reason_code": stale_reason,
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
                replay_metadata=replay_metadata,
                failure_class="stale",
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
        "live_snapshot": not simulation_status["blocks_new_trades"],
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
            replay_metadata=replay_metadata,
            failure_class=(
                simulation_status["reason_code"]
                if simulation_status["blocks_new_trades"]
                else None
            ),
        ),
    }


def account_reason_codes(account_status: dict[str, Any]) -> list[str]:
    codes = [str(account_status.get("reason_code") or "MISSING_ACCOUNT_API_SNAPSHOT")]
    simulation_reason = str(
        (account_status.get("simulation_status") or {}).get("reason_code") or ""
    )
    if simulation_reason and simulation_reason != "SIMULATION_AVAILABLE":
        codes.append(simulation_reason)
    return _unique_codes(codes)


def compute_data_age_ms(*, observed_at: Any, generated_at: str) -> int | None:
    observed = parse_timestamp(observed_at)
    generated = parse_timestamp(generated_at)
    if observed is None or generated is None:
        return None
    delta = generated - observed
    return int(delta.total_seconds() * 1000)


def normalize_account_snapshot(
    *,
    account: dict[str, Any],
    currency: str,
    margin_model: str,
    source_endpoint: str,
    data_age_ms: int | None,
) -> dict[str, Any]:
    equity = as_float(account.get("equity"), default=None)
    balance = as_float(account.get("balance"), default=equity)
    margin_balance = as_float(account.get("margin_balance"), default=equity)
    available_funds = as_float(account.get("available_funds"))
    initial_margin = as_float(account.get("initial_margin"), default=None)
    maintenance_margin = as_float(account.get("maintenance_margin"), default=None)
    nav_value = as_float(account.get("nav_value"), default=equity)
    declared_nav_usd = maybe_float(account.get("nav_usd"))
    nav_usd = (
        declared_nav_usd
        if declared_nav_usd is not None
        else equity
        if currency == "USD"
        else None
    )
    if (
        equity is None
        or equity <= 0
        or nav_value is None
        or nav_value <= 0
        or (declared_nav_usd is not None and declared_nav_usd <= 0)
        or initial_margin is None
        or initial_margin < 0
        or maintenance_margin is None
        or maintenance_margin < 0
    ):
        raise ValueError("account equity, nav, and margins are outside safe bounds")

    computed_im_nav = initial_margin / nav_value
    computed_nav_to_mm = nav_value / max(maintenance_margin, EPSILON)
    declared_im_nav = maybe_float(account.get("im_nav"))
    declared_nav_to_mm = maybe_float(account.get("nav_to_mm"))
    if declared_im_nav is not None and declared_im_nav < 0:
        raise ValueError("account im_nav must be non-negative")
    if declared_nav_to_mm is not None and declared_nav_to_mm <= 0:
        raise ValueError("account nav_to_mm must be positive")
    im_nav = max(computed_im_nav, declared_im_nav or computed_im_nav)
    nav_to_mm = min(
        computed_nav_to_mm,
        declared_nav_to_mm or computed_nav_to_mm,
    )

    return {
        "currency": currency,
        "equity": equity,
        "balance": balance,
        "margin_balance": margin_balance,
        "available_funds": available_funds,
        "initial_margin": initial_margin,
        "maintenance_margin": maintenance_margin,
        "nav_value": nav_value,
        "nav_currency": currency,
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
    attempted = simulation.get("attempted") is True
    source_endpoint = str(
        simulation.get("source_endpoint")
        or simulation.get("endpoint")
        or "private/simulate_portfolio"
    )
    reason_code = str(simulation.get("reason_code") or "")

    if status == "available" and not attempted:
        status = "unavailable"
        reason_code = "SIMULATION_ATTEMPT_REQUIRED"
    elif status == "available":
        try:
            _normalize_projected_margin_values(simulation)
        except (ArithmeticError, TypeError, ValueError):
            status = "unavailable"
            reason_code = "SIMULATION_EVIDENCE_INCOMPLETE"
        else:
            reason_code = reason_code or "SIMULATION_AVAILABLE"
    elif status == "not_requested":
        reason_code = reason_code or "SIMULATION_NOT_REQUESTED"
    elif status == "auth_failed":
        reason_code = reason_code or "AUTH_FAILED_SIMULATION_API"
    elif status == "unavailable":
        reason_code = reason_code or "SIMULATION_UNAVAILABLE"

    elif status not in {"not_requested", "auth_failed", "unavailable"}:
        status = "unavailable"
        reason_code = "SIMULATION_STATUS_INVALID"

    blocks_new_trades = status != "available" or not attempted

    return {
        "status": status,
        "attempted": attempted,
        "available": status == "available" and attempted,
        "blocks_new_trades": blocks_new_trades,
        "reason_code": reason_code,
        "source_endpoint": source_endpoint,
    }


def normalize_projected_margin(*, simulation: dict[str, Any]) -> dict[str, Any]:
    status = str(simulation.get("status") or "not_requested")
    if status == "available" and simulation.get("attempted") is not True:
        status = "unavailable"
    if status not in {"available", "not_requested", "unavailable", "auth_failed"}:
        status = "unavailable"
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

    try:
        values = _normalize_projected_margin_values(simulation)
    except (ArithmeticError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "initial_margin": None,
            "maintenance_margin": None,
            "nav_usd": None,
            "im_nav": None,
            "nav_to_mm": None,
            "delta_initial_margin": None,
            "delta_maintenance_margin": None,
        }
    return {"status": "available", **values}


def _normalize_projected_margin_values(
    simulation: dict[str, Any],
) -> dict[str, float | None]:
    nested_value = simulation.get("projected", {})
    if not isinstance(nested_value, Mapping):
        raise TypeError("simulation projected values must be a mapping")
    nested = dict(nested_value)

    def projected_value(flat_key: str, nested_key: str) -> float | None:
        value = simulation.get(flat_key)
        if value is None:
            value = nested.get(nested_key)
        return maybe_float(value)

    initial_margin = projected_value("projected_initial_margin", "initial_margin")
    maintenance_margin = projected_value(
        "projected_maintenance_margin",
        "maintenance_margin",
    )
    nav_usd = projected_value("projected_nav_usd", "nav_usd")
    if (
        initial_margin is None
        or initial_margin < 0
        or maintenance_margin is None
        or maintenance_margin < 0
        or nav_usd is None
        or nav_usd <= 0
    ):
        raise ValueError("simulation projection is missing safe margin or nav values")

    computed_im_nav = initial_margin / nav_usd
    computed_nav_to_mm = nav_usd / max(maintenance_margin, EPSILON)
    declared_im_nav = projected_value("projected_im_nav", "im_nav")
    declared_nav_to_mm = projected_value("projected_nav_to_mm", "nav_to_mm")
    if declared_im_nav is not None and declared_im_nav < 0:
        raise ValueError("simulation projected_im_nav must be non-negative")
    if declared_nav_to_mm is not None and declared_nav_to_mm <= 0:
        raise ValueError("simulation projected_nav_to_mm must be positive")

    return {
        "initial_margin": initial_margin,
        "maintenance_margin": maintenance_margin,
        "nav_usd": nav_usd,
        "im_nav": max(computed_im_nav, declared_im_nav or computed_im_nav),
        "nav_to_mm": min(
            computed_nav_to_mm,
            declared_nav_to_mm or computed_nav_to_mm,
        ),
        "delta_initial_margin": projected_value(
            "delta_initial_margin",
            "delta_initial_margin",
        ),
        "delta_maintenance_margin": projected_value(
            "delta_maintenance_margin",
            "delta_maintenance_margin",
        ),
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
        "blocks_new_trades": True,
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
            replay_metadata={},
            failure_class="missing",
        ),
    }


def _malformed_account_status(
    *,
    freshness_limit_ms: int,
    source: str,
    source_endpoint: str,
    margin_model: str,
    replay_metadata: dict[str, Any],
) -> dict[str, Any]:
    simulation_status = normalize_simulation_status(simulation={})
    return {
        "status": "malformed",
        "live_snapshot": False,
        "source": source,
        "source_endpoint": source_endpoint,
        "reason_code": "MALFORMED_ACCOUNT_REPLAY",
        "margin_light": ACCOUNT_MARGIN_HALT,
        "trade_gate": ACCOUNT_GATE_NO_TRADE,
        "freshness_limit_ms": freshness_limit_ms,
        "data_age_ms": None,
        "margin_model": margin_model,
        "snapshot": None,
        "positions": [],
        "simulation_status": simulation_status,
        "projected_margin": normalize_projected_margin(simulation={}),
        "private_adapter_contract": _private_adapter_contract(
            source=source,
            source_endpoint=source_endpoint,
            positions=[],
            simulation_status=simulation_status,
            data_age_ms=None,
            replay_metadata=replay_metadata,
            failure_class="malformed",
        ),
    }


def _private_adapter_contract(
    *,
    source: str,
    source_endpoint: str,
    positions: list[dict[str, Any]],
    simulation_status: dict[str, Any],
    data_age_ms: int | None,
    replay_metadata: dict[str, Any] | None = None,
    failure_class: str | None = None,
) -> dict[str, Any]:
    endpoints = [source_endpoint, "private/get_positions"]
    simulation_endpoint = simulation_status.get("source_endpoint")
    if simulation_endpoint and simulation_endpoint not in endpoints:
        endpoints.append(str(simulation_endpoint))
    return {
        "schema_version": "private_account_adapter_contract.v1",
        "source": source,
        "auth_safe": source != "unauthenticated_account_snapshot",
        "credential_required_for_tests": False,
        "replay_fixture": source == "deribit_replay",
        "live_order_submission_possible": False,
        "source_endpoints": endpoints,
        "position_count": len(positions),
        "data_age_ms": data_age_ms,
        "failure_class": failure_class,
        "redaction_proof": (replay_metadata or {}).get(
            "redaction_proof",
            "no_credentials_or_account_identifiers",
        ),
        "replay_fixture_id": (replay_metadata or {}).get("fixture_name"),
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
        return None
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
    if isinstance(value, bool):
        raise TypeError("boolean is not an economic numeric value")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("economic numeric values must be finite")
    return parsed


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
