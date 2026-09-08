"""Public analysis regressions captured before extracting admission groups.

The shared contract scenarios construct authenticated *test* evidence and enter
through AnalysisRun.evaluate; they do not contact an account or a trading venue.
The digest excludes build/run identity and binds every ordered audit field,
decision status, reason code, and veto source instead.
"""

import copy
from dataclasses import replace

import pytest
import test_analysis_run_contract as contract_scenarios

from crypto_options_report.admission_conditions import build_admission_conditions
from crypto_options_report.analysis_run import (
    ConditionStatus,
    ExchangeHealthState,
    PolicyCatalog,
    PreEntryRiskClaim,
    PreEntryRiskState,
    build_analysis_record,
    canonical_sha256,
)

CONDITION_ORDER = (
    "snapshot_trusted",
    "coverage_complete",
    "legs_synchronized",
    "legs_fresh",
    "no_gap_or_resync",
    "explicit_units",
    "explicit_settlement",
    "quotes_valid",
    "detector_allowed",
    "defined_risk_policy",
    "pricing_checks",
    "fair_interval_available",
    "model_promoted_if_required",
    "opportunity_not_expired",
    "invalidation_clear",
    "net_premium_finite",
    "spread_and_fee_known",
    "slippage_reserve_known",
    "depth_impact_known",
    "legging_reserve_known",
    "hedge_reserve_known",
    "uncertainty_reserve_known",
    "economic_dimensions_consistent",
    "conservative_net_edge_positive",
    "capital_at_risk_proxy_positive",
    "edge_to_capital_at_risk_positive",
    "cost_coverage",
    "spread_ratio",
    "depth",
    "open_interest",
    "quote_age",
    "research_capacity",
    "settlement_window",
    "major_event_gate",
    "exchange_health",
    "data_source_health",
    "policy_kill_switch",
    "account_evidence",
    "venue_margin_simulation",
    "portfolio_veto",
)


@pytest.mark.parametrize(
    ("overrides", "expected_status", "expected_digest"),
    [
        ({}, "CONDITIONALLY_ELIGIBLE", "2ffcac5a8bc97d688300698ead8df08ba0c29d1175753c66329443150d14a22e"),
        ({"omit_cost": "hedge_reserve"}, "DEFERRED", "6595145dd38ceac90e493d8cc45410b8a6533572ce11f808cfa4f28d54173a00"),
        ({"conservative_net_edge": 0.001}, "DEFERRED", "06605b8cb093ba870d6a0689f801d24c1240a3a53d24aa0df1901cd0e3886916"),
        (
            {
                "portfolio_action": "reduce_only",
                "event_score": 100,
                "policy_catalog": PolicyCatalog(
                    kill_switch=True,
                    settlement_window_utc=("00:00", "00:05"),
                ),
            },
            "VETOED",
            "e1643a9c9cb364fe614b54586a93e634918d9de9846ebaf0dd24d6a62985671d",
        ),
        ({"risk_observed_at": "2026-07-06T23:58:00Z"}, "DEFERRED", "a4af351bf64d9caea88a9b294ca7800273a59f3e99a18241b14010c0fb3a3492"),
        ({"promote_model": False}, "MONITOR_ONLY", "984815aa8c29f6ba011dcbe58a2890d09148ed3581ec63fa30793176983e42df"),
    ],
    ids=["eligible", "unknown-cost", "edge-covered", "ordered-vetoes", "stale-risk", "unpromoted-model"],
)
def test_public_analysis_preserves_admission_audit_payload(
    overrides, expected_status, expected_digest
):
    scenarios = contract_scenarios.AnalysisRunContractTests()
    record = scenarios._fully_evaluable_record(
        **{"portfolio_action": "allow_new", "conservative_net_edge": 0.10, **overrides}
    )
    payload = []
    for decision in record.entry_admission_decisions:
        assert tuple(item.condition_id for item in decision.conditions) == CONDITION_ORDER
        assert decision.status.value == expected_status
        assert decision.execution_allowed is False
        payload.append(
            {
                "conditions": [item.to_dict() for item in decision.conditions],
                "status": decision.status.value,
                "reason_codes": list(decision.reason_codes),
                "veto_sources": list(decision.veto_sources),
            }
        )
        claim = PreEntryRiskClaim(
            portfolio_state=(
                PreEntryRiskState.VETO
                if overrides.get("portfolio_action") == "reduce_only"
                else PreEntryRiskState.CLEAR
            ),
            exchange_health_state=ExchangeHealthState.CLEAR,
        )
        conditions, vetoes = build_admission_conditions(
            **_admission_arguments(record, decision, claim)
        )
        assert conditions == decision.conditions
        assert vetoes == decision.veto_sources
    assert payload
    assert canonical_sha256(payload) == expected_digest


def _admission_arguments(record, decision, claim):
    """Use the same public domain records with independent analysis sections."""
    projection = record.project_research_report_v1()
    evidence = {item.kind: item for item in record.evidence_lineage}
    return {
        "opportunity": next(
            item for item in record.opportunities
            if item.opportunity_id == decision.opportunity_id
        ),
        "strategy": next(
            item for item in record.strategy_plans
            if item.strategy_id == decision.strategy_id
        ),
        "market_data": projection["data_status"],
        "permission_state": projection["permission_state"],
        "account_status": projection["account_status"],
        "surface_status": projection["vol_surface_status"],
        "market_evidence": evidence["market_snapshot"],
        "account_evidence": evidence.get("account_snapshot"),
        "pre_entry_risk_claim": claim,
        "pre_entry_risk_evidence": evidence.get("pre_entry_risk_veto"),
        "policy": record.policy_bundle.catalog,
        "model_bundle": record.model_bundle,
        "evaluated_at": record.manifest.evaluation_clock,
    }


@pytest.fixture
def admission_arguments():
    scenarios = contract_scenarios.AnalysisRunContractTests()
    record = scenarios._fully_evaluable_record(
        portfolio_action="allow_new", conservative_net_edge=0.10
    )
    return _admission_arguments(
        record,
        scenarios._spread_decision(record),
        PreEntryRiskClaim(
            portfolio_state=PreEntryRiskState.CLEAR,
            exchange_health_state=ExchangeHealthState.CLEAR,
        ),
    )


@pytest.mark.parametrize(
    ("graph_complete", "events", "expected"),
    [
        (True, [], ConditionStatus.PASS),
        (True, [{"kind": "resync_pending"}], ConditionStatus.BLOCK),
        (None, [], ConditionStatus.UNKNOWN),
    ],
)
def test_market_gap_observations_preserve_three_states(
    admission_arguments, graph_complete, events, expected
):
    market = copy.deepcopy(admission_arguments["market_data"])
    market["feed_coverage"]["graph_complete"] = graph_complete
    market["adapter_events"] = events
    conditions, _ = build_admission_conditions(
        **{**admission_arguments, "market_data": market}
    )
    assert _condition(conditions, "no_gap_or_resync").status is expected


@pytest.mark.parametrize(
    "surface",
    [
        {"status": "validated"},
        {"status": "validated", "expiries": []},
        {"status": "validated", "expiries": [{}]},
        {"status": "validated", "expiries": [{"fit_quality_pass": True}]},
        {"status": "validated", "expiries": [{
            "expiry_date": "2099-01-01", "fit_quality_pass": True, "no_arb_pass": True,
        }]},
    ],
    ids=["missing-expiries", "empty-expiries", "missing-diagnostics", "missing-no-arbitrage", "unrelated-expiry"],
)
def test_pricing_cannot_pass_without_observed_surface_diagnostics(
    admission_arguments, surface
):
    conditions, _ = build_admission_conditions(
        **{**admission_arguments, "surface_status": surface}
    )
    condition = _condition(conditions, "pricing_checks")
    assert condition.status is ConditionStatus.BLOCK
    assert condition.reason_code == "PRICING_CHECKS_FAILED"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0.10, ConditionStatus.PASS), (0.0, ConditionStatus.BLOCK), (None, ConditionStatus.UNKNOWN)],
)
def test_economic_edge_preserves_positive_nonpositive_and_unknown(
    admission_arguments, amount, expected
):
    strategy = admission_arguments["strategy"]
    strategy = replace(
        strategy,
        conservative_net_edge=(
            replace(strategy.conservative_net_edge, amount=amount)
            if amount is not None else None
        ),
    )
    conditions, _ = build_admission_conditions(
        **{**admission_arguments, "strategy": strategy}
    )
    assert _condition(conditions, "conservative_net_edge_positive").status is expected


@pytest.mark.parametrize(
    ("event_score", "expected", "vetoed"),
    [(0.0, ConditionStatus.PASS, False), (100.0, ConditionStatus.BLOCK, True), (None, ConditionStatus.UNKNOWN, False)],
)
def test_operational_events_do_not_treat_missing_observation_as_clear(
    admission_arguments, event_score, expected, vetoed
):
    permission = copy.deepcopy(admission_arguments["permission_state"])
    permission["regime_scores"]["event"] = event_score
    conditions, vetoes = build_admission_conditions(
        **{**admission_arguments, "permission_state": permission}
    )
    assert _condition(conditions, "major_event_gate").status is expected
    assert ("MAJOR_EVENT_GATE_BLOCKED" in vetoes) is vetoed


@pytest.mark.parametrize(
    ("state", "expected", "vetoed"),
    [
        (PreEntryRiskState.CLEAR, ConditionStatus.PASS, False),
        (PreEntryRiskState.VETO, ConditionStatus.BLOCK, True),
        (PreEntryRiskState.UNKNOWN, ConditionStatus.UNKNOWN, False),
    ],
)
def test_portfolio_risk_preserves_clear_veto_and_unknown(
    admission_arguments, state, expected, vetoed
):
    claim = replace(admission_arguments["pre_entry_risk_claim"], portfolio_state=state)
    evidence = replace(
        admission_arguments["pre_entry_risk_evidence"],
        payload_hash=claim.payload_hash,
        payload_ref=f"sha256:{claim.payload_hash}",
    )
    conditions, vetoes = build_admission_conditions(
        **{
            **admission_arguments,
            "pre_entry_risk_claim": claim,
            "pre_entry_risk_evidence": evidence,
        }
    )
    assert _condition(conditions, "portfolio_veto").status is expected
    assert ("PORTFOLIO_VETO_ACTIVE" in vetoes) is vetoed


def _condition(conditions, condition_id):
    return next(item for item in conditions if item.condition_id == condition_id)


def test_public_build_with_untrusted_fixture_stays_reproducible_and_blocked():
    scenarios = contract_scenarios.AnalysisRunContractTests()
    arguments = {
        "generated_at": contract_scenarios.FIXED_CLOCK,
        "market_snapshot": scenarios._snapshot(),
    }
    first = build_analysis_record(**arguments)
    second = build_analysis_record(**arguments)

    assert first.output_hash == second.output_hash
    assert first.to_dict() == second.to_dict()
    assert not first.opportunities
    decision = first.entry_admission_decisions[0]
    assert decision.status.value == "BLOCKED_BY_EVIDENCE"
    assert decision.reason_codes[0] == "MARKET_EVIDENCE_NOT_TRUSTED"
    assert decision.execution_allowed is False
