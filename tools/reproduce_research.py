"""Reproduce a blocked research case using only installed package resources.

No network, account credentials, promotion artifacts, or research-state writes
are needed. The default evaluation clock belongs to the bundled snapshot;
successful reproduction does not mean that its research evidence is trusted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from crypto_options_report._canonical import canonical_json_text, canonical_sha256
from crypto_options_report.analysis_run import (
    build_analysis_record,
    validate_analysis_record,
)
from crypto_options_report.market_data import (
    load_snapshot_fixture,
    load_underlying_history_fixture,
)

FIXED_CLOCK = "2026-07-07T00:01:30Z"
SNAPSHOT_RESOURCE = "demo-snapshot.json"
HISTORY_RESOURCE = "demo-underlying-history.json"


def build_case(generated_at: str = FIXED_CLOCK) -> dict[str, Any]:
    """Return the actual analysis result and its reproducibility envelope."""
    clock = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if clock.tzinfo is None:
        raise ValueError("generated-at must include an explicit timezone")
    evaluation_clock = clock.astimezone(UTC).isoformat().replace("+00:00", "Z")
    resources = files("crypto_options_report").joinpath("resources")
    with as_file(resources.joinpath(SNAPSHOT_RESOURCE)) as snapshot_path:
        snapshot = load_snapshot_fixture(snapshot_path)
    with as_file(resources.joinpath(HISTORY_RESOURCE)) as history_path:
        history = load_underlying_history_fixture(history_path)

    record = build_analysis_record(
        generated_at=evaluation_clock,
        market_snapshot=snapshot,
        underlying_history=history,
        persist_paper_ledger=False,
    )
    errors = validate_analysis_record(record)
    if errors:
        raise ValueError(f"Analysis contract failed: {', '.join(errors)}")
    manifest = record.manifest.to_dict()
    decisions = [decision.to_dict() for decision in record.entry_admission_decisions]
    brief = record.project_strategy_brief_v1()
    if brief["execution_allowed"] is not False or any(
        item["execution_allowed"] is not False for item in decisions
    ):
        raise ValueError("Offline case must preserve execution_allowed=false")

    missing = [
        name for name in (
            "account_evidence_hash", "historical_artifact_hash", "pre_entry_risk_evidence_hash",
        ) if manifest.get(name) is None
    ]
    if manifest.get("model_bundle_id") == "model-bundle:unavailable":
        missing.append("promoted_model_bundle")
    payload = {
        "schema_version": "offline_research_case.v1",
        "evaluation_clock": evaluation_clock,
        "inputs": {
            "market_snapshot": {
                "resource": f"packaged:{SNAPSHOT_RESOURCE}",
                "sha256": canonical_sha256(snapshot),
                "captured_at": snapshot["captured_at"],
                "source": snapshot["source"],
            },
            "underlying_history": {
                "resource": f"packaged:{HISTORY_RESOURCE}",
                "sha256": canonical_sha256(history),
                "observation_count": history["observation_count"],
                "source": history["source"],
            },
        },
        "analysis_run_id": record.analysis_run_id,
        "analysis_output_hash": record.output_hash,
        "manifest": manifest,
        "trust_verdict": record.trust_verdict,
        "reason_codes": list(record.global_reason_codes),
        "evidence_lineage": [item.to_dict() for item in record.evidence_lineage],
        "decisions": decisions,
        "missing_evidence": missing,
        "strategy_brief": brief,
        "research_only": True,
        "execution_allowed": False,
        "interpretation": (
            "A matching replay proves repeatability for these inputs, clock, and build only. "
            "It does not authenticate the snapshot, validate historical performance, "
            "calibrate a forecast, or authorize execution. Missing evidence is reported "
            "from this analysis manifest; it is not a complete promotion checklist."
        ),
    }
    return {**payload, "case_sha256": canonical_sha256(payload)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", default=FIXED_CLOCK, help="explicit evaluation clock; default: %(default)s")
    parser.add_argument("--check", action="store_true", help="evaluate twice and fail if the complete cases differ")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--output", type=Path, help="write this standalone case JSON (no research-state persistence)")
    output.add_argument("--verify", type=Path, help="reproduce and compare an existing case; mismatch exits 1")
    args = parser.parse_args(argv)
    try:
        result = build_case(args.generated_at)
        if args.check and canonical_json_text(result) != canonical_json_text(build_case(args.generated_at)):
            print("Repeatability failed: identical inputs, clock, and build produced different cases.", file=sys.stderr)
            return 1
        if args.verify:
            previous = json.loads(args.verify.read_text(encoding="utf-8-sig"))
            if canonical_json_text(previous) != canonical_json_text(result):
                print("Saved case does not match the current inputs, clock, and build.", file=sys.stderr)
                return 1
            print(f"Reproduced case matches: {result['case_sha256']}")
            return 0
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        if args.check:
            print("repeatability=PASS (two complete evaluations)")
        statuses = ",".join(sorted({item["status"] for item in result["decisions"]}))
        print(f"trust={result['trust_verdict']} action={result['strategy_brief']['action']} admission={statuses} execution_allowed=false")
        print(f"reasons={','.join(result['reason_codes'])}")
        print(f"missing_evidence={','.join(result['missing_evidence'])}")
        print(f"case_sha256={result['case_sha256']}")
        if args.output:
            print(f"Saved standalone case: {args.output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Research case failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
