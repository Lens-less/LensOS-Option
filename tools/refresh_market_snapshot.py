"""Research-only Deribit public snapshot sidecar."""

from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from crypto_options_report.market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    DEFAULT_TICKER_REQUEST_BUDGET,
    fetch_deribit_option_chain_snapshot,
    utc_timestamp,
    validate_deribit_base_url,
    write_snapshot_fixture,
)

DEFAULT_REFRESH_INTERVAL_SECONDS = 10.0
EXIT_OK = 0
EXIT_REFRESH_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refresh-market-snapshot",
        description=(
            "Refresh one operator-owned Deribit public snapshot for the "
            "research-only API process."
        ),
    )
    parser.add_argument("--output", required=True, help="snapshot JSON output path")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_REFRESH_INTERVAL_SECONDS,
        help="seconds between completed refresh attempts (default: 10)",
    )
    parser.add_argument(
        "--instrument-limit",
        type=int,
        default=DEFAULT_TICKER_REQUEST_BUDGET,
    )
    parser.add_argument("--currency", default="BTC")
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
    base_url = _validated_base_url(parser, args.base_url)
    currency = str(args.currency).strip().upper()
    if not currency or not currency.isascii() or not currency.isalnum():
        parser.error("currency must contain only letters and digits")
    if not 1 <= args.instrument_limit <= DEFAULT_TICKER_REQUEST_BUDGET:
        parser.error(
            "instrument_limit must be between 1 and "
            f"{DEFAULT_TICKER_REQUEST_BUDGET}"
        )
    if not isfinite(args.interval) or args.interval <= 0:
        parser.error("interval must be finite and greater than zero")

    output = Path(args.output).expanduser().resolve()
    try:
        while True:
            try:
                _refresh_once(
                    output=output,
                    currency=currency,
                    base_url=base_url,
                    instrument_limit=args.instrument_limit,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed and retry
                _log_json(
                    "market_snapshot_refresh_failed",
                    output=str(output),
                    currency=currency,
                    base_url=base_url,
                    instrument_limit=args.instrument_limit,
                    reason_code="SNAPSHOT_REFRESH_FAILED",
                    error_type=type(exc).__name__,
                    retrying=not args.once,
                )
                if args.once:
                    return EXIT_REFRESH_FAILED
            else:
                if args.once:
                    return EXIT_OK
            time.sleep(args.interval)
    except KeyboardInterrupt:
        _log_json(
            "market_snapshot_sidecar_stopped",
            output=str(output),
            currency=currency,
            reason="keyboard_interrupt",
        )
        return EXIT_OK


def _refresh_once(
    *,
    output: Path,
    currency: str,
    base_url: str,
    instrument_limit: int,
) -> None:
    snapshot = fetch_deribit_option_chain_snapshot(
        currency=currency,
        base_url=base_url,
        instrument_limit=instrument_limit,
    )
    written = write_snapshot_fixture(output, snapshot)
    _log_json(
        "market_snapshot_written",
        output=str(written),
        currency=currency,
        base_url=base_url,
        instrument_limit=instrument_limit,
        captured_at=snapshot.get("captured_at"),
        collection_started_at=snapshot.get("collection_started_at"),
        collection_duration_ms=snapshot.get("collection_duration_ms"),
        row_count=len(snapshot.get("rows") or []),
        fetch_error_count=len(snapshot.get("fetch_errors") or []),
        adapter_event_count=len(snapshot.get("adapter_events") or []),
    )


def _validated_base_url(
    parser: argparse.ArgumentParser,
    value: str,
) -> str:
    try:
        return validate_deribit_base_url(value)
    except ValueError as exc:
        parser.error(str(exc))
    raise AssertionError("argparse.error must exit")


def _log_json(event: str, **fields: Any) -> None:
    payload = {
        "timestamp": utc_timestamp(),
        "event": event,
        "research_only": True,
    }
    payload.update(fields)
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
