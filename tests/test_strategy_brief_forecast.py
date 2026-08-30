import unittest

from crypto_options_report.strategy_forecast import (
    build_calibrated_strategy_forecast_artifact,
    build_screening_only_strategy_forecast,
    build_unavailable_strategy_forecast,
    project_strategy_forecast,
    validate_strategy_forecast_artifact,
    validate_strategy_forecast_projection,
)


class StrategyBriefForecastTests(unittest.TestCase):
    def test_production_default_is_unavailable(self) -> None:
        forecast = build_unavailable_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("UNAVAILABLE", forecast["status"])
        self.assertIsNone(forecast["win_rate_low"])
        self.assertIsNone(forecast["win_rate_high"])
        self.assertEqual(["FORECAST_NOT_CALIBRATED"], forecast["reason_codes"])

    def test_screening_only_never_exposes_probabilities(self) -> None:
        forecast = build_screening_only_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("SCREENING_ONLY", forecast["status"])
        self.assertIsNone(forecast["win_rate_low"])
        self.assertIsNone(forecast["win_rate_high"])
        self.assertIsNone(forecast["confidence"])

    def test_valid_live_artifact_projects_calibrated_interval(self) -> None:
        artifact = self._artifact()

        self.assertEqual([], validate_strategy_forecast_artifact(artifact))

        forecast = project_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
            artifact=artifact,
            current_input_fingerprint=self._input_fingerprint(),
            current_lineage=self._lineage(),
            current_oos_monitor=self._oos_monitor(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("CALIBRATED", forecast["status"])
        self.assertEqual(artifact["artifact_id"], forecast["artifact_id"])
        self.assertEqual(0.64, forecast["win_rate_low"])
        self.assertEqual(0.70, forecast["win_rate_high"])
        self.assertEqual("MEDIUM", forecast["confidence"])
        self.assertEqual([], forecast["reason_codes"])

    def test_calibrated_artifact_requires_all_promotion_gates(self) -> None:
        cases = (
            (
                "not_preregistered",
                ("preregistration", "pre_registered"),
                False,
                "pre-registered",
            ),
            (
                "holdout_not_sealed_at_freeze",
                ("preregistration", "holdout_status_at_freeze"),
                "opened",
                "sealed at freeze",
            ),
            (
                "missing_holdout_access_record",
                ("holdout_access",),
                None,
                "holdout_access must be a dict",
            ),
            (
                "holdout_access_before_freeze",
                ("holdout_access", "accessed_at"),
                "2026-08-11T16:49:54Z",
                "after preregistration freeze",
            ),
            (
                "holdout_access_after_promotion",
                ("holdout_access", "accessed_at"),
                "2026-08-30T09:00:00Z",
                "promoted_at must be at or after",
            ),
            (
                "holdout_access_count_reused",
                ("holdout_access", "access_count"),
                2,
                "exactly 1",
            ),
            (
                "holdout_rerun_present",
                ("holdout_access", "rerun_count"),
                1,
                "must be 0",
            ),
            (
                "holdout_invalidated",
                ("holdout_access", "invalidated"),
                True,
                "must be false",
            ),
            (
                "holdout_previously_viewed",
                ("holdout_access", "previously_viewed"),
                True,
                "previously viewed holdout",
            ),
            (
                "holdout_tuned_after_access",
                ("holdout_access", "tuned_after_access"),
                True,
                "post-access tuning",
            ),
            (
                "model_not_frozen",
                ("model", "frozen"),
                False,
                "model must be frozen",
            ),
            (
                "calibrator_not_frozen",
                ("calibrator", "frozen"),
                False,
                "calibrator must be frozen",
            ),
            (
                "not_purged",
                ("validation", "walk_forward", "purged"),
                False,
                "purged",
            ),
            (
                "not_embargoed",
                ("validation", "walk_forward", "embargoed"),
                False,
                "embargoed",
            ),
            (
                "too_few_cohorts",
                ("validation", "walk_forward", "independent_future_cohorts"),
                7,
                "8 independent future cohorts",
            ),
            (
                "too_few_observations",
                ("validation", "walk_forward", "observation_count"),
                99,
                "100 observations",
            ),
            (
                "too_few_regimes",
                ("validation", "walk_forward", "regime_count"),
                1,
                "2 regimes",
            ),
            (
                "too_much_one_regime",
                ("validation", "walk_forward", "max_regime_share"),
                0.61,
                "60%",
            ),
            (
                "brier_not_better",
                ("validation", "performance", "brier_score"),
                0.25,
                "Brier score must beat",
            ),
            (
                "reliability_fails",
                ("validation", "performance", "reliability_pass"),
                False,
                "reliability gate",
            ),
            (
                "interval_too_wide",
                ("validation", "interval", "decision_width_pass"),
                False,
                "decision-width gate",
            ),
            (
                "history_not_validated",
                ("validation", "aligned_support", "history_status"),
                "EXPLORATORY",
                "history must be VALIDATED",
            ),
            (
                "risk_not_passed",
                ("validation", "aligned_support", "risk_status"),
                "BLOCKED",
                "risk gate must pass",
            ),
            (
                "too_many_adverse_oos",
                ("validation", "oos_monitor", "consecutive_adverse_cohorts"),
                3,
                "3 consecutive adverse OOS cohorts",
            ),
        )

        for label, path, value, expected in cases:
            with self.subTest(label=label):
                artifact = self._artifact_payload()
                target = artifact
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, expected):
                    build_calibrated_strategy_forecast_artifact(**artifact)

    def test_demo_and_fixture_evidence_cannot_masquerade_as_live_calibration(self) -> None:
        for source_class in ("demo", "fixture"):
            with self.subTest(source_class=source_class):
                artifact = self._artifact_payload()
                artifact["input_fingerprint"]["source_class"] = source_class

                with self.assertRaisesRegex(ValueError, "live evidence"):
                    build_calibrated_strategy_forecast_artifact(**artifact)

    def test_opened_holdout_cannot_be_reused_for_promotion(self) -> None:
        artifact = self._artifact_payload()
        artifact["holdout_access"]["access_count"] = 2

        with self.assertRaisesRegex(ValueError, "exactly 1"):
            build_calibrated_strategy_forecast_artifact(**artifact)

    def test_artifact_id_must_exist_and_match_canonical_hash(self) -> None:
        artifact = self._artifact()
        artifact["artifact_id"] = None
        self.assertIn(
            "strategy_forecast artifact_id must be present",
            validate_strategy_forecast_artifact(artifact),
        )

        artifact = self._artifact()
        artifact["artifact_id"] = "strategy_forecast:tampered"
        self.assertIn(
            "strategy_forecast artifact_id must match the canonical payload",
            validate_strategy_forecast_artifact(artifact),
        )

    def test_retirement_paths_null_out_old_probabilities(self) -> None:
        artifact = self._artifact()
        cases = (
            (
                "expired",
                "2026-12-01T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                self._lineage(),
                self._oos_monitor(),
                "PROMOTION_EXPIRED",
            ),
            (
                "scope_mismatch",
                "2026-08-30T08:30:00Z",
                {**self._scope(), "direction": "BEARISH"},
                self._input_fingerprint(),
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_SCOPE_MISMATCH",
            ),
            (
                "selection_mismatch",
                "2026-08-30T08:30:00Z",
                self._alternate_scope_same_family(),
                self._input_fingerprint(),
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_SELECTION_MISMATCH",
            ),
            (
                "input_drift",
                "2026-08-30T08:30:00Z",
                self._scope(),
                {**self._input_fingerprint(), "dataset_hash": "dataset-def"},
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_INPUT_DRIFT",
            ),
            (
                "config_drift",
                "2026-08-30T08:30:00Z",
                self._scope(),
                {**self._input_fingerprint(), "config_hash": "config-def"},
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_CONFIG_DRIFT",
            ),
            (
                "schema_drift",
                "2026-08-30T08:30:00Z",
                self._scope(),
                {
                    **self._input_fingerprint(),
                    "feature_schema_version": "feature-schema.v2",
                },
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_SCHEMA_DRIFT",
            ),
            (
                "unit_drift",
                "2026-08-30T08:30:00Z",
                self._scope(),
                {
                    **self._input_fingerprint(),
                    "unit_semantics_version": "units.v2",
                },
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_UNIT_DRIFT",
            ),
            (
                "continuity_broken",
                "2026-08-30T08:30:00Z",
                self._scope(),
                {
                    **self._input_fingerprint(),
                    "continuity_max_gap_days": 4,
                },
                self._lineage(),
                self._oos_monitor(),
                "FORECAST_DATA_CONTINUITY_BROKEN",
            ),
            (
                "lineage_failed",
                "2026-08-30T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                {**self._lineage(), "verified": False},
                self._oos_monitor(),
                "FORECAST_LINEAGE_UNVERIFIED",
            ),
            (
                "lineage_id_drift",
                "2026-08-30T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                {**self._lineage(), "history_artifact_id": "history:def"},
                self._oos_monitor(),
                "FORECAST_LINEAGE_DRIFT",
            ),
            (
                "oos_demoted",
                "2026-08-30T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                self._lineage(),
                {
                    **self._oos_monitor(),
                    "consecutive_adverse_cohorts": 3,
                },
                "FORECAST_OOS_ADVERSE",
            ),
            (
                "oos_directional_fail",
                "2026-08-30T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                self._lineage(),
                {**self._oos_monitor(), "directional_pass": False},
                "FORECAST_OOS_DIRECTIONAL_FAIL",
            ),
            (
                "oos_base_rate_fail",
                "2026-08-30T08:30:00Z",
                self._scope(),
                self._input_fingerprint(),
                self._lineage(),
                {**self._oos_monitor(), "base_rate_quality_pass": False},
                "FORECAST_OOS_BASE_RATE_FAIL",
            ),
        )

        for label, as_of, scope, fingerprint, lineage, oos_monitor, expected in cases:
            with self.subTest(label=label):
                forecast = project_strategy_forecast(
                    as_of=as_of,
                    scope=scope,
                    artifact=artifact,
                    current_input_fingerprint=fingerprint,
                    current_lineage=lineage,
                    current_oos_monitor=oos_monitor,
                )

                self.assertEqual([], validate_strategy_forecast_projection(forecast))
                self.assertEqual("RETIRED", forecast["status"])
                self.assertIsNone(forecast["win_rate_low"])
                self.assertIsNone(forecast["win_rate_high"])
                self.assertIn(expected, forecast["reason_codes"])

    def test_legacy_calibrated_artifact_without_selection_binding_key_retires_unbound(self) -> None:
        artifact = self._artifact()
        artifact.pop("selection_binding_key", None)

        forecast = project_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
            artifact=artifact,
            current_input_fingerprint=self._input_fingerprint(),
            current_lineage=self._lineage(),
            current_oos_monitor=self._oos_monitor(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("RETIRED", forecast["status"])
        self.assertIsNone(forecast["win_rate_low"])
        self.assertIsNone(forecast["win_rate_high"])
        self.assertIn("FORECAST_SELECTION_UNBOUND", forecast["reason_codes"])

    def test_missing_current_evidence_auto_retires_old_probabilities(self) -> None:
        artifact = self._artifact()
        cases = (
            (
                "missing_current_input_fingerprint",
                None,
                self._lineage(),
                self._oos_monitor(),
            ),
            (
                "missing_current_lineage",
                self._input_fingerprint(),
                None,
                self._oos_monitor(),
            ),
            (
                "missing_current_oos_monitor",
                self._input_fingerprint(),
                self._lineage(),
                None,
            ),
        )

        for label, fingerprint, lineage, oos_monitor in cases:
            with self.subTest(label=label):
                forecast = project_strategy_forecast(
                    as_of="2026-08-30T08:30:00Z",
                    scope=self._scope(),
                    artifact=artifact,
                    current_input_fingerprint=fingerprint,
                    current_lineage=lineage,
                    current_oos_monitor=oos_monitor,
                )

                self.assertEqual([], validate_strategy_forecast_projection(forecast))
                self.assertEqual("RETIRED", forecast["status"])
                self.assertIsNone(forecast["win_rate_low"])
                self.assertIsNone(forecast["win_rate_high"])
                self.assertIn(
                    "FORECAST_CURRENT_EVIDENCE_UNAVAILABLE",
                    forecast["reason_codes"],
                )

    def test_current_non_live_source_auto_retires_old_probabilities(self) -> None:
        artifact = self._artifact()

        forecast = project_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
            artifact=artifact,
            current_input_fingerprint={
                **self._input_fingerprint(),
                "source_class": "fixture",
            },
            current_lineage=self._lineage(),
            current_oos_monitor=self._oos_monitor(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("RETIRED", forecast["status"])
        self.assertIsNone(forecast["win_rate_low"])
        self.assertIsNone(forecast["win_rate_high"])
        self.assertIn("FORECAST_CURRENT_SOURCE_NOT_LIVE", forecast["reason_codes"])
        self.assertIn(
            "FORECAST_CURRENT_EVIDENCE_UNAVAILABLE",
            forecast["reason_codes"],
        )

    def test_tampered_artifact_cannot_keep_a_calibrated_projection(self) -> None:
        artifact = self._artifact()
        artifact["validation"]["interval"]["win_rate_high"] = 0.72

        forecast = project_strategy_forecast(
            as_of="2026-08-30T08:30:00Z",
            scope=self._scope(),
            artifact=artifact,
            current_input_fingerprint=self._input_fingerprint(),
            current_lineage=self._lineage(),
            current_oos_monitor=self._oos_monitor(),
        )

        self.assertEqual([], validate_strategy_forecast_projection(forecast))
        self.assertEqual("RETIRED", forecast["status"])
        self.assertIsNone(forecast["win_rate_low"])
        self.assertIsNone(forecast["win_rate_high"])
        self.assertIn("FORECAST_ARTIFACT_INVALID", forecast["reason_codes"])

    def _artifact(self) -> dict[str, object]:
        return build_calibrated_strategy_forecast_artifact(**self._artifact_payload())

    def _artifact_payload(self) -> dict[str, object]:
        return {
            "promoted_at": "2026-08-30T08:00:00Z",
            "expires_at": "2026-11-28T08:00:00Z",
            "scope": self._scope(),
            "preregistration": {
                "pre_registered": True,
                "frozen_at": "2026-08-12T00:49:54+08:00",
                "protocol_document": (
                    "docs/product/exact-strategy-forecast-protocol-v1.md"
                ),
                "holdout_status_at_freeze": "sealed",
            },
            "holdout_access": {
                "accessed_at": "2026-08-30T07:55:00Z",
                "command_hash": "command-hash-001",
                "input_hash": "input-hash-001",
                "result_hash": "result-hash-001",
                "access_count": 1,
                "rerun_count": 0,
                "invalidated": False,
                "previously_viewed": False,
                "tuned_after_access": False,
            },
            "model": {
                "id": "forecast-model-v1",
                "digest": "model-digest-001",
                "frozen": True,
            },
            "calibrator": {
                "id": "isotonic-v1",
                "digest": "calibrator-digest-001",
                "frozen": True,
            },
            "validation": {
                "walk_forward": {
                    "purged": True,
                    "embargoed": True,
                    "independent_future_cohorts": 8,
                    "observation_count": 124,
                    "regime_count": 3,
                    "max_regime_share": 0.50,
                },
                "performance": {
                    "brier_score": 0.18,
                    "base_rate_brier_score": 0.24,
                    "reliability_pass": True,
                },
                "interval": {
                    "win_rate_low": 0.64,
                    "win_rate_high": 0.70,
                    "confidence": "MEDIUM",
                    "decision_width_pass": True,
                    "max_width": 0.08,
                },
                "aligned_support": {
                    "history_status": "VALIDATED",
                    "risk_status": "PASS",
                },
                "oos_monitor": {
                    "consecutive_adverse_cohorts": 0,
                },
            },
            "input_fingerprint": self._input_fingerprint(),
            "lineage": self._lineage(),
        }

    @staticmethod
    def _scope() -> dict[str, object]:
        return {
            "underlying": "BTC",
            "structure": "BULL_PUT_CREDIT_SPREAD",
            "direction": "BULLISH",
            "dte": {"min": 7, "max": 35},
            "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
            "exit_basis": "hold_to_expiry_cash_settlement",
            "selection": {
                "expiry_date": "2026-09-25",
                "legs": [
                    {
                        "instrument_name": "BTC-25SEP26-115000-P",
                        "option_type": "put",
                        "strike": 115_000.0,
                        "quantity": -1.0,
                    },
                    {
                        "instrument_name": "BTC-25SEP26-110000-P",
                        "option_type": "put",
                        "strike": 110_000.0,
                        "quantity": 1.0,
                    },
                ],
            },
        }

    @staticmethod
    def _alternate_scope_same_family() -> dict[str, object]:
        scope = StrategyBriefForecastTests._scope()
        scope["selection"] = {
            "expiry_date": "2026-09-25",
            "legs": [
                {
                    "instrument_name": "BTC-25SEP26-116000-P",
                    "option_type": "put",
                    "strike": 116_000.0,
                    "quantity": -1.0,
                },
                {
                    "instrument_name": "BTC-25SEP26-111000-P",
                    "option_type": "put",
                    "strike": 111_000.0,
                    "quantity": 1.0,
                },
            ],
        }
        return scope

    @staticmethod
    def _input_fingerprint() -> dict[str, object]:
        return {
            "dataset_hash": "dataset-abc",
            "config_hash": "config-abc",
            "feature_schema_version": "feature-schema.v1",
            "unit_semantics_version": "units.v1",
            "continuity_max_gap_days": 2,
            "source_class": "live",
        }

    @staticmethod
    def _lineage() -> dict[str, object]:
        return {
            "verified": True,
            "history_artifact_id": "history:abc",
            "risk_artifact_id": "risk:abc",
            "ranking_artifact_id": "ranking:abc",
        }

    @staticmethod
    def _oos_monitor() -> dict[str, object]:
        return {
            "consecutive_adverse_cohorts": 0,
            "adverse_pass": True,
            "directional_pass": True,
            "base_rate_quality_pass": True,
        }


if __name__ == "__main__":
    unittest.main()
