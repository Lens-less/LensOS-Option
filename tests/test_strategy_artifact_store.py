from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import crypto_options_report.strategy_artifact_store as strategy_artifact_store
from crypto_options_report._canonical import canonical_json_bytes
from crypto_options_report.storage import atomic_write_text
from crypto_options_report.strategy_artifact_store import (
    FORECAST_NAMESPACE,
    HISTORY_NAMESPACE,
    STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION,
    StrategyArtifactStoreCorrupt,
    load_active_strategy_forecast_artifact,
    load_active_strategy_history_artifact,
    load_strategy_forecast_artifact,
    load_strategy_history_artifact,
    set_active_strategy_forecast_artifact,
    set_active_strategy_history_artifact,
    store_strategy_forecast_artifact,
    store_strategy_history_artifact,
)
from crypto_options_report.strategy_forecast import (
    build_calibrated_strategy_forecast_artifact,
)
from crypto_options_report.strategy_history import build_strategy_history_artifact


class StrategyArtifactStoreTests(unittest.TestCase):
    def test_store_and_load_history_artifact_round_trip(self) -> None:
        artifact = self._history_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            path = store_strategy_history_artifact(tmp, artifact)

            self.assertEqual(
                canonical_json_bytes(artifact),
                path.read_bytes(),
            )
            self.assertEqual(
                artifact,
                load_strategy_history_artifact(tmp, artifact["artifact_id"]),
            )

    def test_store_and_load_forecast_artifact_round_trip(self) -> None:
        artifact = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            path = store_strategy_forecast_artifact(tmp, artifact)

            self.assertEqual(
                canonical_json_bytes(artifact),
                path.read_bytes(),
            )
            self.assertEqual(
                artifact,
                load_strategy_forecast_artifact(tmp, artifact["artifact_id"]),
            )

    def test_store_is_idempotent_for_identical_bytes_and_rejects_tampered_existing_file(self) -> None:
        artifact = self._history_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            first = store_strategy_history_artifact(tmp, artifact)
            second = store_strategy_history_artifact(tmp, artifact)

            self.assertEqual(first, second)

            first.write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "content does not match",
            ):
                store_strategy_history_artifact(tmp, artifact)

    def test_wrong_namespace_is_rejected(self) -> None:
        forecast = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "strategy_history"):
                store_strategy_history_artifact(tmp, forecast)

            with self.assertRaisesRegex(ValueError, "strategy forecast artifact_id is invalid"):
                load_strategy_forecast_artifact(
                    tmp,
                    "strategy-history:" + "a" * 64,
                )

    def test_path_traversal_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "artifact_id is invalid"):
                load_strategy_history_artifact(tmp, "../escape")

            with self.assertRaisesRegex(ValueError, "artifact_id is invalid"):
                set_active_strategy_forecast_artifact(tmp, "..\\escape")

    def test_active_pointer_only_targets_verified_history_artifacts(self) -> None:
        artifact = self._history_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            store_strategy_history_artifact(tmp, artifact)
            pointer = set_active_strategy_history_artifact(tmp, artifact["artifact_id"])

            expected = {
                "schema_version": STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION,
                "namespace": HISTORY_NAMESPACE,
                "artifact_id": artifact["artifact_id"],
            }
            self.assertEqual(canonical_json_bytes(expected), pointer.read_bytes())
            self.assertEqual(artifact, load_active_strategy_history_artifact(tmp))

    def test_active_pointer_can_be_written_during_store(self) -> None:
        artifact = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            store_strategy_forecast_artifact(
                tmp,
                artifact,
                update_active_pointer=True,
            )

            self.assertEqual(artifact, load_active_strategy_forecast_artifact(tmp))

    def test_active_pointer_rejects_missing_target(self) -> None:
        missing_id = "strategy-history:" + "b" * 64
        with tempfile.TemporaryDirectory() as tmp:
            pointer = {
                "schema_version": STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION,
                "namespace": HISTORY_NAMESPACE,
                "artifact_id": missing_id,
            }
            atomic_write_text(
                Path(tmp) / HISTORY_NAMESPACE / "active.json",
                canonical_json_bytes(pointer).decode("utf-8"),
            )

            with self.assertRaises(FileNotFoundError):
                load_active_strategy_history_artifact(tmp)

    def test_load_rejects_tampered_artifact_payload(self) -> None:
        artifact = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            path = store_strategy_forecast_artifact(tmp, artifact)
            tampered = dict(artifact)
            tampered["expires_at"] = "2026-11-29T08:00:00Z"
            atomic_write_text(path, canonical_json_bytes(tampered).decode("utf-8"))

            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "strategy forecast artifact .+ is invalid|content does not match|id does not match",
            ):
                load_strategy_forecast_artifact(tmp, artifact["artifact_id"])

    def test_non_regular_files_are_rejected(self) -> None:
        artifact = self._history_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / HISTORY_NAMESPACE
            history_dir.mkdir(parents=True, exist_ok=True)
            target = history_dir / self._encoded_history_filename(artifact["artifact_id"])
            target.mkdir()

            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "is invalid",
            ):
                store_strategy_history_artifact(tmp, artifact)

            pointer_dir = history_dir / "active.json"
            pointer_dir.mkdir()
            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "pointer",
            ):
                load_active_strategy_history_artifact(tmp)

    def test_symlink_files_are_rejected(self) -> None:
        artifact = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            store_strategy_forecast_artifact(tmp, artifact)
            forecast_dir = Path(tmp) / FORECAST_NAMESPACE
            target = forecast_dir / self._encoded_forecast_filename(artifact["artifact_id"])
            target.unlink()
            real_file = forecast_dir / "real.json"
            real_file.write_bytes(canonical_json_bytes(artifact))
            symlink_path = forecast_dir / target.name

            try:
                symlink_path.symlink_to(real_file)
            except (NotImplementedError, OSError):
                self.skipTest("symlink creation is unavailable on this platform")

            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "must not be a symlink",
            ):
                load_strategy_forecast_artifact(tmp, artifact["artifact_id"])

    def test_root_symlink_is_rejected_before_resolution(self) -> None:
        artifact = self._history_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            real_root = Path(tmp) / "real-root"
            real_root.mkdir()
            symlink_root = Path(tmp) / "root-link"
            try:
                symlink_root.symlink_to(real_root, target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest("symlink creation is unavailable on this platform")

            with self.assertRaisesRegex(
                StrategyArtifactStoreCorrupt,
                "must not be a symlink",
            ):
                store_strategy_history_artifact(symlink_root, artifact)

    def test_concurrent_idempotent_store_keeps_one_artifact(self) -> None:
        artifact = self._forecast_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            gate = threading.Barrier(2)
            real_writer = strategy_artifact_store._write_immutable_artifact

            def concurrent_writer(**kwargs: object) -> Path:
                gate.wait(timeout=2)
                return real_writer(**kwargs)

            with patch.object(
                strategy_artifact_store,
                "_write_immutable_artifact",
                side_effect=concurrent_writer,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(store_strategy_forecast_artifact, tmp, artifact)
                        for _ in range(2)
                    ]
                    results = [future.result(timeout=5) for future in futures]

            self.assertEqual(results[0], results[1])
            self.assertEqual(canonical_json_bytes(artifact), results[0].read_bytes())

    def test_concurrent_same_id_different_payloads_never_overwrite_first_writer(self) -> None:
        same_id = "strategy-history:" + "a" * 64
        payload_a = {"artifact_id": same_id, "payload": "alpha"}
        payload_b = {"artifact_id": same_id, "payload": "beta"}
        with tempfile.TemporaryDirectory() as tmp:
            gate = threading.Barrier(2)
            real_writer = strategy_artifact_store._write_immutable_artifact

            def concurrent_writer(**kwargs: object) -> Path:
                gate.wait(timeout=2)
                return real_writer(**kwargs)

            with patch.object(
                strategy_artifact_store,
                "_validated_artifact",
                side_effect=[payload_a, payload_b],
            ), patch.object(
                strategy_artifact_store,
                "_write_immutable_artifact",
                side_effect=concurrent_writer,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(
                            strategy_artifact_store._store_artifact,
                            root=tmp,
                            namespace=HISTORY_NAMESPACE,
                            artifact={"request": "A"},
                        ),
                        pool.submit(
                            strategy_artifact_store._store_artifact,
                            root=tmp,
                            namespace=HISTORY_NAMESPACE,
                            artifact={"request": "B"},
                        ),
                    ]
                    results: list[object] = []
                    for future in futures:
                        try:
                            results.append(future.result(timeout=5))
                        except Exception as exc:
                            results.append(exc)

            successes = [item for item in results if isinstance(item, Path)]
            failures = [
                item for item in results if isinstance(item, StrategyArtifactStoreCorrupt)
            ]
            self.assertEqual(1, len(successes))
            self.assertEqual(1, len(failures))
            self.assertIn("content does not match", str(failures[0]))
            self.assertIn(successes[0].read_bytes(), {
                canonical_json_bytes(payload_a),
                canonical_json_bytes(payload_b),
            })

    @staticmethod
    def _history_artifact() -> dict[str, object]:
        return build_strategy_history_artifact(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            generated_at="2026-08-30T12:00:00Z",
            cohort_ledger=[
                {
                    "cohort_id": f"development-{index + 1}",
                    "expiry_date": f"2027-{index + 1:02d}-15",
                    "sample_role": "development",
                    "source_classification": "development_inventory",
                    "settled": True,
                    "observation_count": 15,
                    "duplicate_observations_dropped": 0,
                    "overlap_observations_dropped": 0,
                    "purged_training_observations": 1,
                    "embargoed_until": f"2027-{index + 1:02d}-20",
                    "volatility_regime": "low_vol" if index % 2 == 0 else "high_vol",
                    "trend_regime": "uptrend" if index % 2 == 0 else "downtrend",
                    "liquidity_regime": "tight" if index % 2 == 0 else "wide",
                }
                for index in range(8)
            ],
            exploratory_metrics={"win_rate": 0.64, "mean_net_r": 0.17},
        )

    @staticmethod
    def _forecast_artifact() -> dict[str, object]:
        return build_calibrated_strategy_forecast_artifact(
            promoted_at="2026-08-30T08:00:00Z",
            expires_at="2026-11-28T08:00:00Z",
            scope={
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
            },
            preregistration={
                "pre_registered": True,
                "frozen_at": "2026-08-12T00:49:54+08:00",
                "protocol_document": "docs/product/exact-strategy-forecast-protocol-v1.md",
                "holdout_status_at_freeze": "sealed",
            },
            holdout_access={
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
            model={
                "id": "forecast-model-v1",
                "digest": "model-digest-001",
                "frozen": True,
            },
            calibrator={
                "id": "isotonic-v1",
                "digest": "calibrator-digest-001",
                "frozen": True,
            },
            validation={
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
            input_fingerprint={
                "dataset_hash": "dataset-abc",
                "config_hash": "config-abc",
                "feature_schema_version": "feature-schema.v1",
                "unit_semantics_version": "units.v1",
                "continuity_max_gap_days": 2,
                "source_class": "live",
            },
            lineage={
                "verified": True,
                "history_artifact_id": "history:abc",
                "risk_artifact_id": "risk:abc",
                "ranking_artifact_id": "ranking:abc",
            },
        )

    @staticmethod
    def _encoded_history_filename(artifact_id: str) -> str:
        return artifact_id.replace(":", "%3A") + ".json"

    @staticmethod
    def _encoded_forecast_filename(artifact_id: str) -> str:
        return artifact_id.replace(":", "%3A") + ".json"


if __name__ == "__main__":
    unittest.main()
