"""Current paper-mode authorization status.

Paper, testnet, and manual execution are future independently authorized
projects. This module intentionally cannot create proposals or mutate a paper
ledger in the current product.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

PAPER_LEDGER_SCHEMA_VERSION = "paper_proposal_ledger_report.v1"
PAPER_MODE_NOT_AUTHORIZED = "PAPER_MODE_NOT_AUTHORIZED"
DEFAULT_MANUAL_APPROVAL_RUNBOOK_PATH = (
    Path(__file__).resolve().parent / "resources" / "manual-approval-runbook.md"
)
DEFAULT_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID = (
    "crypto_options_report/resources/manual-approval-runbook.md"
)
CONFIGURED_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID = "configured://manual-approval-runbook"


def build_paper_proposal_ledger(
    *,
    generated_at: str,
    report: dict[str, Any],
    allow_paper: bool = False,
    review_decisions: list[dict[str, Any]] | None = None,
    storage_path: str | Path | None = None,
    manual_approval_runbook_path: str | Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Report the current authorization boundary without creating proposals.

    Parameters from the former proposal implementation remain accepted so
    callers fail closed during the transition. In particular, ``allow_paper``
    is not authority and ``storage_path`` is never written.
    """

    return {
        "schema_version": PAPER_LEDGER_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "unsupported",
        "authorization_state": "not_authorized",
        "release_state": "NO-GO",
        "proposal_creation_allowed": False,
        "reason_codes": [PAPER_MODE_NOT_AUTHORIZED],
        "proposal_count": 0,
        "proposals": [],
        "ledger_entries": [],
        "workflow_states": [],
        "automatic_live_submission_possible": False,
        "live_order_adapter": "not_implemented",
        "manual_approval_runbook": manual_approval_runbook_evidence(
            manual_approval_runbook_path
        ),
        "persistence": {
            "mode": "unsupported",
            "write_allowed": False,
            "storage_path": None,
        },
        "reconciliation": {
            "schema_version": "paper_reconciliation_contract.v1",
            "status": "not_authorized",
            "evidence_state": "not_run",
            "ready": False,
            "reason_codes": [PAPER_MODE_NOT_AUTHORIZED],
            "runbook": build_paper_reconciliation_runbook(),
        },
    }


def validate_paper_proposal_ledger(report: Any) -> list[str]:
    """Validate the current unsupported/no-write paper contract."""

    if not isinstance(report, dict):
        return ["paper_proposal_ledger must be a dict"]

    errors: list[str] = []
    if report.get("schema_version") != PAPER_LEDGER_SCHEMA_VERSION:
        errors.append(
            "paper_proposal_ledger.schema_version must be "
            "paper_proposal_ledger_report.v1"
        )
    if report.get("status") != "unsupported":
        errors.append("paper proposal ledger must be unsupported")
    if report.get("authorization_state") != "not_authorized":
        errors.append("paper proposal ledger must remain not_authorized")
    if report.get("release_state") != "NO-GO":
        errors.append("paper proposal ledger release state must remain NO-GO")
    if report.get("proposal_creation_allowed") is not False:
        errors.append("paper proposal creation must remain disabled")
    if report.get("automatic_live_submission_possible") is not False:
        errors.append("automatic live submission must remain impossible")
    if report.get("reason_codes") != [PAPER_MODE_NOT_AUTHORIZED]:
        errors.append(
            "unsupported paper mode must remain blocked by PAPER_MODE_NOT_AUTHORIZED"
        )
    proposal_count = report.get("proposal_count")
    if type(proposal_count) is not int or proposal_count != 0:
        errors.append("unsupported paper mode proposal_count must be zero")
    if (
        report.get("proposals") != []
        or report.get("ledger_entries") != []
        or report.get("workflow_states") != []
    ):
        errors.append("unsupported paper mode must not expose proposals or entries")
    if report.get("live_order_adapter") != "not_implemented":
        errors.append("unsupported paper mode must not expose a live order adapter")

    runbook_evidence = report.get("manual_approval_runbook")
    if not isinstance(runbook_evidence, dict):
        errors.append("paper manual approval runbook evidence must be a dict")
        runbook_evidence = {}
    if runbook_evidence.get("external_approval_recorded") is not False:
        errors.append("paper mode must not record external approval")

    persistence = report.get("persistence")
    if not isinstance(persistence, dict):
        errors.append("paper proposal persistence state must be a dict")
        persistence = {}
    if persistence.get("mode") != "unsupported":
        errors.append("paper proposal persistence mode must remain unsupported")
    if persistence.get("write_allowed") is not False:
        errors.append("unsupported paper mode must not allow persistence writes")
    if persistence.get("storage_path") is not None:
        errors.append("unsupported paper mode must not expose a storage path")

    reconciliation = report.get("reconciliation")
    if not isinstance(reconciliation, dict):
        errors.append("paper proposal reconciliation state must be a dict")
        reconciliation = {}
    if reconciliation.get("schema_version") != "paper_reconciliation_contract.v1":
        errors.append(
            "paper proposal reconciliation schema must be "
            "paper_reconciliation_contract.v1"
        )
    if reconciliation.get("status") != "not_authorized":
        errors.append("unsupported paper reconciliation must remain not_authorized")
    if reconciliation.get("evidence_state") != "not_run":
        errors.append("unsupported paper reconciliation evidence must remain not_run")
    if reconciliation.get("ready") is not False:
        errors.append("unsupported paper reconciliation must not be ready")
    if reconciliation.get("reason_codes") != [PAPER_MODE_NOT_AUTHORIZED]:
        errors.append(
            "unsupported paper reconciliation must remain blocked by "
            "PAPER_MODE_NOT_AUTHORIZED"
        )

    reconciliation_runbook = reconciliation.get("runbook")
    if not isinstance(reconciliation_runbook, dict):
        errors.append("paper reconciliation runbook must be a dict")
        reconciliation_runbook = {}
    if (
        reconciliation_runbook.get("schema_version")
        != "paper_reconciliation_runbook.v1"
    ):
        errors.append("paper reconciliation runbook schema is invalid")
    if reconciliation_runbook.get("implementation_status") != "not_authorized":
        errors.append("paper reconciliation runbook must remain not_authorized")
    if reconciliation_runbook.get("automatic_live_submission_possible") is not False:
        errors.append("paper reconciliation runbook must forbid live submission")
    return errors


def build_paper_reconciliation_runbook() -> dict[str, Any]:
    """Describe the future evidence rubric without implementing the workflow."""

    return {
        "schema_version": "paper_reconciliation_runbook.v1",
        "window_days": {"minimum": 30, "target": 60},
        "cadence": "daily_append_weekly_review",
        "required_observations": [
            "proposal",
            "manual_review_state",
            "simulated_fill",
            "observed_fill_when_available",
            "fees",
            "slippage",
            "latency",
            "reject_or_expiry_reason",
            "terminal_outcome",
        ],
        "unlock_policy": (
            "paper_manual_remains_blocked_until_external_definition_of_done_is_recorded"
        ),
        "automatic_live_submission_possible": False,
        "implementation_status": "not_authorized",
    }


def manual_approval_runbook_evidence(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a local policy document without treating it as approval."""

    candidate = Path(path) if path is not None else DEFAULT_MANUAL_APPROVAL_RUNBOOK_PATH
    candidate = candidate.expanduser().resolve()
    base = {
        "schema_version": "manual_approval_runbook_evidence.v1",
        "path": _manual_approval_runbook_public_id(candidate),
        "status": "missing",
        "version": None,
        "sha256": None,
        "external_approval_recorded": False,
        "reason_codes": ["MISSING_MANUAL_APPROVAL_RUNBOOK"],
    }
    if not candidate.is_file():
        return base
    try:
        raw = candidate.read_bytes()
        content = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            **base,
            "status": "invalid",
            "reason_codes": ["INVALID_MANUAL_APPROVAL_RUNBOOK"],
        }

    version_match = re.search(
        r"(?im)^\s*(?:version|版本)\s*[:：]\s*([^\s]+)", content
    )
    normalized = content.lower()
    required_terms = (
        "research_only" in normalized,
        "manual approval" in normalized or "人工审批" in content or "手动审批" in content,
    )
    digest = hashlib.sha256(raw).hexdigest()
    if version_match is None or not all(required_terms):
        return {
            **base,
            "status": "invalid",
            "version": version_match.group(1) if version_match else None,
            "sha256": digest,
            "reason_codes": ["INVALID_MANUAL_APPROVAL_RUNBOOK"],
        }
    return {
        **base,
        "status": "verified_local",
        "version": version_match.group(1),
        "sha256": digest,
        "reason_codes": ["EXTERNAL_APPROVAL_PENDING"],
    }


def _manual_approval_runbook_public_id(candidate: Path) -> str:
    if candidate == DEFAULT_MANUAL_APPROVAL_RUNBOOK_PATH:
        return DEFAULT_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID
    return CONFIGURED_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID
