"""Candidate quality follows the option side, including a put-only chain."""

from __future__ import annotations

import unittest
from copy import deepcopy

from crypto_options_report.surface import (
    _candidate_filter_reasons,
    build_vol_surface_and_candidate_research,
)
from tests.test_expanded_universe import CAPTURED_AT, _two_sided_snapshot


def _research(snapshot: dict) -> tuple[dict, dict]:
    return build_vol_surface_and_candidate_research(
        market_snapshot=snapshot,
        generated_at=CAPTURED_AT,
        data_status={"status": "validated"},
        pnl_evidence={"status": "pass"},
    )


class PutSurfaceQualityTests(unittest.TestCase):
    def test_put_only_chain_produces_eligible_put_spreads(self) -> None:
        snapshot = _two_sided_snapshot()
        snapshot["rows"] = [
            row for row in snapshot["rows"] if row["instrument_name"].endswith("-P")
        ]

        surface, candidates = _research(snapshot)
        expiry = surface["expiries"][0]
        self.assertFalse(expiry["candidate_eligible"])
        self.assertTrue(expiry["put_candidate_eligible"])
        self.assertTrue(candidates["put_credit_spreads"]["eligible"])
        for tier in candidates["put_credit_spreads"].values():
            for candidate in tier:
                self.assertNotIn(
                    "SURFACE_QUALITY_BLOCKED", candidate["filter_reason_codes"]
                )
        self.assertEqual(1, surface["summary"]["eligible_expiries"])
        self.assertEqual(1, candidates["summary"]["eligible_expiries"])

    def test_put_spread_quality_reports_the_put_smile(self) -> None:
        snapshot = _two_sided_snapshot()
        snapshot["rows"] = [
            row for row in snapshot["rows"] if row["instrument_name"].endswith("-P")
        ]

        surface, candidates = _research(snapshot)
        expiry = surface["expiries"][0]
        spreads = [
            candidate
            for tier in candidates["put_credit_spreads"].values()
            for candidate in tier
        ]
        self.assertTrue(spreads)
        for candidate in spreads:
            for field in ("fit_quality_score", "no_arb_pass", "no_arb_error"):
                self.assertEqual(
                    expiry["sides"]["put"][field],
                    candidate["surface_quality"][field],
                )

    def test_put_filter_fails_closed_even_when_call_side_passes(self) -> None:
        surface, _ = _research(_two_sided_snapshot())
        expiry = deepcopy(surface["expiries"][0])
        self.assertTrue(expiry["candidate_eligible"])
        expiry["put_candidate_eligible"] = False
        expiry["sides"]["put"]["candidate_eligible"] = False

        reasons = _candidate_filter_reasons(expiry["put_surface_points"][0], expiry)

        self.assertIn("SURFACE_QUALITY_BLOCKED", reasons)
        self.assertNotIn(
            "SURFACE_QUALITY_BLOCKED",
            _candidate_filter_reasons(expiry["surface_points"][0], expiry),
        )

    def test_poor_put_side_does_not_block_eligible_call_spreads(self) -> None:
        snapshot = _two_sided_snapshot()
        put_rows = [
            row for row in snapshot["rows"] if row["instrument_name"].endswith("-P")
        ]
        snapshot["rows"] = [
            row for row in snapshot["rows"] if row["instrument_name"].endswith("-C")
        ] + put_rows[:3]

        surface, candidates = _research(snapshot)

        self.assertTrue(surface["expiries"][0]["candidate_eligible"])
        self.assertFalse(surface["expiries"][0]["put_candidate_eligible"])
        self.assertTrue(candidates["call_credit_spreads"]["eligible"])
        self.assertFalse(any(candidates["put_credit_spreads"].values()))


if __name__ == "__main__":
    unittest.main()
