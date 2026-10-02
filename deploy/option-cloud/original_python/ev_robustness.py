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

from .ev_scanner import (
    build_absolute_ev,
    executable_quotes_usd,
)
from .ev_scanner import (
    execution_sensitivity as _execution_sensitivity,
)

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

    quotes = executable_quotes_usd(candidate)
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

    execution = _execution_variants(reference=reference, quotes=quotes)
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


def _execution_variants(
    *, reference: dict[str, Any], quotes: dict[str, float]
) -> dict[str, Any]:
    """Delegates to the scanner's implementation so the two cannot drift."""
    return {
        **_execution_sensitivity(
            quotes=quotes,
            expected_payout_usdc=float(reference["expected_payout_usdc"]),
            fees_usdc=float(reference["modelled_fees_usdc"]["total_usdc"]),
        ),
        "modelled_fees_usdc": float(reference["modelled_fees_usdc"]["total_usdc"]),
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
