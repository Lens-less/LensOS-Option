"""Candidate ranking for the research-only report.

History matters here. An earlier implementation wrapped hard-coded return
templates in the production path-risk calculator and emitted precise-looking
EV, CVaR, P-touch and ranking values with no validated history behind them. It
was replaced by a stub that refused to score at all.

This implementation restores scoring without restoring that mistake, by keeping
two claims separate:

* **Relative value** — "this strike is priced richer than its neighbours on the
  same smile" — needs only the current chain, and is computed via `edge_score`.
  It is real information and is reported.
* **Absolute expected value** — "selling this is profitable" — needs a realized
  return distribution and, to be promoted, walk-forward evidence. Without a
  validated path-risk artifact `ev_after_cost_usdc` stays `None`. It is never
  inferred from the relative-value score.

Every candidate therefore carries `score_status = UNCALIBRATED_RESEARCH_ONLY`,
and the scanner never permits sizing, order instructions, or paper candidates.
"""

from __future__ import annotations

import math
from typing import Any

from .edge_score import (
    CAUTION,
    OK,
    build_relative_value_edge_score,
    find_atm_reference,
    normalize_premium_to_usd,
    rank_candidates_by_edge,
)
from .path_risk import (
    VOL_SCALING_NONE,
    build_path_risk_report_from_underlying_history,
)
from .pnl import (
    delivery_fee_inverse,
    delivery_fee_linear,
    option_fee_inverse,
    option_fee_linear,
)
from .structures import build_structure
from .surface import black_scholes_price

MISSING_CANDIDATE_GREEKS = "MISSING_CANDIDATE_GREEKS"
MISSING_VALIDATED_PATH_RISK = "MISSING_VALIDATED_PATH_RISK"
UNCALIBRATED_SCORE_MODEL = "UNCALIBRATED_SCORE_MODEL"
NO_VALIDATED_PATH_RISK = "NO_VALIDATED_PATH_RISK"
SUSPECT_PRICE_DIVERGENCE = "SUSPECT_PRICE_DIVERGENCE"
UNBOUNDED_LOSS_STRUCTURE = "UNBOUNDED_LOSS_STRUCTURE"

RESEARCH_ONLY = "RESEARCH_ONLY"
REVIEW = "REVIEW"
REJECT = "REJECT"

NAKED = "naked_short_call"
SPREAD = "call_credit_spread"

# A quoted credit this far from the model's own valuation is treated as a data
# problem, not an opportunity. Selling far above fair value would be a large
# arbitrage; in practice it means a unit mismatch or a stale quote.
MAX_CREDIT_TO_FAIR_VALUE_RATIO = 3.0
MIN_CREDIT_TO_FAIR_VALUE_RATIO = 0.2

# Per-candidate expected value replays the full path set, so the number of
# candidates it runs for is bounded rather than unlimited.
MAX_ABSOLUTE_EV_CANDIDATES = 8


def build_ev_candidate_scanner(
    *,
    generated_at: str,
    data_status: dict[str, Any],
    account_status: dict[str, Any],
    calibration_status: dict[str, Any],
    permission_state: dict[str, Any],
    candidate_research: dict[str, Any],
    vol_surface_status: dict[str, Any] | None = None,
    path_risk_report: dict[str, Any] | None = None,
    underlying_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank candidates by relative value; report absolute EV only when evidenced.

    Without `vol_surface_status` there is no fitted smile to price against, so
    the scanner reports itself unavailable exactly as it did before scoring
    existed.
    """
    path_evidence = _path_risk_evidence(path_risk_report)

    if not _surface_usable(vol_surface_status) or not _candidates_usable(
        candidate_research
    ):
        return _unavailable()

    scored, rejected_rows = _score_candidate_research(
        candidate_research=candidate_research,
        vol_surface_status=vol_surface_status,
    )
    if not scored and not rejected_rows:
        return _unavailable()

    ranking = rank_candidates_by_edge(scored)
    ranked_candidates = _ranked_candidates(
        ranking=ranking,
        scored=scored,
        rejected_rows=rejected_rows,
        path_validated=path_evidence["validated"],
    )

    scored_by_id = {item.get("candidate_id"): item for item in scored}
    ev_applied = _apply_absolute_ev(
        ranked_candidates,
        scored_by_id=scored_by_id,
        underlying_history=underlying_history,
        permission_state=permission_state,
        generated_at=generated_at,
    )

    # Relative value alone never promotes the scanner past "blocked"; absolute
    # EV requires a validated realized-return distribution behind every reported
    # expected value.
    status = "validated" if (path_evidence["validated"] or ev_applied) else "blocked"

    return {
        "status": status,
        "reason_code": None if path_evidence["validated"] else NO_VALIDATED_PATH_RISK,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "path_risk_evidence": path_evidence["payload"],
        "ranking_basis": {
            "method": "pareto_frontier_then_lexicographic",
            "tie_break_order": ranking["tie_break_order"],
            "dominance_scope": ranking["dominance_scope"],
            # Nominal method and effective method diverge whenever the frontier
            # stops discriminating, which the occupancy block makes checkable
            # instead of leaving it to be inferred from the row count.
            "frontier_occupancy": ranking["frontier_occupancy"],
            "primary_axis": "smile_residual_richness",
            "primary_axis_unit": "residual_std_errors",
            "absolute_ev_available": bool(ev_applied),
            "absolute_ev_candidate_limit": MAX_ABSOLUTE_EV_CANDIDATES,
        },
        "dominated_explanations": ranking["dominated"],
        "recommended_size_allowed": False,
        "trade_instruction_allowed": False,
        "paper_manual_candidates_allowed": False,
        "ranked_candidates": ranked_candidates,
        "summary": _summary(ranked_candidates),
    }


def _unavailable() -> dict[str, Any]:
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


def _path_risk_evidence(path_risk_report: dict[str, Any] | None) -> dict[str, Any]:
    report = path_risk_report or {}
    evidence = (
        report.get("path_risk_evidence")
        or report.get("input_evidence")
        or report.get("evidence")
        or {}
    )
    validated = (
        evidence.get("status") == "validated_historical"
        and evidence.get("placeholder_data") is False
    )
    if not validated:
        return {
            "validated": False,
            "payload": {
                "status": "unavailable",
                "validated": False,
                "placeholder_data": True,
                "artifact_id": None,
                "source": evidence.get("source"),
                "reason_code": NO_VALIDATED_PATH_RISK,
            },
        }

    # The authoritative sample size is the overlap-adjusted independent window
    # count, not the similarity effective sample size. Carrying it here keeps a
    # consumer from reading confidence off the larger number.
    bound = report.get("independent_sample_bound") or {}
    return {
        "validated": True,
        "payload": {
            "status": "validated_historical",
            "validated": True,
            "placeholder_data": False,
            "artifact_id": evidence.get("artifact_id"),
            "source": evidence.get("source"),
            "evidence_class": evidence.get("evidence_class"),
            "excludes": evidence.get("excludes") or [],
            "authoritative_sample_size": bound.get("authoritative_sample_size"),
            "sample_size_basis": bound.get("sample_size_basis"),
            "reason_code": None,
        },
    }


def _surface_usable(vol_surface_status: dict[str, Any] | None) -> bool:
    return isinstance(vol_surface_status, dict) and bool(
        vol_surface_status.get("expiries")
    )


def _candidates_usable(candidate_research: dict[str, Any] | None) -> bool:
    return isinstance(candidate_research, dict) and candidate_research.get(
        "status"
    ) not in {None, "unavailable"}


def _expiry_points(vol_surface_status: dict[str, Any]) -> dict[str, list[dict]]:
    points: dict[str, list[dict]] = {}
    for expiry in vol_surface_status.get("expiries") or []:
        if isinstance(expiry, dict):
            points[str(expiry.get("expiry_date") or "")] = list(
                expiry.get("surface_points") or []
            )
    return points


def _score_candidate_research(
    *,
    candidate_research: dict[str, Any],
    vol_surface_status: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points_by_expiry = _expiry_points(vol_surface_status)
    scored: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []

    # The universe is read from the artifact rather than from a list written
    # here, so a structure type added upstream is scored instead of silently
    # dropped by a scanner that only knew about two tables.
    buckets = candidate_research.get("structure_types") or [
        "naked_short_calls",
        "call_credit_spreads",
    ]
    for bucket in buckets:
        group = candidate_research.get(bucket) or {}
        if not isinstance(group, dict):
            continue
        for tier in ("eligible", "review"):
            for candidate in group.get(tier) or []:
                if not isinstance(candidate, dict):
                    continue
                atm = find_atm_reference(
                    points_by_expiry.get(str(candidate.get("expiry_date") or "")),
                    underlying_price=candidate.get("underlying_price"),
                )
                score = build_relative_value_edge_score(
                    candidate=candidate,
                    structure_type=str(candidate.get("structure_type") or bucket),
                    atm_reference=atm,
                )
                score["_candidate"] = candidate
                scored.append(score)
        for candidate in group.get("rejected") or []:
            if isinstance(candidate, dict):
                rejected_rows.append(
                    {
                        "_candidate": candidate,
                        "structure_type": str(
                            candidate.get("structure_type") or bucket
                        ),
                    }
                )
    return scored, rejected_rows


def _ranked_candidates(
    *,
    ranking: dict[str, Any],
    scored: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    path_validated: bool,
) -> list[dict[str, Any]]:
    dominated_by = {
        entry["candidate_id"]: entry for entry in ranking.get("dominated") or []
    }
    frontier_ids = {
        item.get("candidate_id") for item in ranking.get("frontier") or []
    }
    ordered = list(ranking.get("frontier") or [])
    ordered += [
        item
        for item in scored
        if item.get("candidate_id") in dominated_by
        and item.get("candidate_id") not in frontier_ids
    ]
    ordered += list(ranking.get("partial_evidence") or [])

    rows = [
        _candidate_row(
            score,
            dominated_by,
            path_validated,
            frontier=score.get("candidate_id") in frontier_ids,
        )
        for score in ordered
    ]
    rows += [
        _rejected_row(entry["_candidate"], entry["structure_type"])
        for entry in rejected_rows
    ]
    return rows


def _candidate_row(
    score: dict[str, Any],
    dominated_by: dict[str, Any],
    path_validated: bool,
    *,
    frontier: bool,
) -> dict[str, Any]:
    candidate = score.get("_candidate") or {}
    structure_type = score.get("structure_type")
    spot = candidate.get("underlying_price")
    premium_unit = candidate.get("premium_unit")

    executable_credit = _executable_credit_usd(candidate, structure_type, spot)
    fair_value = _fair_value_usd(candidate, structure_type)

    kill_conditions: list[str] = [UNCALIBRATED_SCORE_MODEL]
    if not path_validated:
        kill_conditions.append(NO_VALIDATED_PATH_RISK)
    # Read from the legs: a ratio that is net short calls is as unbounded as a
    # naked short, and a put spread is as defined-risk as a call spread. Neither
    # is derivable from the structure's name.
    if not _loss_is_bounded(candidate, structure_type):
        kill_conditions.append(UNBOUNDED_LOSS_STRUCTURE)
    if _price_divergence_suspect(executable_credit, fair_value):
        kill_conditions.append(SUSPECT_PRICE_DIVERGENCE)

    reason_codes = [
        f"{name}:{item['reason_code']}"
        for name, item in (score.get("components") or {}).items()
        if item.get("status") != OK and item.get("reason_code")
    ]
    domination = dominated_by.get(score.get("candidate_id"))
    if domination:
        reason_codes.append("dominated_by:" + str(domination.get("dominated_by")))

    has_caution = any(
        (item or {}).get("status") == CAUTION
        for item in (score.get("components") or {}).values()
    )
    action = (
        RESEARCH_ONLY
        if frontier
        and score.get("status") == "scored"
        and not domination
        and not has_caution
        and SUSPECT_PRICE_DIVERGENCE not in kill_conditions
        else REVIEW
    )

    return {
        "candidate_id": score.get("candidate_id"),
        "structure_type": structure_type,
        "expiry_date": candidate.get("expiry_date"),
        # Carried because consumers filter and sort on tenor. Its absence left
        # every DTE cell and the tenor filter reading from a field that was
        # never published.
        "dte_days": candidate.get("dte_days"),
        # The legs and position greeks travel with the ranked row so a consumer
        # can combine rows without going back to the candidate tables and
        # re-deriving which shape each row referred to.
        "structure_legs": candidate.get("structure_legs"),
        "position_greeks": candidate.get("position_greeks"),
        "net_credit": candidate.get("net_credit"),
        "market_bid": candidate.get("market_bid"),
        "premium_unit": premium_unit,
        "underlying_price": spot,
        "action": action,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "ranking_score": _ranking_score(score),
        "premium_usdc": normalize_premium_to_usd(
            candidate.get("market_mid") or candidate.get("net_credit"),
            premium_unit=premium_unit,
            underlying_price=spot,
        ),
        "executable_credit_usdc": executable_credit,
        "fair_value_usdc": fair_value,
        # Reported only against validated path evidence; never inferred from the
        # relative-value components.
        "ev_after_cost_usdc": None,
        "fair_iv_diagnostics": _fair_iv_diagnostics(score, candidate, structure_type),
        "path_risk": {
            "status": "validated_historical" if path_validated else "unavailable",
            "reason_code": None if path_validated else NO_VALIDATED_PATH_RISK,
        },
        "margin_snapshot": _margin_snapshot(candidate, structure_type),
        "hazard_zone": _hazard_zone(score),
        "kill_conditions": kill_conditions,
        "reason_codes": reason_codes,
        "edge_components": score.get("components"),
        "dominated_by": (domination or {}).get("dominated_by"),
        "losing_axes": (domination or {}).get("losing_axes") or [],
    }


def _loss_is_bounded(candidate: dict[str, Any], structure_type: str | None) -> bool:
    legs = candidate.get("structure_legs")
    if not isinstance(legs, list) or not legs:
        # No legs means the shape is unknown, and an unknown shape is treated as
        # unbounded rather than assumed safe.
        return False
    try:
        structure = build_structure(
            structure_type=str(structure_type or "candidate"), legs=legs
        )
        if structure.is_multi_expiry:
            return False
        return structure.risk_profile(entry_cash=0.0).loss_is_bounded
    except ValueError:
        return False


def _rejected_row(candidate: dict[str, Any], structure_type: str) -> dict[str, Any]:
    reason_codes = [
        str(code)
        for code in (candidate.get("decision_reason_codes") or [])
        + (candidate.get("filter_reason_codes") or [])
    ]
    return {
        "candidate_id": candidate.get("candidate_id"),
        "structure_type": structure_type,
        "expiry_date": candidate.get("expiry_date"),
        "dte_days": candidate.get("dte_days"),
        "action": REJECT,
        "score_status": "UNCALIBRATED_RESEARCH_ONLY",
        "ranking_score": None,
        "premium_usdc": None,
        "executable_credit_usdc": None,
        "fair_value_usdc": None,
        "ev_after_cost_usdc": None,
        "fair_iv_diagnostics": {"status": "not_scored"},
        "path_risk": {"status": "unavailable", "reason_code": NO_VALIDATED_PATH_RISK},
        "margin_snapshot": {"status": "not_scored"},
        "hazard_zone": {"status": "not_scored"},
        "kill_conditions": [],
        "reason_codes": reason_codes,
        "edge_components": None,
        "dominated_by": None,
        "losing_axes": [],
    }


def _ranking_score(score: dict[str, Any]) -> float | None:
    """The primary published axis, exposed as-is rather than as a blend."""
    item = (score.get("components") or {}).get("smile_residual_richness") or {}
    return item.get("value") if item.get("status") in {OK, CAUTION} else None


def _executable_credit_usd(
    candidate: dict[str, Any], structure_type: str | None, spot: Any
) -> float | None:
    """The credit the quotes actually support: sell at the bid, buy at the ask."""
    raw = (
        candidate.get("net_credit")
        if candidate.get("net_credit") is not None
        else candidate.get("market_bid")
    )
    return normalize_premium_to_usd(
        raw, premium_unit=candidate.get("premium_unit"), underlying_price=spot
    )


def _fair_value_usd(
    candidate: dict[str, Any], structure_type: str | None
) -> float | None:
    """Credit the structure would collect if every leg traded at its fitted IV.

    Valued leg by leg, so a two-sided or many-legged structure is priced by the
    same code as a single short call. A structure whose legs are not all
    priceable returns None rather than a partial sum, which would understate the
    fair credit and make the quote look rich.
    """
    spot = candidate.get("underlying_price")
    dte = candidate.get("dte_days")
    if not isinstance(spot, (int, float)) or not isinstance(dte, (int, float)):
        return None

    legs = candidate.get("structure_legs")
    if not isinstance(legs, list) or not legs:
        return None

    total = 0.0
    for leg in legs:
        if not isinstance(leg, dict):
            return None
        price = black_scholes_price(
            underlying_price=spot,
            strike=leg.get("strike") or 0.0,
            iv_percent=leg.get("surface_fitted_iv") or 0.0,
            dte_days=dte,
            option_type=str(leg.get("option_type") or "call"),
        )
        quantity = leg.get("quantity")
        if price is None or not isinstance(quantity, (int, float)):
            return None
        # Selling a leg collects its price, buying one pays it.
        total -= float(quantity) * price
    return round(total, 6)


def _price_divergence_suspect(
    executable_credit: float | None, fair_value: float | None
) -> bool:
    """Flag quotes implausibly far from the model's own valuation."""
    if executable_credit is None or fair_value is None or fair_value <= 0:
        return False
    ratio = executable_credit / fair_value
    return (
        ratio > MAX_CREDIT_TO_FAIR_VALUE_RATIO
        or ratio < MIN_CREDIT_TO_FAIR_VALUE_RATIO
    )


def _fair_iv_diagnostics(
    score: dict[str, Any], candidate: dict[str, Any], structure_type: str | None
) -> dict[str, Any]:
    richness = (score.get("components") or {}).get("smile_residual_richness") or {}
    if structure_type == SPREAD:
        market_iv = candidate.get("sell_leg_market_mark_iv")
        fitted_iv = candidate.get("sell_leg_surface_fitted_iv")
    else:
        market_iv = candidate.get("market_mark_iv")
        fitted_iv = candidate.get("surface_fitted_iv")
    return {
        "status": "uncalibrated_research_only",
        "market_mark_iv": market_iv,
        "surface_fitted_iv": fitted_iv,
        "residual_iv_points": richness.get("value"),
        "residual_status": richness.get("status"),
        "measure": "risk_neutral_fitted_smile",
    }


def _margin_snapshot(
    candidate: dict[str, Any], structure_type: str | None
) -> dict[str, Any]:
    """A defined-risk reference only, and only when the legs say risk is defined."""
    legs = candidate.get("structure_legs")
    if isinstance(legs, list) and legs:
        try:
            structure = build_structure(
                structure_type=str(structure_type or "candidate"), legs=legs
            )
            bounded = (
                not structure.is_multi_expiry
                and structure.risk_profile(entry_cash=0.0).loss_is_bounded
            )
        except ValueError:
            bounded = False
        if bounded:
            return {
                "status": "reference_proxy",
                "basis": "defined_risk_width",
                "reference_margin_usdc": candidate.get("spread_width"),
                "account_specific": False,
            }
    return {
        "status": "unavailable",
        "basis": "unbounded_loss_requires_account_context",
        "reference_margin_usdc": None,
        "account_specific": False,
    }


def _hazard_zone(score: dict[str, Any]) -> dict[str, Any]:
    components = score.get("components") or {}
    cushion = components.get("breakeven_cushion") or {}
    assignment = components.get("assignment_cost") or {}
    return {
        "status": "uncalibrated_research_only",
        "breakeven_cushion_expected_moves": cushion.get("value"),
        "risk_neutral_p_itm": assignment.get("value"),
        "physical_probability_available": False,
    }


def _summary(ranked_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidates_scanned": len(ranked_candidates),
        "review_candidates": sum(
            candidate.get("action") == REVIEW for candidate in ranked_candidates
        ),
        "rejected_candidates": sum(
            candidate.get("action") == REJECT for candidate in ranked_candidates
        ),
        "kill_condition_candidates": sum(
            bool(candidate.get("kill_conditions")) for candidate in ranked_candidates
        ),
        "top_candidate_id": (
            ranked_candidates[0].get("candidate_id") if ranked_candidates else None
        ),
        "top_candidate_action": (
            ranked_candidates[0].get("action") if ranked_candidates else None
        ),
    }


def build_absolute_ev(
    *,
    candidate: dict[str, Any],
    structure_type: str,
    underlying_history: dict[str, Any],
    entry_credit_usdc: float | None,
    permission_state: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Expected value of selling this candidate, net of modelled costs.

    Sign convention matters here. `path_risk` reports `expected_payoff_usdc` as
    the seller's expected *payout*, not profit, so expected value is the credit
    received minus that payout minus fees. Reading the payout as profit would
    invert the conclusion.
    """
    spot = candidate.get("underlying_price")
    dte = candidate.get("dte_days")
    if (
        not isinstance(spot, (int, float))
        or not isinstance(dte, (int, float))
        or entry_credit_usdc is None
    ):
        return {"status": "unavailable", "reason_code": "MISSING_CANDIDATE_ECONOMICS"}

    horizon = int(dte)
    if horizon < 1:
        return {"status": "unavailable", "reason_code": "HORIZON_TOO_SHORT"}

    legs = candidate.get("structure_legs")
    strike = (
        candidate.get("sell_leg_strike_price")
        if candidate.get("sell_leg_strike_price") is not None
        else candidate.get("strike_price")
    )
    if not isinstance(strike, (int, float)) and isinstance(legs, list) and legs:
        # A structure with no single "the" strike still has a nearest one to
        # spot, which is what the crossing diagnostic is measured against.
        strikes = [
            leg.get("strike")
            for leg in legs
            if isinstance(leg, dict) and isinstance(leg.get("strike"), (int, float))
        ]
        strike = min(strikes, key=lambda value: abs(value - float(spot))) if strikes else None
    if not isinstance(strike, (int, float)):
        return {"status": "unavailable", "reason_code": "MISSING_STRIKE"}

    permission = permission_state or {}
    regime_scores = _numeric_map(permission.get("regime_scores"))
    feature_vector = _numeric_map(permission.get("volatility_inputs"))
    # With no regime evidence the similarity kernel has nothing to match on, so
    # neutral inputs are used and the weighting degenerates to uniform. That is
    # the honest "no regime information" behaviour, and it is recorded as such
    # rather than presented as a regime-matched sample.
    regime_similarity_applied = bool(regime_scores and feature_vector)
    if not regime_scores:
        regime_scores = {"neutral": 0.0}
    if not feature_vector:
        feature_vector = {"neutral": 0.0}

    # Greeks are inputs to the loss distribution, not decoration: delta drives
    # the crossing diagnostic and vega prices the IV-jump stress leg. Substituting
    # a placeholder when they are absent would produce a stress cost that is an
    # artefact of the placeholder, so a candidate without them is unavailable.
    abs_delta = _positive_magnitude(candidate.get("model_delta"))
    vega_per_iv_point = _positive_magnitude(candidate.get("model_vega"))
    if abs_delta is None or vega_per_iv_point is None:
        return {"status": "unavailable", "reason_code": MISSING_CANDIDATE_GREEKS}
    if abs_delta > 1.0:
        return {"status": "unavailable", "reason_code": "IMPLAUSIBLE_CANDIDATE_DELTA"}

    # The crossing threshold is the move that takes spot to the nearest strike.
    # For an upside-only structure that must be a rise; for a structure whose
    # risk is below spot the diagnostic measures the distance, not the sign.
    delta_cross_up_return = abs(float(strike) / float(spot) - 1.0)
    if delta_cross_up_return <= 0.0:
        return {"status": "unavailable", "reason_code": "STRIKE_EQUALS_SPOT"}

    spec = {
        "instrument_name": str(candidate.get("candidate_id") or "candidate"),
        "structure": structure_type,
        "current_spot": float(spot),
        "strike": float(strike),
        "long_strike": (
            candidate.get("buy_leg_strike_price")
            if structure_type == SPREAD
            else None
        ),
        # When the candidate carries its legs the tracer prices them directly,
        # which is the only way a two-sided structure gets a correct payoff.
        **({"legs": legs} if isinstance(legs, list) and legs else {}),
        "horizon_days": horizon,
        "entry_credit_usdc": float(max(entry_credit_usdc, 0.0)),
        "contract_size": 1.0,
        # Losses are reported per contract in USD. NAV-relative figures would
        # need an account snapshot, so this reference NAV is never surfaced.
        "starting_nav_usdc": 100_000.0,
        "current_abs_delta": abs_delta,
        "delta_cross_up_return": delta_cross_up_return,
        # `model_vega` is USD per one IV *point*; the stress scenarios quote
        # `iv_jump` in absolute volatility, where 1.0 is 100 points. Passing the
        # per-point figure straight through understated every IV-jump stress
        # cost by two orders of magnitude.
        "vega_usdc_per_abs_vol": round(vega_per_iv_point * 100.0, 6),
        # No volatility rescaling. Each historical window is replayed at the
        # volatility it actually had, so the volatility dispersion that produces
        # a short-volatility seller's tail losses survives into the CVaR.
        "vol_scaling": {"mode": VOL_SCALING_NONE},
        "regime_scores": regime_scores,
        "feature_vector": feature_vector,
    }

    try:
        report = build_path_risk_report_from_underlying_history(
            underlying_history, spec, generated_at=generated_at
        )
    except ValueError as exc:
        # A malformed candidate must not propagate an exception through a
        # research projection; it fails closed like any other missing input.
        return {
            "status": "unavailable",
            "reason_code": "INVALID_CANDIDATE_SPEC",
            "detail": str(exc),
        }
    evidence = report.get("input_evidence") or {}
    if evidence.get("status") != "validated_historical":
        return {
            "status": "unavailable",
            "reason_code": (evidence.get("reason_codes") or [NO_VALIDATED_PATH_RISK])[0],
        }

    distributions = report.get("distributions") or {}
    expected_payout = distributions.get("expected_payoff_usdc")
    if not isinstance(expected_payout, (int, float)):
        return {"status": "unavailable", "reason_code": "MISSING_EXPECTED_PAYOFF"}

    fees = _modelled_fees(
        candidate=candidate,
        spot=float(spot),
        entry_credit_usdc=float(entry_credit_usdc),
        expected_payout_usdc=float(expected_payout),
        p_itm=distributions.get("p_itm"),
    )
    if fees is None:
        return {"status": "unavailable", "reason_code": "PREMIUM_UNIT_UNKNOWN"}

    bound = report.get("independent_sample_bound") or {}
    ev = float(entry_credit_usdc) - float(expected_payout) - fees["total_usdc"]
    return {
        "status": "validated",
        "reason_code": None,
        "ev_after_cost_usdc": round(ev, 6),
        "entry_credit_usdc": round(float(entry_credit_usdc), 6),
        "expected_payout_usdc": round(float(expected_payout), 6),
        "modelled_fees_usdc": fees,
        "p_touch": distributions.get("p_touch"),
        "p_itm": distributions.get("p_itm"),
        "cvar_95_usdc": distributions.get("cvar_95_usdc"),
        "cvar_99_usdc": distributions.get("cvar_99_usdc"),
        "authoritative_sample_size": bound.get("authoritative_sample_size"),
        "sample_size_basis": bound.get("sample_size_basis"),
        "evidence_class": evidence.get("evidence_class"),
        "nav_relative_metrics_available": False,
        "regime_similarity_applied": regime_similarity_applied,
        "measure": "physical_realized_return_distribution",
        # Echoed so the reader can see that the distribution behind this number
        # is the underlying's own history, not a history rescaled to an assumed
        # volatility level.
        "volatility_scaling": (
            (report.get("path_sampling") or {}).get("volatility_scaling") or {}
        ).get("mode"),
        "source_vol_dispersion": (
            (report.get("path_sampling") or {}).get("volatility_scaling") or {}
        ).get("observed_source_vol_dispersion"),
    }


def _modelled_fees(
    *,
    candidate: dict[str, Any],
    spot: float,
    entry_credit_usdc: float,
    expected_payout_usdc: float,
    p_itm: Any,
) -> dict[str, Any] | None:
    """Entry fee plus assignment-weighted delivery fee, in the venue's own units."""
    unit = candidate.get("premium_unit")
    itm_weight = float(p_itm) if isinstance(p_itm, (int, float)) else 1.0
    if unit == "quote_currency":
        entry = option_fee_linear(entry_credit_usdc, spot, 1.0)
        delivery = delivery_fee_linear(expected_payout_usdc, spot, 1.0)
        basis = "linear"
    elif unit == "inverse_base_currency":
        if spot <= 0:
            return None
        entry = option_fee_inverse(entry_credit_usdc / spot, 1.0) * spot
        delivery = delivery_fee_inverse(expected_payout_usdc / spot, 1.0) * spot
        basis = "inverse"
    else:
        return None
    weighted_delivery = delivery * itm_weight
    return {
        "basis": basis,
        "entry_fee_usdc": round(entry, 6),
        "expected_delivery_fee_usdc": round(weighted_delivery, 6),
        "delivery_fee_weighted_by": "p_itm",
        "total_usdc": round(entry + weighted_delivery, 6),
    }


def _positive_magnitude(value: Any) -> float | None:
    """Absolute value of a finite non-zero number, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    magnitude = abs(float(value))
    if not math.isfinite(magnitude) or magnitude <= 0.0:
        return None
    return magnitude


def _numeric_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def _apply_absolute_ev(
    ranked_candidates: list[dict[str, Any]],
    *,
    scored_by_id: dict[Any, dict[str, Any]],
    underlying_history: dict[str, Any] | None,
    permission_state: dict[str, Any] | None,
    generated_at: str | None,
) -> int:
    """Populate expected value for the leading candidates; return how many.

    Bounded on purpose: each candidate replays the whole path set, and a chain
    can carry far more candidates than are worth that cost.
    """
    if not underlying_history:
        return 0

    applied = 0
    for row in ranked_candidates:
        if applied >= MAX_ABSOLUTE_EV_CANDIDATES:
            break
        if row.get("action") == REJECT:
            continue
        score = scored_by_id.get(row.get("candidate_id"))
        if not score:
            continue
        result = build_absolute_ev(
            candidate=score.get("_candidate") or {},
            structure_type=row.get("structure_type") or "",
            underlying_history=underlying_history,
            entry_credit_usdc=row.get("executable_credit_usdc"),
            permission_state=permission_state,
            generated_at=generated_at,
        )
        row["absolute_ev"] = result
        if result.get("status") != "validated":
            continue
        row["ev_after_cost_usdc"] = result["ev_after_cost_usdc"]
        row["path_risk"] = {
            "status": "validated_historical",
            "reason_code": None,
            "evidence_class": result.get("evidence_class"),
            "p_touch": result.get("p_touch"),
            "p_itm": result.get("p_itm"),
            "cvar_95_usdc": result.get("cvar_95_usdc"),
            "cvar_99_usdc": result.get("cvar_99_usdc"),
            "authoritative_sample_size": result.get("authoritative_sample_size"),
            "sample_size_basis": result.get("sample_size_basis"),
        }
        if NO_VALIDATED_PATH_RISK in row["kill_conditions"]:
            row["kill_conditions"] = [
                code
                for code in row["kill_conditions"]
                if code != NO_VALIDATED_PATH_RISK
            ]
        applied += 1
    return applied
