import unittest

from crypto_options_report.account_risk import build_account_status
from crypto_options_report.full_surface import build_full_system_surface_report


class FullSurfaceAccountEvidenceTests(unittest.TestCase):
    def test_fresh_live_account_evidence_is_ready_while_portfolio_stays_blocked(self):
        generated_at = "2026-07-14T00:00:30Z"
        account_status = build_account_status(
            generated_at=generated_at,
            account_payload={
                "account": {
                    "status": "available",
                    "source": "deribit_live_private_read_only",
                    "source_endpoint": "private/get_account_summary",
                    "observed_at": "2026-07-14T00:00:00Z",
                    "currency": "BTC",
                    "margin_model": "portfolio_margin",
                    "equity": 1.0,
                    "balance": 1.0,
                    "margin_balance": 1.0,
                    "available_funds": 0.8,
                    "initial_margin": 0.1,
                    "maintenance_margin": 0.05,
                },
                "positions": [],
                "simulation": {
                    "status": "not_requested",
                    "attempted": False,
                    "source_endpoint": "private/simulate_portfolio",
                    "reason_code": "SIMULATION_NOT_REQUESTED",
                },
            },
        )

        self.assertEqual("available", account_status["status"])
        self.assertFalse(account_status["live_snapshot"])
        self.assertTrue(account_status["simulation_status"]["blocks_new_trades"])

        surface = build_full_system_surface_report(
            generated_at=generated_at,
            report={
                "data_status": {
                    "status": "validated",
                    "feed_coverage": {"missing_feeds": []},
                    "public_response_contract": {"overall_status": "pass"},
                },
                "data_trust": {
                    "verdict": "trusted",
                    "source_class": "live",
                    "reason_codes": [],
                },
                "account_status": account_status,
                "portfolio_risk": {
                    "schema_version": "portfolio_risk_report.v1",
                    "final_action": "halt_system",
                },
            },
        )
        gates = {
            gate["name"]: gate
            for gate in surface["release_readiness"]["prerequisites"]
        }

        account_gate = gates["private_account_replay_contract"]
        self.assertTrue(account_gate["satisfied"])
        self.assertEqual("ready", account_gate["release_state"])
        self.assertEqual("verified_local", account_gate["evidence_state"])
        self.assertEqual("live_read_only", account_gate["evidence_class"])
        self.assertEqual([], account_gate["reason_codes"])

        portfolio_gate = gates["portfolio_risk"]
        self.assertFalse(portfolio_gate["satisfied"])
        self.assertEqual("awaiting_external", portfolio_gate["release_state"])
        self.assertIn(
            "portfolio_risk",
            surface["release_readiness"]["missing_prerequisites"],
        )
        self.assertNotIn(
            "private_account_replay_contract",
            surface["release_readiness"]["missing_prerequisites"],
        )


if __name__ == "__main__":
    unittest.main()
