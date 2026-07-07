"""Deribit option-chain snapshot tracing and quality evaluation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_DERIBIT_BASE_URL = "https://www.deribit.com"
DEFAULT_QUALITY_LIMITS = {
    "market_data_max_age_sec": 60,
    "stale_quote_max_sec": 120,
    "min_valid_quotes_per_expiry": 8,
    "max_bad_quote_ratio_per_expiry": 0.25,
    "max_spread_ratio": 0.50,
}

SPREAD_SANITY_FLAGS = {
    "MISSING_BID",
    "MISSING_ASK",
    "NON_POSITIVE_BID",
    "NON_POSITIVE_ASK",
    "CROSSED_MARKET",
    "NON_POSITIVE_MID",
    "MISSING_SPREAD_RATIO",
    "NEGATIVE_SPREAD",
    "SPREAD_TOO_WIDE",
}
BLOCKING_QUALITY_FLAGS = SPREAD_SANITY_FLAGS.union(
    {
        "STALE_QUOTE",
        "INVALID_UNDERLYING_PRICE",
        "MISSING_BID_IV",
        "MISSING_ASK_IV",
        "MISSING_MARK_IV",
        "INVALID_BID_IV",
        "INVALID_ASK_IV",
        "INVALID_MARK_IV",
        "MISSING_DEPTH",
    }
)

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_timestamp_ms(value: str | int | float | None) -> int:
    if value is None:
        raise ValueError("missing timestamp")
    if isinstance(value, (int, float)):
        return int(value)
    return int(
        datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    )


def load_snapshot_fixture(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if "rows" not in payload:
        raise ValueError(f"snapshot fixture {fixture_path} is missing rows")
    payload.setdefault("source", f"fixture:{fixture_path.name}")
    payload.setdefault("currency", "BTC")
    if "captured_at" not in payload:
        raise ValueError(f"snapshot fixture {fixture_path} is missing captured_at")
    return payload


def fetch_deribit_option_chain_snapshot(
    *,
    currency: str = "BTC",
    base_url: str = DEFAULT_DERIBIT_BASE_URL,
    instrument_limit: int | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    summaries = _get_json(
        f"{base_url.rstrip('/')}/api/v2/public/get_book_summary_by_currency",
        {"currency": currency, "kind": "option"},
        timeout=timeout,
    )["result"]
    summaries = sorted(
        (row for row in summaries if _looks_like_option(row.get("instrument_name"))),
        key=lambda row: row["instrument_name"],
    )
    if instrument_limit is not None:
        summaries = summaries[: max(0, instrument_limit)]

    tickers: dict[str, Any] = {}
    errors: list[str] = []
    max_workers = max(1, min(8, len(summaries) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _get_json,
                f"{base_url.rstrip('/')}/api/v2/public/ticker",
                {"instrument_name": row["instrument_name"]},
                timeout,
            ): row["instrument_name"]
            for row in summaries
        }
        for future in as_completed(futures):
            instrument_name = futures[future]
            try:
                tickers[instrument_name] = future.result()["result"]
            except ValueError as exc:
                errors.append(f"{instrument_name}: {exc}")

    rows = [
        {
            "summary": row,
            "ticker": tickers.get(row["instrument_name"]),
            "instrument_name": row["instrument_name"],
        }
        for row in summaries
    ]
    return {
        "captured_at": utc_timestamp(),
        "currency": currency,
        "source": f"deribit_live:{base_url.rstrip('/')}",
        "rows": rows,
        "fetch_errors": errors,
    }


def build_market_data_status(
    snapshot: dict[str, Any],
    *,
    now_ms: int | None = None,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    normalized = normalize_market_snapshot(snapshot, now_ms=now_ms, limits=limits)
    gate = evaluate_market_data_quality(normalized, limits=limits)
    return {
        "status": "validated" if gate["passed"] else "blocked",
        "validated": gate["passed"],
        "source": normalized["source"],
        "reason_code": None if gate["passed"] else "MARKET_DATA_QUALITY_FAIL",
        "snapshot_captured_at": normalized["captured_at"],
        "market_data_age_sec": normalized["snapshot_age_sec"],
        "quality_gate": gate,
    }


def normalize_market_snapshot(
    snapshot: dict[str, Any],
    *,
    now_ms: int | None = None,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    normalized_limits = dict(DEFAULT_QUALITY_LIMITS)
    if limits:
        normalized_limits.update(limits)

    evaluation_now_ms = (
        now_ms if now_ms is not None else parse_timestamp_ms(utc_timestamp())
    )
    captured_at_ms = parse_timestamp_ms(snapshot["captured_at"])
    quotes = [
        _normalize_quote_row(row, snapshot, evaluation_now_ms, normalized_limits)
        for row in snapshot["rows"]
    ]
    return {
        "captured_at": snapshot["captured_at"],
        "captured_at_ms": captured_at_ms,
        "snapshot_age_sec": round(max(0, evaluation_now_ms - captured_at_ms) / 1000, 3),
        "source": snapshot.get("source", "fixture"),
        "currency": snapshot.get("currency", "BTC"),
        "quotes": quotes,
        "fetch_errors": list(snapshot.get("fetch_errors", [])),
    }


def evaluate_market_data_quality(
    normalized_snapshot: dict[str, Any],
    *,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    normalized_limits = dict(DEFAULT_QUALITY_LIMITS)
    if limits:
        normalized_limits.update(limits)

    quotes = normalized_snapshot["quotes"]
    quotes_by_expiry: dict[str, list[dict[str, Any]]] = {}
    for quote in quotes:
        quotes_by_expiry.setdefault(quote["expiry_date"], []).append(quote)

    per_expiry: list[dict[str, Any]] = []
    overall_reason_codes: list[str] = []
    if normalized_snapshot["snapshot_age_sec"] > normalized_limits["market_data_max_age_sec"]:
        overall_reason_codes.append("MARKET_DATA_AGE_EXCEEDED")

    for expiry_date in sorted(quotes_by_expiry):
        expiry_quotes = quotes_by_expiry[expiry_date]
        invalid_quotes = [q for q in expiry_quotes if q["quality_status"] != "valid"]
        valid_quotes = len(expiry_quotes) - len(invalid_quotes)
        bad_quote_ratio = (
            len(invalid_quotes) / len(expiry_quotes) if expiry_quotes else 1.0
        )
        stale_quotes = sum("STALE_QUOTE" in q["quality_flags"] for q in expiry_quotes)
        spread_sanity_failures = sum(
            any(flag in SPREAD_SANITY_FLAGS for flag in q["quality_flags"])
            for q in expiry_quotes
        )
        reason_codes: list[str] = []
        if valid_quotes < normalized_limits["min_valid_quotes_per_expiry"]:
            reason_codes.append("INSUFFICIENT_VALID_QUOTES")
        if bad_quote_ratio > normalized_limits["max_bad_quote_ratio_per_expiry"]:
            reason_codes.append("BAD_QUOTE_RATIO_EXCEEDED")
        if spread_sanity_failures:
            reason_codes.append("SPREAD_SANITY_FAILED")
        status = "pass" if not reason_codes else "fail"
        if status == "fail":
            for code in reason_codes:
                if code not in overall_reason_codes:
                    overall_reason_codes.append(code)

        per_expiry.append(
            {
                "expiry_date": expiry_date,
                "status": status,
                "total_quotes": len(expiry_quotes),
                "valid_quotes": valid_quotes,
                "invalid_quotes": len(invalid_quotes),
                "stale_quotes": stale_quotes,
                "spread_sanity_failures": spread_sanity_failures,
                "bad_quote_ratio": round(bad_quote_ratio, 4),
                "reason_codes": reason_codes,
            }
        )

    passed = not overall_reason_codes and bool(per_expiry)
    return {
        "passed": passed,
        "action_if_fail": "RESEARCH_ONLY_NO_TRADE",
        "reason_codes": overall_reason_codes,
        "thresholds": normalized_limits,
        "per_expiry": per_expiry,
        "summary": {
            "total_quotes": len(quotes),
            "valid_quotes": sum(q["quality_status"] == "valid" for q in quotes),
            "invalid_quotes": sum(q["quality_status"] != "valid" for q in quotes),
            "expiries_evaluated": len(per_expiry),
            "market_data_age_sec": normalized_snapshot["snapshot_age_sec"],
            "fetch_errors": len(normalized_snapshot.get("fetch_errors", [])),
        },
    }


def _normalize_quote_row(
    row: dict[str, Any],
    snapshot: dict[str, Any],
    evaluation_now_ms: int,
    limits: dict[str, float],
) -> dict[str, Any]:
    summary = row.get("summary", row)
    ticker = row.get("ticker") or {}
    instrument_name = (
        row.get("instrument_name")
        or ticker.get("instrument_name")
        or summary.get("instrument_name")
    )
    metadata = _parse_option_metadata(instrument_name)
    bid = _first_number(ticker.get("best_bid_price"), summary.get("bid_price"))
    ask = _first_number(ticker.get("best_ask_price"), summary.get("ask_price"))
    mid = _first_number(
        summary.get("mid_price"),
        _average_if_numbers(bid, ask),
    )
    mark = _first_number(ticker.get("mark_price"), summary.get("mark_price"))
    bid_iv = _to_number(ticker.get("bid_iv"))
    ask_iv = _to_number(ticker.get("ask_iv"))
    mark_iv = _to_number(ticker.get("mark_iv"))
    underlying_price = _first_number(
        ticker.get("underlying_price"),
        summary.get("underlying_price"),
        ticker.get("index_price"),
    )
    best_bid_amount = _to_number(ticker.get("best_bid_amount"))
    best_ask_amount = _to_number(ticker.get("best_ask_amount"))
    depth = (
        None
        if best_bid_amount is None and best_ask_amount is None
        else round((best_bid_amount or 0.0) + (best_ask_amount or 0.0), 6)
    )
    timestamp_ms = _first_number(
        ticker.get("timestamp"),
        summary.get("creation_timestamp"),
        parse_timestamp_ms(snapshot["captured_at"]),
    )
    quote_age_sec = round(max(0, evaluation_now_ms - int(timestamp_ms)) / 1000, 3)
    spread_ratio = None
    if bid is not None and ask is not None and mid not in (None, 0):
        spread_ratio = round((ask - bid) / mid, 6)

    quote = {
        "instrument_name": instrument_name,
        "base_currency": summary.get("base_currency", metadata["base_currency"]),
        "quote_currency": summary.get("quote_currency", "USD"),
        "expiry_date": metadata["expiry_date"],
        "strike": metadata["strike"],
        "option_type": metadata["option_type"],
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "mark": mark,
        "bid_iv": bid_iv,
        "ask_iv": ask_iv,
        "mark_iv": mark_iv,
        "underlying_price": underlying_price,
        "open_interest": _first_number(
            ticker.get("open_interest"),
            summary.get("open_interest"),
        ),
        "best_bid_amount": best_bid_amount,
        "best_ask_amount": best_ask_amount,
        "depth": depth,
        "quote_age_sec": quote_age_sec,
        "source": snapshot.get("source", "fixture"),
        "spread_ratio": spread_ratio,
        "exchange_greeks": _normalize_exchange_greeks(ticker.get("greeks")),
    }
    flags = _quality_flags(quote, limits)
    quote["quality_flags"] = flags
    quote["quality_status"] = "valid" if not flags else "invalid"
    return quote


def _quality_flags(quote: dict[str, Any], limits: dict[str, float]) -> list[str]:
    flags: list[str] = []
    bid = quote["bid"]
    ask = quote["ask"]
    mid = quote["mid"]

    if bid is None:
        flags.append("MISSING_BID")
    elif bid <= 0:
        flags.append("NON_POSITIVE_BID")

    if ask is None:
        flags.append("MISSING_ASK")
    elif ask <= 0:
        flags.append("NON_POSITIVE_ASK")

    if bid is not None and ask is not None and ask < bid:
        flags.append("CROSSED_MARKET")
    if mid is None or mid <= 0:
        flags.append("NON_POSITIVE_MID")

    spread_ratio = quote["spread_ratio"]
    if spread_ratio is None:
        flags.append("MISSING_SPREAD_RATIO")
    elif spread_ratio < 0:
        flags.append("NEGATIVE_SPREAD")
    elif spread_ratio > limits["max_spread_ratio"]:
        flags.append("SPREAD_TOO_WIDE")

    if quote["quote_age_sec"] > limits["stale_quote_max_sec"]:
        flags.append("STALE_QUOTE")
    if quote["underlying_price"] is None or quote["underlying_price"] <= 0:
        flags.append("INVALID_UNDERLYING_PRICE")
    if quote["depth"] is None or quote["depth"] <= 0:
        flags.append("MISSING_DEPTH")

    for field_name, missing_flag, invalid_flag in (
        ("bid_iv", "MISSING_BID_IV", "INVALID_BID_IV"),
        ("ask_iv", "MISSING_ASK_IV", "INVALID_ASK_IV"),
        ("mark_iv", "MISSING_MARK_IV", "INVALID_MARK_IV"),
    ):
        iv_value = quote[field_name]
        if iv_value is None:
            flags.append(missing_flag)
        elif iv_value <= 0 or iv_value > 500:
            flags.append(invalid_flag)

    return sorted(set(flag for flag in flags if flag in BLOCKING_QUALITY_FLAGS))


def _get_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "codex-option-research/0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"http {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ValueError(f"network error: {exc.reason}") from exc


def _parse_option_metadata(instrument_name: str | None) -> dict[str, Any]:
    if not instrument_name:
        raise ValueError("missing instrument_name")
    parts = instrument_name.split("-")
    if len(parts) < 4:
        raise ValueError(f"unexpected option instrument format: {instrument_name}")
    expiry_token = parts[1].upper()
    day = int(expiry_token[:2])
    month = _MONTHS[expiry_token[2:5]]
    year = 2000 + int(expiry_token[5:])
    option_type = {"C": "call", "P": "put"}.get(parts[3].upper(), "unknown")
    return {
        "base_currency": parts[0],
        "expiry_date": datetime(year, month, day, tzinfo=timezone.utc)
        .date()
        .isoformat(),
        "strike": _to_number(parts[2]),
        "option_type": option_type,
    }


def _looks_like_option(instrument_name: str | None) -> bool:
    if not instrument_name:
        return False
    parts = instrument_name.split("-")
    return len(parts) >= 4 and parts[3] in {"C", "P"}


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _to_number(value)
        if number is not None:
            return number
    return None


def _average_if_numbers(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round((left + right) / 2, 6)


def _normalize_exchange_greeks(payload: Any) -> dict[str, float] | None:
    if not isinstance(payload, dict):
        return None
    normalized = {}
    for field_name in ("delta", "gamma", "theta", "vega"):
        value = _to_number(payload.get(field_name))
        if value is not None:
            normalized[field_name] = value
    return normalized or None
