"""Command-line surface for the shared research report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .account_risk import AVAILABLE_ACCOUNT_SCENARIOS
from .alerts import (
    deliver_webhook,
    evaluate_alerts,
    load_alert_state,
    save_alert_state,
    validate_alert_evaluation,
)
from .analysis_run import AnalysisRecord, build_analysis_record
from .backtest import (
    build_fixed_baseline_backtest_report,
    load_backtest_fixture,
)
from .contract import SUPPORTED_MODES, utc_timestamp
from .ev_robustness import DEFAULT_PERIOD_SLICES, build_ev_robustness_report
from .full_surface import build_recommendation_projection
from .historical import build_historical_reconciliation_report, load_historical_fixture
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    build_market_data_status,
    fetch_deribit_option_chain_snapshot,
    load_snapshot_fixture,
    load_underlying_history_fixture,
    parse_timestamp_ms,
    validate_ticker_request_limit,
    write_snapshot_fixture,
)
from .path_risk import (
    build_path_risk_report_from_fixture,
    build_path_risk_report_from_historical_report,
)
from .pnl import build_pnl_evidence_report
from .signal_validation import build_signal_validation_report
from .surface import build_vol_surface_and_candidate_research

# Process exit codes for scheduled analysis / alerts.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_QUALITY_BLOCKED = 10
EXIT_RISK_ALERT = 11
EXIT_HARD_ERROR = 1

# Each tested candidate replays the whole path set once per period slice, so the
# default is a handful rather than the whole eligible table.
DEFAULT_ROBUSTNESS_CANDIDATES = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-report",
        description=(
            "Evidence-first, fail-closed pre-entry research for crypto options. "
            "Output is research-only: it never contains an order instruction or "
            "a tradeable contract count."
        ),
        epilog=(
            "examples:\n"
            "  # Replay a fixed snapshot (deterministic, no network):\n"
            "  crypto-options-report analysis \\\n"
            "      --snapshot-fixture tests/fixtures/deribit_btc_option_chain_snapshot.json \\\n"
            "      --generated-at 2026-07-07T00:01:30Z --compact\n"
            "\n"
            "  # Capture a live public snapshot for offline analysis:\n"
            "  crypto-options-report pull-snapshot --instrument-limit 20 \\\n"
            "      --output artifacts/snapshots/btc-chain.json\n"
            "\n"
            "  # Scheduled run; exit 10 when market data is blocked:\n"
            "  crypto-options-report report \\\n"
            "      --snapshot-fixture artifacts/snapshots/btc-chain.json \\\n"
            "      --output artifacts/reports/latest.json --fail-on-blocked\n"
            "\n"
            "exit codes:\n"
            f"  {EXIT_OK}   success\n"
            f"  {EXIT_HARD_ERROR}   hard error\n"
            f"  {EXIT_USAGE}   usage error\n"
            f"  {EXIT_QUALITY_BLOCKED}  market data blocked or missing (--fail-on-blocked)\n"
            f"  {EXIT_RISK_ALERT}  one or more alerts fired (--fail-on-alert)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    report = subcommands.add_parser("report", help="emit the shared research report")
    _add_report_replay_args(report)
    report.add_argument(
        "--output",
        help="optional path to write JSON (stdout still receives the payload unless --quiet)",
    )
    report.add_argument(
        "--quiet",
        action="store_true",
        help="suppress stdout when --output is set",
    )
    report.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="exit 10 when market data quality is blocked/missing",
    )

    analysis = subcommands.add_parser(
        "analysis",
        help="emit the immutable pre-entry AnalysisRecord",
    )
    _add_report_replay_args(analysis)
    analysis.add_argument("--output", help="optional path to write JSON")

    pull = subcommands.add_parser(
        "pull-snapshot",
        help="capture a live Deribit snapshot to disk for offline analysis",
    )
    pull.add_argument("--currency", default="BTC")
    pull.add_argument("--deribit-base-url", default=DEFAULT_DERIBIT_BASE_URL)
    pull.add_argument("--instrument-limit", type=_parse_ticker_request_limit)
    pull_target = pull.add_mutually_exclusive_group(required=True)
    pull_target.add_argument(
        "--output",
        help="path to write the snapshot JSON",
    )
    pull_target.add_argument(
        "--output-dir",
        help=(
            "directory to append a capture to, named by capture time; use this "
            "for the repeated captures validate-signal consumes"
        ),
    )
    pull.add_argument("--compact", action="store_true")

    alert = subcommands.add_parser(
        "alert-eval",
        help="evaluate research-only risk alerts from a report or snapshot",
    )
    _add_report_replay_args(alert)
    alert.add_argument(
        "--report-json",
        help="optional prebuilt research_report JSON path (skips live rebuild)",
    )
    alert.add_argument(
        "--state-file",
        help="alert debounce state JSON path",
    )
    alert.add_argument(
        "--cooldown-sec",
        type=int,
        default=1800,
        help="per-fingerprint cooldown seconds (default 1800)",
    )
    alert.add_argument(
        "--webhook-url",
        help="optional webhook URL for delivery",
    )
    alert.add_argument(
        "--webhook-secret-env",
        default="ALERT_WEBHOOK_SECRET",
        help="environment variable containing the optional HMAC secret",
    )
    alert.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate only; do not persist state or POST webhook",
    )
    alert.add_argument(
        "--allow-opportunity-alerts",
        action="store_true",
        help="enable candidate watch alerts only when evidence gates pass (default off)",
    )
    alert.add_argument(
        "--fail-on-alert",
        action="store_true",
        help="exit 11 when one or more alerts fire",
    )
    alert.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="exit 10 when market data quality is blocked/missing",
    )
    alert.add_argument("--output", help="optional path to write alert evaluation JSON")

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

    validate_signal = subcommands.add_parser(
        "validate-signal",
        help="measure whether the ranking signals predict anything",
    )
    validate_signal.add_argument(
        "--snapshot-dir",
        required=True,
        help=(
            "directory of chain snapshots captured over time; one file per "
            "capture, as written by pull-snapshot"
        ),
    )
    validate_signal.add_argument(
        "--underlying-history-fixture",
        required=True,
        help="underlying price history supplying the settlement proxy",
    )
    validate_signal.add_argument(
        "--generated-at",
        help="optional ISO timestamp used to keep report output deterministic",
    )
    validate_signal.add_argument("--output", help="optional path to write JSON")
    validate_signal.add_argument("--compact", action="store_true")
    validate_signal.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="exit 10 when the sample is too small to publish statistics",
    )

    ev_robustness = subcommands.add_parser(
        "ev-robustness",
        help="test whether an expected-value sign survives period and execution choices",
    )
    ev_robustness.add_argument(
        "--snapshot-fixture",
        required=True,
        help="chain snapshot the candidates are read from",
    )
    ev_robustness.add_argument(
        "--underlying-history-fixture",
        required=True,
        help="underlying price history the expected value is measured against",
    )
    ev_robustness.add_argument(
        "--candidates",
        type=int,
        default=DEFAULT_ROBUSTNESS_CANDIDATES,
        help=(
            "how many eligible candidates to test "
            f"(default {DEFAULT_ROBUSTNESS_CANDIDATES}); each one replays the "
            "path set once per period slice"
        ),
    )
    ev_robustness.add_argument(
        "--period-slices",
        type=int,
        default=DEFAULT_PERIOD_SLICES,
        help=f"contiguous history slices (default {DEFAULT_PERIOD_SLICES})",
    )
    ev_robustness.add_argument(
        "--generated-at",
        help="optional ISO timestamp used to keep report output deterministic",
    )
    ev_robustness.add_argument("--output", help="optional path to write JSON")
    ev_robustness.add_argument("--compact", action="store_true")

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
        surface_parser.add_argument("--output", help="optional path to write JSON")
        surface_parser.add_argument(
            "--fail-on-blocked",
            action="store_true",
            help="exit 10 when market data quality is blocked/missing",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "pull-snapshot":
            return _cmd_pull_snapshot(args)
        if args.command == "alert-eval":
            return _cmd_alert_eval(args)
        if args.command == "report":
            report = _build_report_from_args(args)
            _emit_json(report, compact=args.compact, output=args.output, quiet=args.quiet)
            if args.fail_on_blocked and _market_blocked(report):
                return EXIT_QUALITY_BLOCKED
            return EXIT_OK
        if args.command == "analysis":
            record = _build_analysis_record_from_args(args)
            _emit_json(
                record.to_dict(),
                compact=args.compact,
                output=args.output,
            )
            return EXIT_OK

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
            _emit_json(
                payload,
                compact=args.compact,
                output=getattr(args, "output", None),
                quiet=False,
            )
            if getattr(args, "fail_on_blocked", False) and _market_blocked(report):
                return EXIT_QUALITY_BLOCKED
            return EXIT_OK

        if args.command in {"backtest", "baseline-backtest"}:
            report = build_fixed_baseline_backtest_report(
                load_backtest_fixture(args.fixture),
                generated_at=args.generated_at,
            )
            _emit_json(report, compact=args.compact)
            return EXIT_OK

        if args.command == "validate-signal":
            return _cmd_validate_signal(args)

        if args.command == "ev-robustness":
            return _cmd_ev_robustness(args)

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
            _emit_json(report, compact=args.compact)
            return EXIT_OK
    except Exception as exc:
        print(
            json.dumps(
                {"error": str(exc), "type": type(exc).__name__},
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return EXIT_HARD_ERROR

    parser.error(f"unsupported command: {args.command}")
    return EXIT_USAGE


def _cmd_pull_snapshot(args: argparse.Namespace) -> int:
    snapshot = fetch_deribit_option_chain_snapshot(
        currency=args.currency,
        base_url=args.deribit_base_url,
        instrument_limit=args.instrument_limit,
        include_feed_graph=True,
    )
    path = write_snapshot_fixture(_snapshot_output_path(args, snapshot), snapshot)
    payload = {
        "schema_version": "snapshot_capture.v1",
        "path": str(path),
        "captured_at": snapshot.get("captured_at"),
        "source": snapshot.get("source"),
        "row_count": len(snapshot.get("rows") or []),
        "fetch_errors": len(snapshot.get("fetch_errors") or []),
        "feeds": list((snapshot.get("feeds") or {}).keys()),
        "instrument_metadata_count": snapshot.get("instrument_metadata_count"),
        "research_only": True,
    }
    _emit_json(payload, compact=args.compact)
    if snapshot.get("fetch_errors") and not snapshot.get("rows"):
        return EXIT_QUALITY_BLOCKED
    return EXIT_OK


def _cmd_ev_robustness(args: argparse.Namespace) -> int:
    """Test the leading candidates' expected-value sign against its assumptions.

    Kept out of the report's hot path on purpose: each candidate replays the
    whole path set once per period slice, so folding it into every projection
    would multiply the cost of a routine run by the slice count for a diagnostic
    nobody reads on every run.
    """
    snapshot = load_snapshot_fixture(args.snapshot_fixture)
    history = load_underlying_history_fixture(args.underlying_history_fixture)
    generated_at = args.generated_at or str(snapshot.get("captured_at") or utc_timestamp())

    data_status = build_market_data_status(
        snapshot, now_ms=parse_timestamp_ms(generated_at)
    )
    _, candidate_research = build_vol_surface_and_candidate_research(
        market_snapshot=snapshot,
        generated_at=generated_at,
        data_status=data_status,
        pnl_evidence=build_pnl_evidence_report(),
    )

    eligible = [
        candidate
        for table in candidate_research.get("structure_types") or []
        for candidate in (candidate_research.get(table) or {}).get("eligible") or []
    ]
    reports = [
        build_ev_robustness_report(
            candidate=candidate,
            structure_type=str(candidate.get("structure_type") or ""),
            underlying_history=history,
            generated_at=generated_at,
            period_slices=args.period_slices,
        )
        for candidate in eligible[: max(args.candidates, 0)]
    ]

    verdicts: dict[str, int] = {}
    for report in reports:
        code = (report.get("verdict") or {}).get("code") or report.get("reason_code")
        verdicts[str(code)] = verdicts.get(str(code), 0) + 1

    payload = {
        "schema_version": "ev_robustness_batch.v1",
        "generated_at": generated_at,
        "research_only": True,
        "snapshot_captured_at": snapshot.get("captured_at"),
        "market_data_status": data_status["status"],
        "eligible_candidate_count": len(eligible),
        "tested_candidate_count": len(reports),
        "verdict_counts": dict(sorted(verdicts.items())),
        "candidates": reports,
    }
    _emit_json(payload, compact=args.compact, output=args.output)
    return EXIT_OK


def _snapshot_output_path(
    args: argparse.Namespace, snapshot: dict[str, Any]
) -> str:
    """Resolve where this capture is written.

    The series form names the file after the capture timestamp rather than a
    counter, so a repeated capture can never overwrite an earlier one and the
    directory sorts chronologically without a manifest.
    """
    if args.output:
        return args.output
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    captured_at = str(snapshot.get("captured_at") or utc_timestamp())
    stamp = captured_at.replace(":", "").replace("-", "").replace("Z", "")
    currency = str(snapshot.get("currency") or "unknown").lower()
    return str(directory / f"{currency}-chain-{stamp}.json")


def _cmd_validate_signal(args: argparse.Namespace) -> int:
    """Measure the ranking signals against a directory of captured snapshots.

    The snapshots are loaded through the same guarded loader the report uses, so
    a directory holding something other than a snapshot fails loudly here rather
    than becoming a silently smaller sample.
    """
    directory = Path(args.snapshot_dir)
    if not directory.is_dir():
        raise ValueError(f"snapshot dir is not a directory: {args.snapshot_dir}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"no snapshot JSON files found in {args.snapshot_dir}")

    snapshots = [load_snapshot_fixture(path) for path in paths]
    history = load_underlying_history_fixture(args.underlying_history_fixture)
    report = build_signal_validation_report(
        snapshots=snapshots,
        underlying_history=history,
        generated_at=args.generated_at or utc_timestamp(),
    )
    _emit_json(report, compact=args.compact, output=args.output)
    if args.fail_on_blocked and report.get("status") != "measured":
        return EXIT_QUALITY_BLOCKED
    return EXIT_OK


def _cmd_alert_eval(args: argparse.Namespace) -> int:
    if args.report_json:
        report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
        alert_source: dict[str, Any] | AnalysisRecord = report
    else:
        record = _build_analysis_record_from_args(args)
        report = record.project_research_report_v1()
        alert_source = record
    state = load_alert_state(args.state_file)
    evaluation = evaluate_alerts(
        alert_source,
        previous_state=state,
        cooldown_sec=args.cooldown_sec,
        allow_opportunity_alerts=args.allow_opportunity_alerts,
    )
    errors = validate_alert_evaluation(evaluation)
    if errors:
        raise ValueError("; ".join(errors))

    delivery = None
    webhook_ok = True
    if args.webhook_url:
        webhook_secret = (
            os.environ.get(args.webhook_secret_env) if args.webhook_secret_env else None
        )
        delivery = deliver_webhook(
            evaluation,
            url=args.webhook_url,
            secret=webhook_secret,
            dry_run=args.dry_run or not bool(evaluation.get("events")),
        )
        evaluation = dict(evaluation)
        evaluation["webhook"] = delivery
        # Failed delivery must not advance cooldown; operator can retry the same risk.
        webhook_ok = delivery.get("status") in {"delivered", "dry_run"}

    if args.state_file and not args.dry_run and webhook_ok:
        save_alert_state(args.state_file, evaluation["state"])
    elif args.state_file and not args.dry_run and not webhook_ok:
        evaluation = dict(evaluation)
        evaluation["state_persisted"] = False
        evaluation["state_persist_skip_reason"] = "webhook_delivery_failed"

    _emit_json(evaluation, compact=args.compact, output=args.output)
    if args.webhook_url and not webhook_ok:
        return EXIT_HARD_ERROR
    if args.fail_on_alert and evaluation.get("events"):
        return EXIT_RISK_ALERT
    if args.fail_on_blocked and _market_blocked(report):
        return EXIT_QUALITY_BLOCKED
    return EXIT_OK


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
    parser.add_argument("--instrument-limit", type=_parse_ticker_request_limit)
    parser.add_argument(
        "--account-scenario",
        choices=AVAILABLE_ACCOUNT_SCENARIOS,
        help="optional replayable account scenario name",
    )
    parser.add_argument(
        "--underlying-history-fixture",
        help=(
            "replay recorded underlying price history; required for absolute "
            "expected value, which is otherwise reported as unavailable"
        ),
    )
    parser.add_argument("--generated-at")


def _build_report_from_args(args: argparse.Namespace) -> dict:
    return _build_analysis_record_from_args(args).project_research_report_v1()


def _build_analysis_record_from_args(args: argparse.Namespace) -> AnalysisRecord:
    market_snapshot = None
    if getattr(args, "snapshot_fixture", None):
        market_snapshot = load_snapshot_fixture(args.snapshot_fixture)
    elif getattr(args, "live_deribit", False):
        market_snapshot = fetch_deribit_option_chain_snapshot(
            currency=args.currency,
            base_url=args.deribit_base_url,
            instrument_limit=args.instrument_limit,
            include_feed_graph=True,
        )
    else:
        # Without a market source the report is honestly, but entirely, empty.
        # Say so, otherwise a forgotten flag looks like a broken tool.
        print(
            "note: no --snapshot-fixture and no --live-deribit; market evidence "
            "will be reported as missing and every gate will stay closed. "
            "For a populated example run:\n"
            "  crypto-options-report report --snapshot-fixture "
            "tests/fixtures/deribit_btc_option_chain_snapshot.json "
            "--generated-at 2026-07-07T00:01:30Z",
            file=sys.stderr,
        )

    underlying_history = None
    if getattr(args, "underlying_history_fixture", None):
        underlying_history = load_underlying_history_fixture(
            args.underlying_history_fixture
        )

    return build_analysis_record(
        mode=args.mode,
        market_snapshot=market_snapshot,
        account_scenario=args.account_scenario,
        generated_at=args.generated_at,
        underlying_history=underlying_history,
    )


def _parse_ticker_request_limit(value: str) -> int:
    try:
        candidate = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("instrument_limit must be an integer") from exc
    try:
        return validate_ticker_request_limit(candidate)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
        calibration = report["walk_forward_calibration"]
        return {
            "schema_version": "feature_status.v1",
            "regime": report["permission_state"],
            "calibration_features": {
                "status": calibration.get("status", "unavailable"),
                "evidence_class": calibration.get("evidence_class", "unavailable"),
                "reason_code": calibration.get(
                    "reason_code", "CALIBRATION_EVIDENCE_UNAVAILABLE"
                ),
                "policy_doc": calibration.get("policy_doc"),
                "features": calibration.get("feature_standardization") or [],
            },
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


def _emit_json(
    payload: Any,
    *,
    compact: bool = False,
    output: str | None = None,
    quiet: bool = False,
) -> None:
    text = json.dumps(
        payload,
        indent=None if compact else 2,
        sort_keys=True,
        allow_nan=False,
    )
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if not quiet or not output:
        sys.stdout.write(text)
        sys.stdout.write("\n")


def _market_blocked(report: dict[str, Any]) -> bool:
    status = (report.get("data_status") or {}).get("status")
    return status in {"blocked", "missing"}


if __name__ == "__main__":
    raise SystemExit(main())
