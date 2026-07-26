"""Volatility scaling of the historical path set must be evidenced or absent.

The path-risk tracer used to rescale every historical window to a single target
volatility, and the expected-value scanner supplied that target as a hard-coded
`0.5`. Two things were wrong with it, and both are guarded here.

The first is provenance: in a product whose whole thesis is that no number
appears without evidence behind it, the single number most responsible for
whether "selling this is profitable" comes out positive was an unsourced
constant.

The second is statistical. Rescaling each window to a common volatility removes
volatility clustering and the dispersion of volatility across windows — exactly
the structure that produces a short-volatility seller's tail losses. The result
looks more precise while describing a market that never existed.
"""

from __future__ import annotations

import math
import unittest
from datetime import UTC, date, datetime, time, timedelta

from crypto_options_report.ev_scanner import (
    MISSING_CANDIDATE_GREEKS,
    build_absolute_ev,
)
from crypto_options_report.path_risk import (
    UNEVIDENCED_VOL_SCALING_TARGET,
    VOL_SCALING_EVIDENCE_TARGET,
    VOL_SCALING_NONE,
    build_path_risk_report_from_underlying_history,
)

NAKED = "naked_short_call"


def _history(days: int = 400, *, seed: int = 99) -> dict:
    """A path whose windows genuinely differ in realized volatility.

    A series with constant volatility could not distinguish scaling from not
    scaling, so the generator alternates calm and turbulent stretches.
    """
    state = seed
    price = 100_000.0
    start = date(2024, 1, 1)
    observations = []
    for index in range(days):
        state = (1103515245 * state + 12345) % (2**31)
        unit = state / float(2**31)
        amplitude = 0.02 if (index // 30) % 2 == 0 else 0.09
        price *= math.exp((unit - 0.5) * amplitude)
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
        "source": "test:alternating-volatility",
        "instrument_name": "BTC-PERPETUAL",
        "resolution_seconds": 86400,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def _candidate(**overrides) -> dict:
    base = {
        "instrument_name": "candidate",
        "structure": NAKED,
        "current_spot": 100_000.0,
        "strike": 112_000.0,
        "long_strike": None,
        "horizon_days": 7,
        "entry_credit_usdc": 300.0,
        "contract_size": 1.0,
        "starting_nav_usdc": 100_000.0,
        "current_abs_delta": 0.1,
        "delta_cross_up_return": 0.12,
        "vega_usdc_per_abs_vol": 2800.0,
        "regime_scores": {"neutral": 0.0},
        "feature_vector": {"neutral": 0.0},
    }
    base.update(overrides)
    return base


def _report(**overrides) -> dict:
    return build_path_risk_report_from_underlying_history(
        _history(),
        _candidate(**overrides),
        generated_at="2026-07-26T00:00:00Z",
    )


class DefaultIsNoScalingTests(unittest.TestCase):
    def test_absent_target_replays_windows_at_their_own_volatility(self) -> None:
        report = _report()

        scaling = report["path_sampling"]["volatility_scaling"]
        self.assertEqual(scaling["mode"], VOL_SCALING_NONE)
        self.assertIsNone(scaling["target_realized_vol"])
        self.assertIs(scaling["removes_volatility_dispersion"], False)
        for row in scaling["per_path_scale_factors"]:
            self.assertEqual(row["scale_factor"], 1.0)

    def test_the_dispersion_scaling_would_have_destroyed_is_reported(self) -> None:
        dispersion = _report()["path_sampling"]["volatility_scaling"][
            "observed_source_vol_dispersion"
        ]

        self.assertEqual(dispersion["status"], "observed")
        # The generator alternates calm and turbulent stretches, so a path set
        # that reported no spread would mean the measurement is broken.
        self.assertGreater(dispersion["max"], dispersion["min"] * 1.5)
        self.assertGreater(dispersion["stdev"], 0.0)


class ScalingChangesTheAnswerTests(unittest.TestCase):
    """Why the hard-coded target was load-bearing rather than cosmetic."""

    def test_scaling_to_a_target_moves_the_tail_and_the_assignment_odds(
        self,
    ) -> None:
        unscaled = _report()["distributions"]
        scaled = _report(
            vol_scaling={
                "mode": VOL_SCALING_EVIDENCE_TARGET,
                "target_realized_vol": 0.5,
                "evidence": {
                    "source": "test:measured",
                    "as_of": "2026-07-26T00:00:00Z",
                },
            }
        )["distributions"]

        self.assertNotEqual(unscaled["p_itm"], scaled["p_itm"])
        self.assertNotEqual(
            unscaled["expected_payoff_usdc"], scaled["expected_payoff_usdc"]
        )
        self.assertNotEqual(unscaled["cvar_95_usdc"], scaled["cvar_95_usdc"])


class EvidenceRequiredTests(unittest.TestCase):
    def test_evidence_target_without_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            _report(
                vol_scaling={
                    "mode": VOL_SCALING_EVIDENCE_TARGET,
                    "target_realized_vol": 0.5,
                }
            )

        self.assertIn("evidence", str(caught.exception))

    def test_evidence_without_a_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _report(
                vol_scaling={
                    "mode": VOL_SCALING_EVIDENCE_TARGET,
                    "target_realized_vol": 0.5,
                    "evidence": {"as_of": "2026-07-26T00:00:00Z"},
                }
            )

    def test_an_unknown_mode_is_rejected_rather_than_defaulted(self) -> None:
        with self.assertRaises(ValueError):
            _report(vol_scaling={"mode": "whatever_looks_reasonable"})

    def test_measured_evidence_is_carried_into_the_report(self) -> None:
        report = _report(
            vol_scaling={
                "mode": VOL_SCALING_EVIDENCE_TARGET,
                "target_realized_vol": 0.62,
                "evidence": {
                    "source": "deribit:DVOL",
                    "as_of": "2026-07-26T00:00:00Z",
                    "measure": "implied_volatility_index",
                },
            }
        )

        evidence = report["path_sampling"]["volatility_scaling"]["evidence"]
        self.assertEqual(evidence["status"], "measured")
        self.assertEqual(evidence["source"], "deribit:DVOL")
        self.assertEqual(evidence["measure"], "implied_volatility_index")


class LegacyTargetTests(unittest.TestCase):
    """Recorded fixtures keep replaying, but stop passing as a measurement."""

    def test_bare_target_still_scales_but_is_labelled_unevidenced(self) -> None:
        report = _report(target_realized_vol=0.5)

        scaling = report["path_sampling"]["volatility_scaling"]
        self.assertEqual(scaling["mode"], VOL_SCALING_EVIDENCE_TARGET)
        self.assertEqual(scaling["target_realized_vol"], 0.5)
        self.assertEqual(scaling["evidence"]["status"], "unevidenced")
        self.assertEqual(
            scaling["evidence"]["reason_code"], UNEVIDENCED_VOL_SCALING_TARGET
        )
        self.assertIs(scaling["removes_volatility_dispersion"], True)


class ExpectedValueScannerTests(unittest.TestCase):
    def _candidate(self, **overrides) -> dict:
        base = {
            "candidate_id": "naked-1",
            "underlying_price": 100_000.0,
            "strike_price": 112_000.0,
            "dte_days": 7.0,
            "model_delta": 0.11,
            "model_vega": 28.0,
            "premium_unit": "quote_currency",
        }
        base.update(overrides)
        return base

    def _ev(self, **overrides) -> dict:
        return build_absolute_ev(
            candidate=self._candidate(**overrides),
            structure_type=NAKED,
            underlying_history=_history(),
            entry_credit_usdc=300.0,
            permission_state={},
            generated_at="2026-07-26T00:00:00Z",
        )

    def test_expected_value_no_longer_assumes_a_volatility_level(self) -> None:
        result = self._ev()

        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["volatility_scaling"], VOL_SCALING_NONE)
        self.assertEqual(result["source_vol_dispersion"]["status"], "observed")

    def test_a_candidate_without_greeks_is_unavailable_not_defaulted(self) -> None:
        for field in ("model_delta", "model_vega"):
            with self.subTest(missing=field):
                result = self._ev(**{field: None})
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["reason_code"], MISSING_CANDIDATE_GREEKS)

    def test_a_zero_greek_is_treated_as_missing_rather_than_as_a_value(self) -> None:
        result = self._ev(model_vega=0.0)

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], MISSING_CANDIDATE_GREEKS)

    def test_a_strike_below_spot_is_now_a_legitimate_downside_structure(self) -> None:
        """The crossing diagnostic measures distance, not an assumed direction.

        It used to reject any strike at or below spot, which encoded "the risk
        is always above" into the expected-value path and made a put-side
        structure unrepresentable.
        """
        result = self._ev(strike_price=90_000.0)

        self.assertEqual(result["status"], "validated")

    def test_a_strike_exactly_at_spot_has_no_crossing_distance(self) -> None:
        result = self._ev(strike_price=100_000.0)

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], "STRIKE_EQUALS_SPOT")


class StructureGeneralityTests(unittest.TestCase):
    """The tracer prices legs, not structure names.

    Before the structure abstraction the terminal payoff was two hard-coded
    branches keyed on `naked_short_call` and `call_credit_spread`, both of which
    assumed the risk was on the upside. A downside structure could not be
    expressed at all, so this is the case that proves the branch is gone.
    """

    def _put_spread_report(self) -> dict:
        return build_path_risk_report_from_underlying_history(
            _history(),
            _candidate(
                structure="put_credit_spread",
                strike=90_000.0,
                long_strike=None,
                legs=[
                    {"option_type": "put", "strike": 90_000.0, "quantity": -1.0},
                    {"option_type": "put", "strike": 80_000.0, "quantity": 1.0},
                ],
                entry_credit_usdc=2_000.0,
                delta_cross_up_return=0.10,
            ),
            generated_at="2026-07-26T00:00:00Z",
        )

    def test_a_put_credit_spread_settles_on_the_downside(self) -> None:
        distributions = self._put_spread_report()["distributions"]

        # A downside structure must be able to finish in obligation at all; the
        # old upside-only branch would have reported a flat zero here.
        self.assertGreater(distributions["p_itm"], 0.0)
        self.assertGreater(distributions["expected_payoff_usdc"], 0.0)

    def test_the_obligation_is_capped_by_the_spread_width(self) -> None:
        report = self._put_spread_report()

        # The long 80k wing caps the obligation at the 10_000 width. A tail
        # above it would mean the wing was dropped and the position priced as a
        # naked short put.
        self.assertLessEqual(report["distributions"]["cvar_99_usdc"], 10_000.0)
        self.assertLessEqual(report["distributions"]["expected_payoff_usdc"], 10_000.0)

    def test_a_credit_above_the_structures_own_max_loss_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            build_path_risk_report_from_underlying_history(
                _history(),
                _candidate(
                    structure="put_credit_spread",
                    strike=90_000.0,
                    long_strike=None,
                    legs=[
                        {"option_type": "put", "strike": 90_000.0, "quantity": -1.0},
                        {"option_type": "put", "strike": 80_000.0, "quantity": 1.0},
                    ],
                    entry_credit_usdc=10_500.0,
                ),
                generated_at="2026-07-26T00:00:00Z",
            )

        self.assertIn("maximum loss", str(caught.exception))

    def test_an_unknown_structure_name_without_legs_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            build_path_risk_report_from_underlying_history(
                _history(),
                _candidate(structure="jade_lizard"),
                generated_at="2026-07-26T00:00:00Z",
            )

        self.assertIn("requires an explicit legs list", str(caught.exception))


class VegaUnitTests(unittest.TestCase):
    """The IV-jump stress leg is priced in absolute volatility, not IV points.

    `model_vega` is USD per one IV point; the stress scenarios quote `iv_jump`
    in absolute volatility where 1.0 is 100 points. Passing the per-point figure
    straight through understated every IV-jump stress cost a hundredfold.
    """

    def test_vega_is_converted_to_usd_per_absolute_volatility(self) -> None:
        vega_per_point = 28.0
        result = build_absolute_ev(
            candidate={
                "candidate_id": "naked-1",
                "underlying_price": 100_000.0,
                "strike_price": 112_000.0,
                "dte_days": 7.0,
                "model_delta": 0.11,
                "model_vega": vega_per_point,
                "premium_unit": "quote_currency",
            },
            structure_type=NAKED,
            underlying_history=_history(),
            entry_credit_usdc=300.0,
            permission_state={},
            generated_at="2026-07-26T00:00:00Z",
        )

        self.assertEqual(result["status"], "validated")
        # The conversion is observable through the stress leg: a 0.15 absolute
        # IV jump must cost 0.15 * vega_per_point * 100, not 0.15 * 28.
        self.assertGreater(abs(result["cvar_99_usdc"]), vega_per_point * 100 * 0.15)


if __name__ == "__main__":
    unittest.main()
