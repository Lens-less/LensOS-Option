"""Isolated entry point for one bounded local backtest job."""

from __future__ import annotations

import argparse
import json
import time
from typing import Sequence

from .evidence_store import run_backtest_evidence_job


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--expected-fixture-sha256", required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--timeout-seconds", required=True, type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = run_backtest_evidence_job(
            fixture_path=args.fixture,
            artifact_dir=args.artifact_dir,
            generated_at=args.generated_at,
            expected_fixture_sha256=args.expected_fixture_sha256,
            deadline_monotonic=time.monotonic() + args.timeout_seconds,
            update_default_pointer=False,
        )
    except TimeoutError:
        print(json.dumps({"status": "failed", "reason_code": "BACKTEST_JOB_TIMEOUT"}))
        return 3
    except (FileNotFoundError, ValueError) as exc:
        reason_code = (
            "HISTORICAL_FIXTURE_CHANGED"
            if "changed after job admission" in str(exc)
            else "HISTORICAL_FIXTURE_REJECTED"
        )
        print(json.dumps({"status": "failed", "reason_code": reason_code}))
        return 2
    except BaseException:
        print(json.dumps({"status": "failed", "reason_code": "BACKTEST_JOB_FAILED"}))
        return 1
    print(json.dumps({"status": "succeeded", "report_id": artifact["report_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
