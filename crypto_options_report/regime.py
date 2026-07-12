"""Research-only regime scoring and conservative permission caps."""

from __future__ import annotations

from typing import Any


DEFAULT_REGIME_INPUTS = {
    "bear_trend_score": 0.35,
    "range_score": 0.55,
    "squeeze_score": 0.20,
    "slow_bull_score": 0.20,
    "fast_bull_breakout_score": 0.10,
    "event_score": 0.00,
}

DEFAULT_REGIME_THRESHOLDS = {
    "bear_trend_active": 0.65,
    "range_active": 0.60,
    "squeeze_review": 0.50,
    "squeeze_active": 0.65,
    "slow_bull_review": 0.45,
    "slow_bull_active": 0.60,
    "breakout_review": 0.55,
    "breakout_kill": 0.70,
    "event_review": 0.40,
    "event_kill": 0.60,
    "data_quality_kill": 0.50,
    "volatility_cap_60": 0.60,
    "volatility_cap_80": 0.80,
    "volatility_cap_95": 0.95,
    "volatility_cap_98": 0.98,
    "naked_permission_min": 0.60,
}

_PRIMARY_LABELS = {
    "bear_trend": "Bear Trend",
    "range": "Range",
    "squeeze": "Squeeze",
    "slow_bull": "Slow Bull",
    "fast_bull_breakout": "Fast Bull Breakout",
}


def build_regime_permission_state(
    *,
    market_snapshot: dict[str, Any] | None,
    data_status: dict[str, Any],
    vol_surface_status: dict[str, Any],
) -> dict[str, Any]:
    if market_snapshot is None or data_status.get("status") == "missing":
        return _blocked_permission_state(
            reason_codes=["MISSING_VALIDATED_MARKET_DATA"],
            account_margin_light="HALT",
            account_trade_gate="NO_TRADE",
        )

    if vol_surface_status.get("status") != "validated":
        return _blocked_permission_state(
            reason_codes=["VOL_SURFACE_NOT_VALIDATED"],
            account_margin_light="HALT",
            account_trade_gate="NO_TRADE",
        )

    raw_inputs = market_snapshot.get("regime_inputs") or {}
    percentiles, percentile_provenance = _resolve_volatility_percentiles(
        raw_inputs,
        vol_surface_status,
    )
    score_fields = (
        ("bear_trend", "bear_trend_score", ("bear_score",), DEFAULT_REGIME_INPUTS["bear_trend_score"]),
        ("range", "range_score", ("range_bound_score",), DEFAULT_REGIME_INPUTS["range_score"]),
        ("squeeze", "squeeze_score", ("squeeze_risk_score",), DEFAULT_REGIME_INPUTS["squeeze_score"]),
        (
            "slow_bull",
            "slow_bull_score",
            ("bull_trend_score",),
            DEFAULT_REGIME_INPUTS["slow_bull_score"],
        ),
        (
            "fast_bull_breakout",
            "fast_bull_breakout_score",
            ("breakout_score",),
            DEFAULT_REGIME_INPUTS["fast_bull_breakout_score"],
        ),
        ("event", "event_score", ("event_risk_score",), DEFAULT_REGIME_INPUTS["event_score"]),
    )
    scores: dict[str, float] = {}
    defaults_applied: list[str] = []
    for score_name, primary, aliases, default in score_fields:
        value, used_default = _score_value_with_provenance(
            raw_inputs,
            primary,
            aliases=aliases,
            default=default,
        )
        scores[score_name] = value
        if used_default:
            defaults_applied.append(primary)
    scores["volatility_stress"] = max(
        percentiles["dvol_percentile"],
        percentiles["atm_iv_percentile"],
    )
    scores["data_quality"] = 0.0 if data_status.get("status") == "validated" else 1.0
    input_provenance = {
        "regime_inputs_present": bool(raw_inputs),
        "defaults_applied": defaults_applied,
        "percentile_source": percentile_provenance,
        "synthetic_inputs": bool(defaults_applied)
        or percentile_provenance == "surface_iv_fallback",
    }

    ignored_inputs = sorted(
        key
        for key in (
            "narrative_label",
            "historical_phase_label",
            "user_regime_label",
            "story_phase",
        )
        if key in raw_inputs
    )

    cap_details = _cap_details(scores, percentiles)
    limiting_cap = min(cap_details, key=lambda detail: (detail["cap"], detail["priority"]))
    sell_permission = round(float(limiting_cap["cap"]), 2)
    kill_active = any(detail["kill"] and detail["active"] for detail in cap_details)
    spread_only_active = any(
        detail["active"] and detail["dimension"] in {"squeeze", "slow_bull"}
        for detail in cap_details
    )
    primary_label = _primary_regime_label(scores)
    reason_codes = _unique_codes(
        [f"PRIMARY_REGIME_{primary_label.upper().replace(' ', '_')}"]
        + [code for detail in cap_details for code in detail["reason_codes"]]
    )
    spread_permission = sell_permission > 0.0
    naked_permission = (
        spread_permission
        and not kill_active
        and not spread_only_active
        and sell_permission >= DEFAULT_REGIME_THRESHOLDS["naked_permission_min"]
    )

    if input_provenance["synthetic_inputs"]:
        reason_codes = _unique_codes(reason_codes + ["REGIME_DEFAULTS_OR_FALLBACK_APPLIED"])

    return {
        "status": "validated",
        "sell_permission": sell_permission,
        "naked_permission": naked_permission,
        "spread_permission": spread_permission,
        "paper_trading_allowed": False,
        "manual_execution_allowed": False,
        "account_margin_light": "HALT",
        "account_trade_gate": "NO_TRADE",
        "primary_regime_label": primary_label,
        "label_is_report_only": True,
        "limiting_dimension": limiting_cap["dimension"],
        "limiting_cap": limiting_cap["cap"],
        "reason_codes": reason_codes,
        "regime_scores": scores,
        "volatility_inputs": percentiles,
        "input_provenance": input_provenance,
        "ignored_inputs": ignored_inputs,
        "cap_details": cap_details,
    }


def _blocked_permission_state(
    *,
    reason_codes: list[str],
    account_margin_light: str,
    account_trade_gate: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "sell_permission": 0.0,
        "naked_permission": False,
        "spread_permission": False,
        "paper_trading_allowed": False,
        "manual_execution_allowed": False,
        "account_margin_light": account_margin_light,
        "account_trade_gate": account_trade_gate,
        "primary_regime_label": "Unavailable",
        "label_is_report_only": True,
        "limiting_dimension": "dependency_gate",
        "limiting_cap": 0.0,
        "reason_codes": list(reason_codes),
        "regime_scores": {
            "bear_trend": 0.0,
            "range": 0.0,
            "squeeze": 0.0,
            "slow_bull": 0.0,
            "fast_bull_breakout": 0.0,
            "event": 0.0,
            "volatility_stress": 0.0,
            "data_quality": 1.0,
        },
        "volatility_inputs": {
            "dvol_percentile": 0.0,
            "atm_iv_percentile": 0.0,
        },
        "input_provenance": {
            "regime_inputs_present": False,
            "defaults_applied": [],
            "percentile_source": "unavailable",
            "synthetic_inputs": True,
        },
        "ignored_inputs": [],
        "cap_details": [
            {
                "dimension": "dependency_gate",
                "score": 1.0,
                "cap": 0.0,
                "active": True,
                "kill": True,
                "priority": 0,
                "reason_codes": list(reason_codes),
            }
        ],
    }


def _resolve_volatility_percentiles(
    raw_inputs: dict[str, Any],
    vol_surface_status: dict[str, Any],
) -> tuple[dict[str, float], str]:
    atm_iv_percentile = _percentile_value(
        raw_inputs,
        "atm_iv_percentile",
        aliases=("atm_iv_pct",),
    )
    dvol_percentile = _percentile_value(
        raw_inputs,
        "dvol_percentile",
        aliases=("dvol_pct",),
    )
    provenance = "measured"
    if atm_iv_percentile is None or dvol_percentile is None:
        fallback = _fallback_iv_percentile(vol_surface_status)
        provenance = "surface_iv_fallback"
        if atm_iv_percentile is None:
            atm_iv_percentile = fallback
        if dvol_percentile is None:
            dvol_percentile = fallback
    return (
        {
            "dvol_percentile": _clamp01(dvol_percentile),
            "atm_iv_percentile": _clamp01(atm_iv_percentile),
        },
        provenance,
    )


def _fallback_iv_percentile(vol_surface_status: dict[str, Any]) -> float:
    values: list[float] = []
    for expiry in vol_surface_status.get("expiries", []):
        for point in expiry.get("surface_points", []):
            iv_value = point.get("surface_fitted_iv")
            if isinstance(iv_value, (int, float)):
                values.append(iv_value)
    if not values:
        return 0.5
    return _clamp01(sum(values) / len(values) / 100.0)


def _score_value_with_provenance(
    raw_inputs: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
    default: float,
) -> tuple[float, bool]:
    for key in (primary, *aliases):
        value = raw_inputs.get(key)
        if value is None:
            continue
        try:
            return _clamp01(float(value)), False
        except (TypeError, ValueError):
            continue
    return _clamp01(default), True


def _score_value(
    raw_inputs: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
    default: float,
) -> float:
    value, _used_default = _score_value_with_provenance(
        raw_inputs,
        primary,
        aliases=aliases,
        default=default,
    )
    return value


def _percentile_value(
    raw_inputs: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
) -> float | None:
    for key in (primary, *aliases):
        value = raw_inputs.get(key)
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 1.0:
                numeric = numeric / 100.0
            return _clamp01(numeric)
    return None


def _cap_details(
    scores: dict[str, float],
    percentiles: dict[str, float],
) -> list[dict[str, Any]]:
    thresholds = DEFAULT_REGIME_THRESHOLDS
    volatility_cap = _volatility_cap(
        max(percentiles["dvol_percentile"], percentiles["atm_iv_percentile"])
    )
    return [
        {
            "dimension": "bear_trend",
            "score": scores["bear_trend"],
            "cap": 0.75 if scores["bear_trend"] >= thresholds["bear_trend_active"] else 1.0,
            "active": scores["bear_trend"] >= thresholds["bear_trend_active"],
            "kill": False,
            "priority": 7,
            "reason_codes": (
                ["BEAR_TREND_PERMISSION_ACTIVE"]
                if scores["bear_trend"] >= thresholds["bear_trend_active"]
                else []
            ),
        },
        {
            "dimension": "range",
            "score": scores["range"],
            "cap": 0.55 if scores["range"] >= thresholds["range_active"] else 1.0,
            "active": scores["range"] >= thresholds["range_active"],
            "kill": False,
            "priority": 8,
            "reason_codes": (
                ["RANGE_PERMISSION_ACTIVE"]
                if scores["range"] >= thresholds["range_active"]
                else []
            ),
        },
        {
            "dimension": "squeeze",
            "score": scores["squeeze"],
            "cap": (
                0.25
                if scores["squeeze"] >= thresholds["squeeze_active"]
                else 0.40
                if scores["squeeze"] >= thresholds["squeeze_review"]
                else 1.0
            ),
            "active": scores["squeeze"] >= thresholds["squeeze_review"],
            "kill": False,
            "priority": 5,
            "reason_codes": (
                ["SQUEEZE_SPREAD_ONLY_CAP"]
                if scores["squeeze"] >= thresholds["squeeze_active"]
                else ["SQUEEZE_REVIEW_CAP"]
                if scores["squeeze"] >= thresholds["squeeze_review"]
                else []
            ),
        },
        {
            "dimension": "slow_bull",
            "score": scores["slow_bull"],
            "cap": (
                0.15
                if scores["slow_bull"] >= thresholds["slow_bull_active"]
                else 0.35
                if scores["slow_bull"] >= thresholds["slow_bull_review"]
                else 1.0
            ),
            "active": scores["slow_bull"] >= thresholds["slow_bull_review"],
            "kill": False,
            "priority": 4,
            "reason_codes": (
                ["SLOW_BULL_SPREAD_ONLY_CAP"]
                if scores["slow_bull"] >= thresholds["slow_bull_active"]
                else ["SLOW_BULL_REVIEW_CAP"]
                if scores["slow_bull"] >= thresholds["slow_bull_review"]
                else []
            ),
        },
        {
            "dimension": "fast_bull_breakout",
            "score": scores["fast_bull_breakout"],
            "cap": (
                0.0
                if scores["fast_bull_breakout"] >= thresholds["breakout_kill"]
                else 0.10
                if scores["fast_bull_breakout"] >= thresholds["breakout_review"]
                else 1.0
            ),
            "active": scores["fast_bull_breakout"] >= thresholds["breakout_review"],
            "kill": scores["fast_bull_breakout"] >= thresholds["breakout_kill"],
            "priority": 1,
            "reason_codes": (
                ["BREAKOUT_KILL"]
                if scores["fast_bull_breakout"] >= thresholds["breakout_kill"]
                else ["BREAKOUT_REVIEW_CAP"]
                if scores["fast_bull_breakout"] >= thresholds["breakout_review"]
                else []
            ),
        },
        {
            "dimension": "event",
            "score": scores["event"],
            "cap": (
                0.0
                if scores["event"] >= thresholds["event_kill"]
                else 0.15
                if scores["event"] >= thresholds["event_review"]
                else 1.0
            ),
            "active": scores["event"] >= thresholds["event_review"],
            "kill": scores["event"] >= thresholds["event_kill"],
            "priority": 2,
            "reason_codes": (
                ["EVENT_KILL"]
                if scores["event"] >= thresholds["event_kill"]
                else ["EVENT_REVIEW_CAP"]
                if scores["event"] >= thresholds["event_review"]
                else []
            ),
        },
        {
            "dimension": "volatility_stress",
            "score": scores["volatility_stress"],
            "cap": volatility_cap["cap"],
            "active": volatility_cap["cap"] < 1.0,
            "kill": volatility_cap["cap"] == 0.0,
            "priority": 3,
            "reason_codes": volatility_cap["reason_codes"],
        },
        {
            "dimension": "data_quality",
            "score": scores["data_quality"],
            "cap": 0.0 if scores["data_quality"] >= thresholds["data_quality_kill"] else 1.0,
            "active": scores["data_quality"] >= thresholds["data_quality_kill"],
            "kill": scores["data_quality"] >= thresholds["data_quality_kill"],
            "priority": 0,
            "reason_codes": (
                ["DATA_QUALITY_KILL"]
                if scores["data_quality"] >= thresholds["data_quality_kill"]
                else []
            ),
        },
    ]


def _volatility_cap(volatility_stress_score: float) -> dict[str, Any]:
    thresholds = DEFAULT_REGIME_THRESHOLDS
    if volatility_stress_score >= thresholds["volatility_cap_98"]:
        return {"cap": 0.0, "reason_codes": ["VOLATILITY_CAP_0"]}
    if volatility_stress_score >= thresholds["volatility_cap_95"]:
        return {"cap": 0.20, "reason_codes": ["VOLATILITY_CAP_20"]}
    if volatility_stress_score >= thresholds["volatility_cap_80"]:
        return {"cap": 0.40, "reason_codes": ["VOLATILITY_CAP_40"]}
    if volatility_stress_score >= thresholds["volatility_cap_60"]:
        return {"cap": 0.65, "reason_codes": ["VOLATILITY_CAP_65"]}
    return {"cap": 1.0, "reason_codes": []}


def _primary_regime_label(scores: dict[str, float]) -> str:
    key = max(_PRIMARY_LABELS, key=lambda name: scores[name])
    return _PRIMARY_LABELS[key]


def _clamp01(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
