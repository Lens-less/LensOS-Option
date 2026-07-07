"""Paper proposal ledger and manual approval tracer for ISSUE-015."""

from __future__ import annotations

from typing import Any

PAPER_LEDGER_SCHEMA_VERSION = "paper_proposal_ledger_report.v1"
LEDGER_STATES = ["proposed", "reviewed", "rejected", "expired", "paper_filled"]


def build_paper_proposal_ledger(
    *,
    generated_at: str,
    report: dict[str, Any],
    allow_paper: bool = False,
    review_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build proposal and ledger evidence without any live submission path."""

    blocked_reasons = _proposal_blockers(report, allow_paper=allow_paper)
    if blocked_reasons:
        return {
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
        }

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
    return {
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
    }


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
    return errors


def _proposal_blockers(report: dict[str, Any], *, allow_paper: bool) -> list[str]:
    blockers = []
    if not allow_paper:
        blockers.append("PAPER_MODE_GATE_CLOSED")
    if (report.get("mode_gate") or {}).get("paper_manual_candidates_allowed") is not True:
        blockers.append("MODE_GATE_BLOCKS_PAPER_MANUAL_CANDIDATES")
    if (report.get("walk_forward_calibration") or {}).get("status") != "validated":
        blockers.append("MISSING_VALIDATED_WALK_FORWARD_CALIBRATION")
    if (report.get("data_status") or {}).get("status") != "validated":
        blockers.append("MARKET_DATA_NOT_VALIDATED")
    account = report.get("account_status") or {}
    if account.get("trade_gate") != "ALLOW_NEW":
        blockers.append("ACCOUNT_OR_MARGIN_GATE_BLOCKS_PROPOSALS")
    if any(
        code in (report.get("reason_codes") or [])
        for code in ("SETTLEMENT_WINDOW_ACTIVE", "EVENT_KILL", "STALE_ACCOUNT_DATA")
    ):
        blockers.append("SETTLEMENT_EVENT_OR_STALENESS_BLOCK")
    return _unique_codes(blockers)


def _proposal_from_candidate(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    structure = candidate.get("structure_type")
    executable_credit = float(candidate.get("executable_credit_usdc") or 0.0)
    fees = float(candidate.get("fee_usdc") or 0.0)
    slippage = float(candidate.get("slippage_usdc") or 0.0)
    if structure == "call_credit_spread":
        conservative_price_basis = "sell_leg_bid_minus_buy_leg_ask"
    else:
        conservative_price_basis = "sell_leg_bid_or_better"
    return {
        "proposal_id": f"proposal-{index:02d}",
        "candidate_id": candidate.get("candidate_id"),
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
        estimated_total_cost = proposal["estimated_fees_usdc"] + proposal["estimated_slippage_usdc"]
        entries.append(
            {
                "proposal_id": proposal["proposal_id"],
                "state": state,
                "proposed_credit_usdc": proposal["executable_credit_usdc"],
                "simulated_fill_usdc": round(simulated_fill, 6),
                "estimated_costs_usdc": round(estimated_total_cost, 6),
                "slippage_vs_proposal_usdc": round(proposal["executable_credit_usdc"] - simulated_fill, 6),
                "state_machine_trigger": decision.get("state_machine_trigger", "none"),
                "reconciled": True,
            }
        )
    return entries


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
