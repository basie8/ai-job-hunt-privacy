import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.feed import Candle
from gold_trader.smc import (
    fair_value_gaps, find_swings, liquidity_sweeps, order_blocks, read_structure, structure_events,
)

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def ohlc(rows, step_min=60):
    """Candles from explicit (open, high, low, close) tuples."""
    return [
        Candle(START + timedelta(minutes=step_min * i), o, h, l, c)
        for i, (o, h, l, c) in enumerate(rows)
    ]


def flat(price, n, spread=1.0):
    return [(price, price + spread, price - spread, price)] * n


class Swings(unittest.TestCase):
    def test_a_clear_peak_is_found(self):
        candles = ohlc([
            (100, 101, 99, 100), (101, 102, 100, 101), (102, 108, 101, 107),
            (107, 107, 105, 106), (106, 106, 104, 105),
        ])
        highs = [s for s in find_swings(candles, lookback=2) if s.kind == "high"]
        self.assertEqual(len(highs), 1)
        self.assertAlmostEqual(highs[0].price, 108)

    def test_a_clear_trough_is_found(self):
        candles = ohlc([
            (108, 109, 107, 108), (107, 108, 106, 107), (106, 107, 100, 101),
            (101, 103, 101, 102), (102, 104, 102, 103),
        ])
        lows = [s for s in find_swings(candles, lookback=2) if s.kind == "low"]
        self.assertEqual(len(lows), 1)
        self.assertAlmostEqual(lows[0].price, 100)

    def test_a_flat_series_has_no_swings(self):
        self.assertEqual(find_swings(ohlc(flat(100, 20)), lookback=2), [])

    def test_swings_carry_their_index_and_timestamp(self):
        candles = ohlc([
            (100, 101, 99, 100), (101, 102, 100, 101), (102, 108, 101, 107),
            (107, 107, 105, 106), (106, 106, 104, 105),
        ])
        swing = find_swings(candles, lookback=2)[0]
        self.assertEqual(swing.index, 2)
        self.assertEqual(swing.ts, candles[2].ts)


class Structure(unittest.TestCase):
    def _up_then_down(self):
        # Rally, pull back, break the high (BOS), then break the low (CHoCH).
        return ohlc([
            (100, 101, 99, 100),
            (100, 102, 100, 101),
            (101, 110, 101, 109),   # swing high 110
            (109, 109, 107, 108),
            (108, 108, 100, 101),   # swing low 100
            (101, 103, 101, 102),
            (102, 104, 102, 103),
            (103, 112, 103, 111),   # closes above 110 -> bullish BOS
            (111, 111, 109, 110),
            (110, 110, 108, 109),
            (109, 110, 96, 97),     # closes below 100 -> bearish CHoCH
        ])

    def test_a_break_with_the_bias_is_a_bos(self):
        events = structure_events(self._up_then_down(), lookback=2)
        self.assertTrue(events)
        self.assertEqual(events[0].kind, "BOS")
        self.assertEqual(events[0].direction, "bullish")
        self.assertAlmostEqual(events[0].broken_level, 110)

    def test_the_first_break_against_the_bias_is_a_choch(self):
        events = structure_events(self._up_then_down(), lookback=2)
        chochs = [e for e in events if e.kind == "CHoCH"]
        self.assertTrue(chochs)
        self.assertEqual(chochs[0].direction, "bearish")

    def test_a_wick_through_a_level_is_not_a_break(self):
        # Structure is defined on the close, so a wick alone must not register.
        candles = ohlc([
            (100, 101, 99, 100), (100, 102, 100, 101), (101, 110, 101, 109),
            (109, 109, 107, 108), (108, 108, 106, 107),
            (107, 115, 107, 108),   # wicks above 110 but closes at 108
        ])
        self.assertEqual([e for e in structure_events(candles, 2) if e.direction == "bullish"], [])

    def test_a_flat_series_produces_no_events(self):
        self.assertEqual(structure_events(ohlc(flat(100, 30)), 2), [])


class FairValueGaps(unittest.TestCase):
    def test_a_bullish_imbalance_is_detected(self):
        # Candle 1 high 101, candle 3 low 105 -> untouched 101-105.
        candles = ohlc([(100, 101, 99, 100), (101, 106, 101, 105), (105, 108, 105, 107)])
        gaps = fair_value_gaps(candles)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].direction, "bullish")
        self.assertAlmostEqual(gaps[0].bottom, 101)
        self.assertAlmostEqual(gaps[0].top, 105)

    def test_a_bearish_imbalance_is_detected(self):
        candles = ohlc([(108, 109, 107, 108), (105, 107, 102, 103), (102, 103, 100, 101)])
        gaps = fair_value_gaps(candles)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].direction, "bearish")
        self.assertAlmostEqual(gaps[0].top, 107)
        self.assertAlmostEqual(gaps[0].bottom, 103)

    def test_overlapping_candles_are_not_a_gap(self):
        self.assertEqual(fair_value_gaps(ohlc(flat(100, 10))), [])

    def test_a_gap_price_returns_into_is_marked_mitigated(self):
        candles = ohlc([
            (100, 101, 99, 100), (101, 106, 101, 105), (105, 108, 105, 107),
            (107, 107, 103, 104),   # trades back into 101-105
        ])
        self.assertTrue(fair_value_gaps(candles)[0].mitigated)

    def test_an_untouched_gap_stays_unmitigated(self):
        candles = ohlc([
            (100, 101, 99, 100), (101, 106, 101, 105), (105, 108, 105, 107),
            (107, 110, 106, 109),
        ])
        self.assertFalse(fair_value_gaps(candles)[0].mitigated)

    def test_min_height_filters_noise(self):
        candles = ohlc([(100, 101, 99, 100), (101, 106, 101, 105), (105, 108, 101.5, 107)])
        self.assertEqual(fair_value_gaps(candles, min_height=5.0), [])


class OrderBlocks(unittest.TestCase):
    def test_the_last_down_candle_before_a_bullish_break_is_the_block(self):
        candles = ohlc([
            (100, 101, 99, 100), (100, 102, 100, 101), (101, 110, 101, 109),
            (109, 109, 107, 108),
            (108, 108, 104, 105),   # down candle, the order block
            (105, 112, 105, 111),   # breaks 110
        ])
        blocks = [z for z in order_blocks(candles, 2) if z.direction == "bullish"]
        self.assertTrue(blocks)
        self.assertAlmostEqual(blocks[0].top, 108)
        self.assertAlmostEqual(blocks[0].bottom, 104)

    def test_zone_geometry_is_consistent(self):
        candles = ohlc([
            (100, 101, 99, 100), (100, 102, 100, 101), (101, 110, 101, 109),
            (109, 109, 107, 108), (108, 108, 104, 105), (105, 112, 105, 111),
        ])
        zone = order_blocks(candles, 2)[0]
        self.assertGreater(zone.height, 0)
        self.assertAlmostEqual(zone.mid, (zone.top + zone.bottom) / 2)
        self.assertTrue(zone.contains(zone.mid))
        self.assertEqual(zone.distance_from(zone.mid), 0.0)
        self.assertGreater(zone.distance_from(zone.top + 5), 0)


class LiquiditySweeps(unittest.TestCase):
    def test_a_wick_below_a_swing_low_that_closes_back_above_is_a_sweep(self):
        candles = ohlc([
            (108, 109, 107, 108), (107, 108, 106, 107), (106, 107, 100, 101),  # swing low 100
            (101, 103, 101, 102), (102, 104, 102, 103),
            (103, 104, 97, 103),    # takes 100, closes back above
        ])
        sweeps = [s for s in liquidity_sweeps(candles, 2) if s.direction == "bullish"]
        self.assertTrue(sweeps)
        self.assertAlmostEqual(sweeps[0].swept_level, 100)
        self.assertAlmostEqual(sweeps[0].penetration, 3.0)

    def test_a_close_beyond_the_level_is_acceptance_not_a_sweep(self):
        candles = ohlc([
            (108, 109, 107, 108), (107, 108, 106, 107), (106, 107, 100, 101),
            (101, 103, 101, 102), (102, 104, 102, 103),
            (103, 104, 97, 98),     # closes below 100 -> accepted, not swept
        ])
        self.assertEqual([s for s in liquidity_sweeps(candles, 2) if s.direction == "bullish"], [])

    def test_min_penetration_filters_marginal_taps(self):
        candles = ohlc([
            (108, 109, 107, 108), (107, 108, 106, 107), (106, 107, 100, 101),
            (101, 103, 101, 102), (102, 104, 102, 103),
            (103, 104, 99.9, 103),
        ])
        self.assertEqual(liquidity_sweeps(candles, 2, min_penetration=1.0), [])


class Integration(unittest.TestCase):
    def test_read_structure_summarises_everything(self):
        candles = ohlc([
            (100, 101, 99, 100), (100, 102, 100, 101), (101, 110, 101, 109),
            (109, 109, 107, 108), (108, 108, 100, 101), (101, 103, 101, 102),
            (102, 104, 102, 103), (103, 112, 103, 111), (111, 111, 109, 110),
            (110, 110, 108, 109), (109, 110, 96, 97),
        ])
        read = read_structure(candles, "h1", lookback=2)
        self.assertIn(read.bias, ("bullish", "bearish"))
        self.assertIsNotNone(read.last_event)
        lines = read.as_prompt_lines(price=105.0)
        self.assertTrue(any("SMC bias" in line for line in lines))
        self.assertIn("timeframe", read.to_dict())

    def test_too_few_candles_returns_an_unknown_read_rather_than_failing(self):
        read = read_structure(ohlc(flat(100, 3)), "h1")
        self.assertEqual(read.bias, "unknown")
        self.assertIsNone(read.last_event)

    def test_nearest_zone_picks_the_closest(self):
        candles = ohlc([
            (100, 101, 99, 100), (101, 106, 101, 105), (105, 108, 105, 107),
            (107, 110, 106, 109), (109, 112, 108, 111),
        ])
        read = read_structure(candles, "h1")
        if read.unmitigated_zones:
            nearest = read.nearest_zone(price=103.0)
            self.assertIsNotNone(nearest)
            self.assertEqual(
                nearest.distance_from(103.0),
                min(z.distance_from(103.0) for z in read.unmitigated_zones),
            )


if __name__ == "__main__":
    unittest.main()
