"""Research-only regime scoring and conservative permission caps."""

from __future__ import annotations

from math import isfinite, log
from typing import Any

from .empirical_rank import empirical_percentile
from .market_data import bound_snapshot_trust_evidence

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

MIN_ROLLING_REGIME_OBSERVATIONS = 20

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

    current_measurements = _current_market_measurements(
        market_snapshot,
        vol_surface_status,
    )
    # Handwritten scores and percentiles are not measurements. Only rolling
    # observations bound by the authenticated trust sidecar may produce ranks.
    trust_evidence = bound_snapshot_trust_evidence(market_snapshot)
    rolling_observations = _rolling_market_observations(trust_evidence)
    observation_count = len(rolling_observations)
    derived_inputs, missing_reasons = _derive_rolling_regime_inputs(
        observations=rolling_observations,
        current=current_measurements,
        trust_status=str(trust_evidence.get("status") or ""),
    )
    if derived_inputs is None:
        return _collecting_permission_state(
            reason_codes=missing_reasons,
            current_measurements=current_measurements,
            observation_count=observation_count,
        )
    raw_inputs = derived_inputs
    explicit_regime_inputs_present = False
    score_source = "rolling_evidence"
    percentile_source_override: str | None = "rolling_evidence"
    if (
        _percentile_value(
            raw_inputs,
            "atm_iv_percentile",
            aliases=("atm_iv_pct",),
        )
        is None
        or _percentile_value(
            raw_inputs,
            "dvol_percentile",
            aliases=("dvol_pct",),
        )
        is None
    ):
        return _collecting_permission_state(
            reason_codes=["REGIME_PERCENTILES_UNAVAILABLE"],
            current_measurements=current_measurements,
            observation_count=observation_count,
            primary_reason=None,
        )
    percentiles, percentile_provenance = _resolve_volatility_percentiles(
        raw_inputs,
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
        "regime_inputs_present": explicit_regime_inputs_present,
        "defaults_applied": defaults_applied,
        "percentile_source": percentile_source_override or percentile_provenance,
        "score_source": score_source,
        "observation_count": observation_count,
        "synthetic_inputs": bool(defaults_applied),
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
        "collection_status": "ready",
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
        "current_measurements": current_measurements,
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
        "collection_status": "unavailable",
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
        "current_measurements": {
            "index_price": None,
            "funding_rate": None,
            "basis_rate": None,
            "dvol": None,
            "atm_iv": None,
            "event_score": None,
        },
        "input_provenance": {
            "regime_inputs_present": False,
            "defaults_applied": [],
            "percentile_source": "unavailable",
            "score_source": "unavailable",
            "observation_count": 0,
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


def _collecting_permission_state(
    *,
    reason_codes: list[str],
    current_measurements: dict[str, float | None],
    observation_count: int,
    primary_reason: str | None = "REGIME_ROLLING_HISTORY_INSUFFICIENT",
) -> dict[str, Any]:
    codes = _unique_codes(
        ([primary_reason] if primary_reason is not None else []) + reason_codes
    )
    state = _blocked_permission_state(
        reason_codes=codes,
        account_margin_light="HALT",
        account_trade_gate="NO_TRADE",
    )
    state["collection_status"] = "collecting"
    state["primary_regime_label"] = "Collecting"
    state["current_measurements"] = current_measurements
    state["volatility_inputs"] = {
        # Numeric sentinels preserve the downstream research-report schema; the
        # explicit measurement_status prevents them being presented as ranks.
        "dvol_percentile": 0.0,
        "atm_iv_percentile": 0.0,
        "measurement_status": "collecting",
    }
    state["input_provenance"] = {
        "regime_inputs_present": False,
        "defaults_applied": [],
        "percentile_source": "collecting",
        "score_source": "collecting",
        "observation_count": observation_count,
        "required_observation_count": MIN_ROLLING_REGIME_OBSERVATIONS,
        "synthetic_inputs": False,
    }
    return state


def _current_market_measurements(
    market_snapshot: dict[str, Any],
    vol_surface_status: dict[str, Any],
) -> dict[str, float | None]:
    feeds = market_snapshot.get("feeds") or {}
    index_spot = feeds.get("index_spot") or {}
    funding_basis = feeds.get("funding_basis") or {}
    vol_index = feeds.get("vol_index") or {}
    events = feeds.get("events")
    return {
        "index_price": _numeric_value(
            index_spot,
            "index_price",
            aliases=("price",),
        ),
        "funding_rate": _numeric_value(
            funding_basis,
            "funding_rate",
            aliases=("current_funding_rate",),
        ),
        "basis_rate": _numeric_value(
            funding_basis,
            "basis_rate",
            aliases=("basis",),
        ),
        "dvol": _fraction_value(
            vol_index,
            "volatility",
            aliases=("dvol", "value"),
        ),
        "atm_iv": _current_atm_iv(vol_surface_status),
        "event_score": _exchange_event_score(events),
    }


def _rolling_market_observations(
    evidence: dict[str, Any],
) -> list[dict[str, float | None]]:
    candidates: Any = evidence.get("rolling_observations")
    if candidates is None:
        rolling = evidence.get("rolling")
        if isinstance(rolling, list):
            candidates = rolling
        elif isinstance(rolling, dict):
            candidates = (
                rolling.get("observations")
                or rolling.get("samples")
                or rolling.get("history")
            )
    if candidates is None:
        candidates = evidence.get("observations") or evidence.get("history")
    if not isinstance(candidates, list):
        return []

    normalized: list[dict[str, float | None]] = []
    for observation in candidates:
        if not isinstance(observation, dict):
            continue
        normalized.append(
            {
                "index_price": _numeric_value(
                    observation,
                    "index_price",
                    aliases=("price", "spot"),
                ),
                "dvol": _fraction_value(
                    observation,
                    "dvol",
                    aliases=("volatility", "dvol_value"),
                ),
                "atm_iv": _fraction_value(
                    observation,
                    "atm_iv",
                    aliases=("atm_iv_percent", "surface_atm_iv"),
                    declared_unit=observation.get("iv_unit"),
                ),
                "funding_rate": _numeric_value(
                    observation,
                    "funding_rate",
                    aliases=("current_funding_rate",),
                ),
                "basis_rate": _numeric_value(
                    observation,
                    "basis_rate",
                    aliases=("basis",),
                ),
            }
        )
    return normalized


def _derive_rolling_regime_inputs(
    *,
    observations: list[dict[str, float | None]],
    current: dict[str, float | None],
    trust_status: str,
) -> tuple[dict[str, float] | None, list[str]]:
    reasons: list[str] = []
    if trust_status.lower() not in {"promoted", "trusted", "pass"}:
        reasons.append("REGIME_TRUST_EVIDENCE_NOT_PROMOTED")
    if len(observations) < MIN_ROLLING_REGIME_OBSERVATIONS:
        reasons.append("REGIME_MIN_OBSERVATIONS_NOT_MET")

    required_current = (
        "index_price",
        "funding_rate",
        "basis_rate",
        "dvol",
        "atm_iv",
        "event_score",
    )
    missing_current = [key for key in required_current if current.get(key) is None]
    if missing_current:
        reasons.append("REGIME_CURRENT_FEEDS_INCOMPLETE")

    history_fields = ("index_price", "dvol", "atm_iv")
    if any(
        sum(observation.get(field) is not None for observation in observations)
        < MIN_ROLLING_REGIME_OBSERVATIONS
        for field in history_fields
    ):
        reasons.append("REGIME_ROLLING_FIELDS_INCOMPLETE")
    positive_history_fields = ("index_price", "dvol", "atm_iv")
    if any(
        observation.get(field) is not None
        and float(observation[field]) <= 0.0
        for observation in observations
        for field in positive_history_fields
    ) or any(
        current.get(field) is not None and float(current[field]) <= 0.0
        for field in positive_history_fields
    ):
        reasons.append("REGIME_ROLLING_VALUES_INVALID")
    if reasons:
        return None, reasons

    prices = [
        float(observation["index_price"])
        for observation in observations
        if observation.get("index_price") is not None
    ]
    dvol_history = [
        float(observation["dvol"])
        for observation in observations
        if observation.get("dvol") is not None
    ]
    atm_iv_history = [
        float(observation["atm_iv"])
        for observation in observations
        if observation.get("atm_iv") is not None
    ]
    current_price = float(current["index_price"])
    current_dvol = float(current["dvol"])
    current_atm_iv = float(current["atm_iv"])
    funding_rate = float(current["funding_rate"])
    basis_rate = float(current["basis_rate"])

    full_return = log(current_price / prices[0])
    recent_anchor = prices[max(0, len(prices) - 5)]
    recent_return = log(current_price / recent_anchor)
    observed_range = (max(prices + [current_price]) - min(prices + [current_price])) / current_price
    dvol_percentile = empirical_percentile(
        current=current_dvol,
        history=dvol_history,
    )
    atm_iv_percentile = empirical_percentile(
        current=current_atm_iv,
        history=atm_iv_history,
    )
    dvol_change = current_dvol - dvol_history[-1]

    positive_carry = max(basis_rate, 0.0) * 20.0 + max(funding_rate, 0.0) * 200.0
    negative_carry = max(-basis_rate, 0.0) * 20.0 + max(-funding_rate, 0.0) * 200.0
    return (
        {
            "bear_trend_score": _clamp01(max(-full_return, 0.0) * 12.0 + negative_carry),
            "range_score": _clamp01(1.0 - min(abs(full_return) * 8.0 + observed_range * 4.0, 1.0)),
            "squeeze_score": _clamp01(
                (1.0 - dvol_percentile) * 0.55
                + (1.0 - atm_iv_percentile) * 0.45
            ),
            "slow_bull_score": _clamp01(max(full_return, 0.0) * 12.0 + positive_carry),
            "fast_bull_breakout_score": _clamp01(
                max(recent_return, 0.0) * 20.0 + max(dvol_change, 0.0) * 4.0
            ),
            "event_score": _clamp01(float(current["event_score"])),
            "dvol_percentile": dvol_percentile,
            "atm_iv_percentile": atm_iv_percentile,
        },
        [],
    )


def _current_atm_iv(vol_surface_status: dict[str, Any]) -> float | None:
    points = [
        point
        for expiry in vol_surface_status.get("expiries", [])
        for point in expiry.get("surface_points", [])
        if isinstance(point.get("surface_fitted_iv"), (int, float))
        and isinstance(point.get("strike_price"), (int, float))
        and isinstance(point.get("underlying_price"), (int, float))
    ]
    if not points:
        return None
    nearest = min(
        points,
        key=lambda point: abs(float(point["strike_price"]) - float(point["underlying_price"])),
    )
    value = float(nearest["surface_fitted_iv"])
    unit = str(nearest.get("iv_unit") or "").strip().lower()
    if unit == "percent_points":
        return value / 100.0
    if unit == "fraction":
        return value
    return None


def _exchange_event_score(events: Any) -> float | None:
    if not isinstance(events, dict):
        return None
    if events.get("exchange_locked") is True:
        return 1.0
    if events.get("locked_currencies") or events.get("locked_indices"):
        return 0.8
    macro_events = events.get("macro_events")
    if isinstance(macro_events, list) and macro_events:
        severities = [
            _numeric_value(event, "severity", aliases=("score",))
            for event in macro_events
            if isinstance(event, dict)
        ]
        measured = [value for value in severities if value is not None]
        return _clamp01(max(measured)) if measured else None
    return 0.0


def _numeric_value(
    payload: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
) -> float | None:
    for key in (primary, *aliases):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if isfinite(numeric):
                return numeric
    return None


def _fraction_value(
    payload: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
    declared_unit: Any = None,
) -> float | None:
    value = _numeric_value(payload, primary, aliases=aliases)
    if value is None:
        return None
    if declared_unit not in (None, ""):
        unit = str(declared_unit).strip().lower().replace("-", "_")
        if unit in {"fraction", "decimal", "ratio"}:
            return value
        if unit in {
            "percent",
            "percentage_points",
            "percent_points",
            "pct",
            "pct_points",
        }:
            return value / 100.0
        return None
    return value / 100.0 if value > 5.0 else value


def _resolve_volatility_percentiles(
    raw_inputs: dict[str, Any],
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
    if atm_iv_percentile is None or dvol_percentile is None:
        raise ValueError("regime percentiles must be measured or derived from history")
    return (
        {
            "dvol_percentile": _clamp01(dvol_percentile),
            "atm_iv_percentile": _clamp01(atm_iv_percentile),
        },
        "measured",
    )


def _score_value_with_provenance(
    raw_inputs: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
    default: float,
) -> tuple[float, bool]:
    for key in (primary, *aliases):
        value = raw_inputs.get(key)
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            continue
        numeric = float(value)
        if isfinite(numeric):
            return _clamp01(numeric), False
    return _clamp01(default), True




def _percentile_value(
    raw_inputs: dict[str, Any],
    primary: str,
    *,
    aliases: tuple[str, ...],
) -> float | None:
    for key in (primary, *aliases):
        value = raw_inputs.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if not isfinite(numeric) or numeric < 0.0 or numeric > 100.0:
                continue
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
