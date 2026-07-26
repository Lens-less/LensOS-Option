import unittest
from pathlib import Path

from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)
from crypto_options_report.market_data import load_snapshot_fixture
from crypto_options_report.strategy_research import validate_strategy_research


class StrategyResearchTests(unittest.TestCase):
    def test_live_market_report_contains_the_complete_research_loop(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=load_snapshot_fixture(self._fixture_path()),
        )

        self.assertEqual([], validate_report_contract(report))
        strategy = report["strategy_research"]
        self.assertEqual("strategy_research.v1", strategy["schema_version"])
        self.assertTrue(strategy["advisory_only"])
        self.assertEqual(
            [
                "COLLECT",
                "ANALYZE",
                "SELECT",
                "ENTER",
                "RISK",
                "EXIT",
                "MONITOR",
                "REVIEW",
            ],
            [stage["stage"] for stage in strategy["pipeline"]],
        )

        self.assertEqual("screening_only", strategy["confidence_ceiling"])
        self.assertEqual("MONITOR_ONLY", strategy["decision"]["stance"])
        self.assertEqual(
            "CALL_CREDIT_SPREAD",
            strategy["decision"]["primary_structure"],
        )
        self.assertEqual(
            "NAKED_SHORT_CALL",
            strategy["decision"]["rejected_structures"][0]["structure"],
        )

        collection = strategy["collection"]
        self.assertEqual("validated", collection["status"])
        self.assertGreater(collection["coverage"]["selected_instrument_count"], 0)
        self.assertGreater(collection["quality"]["valid_quotes"], 0)
        self.assertFalse(collection["feed_graph"]["complete"])
        self.assertEqual(
            [],
            collection["feed_graph"]["missing_required_feeds"],
        )

        analysis = strategy["analysis"]
        self.assertIsNotNone(analysis["market"]["spot_usd"])
        self.assertIsNotNone(analysis["market"]["dvol_percent"])
        self.assertIsNotNone(analysis["volatility"]["expected_move_usd"])
        self.assertIsNotNone(
            analysis["volatility"]["call_wing_richness_iv_points"]
        )

        playbook = strategy["playbook"]
        self.assertEqual("CALL_CREDIT_SPREAD", playbook["structure"])
        self.assertTrue(playbook["candidate"]["sell_leg"])
        self.assertTrue(playbook["candidate"]["buy_leg"])
        self.assertGreater(playbook["economics"]["credit_usd_shadow"], 0)
        self.assertGreater(
            playbook["economics"]["reference_max_loss_usd_shadow"],
            playbook["economics"]["credit_usd_shadow"],
        )
        self.assertGreater(playbook["economics"]["breakeven_usd_shadow"], 0)
        self.assertGreater(
            playbook["economics"]["sell_strike_expected_move_multiple"],
            0,
        )
        self.assertGreaterEqual(len(playbook["entry_contract"]["conditions"]), 8)
        self.assertEqual(
            "account_input_missing",
            playbook["risk_budget"]["sizing_status"],
        )
        self.assertIsNone(playbook["risk_budget"]["contracts"])
        self.assertEqual(
            ["NORMAL", "CAUTION", "DEFENSE", "EXIT_REQUIRED", "FORCE_CLOSE"],
            [
                state["state"]
                for state in playbook["exit_contract"]["position_states"]
            ],
        )
        self.assertEqual(4, len(playbook["exit_contract"]["profit_capture"]))
        self.assertGreaterEqual(len(strategy["monitoring"]), 8)
        self.assertGreaterEqual(len(strategy["review"]["promotion_conditions"]), 4)

    def test_missing_market_data_keeps_the_loop_visible_but_blocks_a_playbook(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        self.assertEqual([], validate_report_contract(report))
        strategy = report["strategy_research"]
        self.assertEqual("blocked", strategy["status"])
        self.assertEqual("NO_RESEARCH_SETUP", strategy["decision"]["stance"])
        self.assertIsNone(strategy["decision"]["primary_structure"])
        self.assertIsNone(strategy["playbook"])
        self.assertEqual(8, len(strategy["pipeline"]))
        self.assertEqual("blocked", strategy["pipeline"][0]["status"])

    def test_strategy_contract_rejects_execution_capability_or_missing_stages(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=load_snapshot_fixture(self._fixture_path()),
        )
        strategy = report["strategy_research"]
        strategy["advisory_only"] = False
        strategy["pipeline"].pop()

        errors = validate_strategy_research(strategy)

        self.assertIn("strategy_research.advisory_only must be true", errors)
        self.assertIn(
            "strategy_research.pipeline must contain the complete research loop",
            errors,
        )

    @staticmethod
    def _fixture_path() -> Path:
        return (
            Path(__file__).with_name("fixtures")
            / "deribit_btc_option_chain_snapshot.json"
        )


if __name__ == "__main__":
    unittest.main()
