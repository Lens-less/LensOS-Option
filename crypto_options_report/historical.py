"""Historical vendor normalization and reconciliation tracer.

ISSUE-003 adds a narrow historical-data surface that normalizes vendor or
fixture option rows into canonical metadata/quote shapes, reconciles their
quality and payoff facts, quarantines failures, and exposes only eligible
canonical data to later consumers.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

HISTORICAL_REPORT_SCHEMA_VERSION = "historical_reconciliation_report.v1"
FAILURE_CODES = {
    "METADATA_MAPPING_FAILED",
    "TIMESTAMP_ALIGNMENT_FAILED",
    "BID_ASK_SANITY_FAILED",
    "IV_SANITY_FAILED",
    "MARK_MID_DRIFT_FAILED",
    "VENDOR_DIFF_FAILED",
    "PAYOFF_REPLAY_FAILED",
    "OI_VOLUME_MAPPING_FAILED",
    "SURFACE_NO_ARB_FAILED",
}

DEFAULT_RECONCILIATION_CONFIG = {
    "timestamp_alignment_seconds": 60,
    "min_iv": 0.01,
    "max_iv": 5.0,
    "max_mark_mid_drift_ratio": 0.20,
    "max_vendor_mid_diff_ratio": 0.02,
    "max_surface_no_arb_error": 0.03,
    "max_payoff_bps_error": 1.0,
    "quantity_tolerance_contracts": 0.001,
    "default_tick_size": 0.5,
    "default_contract_size": 1.0,
}

MONTHS = {
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

INSTRUMENT_RE = re.compile(
    r"^(?P<base>[A-Z]+)-(?P<day>\d{1,2})(?P<month>[A-Z]{3})(?P<year>\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<option>[CP])$"
)


class HistoricalNormalizationError(ValueError):
    """Typed normalization error with a stable failure code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InstrumentMetadata:
    venue: str
    instrument_name: str
    currency: str
    base_currency: str
    quote_currency: str
    settlement_currency: str
    product_type: str
    option_type: str
    expiry: str
    strike: float
    contract_size: float
    tick_size: float
    source_vendor: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "instrument_name": self.instrument_name,
            "currency": self.currency,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "settlement_currency": self.settlement_currency,
            "product_type": self.product_type,
            "option_type": self.option_type,
            "expiry": self.expiry,
            "strike": self.strike,
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            "source_vendor": self.source_vendor,
        }


@dataclass(frozen=True)
class CanonicalHistoricalQuote:
    quote_id: str
    snapshot_key: str
    ts: str
    venue: str
    instrument_name: str
    currency: str
    settlement_currency: str
    expiry: str
    strike: float
    option_type: str
    bid: float
    ask: float
    mid: float
    mark_price: float
    bid_iv: float
    ask_iv: float
    mark_iv: float
    model_iv: float | None
    underlying_price: float
    underlying_index: str
    open_interest: float
    volume_24h: float
    best_bid_amount: float
    best_ask_amount: float
    depth_bid_5: float
    depth_ask_5: float
    quote_age_ms: int
    data_vendor: str
    quality_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote_id": self.quote_id,
            "snapshot_key": self.snapshot_key,
            "ts": self.ts,
            "venue": self.venue,
            "instrument_name": self.instrument_name,
            "currency": self.currency,
            "settlement_currency": self.settlement_currency,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "mark_price": self.mark_price,
            "bid_iv": self.bid_iv,
            "ask_iv": self.ask_iv,
            "mark_iv": self.mark_iv,
            "model_iv": self.model_iv,
            "underlying_price": self.underlying_price,
            "underlying_index": self.underlying_index,
            "open_interest": self.open_interest,
            "volume_24h": self.volume_24h,
            "best_bid_amount": self.best_bid_amount,
            "best_ask_amount": self.best_ask_amount,
            "depth_bid_5": self.depth_bid_5,
            "depth_ask_5": self.depth_ask_5,
            "quote_age_ms": self.quote_age_ms,
            "data_vendor": self.data_vendor,
            "quality_status": self.quality_status,
        }


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_historical_fixture(path: str | Path, *, scenario: str | None = None) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if scenario is None:
        return payload

    scenarios = payload.get("scenarios", {})
    if scenario not in scenarios:
        raise ValueError(f"fixture scenario {scenario!r} not found in {path}")
    scenario_payload = dict(scenarios[scenario])
    scenario_payload.setdefault("name", scenario)
    return scenario_payload


def normalize_historical_rows(
    rows: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> tuple[list[InstrumentMetadata], list[CanonicalHistoricalQuote]]:
    merged_config = _merge_config(config)
    instrument_map: dict[str, InstrumentMetadata] = {}
    quotes: list[CanonicalHistoricalQuote] = []
    for index, row in enumerate(rows):
        metadata = _map_instrument_metadata(row, merged_config)
        prior = instrument_map.get(metadata.instrument_name)
        if prior is not None and _metadata_signature(prior) != _metadata_signature(metadata):
            raise HistoricalNormalizationError(
                "METADATA_MAPPING_FAILED",
                f"inconsistent metadata for {metadata.instrument_name}",
            )
        instrument_map[metadata.instrument_name] = metadata
        quotes.append(_canonicalize_option_row(row, metadata, index, merged_config))
    return list(instrument_map.values()), quotes


def build_historical_reconciliation_report(
    rows: Sequence[dict[str, Any]],
    *,
    generated_at: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_config = _merge_config(config)
    report_generated_at = generated_at or utc_timestamp()
    instrument_map: dict[str, InstrumentMetadata] = {}
    normalized_quotes: list[CanonicalHistoricalQuote] = []
    raw_rows_by_quote_id: dict[str, dict[str, Any]] = {}
    quote_failures: dict[str, list[dict[str, Any]]] = {}
    quarantined_quotes: set[str] = set()
    quarantined_instruments: set[str] = set()
    quarantined_snapshots: set[str] = set()
    failures: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        quote_id = _quote_id(row, index)
        try:
            metadata = _map_instrument_metadata(row, merged_config)
            prior = instrument_map.get(metadata.instrument_name)
            if prior is not None and _metadata_signature(prior) != _metadata_signature(metadata):
                raise HistoricalNormalizationError(
                    "METADATA_MAPPING_FAILED",
                    f"inconsistent metadata for {metadata.instrument_name}",
                )
            instrument_map[metadata.instrument_name] = metadata
            quote = _canonicalize_option_row(row, metadata, index, merged_config)
            normalized_quotes.append(quote)
            raw_rows_by_quote_id[quote.quote_id] = row
        except HistoricalNormalizationError as exc:
            instrument_name = row.get("instrument_name", quote_id)
            failure = _failure_entry(
                code=exc.code,
                scope="instrument",
                quote_id=quote_id,
                vendor=str(row.get("vendor", "fixture")),
                instrument_name=str(instrument_name),
                snapshot_key=str(row.get("snapshot_key", "")),
                detail=str(exc),
            )
            failures.append(failure)
            quote_failures.setdefault(quote_id, []).append(failure)
            quarantined_quotes.add(quote_id)
            quarantined_instruments.add(str(instrument_name))

    for quote in normalized_quotes:
        raw = raw_rows_by_quote_id[quote.quote_id]
        _record_row_level_failures(
            quote,
            raw,
            merged_config,
            failures,
            quote_failures,
            quarantined_quotes,
            quarantined_snapshots,
        )

    grouped = _group_quotes_for_snapshot_checks(normalized_quotes)
    for group in grouped.values():
        _record_group_level_failures(
            group,
            merged_config,
            failures,
            quote_failures,
            quarantined_quotes,
            quarantined_snapshots,
        )

    eligible_quotes = [
        quote
        for quote in normalized_quotes
        if quote.quote_id not in quarantined_quotes
        and quote.instrument_name not in quarantined_instruments
        and quote.snapshot_key not in quarantined_snapshots
    ]
    eligible_instruments = sorted({quote.instrument_name for quote in eligible_quotes})
    failure_counts = _count_failures(failures)
    decision = _eligibility_decision(len(eligible_quotes), len(failures))
    quarantine_quotes_payload = []
    normalized_quote_ids = {quote.quote_id for quote in normalized_quotes}
    for quote in normalized_quotes:
        if quote.quote_id in quarantined_quotes or quote.snapshot_key in quarantined_snapshots:
            failure_codes = sorted(
                {failure["code"] for failure in quote_failures.get(quote.quote_id, [])}
            )
            quarantine_quotes_payload.append(
                {
                    "quote_id": quote.quote_id,
                    "vendor": quote.data_vendor,
                    "instrument_name": quote.instrument_name,
                    "snapshot_key": quote.snapshot_key,
                    "failure_codes": failure_codes,
                    "failure_reasons": failure_codes,
                }
            )
    for quote_id, quote_specific_failures in quote_failures.items():
        if quote_id in normalized_quote_ids:
            continue
        first_failure = quote_specific_failures[0]
        quarantine_quotes_payload.append(
            {
                "quote_id": quote_id,
                "vendor": first_failure["vendor"],
                "instrument_name": first_failure["instrument_name"],
                "snapshot_key": first_failure["snapshot_key"],
                "failure_codes": sorted({failure["code"] for failure in quote_specific_failures}),
                "failure_reasons": sorted({failure["code"] for failure in quote_specific_failures}),
            }
        )

    strict_eligible = decision == "ELIGIBLE"
    aggregate_eligibility = {
        "status": "validated" if decision == "ELIGIBLE" else "blocked",
        "decision": decision,
        "training_allowed": strict_eligible,
        "backtest_allowed": strict_eligible,
        "eligible_quotes": len(eligible_quotes),
        "quarantined_quotes": len(quarantine_quotes_payload),
        "failure_counts": failure_counts,
        "blocks_downstream": decision != "ELIGIBLE",
    }

    return {
        "schema_version": HISTORICAL_REPORT_SCHEMA_VERSION,
        "generated_at": report_generated_at,
        "raw_data_provenance": {
            "source_type": "fixture_or_vendor_rows",
            "raw_rows": len(rows),
            "source_vendors": sorted(
                {str(row.get("vendor", "fixture")) for row in rows}
            ),
            "ingested_at": report_generated_at,
            "normalization_schema_version": HISTORICAL_REPORT_SCHEMA_VERSION,
            "normalization_config": dict(merged_config),
        },
        "summary": {
            "total_rows": len(rows),
            "normalized_quotes": len(normalized_quotes),
            "eligible_quotes": len(eligible_quotes),
            "quarantined_quotes": len(quarantine_quotes_payload),
            "quarantined_instruments": len(quarantined_instruments),
            "quarantined_snapshots": len(quarantined_snapshots),
            "pass_count": len(eligible_quotes),
            "fail_count": len(failures),
            "failure_counts": failure_counts,
        },
        "eligibility": {
            "decision": decision,
            "training_allowed": strict_eligible,
            "backtest_allowed": strict_eligible,
            "eligible_instruments": eligible_instruments,
            "eligible_snapshot_count": len({quote.snapshot_key for quote in eligible_quotes}),
        },
        "aggregate_eligibility": aggregate_eligibility,
        "canonical_data": {
            "instrument_metadata": [
                instrument_map[name].to_dict() for name in sorted(instrument_map)
            ],
            "normalized_quotes": [quote.to_dict() for quote in normalized_quotes],
            "eligible_quotes": [quote.to_dict() for quote in eligible_quotes],
        },
        "quarantine": {
            "instruments": sorted(quarantined_instruments),
            "snapshots": sorted(quarantined_snapshots),
            "quotes": quarantine_quotes_payload,
        },
        "failures": failures,
    }


def query_eligible_canonical_quotes(
    report: dict[str, Any],
    *,
    instrument_name: str | None = None,
    snapshot_key: str | None = None,
) -> list[dict[str, Any]]:
    quotes = report.get("canonical_data", {}).get("eligible_quotes", [])
    filtered: list[dict[str, Any]] = []
    for quote in quotes:
        if instrument_name and quote.get("instrument_name") != instrument_name:
            continue
        if snapshot_key and quote.get("snapshot_key") != snapshot_key:
            continue
        filtered.append(quote)
    return filtered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-options-report-historical")
    parser.add_argument(
        "--fixture",
        required=True,
        help="path to a JSON fixture containing rows or scenarios",
    )
    parser.add_argument(
        "--scenario",
        help="scenario name when the fixture file contains a scenarios object",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = load_historical_fixture(args.fixture, scenario=args.scenario)
    rows = payload.get("rows", [])
    report = build_historical_reconciliation_report(rows)
    json.dump(
        report,
        sys.stdout,
        indent=None if args.compact else 2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_RECONCILIATION_CONFIG)
    if config:
        merged.update(config)
    return merged


def _quote_id(row: dict[str, Any], index: int) -> str:
    vendor = str(row.get("vendor", "fixture"))
    return str(row.get("quote_id", f"{vendor}:{index}"))


def _map_instrument_metadata(
    row: dict[str, Any],
    config: dict[str, Any],
) -> InstrumentMetadata:
    instrument_name = str(row.get("instrument_name", "")).strip()
    if not instrument_name:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            "instrument_name is required",
        )

    match = INSTRUMENT_RE.match(instrument_name)
    if not match:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"instrument_name {instrument_name!r} is not a supported option symbol",
        )

    base_currency = match.group("base")
    month = MONTHS.get(match.group("month"))
    if month is None:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"unsupported expiry month in {instrument_name}",
        )
    expiry = datetime(
        year=2000 + int(match.group("year")),
        month=month,
        day=int(match.group("day")),
        hour=8,
        tzinfo=timezone.utc,
    )
    option_type = "CALL" if match.group("option") == "C" else "PUT"
    strike = float(match.group("strike"))

    settlement_currency = str(
        row.get("settlement_currency")
        or row.get("quote_currency")
        or base_currency
    ).upper()
    quote_currency = str(row.get("quote_currency") or settlement_currency).upper()
    contract_size = _positive_float(
        row.get("contract_size", config["default_contract_size"]),
        "contract_size",
    )
    tick_size = _positive_float(
        row.get("tick_size", config["default_tick_size"]),
        "tick_size",
    )
    vendor = str(row.get("vendor", "fixture"))

    return InstrumentMetadata(
        venue=str(row.get("venue", "DERIBIT")).upper(),
        instrument_name=instrument_name,
        currency=base_currency,
        base_currency=base_currency,
        quote_currency=quote_currency,
        settlement_currency=settlement_currency,
        product_type="OPTION",
        option_type=option_type,
        expiry=_isoformat(expiry),
        strike=strike,
        contract_size=contract_size,
        tick_size=tick_size,
        source_vendor=vendor,
    )


def _canonicalize_option_row(
    row: dict[str, Any],
    metadata: InstrumentMetadata,
    index: int,
    config: dict[str, Any],
) -> CanonicalHistoricalQuote:
    ts = _parse_timestamp(row.get("timestamp") or row.get("ts"))
    underlying_price = _positive_float(row.get("underlying_price"), "underlying_price")
    bid = _non_negative_float(row.get("bid"), "bid")
    ask = _non_negative_float(row.get("ask"), "ask")
    mark = _non_negative_float(row.get("mark"), "mark")
    bid_iv = _normalize_iv(row.get("bid_iv"), "bid_iv")
    ask_iv = _normalize_iv(row.get("ask_iv"), "ask_iv")
    mark_iv = _normalize_iv(row.get("mark_iv", row.get("mark_iv", (bid_iv + ask_iv) / 2.0)), "mark_iv")
    model_iv_value = row.get("model_iv")
    model_iv = None if model_iv_value is None else _normalize_iv(model_iv_value, "model_iv")
    mid = _mid_price(row.get("mid"), bid, ask)
    open_interest = _normalize_contract_quantity(
        row.get("open_interest", row.get("oi")),
        row.get("oi_unit", "contracts"),
        metadata.contract_size,
        underlying_price,
        field_name="open_interest",
    )
    volume_24h = _normalize_contract_quantity(
        row.get("volume_24h"),
        row.get("volume_unit", "contracts"),
        metadata.contract_size,
        underlying_price,
        field_name="volume_24h",
    )
    snapshot_key = str(
        row.get("snapshot_key")
        or row.get("snapshot_group")
        or f"{metadata.instrument_name}@{ts[:16]}"
    )
    return CanonicalHistoricalQuote(
        quote_id=_quote_id(row, index),
        snapshot_key=snapshot_key,
        ts=ts,
        venue=metadata.venue,
        instrument_name=metadata.instrument_name,
        currency=metadata.currency,
        settlement_currency=metadata.settlement_currency,
        expiry=metadata.expiry,
        strike=metadata.strike,
        option_type=metadata.option_type,
        bid=bid,
        ask=ask,
        mid=mid,
        mark_price=mark,
        bid_iv=bid_iv,
        ask_iv=ask_iv,
        mark_iv=mark_iv,
        model_iv=model_iv,
        underlying_price=underlying_price,
        underlying_index=str(row.get("underlying_index", "DERIBIT_INDEX")),
        open_interest=open_interest,
        volume_24h=volume_24h,
        best_bid_amount=_non_negative_float(
            row.get("best_bid_amount", row.get("depth_bid_1", 0.0)),
            "best_bid_amount",
        ),
        best_ask_amount=_non_negative_float(
            row.get("best_ask_amount", row.get("depth_ask_1", 0.0)),
            "best_ask_amount",
        ),
        depth_bid_5=_non_negative_float(row.get("depth_bid_5", 0.0), "depth_bid_5"),
        depth_ask_5=_non_negative_float(row.get("depth_ask_5", 0.0), "depth_ask_5"),
        quote_age_ms=int(row.get("quote_age_ms", 0)),
        data_vendor=str(row.get("vendor", "fixture")),
        quality_status="pending",
    )


def _record_row_level_failures(
    quote: CanonicalHistoricalQuote,
    raw: dict[str, Any],
    config: dict[str, Any],
    failures: list[dict[str, Any]],
    quote_failures: dict[str, list[dict[str, Any]]],
    quarantined_quotes: set[str],
    quarantined_snapshots: set[str],
) -> None:
    if quote.bid > quote.ask or quote.mid <= 0 or (quote.ask - quote.bid) < 0:
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="BID_ASK_SANITY_FAILED",
            scope="quote",
            quote=quote,
            detail="bid must be <= ask and mid must stay positive",
        )

    iv_values = [quote.bid_iv, quote.ask_iv, quote.mark_iv]
    if any(value < config["min_iv"] or value > config["max_iv"] for value in iv_values):
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="IV_SANITY_FAILED",
            scope="quote",
            quote=quote,
            detail="normalized IV is outside the supported range",
        )

    if quote.mid > 0:
        drift_ratio = abs(quote.mark_price - quote.mid) / quote.mid
        if drift_ratio > config["max_mark_mid_drift_ratio"]:
            _record_failure(
                failures,
                quote_failures,
                quarantined_quotes,
                code="MARK_MID_DRIFT_FAILED",
                scope="quote",
                quote=quote,
                detail=f"mark/mid drift ratio {drift_ratio:.4f} exceeds threshold",
            )

    if not _validate_expected_contract_mapping(raw, quote, config):
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="OI_VOLUME_MAPPING_FAILED",
            scope="quote",
            quote=quote,
            detail="OI/volume mapping does not match the expected contract counts",
        )

    if not _validate_payoff_replay(raw, quote, config):
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="PAYOFF_REPLAY_FAILED",
            scope="quote",
            quote=quote,
            detail="recorded payoff does not match replayed settlement payoff",
        )

    surface_no_arb_error = raw.get("surface_no_arb_error")
    if surface_no_arb_error is not None and float(surface_no_arb_error) > config["max_surface_no_arb_error"]:
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="SURFACE_NO_ARB_FAILED",
            scope="snapshot",
            quote=quote,
            detail="surface no-arb error exceeds threshold",
        )
        quarantined_snapshots.add(quote.snapshot_key)

    if raw.get("surface_no_arb_pass") is False:
        _record_failure(
            failures,
            quote_failures,
            quarantined_quotes,
            code="SURFACE_NO_ARB_FAILED",
            scope="snapshot",
            quote=quote,
            detail="surface no-arb flag is false",
        )
        quarantined_snapshots.add(quote.snapshot_key)


def _record_group_level_failures(
    group: list[CanonicalHistoricalQuote],
    config: dict[str, Any],
    failures: list[dict[str, Any]],
    quote_failures: dict[str, list[dict[str, Any]]],
    quarantined_quotes: set[str],
    quarantined_snapshots: set[str],
) -> None:
    if len(group) < 2:
        return

    timestamps = [_parse_timestamp_object(quote.ts) for quote in group]
    span_seconds = (max(timestamps) - min(timestamps)).total_seconds()
    if span_seconds > config["timestamp_alignment_seconds"]:
        for quote in group:
            _record_failure(
                failures,
                quote_failures,
                quarantined_quotes,
                code="TIMESTAMP_ALIGNMENT_FAILED",
                scope="snapshot",
                quote=quote,
                detail=f"snapshot timestamps span {span_seconds:.1f}s",
            )
            quarantined_snapshots.add(quote.snapshot_key)

    vendors = {quote.data_vendor for quote in group}
    if len(vendors) < 2:
        return

    mids = [quote.mid for quote in group]
    median_mid = sorted(mids)[len(mids) // 2]
    max_mid_diff = max(mids) - min(mids)
    ratio = 0.0 if median_mid == 0 else max_mid_diff / median_mid
    if (
        max_mid_diff > config["default_tick_size"]
        and ratio > config["max_vendor_mid_diff_ratio"]
    ):
        for quote in group:
            _record_failure(
                failures,
                quote_failures,
                quarantined_quotes,
                code="VENDOR_DIFF_FAILED",
                scope="snapshot",
                quote=quote,
                detail=f"cross-vendor mid diff {max_mid_diff:.4f} ({ratio:.4%}) exceeds threshold",
            )
            quarantined_snapshots.add(quote.snapshot_key)


def _group_quotes_for_snapshot_checks(
    quotes: Iterable[CanonicalHistoricalQuote],
) -> dict[tuple[str, str], list[CanonicalHistoricalQuote]]:
    grouped: dict[tuple[str, str], list[CanonicalHistoricalQuote]] = {}
    for quote in quotes:
        key = (quote.snapshot_key, quote.instrument_name)
        grouped.setdefault(key, []).append(quote)
    return grouped


def _record_failure(
    failures: list[dict[str, Any]],
    quote_failures: dict[str, list[dict[str, Any]]],
    quarantined_quotes: set[str],
    *,
    code: str,
    scope: str,
    quote: CanonicalHistoricalQuote,
    detail: str,
) -> None:
    failure = _failure_entry(
        code=code,
        scope=scope,
        quote_id=quote.quote_id,
        vendor=quote.data_vendor,
        instrument_name=quote.instrument_name,
        snapshot_key=quote.snapshot_key,
        detail=detail,
    )
    failures.append(failure)
    quote_failures.setdefault(quote.quote_id, []).append(failure)
    quarantined_quotes.add(quote.quote_id)


def _failure_entry(
    *,
    code: str,
    scope: str,
    quote_id: str,
    vendor: str,
    instrument_name: str,
    snapshot_key: str,
    detail: str,
) -> dict[str, Any]:
    if code not in FAILURE_CODES:
        raise ValueError(f"unsupported failure code {code!r}")
    return {
        "code": code,
        "scope": scope,
        "quote_id": quote_id,
        "vendor": vendor,
        "instrument_name": instrument_name,
        "snapshot_key": snapshot_key,
        "detail": detail,
    }


def _count_failures(failures: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in failures:
        code = str(failure["code"])
        counts[code] = counts.get(code, 0) + 1
    return counts


def _eligibility_decision(eligible_quotes: int, failure_count: int) -> str:
    if eligible_quotes == 0:
        return "INELIGIBLE"
    if failure_count == 0:
        return "ELIGIBLE"
    return "PARTIAL"


def _metadata_signature(metadata: InstrumentMetadata) -> tuple[Any, ...]:
    return (
        metadata.venue,
        metadata.instrument_name,
        metadata.currency,
        metadata.base_currency,
        metadata.quote_currency,
        metadata.settlement_currency,
        metadata.product_type,
        metadata.option_type,
        metadata.expiry,
        metadata.strike,
        metadata.contract_size,
        metadata.tick_size,
    )


def _parse_timestamp(value: Any) -> str:
    if value is None:
        raise HistoricalNormalizationError(
            "TIMESTAMP_ALIGNMENT_FAILED",
            "timestamp is required",
        )
    try:
        parsed = _parse_timestamp_object(str(value))
    except ValueError as exc:
        raise HistoricalNormalizationError(
            "TIMESTAMP_ALIGNMENT_FAILED",
            f"invalid timestamp {value!r}",
        ) from exc
    return _isoformat(parsed)


def _parse_timestamp_object(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_iv(value: Any, field_name: str) -> float:
    iv = _non_negative_float(value, field_name)
    if iv > 5.0:
        iv = iv / 100.0
    return iv


def _normalize_contract_quantity(
    value: Any,
    unit: Any,
    contract_size: float,
    underlying_price: float,
    *,
    field_name: str,
) -> float:
    quantity = _non_negative_float(value, field_name)
    normalized_unit = str(unit).lower()
    if normalized_unit == "contracts":
        return quantity
    if normalized_unit == "base_currency":
        return quantity / contract_size
    if normalized_unit == "quote_currency":
        notional = contract_size * underlying_price
        if notional <= 0:
            raise HistoricalNormalizationError(
                "OI_VOLUME_MAPPING_FAILED",
                f"{field_name} quote-currency mapping needs positive notional",
            )
        return quantity / notional
    raise HistoricalNormalizationError(
        "OI_VOLUME_MAPPING_FAILED",
        f"unsupported {field_name} unit {unit!r}",
    )


def _mid_price(raw_mid: Any, bid: float, ask: float) -> float:
    if raw_mid is None:
        return (bid + ask) / 2.0
    return _non_negative_float(raw_mid, "mid")


def _positive_float(value: Any, field_name: str) -> float:
    number = _float(value, field_name)
    if number <= 0:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"{field_name} must be positive",
        )
    return number


def _non_negative_float(value: Any, field_name: str) -> float:
    number = _float(value, field_name)
    if number < 0:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"{field_name} must be non-negative",
        )
    return number


def _float(value: Any, field_name: str) -> float:
    if value is None:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"{field_name} is required",
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"{field_name} must be numeric",
        ) from exc
    if math.isnan(number) or math.isinf(number):
        raise HistoricalNormalizationError(
            "METADATA_MAPPING_FAILED",
            f"{field_name} must be finite",
        )
    return number


def _validate_expected_contract_mapping(
    raw: dict[str, Any],
    quote: CanonicalHistoricalQuote,
    config: dict[str, Any],
) -> bool:
    tolerance = config["quantity_tolerance_contracts"]
    expected_oi = raw.get("expected_open_interest_contracts")
    if expected_oi is not None and abs(float(expected_oi) - quote.open_interest) > tolerance:
        return False
    expected_volume = raw.get("expected_volume_contracts")
    if expected_volume is not None and abs(float(expected_volume) - quote.volume_24h) > tolerance:
        return False
    return True


def _validate_payoff_replay(
    raw: dict[str, Any],
    quote: CanonicalHistoricalQuote,
    config: dict[str, Any],
) -> bool:
    delivery_price_raw = raw.get("delivery_price")
    recorded_long_payoff_raw = raw.get("recorded_long_payoff")
    if delivery_price_raw is None or recorded_long_payoff_raw is None:
        return True

    delivery_price = float(delivery_price_raw)
    recorded_long_payoff = float(recorded_long_payoff_raw)
    intrinsic = max(delivery_price - quote.strike, 0.0)
    if quote.settlement_currency == quote.currency:
        expected_long_payoff = intrinsic / delivery_price if delivery_price > 0 else 0.0
    else:
        expected_long_payoff = intrinsic

    tolerance = (
        config["max_payoff_bps_error"]
        / 10000.0
        * max(quote.strike, delivery_price, 1.0)
    )
    return abs(recorded_long_payoff - expected_long_payoff) <= tolerance


if __name__ == "__main__":
    raise SystemExit(main())
