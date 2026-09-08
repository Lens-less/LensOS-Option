"""Ordered, pure admission checks for one opportunity and strategy.

The interface accepts only the four analysis sections used by admission. Groups
own their observations and PASS/BLOCK/UNKNOWN decisions; their explicit order is
part of the stored analysis contract. Domain records and scalar condition helpers
remain in analysis_run and are imported when a group executes, avoiding a module
initialization cycle without duplicating their semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .analysis_run import (
        AdmissionCondition,
        EvidenceRecord,
        ModelBundleRef,
        OpportunityRecord,
        PolicyCatalog,
        PreEntryRiskClaim,
        StrategyPlan,
    )


def build_admission_conditions(
    *,
    opportunity: OpportunityRecord,
    strategy: StrategyPlan,
    market_data: Mapping[str, Any],
    permission_state: Mapping[str, Any],
    account_status: Mapping[str, Any],
    surface_status: Mapping[str, Any],
    market_evidence: EvidenceRecord,
    account_evidence: EvidenceRecord | None,
    pre_entry_risk_claim: PreEntryRiskClaim | None,
    pre_entry_risk_evidence: EvidenceRecord | None,
    policy: PolicyCatalog,
    model_bundle: ModelBundleRef,
    evaluated_at: str,
) -> tuple[tuple[AdmissionCondition, ...], tuple[str, ...]]:
    """Return all 40 audit conditions and veto reasons in contract order."""
    current_risk_claim = _current_risk_claim(
        claim=pre_entry_risk_claim,
        evidence=pre_entry_risk_evidence,
        policy=policy,
        evaluated_at=evaluated_at,
    )
    market = _market_conditions(
        strategy=strategy,
        market_data=market_data,
        market_evidence=market_evidence,
        policy=policy,
    )
    opportunity_policy = _opportunity_conditions(
        opportunity=opportunity,
        strategy=strategy,
        surface_status=surface_status,
        policy=policy,
        model_bundle=model_bundle,
        evaluated_at=evaluated_at,
    )
    economics = _economic_conditions(strategy=strategy, policy=policy)
    operational, operational_vetoes = _operational_conditions(
        permission_state=permission_state,
        market_evidence=market_evidence,
        current_risk_claim=current_risk_claim,
        policy=policy,
        evaluated_at=evaluated_at,
    )
    portfolio, portfolio_vetoes = _portfolio_conditions(
        account_status=account_status,
        account_evidence=account_evidence,
        current_risk_claim=current_risk_claim,
        policy=policy,
        evaluated_at=evaluated_at,
    )
    restricted_vetoes = (
        ("NAKED_SHORT_RESTRICTED_COMPARISON",)
        if strategy.selection_role == "restricted_comparison_only"
        else ()
    )
    # Veto priority intentionally differs from display order: portfolio first.
    return (
        (*market, *opportunity_policy, *economics, *operational, *portfolio),
        (*portfolio_vetoes, *operational_vetoes, *restricted_vetoes),
    )


def _current_risk_claim(
    *,
    claim: PreEntryRiskClaim | None,
    evidence: EvidenceRecord | None,
    policy: PolicyCatalog,
    evaluated_at: str,
) -> PreEntryRiskClaim | None:
    """Share the same freshness decision across portfolio and exchange checks."""
    from .analysis_run import EvidenceState

    if (
        evidence is not None
        and evidence.state is EvidenceState.TRUSTED
        and evidence.is_current_at(
            evaluated_at,
            max_age_seconds=policy.pre_entry_risk_max_age_seconds,
        )
    ):
        return claim
    return None


def _maximum_quote_age(strategy: StrategyPlan) -> float | None:
    quote_ages = [leg.source_quote.quote_age_seconds for leg in strategy.legs]
    return (
        max(float(item) for item in quote_ages if item is not None)
        if all(item is not None for item in quote_ages)
        else None
    )


def _market_conditions(
    *,
    strategy: StrategyPlan,
    market_data: Mapping[str, Any],
    market_evidence: EvidenceRecord,
    policy: PolicyCatalog,
) -> tuple[AdmissionCondition, ...]:
    """Market trust, coverage, quote coherence, and product units."""
    from .analysis_run import (
        AdmissionCondition,
        ConditionStatus,
        EvidenceState,
        _condition_bool,
        _condition_numeric_max,
        _parse_timestamp,
    )

    quality = market_data.get("quality_gate") or {}
    feeds = market_data.get("feed_coverage") or {}
    leg_times = [
        _parse_timestamp(leg.source_quote.observed_at, field="leg quote observed_at")
        for leg in strategy.legs
        if leg.source_quote.observed_at
    ]
    sync_delta = (
        (max(leg_times) - min(leg_times)).total_seconds()
        if len(leg_times) == len(strategy.legs)
        else None
    )
    max_quote_age = _maximum_quote_age(strategy)
    units_explicit = all(
        leg.product_economics.units_explicit for leg in strategy.legs
    )
    settlement_explicit = all(
        leg.product_economics.settlement_explicit for leg in strategy.legs
    )
    quotes_valid = all(
        leg.source_quote.bid is not None
        and leg.source_quote.ask is not None
        and leg.source_quote.bid.amount > 0
        and leg.source_quote.ask.amount >= leg.source_quote.bid.amount
        for leg in strategy.legs
    )
    gaps = [
        item
        for item in market_data.get("adapter_events") or []
        if isinstance(item, Mapping)
        and any(
            token in str(item.get("kind") or item.get("reason_code") or "").lower()
            for token in ("gap", "resync")
        )
    ]
    graph_complete = feeds.get("graph_complete")
    no_gap_status = (
        ConditionStatus.PASS
        if graph_complete is True and not gaps
        else ConditionStatus.BLOCK
        if gaps
        else ConditionStatus.UNKNOWN
    )

    conditions = (
        _condition_bool(
            "snapshot_trusted",
            market_evidence.state is EvidenceState.TRUSTED,
            observed=market_evidence.state.value,
            requirement="trusted authenticated market evidence",
            pass_code="MARKET_EVIDENCE_TRUSTED",
            block_code="MARKET_EVIDENCE_NOT_TRUSTED",
        ),
        _condition_bool(
            "coverage_complete",
            quality.get("passed") is True,
            observed=str(market_data.get("status") or "missing"),
            requirement="market quality and declared coverage pass",
            pass_code="MARKET_COVERAGE_PASSED",
            block_code="MARKET_COVERAGE_INCOMPLETE",
        ),
        _condition_numeric_max(
            "legs_synchronized",
            sync_delta,
            policy.leg_sync_window_seconds,
            reason_prefix="LEG_SYNCHRONIZATION",
        ),
        _condition_numeric_max(
            "legs_fresh",
            max_quote_age,
            policy.quote_max_age_seconds,
            reason_prefix="LEG_FRESHNESS",
        ),
        AdmissionCondition(
            condition_id="no_gap_or_resync",
            observed=(
                "gap_or_resync"
                if gaps
                else "complete"
                if graph_complete is True
                else "not_observed"
            ),
            requirement="no gap and no resync pending",
            status=no_gap_status,
            reason_code=(
                "NO_GAP_OR_RESYNC_PENDING"
                if no_gap_status is ConditionStatus.PASS
                else "MARKET_GAP_OR_RESYNC_PENDING"
                if no_gap_status is ConditionStatus.BLOCK
                else "MARKET_GAP_STATE_UNKNOWN"
            ),
        ),
        _condition_bool(
            "explicit_units",
            units_explicit,
            observed="explicit" if units_explicit else "unknown",
            requirement="premium unit, product style, and contract scale explicit",
            pass_code="PRODUCT_UNITS_EXPLICIT",
            block_code="PRODUCT_UNIT_UNKNOWN",
        ),
        _condition_bool(
            "explicit_settlement",
            settlement_explicit,
            observed="explicit" if settlement_explicit else "unknown",
            requirement="venue-explicit settlement currency",
            pass_code="SETTLEMENT_EXPLICIT",
            block_code="SETTLEMENT_UNKNOWN",
        ),
        _condition_bool(
            "quotes_valid",
            quotes_valid,
            observed="valid" if quotes_valid else "crossed_empty_or_missing",
            requirement="positive non-crossed bid and ask for every leg",
            pass_code="LEG_QUOTES_VALID",
            block_code="LEG_QUOTES_INVALID",
        ),
    )
    return conditions


def _opportunity_conditions(
    *,
    opportunity: OpportunityRecord,
    strategy: StrategyPlan,
    surface_status: Mapping[str, Any],
    policy: PolicyCatalog,
    model_bundle: ModelBundleRef,
    evaluated_at: str,
) -> tuple[AdmissionCondition, ...]:
    """Detector policy, pricing evidence, model promotion, and lifetime."""
    from .analysis_run import (
        AdmissionCondition,
        ConditionStatus,
        OpportunityStatus,
        _condition_bool,
        _condition_known,
        _parse_timestamp,
    )

    model_required = opportunity.edge_class.value in policy.model_required_edge_classes
    model_pass = not model_required or model_bundle.promoted_for
    expired = _parse_timestamp(
        opportunity.valid_until,
        field="opportunity valid_until",
    ) <= _parse_timestamp(evaluated_at, field="evaluated_at")
    invalidated = opportunity.status is OpportunityStatus.INVALIDATED
    expiries = surface_status.get("expiries")
    pricing_passed = (
        surface_status.get("status") == "validated"
        and isinstance(expiries, list)
        and bool(expiries)
        and all(
            isinstance(item, Mapping)
            and item.get("fit_quality_pass") is True
            and item.get("no_arb_pass") is True
            for item in expiries
        )
        and all(
            any(item.get("expiry_date") == leg.expiry for item in expiries)
            for leg in strategy.legs
        )
    )

    conditions = (
        _condition_bool(
            "detector_allowed",
            f"{opportunity.detector_id}:{opportunity.detector_version}"
            in policy.allowed_detectors,
            observed=f"{opportunity.detector_id}:{opportunity.detector_version}",
            requirement="detector is allowed by the policy catalog",
            pass_code="DETECTOR_ALLOWED",
            block_code="DETECTOR_NOT_ALLOWED",
        ),
        AdmissionCondition(
            condition_id="defined_risk_policy",
            observed=strategy.selection_role,
            requirement="only the primary defined-risk expression may be admitted",
            status=(
                ConditionStatus.PASS
                if strategy.selection_role == "primary_defined_risk_expression"
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "DEFINED_RISK_POLICY_PASSED"
                if strategy.selection_role == "primary_defined_risk_expression"
                else "NAKED_SHORT_RESTRICTED_COMPARISON"
            ),
        ),
        _condition_bool(
            "pricing_checks",
            pricing_passed,
            observed=str(
                surface_status.get("status")
                or "missing"
            ),
            requirement="surface fit and no-arbitrage diagnostics pass",
            pass_code="PRICING_CHECKS_PASSED",
            block_code="PRICING_CHECKS_FAILED",
        ),
        _condition_known(
            "fair_interval_available",
            opportunity.fair_interval is not None,
            observed="available" if opportunity.fair_interval else None,
            requirement="typed fair-value interval available",
            pass_code="FAIR_INTERVAL_AVAILABLE",
            unknown_code="FAIR_INTERVAL_UNAVAILABLE",
        ),
        _condition_bool(
            "model_promoted_if_required",
            model_pass,
            observed=model_bundle.promotion_status,
            requirement=(
                "promoted model required for E2/E3"
                if model_required
                else "no promoted model required for E1"
            ),
            pass_code="MODEL_REQUIREMENT_PASSED",
            block_code="E3_MODEL_NOT_PROMOTED",
        ),
        _condition_bool(
            "opportunity_not_expired",
            not expired,
            observed=opportunity.valid_until,
            requirement=f"valid after {evaluated_at}",
            pass_code="OPPORTUNITY_TTL_VALID",
            block_code="OPPORTUNITY_EXPIRED",
        ),
        _condition_bool(
            "invalidation_clear",
            not invalidated,
            observed=opportunity.status.value,
            requirement="no invalidation condition triggered",
            pass_code="OPPORTUNITY_INVALIDATION_CLEAR",
            block_code="OPPORTUNITY_INVALIDATED",
        ),
    )
    return conditions


def _economic_conditions(
    *,
    strategy: StrategyPlan,
    policy: PolicyCatalog,
) -> tuple[AdmissionCondition, ...]:
    """Typed cost completeness, conservative edge, and liquidity capacity."""
    from .analysis_run import (
        AdmissionCondition,
        ConditionStatus,
        _condition_collection_max,
        _condition_collection_min,
        _condition_cost_coverage,
        _condition_known,
        _condition_known_numeric_positive,
        _condition_numeric_max,
        _economic_dimensions_consistent,
    )

    max_quote_age = _maximum_quote_age(strategy)
    costs = (
        strategy.bid_ask_cost,
        strategy.fee,
        strategy.slippage_reserve,
        strategy.depth_impact,
        strategy.legging_reserve,
        strategy.hedge_reserve,
        strategy.model_uncertainty_reserve,
    )
    conservative_edge = strategy.conservative_net_edge
    economic_dimensions_known = all(
        item is not None and item.contract_scale is not None
        for item in (*costs, conservative_edge)
    )
    economic_dimensions_consistent = _economic_dimensions_consistent(
        (*costs, conservative_edge)
    )
    costs_nonnegative = all(
        item is not None and item.amount >= 0 for item in costs
    )
    costs_known = (
        all(item is not None for item in costs)
        and economic_dimensions_consistent
        and costs_nonnegative
    )
    total_cost = (
        sum(float(item.amount) for item in costs if item is not None)
        if costs_known
        else None
    )
    spread_ratios = [
        leg.source_quote.spread_ratio for leg in strategy.legs
    ]
    depths = [leg.source_quote.depth for leg in strategy.legs]
    open_interests = [leg.source_quote.open_interest for leg in strategy.legs]

    conditions = (
        _condition_known(
            "net_premium_finite",
            strategy.net_premium is not None,
            observed=(
                strategy.net_premium.amount if strategy.net_premium else None
            ),
            requirement="finite typed net credit or debit",
            pass_code="NET_PREMIUM_FINITE",
            unknown_code="NET_PREMIUM_UNKNOWN",
        ),
        _condition_known(
            "spread_and_fee_known",
            strategy.bid_ask_cost is not None and strategy.fee is not None,
            observed=(
                "known"
                if strategy.bid_ask_cost is not None and strategy.fee is not None
                else None
            ),
            requirement="bid/ask cost and fee explicitly known",
            pass_code="SPREAD_AND_FEE_KNOWN",
            unknown_code="SPREAD_OR_FEE_UNKNOWN",
        ),
        _condition_known(
            "slippage_reserve_known",
            strategy.slippage_reserve is not None,
            observed=(
                strategy.slippage_reserve.amount
                if strategy.slippage_reserve
                else None
            ),
            requirement="slippage reserve explicitly known",
            pass_code="SLIPPAGE_RESERVE_KNOWN",
            unknown_code="SLIPPAGE_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "depth_impact_known",
            strategy.depth_impact is not None,
            observed=(
                strategy.depth_impact.amount if strategy.depth_impact else None
            ),
            requirement="depth impact explicitly known",
            pass_code="DEPTH_IMPACT_KNOWN",
            unknown_code="DEPTH_IMPACT_UNKNOWN",
        ),
        _condition_known(
            "legging_reserve_known",
            strategy.legging_reserve is not None,
            observed=(
                strategy.legging_reserve.amount
                if strategy.legging_reserve
                else None
            ),
            requirement="legging reserve explicitly known",
            pass_code="LEGGING_RESERVE_KNOWN",
            unknown_code="LEGGING_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "hedge_reserve_known",
            strategy.hedge_reserve is not None,
            observed=(
                strategy.hedge_reserve.amount
                if strategy.hedge_reserve
                else None
            ),
            requirement="hedge reserve explicitly known",
            pass_code="HEDGE_RESERVE_KNOWN",
            unknown_code="HEDGE_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "uncertainty_reserve_known",
            strategy.model_uncertainty_reserve is not None,
            observed=(
                strategy.model_uncertainty_reserve.amount
                if strategy.model_uncertainty_reserve
                else None
            ),
            requirement="model uncertainty reserve explicitly known",
            pass_code="UNCERTAINTY_RESERVE_KNOWN",
            unknown_code="UNCERTAINTY_RESERVE_UNKNOWN",
        ),
        AdmissionCondition(
            condition_id="economic_dimensions_consistent",
            observed=(
                "consistent"
                if economic_dimensions_consistent
                else "missing_or_mismatched"
            ),
            requirement=(
                "edge and all cost values share currency, product type, "
                "and contract scale"
            ),
            status=(
                ConditionStatus.UNKNOWN
                if not economic_dimensions_known
                else ConditionStatus.PASS
                if economic_dimensions_consistent and costs_nonnegative
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "ECONOMIC_DIMENSIONS_UNKNOWN"
                if not economic_dimensions_known
                else "ECONOMIC_DIMENSIONS_CONSISTENT"
                if economic_dimensions_consistent and costs_nonnegative
                else "ECONOMIC_COST_INVALID"
                if economic_dimensions_consistent
                else "ECONOMIC_DIMENSIONS_MISMATCH"
            ),
        ),
        _condition_known_numeric_positive(
            "conservative_net_edge_positive",
            conservative_edge.amount if conservative_edge else None,
            requirement="conservative typed net edge greater than zero",
            pass_code="CONSERVATIVE_NET_EDGE_POSITIVE",
            block_code="CONSERVATIVE_NET_EDGE_NONPOSITIVE",
            unknown_code="CONSERVATIVE_NET_EDGE_UNKNOWN",
        ),
        _condition_known_numeric_positive(
            "capital_at_risk_proxy_positive",
            (
                strategy.capital_at_risk_proxy.amount
                if strategy.capital_at_risk_proxy
                else None
            ),
            requirement="defined-risk capital-at-risk proxy greater than zero",
            pass_code="CAPITAL_AT_RISK_PROXY_POSITIVE",
            block_code="CAPITAL_AT_RISK_PROXY_NONPOSITIVE",
            unknown_code="CAPITAL_AT_RISK_PROXY_UNKNOWN",
        ),
        _condition_known_numeric_positive(
            "edge_to_capital_at_risk_positive",
            strategy.edge_to_capital_at_risk,
            requirement="conservative edge / capital-at-risk proxy greater than zero",
            pass_code="EDGE_TO_CAPITAL_AT_RISK_POSITIVE",
            block_code="EDGE_TO_CAPITAL_AT_RISK_NONPOSITIVE",
            unknown_code="EDGE_TO_CAPITAL_AT_RISK_UNKNOWN",
        ),
        _condition_cost_coverage(
            conservative_edge=conservative_edge,
            total_cost=total_cost,
            costs_known=costs_known,
            required_ratio=policy.cost_coverage_ratio,
        ),
        _condition_collection_max(
            "spread_ratio",
            spread_ratios,
            policy.max_spread_ratio,
            reason_prefix="SPREAD_RATIO",
        ),
        _condition_collection_min(
            "depth",
            depths,
            policy.minimum_depth,
            reason_prefix="DEPTH",
        ),
        _condition_collection_min(
            "open_interest",
            open_interests,
            policy.minimum_open_interest,
            reason_prefix="OPEN_INTEREST",
        ),
        _condition_numeric_max(
            "quote_age",
            max_quote_age,
            policy.quote_max_age_seconds,
            reason_prefix="QUOTE_AGE",
        ),
        AdmissionCondition(
            condition_id="research_capacity",
            observed=strategy.research_capacity_class or "not_evaluated",
            requirement="non-actionable research capacity class available",
            status=(
                ConditionStatus.PASS
                if strategy.research_capacity_class
                else ConditionStatus.UNKNOWN
            ),
            reason_code=(
                "RESEARCH_CAPACITY_CLASS_AVAILABLE"
                if strategy.research_capacity_class
                else "RESEARCH_CAPACITY_NOT_EVALUATED"
            ),
        ),
    )
    return conditions


def _operational_conditions(
    *,
    permission_state: Mapping[str, Any],
    market_evidence: EvidenceRecord,
    current_risk_claim: PreEntryRiskClaim | None,
    policy: PolicyCatalog,
    evaluated_at: str,
) -> tuple[tuple[AdmissionCondition, ...], tuple[str, ...]]:
    """Settlement, event, exchange, data source, and kill-switch gates."""
    from .analysis_run import (
        AdmissionCondition,
        ConditionStatus,
        EvidenceState,
        ExchangeHealthState,
        _condition_bool,
        _optional_finite,
        _outside_settlement_window,
    )

    event_score = _optional_finite(
        (permission_state.get("regime_scores") or {}).get("event")
    )
    event_clear = (
        event_score is not None
        and event_score <= policy.maximum_event_score
    )
    exchange_health_state = (
        current_risk_claim.exchange_health_state
        if current_risk_claim is not None
        else ExchangeHealthState.UNKNOWN
    )
    exchange_blocked = (
        exchange_health_state.value in policy.exchange_health_blocking_states
    )
    outside_settlement = _outside_settlement_window(evaluated_at, policy)

    conditions = (
        _condition_bool(
            "settlement_window",
            outside_settlement,
            observed="outside" if outside_settlement else "inside",
            requirement=(
                "outside "
                f"{policy.settlement_window_utc[0]}-"
                f"{policy.settlement_window_utc[1]} UTC"
            ),
            pass_code="OUTSIDE_SETTLEMENT_WINDOW",
            block_code="SETTLEMENT_WINDOW_ACTIVE",
        ),
        AdmissionCondition(
            condition_id="major_event_gate",
            observed=event_score,
            requirement=(
                "event score observed and <= "
                f"{policy.maximum_event_score:g}"
            ),
            status=(
                ConditionStatus.UNKNOWN
                if event_score is None
                else ConditionStatus.PASS
                if event_clear
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "MAJOR_EVENT_GATE_UNKNOWN"
                if event_score is None
                else "MAJOR_EVENT_GATE_CLEAR"
                if event_clear
                else "MAJOR_EVENT_GATE_BLOCKED"
            ),
        ),
        AdmissionCondition(
            condition_id="exchange_health",
            observed=exchange_health_state.value,
            requirement="current typed exchange-health evidence is CLEAR",
            status=(
                ConditionStatus.UNKNOWN
                if exchange_health_state is ExchangeHealthState.UNKNOWN
                else ConditionStatus.BLOCK
                if exchange_blocked
                else ConditionStatus.PASS
            ),
            reason_code=(
                "EXCHANGE_HEALTH_UNKNOWN"
                if exchange_health_state is ExchangeHealthState.UNKNOWN
                else "EXCHANGE_HEALTH_BLOCKED"
                if exchange_blocked
                else "EXCHANGE_HEALTH_CLEAR"
            ),
        ),
        _condition_bool(
            "data_source_health",
            market_evidence.state is EvidenceState.TRUSTED,
            observed=market_evidence.state.value,
            requirement="data source remains trusted",
            pass_code="DATA_SOURCE_HEALTH_CLEAR",
            block_code="DATA_SOURCE_DEGRADED",
        ),
        _condition_bool(
            "policy_kill_switch",
            not policy.kill_switch,
            observed=policy.kill_switch,
            requirement="policy kill switch is false",
            pass_code="POLICY_KILL_SWITCH_CLEAR",
            block_code="POLICY_KILL_SWITCH_ACTIVE",
        ),
    )
    veto_sources: list[str] = []
    if policy.kill_switch:
        veto_sources.append("POLICY_KILL_SWITCH_ACTIVE")
    if not outside_settlement:
        veto_sources.append("SETTLEMENT_WINDOW_ACTIVE")
    if event_score is not None and not event_clear:
        veto_sources.append("MAJOR_EVENT_GATE_BLOCKED")
    if exchange_blocked:
        veto_sources.append("EXCHANGE_HEALTH_BLOCKED")
    return conditions, tuple(veto_sources)


def _portfolio_conditions(
    *,
    account_status: Mapping[str, Any],
    account_evidence: EvidenceRecord | None,
    current_risk_claim: PreEntryRiskClaim | None,
    policy: PolicyCatalog,
    evaluated_at: str,
) -> tuple[tuple[AdmissionCondition, ...], tuple[str, ...]]:
    """Current account evidence, venue simulation, and portfolio veto."""
    from .analysis_run import (
        AdmissionCondition,
        ConditionStatus,
        EvidenceState,
        PreEntryRiskState,
        _condition_known,
    )

    account_trusted = (
        account_evidence is not None
        and account_evidence.kind == "account_snapshot"
        and account_evidence.state is EvidenceState.TRUSTED
        and account_evidence.is_current_at(
            evaluated_at,
            max_age_seconds=policy.account_snapshot_max_age_seconds,
        )
    )
    pre_entry_risk_state = (
        current_risk_claim.portfolio_state
        if current_risk_claim is not None
        else PreEntryRiskState.UNKNOWN
    )
    portfolio_veto = (
        pre_entry_risk_state.value in policy.pre_entry_risk_veto_states
    )
    simulation_available = (
        account_trusted
        and (account_status.get("simulation_status") or {}).get("status") == "available"
        and (account_status.get("simulation_status") or {}).get("attempted") is True
    )

    conditions = (
        _condition_known(
            "account_evidence",
            account_trusted,
            observed=(
                account_evidence.state.value if account_evidence else None
            ),
            requirement="authenticated current read-only account evidence",
            pass_code="ACCOUNT_EVIDENCE_TRUSTED",
            unknown_code="ACCOUNT_EVIDENCE_MISSING_OR_UNTRUSTED",
        ),
        _condition_known(
            "venue_margin_simulation",
            simulation_available,
            observed=(
                (account_status.get("simulation_status") or {}).get("status")
                if account_trusted
                else None
            ),
            requirement="venue margin simulation attempted and available",
            pass_code="VENUE_MARGIN_SIMULATION_AVAILABLE",
            unknown_code="VENUE_MARGIN_SIMULATION_NOT_EVALUATED",
        ),
        AdmissionCondition(
            condition_id="portfolio_veto",
            observed=pre_entry_risk_state.value,
            requirement="current pre-entry portfolio risk evidence is CLEAR",
            status=(
                ConditionStatus.BLOCK
                if portfolio_veto
                else ConditionStatus.PASS
                if pre_entry_risk_state is PreEntryRiskState.CLEAR
                else ConditionStatus.UNKNOWN
            ),
            reason_code=(
                "PORTFOLIO_VETO_ACTIVE"
                if portfolio_veto
                else "PORTFOLIO_VETO_CLEAR"
                if pre_entry_risk_state is PreEntryRiskState.CLEAR
                else "PORTFOLIO_VETO_EVIDENCE_UNKNOWN"
            ),
        ),
    )
    veto_sources = ("PORTFOLIO_VETO_ACTIVE",) if portfolio_veto else ()
    return conditions, veto_sources
