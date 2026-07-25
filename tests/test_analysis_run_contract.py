import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import unittest

from crypto_options_report.analysis_run import (
    AnalysisMandate,
    AnalysisRequest,
    AnalysisRun,
    ConditionStatus,
    EntryAdmissionStatus,
    EvidenceRecord,
    EvidenceState,
    ExchangeHealthState,
    ModelBundleRef,
    OpportunityStatus,
    PolicyCatalog,
    PreEntryRiskClaim,
    PreEntryRiskState,
    build_analysis_record,
    canonical_sha256,
    validate_analysis_record,
)
from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)
from crypto_options_report.market_data import (
    load_snapshot_fixture,
    snapshot_payload_sha256,
)


FIXED_CLOCK = "2026-07-07T00:01:30Z"
FIXTURE_PATH = (
    Path(__file__).with_name("fixtures")
    / "deribit_btc_option_chain_snapshot.json"
)


class AnalysisRunContractTests(unittest.TestCase):
    def test_fixed_inputs_replay_to_the_same_manifest_run_and_output_hash(self):
        first = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
        )
        second = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
        )

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.analysis_run_id, second.analysis_run_id)
        self.assertEqual(first.output_hash, second.output_hash)
        self.assertEqual(first.output_hash, first.manifest.output_hash)
        self.assertEqual([], validate_analysis_record(first))

    def test_manifest_binds_clock_evidence_policy_model_config_and_projection(self):
        record = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
            configuration={"surface_adapter": "legacy-v1"},
        )
        manifest = record.manifest.to_dict()

        self.assertEqual(FIXED_CLOCK, manifest["evaluation_clock"])
        self.assertEqual(
            snapshot_payload_sha256(self._snapshot()),
            manifest["market_snapshot_hash"],
        )
        self.assertEqual(record.policy_bundle.policy_bundle_id, manifest["policy_bundle_id"])
        self.assertEqual(record.model_bundle.model_bundle_id, manifest["model_bundle_id"])
        self.assertTrue(manifest["configuration_hash"])
        self.assertEqual(record.output_hash, manifest["output_hash"])
        self.assertEqual(
            "research_report.v1",
            record.project_research_report_v1()["schema_version"],
        )
        self.assertEqual(
            [],
            validate_report_contract(record.project_research_report_v1()),
        )

    def test_policy_model_and_configuration_changes_change_output_identity(self):
        base = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
            configuration={"variant": "base"},
        )
        policy_changed = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
            configuration={"variant": "base"},
            policy_catalog=PolicyCatalog(opportunity_ttl_seconds=601),
        )
        model_changed = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
            configuration={"variant": "base"},
            model_bundle=ModelBundleRef.research(
                model_bundle_id="model-bundle:research-v2",
                artifact_hash="2" * 64,
            ),
        )
        config_changed = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
            configuration={"variant": "changed"},
        )

        identities = {
            (item.analysis_run_id, item.output_hash)
            for item in (base, policy_changed, model_changed, config_changed)
        }
        self.assertEqual(4, len(identities))

    def test_policy_catalog_owns_market_trust_thresholds(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=self._trusted_market_evidence(snapshot),
            policy_catalog=PolicyCatalog(
                trust_minimum_consecutive_passes=4,
            ),
        )

        record = AnalysisRun().evaluate(request)

        self.assertEqual("untrusted", record.trust_verdict)
        self.assertEqual("untrusted", record.market_analysis.status)
        self.assertIsNone(record.market_analysis.spot)
        self.assertEqual((), record.opportunities)
        self.assertIn(
            "MARKET_TRUST_THRESHOLD_NOT_MET",
            record.global_reason_codes,
        )

    def test_mandate_cannot_elevate_research_only(self):
        self.assertEqual("research_only", AnalysisMandate().effective_mode)
        for unsafe_mode in ("paper", "manual", "manual_execution", "live"):
            with self.subTest(mode=unsafe_mode):
                with self.assertRaisesRegex(ValueError, "research_only"):
                    AnalysisMandate(effective_mode=unsafe_mode)

    def test_untrusted_fixture_emits_no_opportunity_and_evidence_block(self):
        record = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
        )

        self.assertEqual("untrusted", record.trust_verdict)
        self.assertEqual((), record.opportunities)
        self.assertEqual(1, len(record.entry_admission_decisions))
        decision = record.entry_admission_decisions[0]
        self.assertEqual(
            EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
            decision.status,
        )
        self.assertIn("MARKET_EVIDENCE_NOT_TRUSTED", decision.reason_codes)
        self.assertFalse(decision.execution_allowed)

    def test_degraded_live_evidence_is_distinct_but_still_blocks_opportunity(self):
        snapshot = self._trusted_snapshot()
        record = build_analysis_record(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
        )

        self.assertEqual("degraded", record.trust_verdict)
        self.assertEqual((), record.opportunities)
        self.assertEqual(
            EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
            record.entry_admission_decisions[0].status,
        )
        self.assertIn(
            "DATA_TRUST_OBSERVATION_COLLECTING",
            record.global_reason_codes,
        )

    def test_explicit_market_evidence_cannot_override_catalog_freshness(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        digest = snapshot_payload_sha256(snapshot)
        stale_evidence = EvidenceRecord(
            evidence_id=f"market:{digest}",
            kind="market_snapshot",
            state=EvidenceState.TRUSTED,
            source=str(snapshot["source"]),
            observed_at="2026-07-06T23:59:00Z",
            received_at=FIXED_CLOCK,
            expires_at="2026-07-07T00:05:00Z",
            authenticated=True,
            payload_ref=f"sha256:{digest}",
            payload_hash=digest,
            reason_codes=(),
            trust_consecutive_passes=3,
            trust_observation_seconds=30.0,
        )
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=stale_evidence,
        )

        record = AnalysisRun().evaluate(request)

        self.assertEqual("untrusted", record.trust_verdict)
        self.assertEqual((), record.opportunities)
        self.assertIn("MARKET_EVIDENCE_STALE", record.global_reason_codes)
        self.assertEqual(
            EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
            record.entry_admission_decisions[0].status,
        )

    def test_trusted_zero_candidate_is_no_opportunity_not_data_failure(self):
        snapshot = self._trusted_snapshot()
        distorted_ivs = [58.5, 66.0, 52.0, 63.0, 49.0, 61.0, 48.0, 60.0]
        for row, mark_iv in zip(snapshot["rows"], distorted_ivs):
            row["ticker"]["mark_iv"] = mark_iv
            row["ticker"]["bid_iv"] = mark_iv - 0.5
            row["ticker"]["ask_iv"] = mark_iv + 0.5

        record = self._evaluate_with_explicit_trust(snapshot)

        self.assertEqual("trusted", record.trust_verdict)
        self.assertEqual((), record.opportunities)
        decision = record.entry_admission_decisions[0]
        self.assertEqual(EntryAdmissionStatus.NO_OPPORTUNITY, decision.status)
        self.assertIn("NO_OPPORTUNITY_DETECTED", decision.reason_codes)
        self.assertNotIn("MARKET_EVIDENCE_NOT_TRUSTED", decision.reason_codes)

    def test_current_short_vol_candidates_are_unpromoted_e3_monitor_only(self):
        record = self._evaluate_with_explicit_trust(self._trusted_snapshot())

        self.assertTrue(record.opportunities)
        self.assertTrue(record.strategy_plans)
        self.assertTrue(
            all(item.edge_class.value == "E3" for item in record.opportunities)
        )
        self.assertTrue(
            all(
                item.status is OpportunityStatus.MODEL_BLOCKED
                for item in record.opportunities
            )
        )
        self.assertTrue(
            all(
                decision.status is EntryAdmissionStatus.MONITOR_ONLY
                for decision in record.entry_admission_decisions
            )
        )
        self.assertFalse(
            any(
                plan.structure == "NAKED_SHORT_CALL"
                for plan in record.strategy_plans
            )
        )
        self.assertTrue(
            all(
                "E3_MODEL_NOT_PROMOTED" in decision.reason_codes
                for decision in record.entry_admission_decisions
            )
        )
        primary = next(
            plan
            for plan in record.strategy_plans
            if plan.structure == "CALL_CREDIT_SPREAD"
        )
        self.assertTrue(primary.why)
        self.assertTrue(primary.why_now)
        self.assertTrue(primary.why_this_structure)
        self.assertTrue(primary.rejected_alternatives)
        self.assertTrue(primary.greeks)
        self.assertTrue(primary.observable_next_step)
        for value in (
            primary.net_premium,
            primary.bid_ask_cost,
            primary.spread_width,
        ):
            self.assertIsNotNone(value)
            self.assertEqual(
                {
                    "amount",
                    "currency",
                    "kind",
                    "product_type",
                    "contract_scale",
                    "as_of",
                    "provenance",
                },
                set(value.to_dict()),
            )

    def test_unsynchronized_legs_are_explainable_and_fail_closed(self):
        snapshot = self._trusted_snapshot()
        by_name = {row["instrument_name"]: row for row in snapshot["rows"]}
        by_name["BTC-25JUL26-125000-C"]["ticker"]["timestamp"] -= 30_000

        record = self._evaluate_with_explicit_trust(
            snapshot,
            model_bundle=self._promoted_model("3"),
        )

        spread_decision = next(
            item
            for item in record.entry_admission_decisions
            if item.strategy_id
            and next(
                plan
                for plan in record.strategy_plans
                if plan.strategy_id == item.strategy_id
            ).structure == "CALL_CREDIT_SPREAD"
        )
        sync = self._condition(spread_decision, "legs_synchronized")
        self.assertEqual(ConditionStatus.BLOCK, sync.status)
        self.assertEqual("LEG_SYNCHRONIZATION_WINDOW_EXCEEDED", sync.reason_code)
        self.assertNotEqual(
            EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
            spread_decision.status,
        )

    def test_unknown_unit_and_settlement_block_before_admission(self):
        snapshot = self._trusted_snapshot()
        for row in snapshot["rows"]:
            row["summary"].pop("settlement_currency", None)

        record = self._evaluate_with_explicit_trust(snapshot)

        self.assertEqual((), record.opportunities)
        decision = record.entry_admission_decisions[0]
        self.assertEqual(
            EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
            decision.status,
        )
        self.assertTrue(
            {"MISSING_SETTLEMENT_CURRENCY", "MARKET_EVIDENCE_NOT_TRUSTED"}
            & set(decision.reason_codes)
        )

    def test_stale_future_partial_and_crossed_market_states_fail_closed(self):
        cases = {}

        stale = self._trusted_snapshot()
        stale["captured_at"] = "2026-07-06T23:58:00Z"
        cases["stale"] = stale

        future = self._trusted_snapshot()
        future["captured_at"] = "2026-07-07T00:05:00Z"
        cases["future"] = future

        partial = self._trusted_snapshot()
        partial["rows"][0]["ticker"] = None
        cases["partial"] = partial

        crossed = self._trusted_snapshot()
        for row in crossed["rows"][:3]:
            row["ticker"]["best_ask_price"] = (
                row["ticker"]["best_bid_price"] - 0.01
            )
        cases["crossed"] = crossed

        for name, snapshot in cases.items():
            with self.subTest(name=name):
                record = self._evaluate_with_explicit_trust(snapshot)
                self.assertEqual((), record.opportunities)
                self.assertEqual(
                    EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
                    record.entry_admission_decisions[0].status,
                )

    def test_opportunity_ttl_expiry_has_a_distinct_deferred_state(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        model = self._promoted_model("4")
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=self._trusted_market_evidence(snapshot),
            policy_catalog=PolicyCatalog(opportunity_ttl_seconds=1),
            model_bundle=model,
            historical_artifact=self._historical_evidence(model),
            opportunity_detected_at="2026-07-07T00:01:00Z",
        )

        record = AnalysisRun().evaluate(request)

        self.assertTrue(record.opportunities)
        self.assertTrue(
            all(
                item.status is OpportunityStatus.EXPIRED
                for item in record.opportunities
            )
        )
        self.assertTrue(
            all(
                item.status is EntryAdmissionStatus.DEFERRED
                for item in record.entry_admission_decisions
            )
        )
        self.assertTrue(
            all(
                "OPPORTUNITY_EXPIRED" in item.reason_codes
                for item in record.entry_admission_decisions
            )
        )

    def test_triggered_invalidation_is_distinct_from_expiry_and_vetoed(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        for section in ("naked_short_calls", "call_credit_spreads"):
            for candidate in report["candidate_research"][section]["eligible"]:
                candidate["analysis_invalidation_triggered"] = True
        model = self._promoted_model("6")
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=self._trusted_market_evidence(snapshot),
            model_bundle=model,
            historical_artifact=self._historical_evidence(model),
        )

        record = AnalysisRun().evaluate(request)

        self.assertTrue(
            all(
                opportunity.status is OpportunityStatus.INVALIDATED
                for opportunity in record.opportunities
            )
        )
        self.assertTrue(
            all(
                decision.status is EntryAdmissionStatus.VETOED
                for decision in record.entry_admission_decisions
            )
        )
        self.assertTrue(
            all(
                "OPPORTUNITY_INVALIDATED" in decision.reason_codes
                for decision in record.entry_admission_decisions
            )
        )

    def test_known_costs_can_pass_but_cost_covered_edge_is_deferred(self):
        passed = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
        )
        covered = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.001,
        )

        passed_spread = self._spread_decision(passed)
        covered_spread = self._spread_decision(covered)
        self.assertEqual(
            EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
            passed_spread.status,
        )
        passed_plan = next(
            plan
            for plan in passed.strategy_plans
            if plan.strategy_id == passed_spread.strategy_id
        )
        self.assertEqual("resolved_linear_defined_risk", passed_plan.payoff_status)
        self.assertIsNotNone(passed_plan.breakeven)
        self.assertIsNotNone(passed_plan.max_profit)
        self.assertIsNotNone(passed_plan.max_loss)
        self.assertIsNotNone(passed_plan.capital_at_risk_proxy)
        self.assertIsNotNone(passed_plan.edge_to_capital_at_risk)
        self.assertEqual(EntryAdmissionStatus.DEFERRED, covered_spread.status)
        self.assertEqual(
            ConditionStatus.BLOCK,
            self._condition(covered_spread, "cost_coverage").status,
        )
        self.assertIn("COST_COVERAGE_FAILED", covered_spread.reason_codes)

    def test_naked_short_call_remains_restricted_comparison_when_gates_pass(self):
        record = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
        )
        self.assertFalse(
            any(
                plan.structure == "NAKED_SHORT_CALL"
                for plan in record.strategy_plans
            )
        )
        self.assertTrue(
            all(
                any(
                    rejected.structure == "NAKED_SHORT_CALL"
                    and "UNBOUNDED_TAIL_LOSS" in rejected.reason_codes
                    for rejected in plan.rejected_alternatives
                )
                for plan in record.strategy_plans
            )
        )

    def test_observed_major_event_gate_is_block_not_unknown(self):
        record = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            event_score=0.90,
        )
        decision = self._spread_decision(record)

        self.assertEqual(EntryAdmissionStatus.VETOED, decision.status)
        event_gate = self._condition(decision, "major_event_gate")
        self.assertEqual(ConditionStatus.BLOCK, event_gate.status)
        self.assertEqual("MAJOR_EVENT_GATE_BLOCKED", event_gate.reason_code)

    def test_event_threshold_is_owned_by_policy_catalog(self):
        blocked = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            event_score=0.80,
        )
        allowed = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            event_score=0.80,
            policy_catalog=PolicyCatalog(maximum_event_score=0.90),
        )

        self.assertEqual(
            EntryAdmissionStatus.VETOED,
            self._spread_decision(blocked).status,
        )
        self.assertEqual(
            EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
            self._spread_decision(allowed).status,
        )

    def test_policy_catalog_rejects_inverted_risk_state_semantics(self):
        with self.assertRaisesRegex(ValueError, "exactly.*VETO"):
            PolicyCatalog(
                pre_entry_risk_veto_states=(PreEntryRiskState.CLEAR.value,)
            )
        with self.assertRaisesRegex(ValueError, "exactly.*BLOCKED"):
            PolicyCatalog(
                exchange_health_blocking_states=(
                    ExchangeHealthState.CLEAR.value,
                )
            )

    def test_account_evidence_must_bind_the_account_projection(self):
        with self.assertRaisesRegex(ValueError, "account evidence hash"):
            self._fully_evaluable_record(
                portfolio_action="allow_new",
                conservative_net_edge=0.10,
                account_hash_override="0" * 64,
            )

    def test_promoted_model_requires_bound_historical_oos_evidence(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        model = self._promoted_model("7")

        with self.assertRaisesRegex(ValueError, "historical OOS"):
            AnalysisRequest.from_projection(
                evaluation_clock=FIXED_CLOCK,
                report_projection=report,
                market_snapshot=snapshot,
                market_evidence=self._trusted_market_evidence(snapshot),
                model_bundle=model,
            )

    def test_promoted_model_rejects_future_expired_or_stale_oos_evidence(self):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        model = self._promoted_model("8")
        digest = model.promotion_evidence_hash

        cases = {
            "future": EvidenceRecord(
                evidence_id=f"historical:{digest}:future",
                kind="historical_oos_promotion_artifact",
                state=EvidenceState.TRUSTED,
                source="licensed_historical_oos",
                observed_at="2026-07-07T00:01:31Z",
                received_at="2026-07-07T00:01:31Z",
                expires_at="2026-07-07T00:03:00Z",
                authenticated=True,
                payload_ref=f"sha256:{digest}",
                payload_hash=digest,
                reason_codes=(),
            ),
            "expired": EvidenceRecord(
                evidence_id=f"historical:{digest}:expired",
                kind="historical_oos_promotion_artifact",
                state=EvidenceState.TRUSTED,
                source="licensed_historical_oos",
                observed_at="2026-07-07T00:00:00Z",
                received_at="2026-07-07T00:00:00Z",
                expires_at="2026-07-07T00:01:00Z",
                authenticated=True,
                payload_ref=f"sha256:{digest}",
                payload_hash=digest,
                reason_codes=(),
            ),
            "stale": self._historical_evidence(model),
        }

        for name, evidence in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError,
                "current historical OOS",
            ):
                AnalysisRequest.from_projection(
                    evaluation_clock=FIXED_CLOCK,
                    report_projection=report,
                    market_snapshot=snapshot,
                    market_evidence=self._trusted_market_evidence(snapshot),
                    policy_catalog=(
                        PolicyCatalog(
                            model_promotion_evidence_max_age_seconds=60
                        )
                        if name == "stale"
                        else None
                    ),
                    model_bundle=model,
                    historical_artifact=evidence,
                )

    def test_legacy_portfolio_action_cannot_override_typed_risk_claim(self):
        legacy_halt_with_clear_claim = self._fully_evaluable_record(
            portfolio_action="halt_system",
            canonical_portfolio_state=PreEntryRiskState.CLEAR,
            conservative_net_edge=0.10,
        )
        legacy_allow_with_veto_claim = self._fully_evaluable_record(
            portfolio_action="allow_new",
            canonical_portfolio_state=PreEntryRiskState.VETO,
            conservative_net_edge=0.10,
        )

        self.assertEqual(
            EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
            self._spread_decision(legacy_halt_with_clear_claim).status,
        )
        self.assertEqual(
            EntryAdmissionStatus.VETOED,
            self._spread_decision(legacy_allow_with_veto_claim).status,
        )

    def test_typed_risk_claim_must_bind_its_evidence_hash(self):
        with self.assertRaisesRegex(ValueError, "typed risk claim"):
            self._fully_evaluable_record(
                portfolio_action="allow_new",
                conservative_net_edge=0.10,
                risk_hash_override="0" * 64,
            )

    def test_expired_risk_evidence_cannot_admit_a_clear_claim(self):
        record = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            risk_observed_at="2026-07-07T00:00:00Z",
            risk_received_at="2026-07-07T00:00:00Z",
            risk_expires_at="2026-07-07T00:01:00Z",
        )
        decision = self._spread_decision(record)

        self.assertEqual(EntryAdmissionStatus.DEFERRED, decision.status)
        self.assertEqual(
            ConditionStatus.UNKNOWN,
            self._condition(decision, "portfolio_veto").status,
        )
        self.assertEqual(
            ConditionStatus.UNKNOWN,
            self._condition(decision, "exchange_health").status,
        )

    def test_portfolio_veto_precedes_unpromoted_e3_monitor_state(self):
        clear = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            promote_model=False,
        )
        vetoed = self._fully_evaluable_record(
            portfolio_action="no_new_trades",
            conservative_net_edge=0.10,
            promote_model=False,
        )

        self.assertEqual(
            EntryAdmissionStatus.MONITOR_ONLY,
            self._spread_decision(clear).status,
        )
        self.assertEqual(
            EntryAdmissionStatus.VETOED,
            self._spread_decision(vetoed).status,
        )

    def test_mismatched_cost_dimensions_fail_closed(self):
        record = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            cost_currency_override=("fee", "EUR"),
        )
        decision = self._spread_decision(record)

        self.assertEqual(EntryAdmissionStatus.DEFERRED, decision.status)
        condition = self._condition(
            decision,
            "economic_dimensions_consistent",
        )
        self.assertEqual(ConditionStatus.BLOCK, condition.status)
        self.assertEqual("ECONOMIC_DIMENSIONS_MISMATCH", condition.reason_code)

    def test_unknown_cost_is_never_conditionally_eligible(self):
        record = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
            omit_cost="slippage_reserve",
        )
        decision = self._spread_decision(record)

        self.assertEqual(EntryAdmissionStatus.DEFERRED, decision.status)
        self.assertEqual(
            ConditionStatus.UNKNOWN,
            self._condition(decision, "slippage_reserve_known").status,
        )

    def test_portfolio_veto_dominates_opportunity_and_risk_is_monotone(self):
        allowed = self._fully_evaluable_record(
            portfolio_action="allow_new",
            conservative_net_edge=0.10,
        )
        no_new = self._fully_evaluable_record(
            portfolio_action="no_new_trades",
            conservative_net_edge=0.10,
        )
        halted = self._fully_evaluable_record(
            portfolio_action="halt_system",
            conservative_net_edge=0.10,
        )

        self.assertEqual(
            EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
            self._spread_decision(allowed).status,
        )
        for record in (no_new, halted):
            decision = self._spread_decision(record)
            self.assertEqual(EntryAdmissionStatus.VETOED, decision.status)
            self.assertIn("PORTFOLIO_VETO_ACTIVE", decision.veto_sources)
            self.assertNotEqual(
                EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE,
                decision.status,
            )

    def test_non_finite_critical_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            PolicyCatalog(cost_coverage_ratio=math.nan)

        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=self._snapshot(),
        )
        report["candidate_research"]["call_credit_spreads"]["eligible"][0][
            "net_credit"
        ] = math.inf
        with self.assertRaisesRegex(ValueError, "finite"):
            AnalysisRequest.from_projection(
                evaluation_clock=FIXED_CLOCK,
                report_projection=report,
                market_snapshot=self._snapshot(),
            )

    def test_analysis_record_has_no_downstream_or_actionable_execution_fields(self):
        record = self._evaluate_with_explicit_trust(self._trusted_snapshot())
        payload = record.to_dict()
        encoded = json.dumps(payload, sort_keys=True)

        self.assertEqual([], validate_analysis_record(record))
        self.assertNotIn("recommended_size", encoded)
        self.assertNotIn("contract_count", encoded)
        self.assertNotIn("order_instruction", encoded)
        self.assertNotIn("position_management", encoded)
        self.assertNotIn("exit_contract", encoded)
        self.assertNotIn("settlement_reconciliation", encoded)
        self.assertNotIn("strategy_research", encoded)
        for legacy_downstream_action in (
            "reduce_size",
            "reduce_existing",
            "close_batch",
            "close_all_and_pause",
        ):
            self.assertNotIn(legacy_downstream_action, encoded)
        self.assertTrue(
            all(
                decision["execution_allowed"] is False
                for decision in payload["entry_admission_decisions"]
            )
        )

    def test_every_admission_condition_preserves_auditable_fields(self):
        record = self._evaluate_with_explicit_trust(self._trusted_snapshot())
        decision = record.entry_admission_decisions[0]

        self.assertTrue(decision.conditions)
        for condition in decision.conditions:
            with self.subTest(condition=condition.condition_id):
                projected = condition.to_dict()
                self.assertEqual(
                    {
                        "condition_id",
                        "observed",
                        "requirement",
                        "status",
                        "reason_code",
                    },
                    set(projected),
                )
                self.assertTrue(projected["requirement"])
                self.assertTrue(projected["reason_code"])

    def _evaluate_with_explicit_trust(
        self,
        snapshot,
        *,
        model_bundle=None,
    ):
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=self._trusted_market_evidence(snapshot),
            model_bundle=model_bundle,
            historical_artifact=(
                self._historical_evidence(model_bundle)
                if model_bundle is not None and model_bundle.promoted_for
                else None
            ),
        )
        return AnalysisRun().evaluate(request)

    def _fully_evaluable_record(
        self,
        *,
        portfolio_action,
        conservative_net_edge,
        omit_cost=None,
        event_score=0.0,
        policy_catalog=None,
        account_hash_override=None,
        cost_currency_override=None,
        promote_model=True,
        canonical_portfolio_state=None,
        risk_hash_override=None,
        risk_observed_at=FIXED_CLOCK,
        risk_received_at=FIXED_CLOCK,
        risk_expires_at="2026-07-07T00:02:00Z",
    ):
        snapshot = self._trusted_snapshot()
        report = generate_research_report(
            generated_at=FIXED_CLOCK,
            market_snapshot=snapshot,
            account_scenario="green",
        )
        report["portfolio_risk"]["final_action"] = portfolio_action
        report["permission_state"].setdefault("regime_scores", {})[
            "event"
        ] = event_score
        for section in ("naked_short_calls", "call_credit_spreads"):
            for candidate in report["candidate_research"][section]["eligible"]:
                candidate["product_style"] = "linear"
                candidate["contract_scale"] = 1.0
                candidate["analysis_capacity_class"] = "small"
                candidate["analysis_fair_interval"] = {
                    "lower": self._economic(0.01, "fair_value_lower"),
                    "upper": self._economic(0.20, "fair_value_upper"),
                }
                candidate["analysis_apparent_edge"] = self._economic(
                    0.12,
                    "apparent_edge",
                )
                candidate["analysis_uncertainty"] = self._economic(
                    0.01,
                    "model_uncertainty",
                )
                costs = {
                    name: self._economic(
                        (
                            conservative_net_edge
                            if name == "conservative_net_edge"
                            else 0.001
                        ),
                        name,
                    )
                    for name in (
                        "fee",
                        "slippage_reserve",
                        "depth_impact",
                        "legging_reserve",
                        "hedge_reserve",
                        "model_uncertainty_reserve",
                        "conservative_net_edge",
                    )
                }
                if omit_cost:
                    costs.pop(omit_cost)
                if (
                    cost_currency_override
                    and cost_currency_override[0] in costs
                ):
                    costs[cost_currency_override[0]]["currency"] = (
                        cost_currency_override[1]
                    )
                candidate["analysis_cost_evidence"] = costs

        account_payload = report["account_status"]
        account_payload["source"] = "deribit_live_private_read_only"
        account_payload["live_snapshot"] = True
        account_payload.setdefault("private_adapter_contract", {}).update(
            {
                "source": "deribit_live_private_read_only",
                "replay_fixture": False,
            }
        )
        account_hash = account_hash_override or canonical_sha256(account_payload)
        account_evidence = EvidenceRecord(
            evidence_id=f"account:{account_hash}",
            kind="account_snapshot",
            state=EvidenceState.TRUSTED,
            source="deribit_live_private_read_only",
            observed_at=FIXED_CLOCK,
            received_at=FIXED_CLOCK,
            expires_at="2026-07-07T00:02:00Z",
            authenticated=True,
            payload_ref=f"sha256:{account_hash}",
            payload_hash=account_hash,
            reason_codes=(),
        )
        risk_claim = PreEntryRiskClaim(
            portfolio_state=(
                canonical_portfolio_state
                or (
                    PreEntryRiskState.CLEAR
                    if portfolio_action == "allow_new"
                    else PreEntryRiskState.VETO
                )
            ),
            exchange_health_state=ExchangeHealthState.CLEAR,
        )
        risk_hash = risk_hash_override or risk_claim.payload_hash
        risk_evidence = EvidenceRecord(
            evidence_id=f"risk:{risk_hash}",
            kind="pre_entry_risk_veto",
            state=EvidenceState.TRUSTED,
            source="pre_entry_risk_engine",
            observed_at=risk_observed_at,
            received_at=risk_received_at,
            expires_at=risk_expires_at,
            authenticated=True,
            payload_ref=f"sha256:{risk_hash}",
            payload_hash=risk_hash,
            reason_codes=(),
        )
        model = self._promoted_model("5") if promote_model else None
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=report,
            market_snapshot=snapshot,
            market_evidence=self._trusted_market_evidence(snapshot),
            account_evidence=account_evidence,
            pre_entry_risk_claim=risk_claim,
            pre_entry_risk_evidence=risk_evidence,
            policy_catalog=policy_catalog,
            model_bundle=model,
            historical_artifact=(
                self._historical_evidence(model) if model else None
            ),
        )
        return AnalysisRun().evaluate(request)

    @staticmethod
    def _economic(amount, kind):
        return {
            "amount": amount,
            "currency": "USD",
            "kind": kind,
            "product_type": "option",
            "contract_scale": 1.0,
            "as_of": FIXED_CLOCK,
            "provenance": "test:typed_evidence",
        }

    @staticmethod
    def _promoted_model(seed):
        return ModelBundleRef.promoted(
            model_bundle_id=f"model-bundle:promoted-e3:{seed}",
            artifact_hash=str(seed) * 64,
            promotion_evidence_hash=canonical_sha256(
                {"historical_oos_promotion": str(seed)}
            ),
            evidence_class="real_oos",
        )

    @staticmethod
    def _historical_evidence(model):
        digest = model.promotion_evidence_hash
        return EvidenceRecord(
            evidence_id=f"historical:{digest}",
            kind="historical_oos_promotion_artifact",
            state=EvidenceState.TRUSTED,
            source="licensed_historical_oos",
            observed_at="2026-07-06T00:00:00Z",
            received_at=FIXED_CLOCK,
            expires_at=None,
            authenticated=True,
            payload_ref=f"sha256:{digest}",
            payload_hash=digest,
            reason_codes=(),
        )

    @staticmethod
    def _spread_decision(record):
        spread_ids = {
            plan.strategy_id
            for plan in record.strategy_plans
            if plan.structure == "CALL_CREDIT_SPREAD"
        }
        return next(
            decision
            for decision in record.entry_admission_decisions
            if decision.strategy_id in spread_ids
        )

    @staticmethod
    def _condition(decision, condition_id):
        return next(
            item
            for item in decision.conditions
            if item.condition_id == condition_id
        )

    @staticmethod
    def _snapshot():
        return load_snapshot_fixture(FIXTURE_PATH)

    def _trusted_snapshot(self):
        snapshot = copy.deepcopy(self._snapshot())
        snapshot["source"] = "deribit_live:https://www.deribit.com"
        observed_at = snapshot["captured_at"]

        def provenance(endpoint):
            return {
                "venue": "DERIBIT",
                "transport": "HTTPS_JSON_RPC",
                "source_endpoint": endpoint,
                "observed_at": observed_at,
                "schema_version": "deribit_public_feed.v1",
            }

        snapshot["feeds"] = {
            "vol_index": {
                "index_name": "BTC DVOL",
                "currency": "BTC",
                "timestamp": observed_at,
                "volatility": 0.64,
                "source_endpoint": "public/get_volatility_index_data",
                "provenance": provenance("public/get_volatility_index_data"),
            },
            "index_spot": {
                "index_name": "btc_usd",
                "currency": "BTC",
                "index_price": 100000.0,
                "observed_at": observed_at,
                "source_endpoint": "public/get_index_price",
                "provenance": provenance("public/get_index_price"),
            },
            "funding_basis": {
                "instrument_name": "BTC-PERPETUAL",
                "funding_rate": 0.0001,
                "basis_rate": 0.001,
                "index_price": 100000.0,
                "mark_price": 100100.0,
                "observed_at": observed_at,
                "source_endpoint": (
                    "public/get_funding_rate_value+public/ticker"
                ),
                "provenance": provenance(
                    "public/get_funding_rate_value+public/ticker"
                ),
            },
            "order_book": {
                "instrument_name": snapshot["rows"][0]["instrument_name"],
                "timestamp": observed_at,
                "state": "open",
                "change_id": 1,
                "bids": [[0.20, 1.0]],
                "asks": [[0.21, 1.0]],
                "source_endpoint": "public/get_order_book",
                "provenance": provenance("public/get_order_book"),
            },
            "events": {
                "observed_at": observed_at,
                "exchange_locked": False,
                "locked_currencies": [],
                "locked_indices": [],
                "macro_events": [],
                "scope": "exchange_native_only",
                "source_endpoint": "public/status",
                "provenance": provenance("public/status"),
            },
        }
        return snapshot

    @staticmethod
    def _trusted_market_evidence(snapshot):
        expires_at = (
            datetime.fromisoformat(
                str(snapshot["captured_at"]).replace("Z", "+00:00")
            )
            .astimezone(timezone.utc)
            + timedelta(seconds=120)
        ).isoformat().replace("+00:00", "Z")
        return EvidenceRecord(
            evidence_id=f"market:{snapshot_payload_sha256(snapshot)}",
            kind="market_snapshot",
            state=EvidenceState.TRUSTED,
            source=str(snapshot["source"]),
            observed_at=str(snapshot["captured_at"]),
            received_at=FIXED_CLOCK,
            expires_at=expires_at,
            authenticated=True,
            payload_ref=f"sha256:{snapshot_payload_sha256(snapshot)}",
            payload_hash=snapshot_payload_sha256(snapshot),
            reason_codes=(),
            trust_consecutive_passes=3,
            trust_observation_seconds=30.0,
        )


if __name__ == "__main__":
    unittest.main()
