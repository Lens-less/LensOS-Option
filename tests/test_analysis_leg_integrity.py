"""Canonical legs must survive the typed seam without changing exposure."""

from copy import deepcopy

import pytest
import test_analysis_run_contract as scenarios

from crypto_options_report.analysis_run import AnalysisRequest, AnalysisRun
from crypto_options_report.contract import generate_research_report


def _evaluate_with_legs(mutate):
    helper = scenarios.AnalysisRunContractTests()
    snapshot = helper._trusted_snapshot()
    report = generate_research_report(
        generated_at=scenarios.FIXED_CLOCK, market_snapshot=snapshot,
    )
    candidate = deepcopy(report["candidate_research"]["call_credit_spreads"]["eligible"][0])
    mutate(candidate["structure_legs"])
    report["candidate_research"] = {"call_credit_spreads": {"eligible": [candidate]}}
    request = AnalysisRequest.from_projection(
        evaluation_clock=scenarios.FIXED_CLOCK,
        report_projection=report,
        market_snapshot=snapshot,
        market_evidence=helper._trusted_market_evidence(snapshot),
    )
    return AnalysisRun().evaluate(request)


def test_non_unit_canonical_quantities_are_preserved_in_typed_legs():
    def double_quantity(legs):
        for leg in legs:
            leg["quantity"] *= 2

    record = _evaluate_with_legs(double_quantity)
    baseline = _evaluate_with_legs(lambda legs: None)
    assert record.strategy_plans
    assert [leg.quantity_ratio for leg in record.strategy_plans[0].legs] == [2.0, 2.0]
    assert record.strategy_plans[0].bid_ask_cost.amount == 2 * baseline.strategy_plans[0].bid_ask_cost.amount
    assert all(decision.execution_allowed is False for decision in record.entry_admission_decisions)


@pytest.mark.parametrize("strike", [None, "not-a-strike", -1.0, 0.0, True])
def test_malformed_leg_is_never_silently_removed_from_a_strategy(strike):
    record = _evaluate_with_legs(lambda legs: legs[1].update(strike=strike))
    assert not record.strategy_plans
    assert all(decision.execution_allowed is False for decision in record.entry_admission_decisions)


def test_unbounded_ratio_is_never_labeled_as_defined_risk():
    def enlarge_short(legs):
        for leg in legs:
            if leg["quantity"] < 0:
                leg["quantity"] *= 2

    record = _evaluate_with_legs(enlarge_short)
    assert not record.strategy_plans
