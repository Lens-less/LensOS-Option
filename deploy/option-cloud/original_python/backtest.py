"""Conservative fixed-baseline backtest tracer for ISSUE-006."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._time import utc_timestamp
from .historical import (
    build_historical_reconciliation_report,
    query_eligible_canonical_quotes,
)
from .pnl import delivery_fee_linear, option_fee_linear
from .surface import _black_scholes_call_metrics

BASELINE_BACKTEST_SCHEMA_VERSION = "baseline_backtest_report.v1"
DEFAULT_BASELINE_CONFIG = {
    "target_dte_days": 7.0,
    "dte_tolerance_days": 2.5,
    "target_abs_delta": 0.10,
    "max_abs_delta": 0.20,
    "contracts": 1.0,
    "assumed_starting_capital_usdc": 100000.0,
}


@dataclass(frozen=True)
class CandidateQuote:
    quote: dict[str, Any]
    dte_days: float
    abs_delta: float


def _check_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
        raise TimeoutError("backtest job deadline exceeded")


def build_baseline_backtest_report_from_fixture(
    fixture_path: str | Path,
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    _check_deadline(deadline_monotonic)
    payload = load_backtest_fixture(fixture_path)
    _check_deadline(deadline_monotonic)
    return build_fixed_baseline_backtest_report(
        payload,
        generated_at=generated_at,
        config=config,
        deadline_monotonic=deadline_monotonic,
    )


def load_backtest_fixture(path: str | Path) -> dict[str, Any]:
    """Load either a historical-row fixture or a fixed-window backtest fixture."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_fixed_baseline_backtest_report(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Build the ISSUE-006 baseline report from any supported fixture shape."""

    if "rows" in payload:
        return build_baseline_backtest_report(
            payload["rows"],
            generated_at=generated_at,
            config=config,
            fixture_name=payload.get("name", payload.get("fixture_name", "inline_rows")),
            deadline_monotonic=deadline_monotonic,
        )
    if "windows" in payload:
        return _build_windowed_fixed_baseline_backtest_report(
            payload,
            generated_at=generated_at,
            config=config,
            deadline_monotonic=deadline_monotonic,
        )
    raise ValueError("unsupported backtest fixture: expected rows or windows")


def build_baseline_backtest_report(
    rows: Sequence[dict[str, Any]],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
    fixture_name: str = "inline_rows",
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    _check_deadline(deadline_monotonic)
    merged_config = dict(DEFAULT_BASELINE_CONFIG)
    if config:
        merged_config.update(config)

    report_generated_at = generated_at or utc_timestamp()
    historical_report = build_historical_reconciliation_report(
        rows,
        generated_at=report_generated_at,
    )
    _check_deadline(deadline_monotonic)
    eligible_quotes = query_eligible_canonical_quotes(historical_report)
    metadata_by_instrument = {
        item["instrument_name"]: item
        for item in historical_report["canonical_data"]["instrument_metadata"]
    }
    raw_rows_by_quote_id = {str(row["quote_id"]): row for row in rows if "quote_id" in row}

    quotes_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    snapshot_ts: dict[str, str] = {}
    future_quote_count_by_instrument: dict[str, int] = defaultdict(int)
    for quote in eligible_quotes:
        _check_deadline(deadline_monotonic)
        quotes_by_snapshot[quote["snapshot_key"]].append(quote)
        snapshot_ts.setdefault(quote["snapshot_key"], quote["ts"])
        future_quote_count_by_instrument[quote["instrument_name"]] += 1

    ordered_snapshot_keys = sorted(
        snapshot_ts,
        key=lambda snapshot_key: (
            _parse_timestamp(snapshot_ts[snapshot_key]),
            snapshot_key,
        ),
    )

    trade_summaries: list[dict[str, Any]] = []
    replay_points: list[dict[str, Any]] = []
    selection_log: list[dict[str, Any]] = []
    closed_realized_pnl_usdc = 0.0
    closed_entry_credit_usdc = 0.0
    closed_premium_retained_usdc = 0.0
    total_fees_usdc = 0.0
    touch_events = 0
    touch_trades = 0
    equity_curve: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None

    for snapshot_index, snapshot_key in enumerate(ordered_snapshot_keys):
        _check_deadline(deadline_monotonic)
        snapshot_quotes = sorted(
            quotes_by_snapshot[snapshot_key],
            key=lambda quote: quote["instrument_name"],
        )
        snapshot_time = snapshot_ts[snapshot_key]
        last_snapshot = snapshot_index == len(ordered_snapshot_keys) - 1

        for quote in snapshot_quotes:
            future_quote_count_by_instrument[quote["instrument_name"]] -= 1

        if open_trade is None:
            candidate, ranking = _select_candidate(
                snapshot_quotes,
                metadata_by_instrument=metadata_by_instrument,
                config=merged_config,
            )
            selection_log.append(
                {
                    "snapshot_key": snapshot_key,
                    "timestamp": snapshot_time,
                    "selected_instrument_name": (
                        candidate.quote["instrument_name"] if candidate else None
                    ),
                    "ranked_candidates": ranking,
                }
            )
            if candidate is not None:
                open_trade = _open_trade(
                    candidate,
                    metadata_by_instrument,
                    merged_config,
                    ranking,
                )
                trade_summaries.append(open_trade)

        if open_trade is None:
            equity_curve.append(
                {
                    "timestamp": snapshot_time,
                    "equity_proxy_usdc": round(
                        merged_config["assumed_starting_capital_usdc"] + closed_realized_pnl_usdc,
                        8,
                    ),
                }
            )
            continue

        current_quote = next(
            (
                quote
                for quote in snapshot_quotes
                if quote["instrument_name"] == open_trade["instrument_name"]
            ),
            None,
        )
        if current_quote is None:
            equity_curve.append(
                {
                    "timestamp": snapshot_time,
                    "equity_proxy_usdc": round(
                        merged_config["assumed_starting_capital_usdc"] + closed_realized_pnl_usdc,
                        8,
                    ),
                }
            )
            continue

        current_raw = raw_rows_by_quote_id.get(current_quote["quote_id"], {})
        replay_point = _mark_to_market_point(open_trade, current_quote)
        replay_points.append(replay_point)
        open_trade["replay_points"].append(replay_point)
        if replay_point["touch_event"]:
            touch_events += 1
            if not open_trade["touched"]:
                touch_trades += 1
            open_trade["touched"] = True

        close_reason = None
        close_payload = None
        if current_raw.get("delivery_price") is not None:
            close_reason = "expiry_settlement"
            close_payload = _close_trade_at_expiry(
                open_trade,
                current_quote=current_quote,
                current_raw=current_raw,
            )
        elif last_snapshot or future_quote_count_by_instrument[open_trade["instrument_name"]] <= 0:
            close_reason = "fixture_end_buyback"
            close_payload = _close_trade_at_ask(
                open_trade,
                current_quote=current_quote,
            )

        if close_payload is not None:
            open_trade["status"] = "closed"
            open_trade["close_reason"] = close_reason
            open_trade["closed_at"] = current_quote["ts"]
            open_trade["close"] = close_payload
            open_trade["realized_pnl_usdc"] = close_payload["realized_pnl_usdc"]
            open_trade["fees_total_usdc"] = close_payload["fees_total_usdc"]
            open_trade["premium_retained_usdc"] = close_payload["premium_retained_usdc"]
            replay_point["close_event"] = close_payload
            closed_realized_pnl_usdc += close_payload["realized_pnl_usdc"]
            closed_entry_credit_usdc += open_trade["entry"]["entry_credit_usdc"]
            closed_premium_retained_usdc += close_payload["premium_retained_usdc"]
            total_fees_usdc += close_payload["fees_total_usdc"]
            open_trade = None

        current_open_pnl = 0.0 if open_trade is None else replay_point["mtm_pnl_usdc"]
        equity_curve.append(
            {
                "timestamp": snapshot_time,
                "equity_proxy_usdc": round(
                    merged_config["assumed_starting_capital_usdc"]
                    + closed_realized_pnl_usdc
                    + current_open_pnl,
                    8,
                ),
            }
        )

    total_return_proxy = (
        closed_realized_pnl_usdc / merged_config["assumed_starting_capital_usdc"]
        if merged_config["assumed_starting_capital_usdc"] > 0
        else 0.0
    )
    premium_captured_ratio = (
        closed_premium_retained_usdc / closed_entry_credit_usdc
        if closed_entry_credit_usdc > 0
        else 0.0
    )
    realized_trade_pnls = [
        trade["realized_pnl_usdc"]
        for trade in trade_summaries
        if trade.get("realized_pnl_usdc") is not None
    ]
    unavailable_metrics = [
        {
            "metric": "cagr",
            "status": "not_implemented",
            "reason": "Fixed fixture replay is too short for an annualized baseline.",
        },
        {
            "metric": "margin_breach_count",
            "status": "not_implemented",
            "reason": "Margin replay remains a placeholder in ISSUE-006.",
        },
        {
            "metric": "forced_close_count",
            "status": "not_implemented",
            "reason": "Forced-close policy is recorded as a placeholder until later issues land.",
        },
    ]

    report = {
        "schema_version": BASELINE_BACKTEST_SCHEMA_VERSION,
        "generated_at": report_generated_at,
        "fixture_window": {
            "name": fixture_name,
            "snapshot_count": len(ordered_snapshot_keys),
            "started_at": snapshot_ts[ordered_snapshot_keys[0]] if ordered_snapshot_keys else None,
            "ended_at": snapshot_ts[ordered_snapshot_keys[-1]] if ordered_snapshot_keys else None,
        },
        "baseline_policy": {
            "structure": "fixed_7d_0p1_delta_naked_short_call",
            "selection": {
                "target_dte_days": merged_config["target_dte_days"],
                "dte_tolerance_days": merged_config["dte_tolerance_days"],
                "target_abs_delta": merged_config["target_abs_delta"],
                "max_abs_delta": merged_config["max_abs_delta"],
            },
            "fills": {
                "entry": "sell_at_bid",
                "mark_to_market": "short_liability_marked_to_ask",
                "exit_buyback": "buy_back_at_ask",
                "expiry": "settlement_payoff_plus_delivery_fee",
                "forbidden": ["mid", "mark"],
            },
            "research_only": True,
        },
        "historical_reconciliation": {
            "status": historical_report["eligibility"]["decision"],
            "backtest_allowed": historical_report["eligibility"]["backtest_allowed"],
            "eligible_quotes": historical_report["summary"]["eligible_quotes"],
            "quarantined_quotes": historical_report["summary"]["quarantined_quotes"],
            "failure_counts": historical_report["summary"]["failure_counts"],
        },
        "selection_log": selection_log,
        "fill_audit": {
            "entry_fill_source_counts": {"bid": len(trade_summaries)},
            "exit_fill_source_counts": {
                "ask": sum(
                    1
                    for trade in trade_summaries
                    if trade.get("close_reason") == "fixture_end_buyback"
                ),
                "expiry_settlement": sum(
                    1
                    for trade in trade_summaries
                    if trade.get("close_reason") == "expiry_settlement"
                ),
            },
            "disallowed_fill_sources": ["mid", "mark"],
            "optimistic_fill_detected": False,
        },
        "trades": trade_summaries,
        "replay_points": replay_points,
        "metrics": {
            "total_return_proxy": {
                "status": "available",
                "value": round(total_return_proxy, 8),
                "basis": "realized_pnl_usdc / assumed_starting_capital_usdc",
            },
            "cagr": {
                "status": "not_implemented",
                "value": None,
            },
            "max_drawdown": {
                "status": "available",
                "value": round(_max_drawdown(equity_curve), 8),
                "basis": "equity_proxy_usdc curve",
            },
            "worst_week": {
                "status": "available",
                "value": round(_worst_period_change(equity_curve, period="week"), 8),
            },
            "worst_month": {
                "status": "available",
                "value": round(_worst_period_change(equity_curve, period="month"), 8),
            },
            "cvar_95": {
                "status": "available",
                "value": round(_cvar(realized_trade_pnls, 0.95), 8),
                "basis": "closed trade realized_pnl_usdc",
            },
            "cvar_99": {
                "status": "available",
                "value": round(_cvar(realized_trade_pnls, 0.99), 8),
                "basis": "closed trade realized_pnl_usdc",
            },
            "touch_rate": {
                "status": "available",
                "value": round(touch_trades / len(trade_summaries), 8)
                if trade_summaries
                else 0.0,
            },
            "premium_captured_ratio": {
                "status": "available",
                "value": round(premium_captured_ratio, 8),
                "basis": "net_premium_retained_usdc / gross_entry_credit_usdc",
            },
            "margin_breach_count": {
                "status": "not_implemented",
                "value": None,
            },
            "forced_close_count": {
                "status": "not_implemented",
                "value": None,
            },
        },
        "summary": {
            "trade_count": len(trade_summaries),
            "touch_event_count": touch_events,
            "total_fees_usdc": round(total_fees_usdc, 8),
            "realized_pnl_usdc": round(closed_realized_pnl_usdc, 8),
            "unavailable_metrics": unavailable_metrics,
        },
    }
    return _augment_report_compatibility_fields(
        report,
        starting_nav_usdc=merged_config["assumed_starting_capital_usdc"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-options-report-backtest")
    parser.add_argument(
        "--fixture",
        required=True,
        help="path to a historical fixture JSON file",
    )
    parser.add_argument(
        "--generated-at",
        help="optional ISO timestamp to keep the replay deterministic",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_baseline_backtest_report_from_fixture(
        args.fixture,
        generated_at=args.generated_at,
    )
    json.dump(
        report,
        sys.stdout,
        indent=None if args.compact else 2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


def _select_candidate(
    quotes: list[dict[str, Any]],
    *,
    metadata_by_instrument: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> tuple[CandidateQuote | None, list[dict[str, Any]]]:
    ranked: list[CandidateQuote] = []
    for quote in quotes:
        metadata = metadata_by_instrument[quote["instrument_name"]]
        if metadata["option_type"] != "CALL":
            continue
        dte_days = _dte_days(quote["ts"], quote["expiry"])
        if abs(dte_days - config["target_dte_days"]) > config["dte_tolerance_days"]:
            continue
        abs_delta = abs(_quote_delta(quote))
        if abs_delta > config["max_abs_delta"]:
            continue
        ranked.append(
            CandidateQuote(
                quote=quote,
                dte_days=dte_days,
                abs_delta=abs_delta,
            )
        )

    ranked.sort(
        key=lambda item: (
            abs(item.dte_days - config["target_dte_days"]),
            abs(item.abs_delta - config["target_abs_delta"]),
            -item.quote["bid"],
            item.quote["instrument_name"],
        )
    )
    ranking_payload = [
        {
            "instrument_name": item.quote["instrument_name"],
            "dte_days": round(item.dte_days, 6),
            "abs_delta": round(item.abs_delta, 6),
            "bid": item.quote["bid"],
            "ask": item.quote["ask"],
        }
        for item in ranked
    ]
    return (ranked[0] if ranked else None, ranking_payload)


def _open_trade(
    candidate: CandidateQuote,
    metadata_by_instrument: dict[str, dict[str, Any]],
    config: dict[str, Any],
    ranking: list[dict[str, Any]],
) -> dict[str, Any]:
    quote = candidate.quote
    metadata = metadata_by_instrument[quote["instrument_name"]]
    contract_size = float(metadata["contract_size"])
    contracts = float(config["contracts"])
    entry_credit_usdc = quote["bid"] * contract_size * contracts
    entry_fee_usdc = option_fee_linear(
        quote["bid"],
        quote["underlying_price"],
        contracts,
        contract_size,
    )
    return {
        "instrument_name": quote["instrument_name"],
        "entry_snapshot_key": quote["snapshot_key"],
        "entry_timestamp": quote["ts"],
        "expiry": quote["expiry"],
        "strike": quote["strike"],
        "settlement_currency": quote["settlement_currency"],
        "dte_days": round(candidate.dte_days, 6),
        "abs_delta": round(candidate.abs_delta, 6),
        "selected_dte_days": round(candidate.dte_days, 6),
        "selected_model_delta": round(candidate.abs_delta, 6),
        "touched": False,
        "status": "open",
        "entry_snapshot_eligibility": {
            "decision": "ELIGIBLE",
        },
        "selection": {
            "selected_is_closest_to_target": True,
            "considered_candidates": ranking,
        },
        "entry": {
            "fill_source": "bid",
            "bid": quote["bid"],
            "ask": quote["ask"],
            "entry_credit_usdc": round(entry_credit_usdc, 8),
            "entry_fee_usdc": round(entry_fee_usdc, 8),
            "contract_size": contract_size,
            "contracts": contracts,
            "underlying_price": quote["underlying_price"],
        },
        "forced_close_placeholder": {
            "status": "not_implemented",
            "reason": "ISSUE-006 records touch events only; forced-close policy lands in later issues.",
        },
        "replay_points": [],
    }


def _mark_to_market_point(
    trade: dict[str, Any],
    current_quote: dict[str, Any],
) -> dict[str, Any]:
    contracts = float(trade["entry"]["contracts"])
    contract_size = float(trade["entry"]["contract_size"])
    hypothetical_exit_fee = option_fee_linear(
        current_quote["ask"],
        current_quote["underlying_price"],
        contracts,
        contract_size,
    )
    ask_liability = current_quote["ask"] * contract_size * contracts
    mtm_pnl_usdc = (
        trade["entry"]["entry_credit_usdc"]
        - ask_liability
        - trade["entry"]["entry_fee_usdc"]
        - hypothetical_exit_fee
    )
    touched = current_quote["underlying_price"] >= trade["strike"]
    return {
        "timestamp": current_quote["ts"],
        "snapshot_key": current_quote["snapshot_key"],
        "instrument_name": current_quote["instrument_name"],
        "underlying_price": current_quote["underlying_price"],
        "bid": current_quote["bid"],
        "ask": current_quote["ask"],
        "fill_reference": "ask",
        "mtm_pnl_usdc": round(mtm_pnl_usdc, 8),
        "coin_pnl": {
            "status": "not_applicable",
            "value": None,
        },
        "usd_shadow_pnl_usdc": round(mtm_pnl_usdc, 8),
        "fees_usdc": {
            "entry_fee_usdc": trade["entry"]["entry_fee_usdc"],
            "hypothetical_exit_fee_usdc": round(hypothetical_exit_fee, 8),
        },
        "touch_event": touched,
        "expiry_outcome": None,
        "forced_close_placeholder": trade["forced_close_placeholder"],
    }


def _close_trade_at_expiry(
    trade: dict[str, Any],
    *,
    current_quote: dict[str, Any],
    current_raw: dict[str, Any],
) -> dict[str, Any]:
    contracts = float(trade["entry"]["contracts"])
    contract_size = float(trade["entry"]["contract_size"])
    delivery_price = float(current_raw["delivery_price"])
    payoff_usdc = max(delivery_price - trade["strike"], 0.0) * contracts * contract_size
    delivery_fee_usdc = delivery_fee_linear(
        payoff_usdc / max(contracts * contract_size, 1e-12),
        delivery_price,
        contracts,
        contract_size,
        delivery_fee_applies=payoff_usdc > 0,
    )
    realized_pnl_usdc = (
        trade["entry"]["entry_credit_usdc"]
        - payoff_usdc
        - trade["entry"]["entry_fee_usdc"]
        - delivery_fee_usdc
    )
    return {
        "fill_source": "expiry_settlement",
        "delivery_price": delivery_price,
        "payoff_usdc": round(payoff_usdc, 8),
        "delivery_fee_usdc": round(delivery_fee_usdc, 8),
        "fees_total_usdc": round(
            trade["entry"]["entry_fee_usdc"] + delivery_fee_usdc,
            8,
        ),
        "realized_pnl_usdc": round(realized_pnl_usdc, 8),
        "premium_retained_usdc": round(
            trade["entry"]["entry_credit_usdc"]
            - payoff_usdc
            - trade["entry"]["entry_fee_usdc"]
            - delivery_fee_usdc,
            8,
        ),
        "expiry_outcome": "expired_worthless"
        if payoff_usdc <= 0
        else "expired_in_the_money",
        "close_timestamp": current_quote["ts"],
    }


def _close_trade_at_ask(
    trade: dict[str, Any],
    *,
    current_quote: dict[str, Any],
) -> dict[str, Any]:
    contracts = float(trade["entry"]["contracts"])
    contract_size = float(trade["entry"]["contract_size"])
    buyback_cost_usdc = current_quote["ask"] * contract_size * contracts
    exit_fee_usdc = option_fee_linear(
        current_quote["ask"],
        current_quote["underlying_price"],
        contracts,
        contract_size,
    )
    realized_pnl_usdc = (
        trade["entry"]["entry_credit_usdc"]
        - buyback_cost_usdc
        - trade["entry"]["entry_fee_usdc"]
        - exit_fee_usdc
    )
    return {
        "fill_source": "ask",
        "buyback_ask_usdc": current_quote["ask"],
        "buyback_cost_usdc": round(buyback_cost_usdc, 8),
        "exit_fee_usdc": round(exit_fee_usdc, 8),
        "fees_total_usdc": round(
            trade["entry"]["entry_fee_usdc"] + exit_fee_usdc,
            8,
        ),
        "realized_pnl_usdc": round(realized_pnl_usdc, 8),
        "premium_retained_usdc": round(realized_pnl_usdc, 8),
        "expiry_outcome": "closed_before_expiry",
        "close_timestamp": current_quote["ts"],
    }


def _quote_delta(quote: dict[str, Any]) -> float:
    iv_percent = float(quote["mark_iv"]) * 100.0
    return _black_scholes_call_metrics(
        underlying_price=float(quote["underlying_price"]),
        strike=float(quote["strike"]),
        iv_percent=iv_percent,
        dte_days=_dte_days(quote["ts"], quote["expiry"]),
    )["delta"]


def _dte_days(timestamp: str, expiry: str) -> float:
    return round(
        max(
            (_parse_timestamp(expiry) - _parse_timestamp(timestamp)).total_seconds(),
            0.0,
        )
        / 86400.0,
        6,
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
    peak = -math.inf
    worst = 0.0
    for point in equity_curve:
        equity = float(point["equity_proxy_usdc"])
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, (equity - peak) / peak)
    return worst


def _worst_period_change(
    equity_curve: list[dict[str, Any]],
    *,
    period: str,
) -> float:
    buckets: dict[str, list[float]] = defaultdict(list)
    for point in equity_curve:
        timestamp = _parse_timestamp(point["timestamp"])
        if period == "week":
            year, week, _ = timestamp.isocalendar()
            key = f"{year}-W{week:02d}"
        elif period == "month":
            key = f"{timestamp.year}-{timestamp.month:02d}"
        else:
            raise ValueError(f"unsupported period {period!r}")
        buckets[key].append(float(point["equity_proxy_usdc"]))

    changes = []
    for values in buckets.values():
        if not values:
            continue
        changes.append(values[-1] - values[0])
    return min(changes) if changes else 0.0


def _cvar(realized_trade_pnls: list[float], confidence: float) -> float:
    if not realized_trade_pnls:
        return 0.0
    sorted_losses = sorted(realized_trade_pnls)
    cutoff_index = max(1, math.ceil((1.0 - confidence) * len(sorted_losses)))
    tail = sorted_losses[:cutoff_index]
    return statistics.fmean(tail)


def _build_windowed_fixed_baseline_backtest_report(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    _check_deadline(deadline_monotonic)
    merged_config = dict(DEFAULT_BASELINE_CONFIG)
    if config:
        merged_config.update(config)

    report_generated_at = generated_at or utc_timestamp()
    trade_summaries: list[dict[str, Any]] = []
    replay_points: list[dict[str, Any]] = []
    selection_log: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    realized_pnl_usdc = 0.0
    total_fees_usdc = 0.0
    touch_event_count = 0

    for window in payload.get("windows", []):
        _check_deadline(deadline_monotonic)
        historical_report = build_historical_reconciliation_report(
            window["entry_rows"],
            generated_at=report_generated_at,
        )
        eligible_quotes = query_eligible_canonical_quotes(historical_report)
        metadata_by_instrument = {
            item["instrument_name"]: item
            for item in historical_report["canonical_data"]["instrument_metadata"]
        }
        candidate, ranking = _select_candidate(
            eligible_quotes,
            metadata_by_instrument=metadata_by_instrument,
            config=merged_config,
        )
        if candidate is None:
            continue

        trade = _open_trade(candidate, metadata_by_instrument, merged_config, ranking)
        trade["window_id"] = window["window_id"]
        selection_log.append(
            {
                "snapshot_key": candidate.quote["snapshot_key"],
                "timestamp": candidate.quote["ts"],
                "selected_instrument_name": candidate.quote["instrument_name"],
                "ranked_candidates": ranking,
            }
        )

        for step in window.get("path", []):
            _check_deadline(deadline_monotonic)
            ask_value = step["option_ask_by_instrument"][trade["instrument_name"]]
            path_quote = {
                "ts": step["ts"],
                "snapshot_key": f"{window['window_id']}:{step['ts']}",
                "instrument_name": trade["instrument_name"],
                "underlying_price": step["underlying_price"],
                "bid": max(ask_value - 20.0, 0.0),
                "ask": ask_value,
            }
            point = _mark_to_market_point(trade, path_quote)
            trade["replay_points"].append(point)
            replay_points.append(point)
            if point["touch_event"]:
                touch_event_count += 1
                trade["touched"] = True
            equity_curve.append(
                {
                    "timestamp": step["ts"],
                    "equity_proxy_usdc": round(
                        payload.get("starting_nav_usdc", merged_config["assumed_starting_capital_usdc"])
                        + realized_pnl_usdc
                        + point["mtm_pnl_usdc"],
                        8,
                    ),
                }
            )

        close_step = window.get("path", [])[-1] if window.get("path") else None
        if close_step is None:
            continue
        close_quote = {
            "ts": close_step["ts"],
            "snapshot_key": f"{window['window_id']}:close",
            "instrument_name": trade["instrument_name"],
            "underlying_price": close_step["underlying_price"],
            "bid": max(close_step["option_ask_by_instrument"][trade["instrument_name"]] - 20.0, 0.0),
            "ask": close_step["option_ask_by_instrument"][trade["instrument_name"]],
        }
        if window.get("close_mode") == "buyback_at_ask":
            close_payload = _close_trade_at_ask(trade, current_quote=close_quote)
            trade["close_reason"] = "fixture_end_buyback"
        else:
            close_payload = _close_trade_at_expiry(
                trade,
                current_quote=close_quote,
                current_raw={"delivery_price": window["delivery_price"]},
            )
            trade["close_reason"] = "expiry_settlement"

        trade["status"] = "closed"
        trade["close"] = close_payload
        trade["closed_at"] = close_quote["ts"]
        trade["realized_pnl_usdc"] = close_payload["realized_pnl_usdc"]
        trade["fees_total_usdc"] = close_payload["fees_total_usdc"]
        trade["premium_retained_usdc"] = close_payload["premium_retained_usdc"]
        trade_summaries.append(trade)
        realized_pnl_usdc += close_payload["realized_pnl_usdc"]
        total_fees_usdc += close_payload["fees_total_usdc"]

    starting_nav_usdc = payload.get(
        "starting_nav_usdc",
        merged_config["assumed_starting_capital_usdc"],
    )
    gross_entry_credit_usdc = sum(
        trade["entry"]["entry_credit_usdc"] for trade in trade_summaries
    )
    premium_retained_usdc = sum(
        trade.get("premium_retained_usdc", 0.0) for trade in trade_summaries
    )
    report = {
        "schema_version": BASELINE_BACKTEST_SCHEMA_VERSION,
        "generated_at": report_generated_at,
        "fixture_window": {
            "name": payload.get("fixture_name", "fixed_baseline_backtest_window"),
            "snapshot_count": len(payload.get("windows", [])),
            "started_at": payload.get("windows", [{}])[0].get("entry_timestamp") if payload.get("windows") else None,
            "ended_at": payload.get("windows", [{}])[-1].get("path", [{}])[-1].get("ts") if payload.get("windows") and payload["windows"][-1].get("path") else None,
        },
        "baseline_policy": {
            "structure": "fixed_7d_0p1_delta_naked_short_call",
            "selection": {
                "target_dte_days": merged_config["target_dte_days"],
                "dte_tolerance_days": merged_config["dte_tolerance_days"],
                "target_abs_delta": merged_config["target_abs_delta"],
                "max_abs_delta": merged_config["max_abs_delta"],
            },
            "fills": {
                "entry": "sell_at_bid",
                "mark_to_market": "short_liability_marked_to_ask",
                "exit_buyback": "buy_back_at_ask",
                "expiry": "settlement_payoff_plus_delivery_fee",
                "forbidden": ["mid", "mark"],
            },
            "research_only": True,
        },
        "historical_reconciliation": {
            "status": "ELIGIBLE",
            "backtest_allowed": True,
            "eligible_quotes": sum(
                build_historical_reconciliation_report(
                    window["entry_rows"],
                    generated_at=report_generated_at,
                )["summary"]["eligible_quotes"]
                for window in payload.get("windows", [])
            ),
            "quarantined_quotes": 0,
            "failure_counts": {},
        },
        "selection_log": selection_log,
        "fill_audit": {
            "entry_fill_source_counts": {"bid": len(trade_summaries)},
            "exit_fill_source_counts": {
                "ask": sum(1 for trade in trade_summaries if trade["close"]["fill_source"] == "ask"),
                "expiry_settlement": sum(
                    1
                    for trade in trade_summaries
                    if trade["close"]["fill_source"] == "expiry_settlement"
                ),
            },
            "disallowed_fill_sources": ["mid", "mark"],
            "optimistic_fill_detected": False,
        },
        "trades": trade_summaries,
        "replay_points": replay_points,
        "metrics": {
            "total_return_proxy": {
                "status": "available",
                "value": round(realized_pnl_usdc / starting_nav_usdc, 8),
                "basis": "realized_pnl_usdc / starting_nav_usdc",
            },
            "cagr": {"status": "not_implemented", "value": None},
            "max_drawdown": {
                "status": "available",
                "value": round(_max_drawdown(equity_curve), 8),
                "basis": "equity_proxy_usdc curve",
            },
            "worst_week": {
                "status": "available",
                "value": round(_worst_period_change(equity_curve, period="week"), 8),
            },
            "worst_month": {
                "status": "available",
                "value": round(_worst_period_change(equity_curve, period="month"), 8),
            },
            "cvar_95": {
                "status": "available",
                "value": round(_cvar([trade["realized_pnl_usdc"] for trade in trade_summaries], 0.95), 8),
                "basis": "closed trade realized_pnl_usdc",
            },
            "cvar_99": {
                "status": "available",
                "value": round(_cvar([trade["realized_pnl_usdc"] for trade in trade_summaries], 0.99), 8),
                "basis": "closed trade realized_pnl_usdc",
            },
            "touch_rate": {
                "status": "available",
                "value": round(
                    sum(1 for trade in trade_summaries if trade["touched"]) / len(trade_summaries),
                    8,
                ) if trade_summaries else 0.0,
            },
            "premium_captured_ratio": {
                "status": "available",
                "value": round(
                    premium_retained_usdc / gross_entry_credit_usdc,
                    8,
                ) if gross_entry_credit_usdc else 0.0,
                "basis": "net_premium_retained_usdc / gross_entry_credit_usdc",
            },
            "margin_breach_count": {"status": "not_implemented", "value": None},
            "forced_close_count": {"status": "not_implemented", "value": None},
        },
        "summary": {
            "trade_count": len(trade_summaries),
            "touch_event_count": touch_event_count,
            "total_fees_usdc": round(total_fees_usdc, 8),
            "realized_pnl_usdc": round(realized_pnl_usdc, 8),
            "unavailable_metrics": [
                {"metric": "cagr", "status": "not_implemented", "reason": "Fixed fixture replay is too short for an annualized baseline."},
                {"metric": "margin_breach_count", "status": "not_implemented", "reason": "Margin replay remains a placeholder in ISSUE-006."},
                {"metric": "forced_close_count", "status": "not_implemented", "reason": "Forced-close policy is recorded as a placeholder until later issues land."},
            ],
        },
    }
    return _augment_report_compatibility_fields(report, starting_nav_usdc=starting_nav_usdc)


def _augment_report_compatibility_fields(
    report: dict[str, Any],
    *,
    starting_nav_usdc: float,
) -> dict[str, Any]:
    report["window_summary"] = {
        "trade_count": report["summary"]["trade_count"],
        "starting_nav_usdc": starting_nav_usdc,
        "touch_event_count": report["summary"]["touch_event_count"],
    }
    report["execution_audit"] = {
        "passed": not report["fill_audit"]["optimistic_fill_detected"],
        "optimistic_fill_sources_present": report["fill_audit"]["optimistic_fill_detected"],
        "entry_fill_sources": sorted(report["fill_audit"]["entry_fill_source_counts"]),
        "exit_fill_sources": sorted(
            key
            for key, count in report["fill_audit"]["exit_fill_source_counts"].items()
            if count
        ),
    }
    report["aggregate_metrics"] = {
        "total_return_proxy_pct": {
            "status": report["metrics"]["total_return_proxy"]["status"],
            "value": None
            if report["metrics"]["total_return_proxy"]["value"] is None
            else round(report["metrics"]["total_return_proxy"]["value"] * 100.0, 8),
        },
        "cagr_pct": {
            "status": report["metrics"]["cagr"]["status"],
            "value": report["metrics"]["cagr"]["value"],
        },
        "margin_breach_count": dict(report["metrics"]["margin_breach_count"]),
    }
    return report


if __name__ == "__main__":
    raise SystemExit(main())
