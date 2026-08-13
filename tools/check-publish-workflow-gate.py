#!/usr/bin/env python3
"""Evaluate capture-lane admission before optional public publication."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

BOOLEAN_FIELDS = (
    "EVIDENCE_SYNC_ENABLED",
    "EVIDENCE_SYNC_READY",
    "FAILURE_WEBHOOK_READY",
    "SUCCESS_HEARTBEAT_READY",
    "SITE_ORIGIN_READY",
    "MONITORING_READY",
)


def _report(status: str, reason_code: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "publish_workflow_gate.v1",
        "status": status,
        "reason_code": reason_code,
        **extra,
    }


def _inputs() -> tuple[dict[str, str | bool], str | None]:
    values: dict[str, str | bool] = {
        name: os.environ.get(name, "")
        for name in (
            "CAPTURE_OUTCOME",
            "BUNDLE_BUILD_OUTCOME",
            "BUNDLE_BOUNDARY_OUTCOME",
            "DEPLOY_DECISION",
            "PUBLISH_OUTCOME",
            "RECEIPT_OUTCOME",
            "DEPLOY_DECISION_ISSUE",
            *BOOLEAN_FIELDS,
        )
    }
    for name in BOOLEAN_FIELDS:
        raw = str(values[name]).strip().lower()
        if raw not in {"true", "false"}:
            return values, name
        values[name] = raw == "true"
    return values, None


def evaluate(values: dict[str, str | bool]) -> tuple[dict[str, Any], int]:
    capture_checks = (
        (values["CAPTURE_OUTCOME"] == "success", "CAPTURE_FAILED"),
        (values["EVIDENCE_SYNC_ENABLED"] is True, "EVIDENCE_SYNC_DISABLED"),
        (values["EVIDENCE_SYNC_READY"] is True, "EVIDENCE_SYNC_NOT_READY"),
        (values["FAILURE_WEBHOOK_READY"] is True, "FAILURE_WEBHOOK_NOT_READY"),
        (values["SUCCESS_HEARTBEAT_READY"] is True, "SUCCESS_HEARTBEAT_NOT_READY"),
    )
    for passed, reason_code in capture_checks:
        if not passed:
            return (
                _report(
                    "blocked",
                    reason_code,
                    capture_lane_accepted=False,
                    publication_attempted=False,
                ),
                10,
            )

    publication_verification_checks = (
        (values["BUNDLE_BUILD_OUTCOME"] == "success", "PUBLIC_BUNDLE_BUILD_FAILED"),
        (
            values["BUNDLE_BOUNDARY_OUTCOME"] == "success",
            "PUBLIC_BUNDLE_BOUNDARY_FAILED",
        ),
    )
    for passed, reason_code in publication_verification_checks:
        if not passed:
            return (
                _report(
                    "blocked",
                    reason_code,
                    capture_lane_accepted=True,
                    publication_verification_accepted=False,
                    publication_attempted=False,
                ),
                10,
            )

    decision = str(values["DEPLOY_DECISION"])
    if decision == "SUSPENDED":
        return (
            _report(
                "capture_lane_accepted_deploy_suspended",
                "DEPLOY_SUSPENDED",
                capture_lane_accepted=True,
                publication_verification_accepted=True,
                publication_attempted=False,
                decision_issue=str(values["DEPLOY_DECISION_ISSUE"]),
            ),
            0,
        )
    if decision != "ACTIVE":
        return (
            _report(
                "invalid_configuration",
                "INVALID_DEPLOY_DECISION",
                capture_lane_accepted=True,
                publication_verification_accepted=True,
                publication_attempted=False,
            ),
            11,
        )

    publication_checks = (
        (values["SITE_ORIGIN_READY"] is True, "SITE_ORIGIN_NOT_READY"),
        (values["PUBLISH_OUTCOME"] == "success", "PUBLICATION_FAILED"),
        (values["RECEIPT_OUTCOME"] == "success", "PUBLICATION_RECEIPT_FAILED"),
        (values["MONITORING_READY"] is True, "MONITORING_NOT_READY"),
    )
    for passed, reason_code in publication_checks:
        if not passed:
            return (
                _report(
                    "blocked",
                    reason_code,
                    capture_lane_accepted=True,
                    publication_verification_accepted=True,
                    publication_attempted=True,
                ),
                10,
            )
    return (
        _report(
            "publication_accepted",
            None,
            capture_lane_accepted=True,
            publication_verification_accepted=True,
            publication_attempted=True,
        ),
        0,
    )


def main() -> int:
    values, invalid_boolean = _inputs()
    if invalid_boolean is not None:
        report = _report(
            "invalid_configuration",
            "INVALID_BOOLEAN_INPUT",
            field=invalid_boolean,
            capture_lane_accepted=False,
            publication_attempted=False,
        )
        exit_code = 11
    else:
        report, exit_code = evaluate(values)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
