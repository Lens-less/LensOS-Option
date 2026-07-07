import unittest
from pathlib import Path

from crypto_options_report.contract import generate_research_report, validate_report_contract
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

    def test_yellow_margin_blocks_new_trades(self):
        report = self._report(account_scenario="yellow")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("YELLOW", report["account_status"]["margin_light"])
        self.assertEqual("no_new_trades", report["portfolio_risk"]["final_action"])
        self.assertIn(
            "ACCOUNT_MARGIN_YELLOW_NO_NEW_TRADES",
            report["portfolio_risk"]["summary"]["reason_codes"],
        )

    def test_size_caps_include_all_dimensions_and_missing_score_reason(self):
        report = self._report()
        cap = report["portfolio_risk"]["size_caps"][0]

        self.assertEqual(
            {
                "cvar",
                "stress",
                "delta",
                "margin",
                "liquidity",
                "score_placeholder",
                "permission",
                "volatility",
                "inverse_multiplier",
            },
            {item["dimension"] for item in cap["dimensions"]},
        )
        self.assertEqual(0.0, cap["final_cap_units"])
        self.assertFalse(cap["size_output_allowed"])
        self.assertIn("score calibration", cap["research_only_reason"].lower())

    def test_volatility_cap_reduces_shadow_size(self):
        normal = self._report_with_regime(dvol_percentile=0.52, atm_iv_percentile=0.48)
        stressed = self._report_with_regime(dvol_percentile=0.97, atm_iv_percentile=0.91)

        normal_vol_cap = self._dimension(normal, "volatility")
        stressed_vol_cap = self._dimension(stressed, "volatility")

        self.assertEqual(1.0, normal_vol_cap)
        self.assertEqual(0.2, stressed_vol_cap)
        self.assertLess(stressed_vol_cap, normal_vol_cap)

    def _dimension(self, report, name):
        cap = report["portfolio_risk"]["size_caps"][0]
        return next(item["cap_units"] for item in cap["dimensions"] if item["dimension"] == name)

    def _report(self, account_scenario="green"):
        return generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=load_snapshot_fixture(self._fixture_path()),
            account_scenario=account_scenario,
        )

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
