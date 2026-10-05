"""Gold is not open all the time, and until 2026-09-17 this system behaved as
though it were. The weekend was mentioned to the analyst in a prompt and
enforced nowhere; the daily rollover was not modelled at all."""

import unittest
from datetime import datetime, timezone

from gold_trader.journal import Journal
from gold_trader.learning import learn
from gold_trader.macro import MacroCalendar
from gold_trader.risk import TradingLimits, evaluate
from gold_trader.sessions import is_daily_break, is_weekend, market_closed, read_sessions

CLEAR = MacroCalendar(events=[], confidence="current")


def utc(year, month, day, hour, minute=30):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class DailyBreak(unittest.TestCase):
    """17:00-18:00 New York. Anchored there, not to a UTC hour, because the
    UTC hour moves when the US changes its clocks."""

    def test_the_break_is_2100_utc_during_us_daylight_saving(self):
        self.assertIsNone(market_closed(utc(2026, 9, 17, 20)))
        self.assertEqual(market_closed(utc(2026, 9, 17, 21)), "daily_break")
        self.assertIsNone(market_closed(utc(2026, 9, 17, 22)))

    def test_the_break_moves_to_2200_utc_in_winter(self):
        # The same 17:00 New York, an hour later in UTC. Hardcoding 21:00 UTC
        # would be right for half the year and silently wrong for the other.
        self.assertIsNone(market_closed(utc(2026, 12, 15, 21)))
        self.assertEqual(market_closed(utc(2026, 12, 15, 22)), "daily_break")
        self.assertIsNone(market_closed(utc(2026, 12, 15, 23)))

    def test_the_break_opens_and_closes_on_the_hour(self):
        self.assertFalse(is_daily_break(utc(2026, 9, 17, 20, 59)))
        self.assertTrue(is_daily_break(utc(2026, 9, 17, 21, 0)))
        self.assertTrue(is_daily_break(utc(2026, 9, 17, 21, 59)))
        self.assertFalse(is_daily_break(utc(2026, 9, 17, 22, 0)))

    def test_friday_evening_is_the_weekend_not_the_daily_break(self):
        # 18 Sep 2026 is a Friday. After 17:00 NY the market is shut until
        # Sunday, so calling it a one-hour break would be badly wrong.
        friday_evening = utc(2026, 9, 18, 21, 30)
        self.assertFalse(is_daily_break(friday_evening))
        self.assertEqual(market_closed(friday_evening), "weekend")

    def test_the_weekend_still_reads_as_the_weekend(self):
        self.assertEqual(market_closed(utc(2026, 9, 19, 12)), "weekend")   # Saturday
        self.assertTrue(is_weekend(utc(2026, 9, 20, 12)))                  # Sunday midday

    def test_sunday_evening_reopens(self):
        self.assertIsNone(market_closed(utc(2026, 9, 20, 23)))


class Enforcement(unittest.TestCase):
    """A closed market is a hard block in the engine, not advice in a prompt."""

    def _assess(self, now):
        return evaluate(
            direction="long", entry=4350.0, stop=4330.0, target=4400.0, conviction=0.7,
            setup_type="bos_continuation", atr=20.0, spot=4350.0, data_source="csv",
            staleness_min=5.0, now=now, limits=TradingLimits(), calendar=CLEAR,
            journal=Journal(), learning=learn(Journal()),
        )

    def test_an_otherwise_perfect_trade_is_approved_while_open(self):
        self.assertTrue(self._assess(utc(2026, 9, 17, 20)).approved)

    def test_the_same_trade_is_blocked_in_the_daily_break(self):
        decision = self._assess(utc(2026, 9, 17, 21))
        self.assertFalse(decision.approved)
        self.assertIn("MARKET_CLOSED", {b.code for b in decision.breaches})

    def test_the_same_trade_is_blocked_at_the_weekend(self):
        self.assertFalse(self._assess(utc(2026, 9, 19, 12)).approved)

    def test_the_block_is_hard_never_a_warning(self):
        # An entry nobody can take is journalled, then resolved against candles
        # that do not represent tradeable prices. That poisons the record the
        # learning loop is built on.
        decision = self._assess(utc(2026, 9, 19, 12))
        breach = next(b for b in decision.breaches if b.code == "MARKET_CLOSED")
        self.assertEqual(breach.severity, "hard")

    def test_a_blocked_trade_is_not_sized(self):
        self.assertEqual(self._assess(utc(2026, 9, 19, 12)).size_units, 0.0)

    def test_the_breach_says_which_closure_it_is(self):
        weekend = self._assess(utc(2026, 9, 19, 12))
        brk = self._assess(utc(2026, 9, 17, 21))
        weekend_text = next(b.detail for b in weekend.breaches if b.code == "MARKET_CLOSED")
        break_text = next(b.detail for b in brk.breaches if b.code == "MARKET_CLOSED")
        self.assertIn("weekend", weekend_text)
        self.assertIn("rollover", break_text)
        self.assertNotEqual(weekend_text, break_text)


class WhatTheAnalystSees(unittest.TestCase):
    def test_the_prompt_says_the_market_is_shut_for_the_rollover(self):
        read = read_sessions([], utc(2026, 9, 17, 21))
        self.assertTrue(read.daily_break)
        self.assertIn("MARKET CLOSED", read.as_prompt_block(4350.0))
        self.assertIn("rollover", read.as_prompt_block(4350.0))

    def test_the_closure_is_serialised_for_the_dashboard(self):
        self.assertTrue(read_sessions([], utc(2026, 9, 17, 21)).to_dict()["daily_break"])
        self.assertFalse(read_sessions([], utc(2026, 9, 17, 20)).to_dict()["daily_break"])


if __name__ == "__main__":
    unittest.main()
