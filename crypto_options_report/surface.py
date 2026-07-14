"""Research-only vol-surface fitting and candidate discovery helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, log, sqrt
from statistics import NormalDist
from typing import Any

from .market_data import normalize_market_snapshot, parse_timestamp_ms

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
    "min_spread_width": 5000.0,
    "max_spread_width": 15000.0,
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

    naked_tables = {"eligible": [], "review": [], "rejected": []}
    spread_tables = {"eligible": [], "review": [], "rejected": []}
    rejected_expiries = []

    for expiry_report in eligible_expiries:
        if not expiry_report["candidate_eligible"]:
            rejected_expiries.append(expiry_report["expiry_date"])
            continue
        points = expiry_report["surface_points"]
        for point in points:
            candidate = _build_naked_candidate(point, expiry_report)
            naked_tables[_decision_bucket(candidate["decision"])].append(candidate)
        for spread in _build_spread_candidates(points, expiry_report):
            spread_tables[_decision_bucket(spread["decision"])].append(spread)

    candidate_status = "validated"
    reason_code = None
    total_candidates = (
        sum(len(rows) for rows in naked_tables.values())
        + sum(len(rows) for rows in spread_tables.values())
    )
    if total_candidates == 0:
        candidate_status = "blocked"
        reason_code = (
            "SURFACE_QUALITY_FAIL"
            if not eligible_expiries
            else "NO_ELIGIBLE_CANDIDATES"
        )

    candidate_research = {
        "status": candidate_status,
        "reason_code": reason_code,
        "filter_thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "naked_short_calls": naked_tables,
        "call_credit_spreads": spread_tables,
        "summary": {
            "expiries_considered": len(expiries),
            "eligible_expiries": len(eligible_expiries),
            "rejected_expiries": rejected_expiries,
            "eligible_naked_short_calls": len(naked_tables["eligible"]),
            "review_naked_short_calls": len(naked_tables["review"]),
            "rejected_naked_short_calls": len(naked_tables["rejected"]),
            "eligible_call_credit_spreads": len(spread_tables["eligible"]),
            "review_call_credit_spreads": len(spread_tables["review"]),
            "rejected_call_credit_spreads": len(spread_tables["rejected"]),
        },
    }
    return vol_surface_status, candidate_research


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
    empty_tables = {"eligible": [], "review": [], "rejected": []}
    return {
        "status": "blocked",
        "reason_code": reason_code,
        "filter_thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "naked_short_calls": empty_tables.copy(),
        "call_credit_spreads": empty_tables.copy(),
        "summary": {
            "expiries_considered": 0,
            "eligible_expiries": 0,
            "rejected_expiries": [],
            "eligible_naked_short_calls": 0,
            "review_naked_short_calls": 0,
            "rejected_naked_short_calls": 0,
            "eligible_call_credit_spreads": 0,
            "review_call_credit_spreads": 0,
            "rejected_call_credit_spreads": 0,
        },
    }


def _build_expiry_surface(
    *,
    expiry_date: str,
    quotes: list[dict[str, Any]],
    evaluation_now_ms: int,
) -> dict[str, Any]:
    valid_quotes = [
        quote
        for quote in sorted(quotes, key=lambda item: item["strike"])
        if quote["quality_status"] == "valid" and quote.get("option_type") == "call"
    ]
    dte_days = _dte_days(expiry_date, evaluation_now_ms)
    if len(valid_quotes) < DEFAULT_SURFACE_LIMITS["min_quotes_per_expiry"]:
        return {
            "expiry_date": expiry_date,
            "dte_days": dte_days,
            "quality_passing_quotes": len(valid_quotes),
            "fit_quality_score": 0.0,
            "fit_quality_pass": False,
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
        "expiry_date": expiry_date,
        "dte_days": dte_days,
        "quality_passing_quotes": len(valid_quotes),
        "fit_quality_score": fit["fit_quality_score"],
        "fit_quality_pass": fit_pass,
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
        residuals = [actual - estimate for actual, estimate in zip(ys, fitted)]
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
    residuals = [actual - estimate for actual, estimate in zip(ys, fitted)]
    rmse = sqrt(sum(value * value for value in residuals) / len(residuals))
    iv_range = max(max(ys) - min(ys), 1.0)
    fit_quality_score = max(0.0, round(1.0 - (rmse / iv_range), 6))
    return {
        "basis": "centred_scaled_log_moneyness",
        "x_center": x_center,
        "x_scale": x_scale,
        "coefficients": coefficients,
        "fitted": fitted,
        "residuals": residuals,
        "fit_quality_score": fit_quality_score,
    }


def _weighted_quadratic_coefficients(
    xs: list[float],
    ys: list[float],
    weights: list[float],
) -> list[float]:
    moments = [sum(weight * (x ** power) for x, weight in zip(xs, weights)) for power in range(5)]
    targets = [
        sum(weight * (x ** power) * y for x, y, weight in zip(xs, ys, weights))
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
        return [sum(weight * value for weight, value in zip(weights, ys)) / total_weight, 0.0, 0.0]


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
                for value, pivot_value in zip(augmented[row], augmented[column])
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
) -> dict[str, Any]:
    monotonic_errors = []
    convexity_errors = []
    reason_codes: list[str] = []
    for left, right in zip(valid_quotes, valid_quotes[1:]):
        if right["strike"] <= left["strike"]:
            monotonic_errors.append(1.0)
            _append_unique(reason_codes, "SURFACE_DUPLICATE_STRIKE")
            continue
        if right["mid"] > left["mid"]:
            base = max(abs(left["mid"]), 1e-6)
            monotonic_errors.append((right["mid"] - left["mid"]) / base)

    for first, second, third in zip(valid_quotes, valid_quotes[1:], valid_quotes[2:]):
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
    metrics = _black_scholes_call_metrics(
        underlying_price=quote["underlying_price"],
        strike=quote["strike"],
        iv_percent=fitted_iv,
        dte_days=dte_days,
    )
    greek_consistency = _assess_greek_consistency(
        metrics["delta"],
        exchange_greeks.get("delta"),
    )
    return {
        "instrument_name": quote["instrument_name"],
        "expiry_date": expiry_date,
        "strike_price": quote["strike"],
        "underlying_price": quote["underlying_price"],
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
        "fit_residual_iv": round(quote["mark_iv"] - fitted_iv, 6),
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


def _black_scholes_call_metrics(
    *,
    underlying_price: float,
    strike: float,
    iv_percent: float,
    dte_days: float,
) -> dict[str, float]:
    sigma = max(iv_percent / 100.0, 1e-6)
    time_years = max(dte_days / 365.0, 1e-6)
    denom = sigma * sqrt(time_years)
    d1 = (log(underlying_price / strike) + 0.5 * sigma * sigma * time_years) / denom
    d2 = d1 - denom
    pdf = _NORMAL.pdf(d1)
    delta = _NORMAL.cdf(d1)
    gamma = pdf / (underlying_price * denom)
    theta = -(underlying_price * pdf * sigma) / (2.0 * sqrt(time_years) * 365.0)
    vega = (underlying_price * pdf * sqrt(time_years)) / 100.0
    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "risk_neutral_p_itm": round(_NORMAL.cdf(d2), 6),
    }


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
    }


def _build_spread_candidates(
    points: list[dict[str, Any]],
    expiry_report: dict[str, Any],
) -> list[dict[str, Any]]:
    spreads = []
    for sell_leg in points:
        sell_filter_reasons = _candidate_filter_reasons(sell_leg, expiry_report)
        applied_thresholds = _premium_thresholds(sell_leg)
        for buy_leg in points:
            if buy_leg["strike_price"] <= sell_leg["strike_price"]:
                continue
            width = round(buy_leg["strike_price"] - sell_leg["strike_price"], 6)
            reason_codes = list(sell_filter_reasons)
            if buy_leg["premium_currency"] != sell_leg["premium_currency"]:
                reason_codes.append("PREMIUM_UNIT_MISMATCH")
            if width < DEFAULT_SURFACE_LIMITS["min_spread_width"] or width > DEFAULT_SURFACE_LIMITS["max_spread_width"]:
                reason_codes.append("SPREAD_WIDTH_OUT_OF_RANGE")
            if (buy_leg["spread_ratio"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_spread_ratio"]:
                reason_codes.append("BUY_LEG_SPREAD_TOO_WIDE")
            if (buy_leg["quote_age_sec"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_quote_age_sec"]:
                reason_codes.append("BUY_LEG_QUOTE_TOO_STALE")
            if (buy_leg["open_interest"] or 0.0) < DEFAULT_SURFACE_LIMITS["min_open_interest"]:
                reason_codes.append("BUY_LEG_OPEN_INTEREST_TOO_LOW")
            net_credit = round(sell_leg["market_bid"] - buy_leg["market_ask"], 6)
            if net_credit < applied_thresholds["min_net_credit"]:
                reason_codes.append("NET_CREDIT_TOO_LOW")

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
                    "structure_type": "call_credit_spread",
                    "expiry_date": sell_leg["expiry_date"],
                    "dte_days": expiry_report["dte_days"],
                    "sell_leg_instrument_name": sell_leg["instrument_name"],
                    "buy_leg_instrument_name": buy_leg["instrument_name"],
                    "sell_leg_strike_price": sell_leg["strike_price"],
                    "buy_leg_strike_price": buy_leg["strike_price"],
                    "spread_width": width,
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
                }
            )
    return spreads


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
    expiry_dt = datetime.fromisoformat(expiry_date).replace(tzinfo=timezone.utc) + timedelta(hours=8)
    evaluation_dt = datetime.fromtimestamp(evaluation_now_ms / 1000, tz=timezone.utc)
    delta = expiry_dt - evaluation_dt
    return round(max(delta.total_seconds(), 0.0) / 86400.0, 6)


def _decision_bucket(decision: str) -> str:
    return {
        "eligible": "eligible",
        "review": "review",
        "reject": "rejected",
    }[decision]
