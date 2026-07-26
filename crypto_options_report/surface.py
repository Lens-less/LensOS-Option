"""Research-only vol-surface fitting and candidate discovery helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import log, sqrt
from statistics import NormalDist
from typing import Any

from .market_data import normalize_market_snapshot, parse_timestamp_ms
from .structures import build_structure

DEFAULT_SURFACE_LIMITS = {
    "min_quotes_per_expiry": 4,
    "fit_quality_threshold": 0.9,
    "max_no_arb_error": 0.03,
    "min_dte_days": 7.0,
    "max_dte_days": 35.0,
    "min_delta": 0.03,
    "max_delta": 0.15,
    # Legacy/non-inverse fixtures quote premium in quote-currency units.
    "min_bid": 0.05,
    # Deribit inverse BTC options quote and settle premium in BTC.  A 0.05 BTC
    # floor was two orders of magnitude above the liquid 3-15 delta market.
    "min_bid_btc": 0.0005,
    "min_open_interest": 10.0,
    "max_spread_ratio": 0.25,
    "max_quote_age_sec": 120.0,
    # Spread width as a fraction of the underlying, resolved per candidate.
    #
    # These were absolute dollars, which made the search a different search at
    # every price level: 5000-15000 is 7.8%-23.3% of spot at 64k and 4.2%-12.5%
    # at 120k, and BTC covered both inside the sample this product measures
    # against. The resolved dollar bounds are published per candidate so the
    # artifact still shows exactly what was applied.
    "min_spread_width_fraction": 0.05,
    "max_spread_width_fraction": 0.25,
    # A protective leg is insurance bought once, not the source of the credit,
    # so it is gated on what crossing it actually costs rather than on the ratio
    # that cost bears to its own tiny premium. A deep out-of-the-money wing
    # quoted 0.0003/0.0004 shows a 28% spread ratio and costs about three
    # dollars to cross; rejecting it on that ratio threw away the structures
    # that bound risk — and, because a condor needs a defined-risk wing on both
    # sides, every condor with it.
    "max_protective_leg_cost_ratio": 0.25,
    # Data sanity for any leg, well above the executable gate: a quote this wide
    # is a broken print rather than an expensive one.
    "max_quote_spread_ratio_hard": 0.75,
    "min_net_credit": 0.01,
    "min_net_credit_btc": 0.0001,
    "delta_diff_review_threshold": 0.03,
    "delta_diff_reject_threshold": 0.08,
}

_NORMAL = NormalDist()
_CANONICAL_SURFACE_IV_UNIT = "percent_points"


def build_vol_surface_and_candidate_research(
    *,
    market_snapshot: dict[str, Any] | None,
    generated_at: str,
    data_status: dict[str, Any],
    pnl_evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if market_snapshot is None:
        return _missing_surface_status(), _missing_candidate_research()

    evaluation_now_ms = parse_timestamp_ms(generated_at)
    normalized = normalize_market_snapshot(
        market_snapshot,
        now_ms=evaluation_now_ms,
    )

    expiry_groups: dict[str, list[dict[str, Any]]] = {}
    try:
        iv_unit_hints = _surface_iv_unit_hints(market_snapshot)
        for quote in normalized["quotes"]:
            canonical_quote = _canonicalize_surface_quote_iv(
                quote,
                unit_hint=iv_unit_hints.get(
                    str(quote.get("instrument_name") or "")
                ),
            )
            expiry_groups.setdefault(canonical_quote["expiry_date"], []).append(
                canonical_quote
            )
    except ValueError:
        return (
            _blocked_surface_status(reason_code="AMBIGUOUS_IV_UNIT"),
            _blocked_candidate_research(reason_code="AMBIGUOUS_IV_UNIT"),
        )

    expiries: list[dict[str, Any]] = []
    eligible_expiries: list[dict[str, Any]] = []
    for expiry_date in sorted(expiry_groups):
        expiry_report = _build_expiry_surface(
            expiry_date=expiry_date,
            quotes=expiry_groups[expiry_date],
            evaluation_now_ms=evaluation_now_ms,
        )
        expiries.append(expiry_report)
        if expiry_report["candidate_eligible"]:
            eligible_expiries.append(expiry_report)

    surface_reason_code = None
    surface_status = "validated"
    surface_validated = True
    if data_status.get("status") == "missing":
        surface_status = "missing"
        surface_validated = False
        surface_reason_code = "MISSING_VALIDATED_MARKET_DATA"
    elif data_status.get("status") == "blocked":
        surface_status = "blocked"
        surface_validated = False
        surface_reason_code = "MARKET_DATA_QUALITY_FAIL"

    vol_surface_status = {
        "status": surface_status,
        "validated": surface_validated,
        "reason_code": surface_reason_code,
        "fit_model": "quadratic_iv_vs_log_moneyness",
        "thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "expiries": expiries,
        "summary": {
            "expiries_evaluated": len(expiries),
            "eligible_expiries": sum(exp["candidate_eligible"] for exp in expiries),
            "quality_passing_quotes": sum(
                exp["quality_passing_quotes"] for exp in expiries
            ),
        },
    }

    if data_status.get("status") != "validated":
        return vol_surface_status, _blocked_candidate_research(
            reason_code="MARKET_DATA_NOT_VALIDATED",
        )
    if pnl_evidence.get("status") != "pass":
        return vol_surface_status, _blocked_candidate_research(
            reason_code="PNL_EVIDENCE_FAIL",
        )

    tables = {name: _empty_tables() for name in CANDIDATE_TABLE_NAMES}
    rejected_expiries = []
    condors_truncated = 0

    for expiry_report in expiries:
        call_eligible = expiry_report["candidate_eligible"]
        put_eligible = expiry_report["put_candidate_eligible"]
        if not call_eligible and not put_eligible:
            rejected_expiries.append(expiry_report["expiry_date"])
            continue

        call_points = expiry_report["surface_points"]
        put_points = expiry_report["put_surface_points"]
        call_spreads: list[dict[str, Any]] = []
        put_spreads: list[dict[str, Any]] = []

        if call_eligible:
            for point in call_points:
                candidate = _build_naked_candidate(point, expiry_report)
                _file(tables["naked_short_calls"], candidate)
            call_spreads = _build_spread_candidates(
                call_points, expiry_report, option_type="call"
            )
        if put_eligible:
            put_spreads = _build_spread_candidates(
                put_points, expiry_report, option_type="put"
            )
        if call_eligible and put_eligible:
            condors, truncated = _build_iron_condor_candidates(
                put_spreads=put_spreads,
                call_spreads=call_spreads,
                expiry_report=expiry_report,
            )
            condors_truncated += truncated
            for condor in condors:
                _file(tables["iron_condors"], condor)

        for spread in call_spreads:
            _file(tables["call_credit_spreads"], spread)
        for spread in put_spreads:
            _file(tables["put_credit_spreads"], spread)

    candidate_status = "validated"
    reason_code = None
    total_candidates = sum(
        len(rows) for table in tables.values() for rows in table.values()
    )
    if total_candidates == 0:
        candidate_status = "blocked"
        reason_code = (
            "SURFACE_QUALITY_FAIL"
            if not eligible_expiries
            else "NO_ELIGIBLE_CANDIDATES"
        )

    summary: dict[str, Any] = {
        "expiries_considered": len(expiries),
        "eligible_expiries": len(eligible_expiries),
        "rejected_expiries": rejected_expiries,
        "iron_condors_truncated": condors_truncated,
        "iron_condor_limit": MAX_IRON_CONDOR_CANDIDATES,
    }
    for name, table in tables.items():
        for tier, key in (("eligible", "eligible"), ("review", "review"), ("rejected", "rejected")):
            summary[f"{key}_{name}"] = len(table[tier])

    candidate_research = {
        "status": candidate_status,
        "reason_code": reason_code,
        "filter_thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "structure_types": list(CANDIDATE_TABLE_NAMES),
        **tables,
        "summary": summary,
    }
    return vol_surface_status, candidate_research


# Published in the artifact so a consumer can enumerate the candidate universe
# instead of hard-coding the table names it happens to know about.
CANDIDATE_TABLE_NAMES = (
    "naked_short_calls",
    "call_credit_spreads",
    "put_credit_spreads",
    "iron_condors",
)


def _empty_tables() -> dict[str, list[dict[str, Any]]]:
    return {"eligible": [], "review": [], "rejected": []}


def _file(table: dict[str, list[dict[str, Any]]], candidate: dict[str, Any]) -> None:
    """Place a candidate in its decision bucket, minus the private leg cache."""
    published = {key: value for key, value in candidate.items() if not key.startswith("_")}
    table[_decision_bucket(candidate["decision"])].append(published)


def _missing_surface_status() -> dict[str, Any]:
    return {
        "status": "missing",
        "validated": False,
        "reason_code": "MISSING_VALIDATED_MARKET_DATA",
        "fit_model": "quadratic_iv_vs_log_moneyness",
        "thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "expiries": [],
        "summary": {
            "expiries_evaluated": 0,
            "eligible_expiries": 0,
            "quality_passing_quotes": 0,
        },
    }


def _blocked_surface_status(*, reason_code: str) -> dict[str, Any]:
    status = _missing_surface_status()
    status.update(
        status="blocked",
        reason_code=reason_code,
    )
    return status


def _surface_iv_unit_hints(
    market_snapshot: dict[str, Any],
) -> dict[str, str]:
    hints: dict[str, str] = {}
    for row in market_snapshot.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker") or {}
        summary = row.get("summary") or {}
        instrument_name = str(
            row.get("instrument_name")
            or ticker.get("instrument_name")
            or summary.get("instrument_name")
            or ""
        )
        declared_units = {
            _normalize_surface_iv_unit(unit)
            for unit in (
                row.get("iv_unit"),
                ticker.get("iv_unit"),
                summary.get("iv_unit"),
            )
            if unit not in (None, "")
        }
        if instrument_name and len(declared_units) == 1:
            hints[instrument_name] = declared_units.pop()
        elif instrument_name and declared_units:
            hints[instrument_name] = "conflicting"
    return hints


def _canonicalize_surface_quote_iv(
    quote: dict[str, Any],
    *,
    unit_hint: str | None,
) -> dict[str, Any]:
    canonical = dict(quote)
    input_unit, provenance_source = _resolve_surface_iv_unit(
        quote,
        unit_hint=unit_hint,
    )
    multiplier = 100.0 if input_unit == "fraction" else 1.0
    for field_name in ("bid_iv", "ask_iv", "mark_iv"):
        value = quote.get(field_name)
        if value is not None:
            canonical[field_name] = float(value) * multiplier
    canonical["iv_unit"] = _CANONICAL_SURFACE_IV_UNIT
    canonical["iv_unit_provenance"] = {
        "input_unit": input_unit,
        "canonical_unit": _CANONICAL_SURFACE_IV_UNIT,
        "source": provenance_source,
    }
    return canonical


def _resolve_surface_iv_unit(
    quote: dict[str, Any],
    *,
    unit_hint: str | None,
) -> tuple[str, str]:
    declared = quote.get("iv_unit") or unit_hint
    if declared not in (None, ""):
        return _normalize_surface_iv_unit(declared), "declared"
    raise ValueError("surface IV unit is required")


def _normalize_surface_iv_unit(declared: Any) -> str:
    normalized = str(declared).strip().lower().replace("-", "_")
    if normalized in {"fraction", "decimal", "ratio"}:
        return "fraction"
    if normalized in {
        "percent",
        "percentage_points",
        "percent_points",
        "pct",
        "pct_points",
    }:
        return "percent_points"
    raise ValueError(f"unsupported surface IV unit: {declared!r}")


def _missing_candidate_research() -> dict[str, Any]:
    return _blocked_candidate_research(reason_code="MISSING_VALIDATED_MARKET_DATA")


def _blocked_candidate_research(*, reason_code: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "expiries_considered": 0,
        "eligible_expiries": 0,
        "rejected_expiries": [],
        "iron_condors_truncated": 0,
        "iron_condor_limit": MAX_IRON_CONDOR_CANDIDATES,
    }
    for name in CANDIDATE_TABLE_NAMES:
        for tier in ("eligible", "review", "rejected"):
            summary[f"{tier}_{name}"] = 0
    return {
        "status": "blocked",
        "reason_code": reason_code,
        "filter_thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "structure_types": list(CANDIDATE_TABLE_NAMES),
        **{name: _empty_tables() for name in CANDIDATE_TABLE_NAMES},
        "summary": summary,
    }


def _build_expiry_surface(
    *,
    expiry_date: str,
    quotes: list[dict[str, Any]],
    evaluation_now_ms: int,
) -> dict[str, Any]:
    """Fit one smile per option type within the expiry.

    Calls and puts are fitted separately rather than merged. Put-call parity
    says their implied volatilities should agree, but that is a property to
    observe, not one to assume: pooling them would hide a parity violation
    inside the residuals of a single fit, and a parity violation is exactly the
    kind of thing a research console should surface rather than smooth away.

    The call side keeps the top-level field names it always had, so every
    existing consumer reads the same surface it read before.
    """
    dte_days = _dte_days(expiry_date, evaluation_now_ms)
    ordered = sorted(quotes, key=lambda item: item["strike"])
    sides = {
        option_type: _build_side_surface(
            expiry_date=expiry_date,
            dte_days=dte_days,
            valid_quotes=[
                quote
                for quote in ordered
                if quote["quality_status"] == "valid"
                and quote.get("option_type") == option_type
            ],
            option_type=option_type,
        )
        for option_type in ("call", "put")
    }
    call_side = sides["call"]
    put_side = sides["put"]

    return {
        "expiry_date": expiry_date,
        "dte_days": dte_days,
        # Legacy top-level fields mirror the call side.
        "quality_passing_quotes": call_side["quality_passing_quotes"],
        "fit_quality_score": call_side["fit_quality_score"],
        "fit_quality_pass": call_side["fit_quality_pass"],
        "fit_residual_rmse": call_side["fit_residual_rmse"],
        "fit_residual_scale": call_side["fit_residual_scale"],
        "fit_degrees_of_freedom": call_side["fit_degrees_of_freedom"],
        "no_arb_pass": call_side["no_arb_pass"],
        "no_arb_error": call_side["no_arb_error"],
        "candidate_eligible": call_side["candidate_eligible"],
        "reason_codes": call_side["reason_codes"],
        "surface_points": call_side["surface_points"],
        # Put side, reported alongside rather than folded in.
        "put_candidate_eligible": put_side["candidate_eligible"],
        "put_surface_points": put_side["surface_points"],
        "sides": {
            option_type: {
                key: value
                for key, value in side.items()
                if key != "surface_points"
            }
            for option_type, side in sorted(sides.items())
        },
    }


def _build_side_surface(
    *,
    expiry_date: str,
    dte_days: float,
    valid_quotes: list[dict[str, Any]],
    option_type: str,
) -> dict[str, Any]:
    if len(valid_quotes) < DEFAULT_SURFACE_LIMITS["min_quotes_per_expiry"]:
        return {
            "option_type": option_type,
            "quality_passing_quotes": len(valid_quotes),
            "fit_quality_score": 0.0,
            "fit_quality_pass": False,
            "fit_residual_rmse": None,
            "fit_residual_scale": None,
            "fit_degrees_of_freedom": len(valid_quotes) - 3,
            "no_arb_pass": False,
            "no_arb_error": 1.0,
            "candidate_eligible": False,
            "reason_codes": ["INSUFFICIENT_SURFACE_QUOTES"],
            "surface_points": [],
        }

    fit = _fit_quadratic_iv_surface(valid_quotes)
    no_arb = _evaluate_no_arb(
        valid_quotes,
        max_error=DEFAULT_SURFACE_LIMITS["max_no_arb_error"],
        option_type=option_type,
    )
    fit_pass = fit["fit_quality_score"] >= DEFAULT_SURFACE_LIMITS["fit_quality_threshold"]
    no_arb_pass = no_arb["passed"]
    reason_codes: list[str] = []
    if not fit_pass:
        reason_codes.append("SURFACE_FIT_QUALITY_TOO_LOW")
    if not no_arb_pass:
        reason_codes.extend(no_arb.get("reason_codes") or ["SURFACE_NO_ARBITRAGE_FAIL"])

    points = [
        _build_surface_point(
            quote=quote,
            fit=fit,
            expiry_date=expiry_date,
            dte_days=dte_days,
        )
        for quote in valid_quotes
    ]

    return {
        "option_type": option_type,
        "quality_passing_quotes": len(valid_quotes),
        "fit_quality_score": fit["fit_quality_score"],
        "fit_quality_pass": fit_pass,
        "fit_residual_rmse": fit["fit_residual_rmse"],
        "fit_residual_scale": fit["fit_residual_scale"],
        "fit_degrees_of_freedom": fit["fit_degrees_of_freedom"],
        "no_arb_pass": no_arb_pass,
        "no_arb_error": no_arb["error"],
        "candidate_eligible": fit_pass and no_arb_pass,
        "reason_codes": reason_codes,
        "surface_points": points,
    }


def _fit_quadratic_iv_surface(valid_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit the smile in a centred log-moneyness basis without dependencies.

    A straight line systematically labels an ordinary option smile as bad data.
    The centred/scaled quadratic basis is stable for the narrow moneyness ranges
    in a single expiry. Two Huber reweighting passes keep one venue print from
    pulling the whole smile while the final quality score still measures every
    raw residual and therefore remains fail-closed for genuinely noisy chains.
    """

    xs = [log(quote["strike"] / quote["underlying_price"]) for quote in valid_quotes]
    ys = [float(quote["mark_iv"]) for quote in valid_quotes]
    x_center = sum(xs) / len(xs)
    x_scale = max(max(abs(value - x_center) for value in xs), 1e-9)
    zs = [(value - x_center) / x_scale for value in xs]
    weights = [1.0] * len(zs)
    coefficients = _weighted_quadratic_coefficients(zs, ys, weights)

    for _iteration in range(2):
        fitted = [_evaluate_quadratic(coefficients, value) for value in zs]
        residuals = [actual - estimate for actual, estimate in zip(ys, fitted, strict=True)]
        absolute = sorted(abs(value) for value in residuals)
        median_abs = absolute[len(absolute) // 2]
        robust_scale = max(median_abs / 0.6745, 1e-6)
        cutoff = 1.5 * robust_scale
        weights = [
            1.0 if abs(value) <= cutoff else cutoff / abs(value)
            for value in residuals
        ]
        coefficients = _weighted_quadratic_coefficients(zs, ys, weights)

    fitted = [_evaluate_quadratic(coefficients, value) for value in zs]
    residuals = [actual - estimate for actual, estimate in zip(ys, fitted, strict=True)]
    rmse = sqrt(sum(value * value for value in residuals) / len(residuals))
    iv_range = max(max(ys) - min(ys), 1.0)
    fit_quality_score = max(0.0, round(1.0 - (rmse / iv_range), 6))
    # A quadratic has 3 free parameters, so the raw RMSE understates the true
    # residual scale on a thin chain. The degrees-of-freedom correction is what
    # makes a residual z-score comparable between a 4-quote and a 40-quote
    # expiry; without it a thin chain always looks like it has huge edge.
    dof = len(residuals) - 3
    residual_scale = (
        sqrt(sum(value * value for value in residuals) / dof) if dof > 0 else None
    )
    return {
        "basis": "centred_scaled_log_moneyness",
        "x_center": x_center,
        "x_scale": x_scale,
        "coefficients": coefficients,
        "fitted": fitted,
        "residuals": residuals,
        "fit_residual_rmse": round(rmse, 6),
        "fit_residual_scale": (
            round(residual_scale, 6) if residual_scale is not None else None
        ),
        "fit_degrees_of_freedom": dof,
        "fit_quality_score": fit_quality_score,
    }


def _weighted_quadratic_coefficients(
    xs: list[float],
    ys: list[float],
    weights: list[float],
) -> list[float]:
    moments = [sum(weight * (x ** power) for x, weight in zip(xs, weights, strict=True)) for power in range(5)]
    targets = [
        sum(weight * (x ** power) * y for x, y, weight in zip(xs, ys, weights, strict=True))
        for power in range(3)
    ]
    matrix = [
        [moments[0], moments[1], moments[2]],
        [moments[1], moments[2], moments[3]],
        [moments[2], moments[3], moments[4]],
    ]
    try:
        return _solve_three_by_three(matrix, targets)
    except ValueError:
        # Duplicate/degenerate strikes cannot support curvature. The constant
        # fallback is honest: its residual score will fail a non-flat chain.
        total_weight = max(sum(weights), 1e-12)
        return [sum(weight * value for weight, value in zip(weights, ys, strict=True)) / total_weight, 0.0, 0.0]


def _solve_three_by_three(matrix: list[list[float]], targets: list[float]) -> list[float]:
    augmented = [list(row) + [targets[index]] for index, row in enumerate(matrix)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            raise ValueError("quadratic fit is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[index][3] for index in range(3)]


def _evaluate_quadratic(coefficients: list[float], value: float) -> float:
    return coefficients[0] + coefficients[1] * value + coefficients[2] * value * value


def _surface_iv(fit: dict[str, Any], log_moneyness: float) -> float:
    scaled = (log_moneyness - fit["x_center"]) / fit["x_scale"]
    return _evaluate_quadratic(fit["coefficients"], scaled)


def _evaluate_no_arb(
    valid_quotes: list[dict[str, Any]],
    *,
    max_error: float,
    option_type: str = "call",
) -> dict[str, Any]:
    """Monotonicity and convexity in strike, in the direction the type requires.

    Call prices must fall as strike rises; put prices must rise. Applying the
    call direction to a put would flag every well-formed put chain as an
    arbitrage and block the whole side.
    """
    monotonic_errors = []
    convexity_errors = []
    reason_codes: list[str] = []
    puts = option_type == "put"
    for left, right in pairwise(valid_quotes):
        if right["strike"] <= left["strike"]:
            monotonic_errors.append(1.0)
            _append_unique(reason_codes, "SURFACE_DUPLICATE_STRIKE")
            continue
        violation = (
            left["mid"] - right["mid"] if puts else right["mid"] - left["mid"]
        )
        if violation > 0:
            base = max(abs(left["mid"]), 1e-6)
            monotonic_errors.append(violation / base)

    for first, second, third in zip(
        valid_quotes, valid_quotes[1:], valid_quotes[2:], strict=False
    ):
        left_width = second["strike"] - first["strike"]
        right_width = third["strike"] - second["strike"]
        if left_width <= 0 or right_width <= 0:
            convexity_errors.append(1.0)
            _append_unique(reason_codes, "SURFACE_DUPLICATE_STRIKE")
            continue
        left_slope = (second["mid"] - first["mid"]) / left_width
        right_slope = (third["mid"] - second["mid"]) / right_width
        if right_slope < left_slope:
            denom = max(abs(left_slope) + abs(right_slope), 1e-6)
            convexity_errors.append((left_slope - right_slope) / denom)
            _append_unique(reason_codes, "SURFACE_NO_ARBITRAGE_FAIL")

    error = round(max(monotonic_errors + convexity_errors + [0.0]), 6)
    if error > 0 and not reason_codes:
        reason_codes.append("SURFACE_NO_ARBITRAGE_FAIL")
    return {"passed": error <= max_error, "error": error, "reason_codes": reason_codes}


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _build_surface_point(
    *,
    quote: dict[str, Any],
    fit: dict[str, Any],
    expiry_date: str,
    dte_days: float,
) -> dict[str, Any]:
    exchange_greeks = quote.get("exchange_greeks") or {}
    log_moneyness = log(quote["strike"] / quote["underlying_price"])
    fitted_iv = round(_surface_iv(fit, log_moneyness), 6)
    canonical_metadata = quote.get("canonical_metadata") or {}
    premium_currency = str(
        quote.get("quote_currency")
        or canonical_metadata.get("settlement_currency")
        or "UNKNOWN"
    ).upper()
    base_currency = str(
        quote.get("base_currency")
        or canonical_metadata.get("base_currency")
        or "UNKNOWN"
    ).upper()
    premium_unit = (
        "inverse_base_currency"
        if premium_currency == base_currency and premium_currency != "UNKNOWN"
        else "quote_currency"
        if premium_currency != "UNKNOWN"
        else "unknown"
    )
    metrics = _black_scholes_metrics(
        underlying_price=quote["underlying_price"],
        strike=quote["strike"],
        iv_percent=fitted_iv,
        dte_days=dte_days,
        option_type=str(quote.get("option_type") or "call"),
    )
    greek_consistency = _assess_greek_consistency(
        metrics["delta"],
        exchange_greeks.get("delta"),
    )
    residual_iv = round(quote["mark_iv"] - fitted_iv, 6)
    # Raw IV points are not comparable across chains or across expiries: one
    # point of residual is noise on a scattered smile and signal on a tight one,
    # and it buys very different premium at 7 DTE than at 35 DTE. The z-score
    # divides out the first difference and the vega-dollar figure the second.
    residual_scale = fit.get("fit_residual_scale")
    residual_z = (
        round(residual_iv / residual_scale, 6)
        if isinstance(residual_scale, (int, float)) and residual_scale > 1e-9
        else None
    )
    residual_vega_usd = (
        round(residual_iv * metrics["vega"], 6)
        if isinstance(metrics.get("vega"), (int, float))
        else None
    )
    return {
        "instrument_name": quote["instrument_name"],
        "expiry_date": expiry_date,
        "option_type": quote.get("option_type"),
        "strike_price": quote["strike"],
        "underlying_price": quote["underlying_price"],
        "forward_price": quote.get("forward_price"),
        "index_price": quote.get("index_price"),
        "underlying_price_source": quote.get("underlying_price_source"),
        "forward_basis": quote.get("forward_basis"),
        "market_bid": quote["bid"],
        "market_ask": quote["ask"],
        "market_mid": quote["mid"],
        "market_bid_iv": quote["bid_iv"],
        "market_ask_iv": quote["ask_iv"],
        "market_mark_iv": quote["mark_iv"],
        "iv_unit": quote["iv_unit"],
        "iv_unit_provenance": dict(quote["iv_unit_provenance"]),
        "premium_currency": premium_currency,
        "premium_unit": premium_unit,
        "settlement_currency": canonical_metadata.get("settlement_currency"),
        "surface_fitted_iv": fitted_iv,
        "fit_residual_iv": residual_iv,
        "fit_residual_z": residual_z,
        "fit_residual_vega_usd": residual_vega_usd,
        "fit_residual_scale": residual_scale,
        "model_delta": metrics["delta"],
        "model_gamma": metrics["gamma"],
        "model_theta": metrics["theta"],
        "model_vega": metrics["vega"],
        "risk_neutral_p_itm": metrics["risk_neutral_p_itm"],
        "quote_age_sec": quote["quote_age_sec"],
        "spread_ratio": quote["spread_ratio"],
        "open_interest": quote["open_interest"],
        "best_bid_amount": quote["best_bid_amount"],
        "best_ask_amount": quote["best_ask_amount"],
        "depth": quote["depth"],
        "exchange_greeks": quote.get("exchange_greeks"),
        "greek_consistency": greek_consistency,
    }


def _black_scholes_metrics(
    *,
    underlying_price: float,
    strike: float,
    iv_percent: float,
    dte_days: float,
    option_type: str = "call",
) -> dict[str, float]:
    """Greeks and risk-neutral ITM probability for either option type.

    Gamma, vega and theta are shared by both types under this model; delta and
    the ITM probability are not. A put's delta is the call's minus one and its
    ITM probability is the complement, so reusing the call figures for a put
    would place every put in the wrong delta bucket and invert its assignment
    odds — silently, because both numbers stay inside their plausible ranges.
    """
    sigma = max(iv_percent / 100.0, 1e-6)
    time_years = max(dte_days / 365.0, 1e-6)
    denom = sigma * sqrt(time_years)
    d1 = (log(underlying_price / strike) + 0.5 * sigma * sigma * time_years) / denom
    d2 = d1 - denom
    pdf = _NORMAL.pdf(d1)
    gamma = pdf / (underlying_price * denom)
    theta = -(underlying_price * pdf * sigma) / (2.0 * sqrt(time_years) * 365.0)
    vega = (underlying_price * pdf * sqrt(time_years)) / 100.0
    if option_type == "put":
        delta = _NORMAL.cdf(d1) - 1.0
        p_itm = _NORMAL.cdf(-d2)
    else:
        delta = _NORMAL.cdf(d1)
        p_itm = _NORMAL.cdf(d2)
    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "risk_neutral_p_itm": round(p_itm, 6),
    }


def _black_scholes_call_metrics(
    *,
    underlying_price: float,
    strike: float,
    iv_percent: float,
    dte_days: float,
) -> dict[str, float]:
    """Call-only entry point retained for the baseline backtest tracer."""
    return _black_scholes_metrics(
        underlying_price=underlying_price,
        strike=strike,
        iv_percent=iv_percent,
        dte_days=dte_days,
        option_type="call",
    )


def black_scholes_price(
    *,
    underlying_price: float,
    strike: float,
    iv_percent: float,
    dte_days: float,
    option_type: str = "call",
) -> float | None:
    """Theoretical option price under the same model the greeks already use.

    Shares the conventions of `_black_scholes_metrics`: zero rate, zero carry,
    and `underlying_price` treated as the forward — which it is when the venue
    supplied one, and is not when spot was substituted, a case the quote's
    `underlying_price_source` records. It exists so a quoted premium can be
    compared against the fitted surface's own valuation; it is not an
    independent valuation and inherits every assumption of that model.

    Returns None when the inputs cannot support a price rather than returning a
    degenerate zero.
    """
    if underlying_price <= 0 or strike <= 0 or dte_days <= 0 or iv_percent <= 0:
        return None
    sigma = iv_percent / 100.0
    time_years = dte_days / 365.0
    denominator = sigma * sqrt(time_years)
    if denominator <= 0:
        return None
    d1 = (log(underlying_price / strike) + 0.5 * sigma * sigma * time_years) / denominator
    d2 = d1 - denominator
    call = underlying_price * _NORMAL.cdf(d1) - strike * _NORMAL.cdf(d2)
    if option_type == "put":
        # Put-call parity at zero rate with forward = underlying_price.
        return call - underlying_price + strike
    return call


def black_scholes_call_price(
    *,
    underlying_price: float,
    strike: float,
    iv_percent: float,
    dte_days: float,
) -> float | None:
    """Call-only entry point retained for existing callers."""
    return black_scholes_price(
        underlying_price=underlying_price,
        strike=strike,
        iv_percent=iv_percent,
        dte_days=dte_days,
        option_type="call",
    )


def _assess_greek_consistency(
    model_delta: float,
    exchange_delta: float | None,
) -> dict[str, Any]:
    if exchange_delta is None:
        return {
            "status": "not_available",
            "exchange_delta": None,
            "delta_diff": None,
            "reason_codes": [],
        }

    delta_diff = round(abs(model_delta - exchange_delta), 6)
    if delta_diff > DEFAULT_SURFACE_LIMITS["delta_diff_reject_threshold"]:
        status = "reject"
        reason_codes = ["MODEL_EXCHANGE_DELTA_REJECT"]
    elif delta_diff > DEFAULT_SURFACE_LIMITS["delta_diff_review_threshold"]:
        status = "review"
        reason_codes = ["MODEL_EXCHANGE_DELTA_REVIEW"]
    else:
        status = "ok"
        reason_codes = []
    return {
        "status": status,
        "exchange_delta": exchange_delta,
        "delta_diff": delta_diff,
        "reason_codes": reason_codes,
    }


def _build_naked_candidate(
    point: dict[str, Any],
    expiry_report: dict[str, Any],
) -> dict[str, Any]:
    filter_reasons = _candidate_filter_reasons(point, expiry_report)
    greek_status = point["greek_consistency"]["status"]
    decision = "eligible"
    if filter_reasons or greek_status == "reject":
        decision = "reject"
    elif greek_status == "review":
        decision = "review"

    reason_codes = list(filter_reasons)
    reason_codes.extend(point["greek_consistency"]["reason_codes"])

    applied_thresholds = _premium_thresholds(point)
    return {
        "candidate_id": f"{point['instrument_name']}:naked",
        "structure_type": "naked_short_call",
        "instrument_name": point["instrument_name"],
        "expiry_date": point["expiry_date"],
        "dte_days": expiry_report["dte_days"],
        "strike_price": point["strike_price"],
        "underlying_price": point["underlying_price"],
        "underlying_price_source": point["underlying_price_source"],
        "forward_basis": point["forward_basis"],
        "market_bid": point["market_bid"],
        "market_ask": point["market_ask"],
        "market_mid": point["market_mid"],
        "premium_currency": point["premium_currency"],
        "premium_unit": point["premium_unit"],
        "settlement_currency": point["settlement_currency"],
        "applied_filter_thresholds": applied_thresholds,
        "market_bid_iv": point["market_bid_iv"],
        "market_ask_iv": point["market_ask_iv"],
        "market_mark_iv": point["market_mark_iv"],
        "surface_fitted_iv": point["surface_fitted_iv"],
        "fit_residual_iv": point["fit_residual_iv"],
        "fit_residual_z": point["fit_residual_z"],
        "fit_residual_vega_usd": point["fit_residual_vega_usd"],
        "fit_residual_scale": point["fit_residual_scale"],
        "model_delta": point["model_delta"],
        "model_gamma": point["model_gamma"],
        "model_theta": point["model_theta"],
        "model_vega": point["model_vega"],
        "risk_neutral_p_itm": point["risk_neutral_p_itm"],
        "open_interest": point["open_interest"],
        "spread_ratio": point["spread_ratio"],
        "quote_age_sec": point["quote_age_sec"],
        "best_bid_amount": point["best_bid_amount"],
        "best_ask_amount": point["best_ask_amount"],
        "depth": point["depth"],
        "surface_quality": {
            "fit_quality_score": expiry_report["fit_quality_score"],
            "no_arb_pass": expiry_report["no_arb_pass"],
            "no_arb_error": expiry_report["no_arb_error"],
        },
        "greek_consistency": point["greek_consistency"],
        "filter_status": "pass" if not filter_reasons else "fail",
        "filter_reason_codes": filter_reasons,
        "decision": decision,
        "decision_reason_codes": reason_codes,
        **_structure_annotations(
            structure_type="naked_short_call",
            legs=[_leg(point, quantity=-1.0)],
            points_by_instrument={point["instrument_name"]: point},
        ),
    }


def _build_spread_candidates(
    points: list[dict[str, Any]],
    expiry_report: dict[str, Any],
    *,
    option_type: str = "call",
) -> list[dict[str, Any]]:
    """Vertical credit spreads on one side of the chain.

    Direction is the only thing that differs between the two sides: a call
    credit spread sells the lower strike and buys the higher one for protection,
    a put credit spread does the reverse. Everything downstream — width, credit,
    filters, leg annotations — is identical, which is why this is one function
    rather than a copy.
    """
    structure_type = f"{option_type}_credit_spread"
    spreads = []
    for sell_leg in points:
        sell_filter_reasons = _candidate_filter_reasons(sell_leg, expiry_report)
        applied_thresholds = _premium_thresholds(sell_leg)
        for buy_leg in points:
            protective = (
                buy_leg["strike_price"] > sell_leg["strike_price"]
                if option_type == "call"
                else buy_leg["strike_price"] < sell_leg["strike_price"]
            )
            if not protective:
                continue
            width = round(
                abs(buy_leg["strike_price"] - sell_leg["strike_price"]), 6
            )
            width_bounds = _spread_width_bounds(sell_leg["underlying_price"])
            reason_codes = list(sell_filter_reasons)
            if buy_leg["premium_currency"] != sell_leg["premium_currency"]:
                reason_codes.append("PREMIUM_UNIT_MISMATCH")
            if width_bounds is None:
                reason_codes.append("SPREAD_WIDTH_BOUNDS_UNAVAILABLE")
            elif width < width_bounds["min"] or width > width_bounds["max"]:
                reason_codes.append("SPREAD_WIDTH_OUT_OF_RANGE")
            if (buy_leg["quote_age_sec"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_quote_age_sec"]:
                reason_codes.append("BUY_LEG_QUOTE_TOO_STALE")
            if (buy_leg["open_interest"] or 0.0) < DEFAULT_SURFACE_LIMITS["min_open_interest"]:
                reason_codes.append("BUY_LEG_OPEN_INTEREST_TOO_LOW")
            net_credit = round(sell_leg["market_bid"] - buy_leg["market_ask"], 6)
            if net_credit < applied_thresholds["min_net_credit"]:
                reason_codes.append("NET_CREDIT_TOO_LOW")
            protective_cost = _protective_leg_cost(buy_leg, net_credit=net_credit)
            reason_codes.extend(protective_cost["reason_codes"])

            greek_consistency = _combine_greek_consistency(
                sell_leg["greek_consistency"],
                buy_leg["greek_consistency"],
            )
            decision = "eligible"
            if reason_codes or greek_consistency["status"] == "reject":
                decision = "reject"
            elif greek_consistency["status"] == "review":
                decision = "review"

            decision_reason_codes = list(reason_codes)
            decision_reason_codes.extend(greek_consistency["reason_codes"])
            spreads.append(
                {
                    "candidate_id": (
                        f"{sell_leg['instrument_name']}->{buy_leg['instrument_name']}:spread"
                    ),
                    "structure_type": structure_type,
                    "option_type": option_type,
                    "mid_credit": _mid_credit(
                        [(sell_leg, -1.0), (buy_leg, 1.0)]
                    ),
                    # Carried so a condor can aggregate its wings' greeks, and
                    # stripped before the candidate is published.
                    "_leg_points": {
                        sell_leg["instrument_name"]: sell_leg,
                        buy_leg["instrument_name"]: buy_leg,
                    },
                    "expiry_date": sell_leg["expiry_date"],
                    "dte_days": expiry_report["dte_days"],
                    "sell_leg_instrument_name": sell_leg["instrument_name"],
                    "buy_leg_instrument_name": buy_leg["instrument_name"],
                    "sell_leg_strike_price": sell_leg["strike_price"],
                    "buy_leg_strike_price": buy_leg["strike_price"],
                    "spread_width": width,
                    "spread_width_bounds": width_bounds,
                    "protective_leg_cost": protective_cost["detail"],
                    "net_credit": net_credit,
                    "premium_currency": sell_leg["premium_currency"],
                    "premium_unit": sell_leg["premium_unit"],
                    "settlement_currency": sell_leg["settlement_currency"],
                    "applied_filter_thresholds": applied_thresholds,
                    "underlying_price": sell_leg["underlying_price"],
                    "sell_leg_market_bid": sell_leg["market_bid"],
                    "sell_leg_market_ask": sell_leg["market_ask"],
                    "buy_leg_market_bid": buy_leg["market_bid"],
                    "buy_leg_market_ask": buy_leg["market_ask"],
                    "sell_leg_market_bid_iv": sell_leg["market_bid_iv"],
                    "sell_leg_market_ask_iv": sell_leg["market_ask_iv"],
                    "buy_leg_market_bid_iv": buy_leg["market_bid_iv"],
                    "buy_leg_market_ask_iv": buy_leg["market_ask_iv"],
                    "sell_leg_market_mark_iv": sell_leg["market_mark_iv"],
                    "buy_leg_market_mark_iv": buy_leg["market_mark_iv"],
                    "sell_leg_surface_fitted_iv": sell_leg["surface_fitted_iv"],
                    "buy_leg_surface_fitted_iv": buy_leg["surface_fitted_iv"],
                    "sell_leg_fit_residual_iv": sell_leg["fit_residual_iv"],
                    "buy_leg_fit_residual_iv": buy_leg["fit_residual_iv"],
                    "sell_leg_fit_residual_vega_usd": sell_leg["fit_residual_vega_usd"],
                    "buy_leg_fit_residual_vega_usd": buy_leg["fit_residual_vega_usd"],
                    "fit_residual_scale": sell_leg["fit_residual_scale"],
                    "sell_leg_depth": sell_leg["depth"],
                    "buy_leg_depth": buy_leg["depth"],
                    "sell_leg_spread_ratio": sell_leg["spread_ratio"],
                    "buy_leg_spread_ratio": buy_leg["spread_ratio"],
                    "model_delta": round(
                        sell_leg["model_delta"] - buy_leg["model_delta"], 6
                    ),
                    "model_gamma": round(
                        sell_leg["model_gamma"] - buy_leg["model_gamma"], 8
                    ),
                    "model_theta": round(
                        sell_leg["model_theta"] - buy_leg["model_theta"], 6
                    ),
                    "model_vega": round(
                        sell_leg["model_vega"] - buy_leg["model_vega"], 6
                    ),
                    "risk_neutral_p_itm": sell_leg["risk_neutral_p_itm"],
                    "underlying_price_source": sell_leg["underlying_price_source"],
                    "forward_basis": sell_leg["forward_basis"],
                    "surface_quality": {
                        "fit_quality_score": expiry_report["fit_quality_score"],
                        "no_arb_pass": expiry_report["no_arb_pass"],
                        "no_arb_error": expiry_report["no_arb_error"],
                    },
                    "greek_consistency": greek_consistency,
                    "filter_status": "pass" if not reason_codes else "fail",
                    "filter_reason_codes": reason_codes,
                    "decision": decision,
                    "decision_reason_codes": decision_reason_codes,
                    **_structure_annotations(
                        structure_type=structure_type,
                        legs=[
                            _leg(sell_leg, quantity=-1.0),
                            _leg(buy_leg, quantity=1.0),
                        ],
                        points_by_instrument={
                            sell_leg["instrument_name"]: sell_leg,
                            buy_leg["instrument_name"]: buy_leg,
                        },
                    ),
                }
            )
    return spreads


# An iron condor is one put spread paired with one call spread, so the pair
# count is the product of two already-quadratic sets. The cap keeps a wide chain
# from producing a table nobody can read, and the truncation is reported rather
# than applied silently.
MAX_IRON_CONDOR_CANDIDATES = 64


def _build_iron_condor_candidates(
    *,
    put_spreads: list[dict[str, Any]],
    call_spreads: list[dict[str, Any]],
    expiry_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Pair defined-risk wings into two-sided structures.

    Only spreads that already passed their own filters are paired. A condor
    built from a rejected wing inherits that wing's problem, and burying the
    rejection inside a four-legged aggregate is exactly how a bad leg stops
    being visible.
    """
    eligible_puts = [item for item in put_spreads if item["decision"] == "eligible"]
    eligible_calls = [item for item in call_spreads if item["decision"] == "eligible"]

    pairs: list[dict[str, Any]] = []
    truncated = 0
    for put_spread in sorted(eligible_puts, key=lambda item: item["candidate_id"]):
        for call_spread in sorted(eligible_calls, key=lambda item: item["candidate_id"]):
            if put_spread["sell_leg_strike_price"] >= call_spread["sell_leg_strike_price"]:
                # The short strikes would cross, which is not a condor: the
                # position would be guaranteed to finish in obligation.
                continue
            if len(pairs) >= MAX_IRON_CONDOR_CANDIDATES:
                truncated += 1
                continue
            pairs.append(_iron_condor(put_spread, call_spread, expiry_report))
    return pairs, truncated


def _iron_condor(
    put_spread: dict[str, Any],
    call_spread: dict[str, Any],
    expiry_report: dict[str, Any],
) -> dict[str, Any]:
    legs = list(put_spread["structure_legs"]) + list(call_spread["structure_legs"])
    points = {**put_spread["_leg_points"], **call_spread["_leg_points"]}
    net_credit = round(put_spread["net_credit"] + call_spread["net_credit"], 6)
    mid_credit = _sum_optional(
        put_spread.get("mid_credit"), call_spread.get("mid_credit")
    )
    reason_codes = _unique(
        list(put_spread["filter_reason_codes"])
        + list(call_spread["filter_reason_codes"])
    )
    greek_consistency = _combine_greek_consistency(
        put_spread["greek_consistency"], call_spread["greek_consistency"]
    )
    decision = "eligible"
    if reason_codes or greek_consistency["status"] == "reject":
        decision = "reject"
    elif greek_consistency["status"] == "review":
        decision = "review"

    return {
        "candidate_id": (
            f"{put_spread['candidate_id']}+{call_spread['candidate_id']}:condor"
        ),
        "structure_type": "iron_condor",
        "expiry_date": expiry_report["expiry_date"],
        "dte_days": expiry_report["dte_days"],
        "put_spread_id": put_spread["candidate_id"],
        "call_spread_id": call_spread["candidate_id"],
        "put_short_strike_price": put_spread["sell_leg_strike_price"],
        "put_long_strike_price": put_spread["buy_leg_strike_price"],
        "call_short_strike_price": call_spread["sell_leg_strike_price"],
        "call_long_strike_price": call_spread["buy_leg_strike_price"],
        # The margin proxy is the wider wing: only one side can finish in
        # obligation, so the two widths are not additive.
        "spread_width": max(put_spread["spread_width"], call_spread["spread_width"]),
        "net_credit": net_credit,
        "mid_credit": mid_credit,
        "underlying_price": call_spread["underlying_price"],
        "underlying_price_source": call_spread["underlying_price_source"],
        "forward_basis": call_spread["forward_basis"],
        "premium_currency": call_spread["premium_currency"],
        "premium_unit": call_spread["premium_unit"],
        "settlement_currency": call_spread["settlement_currency"],
        "applied_filter_thresholds": call_spread["applied_filter_thresholds"],
        "fit_residual_scale": call_spread["fit_residual_scale"],
        "sell_leg_market_mark_iv": call_spread["sell_leg_market_mark_iv"],
        "sell_leg_surface_fitted_iv": call_spread["sell_leg_surface_fitted_iv"],
        "buy_leg_market_mark_iv": call_spread["buy_leg_market_mark_iv"],
        "buy_leg_surface_fitted_iv": call_spread["buy_leg_surface_fitted_iv"],
        # Only one wing can finish in the money, so the two assignment
        # probabilities are disjoint and add.
        "risk_neutral_p_itm": round(
            (put_spread["risk_neutral_p_itm"] or 0.0)
            + (call_spread["risk_neutral_p_itm"] or 0.0),
            6,
        ),
        "surface_quality": {
            "fit_quality_score": min(
                expiry_report["sides"]["call"]["fit_quality_score"],
                expiry_report["sides"]["put"]["fit_quality_score"],
            ),
            "no_arb_pass": (
                expiry_report["sides"]["call"]["no_arb_pass"]
                and expiry_report["sides"]["put"]["no_arb_pass"]
            ),
            "no_arb_error": max(
                expiry_report["sides"]["call"]["no_arb_error"],
                expiry_report["sides"]["put"]["no_arb_error"],
            ),
        },
        "greek_consistency": greek_consistency,
        "filter_status": "pass" if not reason_codes else "fail",
        "filter_reason_codes": reason_codes,
        "decision": decision,
        "decision_reason_codes": _unique(
            reason_codes + list(greek_consistency["reason_codes"])
        ),
        **_structure_annotations(
            structure_type="iron_condor",
            legs=legs,
            points_by_instrument=points,
        ),
    }


def _mid_credit(legs: list[tuple[dict[str, Any], float]]) -> float | None:
    """Credit at the mid of every leg: the yardstick executable credit is measured against."""
    total = 0.0
    for point, quantity in legs:
        mid = point.get("market_mid")
        if not isinstance(mid, (int, float)) or isinstance(mid, bool):
            return None
        total -= quantity * float(mid)
    return round(total, 6)


def _sum_optional(left: Any, right: Any) -> float | None:
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return None
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        return None
    return round(float(left) + float(right), 6)


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _spread_width_bounds(underlying_price: Any) -> dict[str, Any] | None:
    """Resolve the fractional width window against this candidate's own underlying."""
    if not isinstance(underlying_price, (int, float)) or isinstance(
        underlying_price, bool
    ):
        return None
    if not underlying_price > 0:
        return None
    return {
        "min": round(
            underlying_price * DEFAULT_SURFACE_LIMITS["min_spread_width_fraction"], 6
        ),
        "max": round(
            underlying_price * DEFAULT_SURFACE_LIMITS["max_spread_width_fraction"], 6
        ),
        "min_fraction": DEFAULT_SURFACE_LIMITS["min_spread_width_fraction"],
        "max_fraction": DEFAULT_SURFACE_LIMITS["max_spread_width_fraction"],
        "underlying_price": underlying_price,
    }


def _protective_leg_cost(
    buy_leg: dict[str, Any], *, net_credit: float
) -> dict[str, Any]:
    """What crossing the protective leg costs, against what it is protecting.

    The sell leg is gated on its spread ratio because that ratio *is* the cost:
    the credit is taken at the bid. The buy leg is not — it is a one-off
    insurance premium, and a deep wing's ratio is large because its premium is
    tiny, not because crossing it is expensive. Measuring the crossing cost
    against the credit it protects is the same question asked in units that
    mean something.
    """
    bid = buy_leg.get("market_bid")
    ask = buy_leg.get("market_ask")
    ratio = buy_leg.get("spread_ratio")
    reason_codes: list[str] = []

    if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
        return {
            "reason_codes": ["BUY_LEG_QUOTE_UNAVAILABLE"],
            "detail": {"status": "unavailable"},
        }
    if isinstance(ratio, (int, float)) and ratio > DEFAULT_SURFACE_LIMITS[
        "max_quote_spread_ratio_hard"
    ]:
        reason_codes.append("BUY_LEG_QUOTE_IMPLAUSIBLE")

    half_spread = max((ask - bid) / 2.0, 0.0)
    cost_ratio = (
        half_spread / net_credit if net_credit > 0 else None
    )
    if cost_ratio is None:
        reason_codes.append("BUY_LEG_COST_NOT_COMPARABLE")
    elif cost_ratio > DEFAULT_SURFACE_LIMITS["max_protective_leg_cost_ratio"]:
        reason_codes.append("BUY_LEG_COST_EXCEEDS_CREDIT_SHARE")

    return {
        "reason_codes": reason_codes,
        "detail": {
            "status": "measured",
            "half_spread": round(half_spread, 8),
            "quote_spread_ratio": ratio,
            "cost_share_of_credit": (
                round(cost_ratio, 6) if cost_ratio is not None else None
            ),
            "max_cost_share": DEFAULT_SURFACE_LIMITS["max_protective_leg_cost_ratio"],
            "basis": "half_spread_over_net_credit",
        },
    }


def _leg(point: dict[str, Any], *, quantity: float) -> dict[str, Any]:
    return {
        "option_type": point.get("option_type") or "call",
        "strike": point["strike_price"],
        "quantity": quantity,
        "expiry_date": point["expiry_date"],
        "instrument_name": point["instrument_name"],
        # The leg's own fitted volatility travels with it so a consumer can
        # value any structure from its legs instead of needing a per-structure
        # formula.
        "surface_fitted_iv": point["surface_fitted_iv"],
        "market_mark_iv": point["market_mark_iv"],
    }


def _structure_annotations(
    *,
    structure_type: str,
    legs: list[dict[str, Any]],
    points_by_instrument: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach the candidate's legs and its position greeks.

    Downstream consumers used to negate the long option's greeks by hand to
    recover the short position's, which is right until a structure mixes
    directions. Aggregating here with signed quantities means every consumer
    reads greeks that already face the way the position does, and the legs
    travel with the candidate so risk bounds can be derived rather than inferred
    from the structure's name.
    """
    structure = build_structure(structure_type=structure_type, legs=legs)
    greeks = structure.position_greeks(
        {
            name: {
                "delta": point.get("model_delta"),
                "gamma": point.get("model_gamma"),
                "theta": point.get("model_theta"),
                "vega": point.get("model_vega"),
            }
            for name, point in points_by_instrument.items()
        }
    )
    return {
        "structure_legs": legs,
        "structure_shape": structure.to_dict(),
        "position_greeks": greeks,
    }


def _combine_greek_consistency(
    sell_leg: dict[str, Any],
    buy_leg: dict[str, Any],
) -> dict[str, Any]:
    statuses = {sell_leg["status"], buy_leg["status"]}
    if "reject" in statuses:
        status = "reject"
    elif "review" in statuses:
        status = "review"
    elif statuses == {"not_available"}:
        status = "not_available"
    else:
        status = "ok"
    reason_codes = list(sell_leg.get("reason_codes", []))
    for code in buy_leg.get("reason_codes", []):
        if code not in reason_codes:
            reason_codes.append(code)
    return {
        "status": status,
        "sell_leg": sell_leg,
        "buy_leg": buy_leg,
        "reason_codes": reason_codes,
    }


def _candidate_filter_reasons(
    point: dict[str, Any],
    expiry_report: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    dte_days = expiry_report["dte_days"]
    delta = abs(point["model_delta"])
    if dte_days < DEFAULT_SURFACE_LIMITS["min_dte_days"] or dte_days > DEFAULT_SURFACE_LIMITS["max_dte_days"]:
        reasons.append("DTE_OUT_OF_RANGE")
    if delta < DEFAULT_SURFACE_LIMITS["min_delta"] or delta > DEFAULT_SURFACE_LIMITS["max_delta"]:
        reasons.append("DELTA_OUT_OF_RANGE")
    applied_thresholds = _premium_thresholds(point)
    if point["market_bid"] < applied_thresholds["min_bid"]:
        reasons.append("BID_TOO_LOW")
    if (point["open_interest"] or 0.0) < DEFAULT_SURFACE_LIMITS["min_open_interest"]:
        reasons.append("OPEN_INTEREST_TOO_LOW")
    if (point["spread_ratio"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_spread_ratio"]:
        reasons.append("SPREAD_RATIO_TOO_WIDE")
    if point["quote_age_sec"] > DEFAULT_SURFACE_LIMITS["max_quote_age_sec"]:
        reasons.append("QUOTE_TOO_STALE")
    if not expiry_report["candidate_eligible"]:
        reasons.append("SURFACE_QUALITY_BLOCKED")
    return reasons


def _premium_thresholds(point: dict[str, Any]) -> dict[str, Any]:
    premium_currency = str(point.get("premium_currency") or "UNKNOWN").upper()
    premium_unit = str(point.get("premium_unit") or "unknown")
    if premium_currency == "BTC" and premium_unit == "inverse_base_currency":
        min_bid = DEFAULT_SURFACE_LIMITS["min_bid_btc"]
        min_net_credit = DEFAULT_SURFACE_LIMITS["min_net_credit_btc"]
    else:
        min_bid = DEFAULT_SURFACE_LIMITS["min_bid"]
        min_net_credit = DEFAULT_SURFACE_LIMITS["min_net_credit"]
    return {
        "min_bid": min_bid,
        "min_net_credit": min_net_credit,
        "premium_currency": premium_currency,
        "premium_unit": premium_unit,
    }


def _dte_days(expiry_date: str, evaluation_now_ms: int) -> float:
    expiry_dt = datetime.fromisoformat(expiry_date).replace(tzinfo=UTC) + timedelta(hours=8)
    evaluation_dt = datetime.fromtimestamp(evaluation_now_ms / 1000, tz=UTC)
    delta = expiry_dt - evaluation_dt
    return round(max(delta.total_seconds(), 0.0) / 86400.0, 6)


def _decision_bucket(decision: str) -> str:
    return {
        "eligible": "eligible",
        "review": "review",
        "reject": "rejected",
    }[decision]
