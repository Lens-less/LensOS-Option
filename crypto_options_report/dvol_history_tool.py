"""Capture public Deribit DVOL history for deterministic replay."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .market_data import DEFAULT_DERIBIT_BASE_URL
from .storage import atomic_write_json
from .vrp import (
    MAX_DVOL_HISTORY_DAYS,
    fetch_deribit_dvol_history,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-dvol-history",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--currency", default="BTC")
    parser.add_argument(
        "--days",
        type=int,
        default=1095,
        help=f"calendar days of history (1..{MAX_DVOL_HISTORY_DAYS})",
    )
    parser.add_argument(
        "--resolution",
        default="1D",
        choices=["1D"],
        help="candle resolution",
    )
    parser.add_argument("--deribit-base-url", default=DEFAULT_DERIBIT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--output", required=True, help="path to write history JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        history = fetch_deribit_dvol_history(
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
    coverage = history.get("coverage") or {}
    summary = {
        "output": str(args.output),
        "currency": history["currency"],
        "resolution": history["resolution"],
        "observation_count": history["observation_count"],
        "first_observed_at": history["first_observed_at"],
        "last_observed_at": history["last_observed_at"],
        "missing_day_count": coverage.get("missing_day_count"),
        "missing_days": coverage.get("missing_days"),
        "coverage_ratio": coverage.get("coverage_ratio"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
