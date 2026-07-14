from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from crypto_options_report.contract import (
    generate_research_report,
    validate_report_contract,
)
from crypto_options_report.paper_ledger import (
    build_paper_proposal_ledger,
    validate_paper_proposal_ledger,
)


class PaperProposalLedgerTests(unittest.TestCase):
    def test_default_report_declares_paper_mode_unsupported(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        ledger = report["paper_proposal_ledger"]

        self.assertEqual([], validate_paper_proposal_ledger(ledger))
        self.assertEqual("unsupported", ledger["status"])
        self.assertEqual("not_authorized", ledger["authorization_state"])
        self.assertEqual("NO-GO", ledger["release_state"])
        self.assertFalse(ledger["proposal_creation_allowed"])
        self.assertFalse(ledger["automatic_live_submission_possible"])
        self.assertIn("PAPER_MODE_NOT_AUTHORIZED", ledger["reason_codes"])

    def test_allow_paper_flag_is_not_authority(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report={
                "mode_gate": {"paper_manual_candidates_allowed": True},
                "walk_forward_calibration": {
                    "status": "validated",
                    "model_registry": {"promoted_for_sizing": True},
                },
                "ev_candidate_scanner": {
                    "ranked_candidates": [{"candidate_id": "self-attested"}]
                },
            },
            allow_paper=True,
        )

        self.assertEqual([], validate_paper_proposal_ledger(ledger))
        self.assertEqual("unsupported", ledger["status"])
        self.assertEqual(0, ledger["proposal_count"])
        self.assertEqual([], ledger["proposals"])
        self.assertEqual([], ledger["ledger_entries"])

    def test_review_decisions_do_not_create_paper_entries(self):
        ledger = build_paper_proposal_ledger(
            generated_at="2026-07-07T00:01:30Z",
            report={},
            allow_paper=True,
            review_decisions=[
                {
                    "proposal_id": "proposal-01",
                    "state": "paper_filled",
                    "observed_fill_usdc": 117.5,
                }
            ],
        )

        self.assertEqual([], ledger["workflow_states"])
        self.assertEqual([], ledger["ledger_entries"])
        self.assertEqual("not_authorized", ledger["reconciliation"]["status"])
        self.assertEqual("not_run", ledger["reconciliation"]["evidence_state"])
        self.assertFalse(ledger["reconciliation"]["ready"])

    def test_storage_path_is_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper-ledger.json"
            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-07T00:01:30Z",
                report={},
                allow_paper=True,
                storage_path=path,
                persist=True,
            )

            self.assertFalse(path.exists())
            self.assertEqual("unsupported", ledger["persistence"]["mode"])
            self.assertFalse(ledger["persistence"]["write_allowed"])
            self.assertIsNone(ledger["persistence"]["storage_path"])

    def test_whole_contract_rejects_forged_unsupported_paper_state(self):
        report = generate_research_report(generated_at="2026-07-07T00:01:30Z")
        mutations = (
            (
                "proposal count",
                ("proposal_count",),
                999,
                "unsupported paper mode proposal_count must be zero",
            ),
            (
                "external approval",
                ("manual_approval_runbook", "external_approval_recorded"),
                True,
                "paper mode must not record external approval",
            ),
            (
                "reconciliation status",
                ("reconciliation", "status"),
                "reconciled",
                "unsupported paper reconciliation must remain not_authorized",
            ),
            (
                "reconciliation readiness",
                ("reconciliation", "ready"),
                True,
                "unsupported paper reconciliation must not be ready",
            ),
        )

        for label, path, value, expected_error in mutations:
            with self.subTest(label=label):
                mutated = deepcopy(report)
                target = mutated["paper_proposal_ledger"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value

                self.assertIn(expected_error, validate_report_contract(mutated))


if __name__ == "__main__":
    unittest.main()
