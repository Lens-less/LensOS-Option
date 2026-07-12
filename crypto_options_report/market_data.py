"""Deribit option-chain snapshot tracing and quality evaluation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .storage import atomic_write_json

DEFAULT_DERIBIT_BASE_URL = "https://www.deribit.com"
ALLOWED_DERIBIT_BASE_URLS = frozenset(
    {
        "https://www.deribit.com",
        "https://test.deribit.com",
    }
)
DEFAULT_QUALITY_LIMITS = {
    "market_data_max_age_sec": 60,
    "stale_quote_max_sec": 120,
    "min_valid_quotes_per_expiry": 8,
    "max_bad_quote_ratio_per_expiry": 0.25,
    "max_spread_ratio": 0.50,
}
HTTP_MAX_INSTRUMENT_LIMIT = 50
INSTRUMENT_RE = re.compile(
    r"^(?P<base>[A-Z0-9]+)-(?P<day>\d{1,2})(?P<month>[A-Z]{3})(?P<year>\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<option>[CP])$"
)

PUBLIC_FEED_CONTRACTS = {
    "option_chain": "required",
    "ticker": "required",
    "order_book": "not_implemented",
    "vol_index": "required",
    "funding_basis": "not_implemented",
    "index_spot": "not_implemented",
    "events": "not_implemented",
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
        "MISSING_SETTLEMENT_CURRENCY",
        "MISSING_CANONICAL_METADATA",
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


def resolve_snapshot_fixture_path(
    path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> Path:
    """Resolve a snapshot fixture path, optionally confining it to allowed roots."""
    fixture_path = Path(path).expanduser()
    if not fixture_path.is_absolute():
        fixture_path = (Path.cwd() / fixture_path).resolve()
    else:
        fixture_path = fixture_path.resolve()

    if allowed_roots is not None:
        roots = [Path(root).expanduser().resolve() for root in allowed_roots]
        if not any(_is_relative_to(fixture_path, root) for root in roots):
            raise ValueError("snapshot_fixture path escapes allowed fixture roots")
    return fixture_path


def default_http_fixture_roots() -> list[Path]:
    """Default roots for HTTP-served snapshot fixtures (repo-local only)."""
    package_root = Path(__file__).resolve().parents[1]
    return [
        package_root / "tests" / "fixtures",
        package_root / "crypto_options_report",
    ]


def load_snapshot_fixture(
    path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    fixture_path = resolve_snapshot_fixture_path(path, allowed_roots=allowed_roots)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if "rows" not in payload:
        raise ValueError("snapshot fixture is missing rows")
    payload.setdefault("source", f"fixture:{fixture_path.name}")
    payload.setdefault("currency", "BTC")
    if "captured_at" not in payload:
        raise ValueError("snapshot fixture is missing captured_at")
    return payload


def validate_deribit_base_url(base_url: str) -> str:
    """Allow only known Deribit public HTTPS endpoints (anti-SSRF)."""
    normalized = (base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("deribit_base_url must be an https URL from the allowlist")
    candidate = f"{parsed.scheme}://{parsed.netloc}"
    if candidate not in ALLOWED_DERIBIT_BASE_URLS:
        raise ValueError("deribit_base_url is not in the allowlist")
    return candidate


def load_public_replay_fixture(
    path: str | Path,
    *,
    scenario: str,
) -> dict[str, Any]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios") or {}
    if scenario not in scenarios:
        raise ValueError(f"public replay scenario {scenario!r} not found in {fixture_path}")

    scenario_payload = scenarios[scenario]
    if "snapshot" in scenario_payload:
        snapshot = json.loads(json.dumps(scenario_payload["snapshot"]))
    else:
        base_path = Path(payload["base_snapshot"])
        if not base_path.is_absolute():
            base_path = fixture_path.parent / base_path
        snapshot = load_snapshot_fixture(base_path)

    if "rows" in scenario_payload:
        snapshot["rows"] = json.loads(json.dumps(scenario_payload["rows"]))
    if "captured_at" in scenario_payload:
        snapshot["captured_at"] = scenario_payload["captured_at"]
    if "fetch_errors" in scenario_payload:
        snapshot["fetch_errors"] = list(scenario_payload["fetch_errors"])
    if "adapter_events" in scenario_payload:
        snapshot["adapter_events"] = list(scenario_payload["adapter_events"])
    if "feeds" in scenario_payload:
        snapshot["feeds"] = json.loads(json.dumps(scenario_payload["feeds"]))
    if "source" in scenario_payload:
        snapshot["source"] = scenario_payload["source"]

    for mutation in scenario_payload.get("mutations", []):
        _apply_public_replay_mutation(snapshot, mutation)

    snapshot.setdefault("source", f"public_replay:{scenario}")
    snapshot["replay_scenario"] = scenario
    return snapshot


def fetch_deribit_option_chain_snapshot(
    *,
    currency: str = "BTC",
    base_url: str = DEFAULT_DERIBIT_BASE_URL,
    instrument_limit: int | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Fetch a live public option-chain snapshot, always returning a structured payload.

    Network, JSON-RPC envelope, schema, and ticker failures are mapped into
    ``fetch_errors`` / ``adapter_events`` instead of raising, so research reports
    stay fail-closed rather than crashing mid-pipeline.
    """
    safe_base = validate_deribit_base_url(base_url)
    captured_at = utc_timestamp()
    errors: list[str] = []
    adapter_events: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    try:
        payload = _get_json(
            f"{safe_base}/api/v2/public/get_book_summary_by_currency",
            {"currency": currency, "kind": "option"},
            timeout=timeout,
        )
        result = _jsonrpc_result(payload, endpoint="get_book_summary_by_currency")
        if not isinstance(result, list):
            raise ValueError("book summary result must be a list")
        summaries = sorted(
            (
                row
                for row in result
                if isinstance(row, dict) and _looks_like_option(row.get("instrument_name"))
            ),
            key=lambda row: str(row.get("instrument_name") or ""),
        )
    except ValueError as exc:
        message = str(exc)
        errors.append(f"book_summary: {message}")
        adapter_events.append(_adapter_event_from_error(message))
    summaries = []

    if instrument_limit is not None:
        summaries = summaries[: max(0, int(instrument_limit))]

    tickers: dict[str, Any] = {}
    max_workers = max(1, min(8, len(summaries) or 1))
    if summaries:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _get_json,
                    f"{safe_base}/api/v2/public/ticker",
                    {"instrument_name": row["instrument_name"]},
                    timeout,
                ): row["instrument_name"]
                for row in summaries
            }
            for future in as_completed(futures):
                instrument_name = futures[future]
                try:
                    ticker_payload = future.result()
                    tickers[instrument_name] = _jsonrpc_result(
                        ticker_payload,
                        endpoint=f"ticker:{instrument_name}",
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    errors.append(f"{instrument_name}: {exc}")

    instrument_meta: dict[str, dict[str, Any]] = {}
    if summaries:
        try:
            instrument_meta = _fetch_option_instrument_metadata(
                safe_base,
                currency=currency,
                timeout=timeout,
            )
        except (ValueError, TypeError, KeyError) as exc:
            message = f"instruments: {exc}"
            errors.append(message)
            adapter_events.append(_adapter_event_from_error(message))

    rows = []
    for row in summaries:
        instrument_name = row.get("instrument_name")
        summary = dict(row)
        meta = instrument_meta.get(str(instrument_name) if instrument_name else "")
        if meta:
            # Only apply explicit settlement_currency from the venue instrument
            # registry. Never infer from quote_currency (would fake product units).
            if summary.get("settlement_currency") in (None, ""):
                if meta.get("settlement_currency"):
                    summary["settlement_currency"] = meta["settlement_currency"]
                    summary["settlement_currency_source"] = "explicit_settlement_currency"
            if summary.get("quote_currency") in (None, ""):
                if meta.get("quote_currency"):
                    summary["quote_currency"] = meta["quote_currency"]
            if summary.get("base_currency") in (None, ""):
                if meta.get("base_currency"):
                    summary["base_currency"] = meta["base_currency"]
            summary.setdefault("instrument_metadata_source", "public/get_instruments")
        rows.append(
            {
                "summary": summary,
                "ticker": tickers.get(row["instrument_name"]),
                "instrument_name": row["instrument_name"],
            }
        )

    feeds: dict[str, Any] = {}
    try:
        vol_index = _fetch_vol_index_feed(
            safe_base,
            currency=currency,
            timeout=timeout,
            captured_at=captured_at,
        )
        feeds["vol_index"] = vol_index
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        message = f"vol_index: {exc}"
        errors.append(message)
        adapter_events.append(_adapter_event_from_error(message))

    return {
        "captured_at": captured_at,
        "currency": currency,
        "source": f"deribit_live:{safe_base}",
        "rows": rows,
        "fetch_errors": errors,
        "adapter_events": adapter_events,
        "feeds": feeds,
        "instrument_metadata_count": len(instrument_meta),
    }


def write_snapshot_fixture(path: str | Path, snapshot: dict[str, Any]) -> Path:
    """Persist a market snapshot JSON for reproducible offline analysis."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    else:
        target = target.resolve()
    payload = dict(snapshot)
    payload.setdefault("captured_at", utc_timestamp())
    payload.setdefault("source", payload.get("source") or "snapshot_write")
    return atomic_write_json(target, payload)


def build_market_data_status(
    snapshot: dict[str, Any],
    *,
    now_ms: int | None = None,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    normalized = normalize_market_snapshot(snapshot, now_ms=now_ms, limits=limits)
    gate = evaluate_market_data_quality(normalized, limits=limits)
    response_contract = _public_response_contract(normalized)
    feed_coverage = _feed_coverage(normalized)
    return {
        "status": "validated" if gate["passed"] else "blocked",
        "validated": gate["passed"],
        "source": normalized["source"],
        "reason_code": None if gate["passed"] else "MARKET_DATA_QUALITY_FAIL",
        "snapshot_captured_at": normalized["captured_at"],
        "market_data_age_sec": normalized["snapshot_age_sec"],
        "quality_gate": gate,
        "public_response_contract": response_contract,
        "feed_coverage": feed_coverage,
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
        "adapter_events": list(snapshot.get("adapter_events", [])),
        "feeds": dict(snapshot.get("feeds") or {}),
        "replay_scenario": snapshot.get("replay_scenario"),
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
    response_contract = _public_response_contract(normalized_snapshot)
    if not quotes:
        overall_reason_codes.append("EMPTY_PUBLIC_RESPONSE")
    for event in normalized_snapshot.get("adapter_events", []):
        event_class = str(event.get("class") or "")
        if event_class == "rate_limit":
            overall_reason_codes.append("PUBLIC_RATE_LIMIT_RETRYABLE")
        elif event_class == "transient_network":
            overall_reason_codes.append("PUBLIC_NETWORK_RETRYABLE")
        elif event_class == "schema_drift":
            overall_reason_codes.append("PUBLIC_SCHEMA_DRIFT_MALFORMED")
    if response_contract["response_classes"]["schema_drift"]:
        overall_reason_codes.append("PUBLIC_SCHEMA_DRIFT_MALFORMED")
        vol_index_status = response_contract["endpoints"]["vol_index"]
        if vol_index_status["status"] != "available":
            overall_reason_codes.append("REQUIRED_FEED_MISSING")
            overall_reason_codes.append(vol_index_status["reason_code"])
    if normalized_snapshot.get("fetch_errors"):
        overall_reason_codes.append("PUBLIC_FETCH_ERRORS_PRESENT")

    feed_coverage = _feed_coverage(normalized_snapshot)
    missing_required = list(feed_coverage.get("missing_required_feeds") or [])
    if missing_required:
        overall_reason_codes.append("REQUIRED_FEED_MISSING")
        vol_status = (response_contract.get("endpoints") or {}).get("vol_index") or {}
        vol_reason = vol_status.get("reason_code")
        if vol_reason and vol_reason not in overall_reason_codes:
            overall_reason_codes.append(vol_reason)

    fetch_errors = list(normalized_snapshot.get("fetch_errors") or [])
    if fetch_errors:
        overall_reason_codes.append("PUBLIC_FETCH_ERRORS_PRESENT")

    for expiry_date in sorted(quotes_by_expiry):
        expiry_quotes = quotes_by_expiry[expiry_date]
        invalid_quotes = [q for q in expiry_quotes if q["quality_status"] != "valid"]
        invalid_quote_flags = sorted(
            {
                flag
                for quote in invalid_quotes
                for flag in quote.get("quality_flags", [])
            }
        )
        valid_quotes = len(expiry_quotes) - len(invalid_quotes)
        bad_quote_ratio = (
            len(invalid_quotes) / len(expiry_quotes) if expiry_quotes else 1.0
        )
        stale_quotes = sum("STALE_QUOTE" in q["quality_flags"] for q in expiry_quotes)
        spread_sanity_failures = sum(
            any(flag in SPREAD_SANITY_FLAGS for flag in q["quality_flags"])
            for q in expiry_quotes
        )
        duplicate_instruments = _duplicate_count(
            q["instrument_name"] for q in expiry_quotes
        )
        duplicate_strikes = _duplicate_count(
            (q["strike"], q["option_type"]) for q in expiry_quotes
        )
        reason_codes: list[str] = []
        if valid_quotes < normalized_limits["min_valid_quotes_per_expiry"]:
            reason_codes.append("INSUFFICIENT_VALID_QUOTES")
        if bad_quote_ratio > normalized_limits["max_bad_quote_ratio_per_expiry"]:
            reason_codes.append("BAD_QUOTE_RATIO_EXCEEDED")
        if spread_sanity_failures:
            reason_codes.append("SPREAD_SANITY_FAILED")
        if duplicate_instruments or duplicate_strikes:
            reason_codes.append("DUPLICATE_INSTRUMENT_OR_STRIKE")
        reason_codes.extend(
            flag for flag in invalid_quote_flags if flag not in reason_codes
        )
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
                "duplicate_instruments": duplicate_instruments,
                "duplicate_strikes": duplicate_strikes,
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
        "sample_canonical_metadata": [
            quote["canonical_metadata"] for quote in quotes[: min(len(quotes), 5)]
        ],
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
    parse_error: str | None = None
    try:
        metadata = _parse_option_metadata(instrument_name)
    except ValueError as exc:
        parse_error = str(exc)
        metadata = {
            "base_currency": summary.get("base_currency") or "BTC",
            "expiry_date": "1970-01-01",
            "strike": None,
            "option_type": "unknown",
        }
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
        "quote_currency": summary.get("quote_currency"),
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
    quote["canonical_metadata"] = _canonical_metadata(
        instrument_name=instrument_name,
        quote=quote,
        summary=summary,
        metadata=metadata,
    )
    flags = _quality_flags(quote, limits)
    if parse_error:
        flags = sorted(set(flags).union({"MISSING_CANONICAL_METADATA", "INSTRUMENT_PARSE_FAILED"}))
    quote["quality_flags"] = flags
    quote["quality_status"] = "valid" if not flags else "invalid"
    if parse_error:
        quote["parse_error"] = parse_error
    return quote


def _public_response_contract(normalized_snapshot: dict[str, Any]) -> dict[str, Any]:
    quotes = normalized_snapshot["quotes"]
    ticker_missing = sum(quote["depth"] is None for quote in quotes)
    duplicate_instruments = _duplicate_count(quote["instrument_name"] for quote in quotes)
    duplicate_strikes = _duplicate_count(
        (quote["expiry_date"], quote["strike"], quote["option_type"]) for quote in quotes
    )
    malformed_quotes = sum(quote["quality_status"] != "valid" for quote in quotes)
    event_classes = {
        str(event.get("class") or "")
        for event in normalized_snapshot.get("adapter_events", [])
    }
    vol_index_status = _vol_index_status(normalized_snapshot)
    response_classes = {
        "empty": len(quotes) == 0,
        "partial": bool(ticker_missing or normalized_snapshot.get("fetch_errors")),
        "duplicate": bool(duplicate_instruments or duplicate_strikes),
        "malformed": bool(malformed_quotes),
        "stale": normalized_snapshot["snapshot_age_sec"]
        > DEFAULT_QUALITY_LIMITS["market_data_max_age_sec"],
        "rate_limited": "rate_limit" in event_classes,
        "transient_network": "transient_network" in event_classes,
        "schema_drift": "schema_drift" in event_classes,
    }
    if response_classes["rate_limited"] or response_classes["transient_network"]:
        overall_status = "retryable"
    elif response_classes["schema_drift"] or (
        response_classes["malformed"] and not response_classes["partial"]
    ):
        overall_status = "malformed"
    elif response_classes["stale"]:
        overall_status = "stale"
    elif response_classes["empty"] or response_classes["duplicate"] or response_classes["partial"]:
        overall_status = "blocked"
    else:
        overall_status = "pass"
    return {
        "source": normalized_snapshot["source"],
        "replay_scenario": normalized_snapshot.get("replay_scenario"),
        "overall_status": overall_status,
        "credential_required": False,
        "network_required_for_tests": False,
        "endpoints": {
            "book_summary": {
                "status": "available" if quotes else "missing",
                "rows": len(quotes),
            },
            "ticker": {
                "status": "available" if ticker_missing == 0 else "partial",
                "missing_rows": ticker_missing,
            },
            "vol_index": vol_index_status,
        },
        "response_classes": response_classes,
        "duplicate_instruments": duplicate_instruments,
        "duplicate_strikes": duplicate_strikes,
        "fetch_errors": list(normalized_snapshot.get("fetch_errors", [])),
        "adapter_events": list(normalized_snapshot.get("adapter_events", [])),
    }


def _feed_coverage(normalized_snapshot: dict[str, Any]) -> dict[str, Any]:
    response_contract = _public_response_contract(normalized_snapshot)
    ticker_status = response_contract["endpoints"]["ticker"]["status"]
    feeds = {}
    for name, requirement in PUBLIC_FEED_CONTRACTS.items():
        if name == "option_chain":
            status = "available" if normalized_snapshot["quotes"] else "missing"
        elif name == "ticker":
            status = ticker_status
        elif name == "vol_index":
            status = response_contract["endpoints"]["vol_index"]["status"]
        else:
            status = "missing"
        feeds[name] = {
            "requirement": requirement,
            "status": status,
            "freshness_status": "fresh"
            if normalized_snapshot["snapshot_age_sec"]
            <= DEFAULT_QUALITY_LIMITS["market_data_max_age_sec"]
            else "stale",
        }
    return {
        "feeds": feeds,
        "missing_feeds": [
            name
            for name, item in feeds.items()
            if item["requirement"] == "not_implemented"
            or (
                item["requirement"] == "required"
                and item["status"] != "available"
            )
        ],
        "missing_required_feeds": [
            name
            for name, item in feeds.items()
            if item["requirement"] == "required" and item["status"] != "available"
        ],
        "remaining_out_of_scope_feeds": [
            name
            for name, item in feeds.items()
            if item["requirement"] == "not_implemented"
        ],
        "readiness_contribution": "research_only_partial_public_graph",
    }


def _vol_index_status(normalized_snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = (
        (normalized_snapshot.get("feeds") or {}).get("vol_index")
        or normalized_snapshot.get("vol_index")
        or {}
    )
    if not payload:
        return {
            "status": "missing",
            "required_fields": ["index_name", "currency", "timestamp", "volatility"],
            "reason_code": "VOL_INDEX_MISSING",
        }

    required_fields = ["index_name", "currency", "timestamp", "volatility"]
    missing_fields = [field for field in required_fields if payload.get(field) in (None, "")]
    if missing_fields:
        return {
            "status": "malformed",
            "required_fields": required_fields,
            "missing_fields": missing_fields,
            "reason_code": "VOL_INDEX_MALFORMED",
        }

    currency = str(payload.get("currency")).upper()
    if currency != str(normalized_snapshot.get("currency", "BTC")).upper():
        return {
            "status": "misaligned",
            "required_fields": required_fields,
            "reason_code": "VOL_INDEX_CURRENCY_MISALIGNED",
            "currency": currency,
        }

    try:
        timestamp_ms = parse_timestamp_ms(payload.get("timestamp"))
    except (TypeError, ValueError):
        return {
            "status": "malformed",
            "required_fields": required_fields,
            "reason_code": "VOL_INDEX_TIMESTAMP_MALFORMED",
        }

    age_sec = round(
        max(0, normalized_snapshot["captured_at_ms"] - timestamp_ms) / 1000,
        3,
    )
    volatility = _to_number(payload.get("volatility"))
    if volatility is None or volatility <= 0:
        return {
            "status": "malformed",
            "required_fields": required_fields,
            "reason_code": "VOL_INDEX_VALUE_MALFORMED",
        }
    if age_sec > DEFAULT_QUALITY_LIMITS["market_data_max_age_sec"]:
        return {
            "status": "stale",
            "required_fields": required_fields,
            "age_sec": age_sec,
            "reason_code": "VOL_INDEX_STALE",
        }
    return {
        "status": "available",
        "required_fields": required_fields,
        "age_sec": age_sec,
        "index_name": str(payload.get("index_name")),
        "currency": currency,
        "volatility": volatility,
    }


def _canonical_metadata(
    *,
    instrument_name: str | None,
    quote: dict[str, Any],
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    base_currency = quote["base_currency"]
    quote_currency = quote["quote_currency"]
    settlement_currency = summary.get("settlement_currency")
    return {
        "instrument_name": instrument_name,
        "venue": "DERIBIT",
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "settlement_currency_source": (
            "explicit_settlement_currency"
            if summary.get("settlement_currency")
            else "missing"
        ),
        "expiry_date": metadata["expiry_date"],
        "strike_price": metadata["strike"],
        "option_type": metadata["option_type"],
        "underlying_index": summary.get("underlying_index", f"{base_currency}_USD"),
        "underlying_index_source": (
            "explicit_underlying_index"
            if summary.get("underlying_index")
            else "default_registry"
        ),
        "timestamp_semantics": "exchange_milliseconds",
    }


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

    metadata = quote.get("canonical_metadata") or {}
    if not metadata.get("instrument_name") or metadata.get("strike_price") is None:
        flags.append("MISSING_CANONICAL_METADATA")
    if (
        not metadata.get("settlement_currency")
        or metadata.get("settlement_currency_source") != "explicit_settlement_currency"
    ):
        flags.append("MISSING_SETTLEMENT_CURRENCY")

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
    match = INSTRUMENT_RE.match(str(instrument_name).upper())
    if match is None:
        raise ValueError(f"unexpected option instrument format: {instrument_name}")
    month_token = match.group("month")
    if month_token not in _MONTHS:
        raise ValueError(f"unexpected option instrument month: {instrument_name}")
    day = int(match.group("day"))
    month = _MONTHS[month_token]
    year = 2000 + int(match.group("year"))
    option_type = {"C": "call", "P": "put"}.get(match.group("option"), "unknown")
    try:
        expiry_date = datetime(year, month, day, tzinfo=timezone.utc).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid option instrument expiry: {instrument_name}") from exc
    return {
        "base_currency": match.group("base"),
        "expiry_date": expiry_date,
        "strike": _to_number(match.group("strike")),
        "option_type": option_type,
    }


def _fetch_option_instrument_metadata(
    base_url: str,
    *,
    currency: str,
    timeout: int,
) -> dict[str, dict[str, Any]]:
    payload = _get_json(
        f"{base_url}/api/v2/public/get_instruments",
        {"currency": currency, "kind": "option", "expired": "false"},
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint="get_instruments")
    if not isinstance(result, list):
        raise ValueError("get_instruments result must be a list")
    metadata: dict[str, dict[str, Any]] = {}
    for item in result:
        if not isinstance(item, dict):
            continue
        name = item.get("instrument_name")
        if not name or not _looks_like_option(str(name)):
            continue
        # Explicit venue settlement only — never quote_currency substitution.
        settlement_currency = item.get("settlement_currency")
        if settlement_currency in (None, ""):
            settlement_currency = None
        metadata[str(name)] = {
            "settlement_currency": settlement_currency,
            "quote_currency": item.get("quote_currency"),
            "base_currency": item.get("base_currency") or currency,
            "instrument_type": item.get("instrument_type") or item.get("kind"),
            "settlement_currency_source": (
                "explicit_settlement_currency"
                if settlement_currency is not None
                else "missing"
            ),
            "raw_settlement_period": item.get("settlement_period"),
        }
    return metadata


def _coerce_vol_index_timestamp_ms(value: Any) -> int:
    """Return an integer DVOL timestamp without truncating malformed JSON numbers."""
    if isinstance(value, bool) or (
        isinstance(value, float) and (not isfinite(value) or not value.is_integer())
    ):
        raise ValueError("volatility index timestamp is not integer-like")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("volatility index timestamp is not integer-like") from exc


def _fetch_vol_index_feed(
    base_url: str,
    *,
    currency: str,
    timeout: int,
    captured_at: str,
) -> dict[str, Any]:
    """Fetch latest DVOL-like volatility index point for required feed coverage."""
    captured_ms = parse_timestamp_ms(captured_at)
    # Prefer recent 2h window at 1h resolution; Deribit returns OHLC rows.
    start_ms = max(0, captured_ms - 2 * 60 * 60 * 1000)
    payload = _get_json(
        f"{base_url}/api/v2/public/get_volatility_index_data",
        {
            "currency": currency,
            "resolution": 3600,
            "start_timestamp": start_ms,
            "end_timestamp": captured_ms,
        },
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint="get_volatility_index_data")
    data_rows = result.get("data") if isinstance(result, dict) else result
    if not isinstance(data_rows, list) or not data_rows:
        raise ValueError("empty volatility index data")
    last = data_rows[-1]
    timestamp_ms: int
    volatility: float | None
    # Typical row: [timestamp_ms, open, high, low, close]
    if isinstance(last, (list, tuple)) and len(last) >= 5:
        if last[0] is None:
            raise ValueError("volatility index row missing timestamp")
        timestamp_ms = _coerce_vol_index_timestamp_ms(last[0])
        volatility = _to_number(last[4])
    elif isinstance(last, dict):
        raw_ts = last.get("timestamp")
        if raw_ts is None:
            raw_ts = last.get("t")
        if raw_ts is None:
            raise ValueError("volatility index dict row missing timestamp")
        timestamp_ms = _coerce_vol_index_timestamp_ms(raw_ts)
        volatility = _to_number(
            last.get("close")
            or last.get("volatility")
            or last.get("value")
        )
    else:
        raise ValueError("unrecognized volatility index row shape")
    if volatility is None or volatility <= 0:
        raise ValueError("invalid volatility index value")
    # Deribit DVOL is often percent points (e.g. 55.2); fixtures use 0-1 fractions.
    normalized = volatility / 100.0 if volatility > 5.0 else float(volatility)
    index_name = f"{currency} DVOL"
    try:
        timestamp = (
            datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("volatility index timestamp is out of range") from exc
    return {
        "index_name": index_name,
        "currency": currency,
        "timestamp": timestamp,
        "volatility": normalized,
        "source_endpoint": "public/get_volatility_index_data",
        "raw_close": volatility,
    }


def _jsonrpc_result(payload: Any, *, endpoint: str) -> Any:
    if not isinstance(payload, dict):
        raise ValueError(f"{endpoint}: response is not a JSON object")
    if payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or error.get("data") or "rpc error"
            raise ValueError(f"{endpoint}: rpc error {code}: {message}")
        raise ValueError(f"{endpoint}: rpc error {error}")
    if "result" not in payload:
        raise ValueError(f"{endpoint}: missing result field")
    return payload["result"]


def _adapter_event_from_error(message: str) -> dict[str, Any]:
    lowered = message.lower()
    if "429" in lowered or "rate" in lowered:
        event_class = "rate_limit"
    elif "network" in lowered or "timed out" in lowered or "timeout" in lowered:
        event_class = "transient_network"
    else:
        event_class = "schema_drift"
    return {
        "class": event_class,
        "message": message,
        "source": "live_public_deribit",
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _looks_like_option(instrument_name: str | None) -> bool:
    if not instrument_name:
        return False
    parts = instrument_name.split("-")
    return len(parts) >= 4 and parts[3] in {"C", "P"}


def _duplicate_count(values: Iterable[Any]) -> int:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return len(duplicates)


def _apply_public_replay_mutation(snapshot: dict[str, Any], mutation: dict[str, Any]) -> None:
    op = mutation.get("op")
    if op == "duplicate_row":
        rows = snapshot.setdefault("rows", [])
        source_index = int(mutation.get("source_index", 0))
        rows.append(json.loads(json.dumps(rows[source_index])))
        return
    if op == "set":
        _set_nested(snapshot, list(mutation["path"]), mutation.get("value"))
        return
    if op == "delete":
        _delete_nested(snapshot, list(mutation["path"]))
        return
    raise ValueError(f"unsupported public replay mutation op {op!r}")


def _set_nested(payload: dict[str, Any] | list[Any], path: list[Any], value: Any) -> None:
    target: Any = payload
    for key in path[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
    last = path[-1]
    if isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value


def _delete_nested(payload: dict[str, Any] | list[Any], path: list[Any]) -> None:
    target: Any = payload
    for key in path[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
    last = path[-1]
    if isinstance(target, list):
        del target[int(last)]
    else:
        target.pop(last, None)


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
