import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from crypto_options_report._canonical import canonical_sha256
from crypto_options_report.analysis_run import (
    AnalysisRequest,
    AnalysisRun,
    EvidenceRecord,
    EvidenceState,
    build_analysis_record,
)
from crypto_options_report.api import (
    RuntimeConfig,
    _report_options_from_query,
    build_api_analysis_record,
    build_api_report,
)
from crypto_options_report.api import (
    build_parser as build_api_parser,
)
from crypto_options_report.cli import build_parser as build_cli_parser
from crypto_options_report.publication import _build_publication_inputs
from crypto_options_report.strategy_brief import validate_strategy_brief
from crypto_options_report.strategy_forecast import (
    build_calibrated_strategy_forecast_artifact,
    build_strategy_forecast_runtime_evidence,
)
from crypto_options_report.strategy_history import (
    EMBARGO_DAYS,
    build_holdout_access_receipt,
    build_strategy_history_artifact,
    build_strategy_history_protocol,
)
from tests import test_strategy_brief_forecast as forecast_fixtures
from tests.test_strategy_brief_contract import _bear_call
from tests.test_strategy_brief_history import (
    _cohort_entries,
    _passing_holdout_metrics,
)

FIXED_CLOCK = "2028-01-02T00:00:05Z"


class StrategyBriefAnalysisIntegrationTests(unittest.TestCase):
    def test_analysis_record_consumes_validated_history_and_binds_identity(self) -> None:
        history = self._validated_history()

        without_history = self._record()
        first = self._record(history_artifacts=(history,))
        second = self._record(history_artifacts=(history,))

        brief = first.project_strategy_brief_v1()
        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("STRATEGIES_AVAILABLE", brief["action"])
        self.assertEqual(1, len(brief["strategies"]))
        strategy = brief["strategies"][0]
        self.assertEqual("VALIDATED", strategy["history"]["status"])
        self.assertEqual(history["artifact_id"], strategy["history"]["artifact_id"])
        self.assertEqual(0.68, strategy["history"]["win_rate"])
        self.assertEqual(0.21, strategy["history"]["mean_net_r"])
        self.assertEqual(first.analysis_run_id, second.analysis_run_id)
        self.assertEqual(first.output_hash, second.output_hash)
        self.assertNotEqual(without_history.analysis_run_id, first.analysis_run_id)

    def test_analysis_record_derives_history_binding_from_legacy_full_artifact(self) -> None:
        history = self._validated_history()
        history["public_summary"].pop("history_binding_key", None)

        strategy = self._record(history_artifacts=(history,)).project_strategy_brief_v1()[
            "strategies"
        ][0]

        self.assertEqual("VALIDATED", strategy["history"]["status"])
        self.assertEqual(history["artifact_id"], strategy["history"]["artifact_id"])

    def test_analysis_record_consumes_calibration_and_retires_on_input_drift(self) -> None:
        artifact, runtime = self._forecast_runtime_evidence()

        calibrated = self._record(forecast_runtime_evidence=(runtime,))
        strategy = calibrated.project_strategy_brief_v1()["strategies"][0]
        self.assertEqual("CALIBRATED", strategy["forecast"]["status"])
        self.assertEqual(artifact["artifact_id"], strategy["forecast"]["artifact_id"])
        self.assertEqual(0.64, strategy["forecast"]["win_rate_low"])
        self.assertEqual(0.70, strategy["forecast"]["win_rate_high"])

        drifted_runtime = copy.deepcopy(runtime)
        drifted_runtime["current_input_fingerprint"]["dataset_hash"] = "dataset-drifted"
        retired = self._record(forecast_runtime_evidence=(drifted_runtime,))
        retired_strategy = retired.project_strategy_brief_v1()["strategies"][0]
        self.assertEqual("RETIRED", retired_strategy["forecast"]["status"])
        self.assertIsNone(retired_strategy["forecast"]["win_rate_low"])
        self.assertIsNone(retired_strategy["forecast"]["win_rate_high"])
        self.assertIn(
            "FORECAST_INPUT_DRIFT",
            retired_strategy["primary_reason_codes"],
        )

    def test_malformed_current_evidence_retires_without_crashing(self) -> None:
        _, runtime = self._forecast_runtime_evidence()
        malformed_runtime = copy.deepcopy(runtime)
        malformed_runtime["current_input_fingerprint"] = "not-an-object"
        malformed_runtime["current_lineage"] = ["not", "an", "object"]

        strategy = self._record(
            forecast_runtime_evidence=(malformed_runtime,)
        ).project_strategy_brief_v1()["strategies"][0]

        self.assertEqual("RETIRED", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])
        self.assertIsNone(strategy["forecast"]["win_rate_high"])
        self.assertIn(
            "FORECAST_CURRENT_EVIDENCE_UNAVAILABLE",
            strategy["primary_reason_codes"],
        )

    def test_same_family_forecast_for_different_card_retires_with_selection_mismatch(self) -> None:
        payload = forecast_fixtures.StrategyBriefForecastTests()._artifact_payload()
        payload["promoted_at"] = "2028-01-01T12:00:00Z"
        payload["expires_at"] = "2028-03-31T12:00:00Z"
        payload["holdout_access"]["accessed_at"] = "2028-01-01T11:55:00Z"
        payload["scope"] = {
            **payload["scope"],
            "structure": "BEAR_CALL_CREDIT_SPREAD",
            "direction": "BEARISH",
            "selection": {
                "expiry_date": "2028-01-28",
                "legs": [
                    {
                        "instrument_name": "BTC-28JAN28-129000-C",
                        "option_type": "call",
                        "strike": 129_000.0,
                        "quantity": -1.0,
                    },
                    {
                        "instrument_name": "BTC-28JAN28-133000-C",
                        "option_type": "call",
                        "strike": 133_000.0,
                        "quantity": 1.0,
                    },
                ],
            },
        }
        artifact = build_calibrated_strategy_forecast_artifact(**payload)
        drifted_runtime = build_strategy_forecast_runtime_evidence(
            artifact=artifact,
            current_input_fingerprint=payload["input_fingerprint"],
            current_lineage=payload["lineage"],
            current_oos_monitor=forecast_fixtures.StrategyBriefForecastTests._oos_monitor(),
        )

        strategy = self._record(
            forecast_runtime_evidence=(drifted_runtime,)
        ).project_strategy_brief_v1()["strategies"][0]

        self.assertEqual("RETIRED", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])
        self.assertIsNone(strategy["forecast"]["win_rate_high"])
        self.assertIn(
            "FORECAST_SELECTION_MISMATCH",
            strategy["primary_reason_codes"],
        )

    def test_forecast_scope_cannot_cross_contaminate_another_family(self) -> None:
        payload = forecast_fixtures.StrategyBriefForecastTests()._artifact_payload()
        payload["promoted_at"] = "2028-01-01T12:00:00Z"
        payload["expires_at"] = "2028-03-31T12:00:00Z"
        payload["holdout_access"]["accessed_at"] = "2028-01-01T11:55:00Z"
        artifact = build_calibrated_strategy_forecast_artifact(**payload)
        runtime = build_strategy_forecast_runtime_evidence(
            artifact=artifact,
            current_input_fingerprint=payload["input_fingerprint"],
            current_lineage=payload["lineage"],
            current_oos_monitor=(
                forecast_fixtures.StrategyBriefForecastTests._oos_monitor()
            ),
        )

        strategy = self._record(
            forecast_runtime_evidence=(runtime,)
        ).project_strategy_brief_v1()["strategies"][0]

        self.assertEqual("UNAVAILABLE", strategy["forecast"]["status"])
        self.assertIsNone(strategy["forecast"]["win_rate_low"])
        self.assertIsNone(strategy["forecast"]["win_rate_high"])

    def test_cli_and_api_load_operator_owned_strategy_evidence_paths(self) -> None:
        history = self._validated_history()
        _, forecast_runtime = self._forecast_runtime_evidence()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path = root / "history.json"
            forecast_path = root / "forecast-runtime.json"
            history_path.write_text(json.dumps(history), encoding="utf-8")
            forecast_path.write_text(json.dumps(forecast_runtime), encoding="utf-8")

            runtime = RuntimeConfig(
                strategy_history_artifacts=(str(history_path),),
                strategy_forecast_runtime_evidence=(str(forecast_path),),
            ).validate()
            options = _report_options_from_query("", runtime=runtime)
            self.assertEqual((str(history_path),), options["strategy_history_artifacts"])
            self.assertEqual(
                (str(forecast_path),),
                options["strategy_forecast_runtime_evidence"],
            )

            baseline = build_analysis_record(generated_at=FIXED_CLOCK)
            loaded = build_api_analysis_record(
                generated_at=FIXED_CLOCK,
                strategy_history_artifacts=(str(history_path),),
                strategy_forecast_runtime_evidence=(str(forecast_path),),
            )
            self.assertNotEqual(baseline.analysis_run_id, loaded.analysis_run_id)

            cli_args = build_cli_parser().parse_args(
                [
                    "report",
                    "--strategy-history-artifact",
                    str(history_path),
                    "--strategy-forecast-runtime-evidence",
                    str(forecast_path),
                ]
            )
            self.assertEqual([str(history_path)], cli_args.strategy_history_artifact)
            api_args = build_api_parser().parse_args(
                [
                    "--strategy-history-artifact",
                    str(history_path),
                    "--strategy-forecast-runtime-evidence",
                    str(forecast_path),
                ]
            )
            self.assertEqual([str(forecast_path)], api_args.strategy_forecast_runtime_evidence)

    def test_programmatic_api_report_forwards_strategy_evidence_paths(self) -> None:
        with patch("crypto_options_report.api.build_api_analysis_record") as builder:
            builder.return_value.project_research_report_v1.return_value = {
                "schema_version": "research_report.v1"
            }
            report = build_api_report(
                strategy_history_artifacts=("history.json",),
                strategy_forecast_runtime_evidence=("forecast.json",),
            )

        self.assertEqual("research_report.v1", report["schema_version"])
        self.assertEqual(
            ("history.json",),
            builder.call_args.kwargs["strategy_history_artifacts"],
        )
        self.assertEqual(
            ("forecast.json",),
            builder.call_args.kwargs["strategy_forecast_runtime_evidence"],
        )

    def test_publication_inputs_bind_strategy_evidence_content_not_paths(self) -> None:
        history = self._validated_history()
        _, runtime = self._forecast_runtime_evidence()
        inputs = _build_publication_inputs(
            snapshot_payload={"source": "snapshot"},
            underlying_payload={"source": "underlying"},
            dvol_payload={"source": "dvol"},
            signal_payload={"source": "signal"},
            series_payload={"source": "series"},
            publication_history_payload={"source": "publication-history"},
            strategy_history_artifact_payloads=(history,),
            strategy_forecast_runtime_evidence_payloads=(runtime,),
            published_dt=datetime(2028, 1, 2, tzinfo=UTC),
            git_provenance={"git_sha": None},
            site_origin="https://example.test",
        )

        self.assertEqual(
            [canonical_sha256(history)],
            inputs["strategy_history_artifacts"],
        )
        self.assertEqual(
            [canonical_sha256(runtime)],
            inputs["strategy_forecast_runtime_evidence"],
        )

    def _record(
        self,
        *,
        history_artifacts=(),
        forecast_runtime_evidence=(),
    ):
        projection = {
            "schema_version": "research_report.v1",
            "generated_at": FIXED_CLOCK,
            "data_status": {
                "status": "validated",
                "source": "deribit:public_api",
                "snapshot_captured_at": FIXED_CLOCK,
                "quality_gate": {"reason_codes": []},
            },
            "data_trust": {"reason_codes": []},
            "permission_state": {
                "status": "validated",
                "primary_regime_label": "Range",
                "volatility_inputs": {"dvol_percentile": 0.80},
            },
            "vol_surface_status": {"status": "validated"},
            "candidate_research": {},
            "ev_candidate_scanner": {
                "ranked_candidates": [self._candidate()],
            },
            "account_status": {"status": "missing"},
        }
        digest = "a" * 64
        evidence = EvidenceRecord(
            evidence_id=f"market:{digest}",
            kind="market_snapshot",
            state=EvidenceState.TRUSTED,
            source="deribit:public_api",
            observed_at=FIXED_CLOCK,
            received_at=FIXED_CLOCK,
            expires_at="2028-01-02T00:10:05Z",
            authenticated=True,
            payload_ref=f"sha256:{digest}",
            payload_hash=digest,
            reason_codes=(),
            trust_consecutive_passes=6,
            trust_observation_seconds=60.0,
        )
        request = AnalysisRequest.from_projection(
            evaluation_clock=FIXED_CLOCK,
            report_projection=projection,
            market_snapshot=None,
            market_evidence=evidence,
            strategy_history_artifacts=history_artifacts,
            strategy_forecast_runtime_evidence=forecast_runtime_evidence,
        )
        return AnalysisRun().evaluate(request)

    @staticmethod
    def _candidate() -> dict:
        candidate = _bear_call()
        candidate["valid_until"] = "2028-01-02T00:00:55Z"
        for leg in candidate["structure_legs"]:
            leg["instrument_name"] = leg["instrument_name"].replace(
                "25SEP26", "28JAN28"
            )
            leg["observed_at"] = "2028-01-02T00:00:02Z"
            leg["expiry_date"] = "2028-01-28"
        return candidate

    @staticmethod
    def _validated_history() -> dict:
        protocol = build_strategy_history_protocol(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            frozen_at="2026-08-30T12:00:00Z",
        )
        receipt = build_holdout_access_receipt(
            accessed_at="2028-01-01T00:00:00Z",
            command_hash="cmd-analysis-integration",
            input_hash="input-analysis-integration",
            result_hash="result-analysis-integration",
            verified_source="future_holdout",
        )
        return build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at=FIXED_CLOCK,
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
                    "fold_id": "fold-analysis-integration",
                    "train_end": "2027-04-15T08:00:00Z",
                    "validation_start": "2027-05-20T08:00:00Z",
                    "validation_end": "2027-06-15T08:00:00Z",
                    "embargo_days": EMBARGO_DAYS,
                }
            ],
        )

    def _forecast_runtime_evidence(self):
        payload = forecast_fixtures.StrategyBriefForecastTests()._artifact_payload()
        payload["promoted_at"] = "2028-01-01T12:00:00Z"
        payload["expires_at"] = "2028-03-31T12:00:00Z"
        payload["holdout_access"]["accessed_at"] = "2028-01-01T11:55:00Z"
        payload["scope"] = {
            **payload["scope"],
            "structure": "BEAR_CALL_CREDIT_SPREAD",
            "direction": "BEARISH",
            "selection": {
                "expiry_date": "2028-01-28",
                "legs": [
                    {
                        "instrument_name": "BTC-28JAN28-128000-C",
                        "option_type": "call",
                        "strike": 128_000.0,
                        "quantity": -1.0,
                    },
                    {
                        "instrument_name": "BTC-28JAN28-132000-C",
                        "option_type": "call",
                        "strike": 132_000.0,
                        "quantity": 1.0,
                    },
                ],
            },
        }
        artifact = build_calibrated_strategy_forecast_artifact(**payload)
        runtime = build_strategy_forecast_runtime_evidence(
            artifact=artifact,
            current_input_fingerprint=payload["input_fingerprint"],
            current_lineage=payload["lineage"],
            current_oos_monitor=(
                forecast_fixtures.StrategyBriefForecastTests._oos_monitor()
            ),
        )
        return artifact, runtime


if __name__ == "__main__":
    unittest.main()
