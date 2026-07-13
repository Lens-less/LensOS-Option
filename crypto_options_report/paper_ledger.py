"""Paper proposal ledger and manual approval tracer for ISSUE-015."""

from __future__ import annotations

import json
import hashlib
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import atomic_write_json

PAPER_LEDGER_SCHEMA_VERSION = "paper_proposal_ledger_report.v1"
LEDGER_STATES = ["proposed", "reviewed", "rejected", "expired", "paper_filled"]
DEFAULT_MANUAL_APPROVAL_RUNBOOK_PATH = (
    Path(__file__).resolve().parent
    / "resources"
    / "manual-approval-runbook.md"
)
_PERSISTENCE_LOCK = threading.RLock()


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
    """Build proposal and ledger evidence without any live submission path."""

    blocked_reasons = _proposal_blockers(report, allow_paper=allow_paper)
    if blocked_reasons:
        ledger = {
            "schema_version": PAPER_LEDGER_SCHEMA_VERSION,
            "generated_at": generated_at,
            "status": "blocked",
            "proposal_creation_allowed": False,
            "reason_codes": blocked_reasons,
            "proposal_count": 0,
            "proposals": [],
            "ledger_entries": [],
            "workflow_states": list(LEDGER_STATES),
            "automatic_live_submission_possible": False,
            "live_order_adapter": "not_implemented",
            "post_only_assumption": "recorded_without_maker_fee_exemption",
            "manual_approval_runbook": manual_approval_runbook_evidence(
                manual_approval_runbook_path
            ),
            "persistence": _persistence_contract(storage_path=storage_path),
            "reconciliation": _reconciliation_contract(
                ledger_entries=[],
                blocked=True,
            ),
        }
        _merge_persisted_ledger(ledger, storage_path, persist=persist)
        return ledger

    ranked = [
        item
        for item in (report.get("ev_candidate_scanner") or {}).get("ranked_candidates", [])
        if item.get("action") in {"RESEARCH_ONLY", "REVIEW"} and not item.get("kill_conditions")
    ][:3]
    proposals = [_proposal_from_candidate(item, index=index) for index, item in enumerate(ranked, start=1)]
    ledger_entries = _ledger_entries(
        proposals=proposals,
        review_decisions=review_decisions or [],
    )
    ledger = {
        "schema_version": PAPER_LEDGER_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "validated",
        "proposal_creation_allowed": True,
        "reason_codes": ["PAPER_MODE_ALLOWED", "TOP_1_TO_3_CALIBRATED_CANDIDATES_ONLY"],
        "proposal_count": len(proposals),
        "proposals": proposals,
        "ledger_entries": ledger_entries,
        "workflow_states": list(LEDGER_STATES),
        "automatic_live_submission_possible": False,
        "live_order_adapter": "not_implemented",
        "post_only_assumption": "recorded_without_maker_fee_exemption",
        "manual_approval_runbook": manual_approval_runbook_evidence(
            manual_approval_runbook_path
        ),
        "persistence": _persistence_contract(storage_path=storage_path),
        "reconciliation": _reconciliation_contract(
            ledger_entries=ledger_entries,
            blocked=False,
        ),
    }
    _merge_persisted_ledger(ledger, storage_path, persist=persist)
    return ledger


def validate_paper_proposal_ledger(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["paper_proposal_ledger must be a dict"]
    if report.get("schema_version") != PAPER_LEDGER_SCHEMA_VERSION:
        errors.append("paper_proposal_ledger.schema_version must be paper_proposal_ledger_report.v1")
    if report.get("automatic_live_submission_possible") is not False:
        errors.append("paper_proposal_ledger must make automatic live submission impossible")
    if set(report.get("workflow_states") or []) != set(LEDGER_STATES):
        errors.append("paper_proposal_ledger.workflow_states must include all states")
    proposals = report.get("proposals")
    if not isinstance(proposals, list):
        errors.append("paper_proposal_ledger.proposals must be a list")
    elif len(proposals) > 3:
        errors.append("paper_proposal_ledger must limit proposals to top 1-3 candidates")
    persistence = report.get("persistence") or {}
    if persistence.get("idempotent") is not True:
        errors.append("paper_proposal_ledger.persistence.idempotent must be true")
    reconciliation = report.get("reconciliation") or {}
    if reconciliation.get("window") != "30_to_60_days_required":
        errors.append("paper_proposal_ledger.reconciliation.window must be 30_to_60_days_required")
    runbook = report.get("manual_approval_runbook") or {}
    if runbook.get("schema_version") != "manual_approval_runbook_evidence.v1":
        errors.append(
            "paper_proposal_ledger.manual_approval_runbook must be versioned evidence"
        )
    return errors


def _proposal_blockers(report: dict[str, Any], *, allow_paper: bool) -> list[str]:
    blockers = []
    calibration = report.get("walk_forward_calibration") or {}
    model_registry = calibration.get("model_registry") or {}
    account = report.get("account_status") or {}
    private_contract = account.get("private_adapter_contract") or {}
    if not allow_paper:
        blockers.append("PAPER_MODE_GATE_CLOSED")
    if (report.get("mode_gate") or {}).get("paper_manual_candidates_allowed") is not True:
        blockers.append("MODE_GATE_BLOCKS_PAPER_MANUAL_CANDIDATES")
    if calibration.get("status") != "validated":
        blockers.append("MISSING_VALIDATED_WALK_FORWARD_CALIBRATION")
    if model_registry.get("promoted_for_sizing") is not True:
        blockers.append("MISSING_PROMOTED_SCORE_MODEL")
    if (report.get("data_status") or {}).get("status") != "validated":
        blockers.append("MARKET_DATA_NOT_VALIDATED")
    if account.get("trade_gate") != "ALLOW_NEW":
        blockers.append("ACCOUNT_OR_MARGIN_GATE_BLOCKS_PROPOSALS")
    if not (
        private_contract.get("auth_safe") is True
        and private_contract.get("replay_fixture") is True
        and private_contract.get("live_order_submission_possible") is False
    ):
        blockers.append("MISSING_PRIVATE_ACCOUNT_REPLAY_EVIDENCE")
    if any(
        code in (report.get("reason_codes") or [])
        for code in ("SETTLEMENT_WINDOW_ACTIVE", "EVENT_KILL", "STALE_ACCOUNT_DATA")
    ):
        blockers.append("SETTLEMENT_EVENT_OR_STALENESS_BLOCK")
    return _unique_codes(blockers)


def _proposal_from_candidate(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    structure = candidate.get("structure_type")
    candidate_id = str(candidate.get("candidate_id") or f"candidate-{index:02d}")
    executable_credit = float(candidate.get("executable_credit_usdc") or 0.0)
    fees = float(candidate.get("fee_usdc") or 0.0)
    slippage = float(candidate.get("slippage_usdc") or 0.0)
    if structure == "call_credit_spread":
        conservative_price_basis = "sell_leg_bid_minus_buy_leg_ask"
    else:
        conservative_price_basis = "sell_leg_bid_or_better"
    return {
        "proposal_id": f"proposal-{index:02d}-{candidate_id}",
        "candidate_id": candidate_id,
        "structure_type": structure,
        "legs": _legs(candidate),
        "dte_days": candidate.get("dte_days"),
        "model_delta": candidate.get("model_delta"),
        "executable_credit_usdc": round(executable_credit, 6),
        "ev_after_cost_usdc": candidate.get("ev_after_cost_usdc"),
        "p_touch": (candidate.get("path_risk") or {}).get("p_touch"),
        "cvar_99_usdc": (candidate.get("path_risk") or {}).get("cvar_99_usdc"),
        "stress_loss_usdc": (candidate.get("path_risk") or {}).get("stress_loss_usdc"),
        "size_cap_units": 0.0,
        "entry_condition": "post_only_limit_at_or_above_conservative_credit",
        "take_profit_condition": "buyback_when_50_percent_of_credit_captured",
        "risk_exit_condition": "state_machine_exit_required_or_force_close",
        "reason_codes": _unique_codes(list(candidate.get("reason_codes") or []) + ["MANUAL_REVIEW_REQUIRED"]),
        "conservative_price_basis": conservative_price_basis,
        "estimated_fees_usdc": round(fees, 6),
        "estimated_slippage_usdc": round(slippage, 6),
        "state": "proposed",
        "proposed_at": None,
    }


def _ledger_entries(
    *,
    proposals: list[dict[str, Any]],
    review_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions_by_id = {
        str(item.get("proposal_id")): item
        for item in review_decisions
    }
    entries = []
    for proposal in proposals:
        decision = decisions_by_id.get(proposal["proposal_id"], {})
        state = str(decision.get("state") or "proposed")
        if state not in LEDGER_STATES:
            state = "reviewed"
        simulated_fill = float(decision.get("simulated_fill_usdc") or proposal["executable_credit_usdc"])
        observed_fill_raw = decision.get("observed_fill_usdc")
        observed_fee_raw = decision.get("observed_fee_usdc")
        observed_fill = None if observed_fill_raw is None else float(observed_fill_raw)
        observed_fee = None if observed_fee_raw is None else float(observed_fee_raw)
        estimated_total_cost = proposal["estimated_fees_usdc"] + proposal["estimated_slippage_usdc"]
        expected_fill = proposal["executable_credit_usdc"]
        fill_delta = None if observed_fill is None else round(observed_fill - expected_fill, 6)
        fee_delta = None if observed_fee is None else round(observed_fee - proposal["estimated_fees_usdc"], 6)
        reconciled = observed_fill is not None or state in {"rejected", "expired"}
        entries.append(
            {
                "proposal_id": proposal["proposal_id"],
                "state": state,
                "manual_review_state": str(decision.get("manual_review_state") or state),
                "proposed_at": decision.get("proposed_at"),
                "reviewed_at": decision.get("reviewed_at"),
                "observed_at": decision.get("observed_at"),
                "terminal_outcome": (
                    state
                    if state in {"rejected", "expired", "paper_filled"}
                    else "pending"
                ),
                "expected_fill_usdc": expected_fill,
                "proposed_credit_usdc": expected_fill,
                "simulated_fill_usdc": round(simulated_fill, 6),
                "observed_fill_usdc": None if observed_fill is None else round(observed_fill, 6),
                "observed_fee_usdc": None if observed_fee is None else round(observed_fee, 6),
                "estimated_costs_usdc": round(estimated_total_cost, 6),
                "slippage_vs_proposal_usdc": round(expected_fill - simulated_fill, 6),
                "fill_delta_usdc": fill_delta,
                "fee_delta_usdc": fee_delta,
                "latency_ms": decision.get("latency_ms"),
                "state_machine_trigger": decision.get("state_machine_trigger", "none"),
                "reconciled": reconciled,
            }
        )
    return entries


def _persistence_contract(*, storage_path: str | Path | None) -> dict[str, Any]:
    return {
        "mode": "persistent_json" if storage_path else "ephemeral_memory",
        "storage_path": None if storage_path is None else str(storage_path),
        "idempotent": True,
        "merge_key": "proposal_id",
    }


def _reconciliation_contract(
    *,
    ledger_entries: list[dict[str, Any]],
    blocked: bool,
) -> dict[str, Any]:
    observed_entries = [
        entry
        for entry in ledger_entries
        if entry.get("observed_fill_usdc") is not None
        or entry.get("terminal_outcome") in {"rejected", "expired"}
    ]
    reconciled_entries = [entry for entry in ledger_entries if entry.get("reconciled")]
    timestamps = [
        parsed
        for entry in ledger_entries
        for raw in (
            entry.get("proposed_at"),
            entry.get("reviewed_at"),
            entry.get("observed_at"),
        )
        if (parsed := _parse_optional_timestamp(raw)) is not None
    ]
    observation_started_at = min(timestamps) if timestamps else None
    observation_ended_at = max(timestamps) if timestamps else None
    observation_days = (
        (observation_ended_at - observation_started_at).total_seconds() / 86_400
        if observation_started_at is not None and observation_ended_at is not None
        else 0.0
    )
    complete = bool(
        ledger_entries
        and len(reconciled_entries) == len(ledger_entries)
        and observed_entries
        and observation_days >= 30.0
    )
    if complete:
        evidence_state = "verified_local"
        reason_codes: list[str] = []
    elif ledger_entries:
        evidence_state = "verified_local"
        reason_codes = []
        if len(reconciled_entries) != len(ledger_entries):
            reason_codes.append("PAPER_RECONCILIATION_INCOMPLETE")
        if not observed_entries:
            reason_codes.append("MISSING_OBSERVED_PAPER_OUTCOMES")
        if observation_days < 30.0:
            reason_codes.append("MISSING_30_60_DAY_RECONCILIATION")
    else:
        evidence_state = "not_run"
        reason_codes = ["MISSING_30_60_DAY_RECONCILIATION"]
    return {
        "schema_version": "paper_reconciliation_contract.v1",
        "window": "30_to_60_days_required",
        "runbook": build_paper_reconciliation_runbook(),
        "status": (
            "reconciled"
            if complete
            else "blocked"
            if blocked and not ledger_entries
            else "pending_observed_fills"
        ),
        "evidence_state": evidence_state,
        "ready": complete,
        "reason_codes": reason_codes,
        "observation_started_at": (
            observation_started_at.isoformat().replace("+00:00", "Z")
            if observation_started_at
            else None
        ),
        "observation_ended_at": (
            observation_ended_at.isoformat().replace("+00:00", "Z")
            if observation_ended_at
            else None
        ),
        "observation_days": round(observation_days, 6),
        "minimum_observation_days": 30,
        "observed_entry_count": len(observed_entries),
        "expected_entry_count": len(ledger_entries),
        "reconciled_entry_count": len(reconciled_entries),
        "checks": [
            "expected_vs_observed_fill",
            "fees",
            "slippage",
            "latency",
            "rejected_or_expired_actions",
        ],
    }


def build_paper_reconciliation_runbook() -> dict[str, Any]:
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
        "unlock_policy": "paper_manual_remains_blocked_until_external_definition_of_done_is_recorded",
        "automatic_live_submission_possible": False,
    }


def manual_approval_runbook_evidence(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate the local runbook without treating it as external approval."""

    candidate = Path(path) if path is not None else DEFAULT_MANUAL_APPROVAL_RUNBOOK_PATH
    candidate = candidate.expanduser().resolve()
    base = {
        "schema_version": "manual_approval_runbook_evidence.v1",
        "path": str(candidate),
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
        return {**base, "status": "invalid", "reason_codes": ["INVALID_MANUAL_APPROVAL_RUNBOOK"]}

    version_match = re.search(
        r"(?im)^\s*(?:version|版本)\s*[:：]\s*([^\s]+)", content
    )
    normalized = content.lower()
    required_terms = (
        "research_only" in normalized,
        "manual approval" in normalized or "人工审批" in content or "手动审批" in content,
    )
    if version_match is None or not all(required_terms):
        return {
            **base,
            "status": "invalid",
            "version": version_match.group(1) if version_match else None,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "reason_codes": ["INVALID_MANUAL_APPROVAL_RUNBOOK"],
        }
    return {
        **base,
        "status": "verified_local",
        "version": version_match.group(1),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "reason_codes": ["EXTERNAL_APPROVAL_PENDING"],
    }


def _merge_persisted_ledger(
    ledger: dict[str, Any],
    storage_path: str | Path | None,
    *,
    persist: bool,
) -> None:
    """Project existing evidence and write only in an explicit writer context."""

    if storage_path is None:
        return
    path = Path(storage_path).expanduser().resolve()
    with _PERSISTENCE_LOCK:
        if persist:
            path.parent.mkdir(parents=True, exist_ok=True)
        prior_entries: list[dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # Never replace operator evidence after a corrupt/partial read.
                raise ValueError("existing paper ledger is invalid JSON") from exc
            if not isinstance(existing, dict):
                raise ValueError("existing paper ledger must be a JSON object")
            prior_entries = list(existing.get("ledger_entries") or [])
            merged_entries = {
                str(entry.get("proposal_id")): entry
                for entry in prior_entries
                if entry.get("proposal_id")
            }
            for entry in ledger.get("ledger_entries") or []:
                proposal_id = str(entry.get("proposal_id"))
                if proposal_id:
                    merged_entries[proposal_id] = entry
            ledger["ledger_entries"] = list(merged_entries.values())
            ledger["reconciliation"] = _reconciliation_contract(
                ledger_entries=ledger["ledger_entries"],
                blocked=ledger.get("status") == "blocked",
            )
        ledger["persistence"]["prior_entry_count"] = len(prior_entries)
        ledger["persistence"]["saved_entry_count"] = len(ledger.get("ledger_entries") or [])
        ledger["persistence"]["history_preserved"] = bool(prior_entries)
        ledger["persistence"]["write_performed"] = persist
        if persist:
            atomic_write_json(path, ledger, trailing_newline=False)


def _parse_optional_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _legs(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    if candidate.get("structure_type") == "call_credit_spread":
        return [
            {"role": "sell", "instrument_name": candidate.get("sell_leg_instrument_name")},
            {"role": "buy", "instrument_name": candidate.get("buy_leg_instrument_name")},
        ]
    return [{"role": "sell", "instrument_name": candidate.get("instrument_name")}]


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
