"""Relative-value edge scoring for research candidates.

This layer answers one bounded question: **among the candidates on this chain
right now, which are better priced than the others?** It deliberately does not
answer "is selling volatility profitable", which is a physical-measure claim
requiring realized-return evidence (`realized_vol.py`) and, for any promoted
claim, walk-forward validation.

Two design choices carry most of the honesty burden:

* **No weighted sum.** Blending vol points, cost fractions, sigma multiples and
  probability into one number requires weights, and a weight vector is an
  unstated confidence claim ("richness matters twice as much as carry"). Instead
  candidates are partitioned onto a Pareto frontier and only tie-broken in a
  published lexicographic order. This also makes "why did it rank there"
  answerable: a dominated candidate is beaten by a specific rival on a specific
  set of axes.
* **Components fail closed independently.** A missing input blocks its own
  component and that axis is dropped from comparison; it is never imputed. A
  candidate with any blocked component is reported separately rather than
  silently ranked as if fully evidenced.
"""

from __future__ import annotations

import math
from typing import Any

from .structures import build_structure

EDGE_SCORE_SCHEMA_VERSION = "relative_value_edge_score.v1"

# Component status vocabulary.
OK = "OK"
CAUTION = "CAUTION"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"

HIGHER_BETTER = "higher_better"
LOWER_BETTER = "lower_better"

# Published tie-break order. Changing this changes displayed rank, so it is a
# contract, not an implementation detail.
TIE_BREAK_ORDER = (
    ("smile_residual_richness", HIGHER_BETTER),
    ("return_on_risk", HIGHER_BETTER),
    ("liquidity_cost_ratio", LOWER_BETTER),
    ("theta_efficiency", HIGHER_BETTER),
    ("breakeven_cushion", HIGHER_BETTER),
    ("assignment_cost", LOWER_BETTER),
)

NAKED = "naked_short_call"
SPREAD = "call_credit_spread"

UNBOUNDED_MAX_LOSS = "UNBOUNDED_MAX_LOSS_NO_RETURN_ON_RISK_DEFINED"
MISSING_ATM_REFERENCE = "MISSING_ATM_SURFACE_REFERENCE"
PREMIUM_UNIT_UNKNOWN = "PREMIUM_UNIT_UNKNOWN"
VEGA_ZERO_OR_MISSING = "VEGA_ZERO_OR_MISSING"
NON_POSITIVE_MID_CREDIT = "NON_POSITIVE_MID_CREDIT"
SURFACE_NOT_TRUSTED = "SURFACE_FIT_NOT_TRUSTED"
RESIDUAL_SCALE_UNAVAILABLE = "RESIDUAL_SCALE_UNAVAILABLE"
INDEX_SPOT_FORWARD_FALLBACK = "INDEX_SPOT_SUBSTITUTED_FOR_FORWARD"


def normalize_premium_to_usd(
    value: float | None,
    *,
    premium_unit: str | None,
    underlying_price: float | None,
) -> float | None:
    """Convert a quoted premium to USD.

    Deribit lists both inverse (coin-quoted) and linear (quote-currency)
    options. Dividing a coin-quoted credit by a USD strike width is wrong by
    roughly the spot price, so every USD figure in this module routes through
    here. An undeclared unit returns None rather than assuming a convention.
    """
    if value is None or not isinstance(value, (int, float)):
        return None
    if premium_unit == "quote_currency":
        return float(value)
    if premium_unit == "inverse_base_currency":
        if not isinstance(underlying_price, (int, float)) or underlying_price <= 0:
            return None
        return float(value) * float(underlying_price)
    return None


def build_relative_value_edge_score(
    *,
    candidate: dict[str, Any],
    structure_type: str,
    atm_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one candidate's relative value; never its absolute profitability."""
    components: dict[str, dict[str, Any]] = {
        "smile_residual_richness": _smile_residual_richness(candidate, structure_type),
        "liquidity_cost_ratio": _liquidity_cost_ratio(candidate, structure_type),
        "breakeven_cushion": _breakeven_cushion(candidate, structure_type, atm_reference),
        "theta_efficiency": _theta_efficiency(candidate),
        "assignment_cost": _assignment_cost(candidate),
        "return_on_risk": _return_on_risk(candidate, structure_type),
    }

    # A blocked surface fit invalidates every fitted-IV-derived component at
    # once, so it is checked as a whole rather than per component.
    if not _surface_trusted(candidate):
        for name in ("smile_residual_richness", "breakeven_cushion"):
            components[name] = _component(
                None, "residual_std_errors", BLOCKED, SURFACE_NOT_TRUSTED, HIGHER_BETTER
            )

    blocked = [
        name
        for name, item in components.items()
        if item["status"] == BLOCKED and not _structurally_absent(name, structure_type)
    ]
    unknown = [name for name, item in components.items() if item["status"] == UNKNOWN]

    status = "partial" if blocked or unknown else "scored"

    return {
        "schema_version": EDGE_SCORE_SCHEMA_VERSION,
        "candidate_id": candidate.get("candidate_id"),
        "structure_type": structure_type,
        "status": status,
        "components": components,
        "blocked_components": blocked,
        "unknown_components": unknown,
        "cannot_tell": [
            "This score is relative to the current chain only. It does not "
            "establish that selling volatility here is profitable.",
            "All inputs are risk-neutral / model-implied; none is a physical "
            "probability.",
            "The pricing model assumes zero rate and forward = spot, so any "
            "real basis is unmodelled.",
        ],
    }


def rank_candidates_by_edge(
    scored_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Partition candidates onto a Pareto frontier, then tie-break lexically.

    Dominance is computed **within a structure type**. A naked call has no
    defined return-on-risk (its loss is unbounded), so comparing it against a
    spread on the axes that happen to remain would let it win by absence of
    evidence rather than by merit.
    """
    fully_scored = [item for item in scored_candidates if item.get("status") == "scored"]
    partial = [item for item in scored_candidates if item.get("status") == "partial"]

    frontier: list[dict[str, Any]] = []
    dominated: list[dict[str, Any]] = []

    for structure_type in sorted({item.get("structure_type") for item in fully_scored}):
        group = [
            item for item in fully_scored if item.get("structure_type") == structure_type
        ]
        for candidate in group:
            dominators = [
                rival
                for rival in group
                if rival is not candidate and _dominates(rival, candidate)
            ]
            if dominators:
                best = _sort_key(dominators[0])
                winner = dominators[0]
                for rival in dominators[1:]:
                    if _sort_key(rival) < best:
                        best, winner = _sort_key(rival), rival
                dominated.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "structure_type": structure_type,
                        "dominated_by": winner.get("candidate_id"),
                        "losing_axes": _losing_axes(winner, candidate),
                    }
                )
            else:
                frontier.append(candidate)

    frontier.sort(key=_sort_key)
    return {
        "schema_version": EDGE_SCORE_SCHEMA_VERSION,
        "frontier": frontier,
        "dominated": dominated,
        "partial_evidence": partial,
        "tie_break_order": [name for name, _ in TIE_BREAK_ORDER],
        "dominance_scope": "within_structure_type",
        "frontier_occupancy": _frontier_occupancy(fully_scored, frontier),
    }


# Above this share of candidates surviving on the frontier, Pareto dominance has
# stopped discriminating and the displayed order is, in practice, produced by the
# first tie-break axis alone.
FRONTIER_DEGENERACY_THRESHOLD = 0.8


def _frontier_occupancy(
    fully_scored: list[dict[str, Any]], frontier: list[dict[str, Any]]
) -> dict[str, Any]:
    """How much of the ranking Pareto dominance is actually doing.

    Dominance requires a rival to be at least as good on *every* comparable
    axis. With six axes that condition is rarely met, so the frontier tends to
    swallow the whole candidate set and the published order collapses onto
    `TIE_BREAK_ORDER[0]`. The design note in this module argues that avoiding a
    weighted sum avoids an unstated claim about relative importance; when the
    frontier is degenerate that claim has simply moved into the tie-break order
    instead of disappearing. Reporting the occupancy keeps that visible rather
    than letting the Pareto framing imply a discrimination it is not providing.
    """
    frontier_ids = {item.get("candidate_id") for item in frontier}
    by_structure: dict[str, dict[str, Any]] = {}
    for structure_type in sorted(
        {item.get("structure_type") for item in fully_scored}
    ):
        group = [
            item for item in fully_scored if item.get("structure_type") == structure_type
        ]
        on_frontier = sum(
            1 for item in group if item.get("candidate_id") in frontier_ids
        )
        fraction = on_frontier / len(group) if group else 0.0
        by_structure[str(structure_type)] = {
            "scored_candidates": len(group),
            "frontier_candidates": on_frontier,
            "frontier_fraction": round(fraction, 6),
            "dominance_discriminating": fraction < FRONTIER_DEGENERACY_THRESHOLD,
        }

    total = len(fully_scored)
    overall = len(frontier_ids) / total if total else 0.0
    degenerate = total > 0 and overall >= FRONTIER_DEGENERACY_THRESHOLD
    return {
        "axis_count": len(TIE_BREAK_ORDER),
        "scored_candidates": total,
        "frontier_candidates": len(frontier_ids),
        "frontier_fraction": round(overall, 6),
        "degeneracy_threshold": FRONTIER_DEGENERACY_THRESHOLD,
        "dominance_discriminating": not degenerate,
        "effective_ranking_basis": (
            f"lexicographic_on_{TIE_BREAK_ORDER[0][0]}"
            if degenerate
            else "pareto_frontier_then_lexicographic"
        ),
        "by_structure_type": by_structure,
    }


# --- components ------------------------------------------------------------


def _smile_residual_richness(
    candidate: dict[str, Any], structure_type: str
) -> dict[str, Any]:
    """How far the mark sits above its own fitted smile, in residual standard errors.

    Uses mark, not bid. `bid_iv - fitted_iv` collapses to minus half the
    bid/ask spread whenever the fit is good, which measures quote width rather
    than mispricing and would rank widely-quoted strikes as cheap.

    The value is standardized by the expiry's own residual scale rather than
    left in raw IV points. Raw points are not comparable between chains: on a
    scattered smile a 1.5-point residual is inside the fit's own noise, while on
    a tight one it is a large deviation. Ranking on raw points therefore
    systematically promotes the thinnest, worst-fit expiries — the ones where a
    three-parameter quadratic has the fewest quotes to constrain it. The raw
    figure is still carried for display.

    A missing residual scale blocks the component rather than falling back to
    raw points, because the chains that cannot support the scale are exactly the
    ones the fallback would flatter.
    """
    if structure_type == SPREAD:
        sell = _residual(candidate, "sell_leg_market_mark_iv", "sell_leg_surface_fitted_iv")
        buy = _residual(candidate, "buy_leg_market_mark_iv", "buy_leg_surface_fitted_iv")
        raw = None if sell is None or buy is None else sell - buy
    else:
        raw = _residual(candidate, "market_mark_iv", "surface_fitted_iv")

    if raw is None:
        return _component(None, "residual_std_errors", UNKNOWN, None, HIGHER_BETTER)

    scale = _number(candidate.get("fit_residual_scale"))
    if scale is None or scale <= 1e-9:
        component = _component(
            None,
            "residual_std_errors",
            BLOCKED,
            RESIDUAL_SCALE_UNAVAILABLE,
            HIGHER_BETTER,
        )
        component["raw_iv_points"] = round(raw, 6)
        return component

    status, reason = OK, None
    if candidate.get("underlying_price_source") != "option_forward":
        # A wrong forward shifts every strike's moneyness, which moves the
        # fitted smile under the mark and shows up here as richness that is an
        # artefact of the substitution.
        status, reason = CAUTION, INDEX_SPOT_FORWARD_FALLBACK

    component = _component(
        round(raw / scale, 6), "residual_std_errors", status, reason, HIGHER_BETTER
    )
    component["raw_iv_points"] = round(raw, 6)
    component["residual_scale_iv_points"] = round(scale, 6)
    return component


def _liquidity_cost_ratio(
    candidate: dict[str, Any], structure_type: str
) -> dict[str, Any]:
    """Fraction of the mid-to-mid credit surrendered to both legs' spreads.

    Only meaningful for spreads. For a single leg it reduces to the existing
    `spread_ratio` field and would double-count it in dominance.
    """
    if structure_type != SPREAD:
        return _component(None, "ratio", BLOCKED, "SINGLE_LEG_USES_SPREAD_RATIO", LOWER_BETTER)

    sell_mid = _mid(candidate, "sell_leg_market_bid", "sell_leg_market_ask")
    buy_mid = _mid(candidate, "buy_leg_market_bid", "buy_leg_market_ask")
    credit = _number(candidate.get("net_credit"))
    if sell_mid is None or buy_mid is None or credit is None:
        return _component(None, "ratio", UNKNOWN, None, LOWER_BETTER)

    mid_credit = sell_mid - buy_mid
    if mid_credit <= 0:
        return _component(None, "ratio", BLOCKED, NON_POSITIVE_MID_CREDIT, LOWER_BETTER)
    return _component(round(1.0 - (credit / mid_credit), 6), "ratio", OK, None, LOWER_BETTER)


def _breakeven_cushion(
    candidate: dict[str, Any],
    structure_type: str,
    atm_reference: dict[str, Any] | None,
) -> dict[str, Any]:
    """Distance from breakeven to spot, in ATM 1-sigma expected moves.

    Expected move is an ATM-vol convention. Substituting this candidate's own
    out-of-the-money fitted IV would systematically distort the cushion with the
    smile's skew, so an absent ATM reference yields UNKNOWN rather than a
    fallback.
    """
    spot = _number(candidate.get("underlying_price"))
    dte = _number(candidate.get("dte_days"))
    if spot is None or spot <= 0 or dte is None or dte <= 0:
        return _component(None, "expected_moves", UNKNOWN, None, HIGHER_BETTER)

    atm_iv = _number((atm_reference or {}).get("surface_fitted_iv"))
    if atm_iv is None or atm_iv <= 0:
        return _component(
            None, "expected_moves", UNKNOWN, MISSING_ATM_REFERENCE, HIGHER_BETTER
        )

    premium_unit = candidate.get("premium_unit")
    credit = normalize_premium_to_usd(
        _number(candidate.get("net_credit"))
        if structure_type == SPREAD
        else _number(candidate.get("market_bid")),
        premium_unit=premium_unit,
        underlying_price=spot,
    )
    if credit is None:
        return _component(
            None, "expected_moves", BLOCKED, PREMIUM_UNIT_UNKNOWN, HIGHER_BETTER
        )

    expected_move = spot * (atm_iv / 100.0) * math.sqrt(dte / 365.0)
    if expected_move <= 0:
        return _component(None, "expected_moves", UNKNOWN, None, HIGHER_BETTER)

    cushion = _nearest_breakeven_distance(candidate, spot=spot, credit_usd=credit)
    if cushion is None:
        return _component(None, "expected_moves", UNKNOWN, None, HIGHER_BETTER)
    return _component(
        round(cushion / expected_move, 6), "expected_moves", OK, None, HIGHER_BETTER
    )


def _nearest_breakeven_distance(
    candidate: dict[str, Any], *, spot: float, credit_usd: float
) -> float | None:
    """How far spot can travel before the structure starts losing.

    Taken from the structure's own breakevens, so a two-sided position is
    measured by whichever side is closer rather than by the upside alone. The
    legacy `strike + credit - spot` form is kept for candidates that predate
    legs, and is the same quantity for an upside-only short.
    """
    legs = candidate.get("structure_legs")
    if isinstance(legs, list) and legs:
        try:
            structure = build_structure(
                structure_type=str(candidate.get("structure_type") or "candidate"),
                legs=legs,
            )
            if structure.is_multi_expiry:
                return None
            breakevens = structure.risk_profile(entry_cash=credit_usd).breakevens
        except ValueError:
            return None
        if not breakevens:
            return None
        return min(abs(level - spot) for level in breakevens)

    strike = _number(
        candidate.get("sell_leg_strike_price")
        if candidate.get("sell_leg_strike_price") is not None
        else candidate.get("strike_price")
    )
    if strike is None:
        return None
    return (strike + credit_usd) - spot


def _theta_efficiency(candidate: dict[str, Any]) -> dict[str, Any]:
    """Daily decay collected per unit of vol exposure, in position sign.

    Position greeks are read from the candidate's aggregated legs when they are
    present. The legacy fallback negates `model_theta`/`model_vega`, which are
    the *long* option's greeks, and is correct only because every legacy
    structure is net short. Aggregated legs carry their own direction, so a
    structure that is net long vol reports a negative efficiency instead of a
    sign-flipped positive one.
    """
    position = candidate.get("position_greeks")
    if isinstance(position, dict) and position.get("status") == "aggregated":
        position_theta = _number(position.get("theta"))
        position_vega = _number(position.get("vega"))
    else:
        theta = _number(candidate.get("model_theta"))
        vega = _number(candidate.get("model_vega"))
        position_theta = None if theta is None else -theta
        position_vega = None if vega is None else -vega

    if position_theta is None or position_vega is None:
        return _component(None, "per_vol_point", UNKNOWN, None, HIGHER_BETTER)
    if abs(position_vega) < 1e-12:
        return _component(
            None, "per_vol_point", BLOCKED, VEGA_ZERO_OR_MISSING, HIGHER_BETTER
        )
    value = position_theta / abs(position_vega)
    status = OK if value > 0 else CAUTION
    reason = None if value > 0 else "NEGATIVE_THETA_EFFICIENCY"
    return _component(round(value, 6), "per_vol_point", status, reason, HIGHER_BETTER)


def _assignment_cost(candidate: dict[str, Any]) -> dict[str, Any]:
    """Model-implied ITM probability, used only as a tie-break axis.

    This is a risk-neutral quantity: it already embeds the risk premium and is
    not the physical chance of assignment. It must never be presented as one.
    """
    p_itm = _number(candidate.get("risk_neutral_p_itm"))
    if p_itm is None or not (0.0 <= p_itm <= 1.0):
        return _component(None, "risk_neutral_probability", UNKNOWN, None, LOWER_BETTER)
    consistency = (candidate.get("greek_consistency") or {}).get("status")
    if consistency == "reject":
        return _component(
            round(p_itm, 6),
            "risk_neutral_probability",
            CAUTION,
            "GREEK_CONSISTENCY_REJECTED",
            LOWER_BETTER,
        )
    return _component(round(p_itm, 6), "risk_neutral_probability", OK, None, LOWER_BETTER)


def _return_on_risk(candidate: dict[str, Any], structure_type: str) -> dict[str, Any]:
    """Credit over maximum loss, for any structure whose loss is bounded.

    The bound comes from the candidate's own legs rather than from its name. A
    put credit spread and an iron condor are as defined-risk as a call credit
    spread, and a ratio that is net short calls is as unbounded as a naked
    short, none of which is derivable from a structure-type string.
    """
    spot = _number(candidate.get("underlying_price"))
    credit_usd = normalize_premium_to_usd(
        _number(candidate.get("net_credit"))
        if structure_type == SPREAD
        else _number(candidate.get("market_bid")),
        premium_unit=candidate.get("premium_unit"),
        underlying_price=spot,
    )
    if credit_usd is None:
        return _component(None, "ratio", BLOCKED, PREMIUM_UNIT_UNKNOWN, HIGHER_BETTER)

    max_loss = _structure_max_loss(candidate, credit_usd=credit_usd)
    if max_loss is None:
        # Either the legs say the loss runs without limit, or they are absent
        # and the legacy width is unavailable. Both mean no denominator exists.
        return _component(None, "ratio", BLOCKED, UNBOUNDED_MAX_LOSS, HIGHER_BETTER)
    if max_loss <= 0:
        return _component(None, "ratio", BLOCKED, "NON_POSITIVE_MAX_LOSS", HIGHER_BETTER)
    return _component(round(credit_usd / max_loss, 6), "ratio", OK, None, HIGHER_BETTER)


def _structure_max_loss(
    candidate: dict[str, Any], *, credit_usd: float
) -> float | None:
    """Maximum loss from the candidate's legs; None when unbounded or unknown."""
    legs = candidate.get("structure_legs")
    if isinstance(legs, list) and legs:
        try:
            structure = build_structure(
                structure_type=str(candidate.get("structure_type") or "candidate"),
                legs=legs,
            )
            if structure.is_multi_expiry:
                return None
            profile = structure.risk_profile(entry_cash=credit_usd)
        except ValueError:
            return None
        return profile.max_loss

    # Legacy candidates without legs: only the call credit spread's width was
    # ever available, and a naked short has no bound to fall back on.
    width = _number(candidate.get("spread_width"))
    if width is None:
        return None
    return width - credit_usd


# --- dominance -------------------------------------------------------------


def _comparable_axes(left: dict[str, Any], right: dict[str, Any]) -> list[tuple[str, str]]:
    axes: list[tuple[str, str]] = []
    for name, direction in TIE_BREAK_ORDER:
        left_item = left["components"].get(name) or {}
        right_item = right["components"].get(name) or {}
        if left_item.get("status") in {OK, CAUTION} and right_item.get("status") in {
            OK,
            CAUTION,
        }:
            axes.append((name, direction))
    return axes


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    axes = _comparable_axes(left, right)
    if not axes:
        return False
    strictly_better_somewhere = False
    for name, direction in axes:
        left_value = left["components"][name]["value"]
        right_value = right["components"][name]["value"]
        if left_value is None or right_value is None:
            return False
        if direction == HIGHER_BETTER:
            if left_value < right_value:
                return False
            if left_value > right_value:
                strictly_better_somewhere = True
        else:
            if left_value > right_value:
                return False
            if left_value < right_value:
                strictly_better_somewhere = True
    return strictly_better_somewhere


def _losing_axes(winner: dict[str, Any], loser: dict[str, Any]) -> list[str]:
    losing: list[str] = []
    for name, direction in _comparable_axes(winner, loser):
        winner_value = winner["components"][name]["value"]
        loser_value = loser["components"][name]["value"]
        if winner_value is None or loser_value is None:
            continue
        better = (
            winner_value > loser_value
            if direction == HIGHER_BETTER
            else winner_value < loser_value
        )
        if better:
            losing.append(name)
    return losing


def _sort_key(scored: dict[str, Any]) -> tuple:
    key: list[Any] = []
    for name, direction in TIE_BREAK_ORDER:
        item = scored["components"].get(name) or {}
        value = item.get("value")
        if item.get("status") not in {OK, CAUTION} or value is None:
            # Missing axes sort last without being treated as a real value.
            key.append(math.inf)
            continue
        key.append(-value if direction == HIGHER_BETTER else value)
    key.append(str(scored.get("candidate_id") or ""))
    return tuple(key)


# --- helpers ---------------------------------------------------------------


def _component(
    value: float | None,
    unit: str,
    status: str,
    reason_code: str | None,
    direction: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "reason_code": reason_code,
        "direction": direction,
    }


def _structurally_absent(component_name: str, structure_type: str) -> bool:
    """True when a component is undefined by structure, not by missing data."""
    return structure_type != SPREAD and component_name in {
        "liquidity_cost_ratio",
        "return_on_risk",
    }


def _surface_trusted(candidate: dict[str, Any]) -> bool:
    quality = candidate.get("surface_quality") or {}
    return quality.get("no_arb_pass") is True and _number(
        quality.get("fit_quality_score")
    ) is not None


def _residual(candidate: dict[str, Any], mark_key: str, fitted_key: str) -> float | None:
    mark = _number(candidate.get(mark_key))
    fitted = _number(candidate.get(fitted_key))
    if mark is None or fitted is None:
        return None
    return mark - fitted


def _mid(candidate: dict[str, Any], bid_key: str, ask_key: str) -> float | None:
    bid = _number(candidate.get(bid_key))
    ask = _number(candidate.get(ask_key))
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def find_atm_reference(
    surface_points: list[dict[str, Any]] | None,
    *,
    underlying_price: float | None,
) -> dict[str, Any] | None:
    """Return the same-expiry surface point closest to spot."""
    if not surface_points or not isinstance(underlying_price, (int, float)):
        return None
    best: dict[str, Any] | None = None
    best_distance = math.inf
    for point in surface_points:
        strike = _number((point or {}).get("strike_price"))
        if strike is None:
            continue
        distance = abs(strike - float(underlying_price))
        if distance < best_distance:
            best_distance, best = distance, point
    return best
