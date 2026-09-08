"""Business regression at the public analysis interface during input migration."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from crypto_options_report.analysis_inputs import (
    JsonDocument,
    ReportProjectionOptions,
    compute_analysis_inputs,
)
from crypto_options_report.analysis_run import (
    AnalysisRequest,
    AnalysisRun,
    build_analysis_record,
)
from crypto_options_report.build_info import get_build_info
from crypto_options_report.market_data import load_snapshot_fixture

FIXTURE = Path(__file__).parent / "fixtures" / "deribit_btc_option_chain_snapshot.json"
GOLDEN = Path(__file__).parent / "fixtures" / "analysis_input_business_v1.json"
CLOCK = "2026-07-07T00:01:30Z"


def business_digest(value):
    """Build identity may change; all computed values and safety claims may not."""
    identity_keys = {
        "analysis_run_id",
        "decision_id",
        "brief_id",
        "event_id",
        "correlation_id",
        "output_hash",
        "manifest",
    }

    def business(item):
        if isinstance(item, dict):
            return {
                key: (
                    sorted(
                        (business(event) for event in nested),
                        key=lambda event: json.dumps(event, sort_keys=True),
                    )
                    if key == "domain_events"
                    else business(nested)
                )
                for key, nested in item.items()
                if key not in identity_keys
            }
        if isinstance(item, list):
            return [business(nested) for nested in item]
        return item

    encoded = json.dumps(
        business(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def migration_case(name):
    options = {"generated_at": CLOCK, "persist_paper_ledger": False}
    if name != "missing":
        options["market_snapshot"] = load_snapshot_fixture(FIXTURE)
    if name in {"account_green", "account_red"}:
        options["account_scenario"] = name.removeprefix("account_")
    if name == "manual_mode":
        options["mode"] = "manual_execution"
    return build_analysis_record(**options)


@pytest.mark.parametrize(
    "case", ["missing", "fixture", "account_green", "account_red", "manual_mode"]
)
def test_fixed_public_inputs_preserve_analysis_and_compatibility_values(case):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))[case]
    record = migration_case(case)
    assert business_digest(record.to_dict()) == expected["analysis"]
    assert business_digest(record.project_research_report_v1()) == expected["report"]


def test_independent_inputs_and_legacy_adapter_have_the_same_domain_result():
    snapshot = load_snapshot_fixture(FIXTURE)
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK, market_snapshot=snapshot)
    request = AnalysisRequest.from_inputs(
        evaluation_clock=CLOCK,
        analysis_inputs=inputs,
        market_snapshot=snapshot,
        report_options=ReportProjectionOptions(persist_paper_ledger=False),
    )
    independent = AnalysisRun().evaluate(request)
    report = independent.project_research_report_v1()
    report["position_management"]["compatibility_note"] = "presentation only"
    legacy = AnalysisRun().evaluate(
        AnalysisRequest.from_projection(
            evaluation_clock=CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
        )
    )
    assert independent.to_dict() == legacy.to_dict()
    assert independent.to_dict() == migration_case("fixture").to_dict()


def test_analysis_inputs_detach_both_original_observations_and_returned_views():
    snapshot = load_snapshot_fixture(FIXTURE)
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK, market_snapshot=snapshot)
    original = inputs.identity_payload()
    snapshot["rows"].clear()
    inputs.market.data.read()["status"] = "trusted"
    inputs.market.candidates.read().clear()
    assert inputs.identity_payload() == original


def test_future_opportunity_detection_is_rejected_before_evaluation():
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK)
    with pytest.raises(ValueError, match="opportunity_detected_at must not be after"):
        AnalysisRequest.from_inputs(
            evaluation_clock=CLOCK,
            analysis_inputs=inputs,
            market_snapshot=None,
            opportunity_detected_at="2026-07-07T00:01:31Z",
        )


def test_opportunity_detection_compares_instants_across_timezones():
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK)
    request = AnalysisRequest.from_inputs(
        evaluation_clock=CLOCK,
        analysis_inputs=inputs,
        market_snapshot=None,
        opportunity_detected_at="2026-07-07T08:01:30+08:00",
    )
    assert AnalysisRun().evaluate(request).trust_verdict == "missing"


@pytest.mark.parametrize(
    "updates",
    [
        {"validated": "true"},
        {"status": 1},
        {"quality_gate": []},
        {"trust_evidence": "self-certified"},
    ],
)
def test_malformed_calculated_market_inputs_are_rejected(updates):
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK)
    with pytest.raises(ValueError):
        replace(
            inputs, market=replace(inputs.market, data=JsonDocument.freeze(updates))
        )


@pytest.mark.parametrize(("field", "payload"), [
    ("trust", {"verdict": "trusted", "reason_codes": "READY"}),
    ("candidates", {"call_credit_spreads": {"eligible": "candidate"}}),
    ("candidates", {"iron_condors": {"eligible": [1]}}),
    ("surface", {"status": "validated", "expiries": {}}),
])
def test_malformed_research_collections_are_rejected_before_evaluation(field, payload):
    inputs = compute_analysis_inputs(evaluation_clock=CLOCK)
    with pytest.raises(ValueError):
        replace(inputs, market=replace(inputs.market, **{field: JsonDocument.freeze(payload)}))


def test_analysis_manifest_contains_the_loaded_build_identity():
    record = migration_case("missing")
    manifest = record.manifest.to_dict()
    assert manifest["build_info"] == get_build_info().to_dict()
    assert manifest["code_version"] == "lensos-option-pre-entry-p0.v1"
    assert manifest["build_info"]["source_digest"].startswith("sha256:")
    assert manifest["analysis_inputs_hash"] == manifest["projection_hash"]
    assert manifest["analysis_inputs_schema"] == "analysis_inputs.v1"


def test_core_and_brief_do_not_read_compatibility_runbook_paths():
    record = build_analysis_record(
        generated_at=CLOCK, manual_approval_runbook_path="\0", persist_paper_ledger=False
    )
    assert record.trust_verdict == "missing"
    assert record.project_strategy_brief_v1()["action"] == "NO_TRADE"
    # pathlib treats this malformed path as unavailable on supported runtimes;
    # requesting the compatibility view retains that fail-closed result.
    report = record.project_research_report_v1()
    assert report["paper_proposal_ledger"]["manual_approval_runbook"]["status"] == "missing"


def test_compatibility_is_read_once_on_demand_and_each_view_is_detached(tmp_path):
    runbook = tmp_path / "runbook.md"
    record = build_analysis_record(
        generated_at=CLOCK, manual_approval_runbook_path=str(runbook), persist_paper_ledger=False
    )
    # A file created after core evaluation must be visible at first projection.
    runbook.write_text("Version: example-v1\nresearch_only manual approval\n", encoding="utf-8")
    first = record.project_research_report_v1()
    evidence = first["paper_proposal_ledger"]["manual_approval_runbook"]
    assert evidence["status"] == "verified_local"
    digest = evidence["sha256"]
    runbook.unlink()
    evidence["sha256"] = "caller mutation"
    second = record.project_research_report_v1()
    assert second["paper_proposal_ledger"]["manual_approval_runbook"]["sha256"] == digest
