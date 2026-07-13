import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from crypto_options_report.api import build_api_report, smoke_once
from crypto_options_report.contract import (
    DEFAULT_REASON_CODES,
    FORBIDDEN_RESEARCH_ONLY_KEYS,
    generate_research_report,
    report_shape,
    validate_report_contract,
)
from crypto_options_report.market_data import (
    build_market_data_status,
    load_snapshot_fixture,
    normalize_market_snapshot,
)
from crypto_options_report.surface import _candidate_filter_reasons


class ResearchReportContractTests(unittest.TestCase):
    def test_default_report_locks_required_schema(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("research_report.v1", report["schema_version"])
        self.assertEqual("research_only", report["mode"])
        self.assertEqual("research_only", report["effective_mode"])
        self.assertIn(report["action"], {"RESEARCH_ONLY", "NO_TRADE"})
        self.assertEqual("UNCALIBRATED", report["confidence"])
        self.assertEqual("HALT", report["risk_state"])
        self.assertEqual("pass", report["pnl_evidence"]["status"])

    def test_unavailable_and_pending_prerequisites_have_distinct_reason_codes(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        for code in DEFAULT_REASON_CODES[:3]:
            self.assertIn(code, report["reason_codes"])
        self.assertEqual(
            "MISSING_VALIDATED_MARKET_DATA",
            report["data_status"]["reason_code"],
        )
        self.assertEqual(
            "MISSING_ACCOUNT_API_SNAPSHOT",
            report["account_status"]["reason_code"],
        )
        self.assertEqual(
            "CALIBRATION_PROMOTION_PENDING",
            report["calibration_status"]["reason_code"],
        )
        self.assertEqual("BACKTEST_NOT_RUN", report["backtest_status"]["reason_code"])

    def test_research_only_mode_gate_blocks_trade_outputs(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        self.assertFalse(report["mode_gate"]["trade_recommendation_allowed"])
        self.assertFalse(report["mode_gate"]["recommended_size_allowed"])
        self.assertFalse(report["mode_gate"]["order_instructions_allowed"])
        self.assertFalse(report["mode_gate"]["paper_manual_candidates_allowed"])
        self.assertFalse(report["permission_state"]["paper_trading_allowed"])
        self.assertFalse(report["permission_state"]["manual_execution_allowed"])
        self.assertEqual(set(), self._forbidden_keys(report))

    def test_validator_rejects_unsafe_nested_state_mutations(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")
        mutated = copy.deepcopy(report)
        mutated["permission_state"]["sell_permission"] = 1.0
        mutated["permission_state"]["naked_permission"] = True
        mutated["permission_state"]["paper_trading_allowed"] = True
        mutated["data_status"]["status"] = "validated"
        mutated["data_status"]["validated"] = True
        mutated["account_status"]["status"] = "available"
        mutated["account_status"]["live_snapshot"] = True
        mutated["calibration_status"]["status"] = "calibrated"
        mutated["calibration_status"]["calibrated"] = True
        mutated["calibration_status"]["model_version"] = "unsafe"
        mutated["backtest_status"]["status"] = "aligned"
        mutated["backtest_status"]["aligned"] = True

        errors = validate_report_contract(mutated)

        self.assertTrue(errors)
        self.assertIn(
            "blocked permission_state must keep sell_permission at 0.0", errors
        )
        self.assertIn("market data status must include a source", errors)
        self.assertIn("market data status must include snapshot_captured_at", errors)
        self.assertIn("available account_status.snapshot is required", errors)
        self.assertIn("calibration_status must match walk-forward model registry", errors)
        self.assertIn("backtest_status.aligned must be false", errors)

    def test_validator_rejects_forbidden_actionable_aliases(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")
        report["candidate_preview"] = {
            "symbol": "BTC",
            "side": "sell",
            "quantity": 1,
            "limit_price": 10,
            "strike": 100000,
            "expiry": "2026-07-31",
        }

        errors = validate_report_contract(report)

        self.assertTrue(errors)
        self.assertTrue(
            any("forbidden research-only keys present" in error for error in errors)
        )

    def test_paper_and_manual_modes_still_no_trade_until_dod(self):
        for mode in ("paper", "manual_execution"):
            with self.subTest(mode=mode):
                report = generate_research_report(
                    mode=mode,
                    generated_at="2026-07-07T00:00:00Z",
                )
                self.assertEqual([], validate_report_contract(report))
                self.assertEqual("NO_TRADE", report["action"])
                self.assertIn("MODE_NOT_ENABLED", report["reason_codes"])

    def test_validator_rejects_bad_pnl_evidence_status(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")
        report["pnl_evidence"]["status"] = "unknown"

        errors = validate_report_contract(report)

        self.assertIn("pnl_evidence.status must be pass or fail", errors)

    def test_cli_and_api_share_report_shape(self):
        cli_report = self._run_cli_report()
        api_report = build_api_report()

        self.assertEqual([], validate_report_contract(cli_report))
        self.assertEqual([], validate_report_contract(api_report))
        self.assertEqual(report_shape(cli_report), report_shape(api_report))
        self.assertEqual(cli_report["mode_gate"], api_report["mode_gate"])

    def test_http_endpoint_returns_valid_report_shape(self):
        report = smoke_once()

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("research_only", report["mode"])
        self.assertIn(report["action"], {"RESEARCH_ONLY", "NO_TRADE"})

    def test_fresh_snapshot_passes_market_quality_gate(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_fixture(),
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY", report["action"])
        self.assertEqual("validated", report["data_status"]["status"])
        self.assertTrue(report["data_status"]["validated"])
        self.assertTrue(report["data_status"]["quality_gate"]["passed"])
        self.assertEqual(
            8,
            report["data_status"]["quality_gate"]["per_expiry"][0]["valid_quotes"],
        )
        self.assertNotIn("MISSING_VALIDATED_MARKET_DATA", report["reason_codes"])

    def test_stale_snapshot_forces_research_only_no_trade(self):
        snapshot = self._load_fixture()
        snapshot["captured_at"] = "2026-07-06T23:58:00Z"

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
        self.assertEqual("blocked", report["data_status"]["status"])
        self.assertIn(
            "MARKET_DATA_AGE_EXCEEDED",
            report["data_status"]["quality_gate"]["reason_codes"],
        )

    def test_bad_bid_ask_ratio_fails_quality_gate(self):
        snapshot = self._load_fixture()
        for row in snapshot["rows"][:3]:
            row["ticker"]["best_ask_price"] = row["ticker"]["best_bid_price"] - 0.01

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
        expiry_summary = report["data_status"]["quality_gate"]["per_expiry"][0]
        self.assertEqual("fail", expiry_summary["status"])
        self.assertIn("BAD_QUOTE_RATIO_EXCEEDED", expiry_summary["reason_codes"])
        self.assertIn("SPREAD_SANITY_FAILED", expiry_summary["reason_codes"])

    def test_insufficient_valid_quotes_fail_quality_gate(self):
        snapshot = self._load_fixture()
        snapshot["rows"][0]["ticker"]["best_ask_amount"] = 0
        snapshot["rows"][0]["ticker"]["best_bid_amount"] = 0

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY_NO_TRADE", report["action"])
        expiry_summary = report["data_status"]["quality_gate"]["per_expiry"][0]
        self.assertIn("INSUFFICIENT_VALID_QUOTES", expiry_summary["reason_codes"])
        self.assertEqual(7, expiry_summary["valid_quotes"])

    def test_cli_and_api_share_market_quality_report_shape(self):
        fixture_path = self._fixture_path()
        cli_report = self._run_cli_report(
            "--snapshot-fixture",
            str(fixture_path),
            "--account-scenario",
            "green",
            "--generated-at",
            "2026-07-07T00:01:30Z",
        )
        api_report = build_api_report(
            snapshot_fixture=str(fixture_path),
            account_scenario="green",
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual([], validate_report_contract(cli_report))
        self.assertEqual([], validate_report_contract(api_report))
        self.assertEqual(report_shape(cli_report), report_shape(api_report))
        self.assertIn("per_expiry", cli_report["data_status"]["quality_gate"])

    def test_http_endpoint_smoke_supports_fixture_snapshot(self):
        report = smoke_once(
            snapshot_fixture=str(self._fixture_path()),
            account_scenario="green",
            generated_at="2026-07-07T00:01:30Z",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertTrue(report["data_status"]["quality_gate"]["per_expiry"])

    def test_normalized_quotes_include_required_canonical_fields(self):
        normalized = normalize_market_snapshot(
            self._load_fixture(),
            now_ms=1783382490000,
        )
        first_quote = normalized["quotes"][0]

        for field_name in (
            "instrument_name",
            "base_currency",
            "quote_currency",
            "expiry_date",
            "strike",
            "option_type",
            "bid",
            "ask",
            "mid",
            "mark",
            "bid_iv",
            "ask_iv",
            "mark_iv",
            "underlying_price",
            "open_interest",
            "depth",
            "quote_age_sec",
            "source",
            "quality_status",
        ):
            self.assertIn(field_name, first_quote)

    def test_market_data_status_exposes_per_expiry_quality_summary(self):
        status = build_market_data_status(
            self._load_fixture(),
            now_ms=1783382490000,
        )

        self.assertTrue(status["validated"])
        self.assertTrue(status["quality_gate"]["passed"])
        self.assertEqual(1, len(status["quality_gate"]["per_expiry"]))

    def test_default_report_includes_surface_and_candidate_slices(self):
        report = generate_research_report(generated_at="2026-07-07T00:00:00Z")

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("missing", report["vol_surface_status"]["status"])
        self.assertEqual(
            "MISSING_VALIDATED_MARKET_DATA",
            report["candidate_research"]["reason_code"],
        )
        self.assertFalse(report["candidate_research"]["naked_short_calls"]["eligible"])
        self.assertEqual("blocked", report["permission_state"]["status"])
        self.assertEqual(0.0, report["permission_state"]["sell_permission"])

    def test_validated_snapshot_builds_surface_and_both_candidate_tables(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_fixture(),
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        expiry = report["vol_surface_status"]["expiries"][0]
        self.assertEqual("validated", report["vol_surface_status"]["status"])
        self.assertTrue(expiry["fit_quality_pass"])
        self.assertTrue(expiry["no_arb_pass"])
        self.assertEqual("validated", report["candidate_research"]["status"])
        self.assertGreater(
            len(report["candidate_research"]["naked_short_calls"]["eligible"]),
            0,
        )
        self.assertGreater(
            len(report["candidate_research"]["call_credit_spreads"]["eligible"]),
            0,
        )
        self.assertEqual("validated", report["ev_candidate_scanner"]["status"])
        self.assertGreater(
            len(report["ev_candidate_scanner"]["ranked_candidates"]),
            0,
        )
        self.assertEqual("validated", report["permission_state"]["status"])
        self.assertTrue(report["permission_state"]["label_is_report_only"])
        self.assertIn("primary_regime_label", report["permission_state"])
        self.assertIn("regime_scores", report["permission_state"])

    def test_ev_candidate_scanner_ranks_research_only_candidates_without_trade_outputs(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_fixture(),
            account_scenario="green",
        )

        scanner = report["ev_candidate_scanner"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("validated", scanner["status"])
        self.assertEqual("UNCALIBRATED_RESEARCH_ONLY", scanner["score_status"])
        self.assertFalse(scanner["recommended_size_allowed"])
        self.assertFalse(scanner["trade_instruction_allowed"])
        ranked = scanner["ranked_candidates"]
        self.assertGreater(len(ranked), 0)
        self.assertEqual(
            sorted(
                [candidate["ranking_score"] for candidate in ranked],
                reverse=True,
            ),
            [candidate["ranking_score"] for candidate in ranked],
        )
        first = ranked[0]
        self.assertIn(first["action"], {"RESEARCH_ONLY", "REVIEW", "REJECT"})
        self.assertIn("p_touch", first["path_risk"])
        self.assertIn("fair_physical_iv", first["fair_iv_diagnostics"])
        self.assertNotIn("recommended_size", first)
        self.assertNotIn("trade_instruction", first)

    def test_ev_candidate_scanner_kills_non_positive_ev(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_fixture(),
            account_scenario="green",
        )

        candidate = report["ev_candidate_scanner"]["ranked_candidates"][0]
        self.assertIn("NON_POSITIVE_EV", candidate["kill_conditions"])
        self.assertEqual("REJECT", candidate["action"])

    def test_ev_candidate_scanner_kills_bid_iv_below_fair_physical_iv(self):
        snapshot = self._load_fixture()
        row = snapshot["rows"][6]
        row["ticker"]["bid_iv"] = 20.0

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        candidate = next(
            item
            for item in report["ev_candidate_scanner"]["ranked_candidates"]
            if item["candidate_id"] == "BTC-25JUL26-120000-C:naked"
        )
        self.assertIn("BID_IV_BELOW_FAIR_PHYSICAL_IV", candidate["kill_conditions"])
        self.assertEqual("REJECT", candidate["action"])

    def test_ev_candidate_scanner_kills_insufficient_depth(self):
        snapshot = self._load_fixture()
        row = snapshot["rows"][6]
        row["ticker"]["best_bid_amount"] = 1.0
        row["ticker"]["best_ask_amount"] = 1.0

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        candidate = next(
            item
            for item in report["ev_candidate_scanner"]["ranked_candidates"]
            if item["candidate_id"] == "BTC-25JUL26-120000-C:naked"
        )
        self.assertIn("INSUFFICIENT_DEPTH", candidate["kill_conditions"])

    def test_ev_candidate_scanner_kills_breakout_state(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.86,
            range_score=0.24,
            squeeze_score=0.18,
            slow_bull_score=0.20,
            fast_bull_breakout_score=0.74,
            event_score=0.05,
            dvol_percentile=0.46,
            atm_iv_percentile=0.44,
        )

        candidate = report["ev_candidate_scanner"]["ranked_candidates"][0]
        self.assertIn("BREAKOUT_KILL", candidate["kill_conditions"])
        self.assertEqual("REJECT", candidate["action"])

    def test_ev_candidate_scanner_kills_yellow_account_new_trades(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=self._load_fixture(),
            account_scenario="yellow",
        )

        candidate = report["ev_candidate_scanner"]["ranked_candidates"][0]
        self.assertIn("YELLOW_NO_NEW_TRADES", candidate["kill_conditions"])
        self.assertEqual("REJECT", candidate["action"])

    def test_ev_candidate_scanner_kills_settlement_window_for_short_dated_candidates(self):
        snapshot = self._load_fixture()
        snapshot["captured_at"] = "2026-07-07T07:44:40Z"
        # Keep required vol_index feed fresh relative to the mutated capture time.
        feeds = snapshot.setdefault("feeds", {})
        vol_index = dict(feeds.get("vol_index") or {})
        vol_index["timestamp"] = "2026-07-07T07:44:30Z"
        feeds["vol_index"] = vol_index
        for row in snapshot["rows"]:
            row["summary"]["creation_timestamp"] = 1783410280000
            row["ticker"]["timestamp"] = 1783410280000

        report = generate_research_report(
            generated_at="2026-07-07T07:45:00Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual("validated", report["data_status"]["status"])
        self.assertTrue(report["ev_candidate_scanner"]["ranked_candidates"])
        candidate = report["ev_candidate_scanner"]["ranked_candidates"][0]
        self.assertIn("SETTLEMENT_WINDOW_ACTIVE", candidate["kill_conditions"])
        self.assertIn("PLACEHOLDER_PATH_RISK", candidate["kill_conditions"])

    def test_regime_scores_include_all_issue_008_dimensions(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.82,
            range_score=0.22,
            squeeze_score=0.18,
            slow_bull_score=0.12,
            fast_bull_breakout_score=0.10,
            event_score=0.05,
            dvol_percentile=0.52,
            atm_iv_percentile=0.48,
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual(
            {
                "bear_trend",
                "range",
                "squeeze",
                "slow_bull",
                "fast_bull_breakout",
                "event",
                "volatility_stress",
                "data_quality",
            },
            set(report["permission_state"]["regime_scores"]),
        )

    def test_bear_normal_vol_keeps_positive_sell_permission(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.82,
            range_score=0.20,
            squeeze_score=0.18,
            slow_bull_score=0.15,
            fast_bull_breakout_score=0.10,
            event_score=0.05,
            dvol_percentile=0.52,
            atm_iv_percentile=0.48,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("Bear Trend", permission_state["primary_regime_label"])
        self.assertEqual(0.75, permission_state["sell_permission"])
        self.assertTrue(permission_state["naked_permission"])
        self.assertTrue(permission_state["spread_permission"])
        self.assertIn("BEAR_TREND_PERMISSION_ACTIVE", permission_state["reason_codes"])

    def test_bear_extreme_vol_applies_cap_even_in_bear_trend(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.84,
            range_score=0.18,
            squeeze_score=0.10,
            slow_bull_score=0.12,
            fast_bull_breakout_score=0.08,
            event_score=0.04,
            dvol_percentile=0.97,
            atm_iv_percentile=0.91,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("Bear Trend", permission_state["primary_regime_label"])
        self.assertEqual(0.2, permission_state["sell_permission"])
        self.assertFalse(permission_state["naked_permission"])
        self.assertTrue(permission_state["spread_permission"])
        self.assertEqual("volatility_stress", permission_state["limiting_dimension"])
        self.assertIn("VOLATILITY_CAP_20", permission_state["reason_codes"])

    def test_squeeze_forces_spread_only_cap(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.28,
            range_score=0.34,
            squeeze_score=0.72,
            slow_bull_score=0.22,
            fast_bull_breakout_score=0.18,
            event_score=0.02,
            dvol_percentile=0.45,
            atm_iv_percentile=0.41,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("Squeeze", permission_state["primary_regime_label"])
        self.assertEqual(0.25, permission_state["sell_permission"])
        self.assertFalse(permission_state["naked_permission"])
        self.assertTrue(permission_state["spread_permission"])
        self.assertIn("SQUEEZE_SPREAD_ONLY_CAP", permission_state["reason_codes"])

    def test_slow_bull_forces_spread_only_cap(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.22,
            range_score=0.24,
            squeeze_score=0.30,
            slow_bull_score=0.67,
            fast_bull_breakout_score=0.20,
            event_score=0.05,
            dvol_percentile=0.50,
            atm_iv_percentile=0.44,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("Slow Bull", permission_state["primary_regime_label"])
        self.assertEqual(0.15, permission_state["sell_permission"])
        self.assertFalse(permission_state["naked_permission"])
        self.assertTrue(permission_state["spread_permission"])
        self.assertIn("SLOW_BULL_SPREAD_ONLY_CAP", permission_state["reason_codes"])

    def test_breakout_kill_beats_primary_report_label(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.86,
            range_score=0.24,
            squeeze_score=0.18,
            slow_bull_score=0.20,
            fast_bull_breakout_score=0.74,
            event_score=0.05,
            dvol_percentile=0.46,
            atm_iv_percentile=0.44,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("Bear Trend", permission_state["primary_regime_label"])
        self.assertEqual(0.0, permission_state["sell_permission"])
        self.assertFalse(permission_state["naked_permission"])
        self.assertFalse(permission_state["spread_permission"])
        self.assertEqual("fast_bull_breakout", permission_state["limiting_dimension"])
        self.assertTrue(permission_state["label_is_report_only"])
        self.assertIn("BREAKOUT_KILL", permission_state["reason_codes"])

    def test_event_kill_forces_zero_permission(self):
        report = self._report_with_regime_inputs(
            bear_trend_score=0.78,
            range_score=0.20,
            squeeze_score=0.18,
            slow_bull_score=0.18,
            fast_bull_breakout_score=0.15,
            event_score=0.66,
            dvol_percentile=0.43,
            atm_iv_percentile=0.38,
        )

        permission_state = report["permission_state"]
        self.assertEqual([], validate_report_contract(report))
        self.assertEqual(0.0, permission_state["sell_permission"])
        self.assertFalse(permission_state["naked_permission"])
        self.assertFalse(permission_state["spread_permission"])
        self.assertEqual("event", permission_state["limiting_dimension"])
        self.assertIn("EVENT_KILL", permission_state["reason_codes"])

    def test_narrative_labels_are_ignored_for_permission_output(self):
        base_inputs = {
            "bear_trend_score": 0.82,
            "range_score": 0.21,
            "squeeze_score": 0.19,
            "slow_bull_score": 0.16,
            "fast_bull_breakout_score": 0.10,
            "event_score": 0.03,
            "dvol_percentile": 0.51,
            "atm_iv_percentile": 0.47,
        }
        left = self._report_with_regime_inputs(
            **base_inputs,
            narrative_label="slow bull story",
            historical_phase_label="manual-bear-tag",
        )
        right = self._report_with_regime_inputs(
            **base_inputs,
            narrative_label="squeeze story",
            historical_phase_label="manual-range-tag",
        )

        self.assertEqual([], validate_report_contract(left))
        self.assertEqual([], validate_report_contract(right))
        self.assertEqual(
            left["permission_state"]["sell_permission"],
            right["permission_state"]["sell_permission"],
        )
        self.assertEqual(
            left["permission_state"]["naked_permission"],
            right["permission_state"]["naked_permission"],
        )
        self.assertEqual(
            left["permission_state"]["primary_regime_label"],
            right["permission_state"]["primary_regime_label"],
        )
        self.assertEqual(
            ["historical_phase_label", "narrative_label"],
            left["permission_state"]["ignored_inputs"],
        )
        self.assertEqual(
            ["historical_phase_label", "narrative_label"],
            right["permission_state"]["ignored_inputs"],
        )

    def test_low_fit_quality_blocks_expiry_from_candidates(self):
        snapshot = self._load_fixture()
        distorted_ivs = [58.5, 66.0, 52.0, 63.0, 49.0, 61.0, 48.0, 60.0]
        for row, mark_iv in zip(snapshot["rows"], distorted_ivs):
            row["ticker"]["mark_iv"] = mark_iv
            row["ticker"]["bid_iv"] = mark_iv - 0.5
            row["ticker"]["ask_iv"] = mark_iv + 0.5

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        expiry = report["vol_surface_status"]["expiries"][0]
        self.assertFalse(expiry["fit_quality_pass"])
        self.assertIn("SURFACE_FIT_QUALITY_TOO_LOW", expiry["reason_codes"])
        self.assertEqual("blocked", report["candidate_research"]["status"])
        self.assertEqual(
            "SURFACE_QUALITY_FAIL",
            report["candidate_research"]["reason_code"],
        )

    def test_no_arb_failure_excludes_expiry_from_candidates(self):
        snapshot = self._load_fixture()
        row = snapshot["rows"][6]
        row["summary"]["bid_price"] = 0.11
        row["summary"]["ask_price"] = 0.118
        row["summary"]["mid_price"] = 0.114
        row["summary"]["mark_price"] = 0.1145
        row["ticker"]["best_bid_price"] = 0.11
        row["ticker"]["best_ask_price"] = 0.118
        row["ticker"]["mark_price"] = 0.1145

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        expiry = report["vol_surface_status"]["expiries"][0]
        self.assertFalse(expiry["no_arb_pass"])
        self.assertIn("SURFACE_NO_ARBITRAGE_FAIL", expiry["reason_codes"])
        self.assertEqual("blocked", report["candidate_research"]["status"])

    def test_candidate_filter_rejects_low_open_interest(self):
        snapshot = self._load_fixture()
        snapshot["rows"][6]["summary"]["open_interest"] = 2.0
        snapshot["rows"][6]["ticker"]["open_interest"] = 2.0

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        rejected = report["candidate_research"]["naked_short_calls"]["rejected"]
        candidate = next(
            item
            for item in rejected
            if item["instrument_name"] == "BTC-25JUL26-120000-C"
        )
        self.assertIn("OPEN_INTEREST_TOO_LOW", candidate["filter_reason_codes"])

    def test_exchange_model_delta_diff_marks_candidate_reject(self):
        snapshot = self._load_fixture()
        snapshot["rows"][6]["ticker"]["greeks"] = {"delta": 0.25}

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        rejected = report["candidate_research"]["naked_short_calls"]["rejected"]
        candidate = next(
            item
            for item in rejected
            if item["instrument_name"] == "BTC-25JUL26-120000-C"
        )
        self.assertIn(
            "MODEL_EXCHANGE_DELTA_REJECT",
            candidate["decision_reason_codes"],
        )

    def test_exchange_model_delta_diff_marks_candidate_review(self):
        snapshot = self._load_fixture()
        snapshot["rows"][6]["ticker"]["greeks"] = {"delta": 0.11}

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        review = report["candidate_research"]["naked_short_calls"]["review"]
        candidate = next(
            item
            for item in review
            if item["instrument_name"] == "BTC-25JUL26-120000-C"
        )
        self.assertIn(
            "MODEL_EXCHANGE_DELTA_REVIEW",
            candidate["decision_reason_codes"],
        )

    def test_candidate_filter_rejects_low_bid_and_wide_spread_ratio(self):
        snapshot = self._load_fixture()
        row = snapshot["rows"][7]
        row["summary"]["bid_price"] = 0.04
        row["summary"]["ask_price"] = 0.06
        row["ticker"]["best_bid_price"] = 0.04
        row["ticker"]["best_ask_price"] = 0.06

        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        rejected = report["candidate_research"]["naked_short_calls"]["rejected"]
        candidate = next(
            item
            for item in rejected
            if item["instrument_name"] == "BTC-25JUL26-125000-C"
        )
        self.assertIn("BID_TOO_LOW", candidate["filter_reason_codes"])
        self.assertIn("SPREAD_RATIO_TOO_WIDE", candidate["filter_reason_codes"])

    def test_candidate_filter_helper_covers_dte_delta_quote_age_and_surface_quality(self):
        expiry_report = {
            "dte_days": 3.0,
            "candidate_eligible": False,
        }
        point = {
            "model_delta": 0.2,
            "market_bid": 0.08,
            "open_interest": 12.0,
            "spread_ratio": 0.12,
            "quote_age_sec": 121.0,
        }

        reasons = _candidate_filter_reasons(point, expiry_report)

        self.assertIn("DTE_OUT_OF_RANGE", reasons)
        self.assertIn("DELTA_OUT_OF_RANGE", reasons)
        self.assertIn("QUOTE_TOO_STALE", reasons)
        self.assertIn("SURFACE_QUALITY_BLOCKED", reasons)

    def test_green_account_snapshot_includes_margin_fields(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="green",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY", report["action"])
        self.assertEqual("GREEN", report["risk_state"])
        self.assertEqual("GREEN", report["account_status"]["margin_light"])
        self.assertEqual("ALLOW_NEW", report["account_status"]["trade_gate"])
        snapshot = report["account_status"]["snapshot"]
        for field_name in (
            "equity",
            "balance",
            "margin_balance",
            "available_funds",
            "initial_margin",
            "maintenance_margin",
            "nav_usd",
            "im_nav",
            "nav_to_mm",
            "margin_model",
            "source_endpoint",
            "data_age_ms",
        ):
            self.assertIn(field_name, snapshot)
        position = report["account_status"]["positions"][0]
        for field_name in (
            "size",
            "direction",
            "mark_price",
            "index_price",
            "pnl",
            "initial_margin",
            "maintenance_margin",
            "greeks",
        ):
            self.assertIn(field_name, position)
        self.assertEqual("available", report["account_status"]["projected_margin"]["status"])

    def test_yellow_account_blocks_new_trades(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="yellow",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY", report["action"])
        self.assertEqual("YELLOW", report["risk_state"])
        self.assertEqual("YELLOW", report["account_status"]["margin_light"])
        self.assertEqual("NO_NEW_TRADES", report["account_status"]["trade_gate"])
        self.assertIn("ACCOUNT_MARGIN_YELLOW_NO_NEW_TRADES", report["reason_codes"])

    def test_red_account_requires_reduce_existing(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="red",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("RESEARCH_ONLY", report["action"])
        self.assertEqual("RED", report["risk_state"])
        self.assertEqual("RED", report["account_status"]["margin_light"])
        self.assertEqual("REDUCE_EXISTING", report["account_status"]["trade_gate"])
        self.assertIn("ACCOUNT_MARGIN_RED_REDUCE_EXISTING", report["reason_codes"])

    def test_stale_account_forces_no_trade(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="stale",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("NO_TRADE", report["action"])
        self.assertEqual("HALT", report["risk_state"])
        self.assertEqual("stale", report["account_status"]["status"])
        self.assertEqual("NO_TRADE", report["account_status"]["trade_gate"])
        self.assertIn("STALE_ACCOUNT_DATA", report["reason_codes"])

    def test_simulation_unavailable_forces_no_trade(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="simulation_unavailable",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("NO_TRADE", report["action"])
        self.assertEqual("HALT", report["risk_state"])
        self.assertEqual("HALT", report["account_status"]["margin_light"])
        self.assertEqual("NO_TRADE", report["account_status"]["trade_gate"])
        self.assertEqual(
            "unavailable",
            report["account_status"]["simulation_status"]["status"],
        )
        self.assertEqual(
            "unavailable",
            report["account_status"]["projected_margin"]["status"],
        )
        self.assertIn("SIMULATION_UNAVAILABLE", report["reason_codes"])

    def test_auth_failed_account_forces_no_trade(self):
        report = generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            account_scenario="auth_failed",
        )

        self.assertEqual([], validate_report_contract(report))
        self.assertEqual("NO_TRADE", report["action"])
        self.assertEqual("HALT", report["risk_state"])
        self.assertEqual("auth_failed", report["account_status"]["status"])
        self.assertEqual("NO_TRADE", report["account_status"]["trade_gate"])
        self.assertIn("AUTH_FAILED_ACCOUNT_API", report["reason_codes"])

    def _run_cli_report(self, *extra_args):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "crypto_options_report.cli",
                "report",
                "--mode",
                "research_only",
                "--compact",
                *extra_args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def _fixture_path(self):
        return Path(__file__).with_name("fixtures") / "deribit_btc_option_chain_snapshot.json"

    def _load_fixture(self):
        return load_snapshot_fixture(self._fixture_path())

    def _report_with_regime_inputs(self, **regime_inputs):
        snapshot = self._load_fixture()
        snapshot["regime_inputs"] = regime_inputs
        return generate_research_report(
            generated_at="2026-07-07T00:01:30Z",
            market_snapshot=snapshot,
            account_scenario="green",
        )

    def _forbidden_keys(self, value):
        if isinstance(value, dict):
            found = set(value).intersection(FORBIDDEN_RESEARCH_ONLY_KEYS)
            for nested in value.values():
                found.update(self._forbidden_keys(nested))
            return found
        if isinstance(value, list):
            found = set()
            for item in value:
                found.update(self._forbidden_keys(item))
            return found
        return set()


if __name__ == "__main__":
    unittest.main()
