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
    "min_bid": 0.05,
    "min_open_interest": 10.0,
    "max_spread_ratio": 0.25,
    "max_quote_age_sec": 120.0,
    "min_spread_width": 5000.0,
    "max_spread_width": 15000.0,
    "min_net_credit": 0.01,
    "delta_diff_review_threshold": 0.03,
    "delta_diff_reject_threshold": 0.08,
}

_NORMAL = NormalDist()


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
    for quote in normalized["quotes"]:
        expiry_groups.setdefault(quote["expiry_date"], []).append(quote)

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
        "fit_model": "linear_iv_vs_log_moneyness",
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
        "fit_model": "linear_iv_vs_log_moneyness",
        "thresholds": dict(DEFAULT_SURFACE_LIMITS),
        "expiries": [],
        "summary": {
            "expiries_evaluated": 0,
            "eligible_expiries": 0,
            "quality_passing_quotes": 0,
        },
    }


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
        if quote["quality_status"] == "valid"
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

    fit = _fit_linear_iv_surface(valid_quotes)
    no_arb = _evaluate_no_arb(valid_quotes)
    fit_pass = fit["fit_quality_score"] >= DEFAULT_SURFACE_LIMITS["fit_quality_threshold"]
    no_arb_pass = (
        no_arb["passed"]
        and no_arb["error"] <= DEFAULT_SURFACE_LIMITS["max_no_arb_error"]
    )
    reason_codes: list[str] = []
    if not fit_pass:
        reason_codes.append("SURFACE_FIT_QUALITY_TOO_LOW")
    if not no_arb_pass:
        reason_codes.append("SURFACE_NO_ARBITRAGE_FAIL")

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


def _fit_linear_iv_surface(valid_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    xs = []
    ys = []
    for quote in valid_quotes:
        xs.append(log(quote["strike"] / quote["underlying_price"]))
        ys.append(quote["mark_iv"])

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((value - mean_x) ** 2 for value in xs)
    if denom <= 0:
        slope = 0.0
        intercept = mean_y
    else:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
        intercept = mean_y - slope * mean_x

    fitted = [intercept + slope * x for x in xs]
    residuals = [actual - estimate for actual, estimate in zip(ys, fitted)]
    rmse = sqrt(sum(value * value for value in residuals) / len(residuals))
    iv_range = max(max(ys) - min(ys), 1.0)
    fit_quality_score = max(0.0, round(1.0 - (rmse / iv_range), 6))
    return {
        "slope": slope,
        "intercept": intercept,
        "fitted": fitted,
        "residuals": residuals,
        "fit_quality_score": fit_quality_score,
    }


def _evaluate_no_arb(valid_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    monotonic_errors = []
    convexity_errors = []
    for left, right in zip(valid_quotes, valid_quotes[1:]):
        if right["mid"] > left["mid"]:
            base = max(abs(left["mid"]), 1e-6)
            monotonic_errors.append((right["mid"] - left["mid"]) / base)

    for first, second, third in zip(valid_quotes, valid_quotes[1:], valid_quotes[2:]):
        left_slope = (second["mid"] - first["mid"]) / (second["strike"] - first["strike"])
        right_slope = (third["mid"] - second["mid"]) / (third["strike"] - second["strike"])
        if right_slope < left_slope:
            denom = max(abs(left_slope) + abs(right_slope), 1e-6)
            convexity_errors.append((left_slope - right_slope) / denom)

    error = round(max(monotonic_errors + convexity_errors + [0.0]), 6)
    return {"passed": error <= 0.0, "error": error}


def _build_surface_point(
    *,
    quote: dict[str, Any],
    fit: dict[str, Any],
    expiry_date: str,
    dte_days: float,
) -> dict[str, Any]:
    exchange_greeks = quote.get("exchange_greeks") or {}
    log_moneyness = log(quote["strike"] / quote["underlying_price"])
    fitted_iv = round(fit["intercept"] + fit["slope"] * log_moneyness, 6)
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
        for buy_leg in points:
            if buy_leg["strike_price"] <= sell_leg["strike_price"]:
                continue
            width = round(buy_leg["strike_price"] - sell_leg["strike_price"], 6)
            reason_codes = list(sell_filter_reasons)
            if width < DEFAULT_SURFACE_LIMITS["min_spread_width"] or width > DEFAULT_SURFACE_LIMITS["max_spread_width"]:
                reason_codes.append("SPREAD_WIDTH_OUT_OF_RANGE")
            if (buy_leg["spread_ratio"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_spread_ratio"]:
                reason_codes.append("BUY_LEG_SPREAD_TOO_WIDE")
            if (buy_leg["quote_age_sec"] or 0.0) > DEFAULT_SURFACE_LIMITS["max_quote_age_sec"]:
                reason_codes.append("BUY_LEG_QUOTE_TOO_STALE")
            if (buy_leg["open_interest"] or 0.0) < DEFAULT_SURFACE_LIMITS["min_open_interest"]:
                reason_codes.append("BUY_LEG_OPEN_INTEREST_TOO_LOW")
            net_credit = round(sell_leg["market_bid"] - buy_leg["market_ask"], 6)
            if net_credit < DEFAULT_SURFACE_LIMITS["min_net_credit"]:
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
    if point["market_bid"] < DEFAULT_SURFACE_LIMITS["min_bid"]:
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
