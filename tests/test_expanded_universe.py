"""End to end: the candidate universe is no longer one side of one chain.

The discovery path used to filter `option_type == "call"` at the surface and
then emit exactly two structure names. Everything downstream — scoring, risk
bounds, expected value — inherited that. This file drives a chain carrying both
calls and puts through the real pipeline and checks that the other structures
come out the far end scored, not merely constructed.

Strikes are solved for a target delta rather than hard-coded, because the
eligibility window is defined in delta and a hard-coded strike silently drifts
out of it whenever the smile or the horizon changes.
"""

from __future__ import annotations

import math
import unittest
from datetime import UTC, date, datetime, time
from statistics import NormalDist

from crypto_options_report.contract import _build_research_report_v1_projection
from crypto_options_report.surface import (
    CANDIDATE_TABLE_NAMES,
    build_vol_surface_and_candidate_research,
)

_NORMAL = NormalDist()
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

SPOT = 100_000.0
CAPTURED_ON = date(2026, 7, 7)
EXPIRY = date(2026, 7, 25)
BASE_IV = 58.0
CAPTURED_AT = "2026-07-07T00:00:30Z"


def _dte_days() -> float:
    captured = datetime.combine(CAPTURED_ON, time(0, 0, 30), tzinfo=UTC)
    expiry = datetime.combine(EXPIRY, time(8), tzinfo=UTC)
    return (expiry - captured).total_seconds() / 86400.0


def _strike_for_delta(target_abs_delta: float, *, option_type: str) -> float:
    """Invert Black-Scholes delta for the strike, then round to a listed one.

    The surface prices with `log(spot / strike)`, so this inversion has to use
    the same orientation or every strike lands on the wrong side of spot.
    """
    sigma = BASE_IV / 100.0
    years = _dte_days() / 365.0
    denom = sigma * math.sqrt(years)
    # A call's delta is N(d1) and a put's is N(d1) - 1, so |delta| = t means
    # N(d1) = 1 - t for a call and N(-d1) = t for a put. Both invert to
    # d1 = -inv_cdf(probability) with the probability chosen per type; getting
    # this sign wrong puts every put strike above spot, deep in the money.
    probability = (
        1.0 - target_abs_delta if option_type == "call" else target_abs_delta
    )
    d1 = -_NORMAL.inv_cdf(probability)
    strike = SPOT / math.exp(d1 * denom - 0.5 * sigma * sigma * years)
    return float(round(strike / 1000.0) * 1000)


def _iv_for(strike: float) -> float:
    """A smooth skew, so the quadratic fit is well specified."""
    return round(BASE_IV - 60.0 * math.log(strike / SPOT), 6)


def _price(strike: float, iv_percent: float, option_type: str) -> float:
    sigma = iv_percent / 100.0
    years = _dte_days() / 365.0
    denom = sigma * math.sqrt(years)
    d1 = (math.log(SPOT / strike) + 0.5 * sigma * sigma * years) / denom
    d2 = d1 - denom
    call = SPOT * _NORMAL.cdf(d1) - strike * _NORMAL.cdf(d2)
    return call - SPOT + strike if option_type == "put" else call


def _instrument(strike: float, option_type: str) -> str:
    suffix = "C" if option_type == "call" else "P"
    return (
        f"BTC-{EXPIRY.day}{_MONTHS[EXPIRY.month - 1]}{EXPIRY.year % 100:02d}"
        f"-{int(strike)}-{suffix}"
    )


def _row(strike: float, option_type: str) -> dict:
    timestamp_ms = int(
        datetime.combine(CAPTURED_ON, time(0, 0, 30), tzinfo=UTC).timestamp() * 1000
    )
    iv = _iv_for(strike)
    mark = _price(strike, iv, option_type)
    bid = round(mark * 0.98, 6)
    ask = round(mark * 1.02, 6)
    name = _instrument(strike, option_type)
    return {
        "instrument_name": name,
        "summary": {
            "instrument_name": name,
            "base_currency": "BTC",
            "quote_currency": "USDC",
            "settlement_currency": "USDC",
            "bid_price": bid,
            "ask_price": ask,
            "mid_price": round((bid + ask) / 2.0, 6),
            "mark_price": round(mark, 6),
            "underlying_price": SPOT,
            "open_interest": 80.0,
            "creation_timestamp": timestamp_ms,
        },
        "ticker": {
            "instrument_name": name,
            "iv_unit": "percent_points",
            "timestamp": timestamp_ms,
            "best_bid_price": bid,
            "best_ask_price": ask,
            "best_bid_amount": 8.0,
            "best_ask_amount": 8.0,
            "mark_price": round(mark, 6),
            "bid_iv": round(iv - 0.4, 6),
            "ask_iv": round(iv + 0.4, 6),
            "mark_iv": iv,
            "underlying_price": SPOT,
            "index_price": SPOT,
            "open_interest": 80.0,
        },
    }


def _two_sided_snapshot() -> dict:
    # Deltas chosen so adjacent strikes land 5_000-15_000 apart, which is the
    # configured spread-width window.
    call_strikes = sorted(
        {_strike_for_delta(delta, option_type="call") for delta in (0.13, 0.10, 0.07, 0.05, 0.035)}
    )
    put_strikes = sorted(
        {_strike_for_delta(delta, option_type="put") for delta in (0.13, 0.10, 0.07, 0.05, 0.035)}
    )
    rows = [_row(strike, "call") for strike in call_strikes]
    rows += [_row(strike, "put") for strike in put_strikes]
    return {
        "captured_at": CAPTURED_AT,
        "source": "test:two-sided-chain",
        "currency": "BTC",
        "feeds": {
            "vol_index": {
                "index_name": "BTC DVOL",
                "currency": "BTC",
                "timestamp": CAPTURED_AT,
                "volatility": 0.58,
            }
        },
        "rows": rows,
    }


def _research() -> tuple[dict, dict]:
    snapshot = _two_sided_snapshot()
    return build_vol_surface_and_candidate_research(
        market_snapshot=snapshot,
        generated_at=CAPTURED_AT,
        data_status={"status": "validated"},
        pnl_evidence={"status": "pass"},
    )


class SurfaceCoversBothSidesTests(unittest.TestCase):
    def test_puts_get_their_own_fitted_smile(self) -> None:
        vol_surface_status, _ = _research()
        expiry = vol_surface_status["expiries"][0]

        self.assertTrue(expiry["surface_points"])
        self.assertTrue(expiry["put_surface_points"])
        self.assertIn("put", expiry["sides"])
        self.assertIs(expiry["sides"]["put"]["candidate_eligible"], True)
        self.assertIs(expiry["sides"]["call"]["candidate_eligible"], True)

    def test_put_deltas_are_negative_rather_than_reusing_call_deltas(self) -> None:
        vol_surface_status, _ = _research()
        puts = vol_surface_status["expiries"][0]["put_surface_points"]

        for point in puts:
            with self.subTest(instrument=point["instrument_name"]):
                self.assertLess(point["model_delta"], 0.0)
                self.assertGreater(point["model_delta"], -1.0)

    def test_a_put_chain_is_not_flagged_as_an_arbitrage(self) -> None:
        """Put prices rise with strike; the call direction would reject them all."""
        vol_surface_status, _ = _research()

        self.assertIs(
            vol_surface_status["expiries"][0]["sides"]["put"]["no_arb_pass"], True
        )


class ExpandedCandidateUniverseTests(unittest.TestCase):
    def test_all_four_structure_tables_are_published(self) -> None:
        _, candidate_research = _research()

        self.assertEqual(
            list(candidate_research["structure_types"]), list(CANDIDATE_TABLE_NAMES)
        )
        for name in CANDIDATE_TABLE_NAMES:
            with self.subTest(table=name):
                self.assertIn(name, candidate_research)

    def test_put_credit_spreads_are_discovered(self) -> None:
        _, candidate_research = _research()
        eligible = candidate_research["put_credit_spreads"]["eligible"]

        self.assertTrue(eligible)
        for candidate in eligible:
            with self.subTest(candidate=candidate["candidate_id"]):
                self.assertEqual(candidate["structure_type"], "put_credit_spread")
                # A put credit spread sells the higher strike and buys the
                # lower one; the reverse would be a debit spread.
                self.assertGreater(
                    candidate["sell_leg_strike_price"],
                    candidate["buy_leg_strike_price"],
                )
                self.assertGreater(candidate["net_credit"], 0.0)

    def test_iron_condors_are_discovered_with_four_legs(self) -> None:
        _, candidate_research = _research()
        condors = candidate_research["iron_condors"]["eligible"]

        self.assertTrue(condors)
        condor = condors[0]
        self.assertEqual(len(condor["structure_legs"]), 4)
        self.assertLess(
            condor["put_short_strike_price"], condor["call_short_strike_price"]
        )
        self.assertEqual(condor["position_greeks"]["status"], "aggregated")

    def test_condor_credit_is_the_sum_of_its_two_wings(self) -> None:
        _, candidate_research = _research()
        condor = candidate_research["iron_condors"]["eligible"][0]
        by_id = {
            item["candidate_id"]: item
            for name in ("call_credit_spreads", "put_credit_spreads")
            for item in candidate_research[name]["eligible"]
        }

        wings = by_id[condor["put_spread_id"]], by_id[condor["call_spread_id"]]
        self.assertAlmostEqual(
            condor["net_credit"],
            wings[0]["net_credit"] + wings[1]["net_credit"],
            places=6,
        )


class ScoredThroughTheWholePipelineTests(unittest.TestCase):
    def _projection(self) -> dict:
        return _build_research_report_v1_projection(
            generated_at=CAPTURED_AT,
            market_snapshot=_two_sided_snapshot(),
            persist_paper_ledger=False,
        )

    def test_new_structures_reach_the_ranked_table(self) -> None:
        ranked = self._projection()["ev_candidate_scanner"]["ranked_candidates"]

        structure_types = {row["structure_type"] for row in ranked}
        self.assertIn("put_credit_spread", structure_types)
        self.assertIn("iron_condor", structure_types)

    def test_defined_risk_structures_are_not_flagged_as_unbounded(self) -> None:
        ranked = self._projection()["ev_candidate_scanner"]["ranked_candidates"]

        for row in ranked:
            if row["structure_type"] in {
                "call_credit_spread",
                "put_credit_spread",
                "iron_condor",
            }:
                with self.subTest(candidate=row["candidate_id"]):
                    self.assertNotIn(
                        "UNBOUNDED_LOSS_STRUCTURE", row["kill_conditions"]
                    )

    def test_naked_shorts_are_still_flagged_as_unbounded(self) -> None:
        ranked = self._projection()["ev_candidate_scanner"]["ranked_candidates"]
        # Rejected rows never reach scoring, so they carry no kill conditions.
        naked = [
            row
            for row in ranked
            if row["structure_type"] == "naked_short_call"
            and row["action"] != "REJECT"
        ]

        self.assertTrue(naked)
        for row in naked:
            with self.subTest(candidate=row["candidate_id"]):
                self.assertIn("UNBOUNDED_LOSS_STRUCTURE", row["kill_conditions"])

    def test_the_report_carries_a_combination_view(self) -> None:
        combination = self._projection()["combination_risk"]

        self.assertIn(combination["status"], {"evaluated", "unavailable"})
        self.assertIs(combination["recommended_size_allowed"], False)
        self.assertEqual(combination["basis"], "one_contract_per_structure")

    def test_the_expanded_universe_still_emits_no_sizing(self) -> None:
        rendered = repr(self._projection())

        for forbidden in ("recommended_size", "order_instruction", "post_only_price"):
            self.assertNotIn(f"'{forbidden}':", rendered)


if __name__ == "__main__":
    unittest.main()
