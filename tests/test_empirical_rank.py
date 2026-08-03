from __future__ import annotations

import unittest

from crypto_options_report.empirical_rank import (
    empirical_percentile,
    vrp_band_for_percentile,
)


class EmpiricalPercentileTests(unittest.TestCase):
    def test_rank_uses_one_shared_less_or_equal_definition(self):
        self.assertEqual(
            0.75,
            empirical_percentile(current=2.0, history=[1.0, 2.0, 2.0, 3.0]),
        )

    def test_empty_history_is_undefined_and_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            empirical_percentile(current=1.0, history=[])

    def test_non_finite_values_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            empirical_percentile(current=float("nan"), history=[1.0])

    def test_vrp_band_boundaries_have_one_canonical_definition(self):
        cases = (
            (0.9, "extremely_expensive"),
            (0.8999, "expensive"),
            (0.7, "expensive"),
            (0.6999, "neutral"),
            (0.3001, "neutral"),
            (0.3, "thin"),
            (0.1001, "thin"),
            (0.1, "extremely_thin"),
        )
        for percentile, expected in cases:
            with self.subTest(percentile=percentile):
                self.assertEqual(expected, vrp_band_for_percentile(percentile))


if __name__ == "__main__":
    unittest.main()
