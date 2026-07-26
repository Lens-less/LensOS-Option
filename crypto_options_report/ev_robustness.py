"""How much of an expected-value conclusion is the data, and how much is assumption.

On the first run against live Deribit data every candidate that obtained a
validated expected value came out negative. That is a finding, but on its own it
is not an actionable one, because at least three different situations produce
the same number and they call for opposite responses:

* the sample period happens to contain the move the seller was short;
* the edge is real but sits inside the bid/ask, so neither side can capture it;
* selling this shape is genuinely unprofitable, which makes the other side the
  interesting one.

This module separates them, and it does so without re-deriving anything. The
expected payout depends only on the underlying's distribution, never on the
price the position was opened at, so every execution variant is arithmetic on
one path replay. Only the period slices need their own replay.

The output is descriptive. It reports where the conclusion is stable and where
it is not; it does not convert that into a recommendation, and the buy-side
figures are as research-only as the sell-side ones.
"""

from __future__ import annotations

from typing import Any

from .edge_score import normalize_premium_to_usd
from .ev_scanner import build_absolute_ev

EV_ROBUSTNESS_SCHEMA_VERSION = "ev_robustness_report.v1"

# Enough independent windows must survive inside each slice for its own
# distribution claim to stand; below that the slice is reported as blocked
# rather than quietly resting on a handful of windows.
DEFAULT_PERIOD_SLICES = 3

MISSING_BASE_EV = "MISSING_BASE_EXPECTED_VALUE"
MISSING_QUOTES = "MISSING_EXECUTABLE_QUOTES"
INSUFFICIENT_HISTORY_FOR_SLICES = "INSUFFICIENT_HISTORY_FOR_PERIOD_SLICES"

# Verdicts. They name what the numbers show, not what to do about it.
STABLE_NEGATIVE = "negative_across_periods_and_execution"
STABLE_POSITIVE = "positive_across_periods_and_execution"
PERIOD_DEPENDENT = "sign_flips_across_periods"
NO_CAPTURABLE_EDGE = "no_capturable_edge_at_the_touch"
DIRECTION_DEPENDENT = "other_direction_is_positive"
UNDETERMINED = "undetermined"


def build_ev_robustness_report(
    *,
    candidate: dict[str, Any],
    structure_type: str,
    underlying_history: dict[str, Any],
    generated_at: str | None = None,
    permission_state: dict[str, Any] | None = None,
    period_slices: int = DEFAULT_PERIOD_SLICES,
) -> dict[str, Any]:
    """Test one candidate's expected value against period and execution choices."""
    base = {
        "schema_version": EV_ROBUSTNESS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "candidate_id": candidate.get("candidate_id"),
        "structure_type": structure_type,
        "period_slices_requested": period_slices,
    }

    quotes = _executable_quotes(candidate)
    if quotes is None:
        return {**base, "status": "unavailable", "reason_code": MISSING_QUOTES}

    reference = build_absolute_ev(
        candidate=candidate,
        structure_type=structure_type,
        underlying_history=underlying_history,
        entry_credit_usdc=quotes["sell_at_bid"],
        permission_state=permission_state,
        generated_at=generated_at,
    )
    if reference.get("status") != "validated":
        return {
            **base,
            "status": "unavailable",
            "reason_code": reference.get("reason_code") or MISSING_BASE_EV,
        }

    execution = _execution_sensitivity(reference=reference, quotes=quotes)
    periods = _period_sensitivity(
        candidate=candidate,
        structure_type=structure_type,
        underlying_history=underlying_history,
        quotes=quotes,
        permission_state=permission_state,
        generated_at=generated_at,
        period_slices=period_slices,
    )

    return {
        **base,
        "status": "evaluated",
        "reason_code": None,
        "reference": {
            "ev_after_cost_usdc": reference["ev_after_cost_usdc"],
            "expected_payout_usdc": reference["expected_payout_usdc"],
            "entry_credit_usdc": reference["entry_credit_usdc"],
            "authoritative_sample_size": reference.get("authoritative_sample_size"),
            "sample_size_basis": reference.get("sample_size_basis"),
        },
        "execution_sensitivity": execution,
        "period_sensitivity": periods,
        "verdict": _verdict(execution, periods),
        "cannot_tell": [
            "The expected payout is one estimate from one history. Splitting "
            "that history into slices shows dispersion, not a confidence "
            "interval.",
            "Mid-price figures assume a fill that the quoted book does not "
            "promise. They bound what execution could contribute; they are not "
            "an achievable price.",
            "Buy-side figures are reported to locate the edge, not to propose "
            "the trade. Nothing here is sized or executable.",
        ],
    }


def _executable_quotes(candidate: dict[str, Any]) -> dict[str, float] | None:
    """The credit or debit implied by each side of the quoted book, in USD.

    A structure carries a net credit built from selling at the bid and buying at
    the ask; a single leg carries its own bid and ask. Both reduce to the same
    four numbers: what the seller receives crossing or resting, and what the
    buyer pays doing the same.
    """
    spot = candidate.get("underlying_price")
    unit = candidate.get("premium_unit")

    def usd(value: Any) -> float | None:
        return normalize_premium_to_usd(
            value, premium_unit=unit, underlying_price=spot
        )

    if candidate.get("net_credit") is not None:
        executable = usd(candidate.get("net_credit"))
        mid = usd(candidate.get("mid_credit"))
        if executable is None or mid is None:
            return None
        # The buyer of the same structure pays the mirror of what the seller
        # receives: the seller's spread cost measured from the mid, applied the
        # other way.
        spread = mid - executable
        buy_at_ask = mid + spread
    else:
        bid = usd(candidate.get("market_bid"))
        ask = usd(candidate.get("market_ask"))
        if bid is None or ask is None:
            return None
        executable, mid, buy_at_ask = bid, (bid + ask) / 2.0, ask

    if executable <= 0 or mid <= 0:
        return None
    return {
        "sell_at_bid": round(executable, 6),
        "mid": round(mid, 6),
        "buy_at_ask": round(buy_at_ask, 6),
        "spread_cost_usdc": round(mid - executable, 6),
    }


def _execution_sensitivity(
    *, reference: dict[str, Any], quotes: dict[str, float]
) -> dict[str, Any]:
    """Expected value at each side of the book, both directions.

    No path is replayed here. The expected payout is a property of the
    underlying's distribution and does not change with the price paid, so every
    variant below is the same payout against a different entry.
    """
    payout = float(reference["expected_payout_usdc"])
    fees = float(reference["modelled_fees_usdc"]["total_usdc"])

    variants = {
        "sell_at_bid": round(quotes["sell_at_bid"] - payout - fees, 6),
        "sell_at_mid": round(quotes["mid"] - payout - fees, 6),
        "buy_at_mid": round(payout - quotes["mid"] - fees, 6),
        "buy_at_ask": round(payout - quotes["buy_at_ask"] - fees, 6),
    }
    both_sides_negative = variants["sell_at_bid"] < 0 and variants["buy_at_ask"] < 0
    mid_would_flip = variants["sell_at_bid"] < 0 <= variants["sell_at_mid"]

    return {
        "ev_after_cost_usdc": variants,
        "spread_cost_usdc": quotes["spread_cost_usdc"],
        "modelled_fees_usdc": fees,
        # When crossing the spread loses on both sides, whatever edge the model
        # sees is smaller than the cost of reaching it.
        "both_directions_negative_at_the_touch": both_sides_negative,
        "mid_execution_would_flip_the_sign": mid_would_flip,
        "basis": "expected_payout_is_invariant_to_entry_price",
        # The fee model is the seller's: an entry fee plus an assignment-weighted
        # delivery fee. Reusing it on the buy side is an approximation, and it
        # is named rather than absorbed because it moves the buy-side figures.
        "buy_side_fee_basis": "seller_fee_model_reused",
    }


def _period_sensitivity(
    *,
    candidate: dict[str, Any],
    structure_type: str,
    underlying_history: dict[str, Any],
    quotes: dict[str, float],
    permission_state: dict[str, Any] | None,
    generated_at: str | None,
    period_slices: int,
) -> dict[str, Any]:
    """Expected value recomputed over consecutive slices of the history.

    Contiguous slices rather than random resampling: the question is whether the
    conclusion belongs to a regime, and a shuffled sample destroys exactly the
    ordering that would reveal it.
    """
    observations = (underlying_history or {}).get("observations")
    if not isinstance(observations, list) or period_slices < 2:
        return {
            "status": "unavailable",
            "reason_code": INSUFFICIENT_HISTORY_FOR_SLICES,
            "slices": [],
        }

    total = len(observations)
    rows: list[dict[str, Any]] = []
    for index in range(period_slices):
        start = (index * total) // period_slices
        end = ((index + 1) * total) // period_slices
        window = observations[start:end]
        row: dict[str, Any] = {
            "slice": index + 1,
            "observation_count": len(window),
            "first_observed_at": window[0].get("observed_at") if window else None,
            "last_observed_at": window[-1].get("observed_at") if window else None,
        }
        if len(window) < 2:
            rows.append({**row, "status": "blocked", "reason_code": "SLICE_TOO_SHORT"})
            continue

        sliced_history = {
            **underlying_history,
            "observations": window,
            "observation_count": len(window),
            "first_observed_at": window[0].get("observed_at"),
            "last_observed_at": window[-1].get("observed_at"),
        }
        result = build_absolute_ev(
            candidate=candidate,
            structure_type=structure_type,
            underlying_history=sliced_history,
            entry_credit_usdc=quotes["sell_at_bid"],
            permission_state=permission_state,
            generated_at=generated_at,
        )
        if result.get("status") != "validated":
            rows.append(
                {
                    **row,
                    "status": "blocked",
                    "reason_code": result.get("reason_code"),
                }
            )
            continue
        rows.append(
            {
                **row,
                "status": "evaluated",
                "reason_code": None,
                "ev_after_cost_usdc": result["ev_after_cost_usdc"],
                "expected_payout_usdc": result["expected_payout_usdc"],
                "p_itm": result.get("p_itm"),
                "cvar_95_usdc": result.get("cvar_95_usdc"),
                "authoritative_sample_size": result.get("authoritative_sample_size"),
            }
        )

    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    values = [float(row["ev_after_cost_usdc"]) for row in evaluated]
    if len(values) < 2:
        return {
            "status": "insufficient_slices",
            "reason_code": INSUFFICIENT_HISTORY_FOR_SLICES,
            "evaluated_slice_count": len(evaluated),
            "slices": rows,
        }

    signs = {value >= 0 for value in values}
    return {
        "status": "evaluated",
        "reason_code": None,
        "evaluated_slice_count": len(evaluated),
        "min_ev_after_cost_usdc": round(min(values), 6),
        "max_ev_after_cost_usdc": round(max(values), 6),
        "range_usdc": round(max(values) - min(values), 6),
        "sign_stable": len(signs) == 1,
        "slices": rows,
        "basis": "contiguous_history_slices",
    }


def _verdict(execution: dict[str, Any], periods: dict[str, Any]) -> dict[str, Any]:
    """Name which of the situations the numbers describe.

    Ordered so the cheapest explanation is ruled out first: an unstable sign
    across periods means the level is not established at all, and no statement
    about direction or execution survives it.
    """
    variants = execution["ev_after_cost_usdc"]
    if periods.get("status") == "evaluated" and not periods["sign_stable"]:
        return {
            "code": PERIOD_DEPENDENT,
            "detail": (
                "Expected value changes sign between history slices, so its "
                "level is a property of the period sampled rather than of the "
                "structure."
            ),
        }
    if execution["both_directions_negative_at_the_touch"]:
        # Both sides losing means the modelled fair value sits between the bid
        # and the ask, which is what a competently quoted market looks like. It
        # is a statement about capture, not about the presence of an edge, and
        # naming it otherwise would turn an ordinary spread into a discovery.
        return {
            "code": NO_CAPTURABLE_EDGE,
            "detail": (
                "Selling at the bid and buying at the ask both lose, so the "
                "modelled fair value lies inside the quoted spread. Whether "
                "resting rather than crossing would change that is reported "
                "separately as mid_execution_would_flip_the_sign."
            ),
        }
    if variants["sell_at_bid"] >= 0:
        return {
            "code": STABLE_POSITIVE,
            "detail": "Positive selling at the quoted bid, stable across slices.",
        }
    if variants["buy_at_ask"] >= 0:
        return {
            "code": DIRECTION_DEPENDENT,
            "detail": (
                "Selling loses but buying at the ask does not, so the structure "
                "is mispriced in the opposite direction to the one screened."
            ),
        }
    if periods.get("status") != "evaluated":
        return {
            "code": UNDETERMINED,
            "detail": "Too few usable history slices to say whether the sign holds.",
        }
    return {
        "code": STABLE_NEGATIVE,
        "detail": (
            "Negative selling at the bid, negative buying at the ask is not the "
            "cause, and the sign holds across history slices."
        ),
    }
