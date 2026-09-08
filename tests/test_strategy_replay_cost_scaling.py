"""Regression checks for linear expiry fees and replay risk units."""

import unittest
from copy import deepcopy

from crypto_options_report.strategy_history import build_strategy_history_protocol
from crypto_options_report.strategy_replay import (
    MAX_LOSS_BASIS,
    _delivery_fee_for_leg,
    _record_hash,
    build_strategy_replay_ledger,
    build_strategy_replay_observation,
)


def _observation(*, structure_type="BEAR_CALL_CREDIT_SPREAD", contract_size=1.0, spot=100.01):
    definitions = {
        "BEAR_CALL_CREDIT_SPREAD": [("call", 100.0, -1.0), ("call", 110.0, 1.0)],
        "BULL_PUT_CREDIT_SPREAD": [("put", 100.0, -1.0), ("put", 90.0, 1.0)],
        "IRON_CONDOR": [
            ("put", 90.0, -1.0), ("put", 80.0, 1.0),
            ("call", 110.0, -1.0), ("call", 120.0, 1.0),
        ],
    }
    legs = [
        {
            "instrument_name": f"TEST-25SEP26-{strike}-{option_type}",
            "option_type": option_type,
            "strike": strike,
            "quantity": quantity,
            "bid": 2.0 if quantity < 0 else 0.9,
            "ask": 2.2 if quantity < 0 else 1.0,
            "tick_size": 0.01,
            "observed_at": "2026-08-30T12:00:00Z",
            "expiry_date": "2026-09-25",
            "premium_unit": "quote_currency",
            "quote_currency": "USDC",
            "settlement_currency": "USDC",
            "contract_size": contract_size,
            "underlying_price": 100.0,
        }
        for option_type, strike, quantity in definitions[structure_type]
    ]
    return build_strategy_replay_observation(
        structure_type=structure_type,
        protocol=build_strategy_history_protocol(
            structure_type=structure_type,
            frozen_at="2026-08-30T12:00:00Z",
        ),
        legs=legs,
        settlement={
            "expiry_date": "2026-09-25",
            "settlement_price": spot,
            "settlement_currency": "USDC",
            "settlement_at": "2026-09-25T08:00:00Z",
            "published_at": "2026-09-25T08:00:30Z",
            "basis": "official_expiry_settlement",
            "source": "deribit_official_settlement",
            "source_hash": "test-source",
            "receipt_hash": "test-receipt",
        },
        selection_slot="test-slot",
        fold_id="test-fold",
    )


class StrategyReplayDeliveryFeeScalingTests(unittest.TestCase):
    def test_near_strike_option_value_cap_scales_with_contract_size(self):
        # At S=100.01 a call struck at 100 is worth 0.01 per underlying
        # unit. Its 12.5% fee cap is therefore 0.00125 * contract_size.
        for contract_size in (0.1, 1.0, 10.0):
            for option_type, strike in (("call", 100.0), ("put", 100.02)):
                with self.subTest(contract_size=contract_size, option_type=option_type):
                    fee = _delivery_fee_for_leg(
                        leg={
                            "option_type": option_type,
                            "strike": strike,
                            "quantity": -1.0,
                            "contract_size": contract_size,
                        },
                        settlement_price=100.01,
                    )
                    self.assertAlmostEqual(0.00125 * contract_size, fee, places=10)

    def test_deep_itm_notional_fee_scales_with_quantity_and_contract_size(self):
        for quantity in (-3.0, 3.0):
            with self.subTest(quantity=quantity):
                fee = _delivery_fee_for_leg(
                    leg={
                        "option_type": "call",
                        "strike": 100.0,
                        "quantity": quantity,
                        "contract_size": 10.0,
                    },
                    settlement_price=120.0,
                )
                self.assertAlmostEqual(0.00015 * 120.0 * 3.0 * 10.0, fee)

    def test_otm_and_at_the_money_options_have_no_delivery_fee(self):
        for option_type, settlement_price in (("call", 99.0), ("put", 101.0), ("call", 100.0)):
            with self.subTest(option_type=option_type, settlement_price=settlement_price):
                fee = _delivery_fee_for_leg(
                    leg={
                        "option_type": option_type,
                        "strike": 100.0,
                        "quantity": -1.0,
                        "contract_size": 10.0,
                    },
                    settlement_price=settlement_price,
                )
                self.assertEqual(0.0, fee)


class StrategyReplayRiskDenominatorTests(unittest.TestCase):
    def test_all_cash_values_scale_with_contract_size_and_net_r_does_not(self):
        for structure_type, spot in (
            ("BEAR_CALL_CREDIT_SPREAD", 100.01),
            ("BULL_PUT_CREDIT_SPREAD", 99.99),
            ("IRON_CONDOR", 110.01),
        ):
            reference = _observation(structure_type=structure_type, spot=spot)
            for contract_size in (0.01, 0.1, 10.0):
                with self.subTest(structure_type=structure_type, contract_size=contract_size):
                    scaled = _observation(
                        structure_type=structure_type, contract_size=contract_size, spot=spot,
                    )
                    for field in ("entry_credit", "entry_fee", "terminal_payoff", "delivery_fee", "net_pnl", "max_loss"):
                        self.assertAlmostEqual(reference[field] * contract_size, scaled[field], places=8)
                    self.assertEqual(reference["net_r"], scaled["net_r"])

    def test_risk_budget_includes_entry_fees_and_excludes_spot_dependent_delivery_fees(self):
        record = _observation()
        # Width=10, credit=(2-.01)-(1+.01)=.98, entry fees=.03*2=.06.
        self.assertAlmostEqual(9.08, record["max_loss"])
        self.assertEqual(MAX_LOSS_BASIS, record["max_loss_basis"])
        self.assertEqual(MAX_LOSS_BASIS, record["scope"]["max_loss_basis"])
        self.assertIs(False, record["delivery_fee_in_risk_denominator"])
        self.assertIs(False, record["scope"]["delivery_fee_in_risk_denominator"])
        self.assertIs(False, record["fee_inclusive_loss_is_bounded"])
        self.assertIs(True, record["defined_loss"])

    def test_call_delivery_costs_can_exceed_entry_time_risk_budget(self):
        near = _observation(spot=110.0)
        far = _observation(spot=1_000_000.0)
        self.assertEqual(near["max_loss"], far["max_loss"])
        self.assertAlmostEqual(300.0, far["delivery_fee"])
        self.assertAlmostEqual(-309.08, far["net_pnl"])
        self.assertLess(far["net_pnl"], near["net_pnl"])
        self.assertLess(near["net_r"], -1.0)
        self.assertLess(far["net_r"], near["net_r"])

    def test_put_only_costs_are_bounded_but_are_not_in_the_risk_denominator(self):
        record = _observation(structure_type="BULL_PUT_CREDIT_SPREAD", spot=89.0)
        self.assertIs(True, record["fee_inclusive_loss_is_bounded"])
        self.assertIs(False, record["delivery_fee_in_risk_denominator"])
        self.assertAlmostEqual(9.08, record["max_loss"])
        self.assertLess(record["net_r"], -1.0)

    def test_ledger_preserves_risk_basis_and_rejects_legacy_or_false_boundaries(self):
        record = _observation()
        ledger = build_strategy_replay_ledger(
            records=[record], sample_role="development", source_classification="development_inventory",
        )
        self.assertEqual(MAX_LOSS_BASIS, ledger["scope"]["max_loss_basis"])
        for field, value in (
            ("max_loss_basis", None),
            ("delivery_fee_in_risk_denominator", True),
            ("fee_inclusive_loss_is_bounded", True),
        ):
            with self.subTest(field=field):
                invalid = deepcopy(record)
                invalid[field] = value
                invalid["result_hash"] = _record_hash(invalid)
                invalid["replay_id"] = f"strategy-replay:{invalid['result_hash']}"
                with self.assertRaisesRegex(ValueError, "risk denominator basis|loss boundary"):
                    build_strategy_replay_ledger(
                        records=[invalid], sample_role="development", source_classification="development_inventory",
                    )
