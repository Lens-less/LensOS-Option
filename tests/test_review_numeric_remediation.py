from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from crypto_options_report.historical import build_historical_reconciliation_report
from crypto_options_report.path_risk import build_path_risk_distribution_report
from crypto_options_report.regime import build_regime_permission_state
from crypto_options_report.surface import build_vol_surface_and_candidate_research


GENERATED_AT = "2026-07-07T00:01:30Z"


class ReviewNumericRemediationTests(unittest.TestCase):
    def test_surface_accepts_nonzero_no_arb_error_within_configured_tolerance(self):
        snapshot = _surface_snapshot(mids=[0.10, 0.05, 0.02, 0.0202])

        surface, _candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at=GENERATED_AT,
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        expiry = surface["expiries"][0]
        self.assertEqual(0.01, expiry["no_arb_error"])
        self.assertTrue(expiry["no_arb_pass"])
        self.assertTrue(expiry["candidate_eligible"])

    def test_surface_canonicalizes_declared_iv_units_before_fit_and_greeks(self):
        percent_snapshot = _surface_snapshot(mids=[0.10, 0.05, 0.02, 0.01])
        fraction_snapshot = deepcopy(percent_snapshot)
        for percent_row, fraction_row in zip(
            percent_snapshot["rows"],
            fraction_snapshot["rows"],
            strict=True,
        ):
            percent_row["ticker"]["iv_unit"] = "percent_points"
            fraction_row["ticker"]["iv_unit"] = "fraction"
            for field_name in ("bid_iv", "ask_iv", "mark_iv"):
                fraction_row["ticker"][field_name] /= 100.0

        percent_surface, _ = build_vol_surface_and_candidate_research(
            market_snapshot=percent_snapshot,
            generated_at=GENERATED_AT,
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )
        fraction_surface, _ = build_vol_surface_and_candidate_research(
            market_snapshot=fraction_snapshot,
            generated_at=GENERATED_AT,
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        percent_point = percent_surface["expiries"][0]["surface_points"][3]
        fraction_point = fraction_surface["expiries"][0]["surface_points"][3]
        self.assertEqual(percent_point["surface_fitted_iv"], fraction_point["surface_fitted_iv"])
        self.assertEqual(percent_point["model_delta"], fraction_point["model_delta"])
        self.assertEqual(
            {
                "input_unit": "fraction",
                "canonical_unit": "percent_points",
                "source": "declared",
            },
            fraction_point["iv_unit_provenance"],
        )

    def test_surface_without_iv_unit_fails_closed_for_live_and_fixture_inputs(self):
        snapshot = _surface_snapshot(mids=[0.10, 0.05, 0.02, 0.01])
        for row in snapshot["rows"]:
            row["ticker"].pop("iv_unit")

        for source in (
            "deribit_live:https://www.deribit.com",
            "fixture:review-numeric-remediation",
            "public_replay:pass",
        ):
            with self.subTest(source=source):
                snapshot["source"] = source
                surface, candidates = build_vol_surface_and_candidate_research(
                    market_snapshot=snapshot,
                    generated_at=GENERATED_AT,
                    data_status={"status": "validated"},
                    pnl_evidence={"status": "pass"},
                )

                self.assertEqual("blocked", surface["status"])
                self.assertEqual("AMBIGUOUS_IV_UNIT", surface["reason_code"])
                self.assertEqual("blocked", candidates["status"])
                self.assertEqual("AMBIGUOUS_IV_UNIT", candidates["reason_code"])

    def test_surface_rejects_conflicting_iv_unit_declarations(self):
        snapshot = _surface_snapshot(mids=[0.10, 0.05, 0.02, 0.01])
        snapshot["rows"][0]["iv_unit"] = "fraction"

        surface, candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at=GENERATED_AT,
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        self.assertEqual("blocked", surface["status"])
        self.assertEqual("AMBIGUOUS_IV_UNIT", surface["reason_code"])
        self.assertEqual("AMBIGUOUS_IV_UNIT", candidates["reason_code"])

    def test_surface_rejects_unknown_iv_unit_declarations_fail_closed(self):
        snapshot = _surface_snapshot(mids=[0.10, 0.05, 0.02, 0.01])
        snapshot["rows"][0]["ticker"]["iv_unit"] = "vol_points-ish"

        surface, candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at=GENERATED_AT,
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        self.assertEqual("blocked", surface["status"])
        self.assertEqual("AMBIGUOUS_IV_UNIT", surface["reason_code"])
        self.assertEqual("AMBIGUOUS_IV_UNIT", candidates["reason_code"])

    def test_path_risk_volatility_scaling_preserves_strictly_positive_prices(self):
        payload = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "path_risk_distribution_fixture.json"
            ).read_text(encoding="utf-8")
        )
        payload["historical_paths"][0]["returns"] = [-0.02, 0, 0, 0, 0, 0, 0]
        payload["historical_paths"][0]["source_realized_vol"] = 0.01

        report = build_path_risk_distribution_report(
            payload,
            generated_at="2026-07-07T10:30:00Z",
        )

        path = report["historical_path_records"][0]
        self.assertTrue(all(value > -1.0 for value in path["scaled_returns"]))
        self.assertTrue(all(level > 0.0 for level in path["normalized_spot_path"]))

    def test_path_risk_rejects_non_finite_or_total_loss_returns(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "path_risk_distribution_fixture.json"
        )
        for invalid_return in (-1.0, float("nan"), True):
            with self.subTest(invalid_return=invalid_return):
                payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                payload["historical_paths"][0]["returns"][0] = invalid_return
                with self.assertRaisesRegex(
                    ValueError,
                    "path returns must be finite and greater than -1",
                ):
                    build_path_risk_distribution_report(
                        payload,
                        generated_at="2026-07-07T10:30:00Z",
                    )

    def test_path_risk_requires_finite_positive_source_and_target_volatility(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "path_risk_distribution_fixture.json"
        )
        cases = (
            ("target_realized_vol", 0.0, "target_realized_vol"),
            ("target_realized_vol", -0.1, "target_realized_vol"),
            ("target_realized_vol", float("nan"), "target_realized_vol"),
            ("target_realized_vol", float("inf"), "target_realized_vol"),
            ("source_realized_vol", 0.0, "source_realized_vol"),
            ("source_realized_vol", -0.1, "source_realized_vol"),
            ("source_realized_vol", float("nan"), "source_realized_vol"),
            ("source_realized_vol", float("inf"), "source_realized_vol"),
        )
        for field_name, invalid_value, expected_error_field in cases:
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                if field_name == "target_realized_vol":
                    payload["candidate"][field_name] = invalid_value
                else:
                    payload["historical_paths"][0][field_name] = invalid_value
                with self.assertRaisesRegex(
                    ValueError,
                    rf"{expected_error_field} must be finite and positive",
                ):
                    build_path_risk_distribution_report(
                        payload,
                        generated_at="2026-07-07T10:30:00Z",
                    )

    def test_path_risk_rejects_non_finite_or_non_positive_scaling_outputs(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "path_risk_distribution_fixture.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["candidate"]["target_realized_vol"] = 1e308
        payload["historical_paths"][0]["source_realized_vol"] = 1e-308

        with self.assertRaisesRegex(
            ValueError,
            "scale_factor must be finite and positive",
        ):
            build_path_risk_distribution_report(
                payload,
                generated_at="2026-07-07T10:30:00Z",
            )

    def test_path_risk_rejects_scaled_price_underflow(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "path_risk_distribution_fixture.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["candidate"]["target_realized_vol"] = 100.0
        payload["historical_paths"][0]["source_realized_vol"] = 1.0
        payload["historical_paths"][0]["returns"][0] = -0.99

        with self.assertRaisesRegex(
            ValueError,
            "scaled path returns must remain finite and greater than -1",
        ):
            build_path_risk_distribution_report(
                payload,
                generated_at="2026-07-07T10:30:00Z",
            )

    def test_path_risk_scaling_evidence_is_finite_and_strictly_positive(self):
        payload = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "path_risk_distribution_fixture.json"
            ).read_text(encoding="utf-8")
        )

        report = build_path_risk_distribution_report(
            payload,
            generated_at="2026-07-07T10:30:00Z",
        )

        paths = [
            *report["historical_path_records"],
            *report["path_sampling"]["bootstrap"]["paths"],
            *report["stress_mixture"]["scenarios"],
        ]
        self.assertTrue(math.isfinite(report["candidate"]["target_realized_vol"]))
        self.assertGreater(report["candidate"]["target_realized_vol"], 0.0)
        for path in paths:
            with self.subTest(path_id=path["path_id"]):
                self.assertTrue(math.isfinite(path["source_realized_vol"]))
                self.assertGreater(path["source_realized_vol"], 0.0)
                self.assertTrue(math.isfinite(path["scale_factor"]))
                self.assertGreater(path["scale_factor"], 0.0)
                self.assertTrue(
                    all(math.isfinite(value) and value > -1.0 for value in path["scaled_returns"])
                )
                self.assertTrue(
                    all(math.isfinite(level) and level > 0.0 for level in path["normalized_spot_path"])
                )

    def test_historical_timezone_naive_timestamps_are_quarantined(self):
        rows = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "historical_vendor"
                / "pass_fixture.json"
            ).read_text(encoding="utf-8")
        )["rows"]
        for row in rows:
            row["timestamp"] = row["timestamp"].removesuffix("Z")

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("INELIGIBLE", report["eligibility"]["decision"])
        self.assertEqual(0, report["summary"]["eligible_quotes"])
        self.assertIn(
            "TIMESTAMP_ALIGNMENT_FAILED",
            report["summary"]["failure_counts"],
        )

    def test_historical_requires_an_explicit_supported_iv_unit(self):
        fixture_path = (
            Path(__file__).with_name("fixtures")
            / "historical_vendor"
            / "pass_fixture.json"
        )
        for invalid_unit in (None, "vol_points-ish", True):
            with self.subTest(invalid_unit=invalid_unit):
                rows = json.loads(fixture_path.read_text(encoding="utf-8"))["rows"]
                for row in rows:
                    if invalid_unit is None:
                        row.pop("iv_unit", None)
                    else:
                        row["iv_unit"] = invalid_unit

                report = build_historical_reconciliation_report(rows)

                self.assertEqual("INELIGIBLE", report["eligibility"]["decision"])
                self.assertEqual(0, report["summary"]["eligible_quotes"])
                self.assertIn("IV_SANITY_FAILED", report["summary"]["failure_counts"])

    def test_historical_canonicalizes_declared_iv_units_to_fraction(self):
        rows = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "historical_vendor"
                / "pass_fixture.json"
            ).read_text(encoding="utf-8")
        )["rows"]
        rows[0]["iv_unit"] = "fraction"
        rows[1]["iv_unit"] = "percent_points"

        report = build_historical_reconciliation_report(rows)

        self.assertEqual("ELIGIBLE", report["eligibility"]["decision"])
        quotes = report["canonical_data"]["eligible_quotes"]
        for quote, expected_mark_iv in zip(quotes, (0.61, 0.611), strict=True):
            self.assertEqual("fraction", quote["iv_unit"])
            self.assertAlmostEqual(expected_mark_iv, quote["mark_iv"])
        self.assertAlmostEqual(0.60, quotes[0]["bid_iv"])
        self.assertAlmostEqual(0.602, quotes[1]["bid_iv"])

    def test_historical_inverse_payoff_replay_uses_coin_denomination_tolerance(self):
        rows = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "historical_vendor"
                / "pass_fixture.json"
            ).read_text(encoding="utf-8")
        )["rows"]
        expected_payoff_coin = 5_000.0 / 105_000.0
        for row in rows:
            row["settlement_currency"] = "BTC"
            row["quote_currency"] = "BTC"
            row["recorded_long_payoff"] = expected_payoff_coin

        correct = build_historical_reconciliation_report(rows)
        self.assertEqual("ELIGIBLE", correct["eligibility"]["decision"])

        wrong_rows = deepcopy(rows)
        for row in wrong_rows:
            row["recorded_long_payoff"] = 9.0
        wrong = build_historical_reconciliation_report(wrong_rows)
        self.assertEqual("INELIGIBLE", wrong["eligibility"]["decision"])
        self.assertIn(
            "PAYOFF_REPLAY_FAILED",
            wrong["summary"]["failure_counts"],
        )

    def test_historical_inverse_payoff_uses_north_star_coin_precision(self):
        rows = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "historical_vendor"
                / "pass_fixture.json"
            ).read_text(encoding="utf-8")
        )["rows"]
        expected_payoff_coin = 5_000.0 / 105_000.0
        tolerance = max(1e-10, 1e-7 * abs(expected_payoff_coin))
        for row in rows:
            row["settlement_currency"] = "BTC"
            row["quote_currency"] = "BTC"
            row["recorded_long_payoff"] = expected_payoff_coin + tolerance * 0.9

        within_tolerance = build_historical_reconciliation_report(rows)
        self.assertEqual("ELIGIBLE", within_tolerance["eligibility"]["decision"])

        outside_rows = deepcopy(rows)
        for row in outside_rows:
            row["recorded_long_payoff"] = expected_payoff_coin + tolerance * 1.1
        outside_tolerance = build_historical_reconciliation_report(outside_rows)
        self.assertEqual("INELIGIBLE", outside_tolerance["eligibility"]["decision"])
        self.assertIn(
            "PAYOFF_REPLAY_FAILED",
            outside_tolerance["summary"]["failure_counts"],
        )

    def test_historical_payoff_replay_rejects_boolean_and_non_finite_numbers(self):
        fixture = json.loads(
            (
                Path(__file__).with_name("fixtures")
                / "historical_vendor"
                / "pass_fixture.json"
            ).read_text(encoding="utf-8")
        )["rows"]
        for field_name, invalid_value in (
            ("delivery_price", True),
            ("delivery_price", float("inf")),
            ("recorded_long_payoff", True),
            ("recorded_long_payoff", float("inf")),
        ):
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                rows = deepcopy(fixture)
                rows[0][field_name] = invalid_value

                report = build_historical_reconciliation_report(rows)

                self.assertNotEqual("ELIGIBLE", report["eligibility"]["decision"])
                self.assertFalse(report["eligibility"]["training_allowed"])
                self.assertFalse(report["eligibility"]["backtest_allowed"])
                self.assertIn(
                    "PAYOFF_REPLAY_FAILED",
                    report["summary"]["failure_counts"],
                )

    def test_regime_with_partial_scores_and_no_percentiles_is_always_collecting(self):
        for source in ("deribit_live:test", "fixture:review-numeric-remediation"):
            with self.subTest(source=source):
                permission = build_regime_permission_state(
                    market_snapshot={
                        "source": source,
                        "regime_inputs": {"range_score": 0.2},
                    },
                    data_status={"status": "validated"},
                    vol_surface_status={
                        "status": "validated",
                        "expiries": [
                            {"surface_points": [{"surface_fitted_iv": 60.0}]}
                        ],
                    },
                )

                self.assertEqual("blocked", permission["status"])
                self.assertEqual("collecting", permission["collection_status"])
                self.assertEqual(0.0, permission["sell_permission"])
                self.assertEqual(
                    "collecting",
                    permission["input_provenance"]["percentile_source"],
                )
                self.assertIn(
                    "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
                    permission["reason_codes"],
                )

    def test_regime_ignores_handwritten_complete_inputs_without_bound_history(self):
        permission = build_regime_permission_state(
            market_snapshot={
                "source": "deribit_live:test",
                "regime_inputs": {
                    "atm_iv_percentile": 0.9,
                    "dvol_percentile": 0.8,
                    "bear_trend_score": float("inf"),
                    "range_score": True,
                    "squeeze_score": 0.1,
                    "slow_bull_score": 0.1,
                    "fast_bull_breakout_score": 0.1,
                    "event_score": 0.1,
                },
            },
            data_status={"status": "validated"},
            vol_surface_status={
                "status": "validated",
                "expiries": [{"surface_points": [{"surface_fitted_iv": 60.0}]}],
            },
        )

        self.assertEqual("blocked", permission["status"])
        self.assertEqual("collecting", permission["collection_status"])
        self.assertEqual(0.0, permission["sell_permission"])
        self.assertFalse(permission["input_provenance"]["regime_inputs_present"])
        self.assertIn(
            "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
            permission["reason_codes"],
        )


def _surface_snapshot(*, mids: list[float]) -> dict:
    strikes = [90_000, 100_000, 110_000, 120_000]
    rows = []
    for strike, mid in zip(strikes, mids, strict=True):
        instrument_name = f"BTC-25JUL26-{strike}-C"
        bid = round(mid * 0.99, 8)
        ask = round(mid * 1.01, 8)
        rows.append(
            {
                "instrument_name": instrument_name,
                "summary": {
                    "instrument_name": instrument_name,
                    "base_currency": "BTC",
                    "quote_currency": "USD",
                    "settlement_currency": "USD",
                    "bid_price": bid,
                    "ask_price": ask,
                    "mid_price": mid,
                    "mark_price": mid,
                    "underlying_price": 100_000.0,
                    "open_interest": 20.0,
                    "creation_timestamp": 1_783_382_455_000,
                },
                "ticker": {
                    "instrument_name": instrument_name,
                    "iv_unit": "percent_points",
                    "timestamp": 1_783_382_455_000,
                    "best_bid_price": bid,
                    "best_ask_price": ask,
                    "best_bid_amount": 5.0,
                    "best_ask_amount": 5.0,
                    "mark_price": mid,
                    "bid_iv": 59.0,
                    "ask_iv": 61.0,
                    "mark_iv": 60.0,
                    "underlying_price": 100_000.0,
                    "open_interest": 20.0,
                },
            }
        )
    return {
        "captured_at": "2026-07-07T00:01:00Z",
        "currency": "BTC",
        "source": "fixture:review-numeric-remediation",
        "rows": rows,
    }


if __name__ == "__main__":
    unittest.main()
