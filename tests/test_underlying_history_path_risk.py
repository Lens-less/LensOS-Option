"""Path risk derived from self-sourced underlying price history.

These tests pin the two properties that make this evidence class honest: it
never claims to be option-quote reconciliation, and it publishes the
overlap-adjusted sample size rather than letting the similarity effective
sample size stand in for it.
"""

from __future__ import annotations

import unittest

from crypto_options_report.path_risk import (
    MIN_INDEPENDENT_UNDERLYING_WINDOWS,
    UNDERLYING_HISTORY_SOURCE,
    build_path_risk_report_from_underlying_history,
)
from crypto_options_report.realized_vol import build_realized_return_distribution

CANDIDATE = {
    "instrument_name": "BTC-RESEARCH-C",
    "structure": "naked_short_call",
    "current_spot": 100_000.0,
    "strike": 115_000.0,
    "horizon_days": 18,
    "entry_credit_usdc": 470.0,
    "contract_size": 1.0,
    "starting_nav_usdc": 100_000.0,
    "current_abs_delta": 0.13,
    "delta_cross_up_return": 0.12,
    "vega_usdc_per_abs_vol": 900.0,
    "target_realized_vol": 0.45,
    "regime_scores": {
        "bear_trend": 0.28,
        "range": 0.32,
        "squeeze": 0.5,
        "slow_bull": 0.22,
        "fast_bull_breakout": 0.18,
        "event": 0.05,
    },
    "feature_vector": {
        "dvol_percentile": 0.5,
        "atm_iv_percentile": 0.5,
        "trend_7d": 0.0,
    },
}


def history(days: int, *, resolution_seconds: int = 86400) -> dict:
    """Deterministic synthetic price series with a mild oscillation."""
    observations = []
    price = 100_000.0
    for index in range(days):
        price *= 1.0 + (0.004 if index % 3 else -0.005)
        observations.append(
            {
                "timestamp_ms": 1_700_000_000_000 + index * 86_400_000,
                "observed_at": f"2024-01-01T00:00:{index % 60:02d}Z",
                "close": round(price, 2),
            }
        )
    return {
        "schema_version": "underlying_price_history.v1",
        "source": "deribit_live:https://www.deribit.com",
        "instrument_name": "BTC-PERPETUAL",
        "resolution_seconds": resolution_seconds,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"] if observations else None,
        "last_observed_at": observations[-1]["observed_at"] if observations else None,
        "observations": observations,
    }


def build(days: int, **overrides):
    candidate = {**CANDIDATE, **overrides}
    return build_path_risk_report_from_underlying_history(
        history(days), candidate, generated_at="2026-07-26T00:00:00Z"
    )


class EvidenceClassTests(unittest.TestCase):
    def test_underlying_history_is_not_labelled_as_reconciliation(self):
        """Reconciled option quotes are a stronger class; do not borrow its name."""
        report = build(1200)
        evidence = report["input_evidence"]

        self.assertEqual("validated_historical", evidence["status"])
        self.assertEqual(UNDERLYING_HISTORY_SOURCE, evidence["evidence_class"])
        self.assertNotEqual(
            "validated_historical_reconciliation", evidence["evidence_class"]
        )
        self.assertIs(False, evidence["placeholder_data"])

    def test_evidence_states_what_it_excludes(self):
        report = build(1200)

        excludes = " ".join(report["input_evidence"]["excludes"]).lower()
        self.assertIn("option quotes", excludes)
        self.assertIn("fills", excludes)


class IndependentSampleTests(unittest.TestCase):
    def test_authoritative_sample_size_is_the_independent_window_count(self):
        report = build(1200)
        bound = report["independent_sample_bound"]

        self.assertEqual(1200 // 18, bound["independent_windows"])
        self.assertEqual(
            bound["independent_windows"], bound["authoritative_sample_size"]
        )
        self.assertEqual(
            "independent_non_overlapping_windows", bound["sample_size_basis"]
        )

    def test_similarity_effective_sample_size_is_marked_overlap_blind(self):
        """The ESS is far larger than the real sample; say so explicitly."""
        report = build(1200)
        bound = report["independent_sample_bound"]

        self.assertIs(False, bound["effective_sample_size_accounts_for_overlap"])
        self.assertGreater(
            bound["similarity_effective_sample_size"],
            bound["authoritative_sample_size"],
        )

    def test_overlapping_paths_are_reported_separately(self):
        report = build(1200)
        bound = report["independent_sample_bound"]

        self.assertGreater(bound["overlapping_paths"], bound["independent_windows"])


class FailClosedTests(unittest.TestCase):
    def test_too_few_independent_windows_blocks(self):
        # 18-day horizon over 200 days leaves 11 independent windows.
        report = build(200)

        self.assertEqual("blocked", report["input_evidence"]["status"])
        self.assertIn(
            "INSUFFICIENT_INDEPENDENT_UNDERLYING_WINDOWS",
            report["input_evidence"]["reason_codes"],
        )
        self.assertFalse(report["naked_short_allowed"])
        self.assertTrue(report["spread_only_required"])

    def test_blocked_report_still_states_the_shortfall(self):
        report = build(200)
        coverage = report["input_evidence"]["sample_coverage"]

        self.assertEqual(200 // 18, coverage["independent_windows"])
        self.assertEqual(
            MIN_INDEPENDENT_UNDERLYING_WINDOWS,
            coverage["minimum_independent_windows"],
        )

    def test_non_daily_resolution_is_rejected(self):
        """Independent-window accounting assumes one observation per day."""
        report = build_path_risk_report_from_underlying_history(
            history(1200, resolution_seconds=3600),
            CANDIDATE,
            generated_at="2026-07-26T00:00:00Z",
        )

        self.assertEqual("blocked", report["input_evidence"]["status"])
        self.assertIn(
            "NON_DAILY_UNDERLYING_RESOLUTION",
            report["input_evidence"]["reason_codes"],
        )

    def test_empty_history_is_rejected(self):
        report = build_path_risk_report_from_underlying_history(
            history(0), CANDIDATE, generated_at="2026-07-26T00:00:00Z"
        )

        self.assertEqual("blocked", report["input_evidence"]["status"])
        self.assertIn(
            "INVALID_UNDERLYING_HISTORY", report["input_evidence"]["reason_codes"]
        )

    def test_longer_horizon_blocks_before_a_shorter_one_on_the_same_history(self):
        """Confidence must fall as the horizon consumes the sample."""
        short_horizon = build(1200, horizon_days=18)
        long_horizon = build(1200, horizon_days=120)

        self.assertEqual("validated_historical", short_horizon["input_evidence"]["status"])
        self.assertEqual("blocked", long_horizon["input_evidence"]["status"])


class DistributionTests(unittest.TestCase):
    def test_validated_history_produces_traceable_distribution_metrics(self):
        report = build(1200)
        distributions = report["distributions"]

        for key in (
            "p_touch",
            "p_itm",
            "expected_payoff_usdc",
            "cvar_95_usdc",
            "cvar_99_usdc",
        ):
            self.assertIn(key, distributions)
        self.assertGreaterEqual(distributions["p_touch"], distributions["p_itm"])

    def test_realized_distribution_agrees_on_the_independent_window_count(self):
        """Both modules must derive the same sample size from the same history."""
        payload = history(1200)
        distribution = build_realized_return_distribution(
            history=payload, horizon_days=18, generated_at="2026-07-26T00:00:00Z"
        )
        report = build_path_risk_report_from_underlying_history(
            payload, CANDIDATE, generated_at="2026-07-26T00:00:00Z"
        )

        self.assertEqual(
            distribution["independent_window_count"],
            report["independent_sample_bound"]["independent_windows"],
        )


if __name__ == "__main__":
    unittest.main()
