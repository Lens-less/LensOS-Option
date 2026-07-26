"""Separating a negative expected value from the assumptions that could produce one.

The first run against live data returned a negative expected value for every
candidate that obtained one. At least three different situations produce that
number and they call for opposite responses: the sample period contained the
move the seller was short; the edge is real but sits inside the bid/ask; or
selling this shape is genuinely unprofitable and the other side is the
interesting one. A single figure cannot distinguish them.

Each test below constructs one of those situations and checks the report names
it rather than reporting the same negative number three times.
"""

from __future__ import annotations

import math
import unittest
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise

from crypto_options_report.ev_robustness import (
    EV_ROBUSTNESS_SCHEMA_VERSION,
    build_ev_robustness_report,
)

NAKED = "naked_short_call"
SPOT = 100_000.0
STRIKE = 108_000.0


def _history(
    *, calm_last_third: bool = False, seed: int = 4241, amplitude: float = 0.05
) -> dict:
    """A deterministic price path, optionally quiet in its final third.

    The quiet tail exists so one test can produce a genuine sign flip between
    slices rather than asserting against a threshold nobody can interpret.
    """
    state = seed
    price = SPOT
    start = date(2024, 1, 1)
    observations = []
    total = 900
    for index in range(total):
        state = (1103515245 * state + 12345) % (2**31)
        unit = state / float(2**31)
        step = amplitude
        if calm_last_third and index >= (2 * total) // 3:
            step = 0.004
        price *= math.exp((unit - 0.5) * step)
        day = start + timedelta(days=index)
        observations.append(
            {
                "timestamp_ms": int(
                    datetime.combine(day, time(0), tzinfo=UTC).timestamp() * 1000
                ),
                "observed_at": f"{day.isoformat()}T00:00:00Z",
                "close": round(price, 4),
            }
        )
    return {
        "schema_version": "underlying_price_history.v1",
        "source": "test:robustness",
        "instrument_name": "BTC-PERPETUAL",
        "resolution_seconds": 86400,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def _candidate(*, bid: float, ask: float, **overrides) -> dict:
    base = {
        "candidate_id": "naked-1",
        "structure_type": NAKED,
        "underlying_price": SPOT,
        "strike_price": STRIKE,
        "dte_days": 7.0,
        "model_delta": 0.11,
        "model_vega": 28.0,
        "premium_unit": "quote_currency",
        "market_bid": bid,
        "market_ask": ask,
    }
    base.update(overrides)
    return base


def _report(*, bid: float, ask: float, history: dict | None = None, **overrides) -> dict:
    return build_ev_robustness_report(
        candidate=_candidate(bid=bid, ask=ask, **overrides),
        structure_type=NAKED,
        underlying_history=history or _history(),
        generated_at="2026-07-26T00:00:00Z",
    )


class ExecutionSensitivityTests(unittest.TestCase):
    """The expected payout does not depend on the price the position opened at."""

    def test_every_execution_variant_shares_one_payout(self) -> None:
        report = _report(bid=200.0, ask=260.0)
        variants = report["execution_sensitivity"]["ev_after_cost_usdc"]
        fees = report["execution_sensitivity"]["modelled_fees_usdc"]

        # sell_at_mid = mid - payout - fees and buy_at_mid = payout - mid - fees,
        # so their sum collapses to minus twice the fee regardless of the payout.
        # A variant that had re-derived the payout would break this.
        self.assertAlmostEqual(
            variants["sell_at_mid"] + variants["buy_at_mid"], -2 * fees, places=4
        )

    def test_selling_at_the_mid_beats_selling_at_the_bid(self) -> None:
        variants = _report(bid=200.0, ask=260.0)["execution_sensitivity"][
            "ev_after_cost_usdc"
        ]

        self.assertGreater(variants["sell_at_mid"], variants["sell_at_bid"])
        self.assertGreater(variants["buy_at_mid"], variants["buy_at_ask"])

    def test_the_spread_cost_is_reported_separately_from_fees(self) -> None:
        execution = _report(bid=200.0, ask=260.0)["execution_sensitivity"]

        self.assertAlmostEqual(execution["spread_cost_usdc"], 30.0, places=6)
        self.assertGreater(execution["modelled_fees_usdc"], 0.0)

    def test_the_buy_side_fee_approximation_is_declared(self) -> None:
        execution = _report(bid=200.0, ask=260.0)["execution_sensitivity"]

        self.assertEqual(
            execution["buy_side_fee_basis"], "seller_fee_model_reused"
        )


class VerdictTests(unittest.TestCase):
    def test_a_payout_above_the_ask_points_at_the_other_direction(self) -> None:
        """Selling loses, buying does not: the screened side is the wrong one."""
        report = _report(bid=20.0, ask=30.0)

        self.assertEqual(report["verdict"]["code"], "other_direction_is_positive")
        variants = report["execution_sensitivity"]["ev_after_cost_usdc"]
        self.assertLess(variants["sell_at_bid"], 0.0)
        self.assertGreater(variants["buy_at_ask"], 0.0)

    def test_a_spread_straddling_fair_value_has_no_capturable_edge(self) -> None:
        """Both sides losing is an ordinary market, not a discovery."""
        reference = _report(bid=200.0, ask=260.0)
        payout = reference["reference"]["expected_payout_usdc"]
        fees = reference["execution_sensitivity"]["modelled_fees_usdc"]

        report = _report(bid=payout - fees - 50.0, ask=payout + fees + 50.0)

        self.assertIs(
            report["execution_sensitivity"]["both_directions_negative_at_the_touch"],
            True,
        )
        self.assertEqual(report["verdict"]["code"], "no_capturable_edge_at_the_touch")
        self.assertIn("inside the quoted spread", report["verdict"]["detail"])

    def test_a_credit_above_the_payout_is_positive_on_the_sell_side(self) -> None:
        reference = _report(bid=200.0, ask=260.0)
        payout = reference["reference"]["expected_payout_usdc"]

        report = _report(bid=payout * 3.0, ask=payout * 3.2)

        self.assertEqual(
            report["verdict"]["code"], "positive_across_periods_and_execution"
        )

    def test_a_sign_that_flips_between_slices_outranks_every_other_verdict(
        self,
    ) -> None:
        """An unstable level makes statements about direction meaningless.

        The credit is solved for rather than guessed: a probe run reads the
        per-slice payouts (which do not depend on the entry price), and the
        credit is then placed between the quietest and the most violent slice.
        Guessing a number instead would make the test a hostage to the stress
        overlay's floor.
        """
        history = _history(calm_last_third=True, amplitude=0.12)
        probe = build_ev_robustness_report(
            candidate=_candidate(bid=1.0, ask=2.0),
            structure_type=NAKED,
            underlying_history=history,
            generated_at="2026-07-26T00:00:00Z",
        )
        payouts = [
            row["expected_payout_usdc"]
            for row in probe["period_sensitivity"]["slices"]
            if row.get("status") == "evaluated"
        ]
        self.assertGreaterEqual(len(payouts), 2, probe["period_sensitivity"])
        midpoint = (min(payouts) + max(payouts)) / 2.0

        # One refinement pass: the fee is a function of the credit, so it is
        # read back at roughly the right size rather than assumed.
        fees = probe["execution_sensitivity"]["modelled_fees_usdc"]
        credit = midpoint + fees
        report = build_ev_robustness_report(
            candidate=_candidate(bid=credit, ask=credit * 1.05),
            structure_type=NAKED,
            underlying_history=history,
            generated_at="2026-07-26T00:00:00Z",
        )

        slices = [
            row["ev_after_cost_usdc"]
            for row in report["period_sensitivity"]["slices"]
            if row.get("status") == "evaluated"
        ]
        self.assertTrue(any(value < 0 for value in slices), slices)
        self.assertTrue(any(value >= 0 for value in slices), slices)
        self.assertIs(report["period_sensitivity"]["sign_stable"], False)
        self.assertEqual(report["verdict"]["code"], "sign_flips_across_periods")


class PeriodSensitivityTests(unittest.TestCase):
    def test_slices_are_contiguous_and_cover_the_history(self) -> None:
        report = _report(bid=200.0, ask=260.0)
        rows = report["period_sensitivity"]["slices"]

        self.assertEqual(len(rows), 3)
        self.assertEqual(
            sum(row["observation_count"] for row in rows),
            len(_history()["observations"]),
        )
        for left, right in pairwise(rows):
            self.assertLess(left["last_observed_at"], right["first_observed_at"])

    def test_a_slice_too_thin_to_evaluate_is_reported_not_dropped(self) -> None:
        report = build_ev_robustness_report(
            candidate=_candidate(bid=200.0, ask=260.0),
            structure_type=NAKED,
            underlying_history=_history(),
            generated_at="2026-07-26T00:00:00Z",
            period_slices=40,
        )

        rows = report["period_sensitivity"]["slices"]
        self.assertEqual(len(rows), 40)
        blocked = [row for row in rows if row.get("status") == "blocked"]
        self.assertTrue(blocked)
        for row in blocked:
            self.assertIsNotNone(row["reason_code"])

    def test_the_range_across_slices_is_published(self) -> None:
        periods = _report(bid=200.0, ask=260.0)["period_sensitivity"]

        self.assertEqual(
            periods["range_usdc"],
            round(
                periods["max_ev_after_cost_usdc"]
                - periods["min_ev_after_cost_usdc"],
                6,
            ),
        )
        self.assertEqual(periods["basis"], "contiguous_history_slices")


class FailClosedTests(unittest.TestCase):
    def test_a_candidate_without_both_quotes_is_unavailable(self) -> None:
        report = build_ev_robustness_report(
            candidate=_candidate(bid=200.0, ask=260.0, market_ask=None),
            structure_type=NAKED,
            underlying_history=_history(),
            generated_at="2026-07-26T00:00:00Z",
        )

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["reason_code"], "MISSING_EXECUTABLE_QUOTES")

    def test_an_undeclared_premium_unit_blocks_rather_than_assuming(self) -> None:
        report = build_ev_robustness_report(
            candidate=_candidate(bid=200.0, ask=260.0, premium_unit=None),
            structure_type=NAKED,
            underlying_history=_history(),
            generated_at="2026-07-26T00:00:00Z",
        )

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["reason_code"], "MISSING_EXECUTABLE_QUOTES")

    def test_the_report_stays_research_only(self) -> None:
        report = _report(bid=200.0, ask=260.0)

        self.assertEqual(report["schema_version"], EV_ROBUSTNESS_SCHEMA_VERSION)
        self.assertIs(report["research_only"], True)
        rendered = repr(report)
        for forbidden in ("recommended_size", "order_instruction", "post_only_price"):
            self.assertNotIn(forbidden, rendered)

    def test_buy_side_figures_are_labelled_as_locating_the_edge(self) -> None:
        report = _report(bid=20.0, ask=30.0)

        self.assertTrue(
            any("not to propose the trade" in note for note in report["cannot_tell"])
        )


if __name__ == "__main__":
    unittest.main()
