import json
import subprocess
import sys
import unittest

from crypto_options_report.api import build_api_report
from crypto_options_report.pnl import (
    build_pnl_evidence_report,
    combo_fee,
    inverse_long_call_settlement_coin,
    trace_inverse_call_credit_spread,
    trace_inverse_short_call,
    trace_linear_call_credit_spread,
    trace_linear_short_call,
)


class PnlEvidenceReportTests(unittest.TestCase):
    def test_known_inverse_long_call_settlement_example_is_locked(self):
        settlement = inverse_long_call_settlement_coin(100000.0, 125000.0)

        self.assertAlmostEqual(0.2, settlement, places=8)

    def test_linear_short_call_trace_covers_entry_mtm_expiry_and_fees(self):
        trace = trace_linear_short_call(
            contract_count=1.0,
            contract_size=1.0,
            strike_price=100000.0,
            entry_index_price=100000.0,
            delivery_price=125000.0,
            entry_option_value=2400.0,
            mark_option_value=3100.0,
        )

        self.assertEqual(2400.0, trace["entry_credit_usdc"])
        self.assertEqual(25000.0, trace["expiry_payoff_usdc"])
        self.assertAlmostEqual(-22648.75, trace["expiry_pnl_usdc"], places=8)
        self.assertEqual(3100.0, trace["liability_usdc_mark_to_market"])
        self.assertEqual(-730.0, trace["unrealized_pnl_usdc"])
        self.assertAlmostEqual(30.0, trace["trade_fee_usdc"], places=8)
        self.assertAlmostEqual(18.75, trace["delivery_fee_usdc"], places=8)
        self.assertEqual("UNBOUNDED", trace["max_loss_state"])

    def test_linear_call_credit_spread_trace_reports_pnl_and_max_loss(self):
        trace = trace_linear_call_credit_spread(
            contract_count=1.0,
            contract_size=1.0,
            short_strike_price=100000.0,
            long_strike_price=110000.0,
            entry_index_price=100000.0,
            delivery_price=125000.0,
            sell_leg_bid=2200.0,
            buy_leg_ask=900.0,
        )

        self.assertEqual(1300.0, trace["net_credit_usdc"])
        self.assertEqual(10000.0, trace["spread_payoff_usdc"])
        self.assertAlmostEqual(-8797.5, trace["expiry_pnl_usdc"], places=8)
        self.assertAlmostEqual(8797.5, trace["max_loss_usdc"], places=8)
        self.assertEqual(97.5, trace["total_fees_usdc"])

    def test_inverse_short_call_trace_reports_coin_and_usd_shadow_pnl(self):
        trace = trace_inverse_short_call(
            contract_count=1.0,
            strike_price=100000.0,
            delivery_price=125000.0,
            mark_underlying_price=120000.0,
            entry_option_value_coin=0.05,
            mark_option_value_coin=0.07,
        )

        self.assertAlmostEqual(0.2, trace["settlement_value_coin"], places=8)
        self.assertAlmostEqual(-0.15045, trace["expiry_pnl_coin"], places=8)
        self.assertAlmostEqual(-18806.25, trace["expiry_pnl_usd_shadow"], places=8)
        self.assertAlmostEqual(-2436.0, trace["unrealized_pnl_usd_shadow"], places=8)
        self.assertEqual("UNBOUNDED", trace["max_loss_state"])

    def test_inverse_call_credit_spread_trace_reports_scenario_losses(self):
        trace = trace_inverse_call_credit_spread(
            contract_count=1.0,
            short_strike_price=100000.0,
            long_strike_price=110000.0,
            entry_reference_price=100000.0,
            delivery_price=125000.0,
            sell_leg_bid_coin=0.05,
            buy_leg_ask_coin=0.02,
        )

        self.assertAlmostEqual(0.03, trace["net_credit_coin"], places=8)
        self.assertAlmostEqual(0.08, trace["spread_payoff_coin"], places=8)
        self.assertAlmostEqual(-0.0509, trace["expiry_pnl_coin"], places=8)
        self.assertAlmostEqual(0.0509, trace["scenario_loss_coin"], places=8)
        self.assertAlmostEqual(6362.5, trace["scenario_loss_usd_shadow"], places=8)
        self.assertAlmostEqual(7090.0, trace["reference_max_loss_usd_shadow"], places=8)

    def test_conservative_fee_defaults_ignore_unverified_combo_discount(self):
        report = build_pnl_evidence_report()
        spread_check = next(
            check
            for check in report["checks"]
            if check["id"] == "linear-usdc-call-credit-spread"
        )

        self.assertEqual("ignore_unverified_combo_discount", report["conservative_defaults"]["combo_discount_default"])
        self.assertEqual(60.0, spread_check["outputs"]["trade_fee_usdc"])
        self.assertEqual(0.6, combo_fee(0.3, 0.3))

    def test_evidence_report_and_api_surface_show_pass_status_and_examples(self):
        report = build_pnl_evidence_report()
        api_report = build_api_report()
        cli_payload = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "report",
                "--mode",
                "research_only",
                "--compact",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cli_report = json.loads(cli_payload.stdout)

        self.assertEqual("pass", report["status"])
        self.assertEqual("pass", api_report["pnl_evidence"]["status"])
        self.assertEqual("pass", cli_report["pnl_evidence"]["status"])
        self.assertEqual(
            {"linear-usdc-short-call", "linear-usdc-call-credit-spread", "inverse-short-call", "inverse-call-credit-spread", "inverse-known-long-call-settlement"},
            {check["id"] for check in report["checks"]},
        )


if __name__ == "__main__":
    unittest.main()
