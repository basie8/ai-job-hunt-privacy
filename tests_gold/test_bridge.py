import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gold_trader", "bridge"))
import mt5_export  # noqa: E402


class FakeSymbol:
    def __init__(self, name):
        self.name = name


class FakeTick:
    def __init__(self, ts):
        self.time = int(ts.timestamp())


class FakeMT5:
    """Just enough of the MetaTrader5 surface to exercise the bridge."""

    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15 = 1, 5, 15
    TIMEFRAME_M30, TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 30, 16385, 16388, 16408

    def __init__(self, symbols, tick_time=None, rates=None):
        self._symbols = [FakeSymbol(s) for s in symbols]
        self._tick_time = tick_time
        self._rates = rates
        self.selected = []

    def symbols_get(self):
        return self._symbols

    def symbol_select(self, name, enable=True):
        if name in {s.name for s in self._symbols}:
            self.selected.append(name)
            return True
        return False

    def symbol_info_tick(self, symbol):
        return FakeTick(self._tick_time) if self._tick_time else None

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return self._rates

    def last_error(self):
        return (0, "ok")


class SymbolResolution(unittest.TestCase):
    def test_the_plain_name_is_preferred(self):
        mt5 = FakeMT5(["EURUSD", "XAUUSD", "GOLD"])
        self.assertEqual(mt5_export.resolve_symbol(mt5), "XAUUSD")

    def test_a_broker_suffix_is_discovered(self):
        mt5 = FakeMT5(["EURUSD.m", "XAUUSD.m"])
        self.assertEqual(mt5_export.resolve_symbol(mt5), "XAUUSD.m")

    def test_an_explicit_override_is_honoured(self):
        mt5 = FakeMT5(["XAUUSD", "XAUUSD.raw"])
        self.assertEqual(mt5_export.resolve_symbol(mt5, "XAUUSD.raw"), "XAUUSD.raw")

    def test_an_unknown_override_exits_rather_than_guessing(self):
        mt5 = FakeMT5(["XAUUSD"])
        with self.assertRaises(SystemExit):
            mt5_export.resolve_symbol(mt5, "NOPE")

    def test_an_unrecognised_gold_name_lists_the_candidates(self):
        mt5 = FakeMT5(["XAUUSD.weird", "EURUSD"])
        with self.assertRaises(SystemExit) as ctx:
            mt5_export.resolve_symbol(mt5)
        self.assertIn("XAUUSD.weird", str(ctx.exception))

    def test_a_broker_with_no_gold_exits(self):
        with self.assertRaises(SystemExit):
            mt5_export.resolve_symbol(FakeMT5(["EURUSD"]))


class ServerTimeOffset(unittest.TestCase):
    def test_a_utc_plus_three_broker_is_detected(self):
        mt5 = FakeMT5(["XAUUSD"], tick_time=datetime.now(timezone.utc) + timedelta(hours=3))
        self.assertAlmostEqual(mt5_export.detect_server_offset_hours(mt5, "XAUUSD"), 3.0)

    def test_a_utc_broker_reads_as_zero(self):
        mt5 = FakeMT5(["XAUUSD"], tick_time=datetime.now(timezone.utc))
        self.assertAlmostEqual(mt5_export.detect_server_offset_hours(mt5, "XAUUSD"), 0.0)

    def test_a_half_hour_offset_is_preserved(self):
        mt5 = FakeMT5(["XAUUSD"], tick_time=datetime.now(timezone.utc) + timedelta(hours=5, minutes=30))
        self.assertAlmostEqual(mt5_export.detect_server_offset_hours(mt5, "XAUUSD"), 5.5)

    def test_no_tick_falls_back_to_zero(self):
        self.assertEqual(mt5_export.detect_server_offset_hours(FakeMT5(["XAUUSD"]), "XAUUSD"), 0.0)


class Fetch(unittest.TestCase):
    def _rates(self, base):
        return [
            {"time": int((base + timedelta(hours=i)).timestamp()), "open": 2400.0 + i,
             "high": 2405.0 + i, "low": 2395.0 + i, "close": 2402.0 + i, "tick_volume": 100 + i}
            for i in range(3)
        ]

    def test_server_time_is_shifted_back_to_utc(self):
        # A bar stamped 12:00 on a UTC+3 broker is really 09:00 UTC.
        base = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        mt5 = FakeMT5(["XAUUSD"], rates=self._rates(base))
        rows = mt5_export.fetch(mt5, "XAUUSD", "h1", 3, offset_hours=3.0)
        self.assertEqual(datetime.fromisoformat(rows[0]["time"]).hour, 9)

    def test_a_utc_broker_needs_no_shift(self):
        base = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        mt5 = FakeMT5(["XAUUSD"], rates=self._rates(base))
        rows = mt5_export.fetch(mt5, "XAUUSD", "h1", 3, offset_hours=0.0)
        self.assertEqual(datetime.fromisoformat(rows[0]["time"]).hour, 12)

    def test_an_unsupported_timeframe_exits(self):
        mt5 = FakeMT5(["XAUUSD"], rates=self._rates(datetime.now(timezone.utc)))
        with self.assertRaises(SystemExit):
            mt5_export.fetch(mt5, "XAUUSD", "h3", 3, 0.0)

    def test_an_empty_response_exits_rather_than_writing_nothing(self):
        mt5 = FakeMT5(["XAUUSD"], rates=[])
        with self.assertRaises(SystemExit):
            mt5_export.fetch(mt5, "XAUUSD", "h1", 3, 0.0)

    def test_fetched_rows_parse_back_through_the_pipeline_feed(self):
        from gold_trader.feed import candles_from_rows
        base = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        mt5 = FakeMT5(["XAUUSD"], rates=self._rates(base))
        rows = mt5_export.fetch(mt5, "XAUUSD", "h1", 3, 0.0)
        candles = candles_from_rows(rows)
        self.assertEqual(len(candles), 3)
        self.assertAlmostEqual(candles[0].close, 2402.0)


class CsvWriting(unittest.TestCase):
    def test_writing_creates_the_directory_and_reports_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "XAUUSD_h1.csv")
            rows = [{"time": "2026-09-17T12:00:00+00:00", "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5, "volume": 10}]
            self.assertTrue(mt5_export.write_csv(rows, path))
            self.assertTrue(os.path.exists(path))

    def test_rewriting_identical_candles_reports_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "XAUUSD_h1.csv")
            rows = [{"time": "2026-09-17T12:00:00+00:00", "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5, "volume": 10}]
            mt5_export.write_csv(rows, path)
            # Idempotency is what keeps the data branch free of empty commits.
            self.assertFalse(mt5_export.write_csv(rows, path))

    def test_a_new_bar_reports_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "XAUUSD_h1.csv")
            rows = [{"time": "2026-09-17T12:00:00+00:00", "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5, "volume": 10}]
            mt5_export.write_csv(rows, path)
            rows.append({"time": "2026-09-17T13:00:00+00:00", "open": 1.5, "high": 2.5,
                         "low": 1.0, "close": 2.0, "volume": 12})
            self.assertTrue(mt5_export.write_csv(rows, path))


if __name__ == "__main__":
    unittest.main()
