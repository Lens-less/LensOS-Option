"""Command-line surface for the shared research report."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .account_risk import AVAILABLE_ACCOUNT_SCENARIOS
from .backtest import (
    build_fixed_baseline_backtest_report,
    load_backtest_fixture,
)
from .contract import SUPPORTED_MODES, generate_research_report
from .full_surface import build_recommendation_projection
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
)
from .historical import build_historical_reconciliation_report, load_historical_fixture
from .path_risk import (
    build_path_risk_report_from_fixture,
    build_path_risk_report_from_historical_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-options-report")
    subcommands = parser.add_subparsers(dest="command", required=True)

    report = subcommands.add_parser("report", help="emit the shared research report")
    report.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_MODES),
        default="research_only",
        help="requested product mode; unsafe modes remain gated",
    )
    report.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )
    source_group = report.add_mutually_exclusive_group()
    source_group.add_argument(
        "--snapshot-fixture",
        help="replay a recorded Deribit option-chain snapshot fixture",
    )
    source_group.add_argument(
        "--live-deribit",
        action="store_true",
        help="fetch a live Deribit BTC option-chain snapshot before building the report",
    )
    report.add_argument(
        "--currency",
        default="BTC",
        help="currency for the live Deribit snapshot fetch",
    )
    report.add_argument(
        "--deribit-base-url",
        default=DEFAULT_DERIBIT_BASE_URL,
        help="Deribit API base URL for live fetches",
    )
    report.add_argument(
        "--instrument-limit",
        type=int,
        help="optional live-fetch limit for smoke and diagnostics",
    )
    report.add_argument(
        "--account-scenario",
        choices=AVAILABLE_ACCOUNT_SCENARIOS,
        help="optional replayable account scenario name",
    )
    report.add_argument(
        "--generated-at",
        help="optional ISO timestamp used as the report evaluation time for fixture replay",
    )

    baseline_backtest = subcommands.add_parser(
        "baseline-backtest",
        aliases=["backtest"],
        help="run the fixed 7D 0.1 delta conservative baseline replay",
    )
    baseline_backtest.add_argument(
        "--fixture",
        required=True,
        help="path to a fixed baseline backtest fixture JSON file",
    )
    baseline_backtest.add_argument(
        "--generated-at",
        help="optional ISO timestamp used to keep replay output deterministic",
    )
    baseline_backtest.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )

    path_risk = subcommands.add_parser(
        "path-risk",
        help="run the ISSUE-009 path-risk distribution tracer",
    )
    path_source = path_risk.add_mutually_exclusive_group(required=True)
    path_source.add_argument(
        "--fixture",
        help="path to a path-risk fixture JSON file",
    )
    path_source.add_argument(
        "--historical-fixture",
        help="path to a historical vendor fixture JSON file",
    )
    path_risk.add_argument(
        "--historical-scenario",
        help="scenario name when the historical fixture file contains scenarios",
    )
    path_risk.add_argument(
        "--generated-at",
        help="optional ISO timestamp used to keep report output deterministic",
    )
    path_risk.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON",
    )

    for command, help_text in (
        ("ingest", "run or replay market-data ingestion in research mode"),
        ("ingestion-status", "emit market-data ingestion status"),
        ("fit-surface", "emit vol-surface fitting status"),
        ("surface-status", "emit vol-surface status"),
        ("build-features", "emit regime and calibration feature status"),
        ("feature-status", "emit feature-build status"),
        ("calibrate", "emit walk-forward calibration report"),
        ("scan", "emit research-only candidate scanner output"),
        ("recommend", "emit mode-gated recommendation projection"),
        ("dashboard", "emit dashboard view-model descriptor"),
    ):
        surface_parser = subcommands.add_parser(command, help=help_text)
        _add_report_replay_args(surface_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "report":
        report = _build_report_from_args(args)
        json.dump(
            report,
            sys.stdout,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0

    if args.command in {
        "ingest",
        "ingestion-status",
        "fit-surface",
        "surface-status",
        "build-features",
        "feature-status",
        "calibrate",
        "scan",
        "recommend",
        "dashboard",
    }:
        report = _build_report_from_args(args)
        payload = _surface_payload(args.command, report)
        json.dump(
            payload,
            sys.stdout,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0

    if args.command in {"backtest", "baseline-backtest"}:
        report = build_fixed_baseline_backtest_report(
            load_backtest_fixture(args.fixture),
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

    if args.command == "path-risk":
        if args.fixture:
            report = build_path_risk_report_from_fixture(
                args.fixture,
                generated_at=args.generated_at,
            )
        else:
            historical_payload = load_historical_fixture(
                args.historical_fixture,
                scenario=args.historical_scenario,
            )
            historical_report = build_historical_reconciliation_report(
                historical_payload.get("rows", []),
                generated_at=args.generated_at,
            )
            report = build_path_risk_report_from_historical_report(
                historical_report,
                historical_payload["path_risk_candidate"],
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

    parser.error(f"unsupported command: {args.command}")
    return 2


def _add_report_replay_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_MODES),
        default="research_only",
        help="requested product mode; unsafe modes remain gated",
    )
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--snapshot-fixture",
        help="replay a recorded Deribit option-chain snapshot fixture",
    )
    source_group.add_argument(
        "--live-deribit",
        action="store_true",
        help="fetch a live Deribit BTC option-chain snapshot first",
    )
    parser.add_argument("--currency", default="BTC")
    parser.add_argument("--deribit-base-url", default=DEFAULT_DERIBIT_BASE_URL)
    parser.add_argument("--instrument-limit", type=int)
    parser.add_argument(
        "--account-scenario",
        choices=AVAILABLE_ACCOUNT_SCENARIOS,
        help="optional replayable account scenario name",
    )
    parser.add_argument("--generated-at")


def _build_report_from_args(args: argparse.Namespace) -> dict:
    market_snapshot = None
    if args.snapshot_fixture:
        market_snapshot = load_snapshot_fixture(args.snapshot_fixture)
    elif args.live_deribit:
        market_snapshot = fetch_deribit_option_chain_snapshot(
            currency=args.currency,
            base_url=args.deribit_base_url,
            instrument_limit=args.instrument_limit,
        )

    return generate_research_report(
        mode=args.mode,
        market_snapshot=market_snapshot,
        account_scenario=args.account_scenario,
        generated_at=args.generated_at,
    )


def _surface_payload(command: str, report: dict) -> dict:
    if command in {"ingest", "ingestion-status"}:
        return {
            "schema_version": "ingestion_status.v1",
            "status": report["data_status"]["status"],
            "data_trust": report["data_trust"],
            "data_status": report["data_status"],
        }
    if command in {"fit-surface", "surface-status"}:
        return report["vol_surface_status"]
    if command in {"build-features", "feature-status"}:
        return {
            "schema_version": "feature_status.v1",
            "regime": report["permission_state"],
            "calibration_features": report["walk_forward_calibration"][
                "feature_standardization"
            ],
        }
    if command == "calibrate":
        return report["walk_forward_calibration"]
    if command == "scan":
        return report["ev_candidate_scanner"]
    if command == "recommend":
        return build_recommendation_projection(report)
    if command == "dashboard":
        return report["full_system_surface"]["dashboard"]
    raise ValueError(f"unsupported surface command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
