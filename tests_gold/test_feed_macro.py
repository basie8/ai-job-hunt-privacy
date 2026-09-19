import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.feed import (
    Candle, CsvFeed, FeedUnavailable, HttpFeed, InlineFeed, candles_from_rows, timeframe_minutes,
)
from gold_trader.macro import BlackoutPolicy, MacroCalendar, claims_dates, nfp_dates
from tests_gold.helpers import ramp


class CandleValidation(unittest.TestCase):
    def test_a_candle_with_high_below_low_is_rejected(self):
        with self.assertRaises(ValueError):
            Candle(datetime.now(timezone.utc), 100, 95, 105, 100)

    def test_a_close_outside_the_range_is_rejected(self):
        with self.assertRaises(ValueError):
            Candle(datetime.now(timezone.utc), 100, 105, 95, 120)

    def test_series_rejects_out_of_order_candles(self):
        from gold_trader.feed import Series
        now = datetime.now(timezone.utc)
        a = Candle(now, 100, 101, 99, 100)
        b = Candle(now - timedelta(hours=1), 100, 101, 99, 100)
        with self.assertRaises(ValueError):
            Series("h1", [a, b])


class ColumnAliasing(unittest.TestCase):
    def test_mt5_style_columns_parse(self):
        rows = [{"<DATE>": "2026.09.01 10:00", "<OPEN>": "2400", "<HIGH>": "2410",
                 "<LOW>": "2395", "<CLOSE>": "2405", "<TICKVOL>": "12"}]
        parsed = candles_from_rows(rows)
        self.assertEqual(parsed[0].close, 2405.0)
        self.assertEqual(parsed[0].volume, 12.0)

    def test_tradingview_style_columns_parse(self):
        rows = [{"time": "2026-09-01T10:00:00Z", "open": "2400", "high": "2410",
                 "low": "2395", "close": "2405"}]
        self.assertEqual(candles_from_rows(rows)[0].open, 2400.0)

    def test_rows_are_sorted_oldest_first(self):
        rows = [
            {"date": "2026-09-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            {"date": "2026-09-01", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        ]
        parsed = candles_from_rows(rows)
        self.assertLess(parsed[0].ts, parsed[1].ts)

    def test_a_missing_column_names_what_is_missing(self):
        with self.assertRaises(ValueError) as ctx:
            candles_from_rows([{"date": "2026-09-01", "open": 1}])
        self.assertIn("high", str(ctx.exception))


class CsvAndHttp(unittest.TestCase):
    def test_csv_feed_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "XAUUSD_h1.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("time,open,high,low,close,volume\n")
                base = datetime(2026, 9, 1, tzinfo=timezone.utc)
                for i, close in enumerate(ramp(2400.0, 30, 1.0)):
                    ts = (base + timedelta(hours=i)).isoformat()
                    fh.write(f"{ts},{close-1},{close+2},{close-2},{close},10\n")
            feed = CsvFeed(tmp)
            snap = feed.snapshot(["h1"])
            self.assertEqual(len(snap.series["h1"]), 30)
            self.assertAlmostEqual(snap.spot, 2429.0)

    def test_a_missing_csv_says_what_to_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FeedUnavailable) as ctx:
                CsvFeed(tmp).load("h1")
            self.assertIn("Export", str(ctx.exception))

    def test_http_feed_refuses_rather_than_guessing(self):
        feed = HttpFeed("twelvedata", env={"TWELVEDATA_API_KEY": "x"})
        with self.assertRaises(FeedUnavailable) as ctx:
            feed.snapshot(["h1"])
        self.assertIn("egress policy", str(ctx.exception))

    def test_http_feed_names_the_missing_key_first(self):
        feed = HttpFeed("polygon", env={})
        with self.assertRaises(FeedUnavailable) as ctx:
            feed.snapshot(["h1"])
        self.assertIn("POLYGON_API_KEY", str(ctx.exception))

    def test_unknown_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            timeframe_minutes("h3")


class Staleness(unittest.TestCase):
    def test_staleness_is_measured_against_the_supplied_clock(self):
        # Reproducibility: the same snapshot replayed with the same `now` must
        # give the same answer regardless of when the replay happens.
        from tests_gold.helpers import ramp, snapshot_from
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        snap = snapshot_from(ramp(2400.0, 30, 1.0), timeframes=("h1",), end=now)
        self.assertAlmostEqual(snap.staleness_min(now), 0.0, places=6)
        self.assertAlmostEqual(snap.staleness_min(now + timedelta(minutes=45)), 45.0, places=6)
        self.assertFalse(snap.is_stale(now))

    def test_to_dict_reports_staleness_against_the_same_clock(self):
        from tests_gold.helpers import ramp, snapshot_from
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        snap = snapshot_from(ramp(2400.0, 30, 1.0), timeframes=("h1",), end=now)
        self.assertEqual(snap.to_dict(now)["staleness_min"], 0.0)


class Calendar(unittest.TestCase):
    def test_nfp_lands_on_the_first_friday(self):
        for day in nfp_dates(datetime(2026, 9, 17).date(), months=3):
            self.assertEqual(day.weekday(), 4)
            self.assertLessEqual(day.day, 7)

    def test_claims_land_on_thursdays(self):
        for day in claims_dates(datetime(2026, 9, 17).date(), weeks=4):
            self.assertEqual(day.weekday(), 3)

    def test_calendar_without_a_file_is_derived_only_and_says_so(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        cal = MacroCalendar.build(now, scheduled_path=None)
        self.assertEqual(cal.confidence, "derived_only")
        self.assertIn("WARNING", cal.as_prompt_block(now))

    def test_an_expired_scheduled_file_reads_as_stale(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"covers_through": "2026-08-01T00:00:00Z", "events": []}, fh)
            cal = MacroCalendar.build(now, path)
            self.assertEqual(cal.confidence, "stale")
            self.assertIn("out of date", cal.as_prompt_block(now))

    def test_a_current_scheduled_file_loads_its_events(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "covers_through": "2026-12-31T00:00:00Z",
                        "events": [{"kind": "FOMC", "name": "FOMC decision",
                                    "when": "2026-09-18T18:00:00Z", "impact": "high"}],
                        "readings": [{"name": "DXY", "value": "101.4", "as_of": "2026-09-17", "source": "manual"}],
                    },
                    fh,
                )
            cal = MacroCalendar.build(now, path)
            self.assertEqual(cal.confidence, "current")
            self.assertTrue(any(e.kind == "FOMC" for e in cal.events))
            self.assertIn("DXY", cal.as_prompt_block(now))


class Blackout(unittest.TestCase):
    def _calendar_with_event(self, when):
        from gold_trader.macro import MacroEvent
        return MacroCalendar(events=[MacroEvent("FOMC", "FOMC", when, "high")], confidence="current")

    def test_entries_are_blocked_before_a_high_impact_event(self):
        now = datetime(2026, 9, 17, 17, 30, tzinfo=timezone.utc)
        cal = self._calendar_with_event(datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(cal.blackout(now, BlackoutPolicy()))

    def test_entries_are_blocked_just_after_the_event(self):
        now = datetime(2026, 9, 17, 18, 20, tzinfo=timezone.utc)
        cal = self._calendar_with_event(datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(cal.blackout(now, BlackoutPolicy()))

    def test_entries_are_clear_well_outside_the_window(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        cal = self._calendar_with_event(datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc))
        self.assertIsNone(cal.blackout(now, BlackoutPolicy()))

    def test_a_medium_impact_event_has_a_narrower_window(self):
        from gold_trader.macro import MacroEvent
        event_at = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)
        cal = MacroCalendar(events=[MacroEvent("Claims", "CLAIMS", event_at, "medium")])
        self.assertIsNone(cal.blackout(event_at - timedelta(minutes=45), BlackoutPolicy()))
        self.assertIsNotNone(cal.blackout(event_at - timedelta(minutes=10), BlackoutPolicy()))


if __name__ == "__main__":
    unittest.main()
