from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-dual-capture-acceptance.py"
REQUIRED_ORIGINS = ("local_windows_scheduler", "github_actions_0810_utc")


def _write_receipt(
    root: Path,
    day: str,
    origin: str,
    *,
    usable: bool = True,
    corrupt_snapshot_hash: bool = False,
    run_id: str | None = None,
    currency: str = "BTC",
    protocol: str = "immutable_pre_sync_receipt.v1",
) -> Path:
    timestamp = f"{day.replace('-', '')}T081000000Z"
    snapshot = root / "snapshots" / origin / f"{day}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps({"capture_date": day, "capture_origin": origin}),
        encoding="utf-8",
    )
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if corrupt_snapshot_hash:
        snapshot_hash = "0" * 64

    payload = {
        "schema_version": "capture_daily_receipt.v1",
        "protocol": protocol,
        "run_id": run_id or f"capture-daily-btc-{origin}-{timestamp}",
        "provider_run_id": f"provider-{origin}-{day}",
        "status": "capture_complete",
        "currency": currency,
        "capture_origin": origin,
        "capture_time": f"{day}T08:10:00Z",
        "usable_for_validation": usable,
        "usability_reason_codes": [] if usable else ["MARKET_DATA_QUALITY_FAIL"],
        "artifacts": {
            "snapshot": {
                "relative_path": snapshot.relative_to(root).as_posix(),
                "sha256": snapshot_hash,
            }
        },
    }
    receipt = root / "logs" / f"capture-daily-btc-{origin}-{timestamp}.receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    return receipt


def _git(*arguments: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


def _publish_evidence(root: Path, remote: Path) -> None:
    _git("init", "--bare", str(remote), cwd=root.parent)
    _git("init", "-b", "main", cwd=root)
    _git("add", ".", cwd=root)
    _git(
        "-c",
        "user.name=Test Evidence Bot",
        "-c",
        "user.email=evidence@example.invalid",
        "commit",
        "-m",
        "Commit immutable evidence",
        cwd=root,
    )
    _git("remote", "add", "origin", str(remote), cwd=root)
    _git("push", "-u", "origin", "main", cwd=root)


def _new_evidence_root(container: Path) -> tuple[Path, Path]:
    root = container / "evidence"
    remote = container / "evidence.git"
    root.mkdir()
    return root, remote


def _run(
    root: Path,
    as_of: str = "2026-08-12",
    *,
    days: str = "3",
    origins: tuple[str, ...] = REQUIRED_ORIGINS,
) -> subprocess.CompletedProcess[str]:
    origin_arguments = [
        value for origin in origins for value in ("--required-origin", origin)
    ]
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--evidence-root",
            str(root),
            *origin_arguments,
            "--days",
            days,
            "--as-of",
            as_of,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def test_three_consecutive_durable_dual_capture_days_are_accepted() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_version"] == "dual_capture_acceptance.v1"
    assert report["status"] == "accepted"
    assert report["accepted"] is True
    assert report["accepted_dates"] == ["2026-08-10", "2026-08-11", "2026-08-12"]
    assert report["missing"] == []
    assert report["invalid_evidence"] == []
    assert report["durable_git_boundary"]["head"] == report["durable_git_boundary"][
        "remote_head"
    ]
    assert report["durable_git_boundary"]["remote_ref"] == "refs/heads/main"
    assert all(
        set(runs) == {"local_windows_scheduler", "github_actions_0810_utc"}
        for runs in report["accepted_runs"].values()
    )


def test_a_missing_or_unusable_lane_remains_collecting() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
        _write_receipt(root, "2026-08-10", "github_actions_0810_utc")
        _write_receipt(
            root,
            "2026-08-11",
            "github_actions_0810_utc",
            usable=False,
        )
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 10
    report = json.loads(completed.stdout)
    assert report["status"] == "collecting"
    assert report["accepted"] is False
    assert {
        (item["date"], item["origin"], item["reason"])
        for item in report["missing"]
    } == {
        ("2026-08-11", "github_actions_0810_utc", "validation_unusable"),
        ("2026-08-12", "github_actions_0810_utc", "missing_receipt"),
    }


def test_snapshot_hash_mismatch_is_invalid_evidence() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(
                root,
                day,
                "github_actions_0810_utc",
                corrupt_snapshot_hash=day == "2026-08-12",
            )
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert report["status"] == "invalid"
    assert any(
        item["reason"] == "snapshot_hash_mismatch"
        for item in report["invalid_evidence"]
    )


def test_duplicate_run_id_is_invalid_even_when_receipts_are_otherwise_valid() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        duplicate_run_id = "capture-daily-btc-duplicate"
        first = _write_receipt(
            root,
            "2026-08-10",
            "local_windows_scheduler",
            run_id=duplicate_run_id,
        )
        duplicate = root / "logs" / "capture-daily-btc-duplicate.receipt.json"
        duplicate.write_bytes(first.read_bytes())
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            if day != "2026-08-10":
                _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert report["status"] == "invalid"
    assert any(
        item["reason"] == "duplicate_run_id"
        for item in report["invalid_evidence"]
    )


def test_missing_provider_run_id_is_invalid_provenance() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        receipt = _write_receipt(root, "2026-08-10", "local_windows_scheduler")
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload.pop("provider_run_id")
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            if day != "2026-08-10":
                _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert any(
        item["reason"] == "missing_provider_run_id"
        for item in report["invalid_evidence"]
    )


def test_duplicate_provider_run_id_is_invalid_provenance() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        first = _write_receipt(root, "2026-08-10", "local_windows_scheduler")
        first_payload = json.loads(first.read_text(encoding="utf-8"))
        duplicate = _write_receipt(root, "2026-08-10", "github_actions_0810_utc")
        duplicate_payload = json.loads(duplicate.read_text(encoding="utf-8"))
        duplicate_payload["provider_run_id"] = first_payload["provider_run_id"]
        duplicate.write_text(json.dumps(duplicate_payload), encoding="utf-8")
        for day in ("2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert any(
        item["reason"] == "duplicate_provider_run_id"
        for item in report["invalid_evidence"]
    )


def test_plain_directory_cannot_claim_durable_acceptance() -> None:
    with TemporaryDirectory() as temporary_root:
        root = Path(temporary_root)
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            for origin in REQUIRED_ORIGINS:
                _write_receipt(root, day, origin)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert report["invalid_evidence"] == [
        {"path": "<evidence-root>", "reason": "evidence_root_not_git"}
    ]


def test_uncommitted_or_unpushed_evidence_is_rejected() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            for origin in REQUIRED_ORIGINS:
                _write_receipt(root, day, origin)
        _publish_evidence(root, remote)
        marker = root / "logs" / "uncommitted.txt"
        marker.write_text("not durable", encoding="utf-8")

        dirty = _run(root)
        marker.unlink()
        (root / "logs" / "unpushed.txt").write_text("local commit", encoding="utf-8")
        _git("add", ".", cwd=root)
        _git(
            "-c",
            "user.name=Test Evidence Bot",
            "-c",
            "user.email=evidence@example.invalid",
            "commit",
            "-m",
            "Leave evidence unpushed",
            cwd=root,
        )
        unpushed = _run(root)

    assert dirty.returncode == 11
    assert json.loads(dirty.stdout)["invalid_evidence"][0]["reason"] == (
        "evidence_worktree_not_clean"
    )
    assert unpushed.returncode == 11
    assert json.loads(unpushed.stdout)["invalid_evidence"][0]["reason"] == (
        "evidence_remote_out_of_sync"
    )


def test_gitignored_receipt_that_is_absent_from_remote_ref_is_rejected() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            for origin in REQUIRED_ORIGINS:
                _write_receipt(root, day, origin)
        ignored = _write_receipt(root, "2026-08-09", "local_windows_scheduler")
        (root / ".gitignore").write_text(
            f"/{ignored.relative_to(root).as_posix()}\n",
            encoding="utf-8",
        )
        _publish_evidence(root, remote)

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert {
        "path": ignored.relative_to(root).as_posix(),
        "reason": "receipt_not_in_remote_ref",
    } in report["invalid_evidence"]


def test_acceptance_is_fixed_to_btc_immutable_receipts_and_selected_lanes() -> None:
    with TemporaryDirectory() as temporary_root:
        root, remote = _new_evidence_root(Path(temporary_root))
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(
                root,
                day,
                "local_windows_scheduler",
                currency="ETH" if day == "2026-08-10" else "BTC",
            )
            _write_receipt(
                root,
                day,
                "github_actions_0810_utc",
                protocol=(
                    "mutable_summary.v1"
                    if day == "2026-08-10"
                    else "immutable_pre_sync_receipt.v1"
                ),
            )
        _publish_evidence(root, remote)

        invalid_receipts = _run(root)
        too_short = _run(root, days="1")
        substitute_lane = _run(
            root,
            origins=("local_windows_scheduler", "substitute_cloud_lane"),
        )

    assert invalid_receipts.returncode == 11
    reasons = {
        item["reason"] for item in json.loads(invalid_receipts.stdout)["invalid_evidence"]
    }
    assert {"unexpected_currency", "unexpected_protocol"}.issubset(reasons)
    assert too_short.returncode == 2
    assert "--days must be between 3 and 31" in too_short.stderr
    assert substitute_lane.returncode == 2
    assert "required origins must exactly match" in substitute_lane.stderr
