import unittest

from crypto_options_report.strategy_history import (
    BOOTSTRAP_SEED,
    COST_STRESS_MULTIPLIER,
    DEFAULT_PROTOCOL_DOCUMENT,
    EMBARGO_DAYS,
    ENTRY_COST_BASIS,
    build_holdout_access_receipt,
    build_strategy_history_artifact,
    build_strategy_history_protocol,
    validate_strategy_history_artifact,
)


def _cohort_entries(
    *,
    sample_role: str,
    source_classification: str,
    cohort_count: int,
    observation_count: int = 15,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    volatility = ("low_vol", "high_vol")
    trend = ("uptrend", "downtrend")
    liquidity = ("tight", "wide")
    for index in range(cohort_count):
        month = 1 + index
        year = 2026 if sample_role == "development" else 2027
        entries.append(
            {
                "cohort_id": f"{sample_role}-cohort-{index + 1}",
                "expiry_date": f"{year}-{month:02d}-15",
                "sample_role": sample_role,
                "source_classification": source_classification,
                "settled": True,
                "captured_at": f"{year}-{month:02d}-01T00:00:00Z",
                "settled_at": f"{year}-{month:02d}-15T08:00:00Z",
                "observation_count": observation_count,
                "duplicate_observations_dropped": 1 if index == 0 else 0,
                "overlap_observations_dropped": 2 if index == 1 else 0,
                "purged_training_observations": 3 if sample_role == "development" else 0,
                "embargoed_until": f"{year}-{month:02d}-19",
                "volatility_regime": volatility[index % len(volatility)],
                "trend_regime": trend[index % len(trend)],
                "liquidity_regime": liquidity[index % len(liquidity)],
            }
        )
    return entries


def _passing_holdout_metrics() -> dict[str, object]:
    return {
        "win_rate": 0.68,
        "mean_net_r": 0.21,
        "bootstrap_lower_mean_net_r": 0.05,
        "paired_comparator_mean_net_r_diff": 0.07,
        "cost_stress_mean_net_r": 0.11,
        "max_drawdown_pct_nav": 0.08,
        "cvar_95_pct_nav": 0.02,
        "max_single_cohort_profit_share": 0.30,
        "max_single_month_profit_share": 0.32,
        "max_loss_per_trade_pct_nav": 0.014,
        "same_expiry_max_loss_pct_nav": 0.028,
        "new_margin_pct_nav": 0.07,
        "loss_is_bounded": True,
        "max_loss_known": True,
        "margin_known": True,
        "premium_unit_consistent": True,
        "payoff_currency_consistent": True,
    }


class StrategyBriefHistoryTests(unittest.TestCase):
    def test_bear_call_protocol_freezes_as_exploratory_until_future_holdout_exists(self):
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=_cohort_entries(
                sample_role="development",
                source_classification="development_inventory",
                cohort_count=8,
            ),
            exploratory_metrics={"win_rate": 0.64, "mean_net_r": 0.17},
        )

        self.assertEqual([], validate_strategy_history_artifact(artifact))
        self.assertEqual("EXPLORATORY", artifact["status"])
        self.assertEqual("EXPLORATORY", artifact["public_summary"]["status"])
        self.assertIsNone(artifact["public_summary"]["win_rate"])
        self.assertIsNone(artifact["public_summary"]["mean_net_r"])
        self.assertEqual(
            "CALL_CREDIT_SPREAD",
            artifact["protocol"]["boundary_reference"]["legacy_structure"],
        )
        self.assertEqual(
            "bid_minus_one_adverse_tick",
            artifact["protocol"]["fill_policy"]["short_legs"],
        )
        self.assertEqual(
            "ask_plus_one_adverse_tick",
            artifact["protocol"]["fill_policy"]["long_legs"],
        )
        self.assertEqual([7, 35], artifact["protocol"]["structure_alignment"]["dte_band_days"])
        self.assertEqual(BOOTSTRAP_SEED, artifact["protocol"]["bootstrap"]["seed"])
        self.assertEqual(
            COST_STRESS_MULTIPLIER,
            artifact["protocol"]["cost_stress"]["multiplier"],
        )
        self.assertEqual(
            DEFAULT_PROTOCOL_DOCUMENT,
            artifact["manifest"]["protocol_document"],
        )
        self.assertEqual(
            ENTRY_COST_BASIS,
            artifact["public_summary"]["entry_cost_basis"],
        )
        self.assertEqual([7, 35], artifact["public_summary"]["dte_band_days"])
        self.assertFalse(artifact["public_summary"]["scope_verified"])

    def test_bull_put_keeps_a_separate_boundary_and_does_not_borrow_bear_call_validation(self):
        artifact = build_strategy_history_artifact(
            structure_type="BULL_PUT_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=_cohort_entries(
                sample_role="development",
                source_classification="development_inventory",
                cohort_count=8,
            ),
            exploratory_metrics={"win_rate": 0.66, "mean_net_r": 0.19},
        )

        self.assertEqual([], validate_strategy_history_artifact(artifact))
        self.assertEqual("EXPLORATORY", artifact["status"])
        self.assertIsNone(artifact["protocol"]["boundary_reference"]["legacy_structure"])
        self.assertFalse(
            artifact["protocol"]["boundary_reference"][
                "inherits_legacy_bear_call_boundary"
            ]
        )
        self.assertIn(
            "bull-put history must keep its own aligned replay",
            artifact["notes"][0].lower(),
        )

    def test_insufficient_state_requires_enough_cohorts_observations_and_regime_coverage(self):
        artifact = build_strategy_history_artifact(
            structure_type="IRON_CONDOR",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=_cohort_entries(
                sample_role="development",
                source_classification="development_inventory",
                cohort_count=4,
                observation_count=10,
            ),
        )

        self.assertEqual([], validate_strategy_history_artifact(artifact))
        self.assertEqual("INSUFFICIENT", artifact["status"])
        self.assertIn("INSUFFICIENT_INDEPENDENT_COHORTS", artifact["reason_codes"])
        self.assertIn("INSUFFICIENT_STRATEGY_OBSERVATIONS", artifact["reason_codes"])
        self.assertIsNone(artifact["public_summary"]["win_rate"])
        self.assertIsNone(artifact["public_summary"]["mean_net_r"])

    def test_future_holdout_can_validate_and_expose_public_metrics(self):
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2026-08-30T12:00:00Z",
        )
        receipt = build_holdout_access_receipt(
            accessed_at="2028-01-01T00:00:00Z",
            command_hash="cmd-001",
            input_hash="input-001",
            result_hash="result-001",
            verified_source="future_holdout",
        )
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=[
                *_cohort_entries(
                    sample_role="development",
                    source_classification="development_inventory",
                    cohort_count=8,
                ),
                *_cohort_entries(
                    sample_role="holdout",
                    source_classification="future_holdout",
                    cohort_count=8,
                ),
            ],
            holdout_status="evaluated",
            holdout_metrics=_passing_holdout_metrics(),
            frozen_protocol=protocol,
            access_receipt=receipt,
            walk_forward_folds=[
                {
                    "fold_id": "fold-1",
                    "train_end": "2027-04-15T08:00:00Z",
                    "validation_start": "2027-05-20T08:00:00Z",
                    "validation_end": "2027-06-15T08:00:00Z",
                    "embargo_days": EMBARGO_DAYS,
                }
            ],
        )

        self.assertEqual([], validate_strategy_history_artifact(artifact))
        self.assertEqual("VALIDATED", artifact["status"])
        self.assertAlmostEqual(0.68, artifact["public_summary"]["win_rate"])
        self.assertAlmostEqual(0.21, artifact["public_summary"]["mean_net_r"])
        self.assertEqual(8, artifact["public_summary"]["independent_cohorts"])
        self.assertEqual(120, artifact["public_summary"]["observation_count"])
        self.assertEqual("recorded", artifact["walk_forward"]["metadata_status"])
        self.assertTrue(artifact["manifest"]["content_addressed"])
        self.assertEqual("BEAR_CALL_CREDIT_SPREAD", artifact["public_summary"]["structure_type"])
        self.assertEqual("bearish", artifact["public_summary"]["direction"])
        self.assertEqual(ENTRY_COST_BASIS, artifact["public_summary"]["entry_cost_basis"])
        self.assertTrue(artifact["public_summary"]["scope_verified"])
        self.assertEqual(
            artifact["artifact_id"],
            artifact["public_summary"]["artifact_id"],
        )

    def test_failed_state_hides_public_metrics_when_a_frozen_gate_fails(self):
        metrics = _passing_holdout_metrics()
        metrics["cost_stress_mean_net_r"] = -0.01
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2026-08-30T12:00:00Z",
        )
        receipt = build_holdout_access_receipt(
            accessed_at="2028-01-01T00:00:00Z",
            command_hash="cmd-001",
            input_hash="input-001",
            result_hash="result-001",
            verified_source="future_holdout",
        )
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=[
                *_cohort_entries(
                    sample_role="development",
                    source_classification="development_inventory",
                    cohort_count=8,
                ),
                *_cohort_entries(
                    sample_role="holdout",
                    source_classification="future_holdout",
                    cohort_count=8,
                ),
            ],
            holdout_status="evaluated",
            holdout_metrics=metrics,
            frozen_protocol=protocol,
            access_receipt=receipt,
        )

        self.assertEqual([], validate_strategy_history_artifact(artifact))
        self.assertEqual("FAILED", artifact["status"])
        self.assertIn("COST_STRESS_NOT_POSITIVE", artifact["reason_codes"])
        self.assertIsNone(artifact["public_summary"]["win_rate"])
        self.assertIsNone(artifact["public_summary"]["mean_net_r"])

    def test_validator_rejects_relabelled_development_holdout(self):
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2026-08-30T12:00:00Z",
        )
        receipt = build_holdout_access_receipt(
            accessed_at="2028-01-01T00:00:00Z",
            command_hash="cmd-001",
            input_hash="input-001",
            result_hash="result-001",
            verified_source="future_holdout",
        )
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=[
                *_cohort_entries(
                    sample_role="development",
                    source_classification="development_inventory",
                    cohort_count=8,
                ),
                *_cohort_entries(
                    sample_role="holdout",
                    source_classification="future_holdout",
                    cohort_count=8,
                ),
            ],
            holdout_status="evaluated",
            holdout_metrics=_passing_holdout_metrics(),
            frozen_protocol=protocol,
            access_receipt=receipt,
        )
        artifact["cohort_ledger"]["entries"][-1]["source_classification"] = (
            "development_inventory"
        )
        artifact["holdout"]["future_only"] = False
        artifact["holdout"]["eligible_for_validation"] = False

        errors = validate_strategy_history_artifact(artifact)

        self.assertIn(
            "evaluated strategy_history.holdout must be sourced only from future holdout cohorts",
            errors,
        )
        self.assertIn(
            "strategy_history.result_hash must match the canonical payload",
            errors,
        )

    def test_evaluated_holdout_without_receipt_cannot_validate(self):
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2026-08-30T12:00:00Z",
        )
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=[
                *_cohort_entries(
                    sample_role="development",
                    source_classification="development_inventory",
                    cohort_count=8,
                ),
                *_cohort_entries(
                    sample_role="holdout",
                    source_classification="future_holdout",
                    cohort_count=8,
                ),
            ],
            holdout_status="evaluated",
            holdout_metrics=_passing_holdout_metrics(),
            frozen_protocol=protocol,
        )

        self.assertEqual("FAILED", artifact["status"])
        self.assertIn("MISSING_HOLDOUT_ACCESS_RECEIPT", artifact["reason_codes"])
        self.assertIn(
            "evaluated strategy_history.holdout must provide one-time audited access receipt evidence",
            validate_strategy_history_artifact(artifact),
        )

    def test_evaluated_holdout_with_postdated_protocol_is_rejected(self):
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2027-03-01T00:00:00Z",
        )
        receipt = build_holdout_access_receipt(
            accessed_at="2028-01-01T00:00:00Z",
            command_hash="cmd-001",
            input_hash="input-001",
            result_hash="result-001",
            verified_source="future_holdout",
        )
        artifact = build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2027-03-01T00:00:00Z",
            cohort_ledger=[
                *_cohort_entries(
                    sample_role="development",
                    source_classification="development_inventory",
                    cohort_count=8,
                ),
                *_cohort_entries(
                    sample_role="holdout",
                    source_classification="future_holdout",
                    cohort_count=8,
                ),
            ],
            holdout_status="evaluated",
            holdout_metrics=_passing_holdout_metrics(),
            frozen_protocol=protocol,
            access_receipt=receipt,
        )

        self.assertEqual("FAILED", artifact["status"])
        self.assertIn("PROTOCOL_FROZEN_AFTER_HOLDOUT_CAPTURE", artifact["reason_codes"])

    def test_artifact_hash_is_stable_for_same_inputs_and_changes_with_content(self):
        inputs = {
            "structure_type": "BEAR_CALL_CREDIT_SPREAD",
            "generated_at": "2026-08-30T12:00:00Z",
            "cohort_ledger": _cohort_entries(
                sample_role="development",
                source_classification="development_inventory",
                cohort_count=8,
            ),
            "exploratory_metrics": {"win_rate": 0.64, "mean_net_r": 0.17},
        }

        first = build_strategy_history_artifact(**inputs)
        second = build_strategy_history_artifact(**inputs)
        changed = build_strategy_history_artifact(
            **{
                **inputs,
                "cohort_ledger": [
                    {
                        **inputs["cohort_ledger"][0],
                        "duplicate_observations_dropped": 99,
                    },
                    *inputs["cohort_ledger"][1:],
                ],
            }
        )

        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(first["result_hash"], second["result_hash"])
        self.assertNotEqual(first["artifact_id"], changed["artifact_id"])


if __name__ == "__main__":
    unittest.main()
