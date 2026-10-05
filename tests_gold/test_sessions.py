import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.feed import Candle
from gold_trader.sessions import (
    active_killzone, active_sessions, is_weekend, read_sessions, session_range,
)


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def candles_between(start, end, step_min=15, price=2400.0, spread=2.0):
    out, ts, i = [], start, 0
    while ts < end:
        out.append(Candle(ts, price + i * 0.1, price + i * 0.1 + spread,
                          price + i * 0.1 - spread, price + i * 0.1))
        ts += timedelta(minutes=step_min)
        i += 1
    return out


class Killzones(unittest.TestCase):
    def test_london_killzone_in_summer_is_utc_six_to_nine(self):
        # 02:00-05:00 New York; in EDT that is 06:00-09:00 UTC.
        self.assertEqual(active_killzone(utc(2026, 7, 15, 7)), "london_killzone")
        self.assertIsNone(active_killzone(utc(2026, 7, 15, 5, 30)))

    def test_london_killzone_in_winter_shifts_an_hour(self):
        # Same 02:00-05:00 New York, but EST -> 07:00-10:00 UTC.
        self.assertEqual(active_killzone(utc(2026, 1, 15, 8)), "london_killzone")
        self.assertIsNone(active_killzone(utc(2026, 1, 15, 6, 30)))

    def test_new_york_killzone_is_detected(self):
        self.assertEqual(active_killzone(utc(2026, 7, 15, 12)), "ny_killzone")

    def test_a_quiet_hour_has_no_killzone(self):
        self.assertIsNone(active_killzone(utc(2026, 7, 15, 20)))


class Sessions(unittest.TestCase):
    def test_the_overlap_is_flagged_when_both_are_open(self):
        names = active_sessions(utc(2026, 7, 15, 14))  # 10:00 New York
        self.assertIn("london", names)
        self.assertIn("new_york", names)
        self.assertIn("overlap", names)

    def test_the_asian_session_is_detected(self):
        self.assertIn("asian", active_sessions(utc(2026, 7, 15, 2)))  # 22:00 NY previous day

    def test_new_york_alone_is_not_an_overlap(self):
        names = active_sessions(utc(2026, 7, 15, 20))  # 16:00 New York
        self.assertIn("new_york", names)
        self.assertNotIn("overlap", names)


class Weekend(unittest.TestCase):
    def test_saturday_is_closed(self):
        self.assertTrue(is_weekend(utc(2026, 9, 19, 12)))

    def test_friday_after_the_new_york_close_is_closed(self):
        self.assertTrue(is_weekend(utc(2026, 9, 18, 22)))  # 18:00 NY Friday

    def test_friday_morning_is_open(self):
        self.assertFalse(is_weekend(utc(2026, 9, 18, 14)))

    def test_sunday_evening_reopens(self):
        self.assertFalse(is_weekend(utc(2026, 9, 20, 23)))  # 19:00 NY Sunday

    def test_sunday_afternoon_is_still_closed(self):
        self.assertTrue(is_weekend(utc(2026, 9, 20, 16)))


class Ranges(unittest.TestCase):
    def test_a_completed_asian_range_is_measured(self):
        # Asian session is 19:00-04:00 New York.
        candles = candles_between(utc(2026, 7, 14, 23), utc(2026, 7, 15, 8))
        rng = session_range(candles, "asian", moment=utc(2026, 7, 15, 14))
        self.assertIsNotNone(rng)
        self.assertGreater(rng.high, rng.low)
        self.assertGreater(rng.bars, 0)
        self.assertAlmostEqual(rng.size, rng.high - rng.low)

    def test_a_session_still_running_returns_nothing(self):
        # A range that is still forming is not yet liquidity.
        candles = candles_between(utc(2026, 7, 14, 23), utc(2026, 7, 15, 2))
        self.assertIsNone(session_range(candles, "asian", moment=utc(2026, 7, 15, 2)))

    def test_an_unknown_session_is_rejected(self):
        with self.assertRaises(ValueError):
            session_range([], "tokyo_afternoon", moment=utc(2026, 7, 15, 12))

    def test_no_candles_yields_no_range(self):
        self.assertIsNone(session_range([], "asian", moment=utc(2026, 7, 15, 12)))


class Read(unittest.TestCase):
    def test_the_prompt_block_names_the_session_and_range(self):
        candles = candles_between(utc(2026, 7, 14, 23), utc(2026, 7, 15, 13))
        read = read_sessions(candles, utc(2026, 7, 15, 14))
        block = read.as_prompt_block(price=2400.0)
        self.assertIn("New York", block)
        self.assertIn("overlap", block)
        self.assertIn("asian range", block)

    def test_a_weekend_read_says_the_market_is_closed(self):
        read = read_sessions([], utc(2026, 9, 19, 12))
        self.assertTrue(read.weekend)
        self.assertIn("MARKET CLOSED", read.as_prompt_block(price=2400.0))

    def test_the_read_serialises_for_the_journal(self):
        candles = candles_between(utc(2026, 7, 14, 23), utc(2026, 7, 15, 13))
        payload = read_sessions(candles, utc(2026, 7, 15, 14)).to_dict()
        self.assertIn("killzone", payload)
        self.assertIn("sessions", payload)
        self.assertIn("ranges", payload)


if __name__ == "__main__":
    unittest.main()
