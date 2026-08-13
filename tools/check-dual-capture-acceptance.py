#!/usr/bin/env python3
"""Fail-closed acceptance check for durable independent capture lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ORIGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PROVIDER_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ORIGINS = ("local_windows_scheduler", "github_actions_0810_utc")
EXPECTED_CURRENCY = "BTC"
EXPECTED_PROTOCOL = "immutable_pre_sync_receipt.v1"


class EvidenceBoundaryError(RuntimeError):
    """The selected evidence tree is not proven durable in its remote Git ref."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Require consecutive usable capture receipts from every named lane. "
            "The evidence root itself is the durable-sync boundary."
        )
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        required=True,
        help="checked-out private evidence repository containing immutable receipts",
    )
    parser.add_argument(
        "--required-origin",
        action="append",
        required=True,
        help="required capture_origin; repeat for every independent lane",
    )
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="final UTC calendar date in the acceptance window (YYYY-MM-DD)",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(
    root: Path, *arguments: str, accepted: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode not in accepted:
        raise EvidenceBoundaryError("evidence_git_command_failed")
    return completed


def _verify_durable_git_boundary(root: Path) -> dict[str, str]:
    try:
        top_level = Path(
            _git(root, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
    except (EvidenceBoundaryError, OSError):
        raise EvidenceBoundaryError("evidence_root_not_git") from None
    if top_level != root:
        raise EvidenceBoundaryError("evidence_root_not_git_top_level")
    if _git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        raise EvidenceBoundaryError("evidence_worktree_not_clean")
    branch_result = _git(
        root, "symbolic-ref", "--quiet", "--short", "HEAD", accepted=(0, 1)
    )
    branch = branch_result.stdout.strip()
    if branch_result.returncode != 0 or not branch:
        raise EvidenceBoundaryError("evidence_head_not_named_branch")
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    remote_result = _git(
        root,
        "ls-remote",
        "--refs",
        "origin",
        f"refs/heads/{branch}",
        accepted=(0,),
    )
    remote_lines = [line for line in remote_result.stdout.splitlines() if line.strip()]
    if len(remote_lines) != 1:
        raise EvidenceBoundaryError("evidence_remote_ref_missing")
    fields = remote_lines[0].split("\t", 1)
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}":
        raise EvidenceBoundaryError("evidence_remote_ref_invalid")
    remote_head = fields[0]
    if remote_head != head:
        raise EvidenceBoundaryError("evidence_remote_out_of_sync")
    return {
        "branch": branch,
        "head": head,
        "remote": "origin",
        "remote_ref": f"refs/heads/{branch}",
        "remote_head": remote_head,
    }


def _remote_blob_matches(root: Path, revision: str, path: Path) -> bool:
    relative_path = path.relative_to(root).as_posix()
    remote_blob = _git(
        root,
        "rev-parse",
        "--verify",
        f"{revision}:{relative_path}",
        accepted=(0, 128),
    )
    if remote_blob.returncode != 0:
        return False
    local_blob = _git(
        root, "hash-object", f"--path={relative_path}", "--", str(path)
    ).stdout.strip()
    return remote_blob.stdout.strip() == local_blob


def _safe_evidence_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _capture_date(receipt: dict[str, Any]) -> date | None:
    raw = receipt.get("capture_time")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).date()


def _validate_receipt(
    root: Path, path: Path, payload: object, *, revision: str
) -> tuple[dict[str, Any] | None, str | None]:
    if not _remote_blob_matches(root, revision, path):
        return None, "receipt_not_in_remote_ref"
    if not isinstance(payload, dict):
        return None, "receipt_not_object"
    if payload.get("schema_version") != "capture_daily_receipt.v1":
        return None, "unexpected_schema"
    if payload.get("protocol") != EXPECTED_PROTOCOL:
        return None, "unexpected_protocol"
    if payload.get("status") != "capture_complete":
        return None, "capture_not_complete"
    if payload.get("currency") != EXPECTED_CURRENCY:
        return None, "unexpected_currency"
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None, "missing_run_id"
    provider_run_id = payload.get("provider_run_id")
    if not isinstance(provider_run_id, str) or not provider_run_id.strip():
        return None, "missing_provider_run_id"
    if PROVIDER_RUN_ID_PATTERN.fullmatch(provider_run_id) is None:
        return None, "invalid_provider_run_id"
    origin = payload.get("capture_origin")
    if not isinstance(origin, str) or ORIGIN_PATTERN.fullmatch(origin) is None:
        return None, "invalid_capture_origin"
    if _capture_date(payload) is None:
        return None, "invalid_capture_time"
    artifacts = payload.get("artifacts")
    snapshot = artifacts.get("snapshot") if isinstance(artifacts, dict) else None
    if not isinstance(snapshot, dict):
        return None, "snapshot_record_missing"
    snapshot_path = _safe_evidence_path(root, snapshot.get("relative_path"))
    if snapshot_path is None:
        return None, "snapshot_path_invalid"
    if not snapshot_path.is_file():
        return None, "snapshot_file_missing"
    if not _remote_blob_matches(root, revision, snapshot_path):
        return None, "snapshot_not_in_remote_ref"
    expected_hash = snapshot.get("sha256")
    if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
        return None, "snapshot_hash_invalid"
    if _sha256(snapshot_path) != expected_hash:
        return None, "snapshot_hash_mismatch"
    validated = dict(payload)
    validated["_source_path"] = path.relative_to(root).as_posix()
    validated["_snapshot_path"] = snapshot_path.relative_to(root).as_posix()
    return validated, None


def _read_receipts(
    root: Path, *, revision: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    receipts: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for path in sorted(root.rglob("capture-daily-*.receipt.json")):
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid.append(
                {"path": path.relative_to(root).as_posix(), "reason": "invalid_json"}
            )
            continue
        validated, reason = _validate_receipt(root, path, payload, revision=revision)
        if reason is not None:
            invalid.append({"path": path.relative_to(root).as_posix(), "reason": reason})
        elif validated is not None:
            receipts.append(validated)

    run_ids = Counter(str(receipt["run_id"]) for receipt in receipts)
    for run_id, count in sorted(run_ids.items()):
        if count > 1:
            invalid.append(
                {
                    "path": "<multiple receipts>",
                    "reason": "duplicate_run_id",
                    "run_id": run_id,
                }
            )
    provider_run_ids = Counter(str(receipt["provider_run_id"]) for receipt in receipts)
    for provider_run_id, count in sorted(provider_run_ids.items()):
        if count > 1:
            invalid.append(
                {
                    "path": "<multiple receipts>",
                    "reason": "duplicate_provider_run_id",
                    "provider_run_id": provider_run_id,
                }
            )
    return receipts, invalid


def build_report(
    receipts: list[dict[str, Any]],
    *,
    origins: list[str],
    days: int,
    as_of: date | None,
    invalid_evidence: list[dict[str, str]],
) -> dict[str, Any]:
    indexed: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(list)
    observed_dates: list[date] = []
    for receipt in receipts:
        capture_day = _capture_date(receipt)
        origin = receipt.get("capture_origin")
        if capture_day is None or not isinstance(origin, str):
            continue
        indexed[(capture_day, origin)].append(receipt)
        observed_dates.append(capture_day)

    final_day = as_of or (max(observed_dates) if observed_dates else date.today())
    acceptance_days = [
        final_day - timedelta(days=offset) for offset in reversed(range(days))
    ]
    missing: list[dict[str, str]] = []
    accepted_runs: dict[str, dict[str, dict[str, str]]] = {}
    for capture_day in acceptance_days:
        day_key = capture_day.isoformat()
        accepted_runs[day_key] = {}
        for origin in origins:
            candidates = indexed.get((capture_day, origin), [])
            qualifying = next(
                (
                    candidate
                    for candidate in reversed(candidates)
                    if candidate.get("usable_for_validation") is True
                ),
                None,
            )
            if qualifying is None:
                missing.append(
                    {
                        "date": day_key,
                        "origin": origin,
                        "reason": "validation_unusable" if candidates else "missing_receipt",
                    }
                )
                continue
            accepted_runs[day_key][origin] = {
                "run_id": str(qualifying["run_id"]),
                "provider_run_id": str(qualifying.get("provider_run_id") or ""),
                "receipt": str(qualifying["_source_path"]),
                "snapshot": str(qualifying["_snapshot_path"]),
                "snapshot_sha256": str(qualifying["artifacts"]["snapshot"]["sha256"]),
            }

    accepted = not missing and not invalid_evidence
    status = "accepted" if accepted else ("invalid" if invalid_evidence else "collecting")
    return {
        "schema_version": "dual_capture_acceptance.v1",
        "status": status,
        "accepted": accepted,
        "evidence_root": "<redacted-by-caller>",
        "required_origins": origins,
        "required_consecutive_days": days,
        "as_of": final_day.isoformat(),
        "accepted_dates": [item.isoformat() for item in acceptance_days] if accepted else [],
        "accepted_runs": accepted_runs,
        "missing": missing,
        "invalid_evidence": invalid_evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = args.evidence_root.resolve()
    if not root.is_dir():
        parser.error(f"evidence root is not a directory: {root}")
    origins = list(dict.fromkeys(args.required_origin))
    if len(origins) != len(REQUIRED_ORIGINS) or set(origins) != set(REQUIRED_ORIGINS):
        parser.error(
            "required origins must exactly match: " + ", ".join(REQUIRED_ORIGINS)
        )
    origins = list(REQUIRED_ORIGINS)
    if any(ORIGIN_PATTERN.fullmatch(origin) is None for origin in origins):
        parser.error("required origins must be valid 1-64 character lane identifiers")
    if not 3 <= args.days <= 31:
        parser.error("--days must be between 3 and 31")

    try:
        durability = _verify_durable_git_boundary(root)
    except EvidenceBoundaryError as exc:
        durability = None
        receipts = []
        invalid_evidence = [{"path": "<evidence-root>", "reason": exc.reason}]
    else:
        receipts, invalid_evidence = _read_receipts(
            root, revision=durability["remote_head"]
        )
    report = build_report(
        receipts,
        origins=origins,
        days=args.days,
        as_of=args.as_of,
        invalid_evidence=invalid_evidence,
    )
    report["evidence_root"] = str(root)
    report["durable_git_boundary"] = durability
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    if report["accepted"]:
        return 0
    return 11 if report["invalid_evidence"] else 10


if __name__ == "__main__":
    raise SystemExit(main())
