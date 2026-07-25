import unittest

from crypto_options_report.position_management import (
    classify_position_state,
    evaluate_position_replay,
    validate_position_management_report,
    build_position_management_report,
)


class PositionManagementReplayTests(unittest.TestCase):
    @staticmethod
    def _complete_position(**overrides):
        position = {
            "position_id": "complete-position",
            "current_delta": 0.10,
            "loss_multiple": 0.5,
            "collected_premium_usdc": 100.0,
            "hedge": {
                "realized_funding_usdc": 1.0,
                "trading_fee_usdc": 1.0,
                "slippage_usdc": 1.0,
            },
            "roll_candidate": {
                "ev_before": 1.0,
                "ev_after": 2.0,
                "p_touch_before": 0.4,
                "p_touch_after": 0.3,
                "stress_loss_before": 700.0,
                "stress_loss_after": 500.0,
            },
            "protective_spread": {
                "stress_loss_before": 800.0,
                "stress_loss_after": 420.0,
                "net_short_gamma_before": 0.012,
                "net_short_gamma_after": 0.004,
            },
        }
        position.update(overrides)
        return position

    def test_state_thresholds_cover_delta_and_loss_bands(self):
        self.assertEqual("NORMAL", classify_position_state(current_delta=0.20, loss_multiple=0.5))
        self.assertEqual("CAUTION", classify_position_state(current_delta=0.24, loss_multiple=0.5))
        self.assertEqual("DEFENSE", classify_position_state(current_delta=0.30, loss_multiple=0.5))
        self.assertEqual("EXIT_REQUIRED", classify_position_state(current_delta=0.38, loss_multiple=0.5))
        self.assertEqual("FORCE_CLOSE", classify_position_state(current_delta=0.41, loss_multiple=0.5))
        self.assertEqual("FORCE_CLOSE", classify_position_state(current_delta=0.10, loss_multiple=0.5, breakout_kill=True))

    def test_unknown_portfolio_action_fails_closed(self):
        self.assertEqual(
            "PAUSED",
            classify_position_state(
                current_delta=0.10,
                loss_multiple=0.5,
                portfolio_final_action="halt_systm",
            ),
        )

    def test_portfolio_exit_actions_set_a_minimum_position_state(self):
        self.assertEqual(
            "FORCE_CLOSE",
            classify_position_state(
                current_delta=0.10,
                loss_multiple=0.5,
                portfolio_final_action="close_batch",
            ),
        )
        self.assertEqual(
            "DEFENSE",
            classify_position_state(
                current_delta=0.10,
                loss_multiple=0.5,
                portfolio_final_action="reduce_existing",
            ),
        )

    def test_delta_038_exit_required_allows_only_protective_spread_exception(self):
        replay = evaluate_position_replay(
            position=self._complete_position(
                position_id="exit-required",
                current_delta=0.38,
                loss_multiple=1.5,
            ),
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual("EXIT_REQUIRED", replay["state"])
        self.assertIn("exit_required", replay["allowed_actions"])
        self.assertIn("convert_to_defined_risk_spread", replay["allowed_actions"])
        self.assertIn("risk_expanding_roll", replay["forbidden_actions"])
        self.assertTrue(replay["protective_spread_exception"]["allowed"])

    def test_active_roll_is_prohibited_outside_normal_or_caution(self):
        replay = evaluate_position_replay(
            position=self._complete_position(
                position_id="defense",
                current_delta=0.30,
                loss_multiple=2.2,
                roll_candidate={
                    "ev_before": 1.0,
                    "ev_after": 5.0,
                    "p_touch_before": 0.4,
                    "p_touch_after": 0.2,
                    "stress_loss_before": 700.0,
                    "stress_loss_after": 500.0,
                },
            ),
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual("DEFENSE", replay["state"])
        self.assertIn("active_roll", replay["forbidden_actions"])

    def test_hedge_cost_can_trigger_reevaluation(self):
        replay = evaluate_position_replay(
            position=self._complete_position(
                position_id="hedge-cost",
                current_delta=0.24,
                loss_multiple=1.0,
                hedge={
                    "realized_funding_usdc": 12.0,
                    "trading_fee_usdc": 5.0,
                    "slippage_usdc": 7.0,
                },
            ),
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        hedge = replay["hedge_events"][0]
        self.assertGreater(hedge["cost_to_premium_ratio"], 0.20)
        self.assertTrue(hedge["reevaluation_required"])
        self.assertIn("reevaluate_position", replay["allowed_actions"])

    def test_empty_account_does_not_synthesize_position_replays(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual([], validate_position_management_report(report))
        self.assertEqual("empty", report["status"])
        self.assertEqual("NO_OPEN_POSITIONS", report["reason_code"])
        self.assertEqual([], report["replays"])
        self.assertEqual(0, report["summary"]["positions_observed"])
        self.assertEqual(0, report["summary"]["positions_evaluated"])

    def test_empty_status_rejects_replay_leaks_without_validating_rows(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )
        report["replays"] = [{"state": "UNKNOWN"}]

        errors = validate_position_management_report(report)

        self.assertIn(
            "empty position management must not expose replays",
            errors,
        )
        self.assertNotIn(
            "position_management replay has unknown state",
            errors,
        )

    def test_explicit_position_missing_economic_evidence_is_unavailable(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
            positions=[
                {
                    "position_id": "partial",
                    "current_delta": 0.22,
                    "loss_multiple": 1.0,
                    "collected_premium_usdc": 100.0,
                }
            ],
        )

        self.assertEqual([], validate_position_management_report(report))
        self.assertEqual("unavailable", report["status"])
        self.assertEqual("MISSING_POSITION_MANAGEMENT_EVIDENCE", report["reason_code"])
        self.assertEqual([], report["replays"])
        self.assertIn("hedge.realized_funding_usdc", report["missing_evidence"])
        self.assertIn("roll_candidate.ev_before", report["missing_evidence"])
        self.assertIn("protective_spread.stress_loss_before", report["missing_evidence"])
        self.assertNotIn(0.0, report["missing_evidence"])

    def test_unavailable_status_rejects_replay_leaks_without_validating_rows(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
            positions=[{"position_id": "partial"}],
        )
        report["replays"] = [{"state": "UNKNOWN"}]

        errors = validate_position_management_report(report)

        self.assertIn(
            "unavailable position management must not expose replays",
            errors,
        )
        self.assertNotIn(
            "position_management replay has unknown state",
            errors,
        )

    def test_complete_explicit_position_is_evaluated(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
            positions=[self._complete_position()],
        )

        self.assertEqual([], validate_position_management_report(report))
        self.assertEqual("available", report["status"])
        self.assertIsNone(report["reason_code"])
        self.assertEqual([], report["missing_evidence"])
        self.assertEqual(1, report["summary"]["positions_evaluated"])

    def test_probability_evidence_must_be_within_unit_interval(self):
        for field_name, invalid_value in (
            ("p_touch_before", -0.01),
            ("p_touch_before", 1.01),
            ("p_touch_after", -0.01),
            ("p_touch_after", 1.01),
        ):
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                position = self._complete_position()
                position["roll_candidate"][field_name] = invalid_value
                report = build_position_management_report(
                    generated_at="2026-07-07T00:01:30Z",
                    account_status={"positions": []},
                    portfolio_risk={"final_action": "allow_new"},
                    permission_state={"reason_codes": []},
                    positions=[position],
                )

                self.assertEqual("unavailable", report["status"])
                self.assertIn(
                    f"roll_candidate.{field_name}",
                    report["missing_evidence"],
                )

    def test_loss_evidence_must_be_non_negative(self):
        for section, field_name in (
            ("roll_candidate", "stress_loss_before"),
            ("roll_candidate", "stress_loss_after"),
            ("protective_spread", "stress_loss_before"),
            ("protective_spread", "stress_loss_after"),
        ):
            with self.subTest(section=section, field_name=field_name):
                position = self._complete_position()
                position[section][field_name] = -1.0
                report = build_position_management_report(
                    generated_at="2026-07-07T00:01:30Z",
                    account_status={"positions": []},
                    portfolio_risk={"final_action": "allow_new"},
                    permission_state={"reason_codes": []},
                    positions=[position],
                )

                self.assertEqual("unavailable", report["status"])
                self.assertIn(
                    f"{section}.{field_name}",
                    report["missing_evidence"],
                )

    def test_missing_portfolio_gate_defaults_to_halt_not_allow_new(self):
        replay = evaluate_position_replay(
            position=self._complete_position(),
            portfolio_risk={},
            permission_state={},
        )

        self.assertEqual("PAUSED", replay["state"])
        self.assertNotIn("active_roll", replay["allowed_actions"])
        self.assertIn("active_roll", replay["forbidden_actions"])

    def test_observed_account_position_without_cost_basis_is_unavailable(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={
                "positions": [
                    {
                        "instrument_name": "BTC-25JUL26-120000-C",
                        "size": -1.0,
                        "floating_profit_loss": -40.0,
                    }
                ]
            },
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual([], validate_position_management_report(report))
        self.assertEqual("unavailable", report["status"])
        self.assertEqual("MISSING_POSITION_MANAGEMENT_EVIDENCE", report["reason_code"])
        self.assertEqual([], report["replays"])
        self.assertEqual(1, report["summary"]["positions_observed"])
        self.assertEqual(0, report["summary"]["positions_evaluated"])


if __name__ == "__main__":
    unittest.main()
