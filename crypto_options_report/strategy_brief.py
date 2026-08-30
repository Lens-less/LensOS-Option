# ruff: noqa: RUF001
"""Canonical actionable strategy brief projection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from ._canonical import canonical_sha256
from .strategy_forecast import selection_binding_key_from_scope
from .strategy_history import expected_history_binding_key

STRATEGY_BRIEF_SCHEMA_VERSION = "strategy_brief.v1"
DEFAULT_BRIEF_ID_PREFIX = "brief:"
DEFAULT_RECOMMENDATION_ID_PREFIX = "recommendation:"

ACTION_STRATEGIES_AVAILABLE = "STRATEGIES_AVAILABLE"
ACTION_WATCH = "WATCH"
ACTION_NO_TRADE = "NO_TRADE"

PRICE_BASIS = "SHORT_BID_LONG_ASK"
EXPECTED_DTE_BAND_DAYS = (7.0, 35.0)
QUOTE_SYNC_MAX_SECONDS = 2.0
QUOTE_PREMIUM_UNIT = "quote_currency"
INVERSE_PREMIUM_UNIT = "inverse_base_currency"

ALLOWED_ACTIONS = {ACTION_STRATEGIES_AVAILABLE, ACTION_WATCH, ACTION_NO_TRADE}
ALLOWED_RECOMMENDATION_STATUS = {"RECOMMENDED", "WATCH"}
ALLOWED_HISTORY_STATUS = {"INSUFFICIENT", "EXPLORATORY", "VALIDATED", "FAILED"}
ALLOWED_FORECAST_STATUS = {"UNAVAILABLE", "SCREENING_ONLY", "CALIBRATED", "RETIRED"}
ALLOWED_DIRECTION = {"BEARISH", "BULLISH", "RANGE", "UNCLEAR"}
ALLOWED_VOLATILITY = {"CHEAP", "FAIR", "RICH", "UNKNOWN"}
ALLOWED_LIQUIDITY = {"EXECUTABLE", "LIMITED", "UNAVAILABLE"}
ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNAVAILABLE"}

SUPPORTED_STRUCTURES = {
    "call_credit_spread": "BEAR_CALL_CREDIT_SPREAD",
    "put_credit_spread": "BULL_PUT_CREDIT_SPREAD",
    "iron_condor": "IRON_CONDOR",
}
STRUCTURE_LABELS = {
    "BEAR_CALL_CREDIT_SPREAD": "Bear Call Credit Spread",
    "BULL_PUT_CREDIT_SPREAD": "Bull Put Credit Spread",
    "IRON_CONDOR": "Iron Condor",
}
STRUCTURE_DIRECTIONS = {
    "BEAR_CALL_CREDIT_SPREAD": "BEARISH",
    "BULL_PUT_CREDIT_SPREAD": "BULLISH",
    "IRON_CONDOR": "RANGE",
}
STRUCTURE_THESES_ZH = {
    "BEAR_CALL_CREDIT_SPREAD": "偏空且隐含波动率偏贵，卖出看涨价差并用高执行价保护上行风险。",
    "BULL_PUT_CREDIT_SPREAD": "偏多且隐含波动率偏贵，卖出看跌价差并用低执行价保护下行风险。",
    "IRON_CONDOR": "预期区间震荡且隐含波动率偏贵，同时卖出两侧价差并用保护翼限定尾部风险。",
}

USER_REASON_TEXT_ZH = {
    "HISTORICAL_EVIDENCE_INSUFFICIENT": "历史样本不足，仅供观察",
    "FORECAST_NOT_CALIBRATED": "预测胜率尚未完成校准",
    "FORECAST_SELECTION_MISMATCH": "预测证据不属于当前这张策略卡",
    "FORECAST_SELECTION_UNBOUND": "预测证据没有绑定到精确策略选择",
    "NEGATIVE_EV_AFTER_COST": "扣除成本后期望收益为负",
    "OTHER_DIRECTION_IS_POSITIVE": "当前数据更支持反方向，不建议该卖方结构",
    "NO_CAPTURABLE_EDGE_AT_TOUCH": "当前可成交价格下没有足够收益空间",
    "UNBOUNDED_LOSS_STRUCTURE": "亏损上限不明确，本版本不推荐",
    "MISSING_VALIDATED_PATH_RISK": "风险历史证据不足，暂不推荐",
    "STALE_MARKET_DATA": "行情已过期，等待刷新",
    "CROSSED_MARKET_QUOTES": "关键腿报价交叉，无法确认真实价格",
    "LEGS_NOT_SYNCHRONIZED": "多腿报价不同步，无法确认组合价格",
    "STRATEGY_EXPIRED": "策略已过期，等待下一次筛选",
    "KILL_CONDITION_HIT": "触发取消条件，当前不再成立",
    "MISSING_COST_COMPONENTS": "费用或滑点口径不完整，暂不推荐",
    "MISSING_POSITIVE_TWO_SIDED_QUOTES": "关键腿缺少正的双边报价",
    "UNIT_MISMATCH": "报价、结算或风险单位不一致",
    "ONE_UNIT_ONLY": "当前简报只支持每条腿 1 张的一单位组合",
    "MIXED_EXPIRY": "组合各腿到期日不一致",
    "DTE_OUT_OF_RANGE": "策略到期天数不在 7–35 天范围内",
    "UNSUPPORTED_STRUCTURE": "不支持的策略结构",
    "NO_ELIGIBLE_STRATEGY": "当前没有通过全部硬门禁的有限风险策略",
}

_MARKET_SURFACE = {
    "freshness_status": "UNAVAILABLE",
    "presented_as": "published",
    "source_kind": "fallback",
    "source_label": "Presentation context unavailable",
}

_EVIDENCE_ITEMS = (
    {
        "label": "市场证据",
        "status": "PASS",
        "summary_zh": "执行口径与报价同步通过硬门禁",
        "detail_zh": "组合入场使用 short bid / long ask 的冻结成本模型，不使用 mid 或 mark。",
        "artifact_id": None,
    },
    {
        "label": "历史证据",
        "status": "PASS",
        "summary_zh": "只有 VALIDATED 才显示历史胜率",
        "detail_zh": "未验证或未对齐的历史结果自动退化为状态标签。",
        "artifact_id": None,
    },
    {
        "label": "预测胜率",
        "status": "WARN",
        "summary_zh": "只有 CALIBRATED 才显示预测区间",
        "detail_zh": "未校准、过期或超出适用范围的预测不会显示概率区间。",
        "artifact_id": None,
    },
)

__all__ = [
    "STRATEGY_BRIEF_SCHEMA_VERSION",
    "build_strategy_brief",
    "validate_strategy_brief",
]


def build_strategy_brief(
    *,
    analysis_run_id: str,
    generated_at: str,
    market: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]] | None,
    history_by_candidate: Mapping[str, Mapping[str, Any]] | None = None,
    forecast_by_candidate: Mapping[str, Mapping[str, Any]] | None = None,
    policy_ttl_seconds: float | int | None = None,
) -> dict[str, Any]:
    generated_dt = _parse_timestamp(generated_at)
    generated_at = _format_timestamp(generated_dt)
    market_payload = _normalize_market(market, generated_dt, policy_ttl_seconds)
    history_lookup = history_by_candidate or {}
    forecast_lookup = forecast_by_candidate or {}
    candidate_list = list(candidates or [])

    rejection_counts: Counter[str] = Counter()
    accepted: list[dict[str, Any]] = []
    market_failures = _market_gate_failures(market_payload, generated_dt)
    if market_failures:
        for code in market_failures:
            rejection_counts[code] += max(1, len(candidate_list))
    else:
        for raw in candidate_list:
            if not isinstance(raw, Mapping):
                rejection_counts.update(["UNSUPPORTED_STRUCTURE"])
                continue
            try:
                strategy, rejection_codes = _prepare_candidate(
                    analysis_run_id=analysis_run_id,
                    generated_at=generated_dt,
                    market=market_payload,
                    candidate=raw,
                    history=history_lookup.get(str(raw.get("candidate_id") or "")),
                    forecast=forecast_lookup.get(str(raw.get("candidate_id") or "")),
                )
            except ValueError as exc:
                rejection_counts.update([str(exc)])
                continue
            rejection_counts.update(rejection_codes)
            if strategy is not None:
                accepted.append(strategy)

    accepted.sort(key=_ranking_key)
    selected: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for strategy in accepted:
        family = str(strategy["structure_type"])
        if family in seen_families:
            continue
        seen_families.add(family)
        selected.append(strategy)
        if len(selected) == 3:
            break

    for rank, strategy in enumerate(selected, start=1):
        strategy["rank"] = rank
        strategy["recommendation_id"] = _recommendation_id(strategy)

    action = _expected_action(selected)
    market_payload["action"] = action
    brief = {
        "action": action,
        "analysis_run_id": analysis_run_id,
        "brief_id": None,
        "evidence_summary": _build_evidence_summary(
            generated_at=generated_at,
            market=market_payload,
            selected=selected,
            rejection_counts=rejection_counts,
            candidate_count=len(candidate_list),
            hard_gate_pass_count=len(accepted),
        ),
        "execution_allowed": False,
        "generated_at": generated_at,
        "market": market_payload,
        "no_trade": _build_no_trade(
            action=action,
            market=market_payload,
            rejection_counts=rejection_counts,
        ),
        "research_only": True,
        "schema_version": STRATEGY_BRIEF_SCHEMA_VERSION,
        "strategies": selected,
    }
    brief["brief_id"] = _brief_id(brief)
    return brief


def validate_strategy_brief(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["strategy_brief must be a dict"]

    errors: list[str] = []
    if value.get("schema_version") != STRATEGY_BRIEF_SCHEMA_VERSION:
        errors.append("strategy_brief.schema_version must be strategy_brief.v1")
    if value.get("research_only") is not True:
        errors.append("strategy_brief.research_only must be true")
    if value.get("execution_allowed") is not False:
        errors.append("strategy_brief.execution_allowed must be false")
    if value.get("action") not in ALLOWED_ACTIONS:
        errors.append("strategy_brief.action is invalid")
    if not isinstance(value.get("brief_id"), str) or not str(value.get("brief_id")).startswith(
        DEFAULT_BRIEF_ID_PREFIX
    ):
        errors.append("strategy_brief.brief_id is invalid")
    if not isinstance(value.get("analysis_run_id"), str) or not value.get("analysis_run_id"):
        errors.append("strategy_brief.analysis_run_id is required")
    _validate_timestamp(value.get("generated_at"), "strategy_brief.generated_at", errors)

    market = value.get("market")
    if not isinstance(market, Mapping):
        errors.append("strategy_brief.market must be a dict")
    else:
        errors.extend(_validate_market(market))
        if market.get("action") != value.get("action"):
            errors.append("strategy_brief.market.action must match strategy_brief.action")

    evidence_summary = value.get("evidence_summary")
    if not isinstance(evidence_summary, Mapping):
        errors.append("strategy_brief.evidence_summary must be a dict")
    else:
        errors.extend(_validate_evidence_summary(evidence_summary))

    no_trade = value.get("no_trade")
    if not isinstance(no_trade, Mapping):
        errors.append("strategy_brief.no_trade must be a dict")
    else:
        errors.extend(_validate_no_trade(no_trade, expected_active=value.get("action") == ACTION_NO_TRADE))

    strategies = value.get("strategies")
    if not isinstance(strategies, list):
        errors.append("strategy_brief.strategies must be a list")
        strategies = []
    if len(strategies) > 3:
        errors.append("strategy_brief.strategies must contain at most 3 entries")

    seen_families: set[str] = set()
    for index, strategy in enumerate(strategies, start=1):
        if not isinstance(strategy, Mapping):
            errors.append("strategy_brief.strategies entries must be dicts")
            continue
        errors.extend(_validate_strategy(strategy, index=index))
        family = str(strategy.get("structure_type") or "")
        if family in seen_families:
            errors.append("strategy_brief.strategies must dedupe to one card per structure family")
        seen_families.add(family)
        if strategy.get("rank") != index:
            errors.append("strategy_brief.strategies ranks must be consecutive from 1")

    if value.get("action") != _expected_action(strategies):
        errors.append("strategy_brief.action does not match strategy recommendation states")
    if isinstance(evidence_summary, Mapping):
        if evidence_summary.get("selected_count") != len(strategies):
            errors.append("strategy_brief.evidence_summary.selected_count must match strategies")
        if evidence_summary.get("hard_gate_pass_count", 0) < len(strategies):
            errors.append("strategy_brief.evidence_summary.hard_gate_pass_count is inconsistent")
        recommended_count = sum(
            1
            for strategy in strategies
            if isinstance(strategy, Mapping)
            and strategy.get("recommendation_status") == "RECOMMENDED"
        )
        watch_count = sum(
            1
            for strategy in strategies
            if isinstance(strategy, Mapping)
            and strategy.get("recommendation_status") == "WATCH"
        )
        if evidence_summary.get("recommended_count") != recommended_count:
            errors.append("strategy_brief.evidence_summary.recommended_count is inconsistent")
        if evidence_summary.get("watch_count") != watch_count:
            errors.append("strategy_brief.evidence_summary.watch_count is inconsistent")
        if isinstance(market, Mapping) and evidence_summary.get(
            "default_structure_family"
        ) != _default_structure_family(market):
            errors.append("strategy_brief.evidence_summary.default_structure_family does not match market")

    expected_id = _brief_id({**dict(value), "brief_id": None})
    if value.get("brief_id") != expected_id:
        errors.append("strategy_brief.brief_id must match canonical payload hash")
    return errors


def _prepare_candidate(
    *,
    analysis_run_id: str,
    generated_at: datetime,
    market: Mapping[str, Any],
    candidate: Mapping[str, Any],
    history: Mapping[str, Any] | None,
    forecast: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidate_id = str(candidate.get("candidate_id") or "")
    raw_structure = str(candidate.get("structure_type") or "")
    structure_type = SUPPORTED_STRUCTURES.get(raw_structure)
    if not candidate_id or structure_type is None:
        return None, ["UNSUPPORTED_STRUCTURE"]

    legs, rejection = _normalize_legs(candidate, structure_type=structure_type)
    if rejection is not None:
        return None, [rejection]

    rejection_codes = _quote_gate_failures(candidate, market, generated_at, legs)
    rejection_codes.extend(_unit_evidence_failures(candidate, legs))
    rejection_codes.extend(_cost_evidence_failures(candidate))
    rejection_codes.extend(_risk_evidence_failures(candidate))
    rejection_codes.extend(_robustness_failures(candidate))

    ev_after_cost = _number(candidate.get("ev_after_cost"))
    if ev_after_cost is None and candidate.get("ev_after_cost_usdc") is not None:
        ev_after_cost = _number(candidate.get("ev_after_cost_usdc"))
    if ev_after_cost is None or ev_after_cost <= 0:
        rejection_codes.append("NEGATIVE_EV_AFTER_COST")

    if rejection_codes:
        return None, _unique_codes(rejection_codes)

    min_net_credit = _entry_credit(legs)
    if min_net_credit <= 0:
        return None, ["NEGATIVE_EV_AFTER_COST"]

    structure = _strategy_structure(structure_type, legs)
    if structure is None:
        return None, ["UNBOUNDED_LOSS_STRUCTURE"]

    strategy_as_of = max(_parse_timestamp(leg["observed_at"]) for leg in legs)
    expiry_date = structure["expiry_date"]
    valid_until = _candidate_valid_until(candidate, market=market, strategy_as_of=strategy_as_of)
    expected_scope = _expected_scope(structure_type=structure_type, strategy_as_of=strategy_as_of, expiry_date=expiry_date)
    history_projection = _normalize_history(
        history,
        expected_scope=expected_scope,
        expected_history_binding_key=expected_history_binding_key(structure_type),
    )
    forecast_projection = _normalize_forecast(
        forecast,
        expected_scope=expected_scope,
        expected_selection_binding_key=_expected_selection_binding_key(
            structure_type=structure_type,
            direction=STRUCTURE_DIRECTIONS[structure_type],
            expiry_date=expiry_date,
            legs=legs,
        ),
    )
    public_forecast_projection = {
        key: value
        for key, value in forecast_projection.items()
        if key != "_reason_codes"
    }
    recommendation_status = (
        "RECOMMENDED"
        if history_projection["status"] == "VALIDATED" or forecast_projection["status"] == "CALIBRATED"
        else "WATCH"
    )

    kill_conditions = _candidate_kill_conditions(candidate)[:2]
    normalized_path_risk_cvar_95 = _normalized_path_risk_cvar_95(candidate)
    strategy = {
        "as_of": _format_timestamp(strategy_as_of),
        "copy_recipe": _copy_recipe(
            structure_type,
            legs,
            min_net_credit,
            structure["max_loss_per_unit"],
            valid_until,
            kill_conditions,
            _settlement_currency(candidate, legs),
        ),
        "dte_days": expected_scope["dte_days"],
        "economics": {
            "absolute_ev_status": "VALIDATED",
            "ev_after_cost": round(float(ev_after_cost), 6),
            "net_r": round(float(ev_after_cost) / float(structure["max_loss_per_unit"]), 6),
            "relative_value_status": str(candidate.get("relative_value_status") or "AVAILABLE"),
        },
        "expiry_date": expiry_date,
        "entry": {
            "currency": _settlement_currency(candidate, legs),
            "fees_included": bool(candidate.get("fees_included", True)),
            "minimum_net_credit": round(float(min_net_credit), 6),
            "price_basis": PRICE_BASIS,
            "slippage_included": bool(candidate.get("slippage_included", True)),
        },
        "forecast": public_forecast_projection,
        "history": history_projection,
        "kill_conditions": kill_conditions,
        "legs": _project_legs(legs),
        "primary_reason_codes": _primary_reason_codes(history_projection, forecast_projection),
        "rank": None,
        "recommendation_status": recommendation_status,
        "risk": {
            "breakevens": [round(float(x), 6) for x in structure["breakevens"]],
            "currency": _settlement_currency(candidate, legs),
            "cvar_95": round(float(normalized_path_risk_cvar_95 or 0.0), 6),
            "max_loss_per_unit": round(float(structure["max_loss_per_unit"]), 6),
            "path_risk_status": "VALIDATED",
        },
        "structure_type": structure_type,
        "thesis_zh": STRUCTURE_THESES_ZH[structure_type],
        "valid_until": _format_timestamp(valid_until),
        "analysis_run_id": analysis_run_id,
        "candidate_id": candidate_id,
    }
    return strategy, []


def _normalize_market(
    market: Mapping[str, Any],
    generated_at: datetime,
    policy_ttl_seconds: float | int | None,
) -> dict[str, Any]:
    as_of = _parse_timestamp(market.get("as_of") or _format_timestamp(generated_at))
    ttl = 600.0 if policy_ttl_seconds is None else (_number(policy_ttl_seconds) or 0.0)
    policy_expires_at = as_of + timedelta(seconds=max(0.0, ttl))
    source_expires_at = (
        _parse_timestamp(market.get("expires_at"))
        if market.get("expires_at")
        else policy_expires_at
    )
    expires_at = min(source_expires_at, policy_expires_at)
    direction = _enum(str(market.get("direction") or "UNCLEAR"), ALLOWED_DIRECTION, "UNCLEAR")
    volatility = _enum(str(market.get("volatility") or "UNKNOWN"), ALLOWED_VOLATILITY, "UNKNOWN")
    liquidity = _enum(str(market.get("liquidity") or "UNAVAILABLE"), ALLOWED_LIQUIDITY, "UNAVAILABLE")
    confidence = _enum(str(market.get("confidence") or "UNAVAILABLE"), ALLOWED_CONFIDENCE, "UNAVAILABLE")
    return {
        "action": ACTION_NO_TRADE,
        "as_of": _format_timestamp(as_of),
        "confidence": confidence,
        "direction": direction,
        "expires_at": _format_timestamp(expires_at),
        "liquidity": liquidity,
        "summary_zh": _market_summary_zh(direction, volatility, liquidity),
        "underlying": str(market.get("underlying") or "BTC"),
        "volatility": volatility,
    }


def _market_gate_failures(
    market: Mapping[str, Any],
    evaluation_clock: datetime,
) -> list[str]:
    failures: list[str] = []
    if _parse_timestamp(market["expires_at"]) <= evaluation_clock:
        failures.append("STALE_MARKET_DATA")
    if _parse_timestamp(market["as_of"]) > evaluation_clock + timedelta(
        seconds=QUOTE_SYNC_MAX_SECONDS
    ):
        failures.append("STALE_MARKET_DATA")
    if (
        market.get("direction") == "UNCLEAR"
        or market.get("volatility") != "RICH"
        or market.get("liquidity") != "EXECUTABLE"
        or market.get("confidence") == "UNAVAILABLE"
    ):
        failures.append("NO_ELIGIBLE_STRATEGY")
    return failures


def _validate_market(market: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if market.get("action") not in ALLOWED_ACTIONS:
        errors.append("strategy_brief.market.action is invalid")
    if market.get("direction") not in ALLOWED_DIRECTION:
        errors.append("strategy_brief.market.direction is invalid")
    if market.get("volatility") not in ALLOWED_VOLATILITY:
        errors.append("strategy_brief.market.volatility is invalid")
    if market.get("liquidity") not in ALLOWED_LIQUIDITY:
        errors.append("strategy_brief.market.liquidity is invalid")
    if market.get("confidence") not in ALLOWED_CONFIDENCE:
        errors.append("strategy_brief.market.confidence is invalid")
    if not market.get("underlying"):
        errors.append("strategy_brief.market.underlying is required")
    if not market.get("summary_zh"):
        errors.append("strategy_brief.market.summary_zh is required")
    as_of = _validate_timestamp(market.get("as_of"), "strategy_brief.market.as_of", errors)
    expires_at = _validate_timestamp(
        market.get("expires_at"),
        "strategy_brief.market.expires_at",
        errors,
    )
    if as_of is not None and expires_at is not None and expires_at <= as_of:
        errors.append("strategy_brief.market.expires_at must be after as_of")
    return errors


def _validate_evidence_summary(summary: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("candidate_count", "hard_gate_pass_count", "recommended_count", "selected_count", "watch_count"):
        if not isinstance(summary.get(key), int) or summary.get(key, -1) < 0:
            errors.append(f"strategy_brief.evidence_summary.{key} must be an int")
    if not isinstance(summary.get("rejection_counts"), dict):
        errors.append("strategy_brief.evidence_summary.rejection_counts must be a dict")
    else:
        for code, count in summary["rejection_counts"].items():
            if not isinstance(code, str) or not code or not isinstance(count, int) or count <= 0:
                errors.append("strategy_brief.evidence_summary.rejection_counts is invalid")
                break
    if summary.get("default_structure_family") not in set(STRUCTURE_LABELS) | {None}:
        errors.append("strategy_brief.evidence_summary.default_structure_family is invalid")
    candidate_count = summary.get("candidate_count")
    hard_gate_pass_count = summary.get("hard_gate_pass_count")
    selected_count = summary.get("selected_count")
    if all(isinstance(value, int) for value in (candidate_count, hard_gate_pass_count, selected_count)):
        if not 0 <= selected_count <= hard_gate_pass_count <= candidate_count:
            errors.append("strategy_brief.evidence_summary counts are inconsistent")
    return errors


def _validate_no_trade(no_trade: Mapping[str, Any], *, expected_active: bool) -> list[str]:
    errors: list[str] = []
    if no_trade.get("active") is not expected_active:
        errors.append("strategy_brief.no_trade.active does not match action")
    if expected_active:
        if no_trade.get("headline_zh") != "今日暂无可靠策略":
            errors.append("strategy_brief.no_trade.headline_zh must be 今日暂无可靠策略 when active")
        if not isinstance(no_trade.get("summary_zh"), str) or not no_trade.get("summary_zh"):
            errors.append("strategy_brief.no_trade.summary_zh must be a non-empty string when active")
    else:
        if no_trade.get("headline_zh") is not None:
            errors.append("strategy_brief.no_trade.headline_zh must be null when inactive")
        if no_trade.get("summary_zh") is not None:
            errors.append("strategy_brief.no_trade.summary_zh must be null when inactive")
    reason_codes = no_trade.get("primary_reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(code, str) or not code for code in reason_codes
    ):
        errors.append("strategy_brief.no_trade.primary_reason_codes must be a string list")
    _validate_timestamp(
        no_trade.get("next_update_at"),
        "strategy_brief.no_trade.next_update_at",
        errors,
    )
    return errors


def _validate_strategy(strategy: Mapping[str, Any], *, index: int) -> list[str]:
    errors: list[str] = []
    status = strategy.get("recommendation_status")
    structure_type = strategy.get("structure_type")
    if status not in ALLOWED_RECOMMENDATION_STATUS:
        errors.append("strategy.recommendation_status is invalid")
    if structure_type not in STRUCTURE_LABELS:
        errors.append("strategy.structure_type is invalid")

    as_of = _validate_timestamp(strategy.get("as_of"), "strategy.as_of", errors)
    valid_until = _validate_timestamp(
        strategy.get("valid_until"),
        "strategy.valid_until",
        errors,
    )
    if as_of is not None and valid_until is not None and valid_until <= as_of:
        errors.append("strategy.valid_until must be after strategy.as_of")
    expiry_date = strategy.get("expiry_date")
    try:
        expiry = datetime.fromisoformat(str(expiry_date)).date()
    except ValueError:
        expiry = None
        errors.append("strategy.expiry_date is invalid")
    if not _is_positive_number(strategy.get("dte_days")):
        errors.append("strategy.dte_days must be positive")

    entry = strategy.get("entry")
    risk = strategy.get("risk")
    economics = strategy.get("economics")
    history = strategy.get("history")
    forecast = strategy.get("forecast")
    for field, item in (
        ("entry", entry),
        ("risk", risk),
        ("economics", economics),
        ("history", history),
        ("forecast", forecast),
    ):
        if not isinstance(item, Mapping):
            errors.append(f"strategy.{field} must be a dict")
    entry = entry if isinstance(entry, Mapping) else {}
    risk = risk if isinstance(risk, Mapping) else {}
    economics = economics if isinstance(economics, Mapping) else {}
    history = history if isinstance(history, Mapping) else {}
    forecast = forecast if isinstance(forecast, Mapping) else {}

    if entry.get("price_basis") != PRICE_BASIS:
        errors.append("strategy.entry.price_basis must be SHORT_BID_LONG_ASK")
    if not _is_positive_number(entry.get("minimum_net_credit")):
        errors.append("strategy.entry.minimum_net_credit must be positive")
    if entry.get("fees_included") is not True or entry.get("slippage_included") is not True:
        errors.append("strategy.entry must include frozen fees and slippage")
    if not isinstance(entry.get("currency"), str) or not entry.get("currency"):
        errors.append("strategy.entry.currency is required")

    if not _is_positive_number(risk.get("max_loss_per_unit")):
        errors.append("strategy.risk.max_loss_per_unit must be finite and positive")
    if not _is_positive_number(risk.get("cvar_95")):
        errors.append("strategy.risk.cvar_95 must be finite and positive")
    if risk.get("path_risk_status") != "VALIDATED":
        errors.append("strategy.risk.path_risk_status must be VALIDATED")
    if risk.get("currency") != entry.get("currency"):
        errors.append("strategy risk and entry currency must match")
    breakevens = risk.get("breakevens")
    if not isinstance(breakevens, list) or not breakevens or any(
        _number(value) is None for value in breakevens
    ):
        errors.append("strategy.risk.breakevens must contain finite values")

    if economics.get("absolute_ev_status") != "VALIDATED":
        errors.append("strategy.economics.absolute_ev_status must be VALIDATED")
    if not _is_positive_number(economics.get("ev_after_cost")):
        errors.append("strategy.economics.ev_after_cost must be positive")
    if not _is_positive_number(economics.get("net_r")):
        errors.append("strategy.economics.net_r must be positive")
    if not isinstance(economics.get("relative_value_status"), str) or not economics.get(
        "relative_value_status"
    ):
        errors.append("strategy.economics.relative_value_status is required")

    legs = strategy.get("legs")
    normalized_legs: list[Mapping[str, Any]] = []
    if not isinstance(legs, list) or not legs:
        errors.append("strategy.legs must be a non-empty list")
    else:
        observed_times: list[datetime] = []
        for leg_index, leg in enumerate(legs):
            if not isinstance(leg, Mapping):
                errors.append("strategy.legs entries must be dicts")
                continue
            normalized_legs.append(leg)
            if not isinstance(leg.get("instrument_name"), str) or not leg.get(
                "instrument_name"
            ):
                errors.append("strategy.leg.instrument_name is required")
            if leg.get("side") not in {"BUY", "SELL"} or leg.get("quantity") != 1.0:
                errors.append("strategy legs must use exact one-unit BUY/SELL quantities")
            if not _is_positive_number(leg.get("bid")) or not _is_positive_number(
                leg.get("ask")
            ):
                errors.append("strategy legs require positive two-sided quotes")
            elif float(leg["ask"]) < float(leg["bid"]):
                errors.append("strategy leg quotes must not be crossed")
            observed = _validate_timestamp(
                leg.get("observed_at"),
                f"strategy.legs[{leg_index}].observed_at",
                errors,
            )
            if observed is not None:
                observed_times.append(observed)
        if observed_times and (
            max(observed_times) - min(observed_times)
        ).total_seconds() > QUOTE_SYNC_MAX_SECONDS:
            errors.append("strategy legs must be synchronized within 2 seconds")
        expected_leg_count = 4 if structure_type == "IRON_CONDOR" else 2
        if len(legs) != expected_leg_count:
            errors.append("strategy leg count does not match structure")
        if structure_type in STRUCTURE_LABELS and len(normalized_legs) == len(legs):
            if not _strategy_grammar_matches(str(structure_type), normalized_legs):
                errors.append("strategy legs do not form the declared defined-risk structure")
            else:
                derived = _strategy_structure(str(structure_type), normalized_legs)
                if derived is None:
                    errors.append("strategy structure must have bounded positive max loss")
                else:
                    if abs(
                        float(entry.get("minimum_net_credit") or 0.0)
                        - _entry_credit(normalized_legs)
                    ) > 1e-6:
                        errors.append("strategy entry credit must equal short bid minus long ask")
                    if abs(
                        float(risk.get("max_loss_per_unit") or 0.0)
                        - float(derived["max_loss_per_unit"])
                    ) > 1e-6:
                        errors.append("strategy max loss must match exact legs and entry")
                    if expiry_date != derived["expiry_date"]:
                        errors.append("strategy expiry_date must match every leg")

    expected_scope = None
    if as_of is not None and expiry is not None and structure_type in STRUCTURE_LABELS:
        expected_scope = _expected_scope(
            structure_type=str(structure_type),
            strategy_as_of=as_of,
            expiry_date=str(expiry_date),
        )
    if history.get("status") == "VALIDATED":
        if (
            _probability_or_none(history.get("win_rate")) is None
            or _number(history.get("mean_net_r")) is None
            or not history.get("artifact_id")
            or expected_scope is None
            or not isinstance(history.get("scope"), Mapping)
            or not _scope_matches(history["scope"], expected_scope)
        ):
            errors.append("history metrics must be present when VALIDATED")
    else:
        if history.get("win_rate") is not None or history.get("mean_net_r") is not None:
            errors.append("history metrics must be null unless history.status is VALIDATED")
        if history.get("scope") is not None:
            errors.append("history scope must be null unless history.status is VALIDATED")
    if history.get("status") not in ALLOWED_HISTORY_STATUS:
        errors.append("history.status is invalid")
    if forecast.get("status") == "CALIBRATED":
        low = _probability_or_none(forecast.get("win_rate_low"))
        high = _probability_or_none(forecast.get("win_rate_high"))
        if (
            low is None
            or high is None
            or low > high
            or forecast.get("confidence") not in ALLOWED_CONFIDENCE - {"UNAVAILABLE"}
            or not forecast.get("artifact_id")
            or expected_scope is None
            or not isinstance(forecast.get("scope"), Mapping)
            or not _scope_matches(forecast["scope"], expected_scope)
        ):
            errors.append("forecast probabilities must be present when CALIBRATED")
    else:
        if forecast.get("win_rate_low") is not None or forecast.get("win_rate_high") is not None:
            errors.append("forecast probabilities must be null unless forecast.status is CALIBRATED")
        if forecast.get("confidence") is not None or forecast.get("scope") is not None:
            errors.append("forecast confidence and scope must be null unless CALIBRATED")
    if forecast.get("status") not in ALLOWED_FORECAST_STATUS:
        errors.append("forecast.status is invalid")
    if status == "RECOMMENDED":
        if history.get("status") != "VALIDATED" and forecast.get("status") != "CALIBRATED":
            errors.append(f"strategy_brief.strategies[{index}] RECOMMENDED requires validated history or calibrated forecast")

    kill_conditions = strategy.get("kill_conditions")
    if (
        not isinstance(kill_conditions, list)
        or not 1 <= len(kill_conditions) <= 2
        or any(not isinstance(condition, str) or not condition for condition in kill_conditions)
    ):
        errors.append("strategy.kill_conditions must contain one or two conditions")
    reason_codes = strategy.get("primary_reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(code, str) or not code for code in reason_codes
    ):
        errors.append("strategy.primary_reason_codes must be a string list")
    copy_recipe = strategy.get("copy_recipe")
    if not isinstance(copy_recipe, str) or any(
        marker not in copy_recipe
        for marker in (
            "MIN NET CREDIT:",
            "MAX LOSS PER UNIT:",
            "VALID UNTIL:",
            "CANCEL IF:",
            "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
        )
    ):
        errors.append("strategy.copy_recipe is incomplete")
    if strategy.get("recommendation_id") != _recommendation_id(strategy):
        errors.append("strategy.recommendation_id must match canonical payload hash")
    return errors


def _build_no_trade(
    *,
    action: str,
    market: Mapping[str, Any],
    rejection_counts: Counter[str],
) -> dict[str, Any]:
    if action != ACTION_NO_TRADE:
        return {
            "active": False,
            "headline_zh": None,
            "summary_zh": None,
            "primary_reason_codes": [],
            "next_update_at": market["expires_at"],
        }
    primary = [code for code, _count in rejection_counts.most_common(2)]
    if not primary:
        primary = ["NO_ELIGIBLE_STRATEGY"]
    return {
        "active": True,
        "headline_zh": "今日暂无可靠策略",
        "summary_zh": "当前没有通过全部硬门禁的有限风险策略。",
        "primary_reason_codes": primary,
        "next_update_at": market["expires_at"],
    }


def _build_evidence_summary(
    *,
    generated_at: str,
    market: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    rejection_counts: Counter[str],
    candidate_count: int,
    hard_gate_pass_count: int,
) -> dict[str, Any]:
    recommended_count = sum(1 for strategy in selected if strategy["recommendation_status"] == "RECOMMENDED")
    watch_count = sum(1 for strategy in selected if strategy["recommendation_status"] == "WATCH")
    if recommended_count:
        summary_zh = f"当前有 {recommended_count} 个有限风险策略通过推荐门槛。"
    elif watch_count:
        summary_zh = f"当前有 {watch_count} 个有限风险策略值得观察，历史或预测证据仍在积累。"
    else:
        summary_zh = "当前没有通过全部硬门禁的有限风险策略。"
    primary_reason_codes = (
        [code for code, _count in rejection_counts.most_common(2)]
        if not selected
        else _unique_codes(
            [
                code
                for strategy in selected
                for code in strategy.get("primary_reason_codes", [])
            ]
        )[:2]
    )
    items = [deepcopy(item) for item in _EVIDENCE_ITEMS]
    items[0]["status"] = "BLOCK" if _market_gate_failures(market, _parse_timestamp(generated_at)) else "PASS"
    items[1]["status"] = (
        "PASS" if any(strategy["history"]["status"] == "VALIDATED" for strategy in selected) else "WARN"
    )
    items[2]["status"] = (
        "PASS" if any(strategy["forecast"]["status"] == "CALIBRATED" for strategy in selected) else "WARN"
    )
    return {
        "as_of": generated_at,
        "candidate_count": candidate_count,
        "default_structure_family": _default_structure_family(market),
        "hard_gate_pass_count": hard_gate_pass_count,
        "items": items,
        "primary_reason_codes": primary_reason_codes,
        "recommended_count": recommended_count,
        "rejection_counts": dict(rejection_counts),
        "selected_count": len(selected),
        "summary_zh": summary_zh,
        "surface": deepcopy(_MARKET_SURFACE),
        "valid_until": market["expires_at"],
        "watch_count": watch_count,
    }


def _ranking_key(strategy: Mapping[str, Any]) -> tuple[Any, ...]:
    economics = strategy.get("economics") or {}
    risk = strategy.get("risk") or {}
    return (
        0 if strategy.get("recommendation_status") == "RECOMMENDED" else 1,
        -(_float(economics.get("net_r")) or 0.0),
        _float(risk.get("cvar_95")) or 0.0,
        _float(risk.get("max_loss_per_unit")) or 0.0,
        str(strategy.get("structure_type") or ""),
        str(strategy.get("candidate_id") or ""),
    )


def _default_structure_family(market: Mapping[str, Any]) -> str | None:
    if market.get("volatility") != "RICH":
        return None
    return {
        "BEARISH": "BEAR_CALL_CREDIT_SPREAD",
        "BULLISH": "BULL_PUT_CREDIT_SPREAD",
        "RANGE": "IRON_CONDOR",
    }.get(str(market.get("direction") or ""))


def _copy_recipe(
    structure_type: str,
    legs: Sequence[Mapping[str, Any]],
    minimum_net_credit: float,
    max_loss: float,
    valid_until: datetime,
    kill_conditions: Sequence[str],
    currency: str,
) -> str:
    label = STRUCTURE_LABELS[structure_type]
    lines = [f"STRATEGY: {label}"]
    for leg in legs:
        prefix = "SELL" if leg["side"] == "SELL" else "BUY "
        lines.append(f"{prefix} 1 {leg['instrument_name']}")
    lines.append(f"MIN NET CREDIT: {_format_amount(minimum_net_credit)} {currency}")
    lines.append(f"MAX LOSS PER UNIT: {_format_amount(max_loss)} {currency}")
    lines.append(f"VALID UNTIL: {_format_timestamp(valid_until)}")
    lines.append(f"CANCEL IF: {'; '.join(kill_conditions)}")
    lines.append("RESEARCH_ONLY / MANUAL REVIEW REQUIRED")
    return "\n".join(lines)


def _format_amount(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _recommendation_id(strategy: Mapping[str, Any]) -> str:
    return DEFAULT_RECOMMENDATION_ID_PREFIX + canonical_sha256(
        {
            "analysis_run_id": strategy.get("analysis_run_id"),
            "candidate_id": strategy.get("candidate_id"),
            "structure_type": strategy.get("structure_type"),
        }
    )


def _brief_id(brief: Mapping[str, Any]) -> str:
    payload = dict(brief)
    payload.pop("brief_id", None)
    return DEFAULT_BRIEF_ID_PREFIX + canonical_sha256(payload)


def _project_legs(legs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ask": leg["ask"],
            "bid": leg["bid"],
            "expiry_date": leg["expiry_date"],
            "instrument_name": leg["instrument_name"],
            "observed_at": leg["observed_at"],
            "option_type": leg["option_type"],
            "premium_currency": leg["premium_currency"],
            "premium_unit": leg["premium_unit"],
            "quantity": leg["quantity"],
            "side": leg["side"],
            "strike": leg["strike"],
        }
        for leg in legs
    ]


def _normalize_legs(
    candidate: Mapping[str, Any],
    *,
    structure_type: str,
) -> tuple[list[dict[str, Any]], str | None]:
    raw_legs = candidate.get("structure_legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        return [], "UNSUPPORTED_STRUCTURE"

    normalized: list[dict[str, Any]] = []
    for raw_leg in raw_legs:
        if not isinstance(raw_leg, Mapping):
            return [], "UNSUPPORTED_STRUCTURE"
        quantity = _number(raw_leg.get("quantity"))
        if quantity is None:
            return [], "UNSUPPORTED_STRUCTURE"
        if abs(quantity) != 1.0:
            return [], "ONE_UNIT_ONLY"
        premium_unit = str(raw_leg.get("premium_unit") or candidate.get("premium_unit") or "").strip().lower()
        if premium_unit != QUOTE_PREMIUM_UNIT:
            return [], "UNIT_MISMATCH"
        premium_currency = str(
            raw_leg.get("premium_currency")
            or candidate.get("premium_currency")
            or candidate.get("settlement_currency")
            or ""
        ).strip().upper()
        if not premium_currency:
            return [], "UNIT_MISMATCH"
        instrument_name = str(raw_leg.get("instrument_name") or "").strip()
        if not instrument_name:
            return [], "UNSUPPORTED_STRUCTURE"
        observed_at = raw_leg.get("observed_at") or candidate.get("observed_at")
        expiry_date = str(raw_leg.get("expiry_date") or "")
        option_type = str(raw_leg.get("option_type") or "").lower()
        strike = _finite_positive(raw_leg.get("strike"), field="leg strike")
        bid = _number(raw_leg.get("market_bid") if raw_leg.get("market_bid") is not None else raw_leg.get("bid"))
        ask = _number(raw_leg.get("market_ask") if raw_leg.get("market_ask") is not None else raw_leg.get("ask"))
        if not expiry_date:
            return [], "UNSUPPORTED_STRUCTURE"
        if not option_type or option_type not in {"call", "put"}:
            return [], "UNSUPPORTED_STRUCTURE"
        normalized.append(
            {
                "instrument_name": instrument_name,
                "option_type": option_type,
                "strike": strike,
                "quantity": 1.0,
                "signed_quantity": float(quantity),
                "side": "SELL" if float(quantity) < 0 else "BUY",
                "observed_at": _format_timestamp(_parse_timestamp(observed_at)),
                "expiry_date": expiry_date,
                "bid": bid,
                "ask": ask,
                "premium_unit": premium_unit,
                "premium_currency": premium_currency,
            }
        )

    if len({leg["expiry_date"] for leg in normalized}) != 1:
        return [], "MIXED_EXPIRY"
    if len({leg["premium_unit"] for leg in normalized}) != 1:
        return [], "UNIT_MISMATCH"
    if len({leg["premium_currency"] for leg in normalized}) != 1:
        return [], "UNIT_MISMATCH"
    if not _strategy_grammar_matches(structure_type, normalized):
        return [], "UNBOUNDED_LOSS_STRUCTURE"
    return sorted(normalized, key=_leg_sort_key), None


def _strategy_grammar_matches(structure_type: str, legs: Sequence[Mapping[str, Any]]) -> bool:
    ordered = list(legs)
    if structure_type == "BEAR_CALL_CREDIT_SPREAD":
        return (
            len(ordered) == 2
            and ordered[0]["side"] == "SELL"
            and ordered[1]["side"] == "BUY"
            and ordered[0]["option_type"] == "call"
            and ordered[1]["option_type"] == "call"
            and ordered[0]["strike"] < ordered[1]["strike"]
        )
    if structure_type == "BULL_PUT_CREDIT_SPREAD":
        return (
            len(ordered) == 2
            and ordered[0]["side"] == "SELL"
            and ordered[1]["side"] == "BUY"
            and ordered[0]["option_type"] == "put"
            and ordered[1]["option_type"] == "put"
            and ordered[0]["strike"] > ordered[1]["strike"]
        )
    if structure_type == "IRON_CONDOR":
        puts = [leg for leg in ordered if leg["option_type"] == "put"]
        calls = [leg for leg in ordered if leg["option_type"] == "call"]
        return (
            len(ordered) == 4
            and len(puts) == 2
            and len(calls) == 2
            and puts[0]["side"] == "SELL"
            and puts[1]["side"] == "BUY"
            and calls[0]["side"] == "SELL"
            and calls[1]["side"] == "BUY"
            and puts[0]["strike"] > puts[1]["strike"]
            and calls[0]["strike"] < calls[1]["strike"]
        )
    return False


def _strategy_structure(structure_type: str, legs: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if structure_type in {"BEAR_CALL_CREDIT_SPREAD", "BULL_PUT_CREDIT_SPREAD"}:
        short_leg = next((leg for leg in legs if leg["side"] == "SELL"), None)
        long_leg = next((leg for leg in legs if leg["side"] == "BUY"), None)
        if short_leg is None or long_leg is None:
            return None
        width = abs(long_leg["strike"] - short_leg["strike"])
        credit = _entry_credit(legs)
        if width <= 0 or credit <= 0:
            return None
        if structure_type == "BEAR_CALL_CREDIT_SPREAD" and not short_leg["strike"] < long_leg["strike"]:
            return None
        if structure_type == "BULL_PUT_CREDIT_SPREAD" and not short_leg["strike"] > long_leg["strike"]:
            return None
        max_loss = round(width - credit, 6)
        if max_loss <= 0:
            return None
        breakeven = round(short_leg["strike"] + credit if structure_type == "BEAR_CALL_CREDIT_SPREAD" else short_leg["strike"] - credit, 6)
        return {"expiry_date": legs[0]["expiry_date"], "breakevens": [breakeven], "max_loss_per_unit": max_loss}
    if structure_type == "IRON_CONDOR":
        puts = [leg for leg in legs if leg["option_type"] == "put"]
        calls = [leg for leg in legs if leg["option_type"] == "call"]
        if len(puts) != 2 or len(calls) != 2:
            return None
        short_put = next((leg for leg in puts if leg["side"] == "SELL"), None)
        long_put = next((leg for leg in puts if leg["side"] == "BUY"), None)
        short_call = next((leg for leg in calls if leg["side"] == "SELL"), None)
        long_call = next((leg for leg in calls if leg["side"] == "BUY"), None)
        if any(item is None for item in (short_put, long_put, short_call, long_call)):
            return None
        if not (short_put["strike"] > long_put["strike"] and short_call["strike"] < long_call["strike"]):
            return None
        put_width = short_put["strike"] - long_put["strike"]
        call_width = long_call["strike"] - short_call["strike"]
        width = max(put_width, call_width)
        credit = _entry_credit(legs)
        max_loss = round(width - credit, 6)
        if max_loss <= 0:
            return None
        return {
            "expiry_date": legs[0]["expiry_date"],
            "breakevens": [round(short_put["strike"] - credit, 6), round(short_call["strike"] + credit, 6)],
            "max_loss_per_unit": max_loss,
        }
    return None


def _entry_credit(legs: Sequence[Mapping[str, Any]]) -> float:
    short_bids = sum(float(leg["bid"]) for leg in legs if leg["side"] == "SELL")
    long_asks = sum(float(leg["ask"]) for leg in legs if leg["side"] == "BUY")
    return round(short_bids - long_asks, 6)


def _quote_gate_failures(
    candidate: Mapping[str, Any],
    market: Mapping[str, Any],
    generated_at: datetime,
    legs: Sequence[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if _parse_timestamp(market["expires_at"]) <= generated_at:
        failures.append("STALE_MARKET_DATA")
    valid_until = _candidate_valid_until(candidate, market=market, strategy_as_of=generated_at)
    if valid_until <= generated_at:
        failures.append("STRATEGY_EXPIRED")
    timestamps = [_parse_timestamp(leg["observed_at"]) for leg in legs]
    if timestamps and (max(timestamps) - min(timestamps)).total_seconds() > QUOTE_SYNC_MAX_SECONDS:
        failures.append("LEGS_NOT_SYNCHRONIZED")
    max_quote_age_seconds = _number(candidate.get("max_quote_age_seconds"))
    if max_quote_age_seconds is None:
        max_quote_age_seconds = max(
            0.0,
            (
                _parse_timestamp(market["expires_at"])
                - _parse_timestamp(market["as_of"])
            ).total_seconds(),
        )
    if timestamps:
        if (generated_at - min(timestamps)).total_seconds() > max_quote_age_seconds:
            failures.append("STALE_MARKET_DATA")
        if max(timestamps) > generated_at + timedelta(seconds=QUOTE_SYNC_MAX_SECONDS):
            failures.append("STALE_MARKET_DATA")
    for leg in legs:
        if not _is_positive_number(leg["bid"]) or not _is_positive_number(leg["ask"]):
            failures.append("MISSING_POSITIVE_TWO_SIDED_QUOTES")
            continue
        if float(leg["ask"]) < float(leg["bid"]):
            failures.append("CROSSED_MARKET_QUOTES")
    if _triggered_kill_conditions(candidate):
        failures.append("KILL_CONDITION_HIT")
    dte = _candidate_dte_days(candidate, expiry_date=str(legs[0]["expiry_date"]), strategy_as_of=max(timestamps))
    if dte is None or not _dte_in_band(dte):
        failures.append("DTE_OUT_OF_RANGE")
    return failures


def _cost_evidence_failures(candidate: Mapping[str, Any]) -> list[str]:
    required_flags = (
        "cost_components_complete",
        "fees_included",
        "slippage_included",
        "legging_included",
        "settlement_included",
    )
    if any(candidate.get(field) is not True for field in required_flags):
        return ["MISSING_COST_COMPONENTS"]
    if not candidate.get("cost_model_id") or not candidate.get("cost_config_hash"):
        return ["MISSING_COST_COMPONENTS"]
    return []


def _unit_evidence_failures(
    candidate: Mapping[str, Any],
    legs: Sequence[Mapping[str, Any]],
) -> list[str]:
    currencies = {
        str(value).strip().upper()
        for value in (
            candidate.get("premium_currency"),
            candidate.get("settlement_currency"),
            candidate.get("payoff_currency"),
            candidate.get("risk_currency"),
            *(leg.get("premium_currency") for leg in legs),
        )
        if isinstance(value, str) and value.strip()
    }
    required_currency_fields = (
        "premium_currency",
        "settlement_currency",
        "payoff_currency",
        "risk_currency",
    )
    if any(not candidate.get(field) for field in required_currency_fields):
        return ["UNIT_MISMATCH"]
    if len(currencies) != 1:
        return ["UNIT_MISMATCH"]
    return []


def _risk_evidence_failures(candidate: Mapping[str, Any]) -> list[str]:
    path_risk = candidate.get("path_risk") or {}
    if str(path_risk.get("status") or "").lower() not in {"validated_historical", "validated"}:
        return ["MISSING_VALIDATED_PATH_RISK"]
    if candidate.get("margin_known") is not True:
        return ["MISSING_VALIDATED_PATH_RISK"]
    if _normalized_path_risk_cvar_95(candidate) is None:
        return ["MISSING_VALIDATED_PATH_RISK"]
    return []


def _normalized_path_risk_cvar_95(candidate: Mapping[str, Any]) -> float | None:
    path_risk = candidate.get("path_risk")
    if not isinstance(path_risk, Mapping):
        return None

    legacy_present = "cvar_95" in path_risk
    usdc_present = "cvar_95_usdc" in path_risk
    legacy_value = _number(path_risk.get("cvar_95")) if legacy_present else None
    usdc_value = _number(path_risk.get("cvar_95_usdc")) if usdc_present else None

    if legacy_present and (legacy_value is None or legacy_value <= 0):
        return None
    if usdc_present and (usdc_value is None or usdc_value <= 0):
        return None
    if (
        legacy_present
        and usdc_present
        and abs(float(legacy_value) - float(usdc_value)) > 1e-6
    ):
        return None
    if legacy_present:
        return float(legacy_value)
    if usdc_present:
        return float(usdc_value)
    return None


def _robustness_failures(candidate: Mapping[str, Any]) -> list[str]:
    verdict = (candidate.get("robustness") or {}).get("verdict") or {}
    code = str(verdict.get("code") or "")
    if code == "other_direction_is_positive":
        return ["OTHER_DIRECTION_IS_POSITIVE"]
    if code == "no_capturable_edge_at_the_touch":
        return ["NO_CAPTURABLE_EDGE_AT_TOUCH"]
    if code != "positive_across_periods_and_execution":
        return ["MISSING_ROBUSTNESS_EVIDENCE"]
    return []


def _triggered_kill_conditions(candidate: Mapping[str, Any]) -> bool:
    conditions = candidate.get("kill_conditions")
    if not isinstance(conditions, list):
        conditions = []
    if any(isinstance(item, Mapping) and item.get("triggered") is True for item in conditions):
        return True
    return bool(candidate.get("triggered_kill_conditions"))


def _candidate_kill_conditions(candidate: Mapping[str, Any]) -> list[str]:
    conditions = candidate.get("kill_conditions")
    if not isinstance(conditions, list):
        conditions = []
    visible: list[str] = []
    for item in conditions:
        if isinstance(item, Mapping):
            text = item.get("condition") or item.get("label") or item.get("code")
            if isinstance(text, str) and text:
                visible.append(text)
        elif isinstance(item, str) and item:
            visible.append(item)
    unique = list(dict.fromkeys(visible))
    if unique:
        return unique
    return [
        "任一腿报价过期或不同步",
        "扣除成本后期望收益不再为正",
    ]


def _candidate_valid_until(
    candidate: Mapping[str, Any],
    *,
    market: Mapping[str, Any],
    strategy_as_of: datetime,
) -> datetime:
    raw = candidate.get("valid_until") or candidate.get("expires_at") or market.get("expires_at")
    candidate_expiry = _parse_timestamp(raw) if raw else strategy_as_of
    market_expiry = _parse_timestamp(market["expires_at"])
    return min(candidate_expiry, market_expiry)


def _candidate_dte_days(candidate: Mapping[str, Any], *, expiry_date: str, strategy_as_of: datetime) -> float | None:
    direct = _number(candidate.get("dte_days"))
    if direct is not None:
        return direct
    try:
        expiry = datetime.fromisoformat(expiry_date).date()
    except ValueError:
        return None
    return float((expiry - strategy_as_of.date()).days)


def _dte_in_band(value: float) -> bool:
    return EXPECTED_DTE_BAND_DAYS[0] <= value <= EXPECTED_DTE_BAND_DAYS[1]


def _expected_scope(*, structure_type: str, strategy_as_of: datetime, expiry_date: str) -> dict[str, Any]:
    return {
        "underlying": "BTC",
        "structure_type": structure_type,
        "direction": STRUCTURE_DIRECTIONS[structure_type],
        "dte_band_days": [7, 35],
        "entry_cost_basis": PRICE_BASIS,
        "exit_basis": "hold_to_expiry",
        "expiry_date": expiry_date,
        "dte_days": round(_candidate_dte_days({}, expiry_date=expiry_date, strategy_as_of=strategy_as_of) or 0.0, 6),
    }


def _normalize_history(
    history: Mapping[str, Any] | None,
    *,
    expected_scope: Mapping[str, Any],
    expected_history_binding_key: str,
) -> dict[str, Any]:
    raw = dict(history or {})
    status = str(raw.get("status") or "INSUFFICIENT").upper()
    if status not in ALLOWED_HISTORY_STATUS:
        status = "FAILED"
    actual_scope = _canonical_evidence_scope(raw)
    actual_history_binding_key = raw.get("history_binding_key")
    if status == "VALIDATED":
        if (
            raw.get("scope_verified") is not True
            or not raw.get("artifact_id")
            or actual_scope is None
            or not _scope_matches(actual_scope, expected_scope)
            or not isinstance(actual_history_binding_key, str)
            or actual_history_binding_key != expected_history_binding_key
            or _probability_or_none(raw.get("win_rate")) is None
            or _number(raw.get("mean_net_r")) is None
        ):
            status = "FAILED"
    return {
        "artifact_id": raw.get("artifact_id"),
        "exit_basis": str(raw.get("exit_basis") or "hold_to_expiry"),
        "independent_cohorts": _int_or_none(raw.get("independent_cohorts")),
        "mean_net_r": _number(raw.get("mean_net_r")) if status == "VALIDATED" else None,
        "observation_count": _int_or_none(raw.get("observation_count")),
        "scope": deepcopy(expected_scope) if status == "VALIDATED" else None,
        "status": status,
        "win_rate": _probability_or_none(raw.get("win_rate")) if status == "VALIDATED" else None,
    }


def _normalize_forecast(
    forecast: Mapping[str, Any] | None,
    *,
    expected_scope: Mapping[str, Any],
    expected_selection_binding_key: str | None,
) -> dict[str, Any]:
    raw = dict(forecast or {})
    reason_codes = _unique_codes(
        code
        for code in raw.get("reason_codes", [])
        if isinstance(code, str) and code
    )
    status = str(raw.get("status") or "UNAVAILABLE").upper()
    if status not in ALLOWED_FORECAST_STATUS:
        status = "RETIRED"
    actual_scope = _canonical_evidence_scope(raw.get("scope"))
    actual_selection_binding_key = raw.get("selection_binding_key")
    if status == "CALIBRATED":
        win_low = _probability_or_none(raw.get("win_rate_low"))
        win_high = _probability_or_none(raw.get("win_rate_high"))
        confidence = str(raw.get("confidence") or "UNAVAILABLE").upper()
        if expected_selection_binding_key is None or not isinstance(
            actual_selection_binding_key, str
        ):
            reason_codes = _unique_codes(
                [*reason_codes, "FORECAST_SELECTION_UNBOUND"]
            )
            status = "RETIRED"
        elif actual_selection_binding_key != expected_selection_binding_key:
            reason_codes = _unique_codes(
                [*reason_codes, "FORECAST_SELECTION_MISMATCH"]
            )
            status = "RETIRED"
        if (
            not raw.get("artifact_id")
            or actual_scope is None
            or not _scope_matches(actual_scope, expected_scope)
            or win_low is None
            or win_high is None
            or win_low > win_high
            or confidence not in ALLOWED_CONFIDENCE - {"UNAVAILABLE"}
        ):
            status = "RETIRED"
    if status == "CALIBRATED":
        scope = deepcopy(expected_scope)
    else:
        scope = None
        win_low = None
        win_high = None
        confidence = None
    return {
        "_reason_codes": reason_codes,
        "artifact_id": raw.get("artifact_id"),
        "confidence": confidence,
        "scope": scope,
        "status": status,
        "win_rate_high": win_high,
        "win_rate_low": win_low,
    }


def _scope_matches(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(actual.get(key) == expected.get(key) for key in ("underlying", "structure_type", "direction", "dte_band_days", "entry_cost_basis", "exit_basis"))


def _canonical_evidence_scope(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    scope = value.get("scope") if isinstance(value.get("scope"), Mapping) else value
    structure_type = scope.get("structure_type") or scope.get("structure")
    dte_band = scope.get("dte_band_days")
    if dte_band is None and isinstance(scope.get("dte"), Mapping):
        dte_band = [scope["dte"].get("min"), scope["dte"].get("max")]
    entry_basis = str(scope.get("entry_cost_basis") or "")
    if entry_basis in {
        "SHORT_BID_LONG_ASK_WITH_ADVERSE_TICK",
        "quoted_bid_ask_plus_adverse_tick_and_fees",
    }:
        entry_basis = PRICE_BASIS
    exit_basis = str(scope.get("exit_basis") or "")
    if exit_basis == "hold_to_expiry_cash_settlement":
        exit_basis = "hold_to_expiry"
    normalized = {
        "underlying": scope.get("underlying"),
        "structure_type": structure_type,
        "direction": scope.get("direction"),
        "dte_band_days": list(dte_band) if isinstance(dte_band, (list, tuple)) else None,
        "entry_cost_basis": entry_basis,
        "exit_basis": exit_basis,
    }
    if any(value is None or value == "" for value in normalized.values()):
        return None
    return normalized


def _expected_selection_binding_key(
    *,
    structure_type: str,
    direction: str,
    expiry_date: str,
    legs: Sequence[Mapping[str, Any]],
) -> str | None:
    scope = {
        "underlying": "BTC",
        "structure": structure_type,
        "direction": direction,
        "dte": {"min": 7, "max": 35},
        "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
        "exit_basis": "hold_to_expiry_cash_settlement",
        "selection": {
            "expiry_date": expiry_date,
            "legs": [
                {
                    "instrument_name": leg.get("instrument_name"),
                    "option_type": leg.get("option_type"),
                    "strike": leg.get("strike"),
                    "quantity": leg.get("signed_quantity", leg.get("quantity")),
                }
                for leg in legs
            ],
        },
    }
    return selection_binding_key_from_scope(scope)


def _primary_reason_codes(history: Mapping[str, Any], forecast: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    if history.get("status") != "VALIDATED":
        codes.append("HISTORICAL_EVIDENCE_INSUFFICIENT")
    if forecast.get("status") != "CALIBRATED":
        lifecycle_code = next(
            (
                code
                for code in forecast.get("_reason_codes", [])
                if isinstance(code, str) and code
            ),
            "FORECAST_NOT_CALIBRATED",
        )
        codes.append(lifecycle_code)
    return codes[:2]


def _market_summary_zh(direction: str, volatility: str, liquidity: str) -> str:
    direction_text = {
        "BEARISH": "偏空",
        "BULLISH": "偏多",
        "RANGE": "震荡",
        "UNCLEAR": "方向不明",
    }[direction]
    volatility_text = {
        "CHEAP": "隐含波动率偏便宜",
        "FAIR": "隐含波动率合理",
        "RICH": "隐含波动率偏贵",
        "UNKNOWN": "隐含波动率未知",
    }[volatility]
    liquidity_text = {
        "EXECUTABLE": "流动性可执行",
        "LIMITED": "流动性有限",
        "UNAVAILABLE": "流动性不可用",
    }[liquidity]
    return f"BTC: {direction_text} | {volatility_text} | {liquidity_text}"


def _enum(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _unique_codes(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _float(value: Any) -> float | None:
    return _number(value)


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _probability_or_none(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and 0.0 <= number <= 1.0 else None


def _is_positive_number(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _is_positive_or_zero_number(value: Any) -> bool:
    number = _number(value)
    return number is not None and number >= 0


def _finite_positive(value: Any, *, field: str) -> float:
    number = _number(value)
    if number is None or number <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return number


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validate_timestamp(
    value: Any,
    field: str,
    errors: list[str],
) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field} must be a timestamp with an explicit UTC offset")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be a valid timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include an explicit UTC offset")
        return None
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _settlement_currency(candidate: Mapping[str, Any], legs: Sequence[Mapping[str, Any]]) -> str:
    for value in (
        candidate.get("settlement_currency"),
        candidate.get("currency"),
        candidate.get("premium_currency"),
        legs[0].get("premium_currency") if legs else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return "USD"


def _leg_sort_key(leg: Mapping[str, Any]) -> tuple[int, int, float]:
    return (0 if leg["side"] == "SELL" else 1, 0 if leg["option_type"] == "call" else 1, float(leg["strike"]))


def _expected_action(selected: Sequence[Mapping[str, Any]]) -> str:
    if any(strategy.get("recommendation_status") == "RECOMMENDED" for strategy in selected):
        return ACTION_STRATEGIES_AVAILABLE
    return ACTION_WATCH if selected else ACTION_NO_TRADE


def _structure_label(structure_type: str) -> str:
    return STRUCTURE_LABELS[structure_type]
