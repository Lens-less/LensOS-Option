from __future__ import annotations

import unittest
from types import SimpleNamespace

from crypto_options_report.analysis_run import _strategy_brief_candidates
from crypto_options_report.strategy_brief import (
    build_strategy_brief,
    validate_strategy_brief,
)

FIXED_CLOCK = "2026-08-30T14:30:05Z"


def _market() -> dict[str, object]:
    return {
        "as_of": FIXED_CLOCK,
        "expires_at": "2026-08-30T14:35:05Z",
        "direction": "RANGE",
        "volatility": "RICH",
        "liquidity": "EXECUTABLE",
        "confidence": "HIGH",
    }


def _record_stub() -> object:
    return SimpleNamespace(
        manifest=SimpleNamespace(evaluation_clock=FIXED_CLOCK),
        opportunities=(),
        strategy_plans=(),
    )


def _fallback_candidate(*, candidate_id: str = "fallback-bear-call") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "structure_type": "call_credit_spread",
        "option_type": "call",
        "expiry_date": "2026-09-25",
        "sell_leg_instrument_name": "BTC-25SEP26-128000-C",
        "sell_leg_strike_price": 128_000.0,
        "sell_leg_market_bid": 1_100.0,
        "sell_leg_market_ask": 1_150.0,
        "buy_leg_instrument_name": "BTC-25SEP26-132000-C",
        "buy_leg_strike_price": 132_000.0,
        "buy_leg_market_bid": 650.0,
        "buy_leg_market_ask": 700.0,
        "premium_unit": "quote_currency",
        "premium_currency": "USD",
        "settlement_currency": "USD",
        "valid_until": "2026-08-30T14:34:55Z",
        "cost_components_complete": True,
        "relative_value_status": "AVAILABLE",
        "ranking_score": 1.0,
        "ev_after_cost": 210.0,
        "path_risk": {"status": "validated_historical", "cvar_95": 1_900.0},
        "robustness": {
            "verdict": {"code": "positive_across_periods_and_execution"}
        },
        "structure_legs": [
            {
                "instrument_name": "BTC-25SEP26-128000-C",
                "option_type": "call",
                "strike": 128_000.0,
                "quantity": -1.0,
                "expiry_date": "2026-09-25",
            },
            {
                "instrument_name": "BTC-25SEP26-132000-C",
                "option_type": "call",
                "strike": 132_000.0,
                "quantity": 1.0,
                "expiry_date": "2026-09-25",
            },
        ],
    }


def _projection(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "generated_at": FIXED_CLOCK,
        "candidate_research": {
            "call_credit_spreads": {
                "eligible": [candidate],
                "review": [],
                "rejected": [],
            }
        },
        "ev_candidate_scanner": {"ranked_candidates": [candidate]},
    }


def _project_brief(candidate: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    candidates = _strategy_brief_candidates(_record_stub(), _projection(candidate))
    brief = build_strategy_brief(
        analysis_run_id="analysis:fallback-leg-timestamps",
        generated_at=FIXED_CLOCK,
        market=_market(),
        candidates=candidates,
        policy_ttl_seconds=600,
    )
    return candidates, brief


class StrategyBriefFallbackLegTimestampTests(unittest.TestCase):
    def test_fallback_preserves_source_leg_timestamps_and_rejects_stale_quotes(self) -> None:
        candidate = _fallback_candidate(candidate_id="stale-fallback")
        candidate["structure_legs"][0]["observed_at"] = "2026-08-30T14:20:01Z"
        candidate["structure_legs"][1]["observed_at"] = "2026-08-30T14:20:02Z"

        candidates, brief = _project_brief(candidate)

        self.assertEqual(
            ["2026-08-30T14:20:01Z", "2026-08-30T14:20:02Z"],
            [leg["observed_at"] for leg in candidates[0]["structure_legs"]],
        )
        self.assertEqual("2026-08-30T14:20:02Z", candidates[0]["observed_at"])
        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get("STALE_MARKET_DATA"),
        )

    def test_fallback_preserves_desynced_leg_timestamps_and_rejects_unsynced_quotes(self) -> None:
        candidate = _fallback_candidate(candidate_id="desynced-fallback")
        candidate["structure_legs"][0]["observed_at"] = "2026-08-30T14:30:01Z"
        candidate["structure_legs"][1]["observed_at"] = "2026-08-30T14:30:04Z"

        candidates, brief = _project_brief(candidate)

        self.assertEqual(
            ["2026-08-30T14:30:01Z", "2026-08-30T14:30:04Z"],
            [leg["observed_at"] for leg in candidates[0]["structure_legs"]],
        )
        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get("LEGS_NOT_SYNCHRONIZED"),
        )

    def test_fallback_refuses_to_synthesize_missing_leg_timestamps(self) -> None:
        candidate = _fallback_candidate(candidate_id="missing-fallback")
        candidate["structure_legs"][0]["observed_at"] = "2026-08-30T14:30:01Z"
        candidate["structure_legs"][1].pop("observed_at", None)

        candidates, brief = _project_brief(candidate)

        self.assertNotIn("structure_legs", candidates[0])
        self.assertNotIn("observed_at", candidates[0])
        self.assertEqual([], validate_strategy_brief(brief))
        self.assertEqual("NO_TRADE", brief["action"])
        self.assertEqual(
            1,
            brief["evidence_summary"]["rejection_counts"].get("UNSUPPORTED_STRUCTURE"),
        )


if __name__ == "__main__":
    unittest.main()
