import json
import subprocess
import sys
import unittest
from pathlib import Path

from crypto_options_report.path_risk import (
    build_path_risk_distribution_report,
    build_path_risk_report_from_fixture,
    load_path_risk_fixture,
)


class PathRiskDistributionReportTests(unittest.TestCase):
    def test_candidate_economic_domains_reject_non_finite_non_positive_and_boolean_values(self):
        cases = (
            ("current_spot", float("nan"), "current_spot must be finite and positive"),
            ("current_spot", True, "current_spot must be finite and positive"),
            ("strike", 0.0, "strike must be finite and positive"),
            ("strike", True, "strike must be finite and positive"),
            ("long_strike", float("nan"), "long_strike must be finite and positive"),
            ("horizon_days", 0, "horizon_days must be a positive integer"),
            ("horizon_days", True, "horizon_days must be a positive integer"),
            (
                "entry_credit_usdc",
                True,
                "entry_credit_usdc must be finite and non-negative",
            ),
            ("contract_size", 0.0, "contract_size must be finite and positive"),
            (
                "starting_nav_usdc",
                float("inf"),
                "starting_nav_usdc must be finite and positive",
            ),
            (
                "starting_nav_usdc",
                0.0,
                "starting_nav_usdc must be finite and positive",
            ),
            (
                "current_abs_delta",
                1.1,
                "current_abs_delta must be finite and between 0 and 1",
            ),
            (
                "delta_cross_up_return",
                float("nan"),
                "delta_cross_up_return must be finite and non-negative",
            ),
            (
                "vega_usdc_per_abs_vol",
                -1.0,
                "vega_usdc_per_abs_vol must be finite and non-negative",
            ),
        )
        for field_name, invalid_value, expected_message in cases:
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                payload = load_path_risk_fixture(self._fixture_path())
                payload["candidate"][field_name] = invalid_value

                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

    def test_candidate_structure_enforces_credit_spread_economic_invariants(self):
        cases = (
            (
                # A structure name the module does not know cannot be given a
                # payoff by guessing; it needs its legs spelled out.
                {"structure": "unsupported_structure"},
                "requires an explicit legs list",
            ),
            (
                {"structure": "call_credit_spread", "long_strike": None},
                "call_credit_spread requires long_strike",
            ),
            (
                {"structure": "call_credit_spread", "long_strike": 120000.0},
                "call_credit_spread long_strike must be greater than strike",
            ),
            (
                {"structure": "call_credit_spread", "long_strike": 110000.0},
                "call_credit_spread long_strike must be greater than strike",
            ),
            (
                {
                    "structure": "call_credit_spread",
                    "long_strike": 121000.0,
                    "entry_credit_usdc": 1000.01,
                },
                "call_credit_spread entry_credit_usdc must not exceed spread width",
            ),
        )
        for candidate_override, expected_message in cases:
            with self.subTest(candidate_override=candidate_override):
                payload = load_path_risk_fixture(self._fixture_path())
                payload["candidate"].update(candidate_override)
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

        payload = load_path_risk_fixture(self._fixture_path())
        payload["candidate"].update(
            {
                "structure": "call_credit_spread",
                "long_strike": 130000.0,
            }
        )
        report = build_path_risk_distribution_report(payload)
        self.assertEqual("call_credit_spread", report["candidate"]["structure"])
        self.assertEqual(130000.0, report["candidate"]["long_strike"])

    def test_similarity_inputs_reject_invalid_numeric_domains(self):
        cases = (
            (
                lambda payload: payload["candidate"].__setitem__("feature_vector", {}),
                "candidate feature_vector must be a non-empty mapping",
            ),
            (
                lambda payload: payload["candidate"]["feature_vector"].__setitem__(
                    "trend_7d", True
                ),
                "candidate feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload["candidate"]["feature_vector"].__setitem__(
                    "trend_7d", float("nan")
                ),
                "candidate feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload["candidate"]["feature_vector"].__setitem__(
                    "trend_7d", "0.16"
                ),
                "candidate feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload["historical_paths"][0].__setitem__(
                    "feature_vector", []
                ),
                "historical path feature_vector must be a non-empty mapping",
            ),
            (
                lambda payload: payload["historical_paths"][0][
                    "feature_vector"
                ].__setitem__("trend_7d", True),
                "historical path feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload["historical_paths"][0][
                    "feature_vector"
                ].__setitem__("trend_7d", float("inf")),
                "historical path feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload["historical_paths"][0][
                    "feature_vector"
                ].__setitem__("trend_7d", "0.17"),
                "historical path feature_vector.trend_7d must be finite numeric",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "similarity_bandwidth", True
                ),
                "similarity_bandwidth must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "similarity_bandwidth", float("nan")
                ),
                "similarity_bandwidth must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "similarity_bandwidth", 0.0
                ),
                "similarity_bandwidth must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "similarity_bandwidth", -0.1
                ),
                "similarity_bandwidth must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "similarity_bandwidth", "0.08"
                ),
                "similarity_bandwidth must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "min_effective_sample_size", True
                ),
                "min_effective_sample_size must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "min_effective_sample_size", float("nan")
                ),
                "min_effective_sample_size must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "min_effective_sample_size", 0.0
                ),
                "min_effective_sample_size must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "min_effective_sample_size", -1.0
                ),
                "min_effective_sample_size must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "min_effective_sample_size", "2.0"
                ),
                "min_effective_sample_size must be finite and positive",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "confidence_penalty_multiplier", True
                ),
                "confidence_penalty_multiplier must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "confidence_penalty_multiplier", float("inf")
                ),
                "confidence_penalty_multiplier must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "confidence_penalty_multiplier", -0.1
                ),
                "confidence_penalty_multiplier must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "confidence_penalty_multiplier", 1.01
                ),
                "confidence_penalty_multiplier must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "confidence_penalty_multiplier", "0.5"
                ),
                "confidence_penalty_multiplier must be finite and between 0 and 1",
            ),
        )
        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                payload = load_path_risk_fixture(self._fixture_path())
                mutate(payload)

                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

    def test_path_numeric_payloads_require_native_numbers(self):
        cases = (
            (
                "candidate.current_spot",
                lambda payload: payload["candidate"].__setitem__(
                    "current_spot", "100000.0"
                ),
            ),
            (
                "candidate.strike",
                lambda payload: payload["candidate"].__setitem__(
                    "strike", "120000.0"
                ),
            ),
            (
                "candidate.long_strike",
                lambda payload: payload["candidate"].__setitem__(
                    "long_strike", "130000.0"
                ),
            ),
            (
                "candidate.entry_credit_usdc",
                lambda payload: payload["candidate"].__setitem__(
                    "entry_credit_usdc", "470.0"
                ),
            ),
            (
                "candidate.contract_size",
                lambda payload: payload["candidate"].__setitem__(
                    "contract_size", "1.0"
                ),
            ),
            (
                "candidate.starting_nav_usdc",
                lambda payload: payload["candidate"].__setitem__(
                    "starting_nav_usdc", "100000.0"
                ),
            ),
            (
                "candidate.current_abs_delta",
                lambda payload: payload["candidate"].__setitem__(
                    "current_abs_delta", "0.10"
                ),
            ),
            (
                "candidate.delta_cross_up_return",
                lambda payload: payload["candidate"].__setitem__(
                    "delta_cross_up_return", "0.12"
                ),
            ),
            (
                "candidate.vega_usdc_per_abs_vol",
                lambda payload: payload["candidate"].__setitem__(
                    "vega_usdc_per_abs_vol", "900.0"
                ),
            ),
            (
                "candidate.target_realized_vol",
                lambda payload: payload["candidate"].__setitem__(
                    "target_realized_vol", "0.64"
                ),
            ),
            (
                "candidate.regime_scores",
                lambda payload: payload["candidate"]["regime_scores"].__setitem__(
                    "range", "0.32"
                ),
            ),
            (
                "historical.source_realized_vol",
                lambda payload: payload["historical_paths"][0].__setitem__(
                    "source_realized_vol", "0.60"
                ),
            ),
            (
                "historical.regime_scores",
                lambda payload: payload["historical_paths"][0][
                    "regime_scores"
                ].__setitem__("range", "0.30"),
            ),
            (
                "historical.returns",
                lambda payload: payload["historical_paths"][0]["returns"].__setitem__(
                    0, "0.10"
                ),
            ),
            (
                "bootstrap_source_returns",
                lambda payload: payload["bootstrap_source_returns"].__setitem__(
                    0, "0.01"
                ),
            ),
            (
                "bootstrap_source_realized_vol",
                lambda payload: payload.__setitem__(
                    "bootstrap_source_realized_vol", "0.60"
                ),
            ),
            (
                "random_seed",
                lambda payload: payload.__setitem__("random_seed", "17"),
            ),
            (
                "stress.path_returns",
                lambda payload: payload["stress_scenarios"][0][
                    "path_returns"
                ].__setitem__(0, "0.10"),
            ),
            (
                "stress.weight",
                lambda payload: payload["stress_scenarios"][0].__setitem__(
                    "weight", "0.03"
                ),
            ),
            (
                "stress.iv_jump",
                lambda payload: payload["stress_scenarios"][0].__setitem__(
                    "iv_jump", "0.15"
                ),
            ),
            (
                "stress.liquidity_exit_cost_usdc",
                lambda payload: payload["stress_scenarios"][0].__setitem__(
                    "liquidity_exit_cost_usdc", "120.0"
                ),
            ),
        )
        for field_name, mutate in cases:
            with self.subTest(field_name=field_name):
                payload = load_path_risk_fixture(self._fixture_path())
                mutate(payload)
                with self.assertRaises(ValueError):
                    build_path_risk_distribution_report(payload)

    def test_similarity_underflow_triggers_conservative_fallback(self):
        payload = load_path_risk_fixture(self._fixture_path())
        payload["candidate"]["feature_vector"] = {"extreme": 1e308}
        for path in payload["historical_paths"] + payload["fallback_pool"]:
            path["feature_vector"] = {"extreme": -1e308}

        report = build_path_risk_distribution_report(payload)

        similarity = report["path_sampling"]["similarity_weighted"]
        self.assertEqual(0.0, similarity["initial_effective_sample_size"])
        self.assertTrue(similarity["fallback_triggered"])
        self.assertEqual("hierarchical_pooling", similarity["fallback_mode"])
        self.assertTrue(
            similarity["restrictions"]["confidence_penalty_applied"]
        )
        self.assertAlmostEqual(
            1.0,
            sum(item["weight"] for item in similarity["normalized_weights"]),
        )

    def test_path_config_requires_known_mapping_and_native_finite_values(self):
        invalid_payload_configs = (
            ([], "path risk config must be a mapping"),
            (
                {"unknown_threshold": 1.0},
                "unknown path risk config fields",
            ),
            (
                {"historical_group_weight": "0.75"},
                "historical_group_weight must be finite and between 0 and 1",
            ),
            (
                {"min_effective_sample_size": 0.5},
                "min_effective_sample_size must be finite and positive.*at least 1",
            ),
        )
        for invalid_config, expected_message in invalid_payload_configs:
            with self.subTest(invalid_config=invalid_config):
                payload = load_path_risk_fixture(self._fixture_path())
                payload["config"] = invalid_config
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

        payload = load_path_risk_fixture(self._fixture_path())
        for invalid_config, expected_message in (
            ([], "path risk config must be a mapping"),
            (
                {"unknown_threshold": 1.0},
                "unknown path risk config fields",
            ),
            (
                {"min_effective_sample_size": float("nan")},
                "min_effective_sample_size must be finite and positive",
            ),
        ):
            with self.subTest(explicit_config=invalid_config):
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(
                        payload,
                        config=invalid_config,
                    )

    def test_every_path_config_field_rejects_coercive_or_non_finite_values(self):
        positive_fields = {
            "similarity_bandwidth": (
                False,
                True,
                "0.08",
                float("nan"),
                float("inf"),
                float("-inf"),
                -0.1,
                0.0,
            ),
        }
        minimum_ess_values = (
            False,
            True,
            "2.0",
            float("nan"),
            float("inf"),
            float("-inf"),
            -1.0,
            0.0,
            0.5,
        )
        unit_interval_values = (
            False,
            True,
            "0.5",
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
            1.1,
        )
        invalid_by_field = {
            **positive_fields,
            "min_effective_sample_size": minimum_ess_values,
            **dict.fromkeys(("historical_group_weight", "bootstrap_group_weight", "stress_group_weight", "stress_mixture_min_weight", "confidence_penalty_multiplier"), unit_interval_values),
        }
        for field_name, invalid_values in invalid_by_field.items():
            for invalid_value in invalid_values:
                with self.subTest(
                    field_name=field_name,
                    invalid_value=invalid_value,
                ):
                    payload = load_path_risk_fixture(self._fixture_path())
                    payload.setdefault("config", {})[field_name] = invalid_value
                    with self.assertRaises(ValueError):
                        build_path_risk_distribution_report(payload)

        for invalid_floor in unit_interval_values:
            with self.subTest(payload_stress_floor=invalid_floor):
                payload = load_path_risk_fixture(self._fixture_path())
                payload["stress_mixture_min_weight"] = invalid_floor
                with self.assertRaises(ValueError):
                    build_path_risk_distribution_report(payload)

        payload = load_path_risk_fixture(self._fixture_path())
        payload.setdefault("config", {})["min_effective_sample_size"] = float(
            "nan"
        )
        report = build_path_risk_distribution_report(
            payload,
            config={"min_effective_sample_size": 2.0},
        )
        self.assertTrue(
            report["path_sampling"]["similarity_weighted"]["fallback_triggered"]
        )

        for confidence_boundary in (0.0, 1.0):
            with self.subTest(confidence_boundary=confidence_boundary):
                payload = load_path_risk_fixture(self._fixture_path())
                payload.setdefault("config", {})[
                    "confidence_penalty_multiplier"
                ] = confidence_boundary
                build_path_risk_distribution_report(payload)

    def test_path_and_bootstrap_cardinality_domains_fail_before_sampling(self):
        cases = (
            (
                lambda payload: payload.__setitem__("bootstrap_block_length", 0),
                "bootstrap_block_length must be a positive integer",
            ),
            (
                lambda payload: payload.__setitem__("bootstrap_block_length", True),
                "bootstrap_block_length must be a positive integer",
            ),
            (
                lambda payload: payload.__setitem__("bootstrap_path_count", 0),
                "bootstrap_path_count must be a positive integer",
            ),
            (
                lambda payload: payload.__setitem__("bootstrap_path_count", True),
                "bootstrap_path_count must be a positive integer",
            ),
            (
                lambda payload: payload.__setitem__("bootstrap_source_returns", []),
                "bootstrap_source_returns must contain at least one return",
            ),
            (
                lambda payload: payload.__setitem__("historical_paths", []),
                "historical_paths must contain at least one path",
            ),
            (
                lambda payload: payload["historical_paths"][0].__setitem__("returns", []),
                "path returns must contain at least one return",
            ),
            (
                lambda payload: payload["historical_paths"][0].__setitem__(
                    "horizon_days", 999
                ),
                "historical path horizon_days must equal candidate horizon_days",
            ),
            (
                lambda payload: payload["historical_paths"][0].__setitem__(
                    "returns", [0.01]
                ),
                "historical path returns length must equal horizon_days",
            ),
        )
        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                payload = load_path_risk_fixture(self._fixture_path())
                mutate(payload)

                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

    def test_mixture_weights_reject_non_finite_boolean_and_out_of_range_values(self):
        cases = (
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "historical_group_weight", -0.1
                ),
                "historical_group_weight must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "bootstrap_group_weight", float("nan")
                ),
                "bootstrap_group_weight must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "stress_group_weight", True
                ),
                "stress_group_weight must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.setdefault("config", {}).__setitem__(
                    "stress_mixture_min_weight", 1.1
                ),
                "stress_mixture_min_weight must be finite and between 0 and 1",
            ),
            (
                lambda payload: payload.__setitem__("stress_mixture_min_weight", 2.0),
                "stress_mixture_min_weight must be finite and between 0 and 1",
            ),
        )
        for mutate, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                payload = load_path_risk_fixture(self._fixture_path())
                mutate(payload)

                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

        payload = load_path_risk_fixture(self._fixture_path())
        payload["config"] = {
            "historical_group_weight": 0.0,
            "bootstrap_group_weight": 0.0,
            "stress_group_weight": 0.0,
            "stress_mixture_min_weight": 0.0,
        }
        payload["stress_mixture_min_weight"] = 0.0
        with self.assertRaisesRegex(
            ValueError,
            "mixture group weights must contain positive mass",
        ):
            build_path_risk_distribution_report(payload)

    def test_stress_only_mixture_normalizes_to_complete_probability_mass(self):
        payload = load_path_risk_fixture(self._fixture_path())
        payload.setdefault("config", {}).update(
            {
                "historical_group_weight": 0.0,
                "bootstrap_group_weight": 0.0,
                "stress_group_weight": 0.1,
                "stress_mixture_min_weight": 0.1,
            }
        )
        payload["stress_mixture_min_weight"] = 0.1
        for scenario in payload["stress_scenarios"]:
            scenario["path_returns"] = [0.25] + [0.0] * 6

        report = build_path_risk_distribution_report(payload)

        group_weights = report["stress_mixture"]["group_weights"]
        self.assertAlmostEqual(1.0, sum(group_weights.values()), places=12)
        self.assertAlmostEqual(1.0, report["stress_mixture"]["applied_weight"], places=12)
        self.assertAlmostEqual(1.0, report["distributions"]["p_touch"], places=12)

    def test_stress_mixture_rejects_invalid_scenario_mass_and_cost_inputs(self):
        cases = (
            (
                "weight",
                -0.1,
                "stress scenario weight must be finite and non-negative",
            ),
            (
                "weight",
                True,
                "stress scenario weight must be finite and non-negative",
            ),
            (
                "iv_jump",
                float("nan"),
                "stress scenario iv_jump must be finite and non-negative",
            ),
            (
                "liquidity_exit_cost_usdc",
                -1.0,
                "stress scenario liquidity_exit_cost_usdc must be finite and non-negative",
            ),
        )
        for field_name, invalid_value, expected_message in cases:
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                payload = load_path_risk_fixture(self._fixture_path())
                payload["stress_scenarios"][0][field_name] = invalid_value

                with self.assertRaisesRegex(ValueError, expected_message):
                    build_path_risk_distribution_report(payload)

        payload = load_path_risk_fixture(self._fixture_path())
        for scenario in payload["stress_scenarios"]:
            scenario["weight"] = 0.0
        with self.assertRaisesRegex(
            ValueError,
            "stress scenario weights must contain positive mass",
        ):
            build_path_risk_distribution_report(payload)

    def test_stress_mixture_rejects_overflow_and_preserves_declared_mass(self):
        payload = load_path_risk_fixture(self._fixture_path())
        payload["stress_scenarios"][0]["weight"] = 1e308
        payload["stress_scenarios"][1]["weight"] = 1e308
        with self.assertRaisesRegex(
            ValueError,
            "stress scenario weight total must remain finite and positive",
        ):
            build_path_risk_distribution_report(payload)

        valid_payload = load_path_risk_fixture(self._fixture_path())
        valid_payload["stress_scenarios"][-1]["weight"] = 0.0
        report = build_path_risk_distribution_report(valid_payload)
        stress = report["stress_mixture"]
        self.assertAlmostEqual(
            stress["applied_weight"],
            sum(scenario["mixture_weight"] for scenario in stress["scenarios"]),
            places=12,
        )

    def test_path_risk_report_rejects_non_finite_derived_or_nested_numbers(self):
        cases = (
            (
                lambda payload: payload["candidate"].__setitem__(
                    "contract_size", 1e308
                ),
                "path risk report contains non-finite number",
            ),
            (
                lambda payload: payload["candidate"].__setitem__(
                    "starting_nav_usdc", 5e-324
                ),
                "path risk report contains non-finite number",
            ),
            (
                lambda payload: payload["stress_scenarios"][0].__setitem__(
                    "iv_jump", 1e308
                ),
                "path risk report contains non-finite number",
            ),
            (
                lambda payload: payload["candidate"]["regime_scores"].__setitem__(
                    "event", float("nan")
                ),
                "candidate regime_scores.event must be finite numeric",
            ),
        )
        for mutate, expected_message in cases:
            with self.subTest(mutate=mutate):
                payload = load_path_risk_fixture(self._fixture_path())
                mutate(payload)
                with self.assertRaisesRegex(
                    ValueError,
                    expected_message,
                ):
                    build_path_risk_distribution_report(payload)

        report = build_path_risk_distribution_report(
            load_path_risk_fixture(self._fixture_path())
        )
        json.dumps(report, allow_nan=False)

    def test_path_records_include_required_fields_and_touch_uses_path_maximum(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        self.assertEqual("path_risk_distribution_report.v1", report["schema_version"])
        first = report["historical_path_records"][0]
        for field_name in (
            "start_time",
            "horizon_days",
            "regime_scores",
            "feature_vector",
            "returns",
            "normalized_spot_path",
            "max_up_return",
            "terminal_return",
        ):
            self.assertIn(field_name, first)

        self.assertTrue(report["report_flags"]["path_maximum_touch"])
        self.assertGreater(
            report["distributions"]["p_touch"],
            report["diagnostics"]["terminal_only_touch_proxy"],
        )

    def test_sparse_effective_sample_size_triggers_conservative_fallback(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        similarity = report["path_sampling"]["similarity_weighted"]
        self.assertLess(
            similarity["initial_effective_sample_size"],
            similarity["minimum_effective_sample_size"],
        )
        self.assertTrue(similarity["fallback_triggered"])
        self.assertEqual("hierarchical_pooling", similarity["fallback_mode"])
        self.assertFalse(similarity["restrictions"]["naked_short_allowed"])
        self.assertTrue(similarity["restrictions"]["spread_only_required"])
        self.assertTrue(similarity["restrictions"]["confidence_penalty_applied"])

    def test_circular_block_bootstrap_preserves_multi_day_structure(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        bootstrap = report["path_sampling"]["bootstrap"]
        self.assertEqual("circular_block_bootstrap", bootstrap["method"])
        source = bootstrap["source_returns"]
        valid_pairs = {
            (source[index], source[(index + 1) % len(source)])
            for index in range(len(source))
        }
        for path in bootstrap["paths"]:
            for block in path["sampled_blocks"]:
                self.assertEqual(2, len(block["returns"]))
                self.assertIn(tuple(block["returns"]), valid_pairs)

    def test_stress_mixture_floor_and_stress_loss_are_reported(self):
        report = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        stress = report["stress_mixture"]
        self.assertGreaterEqual(
            stress["applied_weight"],
            stress["configured_min_weight"],
        )
        self.assertEqual(3, len(stress["scenarios"]))
        self.assertGreater(report["distributions"]["stress_loss_usdc"], 0.0)
        self.assertGreater(report["distributions"]["cvar_99_usdc"], 0.0)

    def test_cli_path_risk_command_is_reproducible(self):
        expected = build_path_risk_report_from_fixture(
            self._fixture_path(),
            generated_at="2026-07-07T10:30:00Z",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "path-risk",
                "--fixture",
                str(self._fixture_path()),
                "--generated-at",
                "2026-07-07T10:30:00Z",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = json.loads(completed.stdout)
        self.assertEqual(expected, actual)

    def _fixture_path(self) -> Path:
        return Path(__file__).with_name("fixtures") / "path_risk_distribution_fixture.json"


if __name__ == "__main__":
    unittest.main()
