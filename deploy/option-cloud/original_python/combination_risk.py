"""What a set of candidates does when held together, rather than one at a time.

Every risk number the product produced was per candidate. That is the wrong unit
for the question the product exists to answer — "what should I put on" — because
the risks of two candidates are not independent draws. Two short call spreads on
the same expiry a strike apart are very nearly the same trade twice, and a book
that reads as two moderate positions is one concentrated one.

This module aggregates, and it is careful about the two places aggregation
quietly lies:

* **Maximum loss does not add across expiries.** Summing the worst case of an
  August position and a September one assumes both worst cases happen, which is
  an upper bound rather than a distribution fact. A single joint payoff is
  computed only when every leg shares one expiry; otherwise the sum is published
  as an explicitly labelled bound and the joint figure is refused.
* **Vega does not add across expiries either.** A month of vega and a quarter of
  vega respond to different parts of the term structure, so a single net number
  assumes a parallel shift. The total is still reported, because it is what a
  parallel shift would cost, but it is reported next to the per-expiry
  breakdown that shows what the total is hiding.

Nothing here sizes anything. The output describes the risk of a hypothetical
combination at one contract per structure; it contains no quantity a position
could be opened with.
"""

from __future__ import annotations

from typing import Any

from .edge_score import normalize_premium_to_usd
from .structures import build_structure

COMBINATION_RISK_SCHEMA_VERSION = "combination_risk_report.v1"

# Above this share of the book's absolute vega sitting in one expiry, the book
# is a single term-structure bet regardless of how many rows it has.
EXPIRY_CONCENTRATION_THRESHOLD = 0.7

MISSING_LEGS = "CANDIDATE_HAS_NO_STRUCTURE_LEGS"
MULTI_EXPIRY_BOOK = "BOOK_SPANS_MULTIPLE_EXPIRIES"
UNBOUNDED_MEMBER = "BOOK_CONTAINS_UNBOUNDED_MEMBER"
NO_EVALUABLE_CANDIDATES = "NO_EVALUABLE_CANDIDATES"


def build_combination_risk_report(
    *,
    candidates: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Aggregate a hypothetical book of one contract per candidate."""
    members, excluded = _members(candidates)
    base = {
        "schema_version": COMBINATION_RISK_SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "recommended_size_allowed": False,
        "trade_instruction_allowed": False,
        "basis": "one_contract_per_structure",
        "excluded_candidates": excluded,
    }
    if not members:
        return {
            **base,
            "status": "unavailable",
            "reason_code": NO_EVALUABLE_CANDIDATES,
            "member_count": 0,
            "members": [],
            "book": {},
            "marginal_contributions": [],
            "concentration": {},
        }

    book = _book_risk(members)
    return {
        **base,
        "status": "evaluated",
        "reason_code": book.get("reason_code"),
        "member_count": len(members),
        "members": [
            {
                "candidate_id": member["candidate_id"],
                "structure_type": member["structure_type"],
                "expiry_date": member["expiry_date"],
                "credit_usdc": member["credit_usdc"],
                "max_loss_usdc": member["max_loss"],
                "loss_is_bounded": member["loss_is_bounded"],
            }
            for member in members
        ],
        "book": book,
        "marginal_contributions": _marginal_contributions(members, book),
        "concentration": _concentration(members),
        "cannot_tell": [
            "Aggregated greeks assume a parallel volatility move across "
            "expiries; the per-expiry breakdown shows what that assumption is "
            "smoothing over.",
            "This is a terminal-payoff view. It says nothing about the margin "
            "an exchange would require before expiry, or about the path taken "
            "to get there.",
        ],
    }


def _members(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    members: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        legs = candidate.get("structure_legs")
        if not isinstance(legs, list) or not legs:
            excluded.append({"candidate_id": candidate_id, "reason_code": MISSING_LEGS})
            continue
        spot = candidate.get("underlying_price")
        credit = normalize_premium_to_usd(
            candidate.get("net_credit")
            if candidate.get("net_credit") is not None
            else candidate.get("market_bid"),
            premium_unit=candidate.get("premium_unit"),
            underlying_price=spot,
        )
        try:
            structure = build_structure(
                structure_type=str(candidate.get("structure_type") or "candidate"),
                legs=legs,
            )
        except ValueError as exc:
            excluded.append(
                {
                    "candidate_id": candidate_id,
                    "reason_code": "INVALID_STRUCTURE_LEGS",
                    "detail": str(exc),
                }
            )
            continue
        if structure.is_multi_expiry:
            excluded.append(
                {"candidate_id": candidate_id, "reason_code": "MULTI_EXPIRY_STRUCTURE"}
            )
            continue
        if credit is None:
            excluded.append(
                {"candidate_id": candidate_id, "reason_code": "PREMIUM_UNIT_UNKNOWN"}
            )
            continue

        profile = structure.risk_profile(entry_cash=credit)
        members.append(
            {
                "candidate_id": candidate_id,
                "structure_type": structure.structure_type,
                "expiry_date": structure.expiry_date
                or str(candidate.get("expiry_date") or ""),
                "structure": structure,
                "legs": legs,
                "credit_usdc": round(credit, 6),
                "max_loss": profile.max_loss,
                "loss_is_bounded": profile.loss_is_bounded,
                "position_greeks": candidate.get("position_greeks"),
                "underlying_price": spot,
            }
        )
    return members, excluded


def _book_risk(members: list[dict[str, Any]]) -> dict[str, Any]:
    expiries = sorted({member["expiry_date"] for member in members})
    total_credit = round(sum(member["credit_usdc"] for member in members), 6)
    unbounded = [
        member["candidate_id"] for member in members if not member["loss_is_bounded"]
    ]

    joint: dict[str, Any]
    reason_code: str | None = None
    if len(expiries) == 1:
        combined = build_structure(
            structure_type="combined_book",
            legs=[leg for member in members for leg in member["legs"]],
        )
        profile = combined.risk_profile(entry_cash=total_credit)
        joint = {
            "status": "evaluated",
            "max_loss_usdc": profile.max_loss,
            "max_profit_usdc": profile.max_profit,
            "loss_is_bounded": profile.loss_is_bounded,
            "breakevens": list(profile.breakevens),
            "basis": "single_expiry_joint_terminal_payoff",
        }
    else:
        reason_code = MULTI_EXPIRY_BOOK
        joint = {
            "status": "not_jointly_evaluable",
            "reason_code": MULTI_EXPIRY_BOOK,
            "max_loss_usdc": None,
            "basis": "legs_do_not_share_one_expiry",
            "note": (
                "A single terminal payoff needs one expiry. The bound below "
                "adds each member's own worst case, which assumes every worst "
                "case occurs together."
            ),
        }

    bound = (
        None
        if unbounded
        else round(sum(member["max_loss"] or 0.0 for member in members), 6)
    )
    if unbounded and reason_code is None:
        reason_code = UNBOUNDED_MEMBER

    return {
        "reason_code": reason_code,
        "total_credit_usdc": total_credit,
        "expiries": expiries,
        "joint_terminal_risk": joint,
        "max_loss_upper_bound_usdc": bound,
        "max_loss_upper_bound_basis": "sum_of_independent_member_worst_cases",
        "unbounded_members": unbounded,
        "loss_is_bounded": not unbounded,
        "greeks": _aggregate_greeks(members),
    }


def _aggregate_greeks(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Net greeks, and the per-expiry breakdown the net figure conceals."""
    names = ("delta", "gamma", "theta", "vega")
    totals = dict.fromkeys(names, 0.0)
    by_expiry: dict[str, dict[str, float]] = {}
    missing: list[str] = []

    for member in members:
        greeks = member.get("position_greeks")
        if not isinstance(greeks, dict) or greeks.get("status") != "aggregated":
            missing.append(member["candidate_id"])
            continue
        bucket = by_expiry.setdefault(member["expiry_date"], dict.fromkeys(names, 0.0))
        for name in names:
            value = greeks.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                missing.append(f"{member['candidate_id']}.{name}")
                continue
            totals[name] += float(value)
            bucket[name] += float(value)

    if missing:
        return {
            "status": "blocked",
            "reason_code": "MISSING_MEMBER_GREEKS",
            "missing": sorted(set(missing)),
            "net": None,
            "by_expiry": {},
        }
    return {
        "status": "aggregated",
        "reason_code": None,
        "missing": [],
        "net": {name: round(value, 8) for name, value in totals.items()},
        "net_assumes": "parallel_volatility_move_across_expiries",
        "by_expiry": {
            expiry: {name: round(value, 8) for name, value in bucket.items()}
            for expiry, bucket in sorted(by_expiry.items())
        },
    }


def _marginal_contributions(
    members: list[dict[str, Any]], book: dict[str, Any]
) -> list[dict[str, Any]]:
    """What each member adds to the book, measured by removing it.

    Marginal rather than standalone: a candidate whose own maximum loss is large
    but which offsets an existing position contributes less than its own number
    suggests, and one that doubles an existing exposure contributes more.
    """
    joint = book["joint_terminal_risk"]
    if joint.get("status") != "evaluated" or joint.get("max_loss_usdc") is None:
        return [
            {
                "candidate_id": member["candidate_id"],
                "status": "unavailable",
                "reason_code": book.get("reason_code") or MULTI_EXPIRY_BOOK,
                "standalone_max_loss_usdc": member["max_loss"],
                "marginal_max_loss_usdc": None,
            }
            for member in members
        ]

    full_loss = float(joint["max_loss_usdc"])
    rows: list[dict[str, Any]] = []
    for member in members:
        others = [item for item in members if item is not member]
        if not others:
            without = -round(sum(m["credit_usdc"] for m in members), 6)
        else:
            reduced = build_structure(
                structure_type="combined_book",
                legs=[leg for item in others for leg in item["legs"]],
            )
            credit = round(sum(item["credit_usdc"] for item in others), 6)
            profile = reduced.risk_profile(entry_cash=credit)
            if profile.max_loss is None:
                rows.append(
                    {
                        "candidate_id": member["candidate_id"],
                        "status": "unavailable",
                        "reason_code": UNBOUNDED_MEMBER,
                        "standalone_max_loss_usdc": member["max_loss"],
                        "marginal_max_loss_usdc": None,
                    }
                )
                continue
            without = profile.max_loss
        rows.append(
            {
                "candidate_id": member["candidate_id"],
                "status": "evaluated",
                "reason_code": None,
                "standalone_max_loss_usdc": member["max_loss"],
                "book_max_loss_without_usdc": round(without, 6),
                "marginal_max_loss_usdc": round(full_loss - without, 6),
            }
        )
    return rows


def _concentration(members: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of the book is the same bet more than once."""
    strike_counts: dict[float, int] = {}
    for member in members:
        for leg in member["legs"]:
            strike = leg.get("strike")
            if isinstance(strike, (int, float)) and not isinstance(strike, bool):
                strike_counts[float(strike)] = strike_counts.get(float(strike), 0) + 1

    vega_by_expiry: dict[str, float] = {}
    for member in members:
        greeks = member.get("position_greeks")
        if isinstance(greeks, dict) and isinstance(greeks.get("vega"), (int, float)):
            vega_by_expiry[member["expiry_date"]] = vega_by_expiry.get(
                member["expiry_date"], 0.0
            ) + abs(float(greeks["vega"]))

    total_vega = sum(vega_by_expiry.values())
    largest = max(vega_by_expiry.values(), default=0.0)
    share = (largest / total_vega) if total_vega > 0 else None

    return {
        "shared_strikes": sorted(
            [
                {"strike": strike, "leg_count": count}
                for strike, count in strike_counts.items()
                if count > 1
            ],
            key=lambda row: row["strike"],
        ),
        "expiry_count": len({member["expiry_date"] for member in members}),
        "absolute_vega_by_expiry": {
            expiry: round(value, 8) for expiry, value in sorted(vega_by_expiry.items())
        },
        "largest_expiry_vega_share": (
            round(share, 6) if share is not None else None
        ),
        "concentration_threshold": EXPIRY_CONCENTRATION_THRESHOLD,
        "single_expiry_concentrated": (
            share is not None and share >= EXPIRY_CONCENTRATION_THRESHOLD
        ),
    }
