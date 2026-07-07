import unittest

from crypto_options_report.position_management import (
    classify_position_state,
    evaluate_position_replay,
    validate_position_management_report,
    build_position_management_report,
)


class PositionManagementReplayTests(unittest.TestCase):
    def test_state_thresholds_cover_delta_and_loss_bands(self):
        self.assertEqual("NORMAL", classify_position_state(current_delta=0.20, loss_multiple=0.5))
        self.assertEqual("CAUTION", classify_position_state(current_delta=0.24, loss_multiple=0.5))
        self.assertEqual("DEFENSE", classify_position_state(current_delta=0.30, loss_multiple=0.5))
        self.assertEqual("EXIT_REQUIRED", classify_position_state(current_delta=0.38, loss_multiple=0.5))
        self.assertEqual("FORCE_CLOSE", classify_position_state(current_delta=0.41, loss_multiple=0.5))
        self.assertEqual("FORCE_CLOSE", classify_position_state(current_delta=0.10, loss_multiple=0.5, breakout_kill=True))

    def test_delta_038_exit_required_allows_only_protective_spread_exception(self):
        replay = evaluate_position_replay(
            position={
                "position_id": "exit-required",
                "current_delta": 0.38,
                "loss_multiple": 1.5,
                "collected_premium_usdc": 100.0,
                "protective_spread": {
                    "stress_loss_before": 800.0,
                    "stress_loss_after": 420.0,
                    "net_short_gamma_before": 0.012,
                    "net_short_gamma_after": 0.004,
                },
                "hedge": {"realized_funding_usdc": 1.0, "trading_fee_usdc": 1.0, "slippage_usdc": 1.0},
            },
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
            position={
                "position_id": "defense",
                "current_delta": 0.30,
                "loss_multiple": 2.2,
                "collected_premium_usdc": 100.0,
                "roll_candidate": {
                    "ev_before": 1.0,
                    "ev_after": 5.0,
                    "p_touch_before": 0.4,
                    "p_touch_after": 0.2,
                    "stress_loss_before": 700.0,
                    "stress_loss_after": 500.0,
                },
                "hedge": {"realized_funding_usdc": 1.0, "trading_fee_usdc": 1.0, "slippage_usdc": 1.0},
            },
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual("DEFENSE", replay["state"])
        self.assertIn("active_roll", replay["forbidden_actions"])

    def test_hedge_cost_can_trigger_reevaluation(self):
        replay = evaluate_position_replay(
            position={
                "position_id": "hedge-cost",
                "current_delta": 0.24,
                "loss_multiple": 1.0,
                "collected_premium_usdc": 100.0,
                "hedge": {
                    "realized_funding_usdc": 12.0,
                    "trading_fee_usdc": 5.0,
                    "slippage_usdc": 7.0,
                },
            },
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        hedge = replay["hedge_events"][0]
        self.assertGreater(hedge["cost_to_premium_ratio"], 0.20)
        self.assertTrue(hedge["reevaluation_required"])
        self.assertIn("reevaluate_position", replay["allowed_actions"])

    def test_replay_report_contains_required_surfaces(self):
        report = build_position_management_report(
            generated_at="2026-07-07T00:01:30Z",
            account_status={"positions": []},
            portfolio_risk={"final_action": "allow_new"},
            permission_state={"reason_codes": []},
        )

        self.assertEqual([], validate_position_management_report(report))
        replay = report["replays"][0]
        for field_name in (
            "state",
            "allowed_actions",
            "forbidden_actions",
            "hedge_events",
            "roll_events",
            "forced_exit_events",
        ):
            self.assertIn(field_name, replay)


if __name__ == "__main__":
    unittest.main()
