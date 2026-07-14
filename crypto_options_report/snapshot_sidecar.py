"""Research-only Deribit public snapshot sidecar."""

from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    DEFAULT_TICKER_REQUEST_BUDGET,
    advance_trust_evidence,
    bound_snapshot_trust_evidence,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
    snapshot_trust_state_path,
    utc_timestamp,
    validate_deribit_base_url,
    validate_ticker_request_limit,
    write_snapshot_fixture,
    write_snapshot_trust_state,
)
from .sidecar_auth import SidecarAuthUnavailable

DEFAULT_REFRESH_INTERVAL_SECONDS = 10.0
EXIT_OK = 0
EXIT_REFRESH_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-snapshot-sidecar",
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
        "--complete-feed-graph",
        action="store_true",
        help=(
            "collect the bounded order-book, index, funding/basis, and "
            "exchange-health feeds and persist rolling trust evidence"
        ),
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
    try:
        instrument_limit = validate_ticker_request_limit(args.instrument_limit)
    except ValueError as exc:
        parser.error(str(exc))
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
                    instrument_limit=instrument_limit,
                    complete_feed_graph=bool(args.complete_feed_graph),
                )
            except Exception as exc:  # noqa: BLE001 - fail closed and retry
                _log_json(
                    "market_snapshot_refresh_failed",
                    output=str(output),
                    currency=currency,
                    base_url=base_url,
                    instrument_limit=instrument_limit,
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
    complete_feed_graph: bool = False,
) -> None:
    fetch_kwargs = {
        "currency": currency,
        "base_url": base_url,
        "instrument_limit": instrument_limit,
    }
    if complete_feed_graph:
        fetch_kwargs["include_feed_graph"] = True
    snapshot = fetch_deribit_option_chain_snapshot(**fetch_kwargs)
    trust_evidence: dict[str, Any] | None = None
    if complete_feed_graph:
        previous_snapshot = _read_previous_snapshot(output)
        trust_evidence = advance_trust_evidence(
            snapshot,
            previous_snapshot=previous_snapshot,
        )
    written = write_snapshot_fixture(output, snapshot)
    trust_state_authenticated = False
    if trust_evidence is not None:
        try:
            write_snapshot_trust_state(
                written,
                trust_evidence,
                expected_snapshot=snapshot,
            )
        except SidecarAuthUnavailable:
            snapshot_trust_state_path(written).unlink(missing_ok=True)
        else:
            trust_state_authenticated = True
    else:
        # A non-graph refresh must not leave an older promotion record beside a
        # new snapshot.  Digest validation would already reject it; removing it
        # keeps the operator-visible state unambiguous.
        snapshot_trust_state_path(written).unlink(missing_ok=True)
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
        feed_graph_complete=(trust_evidence or {}).get("feed_graph_complete"),
        trust_evidence_status=(trust_evidence or {}).get("status"),
        rolling_observation_count=(trust_evidence or {}).get(
            "rolling_observation_count"
        ),
        trust_state_authenticated=trust_state_authenticated,
    )


def _read_previous_snapshot(output: Path) -> dict[str, Any] | None:
    if not output.exists():
        return None
    try:
        payload = load_snapshot_fixture(output)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    evidence = bound_snapshot_trust_evidence(payload)
    if evidence:
        payload["trust_evidence"] = evidence
    return payload


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
