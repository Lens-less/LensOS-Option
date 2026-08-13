from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-publish-workflow-gate.py"


def _run(**overrides: str) -> subprocess.CompletedProcess[str]:
    values = {
        "CAPTURE_OUTCOME": "success",
        "BUNDLE_BUILD_OUTCOME": "success",
        "BUNDLE_BOUNDARY_OUTCOME": "success",
        "EVIDENCE_SYNC_ENABLED": "true",
        "EVIDENCE_SYNC_READY": "true",
        "FAILURE_WEBHOOK_READY": "true",
        "SUCCESS_HEARTBEAT_READY": "true",
        "DEPLOY_DECISION": "SUSPENDED",
        "SITE_ORIGIN_READY": "false",
        "PUBLISH_OUTCOME": "skipped",
        "RECEIPT_OUTCOME": "skipped",
        "MONITORING_READY": "false",
        "DEPLOY_DECISION_ISSUE": "docs/operations/public-deployment-suspension.md",
    }
    values.update(overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={**os.environ, **values},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def test_suspended_deploy_passes_capture_admission_without_site_or_monitor() -> None:
    completed = _run()

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "capture_lane_accepted_deploy_suspended"
    assert report["capture_lane_accepted"] is True
    assert report["publication_attempted"] is False


def test_suspended_deploy_still_requires_durable_evidence_sync() -> None:
    completed = _run(EVIDENCE_SYNC_ENABLED="false", EVIDENCE_SYNC_READY="false")

    assert completed.returncode == 10
    report = json.loads(completed.stdout)
    assert report["status"] == "blocked"
    assert report["reason_code"] == "EVIDENCE_SYNC_DISABLED"


def test_nonblank_but_invalid_failure_webhook_is_rejected_by_readiness() -> None:
    completed = _run(FAILURE_WEBHOOK_READY="false")

    assert completed.returncode == 10
    report = json.loads(completed.stdout)
    assert report["reason_code"] == "FAILURE_WEBHOOK_NOT_READY"


def test_active_publication_still_requires_site_publish_receipt_and_monitor() -> None:
    completed = _run(DEPLOY_DECISION="ACTIVE")

    assert completed.returncode == 10
    report = json.loads(completed.stdout)
    assert report["reason_code"] == "SITE_ORIGIN_NOT_READY"

    accepted = _run(
        DEPLOY_DECISION="ACTIVE",
        SITE_ORIGIN_READY="true",
        PUBLISH_OUTCOME="success",
        RECEIPT_OUTCOME="success",
        MONITORING_READY="true",
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["status"] == "publication_accepted"


def test_invalid_boolean_input_fails_closed() -> None:
    completed = _run(SUCCESS_HEARTBEAT_READY="yes")

    assert completed.returncode == 11
    report = json.loads(completed.stdout)
    assert report["status"] == "invalid_configuration"
    assert report["reason_code"] == "INVALID_BOOLEAN_INPUT"
