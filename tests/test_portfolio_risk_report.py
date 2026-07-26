import unittest
from pathlib import Path

from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)
from crypto_options_report.market_data import load_snapshot_fixture
from crypto_options_report.portfolio_risk import (
    SEVERITY_ORDER,
    build_portfolio_risk_report,
    validate_portfolio_risk_report,
)


class PortfolioRiskReportTests(unittest.TestCase):
    def test_risk_signals_have_schema_and_severity_order(self):
        report = self._report()
        portfolio = report["portfolio_risk"]

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual([], validate_portfolio_risk_report(portfolio))
        self.assertEqual(
            [
                "allow_new",
                "reduce_size",
                "spread_only",
                "no_new_trades",
                "reduce_existing",
                "close_batch",
                "close_all_and_pause",
                "halt_system",
            ],
            sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get),
        )
        for signal in portfolio["signals"]:
            for field_name in ("source", "severity", "reason", "reason_codes", "expires_at"):
                self.assertIn(field_name, signal)

    def test_mdd_halt_beats_margin_green(self):
        base = self._report()
        portfolio = build_portfolio_risk_report(
            generated_at=base["generated_at"],
            data_status=base["data_status"],
            account_status=base["account_status"],
            permission_state=base["permission_state"],
            ev_candidate_scanner=base["ev_candidate_scanner"],
            risk_overrides={
                "mdd_circuit": {
                    "status": "halt",
                    "expires_at": "2026-07-08T00:00:00Z",
                }
            },
        )

        self.assertEqual([], validate_portfolio_risk_report(portfolio))
        self.assertEqual("GREEN", base["account_status"]["margin_light"])
        self.assertEqual("halt_system", portfolio["final_action"])
        self.assertEqual("mdd_circuit", portfolio["final_signal"]["source"])

    def test_malformed_permission_state_halts_instead_of_allowing_new_risk(self):
        malformed_states = [
            {
                "sell_permission": float("nan"),
                "naked_permission": False,
                "spread_permission": False,
            },
            {
                "sell_permission": "not-a-number",
                "naked_permission": False,
                "spread_permission": True,
            },
            {
                "sell_permission": True,
                "naked_permission": True,
                "spread_permission": True,
            },
            {
                "sell_permission": 1.01,
                "naked_permission": True,
                "spread_permission": True,
            },
            {
                "sell_permission": 1.0,
                "naked_permission": False,
                "spread_permission": False,
            },
            {
                "sell_permission": 1.0,
                "naked_permission": "false",
                "spread_permission": True,
            },
        ]

        for permission_state in malformed_states:
            with self.subTest(permission_state=permission_state):
                portfolio = self._portfolio(permission_state=permission_state)
                self.assertEqual("halt_system", portfolio["final_action"])
                self.assertIn(
                    "MALFORMED_PERMISSION_STATE",
                    portfolio["summary"]["reason_codes"],
                )

    def test_halt_system_suppresses_shadow_size_cap_evaluation(self):
        base = self._report()
        portfolio = build_portfolio_risk_report(
            generated_at=base["generated_at"],
            data_status=base["data_status"],
            account_status=base["account_status"],
            permission_state={
                "sell_permission": "malformed",
                "naked_permission": False,
                "spread_permission": False,
            },
            ev_candidate_scanner={
                # This helper exercises the sizing calculation itself, so it
                # opts in explicitly. Production keeps this flag false until a
                # score model is promoted.
                "recommended_size_allowed": True,
                "ranked_candidates": [
                    {"candidate_id": "must-not-be-sized", "model_delta": "bad"}
                ]
            },
        )

        self.assertEqual("halt_system", portfolio["final_action"])
        self.assertEqual([], portfolio["size_caps"])
        self.assertEqual(0, portfolio["summary"]["candidate_caps_evaluated"])

    def test_halted_portfolio_rejects_leaked_size_caps(self):
        report = self._report(account_scenario="stale")
        portfolio = report["portfolio_risk"]
        portfolio["size_caps"] = [{"candidate_id": "leaked-cap"}]

        component_errors = validate_portfolio_risk_report(portfolio)
        contract_errors = validate_report_contract(report)

        self.assertIn(
            "halted portfolio_risk must not expose size_caps",
            component_errors,
        )
        self.assertIn(
            "halted portfolio_risk must not expose size_caps",
            contract_errors,
        )

    def test_non_halted_size_caps_require_expected_shape(self):
        portfolio = self._portfolio_with_candidate(
            permission_state=self._sizing_permission_state(),
        )
        portfolio["size_caps"] = [{"candidate_id": "cap-1"}]

        self.assertIn(
            "portfolio_risk.size_cap missing key: raw_cap_units",
            validate_portfolio_risk_report(portfolio),
        )

    def test_malformed_volatility_percentiles_fail_closed_during_direct_sizing(self):
        invalid_inputs = (
            {
                "dvol_percentile": "bad",
                "atm_iv_percentile": float("inf"),
            },
            {
                "dvol_percentile": -0.01,
                "atm_iv_percentile": 0.45,
            },
            {
                "dvol_percentile": 0.55,
                "atm_iv_percentile": 1.01,
            },
        )
        for volatility_inputs in invalid_inputs:
            with self.subTest(volatility_inputs=volatility_inputs):
                portfolio = self._portfolio_with_candidate(
                    permission_state=self._sizing_permission_state(
                        volatility_inputs=volatility_inputs
                    ),
                )

                self.assertEqual("spread_only", portfolio["final_action"])
                self.assertEqual(1, len(portfolio["size_caps"]))
                volatility_dimension = next(
                    item
                    for item in portfolio["size_caps"][0]["dimensions"]
                    if item["dimension"] == "volatility"
                )
                self.assertEqual(0.0, volatility_dimension["cap_units"])

    def test_malformed_or_unknown_mdd_state_halts_instead_of_clearing(self):
        for mdd_state in ({}, {"status": "halt_systm"}, "clear"):
            with self.subTest(mdd_state=mdd_state):
                portfolio = self._portfolio(
                    risk_overrides={"mdd_circuit": mdd_state}
                )
                self.assertEqual("halt_system", portfolio["final_action"])
                self.assertIn(
                    "MDD_STATE_MALFORMED",
                    portfolio["summary"]["reason_codes"],
                )

    def test_explicit_clear_mdd_state_is_accepted(self):
        portfolio = self._portfolio(
            risk_overrides={"mdd_circuit": {"status": "clear"}}
        )

        mdd_signal = next(
            signal
            for signal in portfolio["signals"]
            if signal["source"] == "mdd_circuit"
        )
        self.assertEqual("allow_new", mdd_signal["severity"])
        self.assertEqual(["MDD_CLEAR"], mdd_signal["reason_codes"])

    def test_final_action_tamper_is_rejected_by_component_and_whole_contract(self):
        report = self._report()
        portfolio = report["portfolio_risk"]
        self.assertNotEqual("allow_new", portfolio["final_signal"]["severity"])
        portfolio["final_action"] = "allow_new"

        component_errors = validate_portfolio_risk_report(portfolio)
        contract_errors = validate_report_contract(report)

        self.assertIn(
            "portfolio_risk.final_action must match final_signal.severity",
            component_errors,
        )
        self.assertIn(
            "portfolio_risk.final_action must match final_signal.severity",
            contract_errors,
        )

    def test_explicit_malformed_risk_override_states_halt(self):
        override_fields = {
            "event_risk": "EVENT_RISK_STATE_MALFORMED",
            "liquidity_state": "LIQUIDITY_STATE_MALFORMED",
            "exchange_status": "EXCHANGE_STATUS_MALFORMED",
            "position_state": "POSITION_STATE_MALFORMED",
        }
        for field_name, reason_code in override_fields.items():
            for malformed_state in ({}, {"status": "unknown"}, "clear"):
                with self.subTest(
                    field_name=field_name, malformed_state=malformed_state
                ):
                    portfolio = self._portfolio(
                        risk_overrides={field_name: malformed_state}
                    )
                    self.assertEqual("halt_system", portfolio["final_action"])
                    self.assertIn(
                        reason_code,
                        portfolio["summary"]["reason_codes"],
                    )

    def test_explicit_known_clear_risk_override_states_are_accepted(self):
        clear_states = {
            "event_risk": {"status": "clear"},
            "liquidity_state": {"status": "normal"},
            "exchange_status": {"status": "online"},
            "position_state": {"state": "NORMAL"},
        }
        for field_name, clear_state in clear_states.items():
            with self.subTest(field_name=field_name):
                portfolio = self._portfolio(
                    risk_overrides={field_name: clear_state}
                )
                signal = next(
                    item
                    for item in portfolio["signals"]
                    if item["source"] == field_name
                )
                self.assertEqual("allow_new", signal["severity"])

    def test_yellow_margin_blocks_new_trades(self):
        report = self._report(account_scenario="yellow")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("YELLOW", report["account_status"]["margin_light"])
        self.assertEqual("no_new_trades", report["portfolio_risk"]["final_action"])
        self.assertIn(
            "ACCOUNT_MARGIN_YELLOW_NO_NEW_TRADES",
            report["portfolio_risk"]["summary"]["reason_codes"],
        )

    def test_relative_value_ranking_alone_produces_no_size_caps(self):
        """Ranking says which strike is better priced, not how much to carry."""
        report = self._report()
        portfolio = report["portfolio_risk"]
        scanner = report["ev_candidate_scanner"]

        # Candidates are ranked, but none carries validated path risk.
        self.assertEqual("blocked", scanner["status"])
        self.assertGreater(len(scanner["ranked_candidates"]), 0)
        self.assertTrue(
            all(
                candidate["path_risk"]["status"] == "unavailable"
                for candidate in scanner["ranked_candidates"]
            )
        )
        self.assertTrue(
            all(
                candidate["ev_after_cost_usdc"] is None
                for candidate in scanner["ranked_candidates"]
            )
        )

        self.assertEqual([], portfolio["size_caps"])
        self.assertEqual(0, portfolio["summary"]["candidate_caps_evaluated"])
        self.assertFalse(portfolio["summary"]["trade_sizing_allowed"])
        self.assertIn("MISSING_PROMOTED_SCORE_MODEL", portfolio["summary"]["reason_codes"])

    def test_regime_changes_do_not_conjure_shadow_size_without_ev_evidence(self):
        normal = self._report_with_regime(dvol_percentile=0.52, atm_iv_percentile=0.48)
        stressed = self._report_with_regime(dvol_percentile=0.97, atm_iv_percentile=0.91)

        for report in (normal, stressed):
            self.assertEqual("blocked", report["ev_candidate_scanner"]["status"])
            self.assertEqual([], report["portfolio_risk"]["size_caps"])
            self.assertFalse(
                report["portfolio_risk"]["summary"]["trade_sizing_allowed"]
            )

    def _report(self, account_scenario="green"):
        return generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=load_snapshot_fixture(self._fixture_path()),
            account_scenario=account_scenario,
        )

    def _portfolio(self, *, permission_state=None, risk_overrides=None):
        base = self._report()
        return build_portfolio_risk_report(
            generated_at=base["generated_at"],
            data_status=base["data_status"],
            account_status=base["account_status"],
            permission_state=(
                base["permission_state"]
                if permission_state is None
                else permission_state
            ),
            ev_candidate_scanner=base["ev_candidate_scanner"],
            risk_overrides=risk_overrides,
        )

    def _portfolio_with_candidate(self, *, permission_state):
        base = self._report()
        return build_portfolio_risk_report(
            generated_at=base["generated_at"],
            data_status=base["data_status"],
            account_status=base["account_status"],
            permission_state=permission_state,
            ev_candidate_scanner={
                # This helper exercises the sizing calculation itself, so it
                # opts in explicitly. Production keeps this flag false until a
                # score model is promoted.
                "recommended_size_allowed": True,
                "ranked_candidates": [
                    {
                        "candidate_id": "candidate-1",
                        "structure_type": "call_credit_spread",
                        "model_delta": 0.22,
                        "underlying_price": 100_000.0,
                        "sell_leg_depth": 20.0,
                        "buy_leg_depth": 18.0,
                        "path_risk": {
                            "cvar_99_usdc": 800.0,
                            "stress_loss_usdc": 950.0,
                        },
                        "margin_snapshot": {
                            "delta_initial_margin": 750.0,
                        },
                    }
                ]
            },
        )

    def _sizing_permission_state(self, *, volatility_inputs=None):
        return {
            "sell_permission": 0.25,
            "naked_permission": False,
            "spread_permission": True,
            "reason_codes": ["SIZING_TEST_PERMISSION"],
            "volatility_inputs": (
                {
                    "dvol_percentile": 0.55,
                    "atm_iv_percentile": 0.45,
                }
                if volatility_inputs is None
                else volatility_inputs
            ),
        }

    def _report_with_regime(self, *, dvol_percentile, atm_iv_percentile):
        snapshot = load_snapshot_fixture(self._fixture_path())
        snapshot["regime_inputs"] = {
            "bear_trend_score": 0.82,
            "range_score": 0.20,
            "squeeze_score": 0.18,
            "slow_bull_score": 0.15,
            "fast_bull_breakout_score": 0.10,
            "event_score": 0.05,
            "dvol_percentile": dvol_percentile,
            "atm_iv_percentile": atm_iv_percentile,
        }
        return generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

    def _fixture_path(self):
        return Path(__file__).with_name("fixtures") / "deribit_btc_option_chain_snapshot.json"


if __name__ == "__main__":
    unittest.main()
