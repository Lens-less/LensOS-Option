"""Capture public underlying price history for deterministic replay.

Absolute expected value needs the underlying's realized return distribution.
Production forbids live fetches from the API process, so history is captured
here — by an operator, on purpose — and mounted as a fixture, exactly like
market snapshots.

This fetches only public index candles. It needs no credentials and touches no
account endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    MAX_UNDERLYING_HISTORY_DAYS,
    fetch_deribit_underlying_history,
)
from .realized_vol import build_realized_return_distribution
from .storage import atomic_write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-underlying-history",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--currency", default="BTC")
    parser.add_argument(
        "--days",
        type=int,
        default=1200,
        help=f"calendar days of history (1..{MAX_UNDERLYING_HISTORY_DAYS})",
    )
    parser.add_argument(
        "--resolution",
        default="1D",
        choices=["1D", "12H", "1H"],
        help="candle resolution; only 1D supports independent-window accounting",
    )
    parser.add_argument("--deribit-base-url", default=DEFAULT_DERIBIT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--output", required=True, help="path to write history JSON")
    parser.add_argument(
        "--horizon-days",
        type=int,
        action="append",
        help=(
            "report the independent-window count for this horizon; repeatable. "
            "Use it to check the capture is long enough before relying on it."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        history = fetch_deribit_underlying_history(
            currency=args.currency,
            days=args.days,
            resolution=args.resolution,
            base_url=args.deribit_base_url,
            timeout=args.timeout,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    atomic_write_json(Path(args.output), history)

    summary = {
        "output": str(args.output),
        "currency": history["currency"],
        "resolution": history["resolution"],
        "observation_count": history["observation_count"],
        "first_observed_at": history["first_observed_at"],
        "last_observed_at": history["last_observed_at"],
    }
    # The independent-window count, not the observation count, decides whether a
    # horizon can be evidenced at all, so it is reported up front rather than
    # discovered later as a blocked report.
    for horizon in args.horizon_days or []:
        distribution = build_realized_return_distribution(
            history=history,
            horizon_days=horizon,
            generated_at=history["captured_at"],
        )
        summary.setdefault("horizons", {})[str(horizon)] = {
            "status": distribution["status"],
            "independent_windows": distribution.get("independent_window_count"),
            "overlapping_windows": distribution.get("overlapping_window_count"),
            "realized_volatility_annualized": distribution.get(
                "realized_volatility_annualized"
            ),
            "reason_code": distribution.get("reason_code"),
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
