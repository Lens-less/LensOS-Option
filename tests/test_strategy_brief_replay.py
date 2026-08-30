import unittest
from datetime import UTC, date, datetime, timedelta

from crypto_options_report.strategy_history import build_strategy_history_protocol
from crypto_options_report.strategy_replay import (
    ENTRY_COST_BASIS,
    build_strategy_replay_ledger,
    build_strategy_replay_observation,
)


def _protocol(structure_type: str) -> dict:
    return build_strategy_history_protocol(
        structure_type=structure_type,
        frozen_at="2026-08-30T12:00:00Z",
    )


def _settlement(expiry_date: str, price: float, *, proxy: bool = False) -> dict:
    return {
        "expiry_date": expiry_date,
        "settlement_price": price,
        "settlement_currency": "USDC",
        "settlement_at": f"{expiry_date}T08:00:00Z",
        "published_at": f"{expiry_date}T08:00:30Z",
        "basis": "official_expiry_settlement",
        "is_price_proxy": proxy,
        "source": "deribit_official_settlement",
        "source_hash": f"source:{expiry_date}:{price}",
        "receipt_hash": f"receipt:{expiry_date}:{price}",
    }


def _leg(
    instrument_name: str,
    *,
    option_type: str,
    strike: float,
    quantity: float,
    bid: float,
    ask: float,
    observed_at: str,
    expiry_date: str = "2026-09-25",
    tick_size: float = 10.0,
    premium_unit: str = "quote_currency",
    quote_currency: str = "USDC",
    settlement_currency: str = "USDC",
    underlying_price: float = 120_000.0,
) -> dict:
    return {
        "instrument_name": instrument_name,
        "option_type": option_type,
        "strike": strike,
        "quantity": quantity,
        "bid": bid,
        "ask": ask,
        "tick_size": tick_size,
        "observed_at": observed_at,
        "expiry_date": expiry_date,
        "premium_unit": premium_unit,
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "contract_size": 1.0,
        "underlying_price": underlying_price,
    }


def _bear_call_legs(*, observed_offset_seconds: int = 0) -> list[dict]:
    expiry = "2026-09-25"
    return [
        _leg(
            "BTC-25SEP26-128000-C",
            option_type="call",
            strike=128_000.0,
            quantity=-1.0,
            bid=1_200.0,
            ask=1_250.0,
            observed_at=f"2026-08-30T12:00:{1 + observed_offset_seconds:02d}Z",
            expiry_date=expiry,
        ),
        _leg(
            "BTC-25SEP26-132000-C",
            option_type="call",
            strike=132_000.0,
            quantity=1.0,
            bid=700.0,
            ask=800.0,
            observed_at=f"2026-08-30T12:00:{2 + observed_offset_seconds:02d}Z",
            expiry_date=expiry,
        ),
    ]


def _bull_put_legs() -> list[dict]:
    expiry = "2026-09-25"
    return [
        _leg(
            "BTC-25SEP26-112000-P",
            option_type="put",
            strike=112_000.0,
            quantity=-1.0,
            bid=1_100.0,
            ask=1_160.0,
            observed_at="2026-08-30T12:00:01Z",
            expiry_date=expiry,
        ),
        _leg(
            "BTC-25SEP26-108000-P",
            option_type="put",
            strike=108_000.0,
            quantity=1.0,
            bid=620.0,
            ask=690.0,
            observed_at="2026-08-30T12:00:02Z",
            expiry_date=expiry,
        ),
    ]


def _condor_legs() -> list[dict]:
    expiry = "2026-09-25"
    return [
        _leg(
            "BTC-25SEP26-110000-P",
            option_type="put",
            strike=110_000.0,
            quantity=-1.0,
            bid=900.0,
            ask=960.0,
            observed_at="2026-08-30T12:00:01Z",
            expiry_date=expiry,
        ),
        _leg(
            "BTC-25SEP26-105000-P",
            option_type="put",
            strike=105_000.0,
            quantity=1.0,
            bid=520.0,
            ask=570.0,
            observed_at="2026-08-30T12:00:02Z",
            expiry_date=expiry,
        ),
        _leg(
            "BTC-25SEP26-130000-C",
            option_type="call",
            strike=130_000.0,
            quantity=-1.0,
            bid=980.0,
            ask=1_040.0,
            observed_at="2026-08-30T12:00:01Z",
            expiry_date=expiry,
        ),
        _leg(
            "BTC-25SEP26-135000-C",
            option_type="call",
            strike=135_000.0,
            quantity=1.0,
            bid=610.0,
            ask=680.0,
            observed_at="2026-08-30T12:00:02Z",
            expiry_date=expiry,
        ),
    ]


class StrategyBriefReplayTests(unittest.TestCase):
    def test_bear_call_replay_is_deterministic_and_defined_risk(self):
        record = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 130_000.0),
            regimes={
                "volatility": "high_vol",
                "trend": "range",
                "liquidity": "tight",
            },
            selection_slot="slot-1",
            fold_id="fold-a",
        )

        self.assertEqual("BEAR_CALL_CREDIT_SPREAD", record["structure_type"])
        self.assertEqual("bearish", record["direction"])
        self.assertEqual(380.0, record["entry_credit"])
        self.assertGreater(record["entry_fee"], 0.0)
        self.assertGreater(record["max_loss"], 0.0)
        self.assertAlmostEqual(
            record["net_pnl"] / record["max_loss"],
            record["net_r"],
            places=8,
        )
        self.assertEqual(ENTRY_COST_BASIS, record["scope"]["entry_cost_basis"])
        self.assertEqual(record["result_hash"], build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 130_000.0),
            regimes={
                "volatility": "high_vol",
                "trend": "range",
                "liquidity": "tight",
            },
            selection_slot="slot-1",
            fold_id="fold-a",
        )["result_hash"])

    def test_bull_put_replay_uses_downside_defined_loss(self):
        record = build_strategy_replay_observation(
            structure_type="BULL_PUT_CREDIT_SPREAD",
            protocol=_protocol("BULL_PUT_CREDIT_SPREAD"),
            legs=_bull_put_legs(),
            settlement=_settlement("2026-09-25", 109_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )

        self.assertEqual("BULL_PUT_CREDIT_SPREAD", record["structure_type"])
        self.assertEqual("bullish", record["direction"])
        self.assertGreaterEqual(record["terminal_payoff"], 0.0)
        self.assertTrue(record["defined_loss"])
        self.assertTrue(record["unit_known"])

    def test_iron_condor_replay_handles_four_legs(self):
        record = build_strategy_replay_observation(
            structure_type="IRON_CONDOR",
            protocol=_protocol("IRON_CONDOR"),
            legs=_condor_legs(),
            settlement=_settlement("2026-09-25", 120_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )

        self.assertEqual("IRON_CONDOR", record["structure_type"])
        self.assertEqual("neutral", record["direction"])
        self.assertEqual(4, len(record["legs"]))
        self.assertEqual(0.0, record["terminal_payoff"])

    def test_ledger_clusters_by_expiry_and_rejects_overlap(self):
        first = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 129_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )
        ledger = build_strategy_replay_ledger(
            records=[first],
            sample_role="development",
            source_classification="development_inventory",
        )

        self.assertEqual(1, len(ledger["entries"]))
        self.assertEqual("development", ledger["sample_role"])
        self.assertEqual("development_inventory", ledger["source_classification"])
        self.assertEqual([first["result_hash"]], ledger["entries"][0]["record_hashes"])
        self.assertEqual(1, ledger["entries"][0]["observation_count"])

        overlapping = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(observed_offset_seconds=3),
            settlement=_settlement("2026-09-25", 128_500.0),
            selection_slot="slot-2",
            fold_id="fold-a",
        )
        ledger = build_strategy_replay_ledger(
            records=[first, overlapping],
            sample_role="development",
            source_classification="development_inventory",
        )
        self.assertEqual(2, ledger["entries"][0]["observation_count"])

        leaked = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(observed_offset_seconds=4),
            settlement=_settlement("2026-09-25", 128_000.0),
            selection_slot="slot-3",
            fold_id="fold-b",
            label_window_id=first["label_window_id"],
        )
        with self.assertRaisesRegex(ValueError, "cross-fold label leakage"):
            build_strategy_replay_ledger(
                records=[first, leaked],
                sample_role="development",
                source_classification="development_inventory",
            )

    def test_ledger_can_hold_100_observations_across_8_independent_cohorts(self):
        records: list[dict] = []
        expiry = date(2026, 9, 25)
        for cohort_index in range(8):
            expiry_date = (expiry + timedelta(days=14 * cohort_index)).isoformat()
            base_observed = datetime.fromisoformat(f"{expiry_date}T08:00:00+00:00") - timedelta(
                days=20
            )
            for slot_index in range(13):
                observed_at = (
                    base_observed + timedelta(hours=slot_index % 12, minutes=slot_index)
                ).astimezone(UTC).isoformat().replace("+00:00", "Z")
                legs = _bear_call_legs()
                for leg in legs:
                    leg["expiry_date"] = expiry_date
                    leg["observed_at"] = observed_at
                records.append(
                    build_strategy_replay_observation(
                        structure_type="BEAR_CALL_CREDIT_SPREAD",
                        protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
                        legs=legs,
                        settlement=_settlement(expiry_date, 129_000.0 + cohort_index),
                        selection_slot=f"slot-{cohort_index}-{slot_index}",
                        fold_id="fold-a",
                        label_window_id=f"window-{cohort_index}",
                    )
                )
        ledger = build_strategy_replay_ledger(
            records=records,
            sample_role="development",
            source_classification="development_inventory",
        )

        self.assertEqual(8, len(ledger["entries"]))
        self.assertEqual(104, sum(entry["observation_count"] for entry in ledger["entries"]))

    def test_same_selection_slot_is_rejected_within_one_cohort(self):
        first = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 129_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )
        second = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(observed_offset_seconds=4),
            settlement=_settlement("2026-09-25", 128_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
            label_window_id="window-2",
        )

        with self.assertRaisesRegex(ValueError, "duplicate selection slot"):
            build_strategy_replay_ledger(
                records=[first, second],
                sample_role="development",
                source_classification="development_inventory",
            )

    def test_duplicate_observation_is_rejected(self):
        record = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 129_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )

        with self.assertRaisesRegex(ValueError, "duplicate replay observation"):
            build_strategy_replay_ledger(
                records=[record, record],
                sample_role="development",
                source_classification="development_inventory",
            )

    def test_proxy_settlement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "proxy settlement is forbidden"):
            build_strategy_replay_observation(
                structure_type="BEAR_CALL_CREDIT_SPREAD",
                protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
                legs=_bear_call_legs(),
                settlement=_settlement("2026-09-25", 129_000.0, proxy=True),
                selection_slot="slot-1",
                fold_id="fold-a",
            )

    def test_unit_mismatch_is_rejected(self):
        legs = _bear_call_legs()
        legs[0]["premium_unit"] = "inverse_base_currency"
        with self.assertRaisesRegex(ValueError, "only quote_currency linear premiums"):
            build_strategy_replay_observation(
                structure_type="BEAR_CALL_CREDIT_SPREAD",
                protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
                legs=legs,
                settlement=_settlement("2026-09-25", 129_000.0),
                selection_slot="slot-1",
                fold_id="fold-a",
            )

    def test_lookahead_and_unsynced_legs_are_rejected(self):
        late_settlement = _settlement("2026-09-25", 129_000.0)
        late_settlement["settlement_at"] = "2026-08-30T12:00:02Z"
        with self.assertRaisesRegex(ValueError, "settlement must occur after"):
            build_strategy_replay_observation(
                structure_type="BEAR_CALL_CREDIT_SPREAD",
                protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
                legs=_bear_call_legs(),
                settlement=late_settlement,
                selection_slot="slot-1",
                fold_id="fold-a",
            )

        unsynced = _bear_call_legs()
        unsynced[1]["observed_at"] = "2026-08-30T12:00:10Z"
        with self.assertRaisesRegex(ValueError, "observed within 2 seconds"):
            build_strategy_replay_observation(
                structure_type="BEAR_CALL_CREDIT_SPREAD",
                protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
                legs=unsynced,
                settlement=_settlement("2026-09-25", 129_000.0),
                selection_slot="slot-1",
                fold_id="fold-a",
            )

    def test_dual_itm_delivery_fees_are_charged_per_leg_not_net_payoff(self):
        spread = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 140_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )
        condor = build_strategy_replay_observation(
            structure_type="IRON_CONDOR",
            protocol=_protocol("IRON_CONDOR"),
            legs=_condor_legs(),
            settlement=_settlement("2026-09-25", 140_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )

        self.assertEqual(42.0, spread["delivery_fee"])
        self.assertEqual(42.0, condor["delivery_fee"])

    def test_tampered_record_is_rejected_by_the_ledger(self):
        record = build_strategy_replay_observation(
            structure_type="BEAR_CALL_CREDIT_SPREAD",
            protocol=_protocol("BEAR_CALL_CREDIT_SPREAD"),
            legs=_bear_call_legs(),
            settlement=_settlement("2026-09-25", 129_000.0),
            selection_slot="slot-1",
            fold_id="fold-a",
        )
        record["net_pnl"] = 999.0

        with self.assertRaisesRegex(ValueError, "caller-mutated replay record hash mismatch"):
            build_strategy_replay_ledger(
                records=[record],
                sample_role="development",
                source_classification="development_inventory",
            )


if __name__ == "__main__":
    unittest.main()
