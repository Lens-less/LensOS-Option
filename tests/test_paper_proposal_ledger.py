import unittest

from crypto_options_report.contract import generate_research_report
from crypto_options_report.paper_ledger import (
    build_paper_proposal_ledger,
    validate_paper_proposal_ledger,
)


class PaperProposalLedgerTests(unittest.TestCase):
    def test_default_shared_report_blocks_paper_proposals(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        ledger = report["paper_proposal_ledger"]

        self.assertEqual([], validate_paper_proposal_ledger(ledger))
        self.assertEqual("blocked", ledger["status"])
        self.assertFalse(ledger["proposal_creation_allowed"])
        self.assertFalse(ledger["automatic_live_submission_possible"])
        self.assertIn("PAPER_MODE_GATE_CLOSED", ledger["reason_codes"])

    def test_top_one_to_three_calibrated_candidates_become_proposals(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=self._paper_ready_report(),
            allow_paper=True,
        )

        self.assertEqual([], validate_paper_proposal_ledger(ledger))
        self.assertEqual("validated", ledger["status"])
        self.assertEqual(3, ledger["proposal_count"])
        self.assertEqual(3, len(ledger["proposals"]))
        self.assertFalse(ledger["automatic_live_submission_possible"])

    def test_proposal_schema_and_conservative_pricing_are_recorded(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=self._paper_ready_report(),
            allow_paper=True,
        )
        naked = ledger["proposals"][0]
        spread = ledger["proposals"][1]

        for field_name in (
            "structure_type",
            "legs",
            "dte_days",
            "model_delta",
            "executable_credit_usdc",
            "ev_after_cost_usdc",
            "p_touch",
            "cvar_99_usdc",
            "stress_loss_usdc",
            "size_cap_units",
            "entry_condition",
            "take_profit_condition",
            "risk_exit_condition",
            "reason_codes",
        ):
            self.assertIn(field_name, naked)
        self.assertEqual("sell_leg_bid_or_better", naked["conservative_price_basis"])
        self.assertEqual("sell_leg_bid_minus_buy_leg_ask", spread["conservative_price_basis"])

    def test_workflow_states_and_ledger_reconciliation(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=self._paper_ready_report(),
            allow_paper=True,
            review_decisions=[
                {
                    "proposal_id": "proposal-01",
                    "state": "paper_filled",
                    "simulated_fill_usdc": 118.0,
                    "state_machine_trigger": "take_profit",
                }
            ],
        )

        self.assertEqual(
            {"proposed", "reviewed", "rejected", "expired", "paper_filled"},
            set(ledger["workflow_states"]),
        )
        first = ledger["ledger_entries"][0]
        self.assertEqual("paper_filled", first["state"])
        self.assertTrue(first["reconciled"])
        self.assertEqual("take_profit", first["state_machine_trigger"])

    def test_blocked_states_prevent_proposal_creation(self):
        blocked = self._paper_ready_report()
        blocked["account_status"]["trade_gate"] = "NO_TRADE"

        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report=blocked,
            allow_paper=True,
        )

        self.assertEqual("blocked", ledger["status"])
        self.assertEqual([], ledger["proposals"])
        self.assertIn("ACCOUNT_OR_MARGIN_GATE_BLOCKS_PROPOSALS", ledger["reason_codes"])

    def _paper_ready_report(self):
        candidates = [
            self._candidate("candidate-1", "naked_short_call", 120.0),
            self._candidate("candidate-2", "call_credit_spread", 95.0),
            self._candidate("candidate-3", "naked_short_call", 80.0),
            self._candidate("candidate-4", "naked_short_call", 70.0),
        ]
        return {
            "mode_gate": {"paper_manual_candidates_allowed": True},
            "walk_forward_calibration": {"status": "validated"},
            "data_status": {"status": "validated"},
            "account_status": {"trade_gate": "ALLOW_NEW"},
            "reason_codes": [],
            "ev_candidate_scanner": {"ranked_candidates": candidates},
        }

    def _candidate(self, candidate_id, structure, credit):
        payload = {
            "candidate_id": candidate_id,
            "structure_type": structure,
            "action": "RESEARCH_ONLY",
            "kill_conditions": [],
            "instrument_name": f"{candidate_id}-C",
            "dte_days": 14,
            "model_delta": 0.12,
            "executable_credit_usdc": credit,
            "ev_after_cost_usdc": 10.0,
            "path_risk": {
                "p_touch": 0.22,
                "cvar_99_usdc": 300.0,
                "stress_loss_usdc": 450.0,
            },
            "fee_usdc": 1.5,
            "slippage_usdc": 2.0,
            "reason_codes": [],
        }
        if structure == "call_credit_spread":
            payload["sell_leg_instrument_name"] = f"{candidate_id}-sell"
            payload["buy_leg_instrument_name"] = f"{candidate_id}-buy"
        return payload


if __name__ == "__main__":
    unittest.main()
