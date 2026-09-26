import unittest

from gold_trader.indicators import (
    atr, build_features, donchian, ema, ema_series, rsi, sma, structure, trend_state,
)
from tests_gold.helpers import candles, ramp, series, snapshot_from


class MovingAverages(unittest.TestCase):
    def test_ema_of_a_flat_series_is_that_value(self):
        self.assertAlmostEqual(ema([100.0] * 30, 20), 100.0, places=9)

    def test_ema_needs_at_least_period_values(self):
        self.assertIsNone(ema([1.0, 2.0], 20))
        self.assertEqual(ema_series([1.0, 2.0], 20), [])

    def test_ema_is_seeded_with_the_sma(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(ema_series(values, 4)[0], 2.5)

    def test_ema_tracks_a_rising_series_below_spot(self):
        values = ramp(100.0, 60, 1.0)
        self.assertLess(ema(values, 20), values[-1])

    def test_sma_returns_none_when_short(self):
        self.assertIsNone(sma([1.0], 5))
        self.assertAlmostEqual(sma([1.0, 2.0, 3.0], 3), 2.0)

    def test_period_must_be_positive(self):
        with self.assertRaises(ValueError):
            ema([1.0], 0)


class Oscillators(unittest.TestCase):
    def test_rsi_of_a_monotonic_rise_is_100(self):
        self.assertAlmostEqual(rsi(ramp(100.0, 40, 1.0), 14), 100.0, places=6)

    def test_rsi_of_a_monotonic_fall_is_0(self):
        self.assertAlmostEqual(rsi(ramp(200.0, 40, -1.0), 14), 0.0, places=6)

    def test_rsi_of_an_alternating_series_sits_mid_range(self):
        values = [100.0 + (1.0 if i % 2 else 0.0) for i in range(40)]
        self.assertTrue(40.0 < rsi(values, 14) < 60.0)

    def test_rsi_needs_period_plus_one(self):
        self.assertIsNone(rsi([1.0] * 14, 14))


class Volatility(unittest.TestCase):
    def test_atr_of_constant_range_candles_equals_that_range(self):
        # Flat closes with a fixed spread give every bar the same true range.
        bars = candles([100.0] * 30, spread=3.0)
        self.assertAlmostEqual(atr(bars, 14), 6.0, places=6)

    def test_atr_is_none_when_there_are_too_few_bars(self):
        self.assertIsNone(atr(candles([100.0] * 5), 14))

    def test_atr_rises_with_volatility(self):
        calm = atr(candles([100.0] * 40, spread=1.0), 14)
        wild = atr(candles([100.0] * 40, spread=10.0), 14)
        self.assertGreater(wild, calm)


class Structure(unittest.TestCase):
    def test_donchian_brackets_the_window(self):
        band = donchian(candles(ramp(100.0, 30, 1.0)), 20)
        self.assertGreater(band["upper"], band["lower"])
        self.assertAlmostEqual(band["mid"], (band["upper"] + band["lower"]) / 2)

    def test_donchian_is_none_when_short(self):
        self.assertIsNone(donchian(candles([100.0] * 5), 20))

    def test_trend_state_reads_a_sustained_rise_as_bullish(self):
        self.assertEqual(trend_state(ramp(100.0, 120, 1.0)), "bullish")

    def test_trend_state_reads_a_sustained_fall_as_bearish(self):
        self.assertEqual(trend_state(ramp(2000.0, 120, -1.0)), "bearish")

    def test_trend_state_is_indeterminate_without_enough_history(self):
        self.assertEqual(trend_state([100.0, 101.0]), "indeterminate")

    def test_structure_is_indeterminate_without_swings(self):
        self.assertEqual(structure(candles([100.0] * 10)), "indeterminate")


class Features(unittest.TestCase):
    def test_feature_set_reports_alignment_across_timeframes(self):
        snap = snapshot_from(ramp(2000.0, 120, 1.0), timeframes=("h1", "m15"))
        features = build_features(snap)
        self.assertEqual(features.alignment(), "aligned_bullish")
        self.assertIn("h1", features.per_timeframe)

    def test_prompt_block_names_every_timeframe(self):
        features = build_features(snapshot_from(ramp(2000.0, 120, 1.0)))
        block = features.as_prompt_block()
        self.assertIn("[H1", block)
        self.assertIn("[M15", block)
        self.assertIn("ATR14", block)

    def test_short_series_are_dropped_rather_than_half_computed(self):
        snap = snapshot_from([2000.0], timeframes=("h1",))
        self.assertEqual(build_features(snap).per_timeframe, {})


if __name__ == "__main__":
    unittest.main()
