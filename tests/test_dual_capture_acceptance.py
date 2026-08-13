from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-dual-capture-acceptance.py"


def _write_receipt(
    root: Path,
    day: str,
    origin: str,
    *,
    usable: bool = True,
    corrupt_snapshot_hash: bool = False,
    run_id: str | None = None,
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
        "protocol": "immutable_pre_sync_receipt.v1",
        "run_id": run_id or f"capture-daily-btc-{origin}-{timestamp}",
        "provider_run_id": f"provider-{origin}-{day}",
        "status": "capture_complete",
        "currency": "BTC",
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


def _run(root: Path, as_of: str = "2026-08-12") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--evidence-root",
            str(root),
            "--required-origin",
            "local_windows_scheduler",
            "--required-origin",
            "github_actions_0810_utc",
            "--days",
            "3",
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
        root = Path(temporary_root)
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")

        completed = _run(root)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_version"] == "dual_capture_acceptance.v1"
    assert report["status"] == "accepted"
    assert report["accepted"] is True
    assert report["accepted_dates"] == ["2026-08-10", "2026-08-11", "2026-08-12"]
    assert report["missing"] == []
    assert report["invalid_evidence"] == []
    assert all(
        set(runs) == {"local_windows_scheduler", "github_actions_0810_utc"}
        for runs in report["accepted_runs"].values()
    )


def test_a_missing_or_unusable_lane_remains_collecting() -> None:
    with TemporaryDirectory() as temporary_root:
        root = Path(temporary_root)
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
        _write_receipt(root, "2026-08-10", "github_actions_0810_utc")
        _write_receipt(
            root,
            "2026-08-11",
            "github_actions_0810_utc",
            usable=False,
        )

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
        root = Path(temporary_root)
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(
                root,
                day,
                "github_actions_0810_utc",
                corrupt_snapshot_hash=day == "2026-08-12",
            )

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
        root = Path(temporary_root)
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
        root = Path(temporary_root)
        receipt = _write_receipt(root, "2026-08-10", "local_windows_scheduler")
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload.pop("provider_run_id")
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            if day != "2026-08-10":
                _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert any(
        item["reason"] == "missing_provider_run_id"
        for item in report["invalid_evidence"]
    )


def test_duplicate_provider_run_id_is_invalid_provenance() -> None:
    with TemporaryDirectory() as temporary_root:
        root = Path(temporary_root)
        first = _write_receipt(root, "2026-08-10", "local_windows_scheduler")
        first_payload = json.loads(first.read_text(encoding="utf-8"))
        duplicate = _write_receipt(root, "2026-08-10", "github_actions_0810_utc")
        duplicate_payload = json.loads(duplicate.read_text(encoding="utf-8"))
        duplicate_payload["provider_run_id"] = first_payload["provider_run_id"]
        duplicate.write_text(json.dumps(duplicate_payload), encoding="utf-8")
        for day in ("2026-08-11", "2026-08-12"):
            _write_receipt(root, day, "local_windows_scheduler")
            _write_receipt(root, day, "github_actions_0810_utc")

        completed = _run(root)

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert any(
        item["reason"] == "duplicate_provider_run_id"
        for item in report["invalid_evidence"]
    )
