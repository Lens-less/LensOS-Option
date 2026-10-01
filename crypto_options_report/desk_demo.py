"""Small synthetic market for the complete decision journey, never a live signal."""
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ._time import utc_timestamp


def demo_desk_snapshot(
    asset: str,
    *,
    captured_at: str | None = None,
    expiry_dates: list[str] | None = None,
) -> dict[str, Any]:
    if asset not in {"BTC", "ETH"}:
        raise ValueError("asset must be BTC or ETH")
    captured = captured_at or utc_timestamp()
    clock = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    spot = 100_000.0 if asset == "BTC" else 3_000.0
    expiries = (
        [datetime.fromisoformat(day).replace(hour=8, tzinfo=UTC) for day in expiry_dates]
        if expiry_dates
        else [(clock + timedelta(days=days)).replace(hour=8, minute=0, second=0, microsecond=0) for days in (21, 35)]
    )
    instruments: dict[str, Any] = {}
    summaries: dict[str, Any] = {}
    quotes: dict[str, Any] = {}
    expiry_counts = []
    for expiry in expiries:
        token = f"{expiry.day}{expiry.strftime('%b%y').upper()}"
        for kind, strikes in (("put", (0.85, 0.90, 0.95)), ("call", (1.05, 1.10, 1.15))):
            for strike_pct in strikes:
                strike = round(spot * strike_pct, 2)
                premium_pct = {0.05: 0.032, 0.10: 0.015, 0.15: 0.006}[round(abs(strike_pct - 1), 2)]
                bid, ask = spot * premium_pct, spot * (premium_pct + 0.001)
                name = f"{asset}_USDC-{token}-{strike:g}-{kind[0].upper()}"
                instruments[name] = {
                    "instrument_name": name, "asset": asset, "option_type": kind,
                    "strike": strike, "expiry_date": expiry.date().isoformat(),
                    "expiration_timestamp": int(expiry.timestamp() * 1000), "contract_size": 1,
                    "min_trade_amount": 0.01 if asset == "BTC" else 0.1,
                    "tick_size": 5 if asset == "BTC" else 0.2, "tick_size_steps": [],
                    "instrument_type": "linear", "settlement_currency": "USDC", "price_currency": "USDC",
                    "base_currency": asset, "index_name": f"{asset.lower()}_usdc", "active": True,
                    "settlement_period": "week", "maker_commission": 0, "taker_commission": 0.0003,
                    "eligible": True, "validation_errors": [],
                }
                summary = {
                    "bid": bid, "ask": ask, "mark_iv": 65.0, "iv_unit": "percent_points",
                    "observed_at": captured, "exchange_timestamp": int(clock.timestamp() * 1000),
                    "exchange_at": captured, "timestamp_kind": "summary_created",
                    "open_interest": 100.0, "volume": 10.0, "underlying_price": spot,
                }
                summaries[name] = summary
                quotes[name] = {
                    **summary, "instrument_name": name, "bid_size": 10.0, "ask_size": 12.0,
                    "index_price": spot, "greeks": {}, "timestamp_kind": "exchange_quote",
                    "state": "open", "source_endpoint": "synthetic_demo", "valid": True, "validation_errors": [],
                }
        expiry_counts.append({"expiry_date": expiry.date().isoformat(), "count": 6})
    fingerprint = hashlib.sha256(json.dumps([asset, captured, instruments], sort_keys=True).encode()).hexdigest()
    return {
        "schema_version": "desk_market.v1", "snapshot_id": f"demo-{fingerprint}", "asset": asset,
        "venue": "DERIBIT", "contract_family": "LINEAR_USDC", "execution_allowed": False,
        "captured_at": captured, "expires_at": (clock + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
        "source": {
            "mode": "demo", "provider": "SYNTHETIC_DEMO", "captured_at": captured,
            "notice": "虚构合约与报价，仅演示发现、比较和观察流程；不是历史表现或市场信号。",
        },
        "index": {"price": spot, "currency": "USDC", "name": f"{asset.lower()}_usdc", "observed_at": captured},
        "instruments": instruments, "summaries": summaries, "quotes": quotes,
        "coverage": {
            "registry_count": len(instruments), "summary_count": len(summaries), "scan_complete": True,
            "inverse_excluded_count": 0, "eligible_instrument_count": len(instruments), "deepened_count": len(quotes),
            "failures": [], "exclusions": {}, "expiry_counts": expiry_counts,
        },
    }
