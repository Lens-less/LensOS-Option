from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from math import log
from pathlib import Path

from crypto_options_report.market_data import (
    _rolling_observation_from_snapshot,
    _sanitize_rolling_observations,
    load_snapshot_fixture,
    write_snapshot_fixture,
    write_snapshot_trust_state,
)
from crypto_options_report.regime import (
    _exchange_event_score,
    build_regime_permission_state,
)
from crypto_options_report.surface import build_vol_surface_and_candidate_research


class SurfaceRegimeRuntimeTests(unittest.TestCase):
    def test_uncollected_macro_calendar_is_not_zero_event_risk(self):
        self.assertIsNone(
            _exchange_event_score(
                {
                    "exchange_locked": False,
                    "locked_currencies": [],
                    "locked_indices": [],
                    "macro_events": None,
                    "macro_events_status": "not_collected",
                    "scope": "exchange_native_only",
                }
            )
        )
        self.assertIsNone(
            _exchange_event_score(
                {
                    "exchange_locked": False,
                    "locked_currencies": [],
                    "locked_indices": [],
                    "macro_events": [],
                    "scope": "exchange_native_only",
                }
            )
        )
        self.assertEqual(
            0.0,
            _exchange_event_score(
                {
                    "exchange_locked": False,
                    "locked_currencies": [],
                    "locked_indices": [],
                    "macro_events": [],
                    "macro_events_status": "collected",
                }
            ),
        )

    def test_rolling_observation_respects_explicit_percent_point_iv_unit(self):
        snapshot = {
            "captured_at": "2026-07-14T00:00:00Z",
            "source": "test",
            "feeds": {
                "index_spot": {"index_price": 100_000.0},
                "vol_index": {"volatility": 0.5},
                "funding_basis": {"funding_rate": 0.0001},
            },
            "rows": [
                {
                    "instrument_name": "BTC-31JUL26-100000-C",
                    "ticker": {
                        "instrument_name": "BTC-31JUL26-100000-C",
                        "mark_iv": 4.0,
                        "iv_unit": "percent_points",
                        "underlying_price": 100_000.0,
                    },
                }
            ],
        }

        observation = _rolling_observation_from_snapshot(snapshot)

        self.assertIsNotNone(observation)
        self.assertEqual(0.04, observation["atm_iv"])
        self.assertEqual("fraction", observation["iv_unit"])

    def test_rolling_observation_rejects_missing_or_conflicting_iv_units(self):
        snapshot = {
            "captured_at": "2026-07-14T00:00:00Z",
            "source": "test",
            "feeds": {
                "index_spot": {"index_price": 100_000.0},
                "vol_index": {"volatility": 0.5},
                "funding_basis": {"funding_rate": 0.0001},
            },
            "rows": [
                {
                    "instrument_name": "BTC-31JUL26-100000-C",
                    "iv_unit": "fraction",
                    "ticker": {
                        "instrument_name": "BTC-31JUL26-100000-C",
                        "mark_iv": 4.0,
                        "iv_unit": "percent_points",
                        "underlying_price": 100_000.0,
                    },
                }
            ],
        }
        self.assertIsNone(_rolling_observation_from_snapshot(snapshot))
        del snapshot["rows"][0]["iv_unit"]
        del snapshot["rows"][0]["ticker"]["iv_unit"]
        self.assertIsNone(_rolling_observation_from_snapshot(snapshot))

    def test_stored_rolling_observation_canonicalizes_declared_iv_unit(self):
        base = {
            "observed_at": "2026-07-14T00:00:00Z",
            "index_price": 100_000.0,
            "dvol": 0.5,
            "atm_iv": 4.0,
            "funding_rate": 0.0001,
            "source": "test",
        }

        self.assertEqual(
            0.04,
            _sanitize_rolling_observations(
                [{**base, "iv_unit": "percent_points"}]
            )[0]["atm_iv"],
        )
        self.assertEqual([], _sanitize_rolling_observations([base]))

    def test_quadratic_smile_and_btc_premium_units_produce_research_candidates(self):
        snapshot = self._btc_smile_snapshot()

        surface, candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at="2026-07-07T00:01:30Z",
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        self.assertEqual("quadratic_iv_vs_log_moneyness", surface["fit_model"])
        expiry = surface["expiries"][0]
        self.assertGreaterEqual(expiry["fit_quality_score"], 0.9)
        self.assertTrue(expiry["fit_quality_pass"])
        self.assertTrue(expiry["no_arb_pass"])
        self.assertEqual("validated", candidates["status"])

        research_candidates = (
            candidates["naked_short_calls"]["eligible"]
            + candidates["naked_short_calls"]["review"]
        )
        self.assertTrue(research_candidates)
        candidate = next(
            item for item in research_candidates if item["instrument_name"].endswith("120000-C")
        )
        self.assertEqual("BTC", candidate["premium_currency"])
        self.assertEqual("inverse_base_currency", candidate["premium_unit"])
        self.assertEqual(0.0005, candidate["applied_filter_thresholds"]["min_bid"])
        self.assertNotIn("recommended_size", candidate)
        self.assertNotIn("trade_instruction", candidate)

        spreads = (
            candidates["call_credit_spreads"]["eligible"]
            + candidates["call_credit_spreads"]["review"]
        )
        self.assertTrue(spreads)
        self.assertTrue(all(item["premium_currency"] == "BTC" for item in spreads))
        self.assertTrue(
            all(
                item["applied_filter_thresholds"]["min_net_credit"] == 0.0001
                for item in spreads
            )
        )

    def test_live_regime_without_rolling_history_is_explicitly_collecting(self):
        snapshot = self._btc_smile_snapshot()
        snapshot["feeds"].update(self._live_feeds())
        snapshot = self._bind_trust_evidence(snapshot, {
            "status": "collecting",
            "consecutive_passes": 3,
            "minimum_consecutive_passes": 6,
            "observation_seconds": 30,
            "minimum_observation_seconds": 60,
            "rolling": {"observations": []},
        })
        surface, _candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at="2026-07-07T00:01:30Z",
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        permission = build_regime_permission_state(
            market_snapshot=snapshot,
            data_status={"status": "validated"},
            vol_surface_status=surface,
        )

        self.assertEqual("blocked", permission["status"])
        self.assertEqual("collecting", permission["collection_status"])
        self.assertEqual(0.0, permission["sell_permission"])
        self.assertFalse(permission["naked_permission"])
        self.assertFalse(permission["spread_permission"])
        self.assertIn("REGIME_ROLLING_HISTORY_INSUFFICIENT", permission["reason_codes"])
        self.assertFalse(permission["input_provenance"]["synthetic_inputs"])
        self.assertEqual(100000.0, permission["current_measurements"]["index_price"])
        self.assertEqual(0.0001, permission["current_measurements"]["funding_rate"])
        self.assertEqual(0.47, permission["current_measurements"]["dvol"])

    def test_rolling_market_evidence_drives_regime_without_default_scores(self):
        snapshot = self._btc_smile_snapshot()
        snapshot["feeds"].update(self._live_feeds())
        snapshot = self._bind_trust_evidence(snapshot, {
            "status": "promoted",
            "consecutive_passes": 24,
            "minimum_consecutive_passes": 6,
            "observation_seconds": 300,
            "minimum_observation_seconds": 60,
            "rolling": {
                "observations": [
                    {
                        "observed_at": f"2026-07-06T{hour:02d}:00:00Z",
                        "index_price": 97000.0 + (hour * 125.0),
                        "dvol": 0.35 + (hour * 0.005),
                        "atm_iv": 0.35 + (hour * 0.002),
                        "iv_unit": "fraction",
                        "funding_rate": 0.00002 + (hour * 0.000002),
                        "basis_rate": 0.0003 + (hour * 0.00001),
                    }
                    for hour in range(20)
                ]
            },
        })
        surface, _candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at="2026-07-07T00:01:30Z",
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        permission = build_regime_permission_state(
            market_snapshot=snapshot,
            data_status={"status": "validated"},
            vol_surface_status=surface,
        )

        self.assertEqual("validated", permission["status"])
        self.assertEqual("ready", permission["collection_status"])
        self.assertEqual("rolling_evidence", permission["input_provenance"]["score_source"])
        self.assertEqual("rolling_evidence", permission["input_provenance"]["percentile_source"])
        self.assertEqual([], permission["input_provenance"]["defaults_applied"])
        self.assertFalse(permission["input_provenance"]["regime_inputs_present"])
        self.assertFalse(permission["input_provenance"]["synthetic_inputs"])
        self.assertEqual(20, permission["input_provenance"]["observation_count"])
        self.assertGreater(permission["regime_scores"]["slow_bull"], 0.0)
        self.assertGreater(permission["volatility_inputs"]["dvol_percentile"], 0.0)
        self.assertFalse(permission["paper_trading_allowed"])
        self.assertFalse(permission["manual_execution_allowed"])

    def test_unbound_rolling_evidence_cannot_promote_regime(self):
        snapshot = self._btc_smile_snapshot()
        snapshot["feeds"].update(self._live_feeds())
        snapshot["trust_evidence"] = {
            "status": "promoted",
            "rolling": {
                "observations": [
                    {
                        "index_price": 97_000.0 + (hour * 125.0),
                        "dvol": 0.35 + (hour * 0.005),
                        "atm_iv": 0.35 + (hour * 0.002),
                        "iv_unit": "fraction",
                        "funding_rate": 0.00002,
                        "basis_rate": 0.0003,
                    }
                    for hour in range(20)
                ]
            },
        }
        surface, _candidates = build_vol_surface_and_candidate_research(
            market_snapshot=snapshot,
            generated_at="2026-07-07T00:01:30Z",
            data_status={"status": "validated"},
            pnl_evidence={"status": "pass"},
        )

        permission = build_regime_permission_state(
            market_snapshot=snapshot,
            data_status={"status": "validated"},
            vol_surface_status=surface,
        )

        self.assertEqual("blocked", permission["status"])
        self.assertEqual("collecting", permission["collection_status"])
        self.assertEqual(0, permission["input_provenance"]["observation_count"])
        self.assertIn("REGIME_TRUST_EVIDENCE_NOT_PROMOTED", permission["reason_codes"])

    @staticmethod
    def _bind_trust_evidence(snapshot, evidence):
        evidence = {
            "schema_version": "market_trust_evidence.v1",
            "source_identity": f"{snapshot['source']}|{snapshot['currency']}",
            **evidence,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            key_dir = Path(temp_dir) / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            output = data_dir / "market-snapshot.json"
            auth_key = key_dir / "sidecar.key"
            auth_key.write_bytes(b"r" * 32)
            write_snapshot_fixture(output, snapshot)
            write_snapshot_trust_state(
                output,
                evidence,
                expected_snapshot=snapshot,
                auth_key_file=auth_key,
            )
            return load_snapshot_fixture(output, auth_key_file=auth_key)

    def _btc_smile_snapshot(self):
        path = Path(__file__).with_name("fixtures") / "deribit_btc_option_chain_snapshot.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["source"] = "deribit_live:https://www.deribit.com"
        mids = [0.1200, 0.0900, 0.0610, 0.0390, 0.0230, 0.0125, 0.0060, 0.0025]
        for row, mid in zip(snapshot["rows"], mids):
            summary = row["summary"]
            ticker = row["ticker"]
            strike = float(row["instrument_name"].split("-")[-2])
            x_value = log(strike / 100000.0)
            mark_iv = round(45.0 - (4.0 * x_value) + (80.0 * x_value * x_value), 6)
            bid = round(max(mid - 0.0002, 0.0001), 6)
            ask = round(mid + 0.0002, 6)
            summary.update(
                {
                    "quote_currency": "BTC",
                    "settlement_currency": "BTC",
                    "bid_price": bid,
                    "ask_price": ask,
                    "mid_price": mid,
                    "mark_price": mid,
                    "underlying_price": 100000.0,
                }
            )
            ticker.update(
                {
                    "iv_unit": "percent_points",
                    "best_bid_price": bid,
                    "best_ask_price": ask,
                    "mark_price": mid,
                    "bid_iv": mark_iv - 0.4,
                    "ask_iv": mark_iv + 0.4,
                    "mark_iv": mark_iv,
                    "underlying_price": 100000.0,
                }
            )
            ticker.pop("greeks", None)
        return deepcopy(snapshot)

    @staticmethod
    def _live_feeds():
        return {
            "vol_index": {
                "index_name": "BTC DVOL",
                "currency": "BTC",
                "timestamp": "2026-07-07T00:01:00Z",
                "volatility": 0.47,
            },
            "index_spot": {
                "index_name": "btc_usd",
                "index_price": 100000.0,
                "observed_at": "2026-07-07T00:01:00Z",
            },
            "funding_basis": {
                "instrument_name": "BTC-PERPETUAL",
                "funding_rate": 0.0001,
                "basis_rate": 0.001,
                "index_price": 100000.0,
                "mark_price": 100100.0,
                "observed_at": "2026-07-07T00:01:00Z",
            },
            "events": {
                "observed_at": "2026-07-07T00:01:00Z",
                "exchange_locked": False,
                "locked_currencies": [],
                "locked_indices": [],
                "macro_events": [],
                "macro_events_status": "collected",
                "scope": "exchange_native_only",
            },
        }


if __name__ == "__main__":
    unittest.main()
