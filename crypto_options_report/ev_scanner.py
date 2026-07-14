"""Honest EV-scanner availability for the research-only report."""

from __future__ import annotations

from typing import Any

MISSING_VALIDATED_PATH_RISK = "MISSING_VALIDATED_PATH_RISK"


def build_ev_candidate_scanner(
    *,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    permission_state: dict[str, Any],
    candidate_research: dict[str, Any],
) -> dict[str, Any]:
    """Return unavailable until a validated historical path artifact exists.

    The previous implementation wrapped hard-coded return templates in the
    production path-risk calculator. That produced precise-looking EV, CVaR,
    P-touch, and ranking values despite having no validated history. The
    public call signature remains stable, but upstream candidates are not
    scored until a real path-evidence seam is introduced.
    """

    return {
        "status": "unavailable",
        "reason_code": MISSING_VALIDATED_PATH_RISK,
        "score_status": "UNAVAILABLE",
        "path_risk_evidence": {
            "status": "unavailable",
            "validated": False,
            "artifact_id": None,
            "source": None,
            "reason_code": MISSING_VALIDATED_PATH_RISK,
        },
        "recommended_size_allowed": False,
        "trade_instruction_allowed": False,
        "paper_manual_candidates_allowed": False,
        "ranked_candidates": [],
        "summary": {
            "candidates_scanned": 0,
            "review_candidates": 0,
            "rejected_candidates": 0,
            "kill_condition_candidates": 0,
            "top_candidate_id": None,
            "top_candidate_action": None,
        },
    }
