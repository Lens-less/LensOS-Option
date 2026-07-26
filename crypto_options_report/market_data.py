"""Deribit option-chain snapshot tracing and quality evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .sidecar_auth import (
    ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
    MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
    MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
    SidecarAuthUnavailable,
    require_separate_key_file,
    sign_mapping,
    verify_mapping,
)
from .storage import (
    atomic_write_json,
    read_json_object_from_regular_file,
    read_json_object_from_stream,
)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def urlopen(request: Request, *, timeout: int):
    """Open one public-market request without following redirects."""
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)

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
# Public ticker requests per snapshot. A two-sided universe needs
# `min_valid_quotes_per_expiry` quotes on each side of an expiry, so the budget
# has to cover 2 x that per expiry before more than one expiry fits. At 20 the
# collector could fill exactly one side of one expiry, which is why the put
# tables stayed empty on live chains.
DEFAULT_TICKER_REQUEST_BUDGET = 96
HTTP_MAX_INSTRUMENT_LIMIT = DEFAULT_TICKER_REQUEST_BUDGET
MAX_MARKET_HTTP_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_MARKET_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_MARKET_TRUST_STATE_BYTES = 1024 * 1024
RESEARCH_DTE_RANGE_DAYS = (7, 35)
# Collection deliberately does *not* reach below the research window, and the
# reason is measured rather than assumed.
#
# Only three listed expiries sit inside 7-35 days at any time and new weeklies
# enter at roughly one a week, so a validation sample counted in settled expiry
# cohorts accumulates slowly. Deribit's daily expiries at one to five days look
# like an eightfold acceleration, and collecting them was tried.
#
# They do not survive the data-quality gate. On a live chain the short-dated
# band failed with INVALID_BID_IV, INSUFFICIENT_VALID_QUOTES and
# BAD_QUOTE_RATIO_EXCEEDED while the 7-35 band passed cleanly - and because the
# gate is evaluated over the whole snapshot, mixing them in blocked the healthy
# research-window quotes too. Widening the band would therefore have cost the
# report its own data to buy validation cohorts that the gate rejects anyway.
COLLECTION_DTE_RANGE_DAYS = RESEARCH_DTE_RANGE_DAYS
# Out-of-the-money bands, mirrored around spot. The put band is the reflection
# of the call band, not a copy of it: reusing the call band for puts selects
# deep in-the-money strikes.
RESEARCH_CALL_MONEYNESS_BAND = (1.0, 1.3)
RESEARCH_PUT_MONEYNESS_BAND = (0.7, 1.0)
RESEARCH_TARGET_CALL_MONEYNESS = 1.1
RESEARCH_TARGET_PUT_MONEYNESS = 0.9
# Deribit returns DVOL as one-minute candles. The row timestamp is the candle
# boundary, so a healthy latest row can be slightly older than 60 seconds at
# the minute rollover. Keep this stricter than quote staleness (120s) while
# avoiding a predictable red/green flicker every minute.
VOL_INDEX_MAX_AGE_SEC = 90
INSTRUMENT_RE = re.compile(
    r"^(?P<base>[A-Z0-9]+)-(?P<day>\d{1,2})(?P<month>[A-Z]{3})(?P<year>\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<option>[CP])$"
)

PUBLIC_FEED_CONTRACTS = {
    "option_chain": "required",
    "ticker": "required",
    # These feeds are mandatory for a live Deribit snapshot.  Older checked-in
    # fixtures predate the graph and remain replayable, but cannot contribute a
    # complete-feed or trust-promotion claim.
    "order_book": "required_live",
    "vol_index": "required",
    "funding_basis": "required_live",
    "index_spot": "required_live",
    "events": "required_live",
}

PUBLIC_FEED_MAX_AGE_SEC = 120
PUBLIC_FEED_FUTURE_TOLERANCE_SEC = 5
TRUST_MINIMUM_CONSECUTIVE_PASSES = 6
TRUST_MINIMUM_OBSERVATION_SECONDS = 60
TRUST_MAXIMUM_PASS_GAP_SECONDS = 60
SNAPSHOT_TRUST_STATE_SCHEMA_VERSION = "market_snapshot_trust_state.v2"
_BOUND_TRUST_EVIDENCE_KEY = "_bound_trust_evidence"


class _BoundTrustEvidence(dict[str, Any]):
    """Evidence admitted only after a separate state file binds it to a snapshot."""

    def __init__(self, value: dict[str, Any], *, snapshot_sha256: str) -> None:
        super().__init__(value)
        self.snapshot_sha256 = snapshot_sha256

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
        "FUTURE_QUOTE_TIMESTAMP",
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
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_timestamp_ms(value: str | int | float | None) -> int:
    if value is None:
        raise ValueError("missing timestamp")
    if isinstance(value, bool):
        raise ValueError("timestamp must not be a boolean")
    if isinstance(value, (int, float)):
        if not isfinite(float(value)):
            raise ValueError("timestamp must be finite")
        return int(value)
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string or epoch milliseconds")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


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
    auth_key_file: str | Path | None = None,
) -> dict[str, Any]:
    fixture_path = resolve_snapshot_fixture_path(path, allowed_roots=allowed_roots)
    payload = read_json_object_from_regular_file(
        fixture_path,
        max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
        description="snapshot fixture",
    )
    # Trust is never accepted from the snapshot payload itself.  Only a
    # separately persisted state record that hashes this exact payload may
    # attach the private marker consumed by normalize_market_snapshot().
    payload.pop("trust_evidence", None)
    payload.pop(_BOUND_TRUST_EVIDENCE_KEY, None)
    if "rows" not in payload:
        raise ValueError("snapshot fixture is missing rows")
    payload.setdefault("source", f"fixture:{fixture_path.name}")
    payload.setdefault("currency", "BTC")
    if "captured_at" not in payload:
        raise ValueError("snapshot fixture is missing captured_at")
    bound_evidence = _load_bound_snapshot_trust(
        fixture_path,
        payload,
        auth_key_file=auth_key_file,
    )
    if bound_evidence:
        payload[_BOUND_TRUST_EVIDENCE_KEY] = _BoundTrustEvidence(
            bound_evidence,
            snapshot_sha256=snapshot_payload_sha256(payload),
        )
    return payload


def snapshot_trust_state_path(snapshot_path: str | Path) -> Path:
    snapshot = resolve_snapshot_fixture_path(snapshot_path)
    return snapshot.with_name(f"{snapshot.name}.trust.json")


def snapshot_payload_sha256(snapshot: dict[str, Any]) -> str:
    payload = _snapshot_payload_without_trust(snapshot)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_snapshot_trust_state(
    snapshot_path: str | Path,
    trust_evidence: dict[str, Any],
    *,
    expected_snapshot: dict[str, Any],
    auth_key_file: str | Path | None = None,
) -> Path:
    snapshot_file = resolve_snapshot_fixture_path(snapshot_path)
    payload = read_json_object_from_regular_file(
        snapshot_file,
        max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
        description="snapshot fixture",
    )
    payload = _snapshot_payload_without_trust(payload)
    expected_payload = _snapshot_payload_without_trust(expected_snapshot)
    payload_digest = snapshot_payload_sha256(payload)
    if payload_digest != snapshot_payload_sha256(expected_payload):
        raise ValueError("snapshot changed before trust state could be bound")
    unsigned_state = {
        "schema_version": SNAPSHOT_TRUST_STATE_SCHEMA_VERSION,
        "snapshot_sha256": payload_digest,
        "snapshot_captured_at": expected_payload.get("captured_at"),
        "source_identity": _trust_source_identity(expected_payload),
        "trust_evidence": dict(trust_evidence),
        "research_only": True,
    }
    configured_key = _configured_market_key_file(auth_key_file)
    separated_key = require_separate_key_file(
        snapshot_file,
        snapshot_trust_state_path(snapshot_file),
        key_file=configured_key,
        key_env=MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
        conflicting_key_env=ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
    )
    state = {
        **unsigned_state,
        "hmac_sha256": sign_mapping(
            unsigned_state,
            domain=MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
            key_file=separated_key,
        ),
    }
    return atomic_write_json(snapshot_trust_state_path(snapshot_file), state)


def bound_snapshot_trust_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    evidence = snapshot.get(_BOUND_TRUST_EVIDENCE_KEY)
    if not isinstance(evidence, _BoundTrustEvidence):
        return {}
    try:
        if evidence.snapshot_sha256 != snapshot_payload_sha256(snapshot):
            return {}
    except (TypeError, ValueError):
        return {}
    return dict(evidence)


def _load_bound_snapshot_trust(
    snapshot_path: Path,
    snapshot: dict[str, Any],
    *,
    auth_key_file: str | Path | None = None,
) -> dict[str, Any]:
    try:
        state = read_json_object_from_regular_file(
            snapshot_trust_state_path(snapshot_path),
            max_bytes=MAX_MARKET_TRUST_STATE_BYTES,
            description="market snapshot trust state",
        )
        evidence = state.get("trust_evidence")
        expected_identity = _trust_source_identity(snapshot)
        unsigned_state = {
            key: state.get(key)
            for key in (
                "schema_version",
                "snapshot_sha256",
                "snapshot_captured_at",
                "source_identity",
                "trust_evidence",
                "research_only",
            )
        }
        configured_key = _configured_market_key_file(auth_key_file)
        separated_key = require_separate_key_file(
            snapshot_path,
            snapshot_trust_state_path(snapshot_path),
            key_file=configured_key,
            key_env=MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
            conflicting_key_env=ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
        )
        valid = (
            set(state)
            == {
                "schema_version",
                "snapshot_sha256",
                "snapshot_captured_at",
                "source_identity",
                "trust_evidence",
                "research_only",
                "hmac_sha256",
            }
            and state.get("schema_version") == SNAPSHOT_TRUST_STATE_SCHEMA_VERSION
            and state.get("snapshot_sha256") == snapshot_payload_sha256(snapshot)
            and state.get("snapshot_captured_at") == snapshot.get("captured_at")
            and state.get("source_identity") == expected_identity
            and isinstance(evidence, dict)
            and evidence.get("schema_version") == "market_trust_evidence.v1"
            and evidence.get("source_identity") == expected_identity
            and verify_mapping(
                unsigned_state,
                state.get("hmac_sha256"),
                domain=MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
                key_file=separated_key,
            )
        )
        return dict(evidence) if valid else {}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _snapshot_payload_without_trust(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = dict(snapshot)
    payload.pop("trust_evidence", None)
    payload.pop(_BOUND_TRUST_EVIDENCE_KEY, None)
    return payload


def _configured_market_key_file(
    auth_key_file: str | Path | None,
) -> Path:
    configured = auth_key_file or os.environ.get(MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV)
    if not configured:
        raise SidecarAuthUnavailable(
            f"{MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV} must reference an operator-owned key file"
        )
    return Path(configured).expanduser().resolve()


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


def validate_ticker_request_limit(instrument_limit: int | None) -> int:
    """Return the explicit bounded public-ticker request budget."""
    if instrument_limit is None:
        return DEFAULT_TICKER_REQUEST_BUDGET
    if (
        isinstance(instrument_limit, bool)
        or not isinstance(instrument_limit, int)
        or not 1 <= instrument_limit <= DEFAULT_TICKER_REQUEST_BUDGET
    ):
        raise ValueError(
            "instrument_limit must be between 1 and "
            f"{DEFAULT_TICKER_REQUEST_BUDGET}"
        )
    return instrument_limit


def load_public_replay_fixture(
    path: str | Path,
    *,
    scenario: str,
) -> dict[str, Any]:
    fixture_path = Path(path)
    payload = read_json_object_from_regular_file(
        fixture_path,
        max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
        description="public replay fixture",
    )
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
    include_feed_graph: bool = False,
) -> dict[str, Any]:
    """Fetch a live public option-chain snapshot, always returning a structured payload.

    Network, JSON-RPC envelope, schema, and ticker failures are mapped into
    ``fetch_errors`` / ``adapter_events`` instead of raising, so research reports
    stay fail-closed rather than crashing mid-pipeline.
    """
    safe_base = validate_deribit_base_url(base_url)
    requested_limit = validate_ticker_request_limit(instrument_limit)
    collection_started_monotonic = monotonic()
    collection_started_at = utc_timestamp()
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

    upstream_instrument_count = len(summaries)
    summaries, selection_policy = _select_research_summaries(
        summaries,
        captured_at=collection_started_at,
        instrument_limit=requested_limit,
    )

    tickers: dict[str, Any] = {}
    instrument_meta: dict[str, dict[str, Any]] = {}
    feeds: dict[str, Any] = {}
    max_workers = max(1, min(8, len(summaries) or 1))
    # Instrument metadata and DVOL are independent of individual ticker calls.
    # Run them beside the bounded eight-worker ticker pool instead of adding two
    # serial network round trips to the snapshot critical path.
    with ThreadPoolExecutor(max_workers=2) as auxiliary_pool:
        instrument_meta_future = (
            auxiliary_pool.submit(
                _fetch_option_instrument_metadata,
                safe_base,
                currency=currency,
                timeout=timeout,
            )
            if summaries
            else None
        )
        vol_index_future = auxiliary_pool.submit(
            _fetch_vol_index_feed,
            safe_base,
            currency=currency,
            timeout=timeout,
            captured_at=collection_started_at,
        )

        if summaries:
            with ThreadPoolExecutor(max_workers=max_workers) as ticker_pool:
                futures = {
                    ticker_pool.submit(
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
                        message = f"{instrument_name}: {exc}"
                        errors.append(message)
                        event = _adapter_event_from_error(message)
                        event.update(
                            {
                                "endpoint": "public/ticker",
                                "instrument_name": instrument_name,
                                "retryable": event["class"]
                                in {"rate_limit", "transient_network"},
                            }
                        )
                        adapter_events.append(event)

        if instrument_meta_future is not None:
            try:
                instrument_meta = instrument_meta_future.result()
            except (ValueError, TypeError, KeyError) as exc:
                message = f"instruments: {exc}"
                errors.append(message)
                adapter_events.append(_adapter_event_from_error(message))

        try:
            feeds["vol_index"] = vol_index_future.result()
        except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
            message = f"vol_index: {exc}"
            errors.append(message)
            adapter_events.append(_adapter_event_from_error(message))

    if include_feed_graph and summaries:
        graph_feeds, graph_errors, graph_events = _fetch_public_feed_graph(
            safe_base,
            currency=currency,
            selected_instrument_names=[str(row["instrument_name"]) for row in summaries],
            timeout=timeout,
            observed_at=collection_started_at,
        )
        feeds.update(graph_feeds)
        errors.extend(graph_errors)
        adapter_events.extend(graph_events)

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
                # Deribit ticker IV fields are percentage-point values. Persist
                # the venue unit explicitly so downstream surface code never
                # guesses from magnitude on a live snapshot.
                "iv_unit": "percent_points",
            }
        )

    captured_at = utc_timestamp()
    collection_duration_ms = max(
        0,
        round((monotonic() - collection_started_monotonic) * 1000),
    )

    return {
        "captured_at": captured_at,
        "collection_started_at": collection_started_at,
        "collection_duration_ms": collection_duration_ms,
        "currency": currency,
        "source": f"deribit_live:{safe_base}",
        "rows": rows,
        "fetch_errors": errors,
        "adapter_events": adapter_events,
        "feeds": feeds,
        "instrument_metadata_count": len(instrument_meta),
        "upstream_instrument_count": upstream_instrument_count,
        "selected_instrument_count": len(summaries),
        "selection_policy": selection_policy,
    }


def _select_research_summaries(
    summaries: list[dict[str, Any]],
    *,
    captured_at: str,
    instrument_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested_limit = validate_ticker_request_limit(instrument_limit)
    effective_limit = requested_limit
    min_per_expiry = int(DEFAULT_QUALITY_LIMITS["min_valid_quotes_per_expiry"])
    captured_date = datetime.fromtimestamp(
        parse_timestamp_ms(captured_at) / 1000,
        tz=UTC,
    ).date()

    ranked: list[dict[str, Any]] = []
    for summary in summaries:
        instrument_name = str(summary.get("instrument_name") or "")
        try:
            metadata = _parse_option_metadata(instrument_name)
            expiry_date = str(metadata["expiry_date"])
            dte_days = (datetime.fromisoformat(expiry_date).date() - captured_date).days
            option_type = str(metadata["option_type"])
            underlying_price = _to_number(summary.get("underlying_price"))
            strike = _to_number(metadata.get("strike"))
            moneyness = (
                strike / underlying_price
                if strike is not None
                and underlying_price is not None
                and underlying_price > 0
                else None
            )
        except (TypeError, ValueError, KeyError):
            expiry_date = "unknown"
            dte_days = None
            option_type = "unknown"
            moneyness = None
        in_research_dte = (
            dte_days is not None
            and RESEARCH_DTE_RANGE_DAYS[0] <= dte_days <= RESEARCH_DTE_RANGE_DAYS[1]
        )
        in_target_dte = (
            dte_days is not None
            and COLLECTION_DTE_RANGE_DAYS[0] <= dte_days <= COLLECTION_DTE_RANGE_DAYS[1]
        )
        liquid = _summary_has_preferred_liquidity(summary)
        ranked.append(
            {
                "summary": summary,
                "instrument_name": instrument_name,
                "expiry_date": expiry_date,
                "dte_days": dte_days,
                "option_type": option_type,
                "moneyness": moneyness,
                "in_target_dte": in_target_dte,
                "in_research_dte": in_research_dte,
                "preferred_liquidity": liquid,
            }
        )

    # Stratified by expiry *and* option type. Selecting calls only was coherent
    # while the analysis universe was call-only; with put verticals and condors
    # in the universe it silently starved the put side, so a two-sided chain
    # would have produced a one-sided report with nothing saying why.
    preferred_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in ranked:
        if (
            item["in_target_dte"]
            and item["option_type"] in {"call", "put"}
            and item["preferred_liquidity"]
        ):
            preferred_groups.setdefault(
                (item["expiry_date"], item["option_type"]), []
            ).append(item)
    for rows in preferred_groups.values():
        rows.sort(key=_research_summary_sort_key)

    # Research-window expiries are filled first. The wider collection band must
    # never starve the band the product actually screens: a short-dated group
    # taking budget from a 20-day one would trade the report's own data for
    # validation cohorts.
    qualifying_groups = [
        (key, rows)
        for key, rows in sorted(
            preferred_groups.items(),
            key=lambda item: (
                not any(row["in_research_dte"] for row in item[1]),
                item[0],
            ),
        )
        if len(rows) >= min_per_expiry
    ]
    selected_items: list[dict[str, Any]] = []
    fallback_used = True
    if effective_limit >= min_per_expiry and qualifying_groups:
        group_limit = max(1, effective_limit // min_per_expiry)
        chosen_groups = qualifying_groups[:group_limit]
        for _, rows in chosen_groups:
            selected_items.extend(rows[:min_per_expiry])
        next_indexes = [min_per_expiry for _ in chosen_groups]
        while len(selected_items) < effective_limit:
            added = False
            for index, (_, rows) in enumerate(chosen_groups):
                next_index = next_indexes[index]
                if next_index >= len(rows):
                    continue
                selected_items.append(rows[next_index])
                next_indexes[index] += 1
                added = True
                if len(selected_items) >= effective_limit:
                    break
            if not added:
                break
        fallback_used = False
    elif effective_limit:
        selected_items = sorted(
            ranked,
            key=lambda item: (
                not item["in_target_dte"],
                item["option_type"] not in {"call", "put"},
                not item["preferred_liquidity"],
                abs((item["dte_days"] if item["dte_days"] is not None else 10_000) - 21),
                item["expiry_date"],
                *_research_summary_sort_key(item),
            ),
        )[:effective_limit]

    selected_per_expiry: dict[str, int] = {}
    for item in selected_items:
        expiry = str(item["expiry_date"])
        selected_per_expiry[expiry] = selected_per_expiry.get(expiry, 0) + 1
    selected = [item["summary"] for item in selected_items]
    return selected, {
        "name": "research_candidate_stratified_v1",
        "requested_instrument_limit": requested_limit,
        "ticker_request_budget": DEFAULT_TICKER_REQUEST_BUDGET,
        "effective_limit": effective_limit,
        "preferred_dte_days": list(RESEARCH_DTE_RANGE_DAYS),
        "collection_dte_days": list(COLLECTION_DTE_RANGE_DAYS),
        "research_window_filled_first": True,
        "preferred_option_types": ["call", "put"],
        "stratification": "expiry_and_option_type",
        "preferred_call_moneyness": list(RESEARCH_CALL_MONEYNESS_BAND),
        "target_call_moneyness": RESEARCH_TARGET_CALL_MONEYNESS,
        "preferred_put_moneyness": list(RESEARCH_PUT_MONEYNESS_BAND),
        "target_put_moneyness": RESEARCH_TARGET_PUT_MONEYNESS,
        "min_quotes_per_expiry": min_per_expiry,
        "max_spread_ratio": DEFAULT_QUALITY_LIMITS["max_spread_ratio"],
        "fallback_used": fallback_used,
        "selected_per_expiry": selected_per_expiry,
    }


def _fetch_public_feed_graph(
    base_url: str,
    *,
    currency: str,
    selected_instrument_names: list[str],
    timeout: int,
    observed_at: str,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """Collect independent live feed families with bounded HTTP requests.

    ``events`` intentionally means exchange-native lock/health state.  This
    collector does not invent or proxy a macro-economic calendar.
    """
    representative = selected_instrument_names[0]
    collectors = {
        "index_spot": lambda: _fetch_index_spot_feed(
            base_url,
            currency=currency,
            timeout=timeout,
            observed_at=observed_at,
        ),
        "funding_basis": lambda: _fetch_funding_basis_feed(
            base_url,
            currency=currency,
            timeout=timeout,
            observed_at=observed_at,
        ),
        "order_book": lambda: _fetch_order_book_feed(
            base_url,
            instrument_name=representative,
            selected_instrument_count=len(selected_instrument_names),
            timeout=timeout,
            observed_at=observed_at,
        ),
        "events": lambda: _fetch_exchange_events_feed(
            base_url,
            currency=currency,
            timeout=timeout,
            observed_at=observed_at,
        ),
    }
    feeds: dict[str, Any] = {}
    errors: list[str] = []
    adapter_events: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(collectors)) as pool:
        futures = {pool.submit(collector): name for name, collector in collectors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                feeds[name] = future.result()
            except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
                message = f"{name}: {exc}"
                errors.append(message)
                event = _adapter_event_from_error(message)
                event.update(
                    {
                        "endpoint": _feed_source_endpoint(name),
                        "feed": name,
                        "retryable": event["class"]
                        in {"rate_limit", "transient_network"},
                    }
                )
                adapter_events.append(event)
    return feeds, errors, adapter_events


def _fetch_index_spot_feed(
    base_url: str,
    *,
    currency: str,
    timeout: int,
    observed_at: str,
) -> dict[str, Any]:
    index_name = f"{currency.lower()}_usd"
    payload = _get_json(
        f"{base_url}/api/v2/public/get_index_price",
        {"index_name": index_name},
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint="get_index_price")
    if not isinstance(result, dict):
        raise ValueError("get_index_price result must be an object")
    index_price = _to_number(result.get("index_price"))
    if index_price is None or index_price <= 0:
        raise ValueError("get_index_price returned invalid index_price")
    estimated_delivery = _to_number(result.get("estimated_delivery_price"))
    return {
        "index_name": index_name,
        "currency": currency,
        "index_price": index_price,
        "price": index_price,
        "estimated_delivery_price": estimated_delivery,
        "observed_at": observed_at,
        "as_of": observed_at,
        "source_endpoint": "public/get_index_price",
        "scope": index_name,
        "provenance": _feed_provenance(
            endpoint="public/get_index_price",
            observed_at=observed_at,
        ),
    }


def _fetch_funding_basis_feed(
    base_url: str,
    *,
    currency: str,
    timeout: int,
    observed_at: str,
) -> dict[str, Any]:
    instrument_name = f"{currency}-PERPETUAL"
    end_ms = parse_timestamp_ms(observed_at)
    start_ms = max(0, end_ms - 60 * 60 * 1000)
    funding_payload = _get_json(
        f"{base_url}/api/v2/public/get_funding_rate_value",
        {
            "instrument_name": instrument_name,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
        },
        timeout=timeout,
    )
    funding_result = _jsonrpc_result(
        funding_payload,
        endpoint="get_funding_rate_value",
    )
    funding_rate = _to_number(funding_result)
    if funding_rate is None:
        raise ValueError("get_funding_rate_value returned a non-numeric result")

    ticker_payload = _get_json(
        f"{base_url}/api/v2/public/ticker",
        {"instrument_name": instrument_name},
        timeout=timeout,
    )
    ticker = _jsonrpc_result(ticker_payload, endpoint=f"ticker:{instrument_name}")
    if not isinstance(ticker, dict):
        raise ValueError("perpetual ticker result must be an object")
    mark_price = _to_number(ticker.get("mark_price"))
    index_price = _to_number(ticker.get("index_price"))
    basis_rate = (
        (mark_price - index_price) / index_price
        if mark_price is not None and index_price is not None and index_price > 0
        else None
    )
    return {
        "instrument_name": instrument_name,
        "currency": currency,
        "funding_rate": funding_rate,
        "basis_rate": round(basis_rate, 10) if basis_rate is not None else None,
        "index_price": index_price,
        "mark_price": mark_price,
        "perpetual_mark_price": mark_price,
        "current_funding": _to_number(ticker.get("current_funding")),
        "funding_8h": _to_number(ticker.get("funding_8h")),
        "window_start": _timestamp_from_ms(start_ms),
        "window_end": _timestamp_from_ms(end_ms),
        "observed_at": observed_at,
        "as_of": observed_at,
        "source_endpoint": "public/get_funding_rate_value+public/ticker",
        "scope": "one_hour_realized_and_current_perpetual_basis",
        "provenance": _feed_provenance(
            endpoint="public/get_funding_rate_value+public/ticker",
            observed_at=observed_at,
        ),
    }


def _fetch_order_book_feed(
    base_url: str,
    *,
    instrument_name: str,
    selected_instrument_count: int,
    timeout: int,
    observed_at: str,
) -> dict[str, Any]:
    payload = _get_json(
        f"{base_url}/api/v2/public/get_order_book",
        {"instrument_name": instrument_name, "depth": 5},
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint=f"get_order_book:{instrument_name}")
    if not isinstance(result, dict):
        raise ValueError("get_order_book result must be an object")
    if str(result.get("instrument_name") or "") != instrument_name:
        raise ValueError("get_order_book instrument_name mismatch")
    timestamp_ms = _coerce_exchange_timestamp_ms(result.get("timestamp"))
    bids = _normalize_book_levels(result.get("bids"), side="bids")
    asks = _normalize_book_levels(result.get("asks"), side="asks")
    return {
        "instrument_name": instrument_name,
        "timestamp": _timestamp_from_ms(timestamp_ms),
        "observed_at": observed_at,
        "as_of": _timestamp_from_ms(timestamp_ms),
        "state": str(result.get("state") or "unknown"),
        "change_id": result.get("change_id"),
        "index_price": _to_number(result.get("index_price")),
        "mark_price": _to_number(result.get("mark_price")),
        "best_bid_price": _to_number(result.get("best_bid_price")),
        "best_bid_amount": _to_number(result.get("best_bid_amount")),
        "best_ask_price": _to_number(result.get("best_ask_price")),
        "best_ask_amount": _to_number(result.get("best_ask_amount")),
        "bids": bids,
        "asks": asks,
        "source_endpoint": "public/get_order_book",
        "scope": {
            "kind": "research_sample",
            "depth": 5,
            "sampled_instrument_count": 1,
            "selected_instrument_count": selected_instrument_count,
            "instrument_names": [instrument_name],
        },
        "provenance": _feed_provenance(
            endpoint="public/get_order_book",
            observed_at=observed_at,
        ),
    }


def _fetch_exchange_events_feed(
    base_url: str,
    *,
    currency: str,
    timeout: int,
    observed_at: str,
) -> dict[str, Any]:
    payload = _get_json(
        f"{base_url}/api/v2/public/status",
        {},
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint="status")
    if not isinstance(result, dict) or "locked" not in result:
        raise ValueError("status result must contain locked")
    locked_currencies = result.get("locked_currencies") or []
    locked_indices = result.get("locked_indices") or []
    if not isinstance(locked_currencies, list) or not isinstance(locked_indices, list):
        raise ValueError("status lock collections must be lists")
    return {
        "currency": currency,
        "observed_at": observed_at,
        "as_of": observed_at,
        "exchange_locked": result.get("locked"),
        "locked_currencies": [str(item) for item in locked_currencies],
        "locked_indices": [str(item) for item in locked_indices],
        # Explicitly empty: public/status is exchange health, not a macro feed.
        "macro_events": [],
        "source_endpoint": "public/status",
        "scope": "exchange_native_only",
        "provenance": _feed_provenance(
            endpoint="public/status",
            observed_at=observed_at,
        ),
    }


def _normalize_book_levels(value: Any, *, side: str) -> list[list[float]]:
    if not isinstance(value, list):
        raise ValueError(f"get_order_book {side} must be a list")
    levels: list[list[float]] = []
    for level in value[:5]:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            raise ValueError(f"get_order_book {side} contains malformed level")
        price = _to_number(level[0])
        amount = _to_number(level[1])
        if price is None or amount is None or price < 0 or amount < 0:
            raise ValueError(f"get_order_book {side} contains invalid level")
        levels.append([price, amount])
    return levels


def _coerce_exchange_timestamp_ms(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("exchange timestamp is not integer-like")
    if isinstance(value, float) and (not isfinite(value) or not value.is_integer()):
        raise ValueError("exchange timestamp is not integer-like")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("exchange timestamp is not integer-like") from exc


def _timestamp_from_ms(value: int) -> str:
    try:
        return (
            datetime.fromtimestamp(value / 1000, tz=UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("exchange timestamp is out of range") from exc


def _feed_provenance(*, endpoint: str, observed_at: str) -> dict[str, Any]:
    return {
        "venue": "DERIBIT",
        "transport": "HTTPS_JSON_RPC",
        "source_endpoint": endpoint,
        "observed_at": observed_at,
        "schema_version": "deribit_public_feed.v1",
    }


def _feed_source_endpoint(name: str) -> str:
    return {
        "index_spot": "public/get_index_price",
        "funding_basis": "public/get_funding_rate_value+public/ticker",
        "order_book": "public/get_order_book",
        "events": "public/status",
    }.get(name, "public/unknown")


def _summary_has_preferred_liquidity(summary: dict[str, Any]) -> bool:
    bid = _to_number(summary.get("bid_price"))
    ask = _to_number(summary.get("ask_price"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return False
    mid = (bid + ask) / 2
    if mid <= 0:
        return False
    return (ask - bid) / mid <= DEFAULT_QUALITY_LIMITS["max_spread_ratio"]


def _preferred_moneyness_band(option_type: str) -> tuple[float, float, float]:
    """Out-of-the-money band and target, mirrored for puts.

    The band used to be call-only. Applying `1.0 <= moneyness <= 1.3` to a put
    selects deep in-the-money puts, which are the illiquid, wide-quoted end of
    the chain and the opposite of what the research window wants.
    """
    if option_type == "put":
        return (RESEARCH_PUT_MONEYNESS_BAND[0], RESEARCH_PUT_MONEYNESS_BAND[1], RESEARCH_TARGET_PUT_MONEYNESS)
    return (RESEARCH_CALL_MONEYNESS_BAND[0], RESEARCH_CALL_MONEYNESS_BAND[1], RESEARCH_TARGET_CALL_MONEYNESS)


def _research_summary_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    moneyness = item.get("moneyness")
    low, high, target = _preferred_moneyness_band(str(item.get("option_type") or "call"))
    in_preferred_band = isinstance(moneyness, (int, float)) and low <= moneyness <= high
    bid = _to_number(item["summary"].get("bid_price"))
    ask = _to_number(item["summary"].get("ask_price"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_ratio = (
        (ask - bid) / mid
        if bid is not None and ask is not None and mid is not None and mid > 0
        else float("inf")
    )
    open_interest = _to_number(item["summary"].get("open_interest")) or 0.0
    return (
        not in_preferred_band,
        abs(moneyness - target) if isinstance(moneyness, (int, float)) else float("inf"),
        spread_ratio,
        -open_interest,
        item["instrument_name"],
    )


def _snapshot_collection_scope(
    snapshot: dict[str, Any],
    *,
    row_count: int,
) -> dict[str, Any]:
    upstream_count = _nonnegative_int(
        snapshot.get("upstream_instrument_count"),
        default=row_count,
    )
    selected_count = _nonnegative_int(
        snapshot.get("selected_instrument_count"),
        default=row_count,
    )
    upstream_count = max(upstream_count, selected_count)
    if upstream_count == 0:
        scope = "empty_snapshot"
    elif selected_count < upstream_count:
        scope = "research_sample"
    else:
        scope = "full_snapshot"
    policy = snapshot.get("selection_policy")
    return {
        "scope": scope,
        "upstream_instrument_count": upstream_count,
        "selected_instrument_count": selected_count,
        "coverage_ratio": round(selected_count / upstream_count, 4)
        if upstream_count
        else 0.0,
        "selection_policy": dict(policy) if isinstance(policy, dict) else {},
    }


def _nonnegative_int(value: Any, *, default: int) -> int:
    if value is None or isinstance(value, bool):
        return max(0, int(default))
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return max(0, int(default))


def write_snapshot_fixture(path: str | Path, snapshot: dict[str, Any]) -> Path:
    """Persist a market snapshot JSON for reproducible offline analysis."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    else:
        target = target.resolve()
    payload = _snapshot_payload_without_trust(snapshot)
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
    trust_evidence = _verified_trust_evidence(
        normalized,
        quality_gate=gate,
        feed_coverage=feed_coverage,
    )
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
        "trust_evidence": trust_evidence,
        "collection_scope": dict(normalized["collection_scope"]),
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
    rows = list(snapshot["rows"])
    quotes = [
        _normalize_quote_row(row, snapshot, evaluation_now_ms, normalized_limits)
        for row in rows
    ]
    snapshot_age_sec, snapshot_future_sec = _timestamp_age_seconds(
        reference_ms=evaluation_now_ms,
        observed_ms=captured_at_ms,
    )
    return {
        "captured_at": snapshot["captured_at"],
        "captured_at_ms": captured_at_ms,
        "snapshot_age_sec": snapshot_age_sec,
        "snapshot_future_sec": snapshot_future_sec,
        "source": snapshot.get("source", "fixture"),
        "currency": snapshot.get("currency", "BTC"),
        "quotes": quotes,
        "fetch_errors": list(snapshot.get("fetch_errors", [])),
        "adapter_events": list(snapshot.get("adapter_events", [])),
        "feeds": dict(snapshot.get("feeds") or {}),
        "trust_evidence": bound_snapshot_trust_evidence(snapshot),
        "replay_scenario": snapshot.get("replay_scenario"),
        "collection_scope": _snapshot_collection_scope(snapshot, row_count=len(rows)),
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
    if normalized_snapshot.get("snapshot_future_sec", 0) > PUBLIC_FEED_FUTURE_TOLERANCE_SEC:
        overall_reason_codes.append("FUTURE_SNAPSHOT_TIMESTAMP")
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
        if duplicate_instruments or duplicate_strikes:
            reason_codes.append("DUPLICATE_INSTRUMENT_OR_STRIKE")
        threshold_failed = (
            valid_quotes < normalized_limits["min_valid_quotes_per_expiry"]
            or bad_quote_ratio > normalized_limits["max_bad_quote_ratio_per_expiry"]
        )
        if threshold_failed:
            if spread_sanity_failures:
                reason_codes.append("SPREAD_SANITY_FAILED")
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
                "observed_quality_flags": invalid_quote_flags,
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
    # Deribit's option ticker reports `underlying_price` as the forward for that
    # expiry and `index_price` as spot. They are not interchangeable: the basis
    # between them runs to double-digit annualized rates in a trending market,
    # and pricing an option off spot while calling it a forward makes every call
    # on the chain look systematically rich. Falling back to spot is still
    # allowed — a fitted smile beats no smile — but the substitution is recorded
    # so a consumer can see the assumption instead of inheriting it silently.
    forward_price = _first_number(
        ticker.get("underlying_price"),
        summary.get("underlying_price"),
    )
    index_price = _first_number(
        ticker.get("index_price"),
        summary.get("index_price"),
    )
    if forward_price is not None:
        underlying_price = forward_price
        underlying_price_source = "option_forward"
    elif index_price is not None:
        underlying_price = index_price
        underlying_price_source = "index_spot_fallback"
    else:
        underlying_price = None
        underlying_price_source = "unavailable"
    forward_basis = (
        round((forward_price / index_price) - 1.0, 8)
        if forward_price is not None
        and index_price is not None
        and index_price > 0
        else None
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
    quote_age_sec, quote_future_sec = _timestamp_age_seconds(
        reference_ms=evaluation_now_ms,
        observed_ms=int(timestamp_ms),
    )
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
        "forward_price": forward_price,
        "index_price": index_price,
        "underlying_price_source": underlying_price_source,
        "forward_basis": forward_basis,
        "open_interest": _first_number(
            ticker.get("open_interest"),
            summary.get("open_interest"),
        ),
        "best_bid_amount": best_bid_amount,
        "best_ask_amount": best_ask_amount,
        "depth": depth,
        "quote_age_sec": quote_age_sec,
        "quote_future_sec": quote_future_sec,
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
    quarantined_quotes = sum(quote["quality_status"] != "valid" for quote in quotes)
    schema_malformed_quotes = sum(
        bool(quote.get("parse_error"))
        or "MISSING_CANONICAL_METADATA" in quote.get("quality_flags", [])
        for quote in quotes
    )
    event_classes = {
        str(event.get("class") or "")
        for event in normalized_snapshot.get("adapter_events", [])
    }
    vol_index_status = _vol_index_status(normalized_snapshot)
    response_classes = {
        "empty": len(quotes) == 0,
        "partial": bool(ticker_missing or normalized_snapshot.get("fetch_errors")),
        "duplicate": bool(duplicate_instruments or duplicate_strikes),
        "malformed": bool(schema_malformed_quotes),
        "quality_quarantined": bool(quarantined_quotes),
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
        "quarantined_quotes": quarantined_quotes,
        "fetch_errors": list(normalized_snapshot.get("fetch_errors", [])),
        "adapter_events": list(normalized_snapshot.get("adapter_events", [])),
        "collection_scope": dict(normalized_snapshot["collection_scope"]),
    }


def _feed_coverage(normalized_snapshot: dict[str, Any]) -> dict[str, Any]:
    response_contract = _public_response_contract(normalized_snapshot)
    ticker_status = response_contract["endpoints"]["ticker"]["status"]
    source_is_live = _is_live_deribit_source(normalized_snapshot.get("source"))
    feeds: dict[str, Any] = {}
    for name, contract_requirement in PUBLIC_FEED_CONTRACTS.items():
        if name == "option_chain":
            status = "available" if normalized_snapshot["quotes"] else "missing"
            details: dict[str, Any] = {}
        elif name == "ticker":
            status = ticker_status
            details = {}
        elif name == "vol_index":
            vol_status = response_contract["endpoints"]["vol_index"]
            status = vol_status["status"]
            details = dict(vol_status)
            vol_payload = (normalized_snapshot.get("feeds") or {}).get("vol_index") or {}
            if (
                source_is_live
                and status == "available"
                and not _valid_live_provenance(vol_payload)
            ):
                status = "malformed"
                details = _malformed_feed("VOL_INDEX_PROVENANCE_MISSING")
        else:
            details = _live_feed_status(normalized_snapshot, name)
            status = str(details["status"])
        required_now = contract_requirement == "required" or (
            contract_requirement == "required_live" and source_is_live
        )
        if contract_requirement == "required_live" and not source_is_live:
            requirement = "out_of_scope_for_fixture"
        else:
            requirement = "required" if required_now else contract_requirement
        freshness_status = details.get("freshness_status")
        if freshness_status is None:
            if status == "stale":
                freshness_status = "stale"
            elif status == "available":
                freshness_status = (
                    "fresh"
                    if normalized_snapshot["snapshot_age_sec"]
                    <= DEFAULT_QUALITY_LIMITS["market_data_max_age_sec"]
                    else "stale"
                )
            else:
                freshness_status = "unknown"
        feeds[name] = {
            "requirement": requirement,
            "contract_requirement": contract_requirement,
            "status": status,
            "freshness_status": freshness_status,
            "scope": details.get("scope"),
            "source_endpoint": details.get("source_endpoint"),
            "reason_code": details.get("reason_code"),
        }
    missing_feeds = [
        name
        for name, item in feeds.items()
        if item["contract_requirement"] in {"required", "required_live"}
        and item["status"] != "available"
    ]
    missing_required = [
        name
        for name, item in feeds.items()
        if item["requirement"] == "required" and item["status"] != "available"
    ]
    remaining_out_of_scope = [
        name
        for name, item in feeds.items()
        if item["requirement"] == "out_of_scope_for_fixture"
        and item["status"] != "available"
    ]
    graph_complete = not missing_feeds
    return {
        "feeds": feeds,
        "missing_feeds": missing_feeds,
        "missing_required_feeds": missing_required,
        "remaining_out_of_scope_feeds": remaining_out_of_scope,
        "graph_complete": graph_complete,
        "scope": "live_required" if source_is_live else "fixture_replay_compatible",
        "readiness_contribution": (
            "research_only_complete_public_graph"
            if graph_complete
            else "research_only_partial_public_graph"
        ),
    }


def _live_feed_status(
    normalized_snapshot: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    payload = (normalized_snapshot.get("feeds") or {}).get(name)
    if not isinstance(payload, dict) or not payload:
        return {
            "status": "missing",
            "freshness_status": "unknown",
            "reason_code": f"{name.upper()}_MISSING",
        }
    if _is_live_deribit_source(normalized_snapshot.get("source")) and not _valid_live_provenance(
        payload
    ):
        return _malformed_feed(f"{name.upper()}_PROVENANCE_MISSING")

    validators = {
        "index_spot": _validate_index_spot_feed,
        "funding_basis": _validate_funding_basis_feed,
        "order_book": _validate_order_book_feed,
        "events": _validate_events_feed,
    }
    validator = validators.get(name)
    if validator is None:
        return {
            "status": "malformed",
            "freshness_status": "unknown",
            "reason_code": "UNKNOWN_FEED_CONTRACT",
        }
    result = validator(payload, normalized_snapshot)
    result.setdefault("scope", payload.get("scope"))
    result.setdefault("source_endpoint", payload.get("source_endpoint"))
    return result


def _validate_index_spot_feed(
    payload: dict[str, Any],
    normalized_snapshot: dict[str, Any],
) -> dict[str, Any]:
    index_price = _to_number(payload.get("index_price", payload.get("price")))
    if (
        not payload.get("index_name")
        or str(payload.get("currency") or "").upper()
        != str(normalized_snapshot.get("currency") or "BTC").upper()
        or index_price is None
        or index_price <= 0
    ):
        return _malformed_feed("INDEX_SPOT_MALFORMED")
    return _timestamped_feed_status(
        payload,
        normalized_snapshot,
        timestamp_field="observed_at",
        stale_reason="INDEX_SPOT_STALE",
    )


def _validate_funding_basis_feed(
    payload: dict[str, Any],
    normalized_snapshot: dict[str, Any],
) -> dict[str, Any]:
    funding_rate = _to_number(payload.get("funding_rate"))
    basis_rate = _to_number(payload.get("basis_rate"))
    index_price = _to_number(payload.get("index_price"))
    mark_price = _to_number(
        payload.get("perpetual_mark_price", payload.get("mark_price"))
    )
    if (
        not payload.get("instrument_name")
        or funding_rate is None
        or basis_rate is None
        or index_price is None
        or index_price <= 0
        or mark_price is None
        or mark_price <= 0
    ):
        return _malformed_feed("FUNDING_BASIS_MALFORMED")
    return _timestamped_feed_status(
        payload,
        normalized_snapshot,
        timestamp_field="observed_at",
        stale_reason="FUNDING_BASIS_STALE",
    )


def _validate_order_book_feed(
    payload: dict[str, Any],
    normalized_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if (
        not payload.get("instrument_name")
        or not isinstance(payload.get("bids"), list)
        or not isinstance(payload.get("asks"), list)
        or payload.get("state") not in {
            "open",
            "settlement",
            "delivered",
            "inactive",
            "locked",
            "halted",
            "archivized",
        }
        or _safe_nonnegative_int(payload.get("change_id")) <= 0
    ):
        return _malformed_feed("ORDER_BOOK_MALFORMED")
    return _timestamped_feed_status(
        payload,
        normalized_snapshot,
        timestamp_field="timestamp",
        stale_reason="ORDER_BOOK_STALE",
    )


def _validate_events_feed(
    payload: dict[str, Any],
    normalized_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if (
        "exchange_locked" not in payload
        or not isinstance(payload.get("locked_currencies"), list)
        or not isinstance(payload.get("macro_events"), list)
        or payload.get("scope") != "exchange_native_only"
    ):
        return _malformed_feed("EVENTS_FEED_MALFORMED")
    # A locked exchange is valid evidence, not missing data.  The downstream
    # regime/risk gates decide that it blocks actions.
    return _timestamped_feed_status(
        payload,
        normalized_snapshot,
        timestamp_field="observed_at",
        stale_reason="EVENTS_FEED_STALE",
    )


def _timestamped_feed_status(
    payload: dict[str, Any],
    normalized_snapshot: dict[str, Any],
    *,
    timestamp_field: str,
    stale_reason: str,
) -> dict[str, Any]:
    timestamp = payload.get(timestamp_field) or payload.get("as_of")
    try:
        timestamp_ms = parse_timestamp_ms(timestamp)
    except (TypeError, ValueError, OverflowError):
        return _malformed_feed(stale_reason.replace("STALE", "TIMESTAMP_MALFORMED"))
    age_sec, future_sec = _timestamp_age_seconds(
        reference_ms=normalized_snapshot["captured_at_ms"],
        observed_ms=timestamp_ms,
    )
    if future_sec > PUBLIC_FEED_FUTURE_TOLERANCE_SEC:
        feed_name = stale_reason.removesuffix("_STALE")
        return {
            "status": "invalid",
            "freshness_status": "future",
            "future_by_sec": future_sec,
            "max_future_sec": PUBLIC_FEED_FUTURE_TOLERANCE_SEC,
            "reason_code": f"FUTURE_TIMESTAMP_{feed_name}",
        }
    if age_sec > PUBLIC_FEED_MAX_AGE_SEC:
        return {
            "status": "stale",
            "freshness_status": "stale",
            "age_sec": age_sec,
            "max_age_sec": PUBLIC_FEED_MAX_AGE_SEC,
            "reason_code": stale_reason,
        }
    return {
        "status": "available",
        "freshness_status": "fresh",
        "age_sec": age_sec,
        "max_age_sec": PUBLIC_FEED_MAX_AGE_SEC,
    }


def _malformed_feed(reason_code: str) -> dict[str, Any]:
    return {
        "status": "malformed",
        "freshness_status": "unknown",
        "reason_code": reason_code,
    }


def _timestamp_age_seconds(*, reference_ms: int, observed_ms: int) -> tuple[float, float]:
    delta_ms = reference_ms - observed_ms
    return (
        round(max(0, delta_ms) / 1000, 3),
        round(max(0, -delta_ms) / 1000, 3),
    )


def _is_live_deribit_source(value: Any) -> bool:
    return str(value or "").lower().startswith("deribit_live:")


def _valid_live_provenance(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    provenance = payload.get("provenance")
    return (
        isinstance(provenance, dict)
        and provenance.get("venue") == "DERIBIT"
        and provenance.get("transport") == "HTTPS_JSON_RPC"
        and str(provenance.get("source_endpoint") or "").startswith("public/")
        and bool(provenance.get("observed_at"))
    )


def advance_trust_evidence(
    snapshot: dict[str, Any],
    *,
    previous_snapshot: dict[str, Any] | None = None,
    minimum_consecutive_passes: int = TRUST_MINIMUM_CONSECUTIVE_PASSES,
    minimum_observation_seconds: int = TRUST_MINIMUM_OBSERVATION_SECONDS,
    maximum_pass_gap_seconds: int = TRUST_MAXIMUM_PASS_GAP_SECONDS,
) -> dict[str, Any]:
    """Advance durable live-snapshot evidence without opening any trade mode."""
    if (
        minimum_consecutive_passes < 1
        or minimum_observation_seconds < 0
        or maximum_pass_gap_seconds < 1
    ):
        raise ValueError("trust evidence thresholds must be non-negative")
    captured_at = str(snapshot.get("captured_at") or "")
    captured_ms = parse_timestamp_ms(captured_at)
    status = build_market_data_status(snapshot, now_ms=captured_ms)
    feed_coverage = status["feed_coverage"]
    source_identity = _trust_source_identity(snapshot)
    eligible = (
        status["validated"]
        and _is_live_deribit_source(snapshot.get("source"))
        and bool(feed_coverage.get("graph_complete"))
        and not snapshot.get("fetch_errors")
        and not snapshot.get("adapter_events")
    )

    previous_evidence = (
        dict((previous_snapshot or {}).get("trust_evidence") or {})
        if previous_snapshot
        else {}
    )
    previous_identity = str(previous_evidence.get("source_identity") or "")
    source_changed = bool(previous_identity and previous_identity != source_identity)
    previous_consecutive = _safe_nonnegative_int(
        previous_evidence.get("consecutive_passes")
    )
    continuity_broken = False
    if previous_consecutive > 0:
        try:
            previous_last_ms = parse_timestamp_ms(previous_evidence.get("last_pass_at"))
            pass_gap_ms = captured_ms - previous_last_ms
            continuity_broken = (
                pass_gap_ms < 0
                or pass_gap_ms > maximum_pass_gap_seconds * 1000
            )
        except (TypeError, ValueError, OverflowError):
            continuity_broken = True
    rolling_observations = _advance_rolling_observations(
        snapshot,
        previous_evidence=(
            {}
            if source_changed or continuity_broken
            else previous_evidence
        ),
        append_current=eligible,
    )

    if not eligible:
        reason_codes: list[str] = []
        if not status["validated"]:
            reason_codes.append("MARKET_DATA_QUALITY_FAIL")
        if not feed_coverage.get("graph_complete"):
            reason_codes.append("PUBLIC_FEED_GRAPH_INCOMPLETE")
        if snapshot.get("fetch_errors") or snapshot.get("adapter_events"):
            reason_codes.append("PUBLIC_COLLECTION_DISCONTINUITY")
        if not _is_live_deribit_source(snapshot.get("source")):
            reason_codes.append("LIVE_SOURCE_REQUIRED_FOR_TRUST")
        return _trust_evidence_payload(
            status="reset",
            consecutive_passes=0,
            minimum_consecutive_passes=minimum_consecutive_passes,
            first_pass_at=None,
            last_pass_at=captured_at or None,
            observation_seconds=0,
            minimum_observation_seconds=minimum_observation_seconds,
            reason_codes=reason_codes or ["TRUST_EVIDENCE_RESET"],
            feed_graph_complete=bool(feed_coverage.get("graph_complete")),
            source_identity=source_identity,
            rolling_observations=rolling_observations,
        )

    can_continue = (
        not source_changed
        and not continuity_broken
        and previous_evidence.get("status") in {"collecting", "promoted", "reset"}
        and previous_identity == source_identity
        and previous_consecutive > 0
    )
    if can_continue:
        first_pass_at = str(previous_evidence.get("first_pass_at") or captured_at)
        consecutive_passes = (
            _safe_nonnegative_int(previous_evidence.get("consecutive_passes")) + 1
        )
    else:
        first_pass_at = captured_at
        consecutive_passes = 1
    try:
        observation_seconds = max(
            0,
            int((captured_ms - parse_timestamp_ms(first_pass_at)) / 1000),
        )
    except (TypeError, ValueError, OverflowError):
        first_pass_at = captured_at
        consecutive_passes = 1
        observation_seconds = 0

    promoted = (
        consecutive_passes >= minimum_consecutive_passes
        and observation_seconds >= minimum_observation_seconds
    )
    reason_codes = []
    evidence_status = "promoted" if promoted else "collecting"
    if source_changed:
        evidence_status = "reset"
        reason_codes.append("TRUST_SOURCE_CHANGED")
    if continuity_broken:
        evidence_status = "reset"
        reason_codes.append("TRUST_PASS_GAP_EXCEEDED")
    if consecutive_passes < minimum_consecutive_passes:
        reason_codes.append("TRUST_CONSECUTIVE_PASSES_PENDING")
    if observation_seconds < minimum_observation_seconds:
        reason_codes.append("TRUST_OBSERVATION_WINDOW_PENDING")
    return _trust_evidence_payload(
        status=evidence_status,
        consecutive_passes=consecutive_passes,
        minimum_consecutive_passes=minimum_consecutive_passes,
        first_pass_at=first_pass_at,
        last_pass_at=captured_at,
        observation_seconds=observation_seconds,
        minimum_observation_seconds=minimum_observation_seconds,
        reason_codes=reason_codes,
        feed_graph_complete=True,
        source_identity=source_identity,
        rolling_observations=rolling_observations,
    )


def _verified_trust_evidence(
    normalized_snapshot: dict[str, Any],
    *,
    quality_gate: dict[str, Any],
    feed_coverage: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(normalized_snapshot.get("trust_evidence") or {})
    if not raw:
        return _trust_evidence_payload(
            status="collecting",
            consecutive_passes=0,
            minimum_consecutive_passes=TRUST_MINIMUM_CONSECUTIVE_PASSES,
            first_pass_at=None,
            last_pass_at=None,
            observation_seconds=0,
            minimum_observation_seconds=TRUST_MINIMUM_OBSERVATION_SECONDS,
            reason_codes=["TRUST_EVIDENCE_NOT_OBSERVED"],
            feed_graph_complete=bool(feed_coverage.get("graph_complete")),
            source_identity=_trust_source_identity(normalized_snapshot),
            rolling_observations=[],
        )

    consecutive = _safe_nonnegative_int(raw.get("consecutive_passes"))
    minimum_passes = max(
        TRUST_MINIMUM_CONSECUTIVE_PASSES,
        _safe_nonnegative_int(
            raw.get(
                "minimum_consecutive_passes",
                raw.get("required_consecutive_passes", TRUST_MINIMUM_CONSECUTIVE_PASSES),
            )
        ),
    )
    observation = _safe_nonnegative_int(
        raw.get("observation_seconds", raw.get("observation_sec"))
    )
    minimum_observation = max(
        TRUST_MINIMUM_OBSERVATION_SECONDS,
        _safe_nonnegative_int(
            raw.get(
                "minimum_observation_seconds",
                raw.get("required_observation_sec", TRUST_MINIMUM_OBSERVATION_SECONDS),
            )
        ),
    )
    claimed_status = str(raw.get("status") or "collecting")
    current_valid = (
        quality_gate.get("passed") is True
        and _is_live_deribit_source(normalized_snapshot.get("source"))
        and feed_coverage.get("graph_complete") is True
    )
    promotion_valid = (
        claimed_status == "promoted"
        and current_valid
        and consecutive >= minimum_passes
        and observation >= minimum_observation
        and raw.get("source_identity") == _trust_source_identity(normalized_snapshot)
    )
    if claimed_status == "promoted" and not promotion_valid:
        claimed_status = "reset"
        reason_codes = ["TRUST_EVIDENCE_CLAIM_INVALID"]
    else:
        if claimed_status not in {"collecting", "promoted", "reset"}:
            claimed_status = "reset"
            reason_codes = ["TRUST_EVIDENCE_SCHEMA_INVALID"]
        else:
            reason_codes = [str(item) for item in raw.get("reason_codes") or []]
    if not current_valid:
        claimed_status = "reset"
        if not feed_coverage.get("graph_complete"):
            reason_codes.append("PUBLIC_FEED_GRAPH_INCOMPLETE")
        if not quality_gate.get("passed"):
            reason_codes.append("MARKET_DATA_QUALITY_FAIL")
    if claimed_status != "promoted" and not reason_codes:
        reason_codes.append("TRUST_PROMOTION_PENDING")
    return _trust_evidence_payload(
        status=claimed_status,
        consecutive_passes=consecutive,
        minimum_consecutive_passes=minimum_passes,
        first_pass_at=raw.get("first_pass_at"),
        last_pass_at=raw.get("last_pass_at"),
        observation_seconds=observation,
        minimum_observation_seconds=minimum_observation,
        reason_codes=sorted(set(reason_codes)),
        feed_graph_complete=bool(feed_coverage.get("graph_complete")),
        source_identity=_trust_source_identity(normalized_snapshot),
        rolling_observations=_sanitize_rolling_observations(
            raw.get("rolling_observations", raw.get("rolling"))
        ),
    )


def _trust_evidence_payload(
    *,
    status: str,
    consecutive_passes: int,
    minimum_consecutive_passes: int,
    first_pass_at: Any,
    last_pass_at: Any,
    observation_seconds: int,
    minimum_observation_seconds: int,
    reason_codes: list[str],
    feed_graph_complete: bool,
    source_identity: str,
    rolling_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rolling = _sanitize_rolling_observations(rolling_observations)
    return {
        "schema_version": "market_trust_evidence.v1",
        "status": status,
        "consecutive_passes": consecutive_passes,
        "minimum_consecutive_passes": minimum_consecutive_passes,
        "first_pass_at": first_pass_at,
        "last_pass_at": last_pass_at,
        "observation_seconds": observation_seconds,
        "minimum_observation_seconds": minimum_observation_seconds,
        "reason_codes": sorted({str(item) for item in reason_codes if item}),
        "feed_graph_complete": bool(feed_graph_complete),
        "source_identity": source_identity,
        "rolling_observations": rolling,
        "rolling_observation_count": len(rolling),
        "minimum_rolling_observations": 20,
        "rolling_status": "ready" if len(rolling) >= 20 else "collecting",
        "research_only": True,
    }


def _trust_source_identity(snapshot: dict[str, Any]) -> str:
    return f"{snapshot.get('source') or 'missing'!s}|{str(snapshot.get('currency') or 'BTC').upper()}"


def _safe_nonnegative_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _advance_rolling_observations(
    snapshot: dict[str, Any],
    *,
    previous_evidence: dict[str, Any],
    append_current: bool,
) -> list[dict[str, Any]]:
    observations = _sanitize_rolling_observations(
        previous_evidence.get("rolling_observations", previous_evidence.get("rolling"))
    )
    if not append_current:
        return observations
    current = _rolling_observation_from_snapshot(snapshot)
    if current is None:
        return observations
    observations = [
        item for item in observations if item.get("observed_at") != current["observed_at"]
    ]
    observations.append(current)
    observations.sort(key=lambda item: str(item.get("observed_at") or ""))
    return observations[-288:]


def _rolling_observation_from_snapshot(
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    feeds = snapshot.get("feeds") or {}
    index_payload = feeds.get("index_spot") or {}
    vol_payload = feeds.get("vol_index") or {}
    funding_payload = feeds.get("funding_basis") or {}
    index_price = _to_number(
        index_payload.get("index_price", index_payload.get("price"))
    )
    dvol = _to_number(vol_payload.get("volatility"))
    funding_rate = _to_number(funding_payload.get("funding_rate"))
    observed_at = str(snapshot.get("captured_at") or "")
    if (
        not observed_at
        or index_price is None
        or index_price <= 0
        or dvol is None
        or dvol <= 0
        or funding_rate is None
    ):
        return None

    atm_candidates: list[tuple[float, float]] = []
    for row in snapshot.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker") or {}
        summary = row.get("summary") or row
        if not isinstance(ticker, dict) or not isinstance(summary, dict):
            continue
        mark_iv = _to_number(ticker.get("mark_iv"))
        underlying = _first_number(
            ticker.get("underlying_price"),
            summary.get("underlying_price"),
            index_price,
        )
        instrument_name = (
            row.get("instrument_name")
            or ticker.get("instrument_name")
            or summary.get("instrument_name")
        )
        try:
            strike = _to_number(_parse_option_metadata(instrument_name)["strike"])
        except (TypeError, ValueError, KeyError):
            continue
        normalized_iv = _canonical_fraction_iv(
            mark_iv,
            row.get("iv_unit"),
            ticker.get("iv_unit"),
            summary.get("iv_unit"),
        )
        if (
            normalized_iv is None
            or underlying is None
            or underlying <= 0
            or strike is None
        ):
            continue
        atm_candidates.append((abs(strike / underlying - 1.0), normalized_iv))
    if not atm_candidates:
        return None
    _, atm_iv = min(atm_candidates, key=lambda item: item[0])
    return {
        "observed_at": observed_at,
        "index_price": index_price,
        "dvol": dvol,
        "atm_iv": atm_iv,
        "iv_unit": "fraction",
        "funding_rate": funding_rate,
        "source": str(snapshot.get("source") or "missing"),
    }


def _sanitize_rolling_observations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value[-288:]:
        if not isinstance(item, dict):
            continue
        observed_at = str(item.get("observed_at") or "")
        index_price = _to_number(item.get("index_price"))
        dvol = _to_number(item.get("dvol"))
        atm_iv = _to_number(item.get("atm_iv"))
        normalized_atm_iv = _canonical_fraction_iv(
            atm_iv,
            item.get("iv_unit"),
        )
        funding_rate = _to_number(item.get("funding_rate"))
        try:
            parse_timestamp_ms(observed_at)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            observed_at in seen
            or index_price is None
            or index_price <= 0
            or dvol is None
            or dvol <= 0
            or normalized_atm_iv is None
            or funding_rate is None
        ):
            continue
        seen.add(observed_at)
        sanitized.append(
            {
                "observed_at": observed_at,
                "index_price": index_price,
                "dvol": dvol,
                "atm_iv": normalized_atm_iv,
                "iv_unit": "fraction",
                "funding_rate": funding_rate,
                "source": str(item.get("source") or "missing"),
            }
        )
    sanitized.sort(key=lambda item: item["observed_at"])
    return sanitized[-288:]


def _canonical_fraction_iv(value: Any, *declared_units: Any) -> float | None:
    numeric = _to_number(value)
    if numeric is None or numeric <= 0.0:
        return None
    normalized_units: set[str] = set()
    for declared in declared_units:
        if declared in (None, ""):
            continue
        normalized = str(declared).strip().lower().replace("-", "_")
        if normalized in {"fraction", "decimal", "ratio"}:
            normalized_units.add("fraction")
        elif normalized in {
            "percent",
            "percentage_points",
            "percent_points",
            "pct",
            "pct_points",
        }:
            normalized_units.add("percent_points")
        else:
            return None
    if len(normalized_units) != 1:
        return None
    unit = normalized_units.pop()
    return numeric / 100.0 if unit == "percent_points" else numeric


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

    age_sec, future_sec = _timestamp_age_seconds(
        reference_ms=normalized_snapshot["captured_at_ms"],
        observed_ms=timestamp_ms,
    )
    volatility = _to_number(payload.get("volatility"))
    if volatility is None or volatility <= 0:
        return {
            "status": "malformed",
            "required_fields": required_fields,
            "reason_code": "VOL_INDEX_VALUE_MALFORMED",
        }
    if future_sec > PUBLIC_FEED_FUTURE_TOLERANCE_SEC:
        return {
            "status": "invalid",
            "freshness_status": "future",
            "future_by_sec": future_sec,
            "max_future_sec": PUBLIC_FEED_FUTURE_TOLERANCE_SEC,
            "reason_code": "FUTURE_TIMESTAMP_VOL_INDEX",
        }
    if age_sec > VOL_INDEX_MAX_AGE_SEC:
        return {
            "status": "stale",
            "required_fields": required_fields,
            "age_sec": age_sec,
            "max_age_sec": VOL_INDEX_MAX_AGE_SEC,
            "reason_code": "VOL_INDEX_STALE",
        }
    return {
        "status": "available",
        "required_fields": required_fields,
        "age_sec": age_sec,
        "max_age_sec": VOL_INDEX_MAX_AGE_SEC,
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
    if quote.get("quote_future_sec", 0) > PUBLIC_FEED_FUTURE_TOLERANCE_SEC:
        flags.append("FUTURE_QUOTE_TIMESTAMP")
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

    return sorted({flag for flag in flags if flag in BLOCKING_QUALITY_FLAGS})


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
            return read_json_object_from_stream(
                response,
                max_bytes=MAX_MARKET_HTTP_RESPONSE_BYTES,
                description="Deribit market response",
            )
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
        expiry_date = datetime(year, month, day, tzinfo=UTC).date().isoformat()
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
    # A one-hour candle can be almost an hour old while the live feed is healthy.
    # Request one-minute candles so the returned point can satisfy the bounded
    # DVOL freshness contract used by the report quality gate.
    start_ms = max(0, captured_ms - 10 * 60 * 1000)
    payload = _get_json(
        f"{base_url}/api/v2/public/get_volatility_index_data",
        {
            "currency": currency,
            "resolution": 60,
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
    # Deribit's volatility-index endpoint defines OHLC values in percentage
    # points. Normalize from that documented venue unit unconditionally; value
    # magnitude is never used to guess a unit.
    normalized = float(volatility) / 100.0
    index_name = f"{currency} DVOL"
    try:
        timestamp = (
            datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
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
        "as_of": timestamp,
        "volatility": normalized,
        "volatility_unit": "fraction",
        "source_endpoint": "public/get_volatility_index_data",
        "raw_close": volatility,
        "raw_close_unit": "percent_points",
        "provenance": _feed_provenance(
            endpoint="public/get_volatility_index_data",
            observed_at=timestamp,
        ),
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
    rate_limit_markers = (
        "429",
        "10028",
        "too_many_requests",
        "too many requests",
        "rate_limit",
        "rate limit",
    )
    if any(marker in lowered for marker in rate_limit_markers):
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


# ---------------------------------------------------------------------------
# Underlying price history
#
# Absolute expected value needs the underlying's realized return distribution,
# not just today's quotes. Deribit publishes index/perpetual candles publicly,
# so this history is self-sourced rather than operator-supplied. Historical
# option quote chains are NOT publicly available and remain vendor-supplied;
# nothing here should be mistaken for them.
# ---------------------------------------------------------------------------

UNDERLYING_HISTORY_SCHEMA_VERSION = "underlying_price_history.v1"
MAX_UNDERLYING_HISTORY_DAYS = 3650
_UNDERLYING_RESOLUTIONS = {"1D": 86400, "12H": 43200, "1H": 3600}


def fetch_deribit_underlying_history(
    *,
    currency: str = "BTC",
    days: int = 1095,
    resolution: str = "1D",
    base_url: str = DEFAULT_DERIBIT_BASE_URL,
    timeout: int = 15,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Fetch public underlying candles and return a normalized close series.

    Fails closed: any malformed, misaligned, or non-positive row raises rather
    than being dropped, because a silently shortened series would understate
    the realized-volatility sample without saying so.
    """
    safe_base = validate_deribit_base_url(base_url)
    if resolution not in _UNDERLYING_RESOLUTIONS:
        raise ValueError(
            "underlying history resolution must be one of "
            + ", ".join(sorted(_UNDERLYING_RESOLUTIONS))
        )
    if not isinstance(days, int) or days <= 0 or days > MAX_UNDERLYING_HISTORY_DAYS:
        raise ValueError(
            f"underlying history days must be an int in 1..{MAX_UNDERLYING_HISTORY_DAYS}"
        )
    base_currency = str(currency or "").strip().upper()
    if not base_currency.isalpha():
        raise ValueError("underlying history currency must be alphabetic")

    captured = captured_at or utc_timestamp()
    end_ms = parse_timestamp_ms(captured)
    start_ms = max(0, end_ms - days * 86400 * 1000)
    instrument = f"{base_currency}-PERPETUAL"

    payload = _get_json(
        f"{safe_base}/api/v2/public/get_tradingview_chart_data",
        {
            "instrument_name": instrument,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": resolution,
        },
        timeout=timeout,
    )
    result = _jsonrpc_result(payload, endpoint="get_tradingview_chart_data")
    if not isinstance(result, dict):
        raise ValueError("underlying history result must be an object")
    if str(result.get("status") or "").lower() != "ok":
        raise ValueError(f"underlying history status not ok: {result.get('status')}")

    ticks = result.get("ticks")
    closes = result.get("close")
    if not isinstance(ticks, list) or not isinstance(closes, list):
        raise ValueError("underlying history must contain ticks and close arrays")
    if not ticks:
        raise ValueError("underlying history returned no candles")
    if len(ticks) != len(closes):
        raise ValueError("underlying history ticks and close arrays must align")

    observations: list[dict[str, Any]] = []
    previous_ms: int | None = None
    for raw_ts, raw_close in zip(ticks, closes, strict=True):
        timestamp_ms = _coerce_vol_index_timestamp_ms(raw_ts)
        close = _to_number(raw_close)
        if close is None or close <= 0:
            raise ValueError("underlying history close must be a positive number")
        if previous_ms is not None and timestamp_ms <= previous_ms:
            raise ValueError("underlying history must be strictly increasing in time")
        previous_ms = timestamp_ms
        observations.append(
            {
                "timestamp_ms": timestamp_ms,
                "observed_at": _timestamp_from_ms(timestamp_ms),
                "close": close,
            }
        )

    return {
        "schema_version": UNDERLYING_HISTORY_SCHEMA_VERSION,
        "captured_at": captured,
        "source": f"deribit_live:{safe_base}",
        "instrument_name": instrument,
        "currency": base_currency,
        "resolution": resolution,
        "resolution_seconds": _UNDERLYING_RESOLUTIONS[resolution],
        "requested_days": days,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def load_underlying_history_fixture(
    path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Load a recorded underlying price history for deterministic replay.

    Production forbids live fetches, so history reaches the report the same way
    market snapshots do: as an operator-owned file. The payload is validated to
    the shape `fetch_deribit_underlying_history` emits; a malformed file is
    rejected rather than partially accepted, because a silently truncated series
    would understate the sample without saying so.
    """
    fixture_path = resolve_snapshot_fixture_path(path, allowed_roots=allowed_roots)
    payload = read_json_object_from_regular_file(
        fixture_path,
        max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
        description="underlying history fixture",
    )
    if payload.get("schema_version") != UNDERLYING_HISTORY_SCHEMA_VERSION:
        raise ValueError(
            "underlying history fixture must be "
            f"{UNDERLYING_HISTORY_SCHEMA_VERSION}"
        )
    observations = payload.get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        raise ValueError("underlying history fixture must contain observations")
    previous_ms: int | None = None
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("underlying history observations must be objects")
        close = row.get("close")
        timestamp_ms = row.get("timestamp_ms")
        if not isinstance(close, (int, float)) or close <= 0:
            raise ValueError("underlying history close must be a positive number")
        if not isinstance(timestamp_ms, int):
            raise ValueError("underlying history timestamp_ms must be an integer")
        if previous_ms is not None and timestamp_ms <= previous_ms:
            raise ValueError("underlying history must be strictly increasing in time")
        previous_ms = timestamp_ms
    return payload
