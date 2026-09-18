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


class StdinIsBytes(unittest.TestCase):
    """Regression: Windows translated "\\n" to "\\r\\n" writing git's stdin.

    `git mktree` reads one entry per line, so the stray carriage return became
    part of every filename and the branch shipped 'data\\r/XAUUSD_h1.csv\\r'.
    It looked correct on the machine that pushed it and broke every reader.
    Linux never reproduced it, so the guard is on the call itself.
    """

    def test_stdin_is_sent_as_bytes_not_text(self):
        captured = {}
        real = subprocess.run

        def spy(args, **kwargs):
            captured["input"] = kwargs.get("input")
            captured["text"] = kwargs.get("text")
            return real(["true"], capture_output=True)

        subprocess.run = spy
        try:
            mt5_export.git(".", "mktree", stdin="100644 blob abc\tfile.csv\n")
        finally:
            subprocess.run = real

        self.assertIsInstance(captured["input"], bytes, "stdin must bypass text mode")
        self.assertNotIn(captured.get("text"), (True,), "text=True re-enables translation")
        self.assertNotIn(b"\r", captured["input"])

    def test_a_tree_entry_containing_a_carriage_return_is_refused(self):
        with self.assertRaises(RuntimeError) as ctx:
            mt5_export._mktree(".", ["100644 blob abc\tfile.csv\r"])
        self.assertIn("line break", str(ctx.exception))

    def test_pushed_paths_have_no_stray_characters(self):
        import os as _os
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as tmp:
            origin = _os.path.join(tmp, "origin.git")
            subprocess.run(["git", "init", "--bare", "-q", origin], check=True)
            repo = _os.path.join(tmp, "repo")
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "-C", repo, "remote", "add", "origin", origin], check=True)
            subprocess.run(["git", "-C", repo, "config", "user.email", "t@e.com"], check=True)
            subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)

            end = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
            rows = [{"time": (end - timedelta(hours=i)).isoformat(), "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5, "volume": 10} for i in range(3)]
            mt5_export.write_csv(rows, _os.path.join(repo, "data", "XAUUSD_h1.csv"))
            mt5_export.write_fx(_os.path.join(repo, "data"), "GBPUSD", 1.3377,
                                end.isoformat(), "MT5 GBPUSD")
            mt5_export.push_data_branch(repo, _os.path.join(repo, "data"), "test")

            listing = subprocess.run(
                ["git", "-C", repo, "ls-tree", "-r", "--name-only", "origin/market-data"],
                capture_output=True, text=True, check=True,
            ).stdout.split()
            # The rate travels with the candles; the pipeline reads both from
            # the same branch.
            self.assertEqual(listing, ["data/XAUUSD_h1.csv", "data/fx.json"])


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


class BridgeFxWriting(unittest.TestCase):
    """The rate ticks every second. Writing it every run would put a commit on
    the data branch every 15 minutes, which is what the content-hash check on
    candles exists to prevent."""

    NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    def _at(self, hours):
        return (self.NOW + timedelta(hours=hours)).isoformat()

    def test_the_first_reading_is_always_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(mt5_export.fx_needs_writing(tmp, "GBPUSD", 1.3377, self._at(0)))

    def test_an_unchanged_rate_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5")
            self.assertEqual(mt5_export.fx_needs_writing(tmp, "GBPUSD", 1.3377, self._at(1)), "")

    def test_a_move_below_the_threshold_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5")
            self.assertEqual(
                mt5_export.fx_needs_writing(tmp, "GBPUSD", 1.33775, self._at(1)), "")

    def test_a_real_move_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5")
            self.assertIn("moved", mt5_export.fx_needs_writing(tmp, "GBPUSD", 1.3450, self._at(1)))

    def test_a_flat_rate_is_refreshed_before_the_reader_calls_it_stale(self):
        # Otherwise a quiet market looks identical to a stopped bridge.
        from gold_trader.fx import STALE_AFTER_HOURS

        self.assertLess(mt5_export.FX_REFRESH_HOURS, STALE_AFTER_HOURS)
        with tempfile.TemporaryDirectory() as tmp:
            mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5")
            self.assertIn("refreshed", mt5_export.fx_needs_writing(
                tmp, "GBPUSD", 1.3377, self._at(mt5_export.FX_REFRESH_HOURS + 1)))

    def test_a_corrupt_file_is_treated_as_no_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "fx.json"), "w") as fh:
                fh.write("{broken")
            self.assertEqual(
                mt5_export.fx_needs_writing(tmp, "GBPUSD", 1.3377, self._at(0)), "first reading")

    def test_what_the_bridge_writes_the_pipeline_reads(self):
        # Two separate implementations of the same file format -- the bridge
        # ships standalone on Windows and cannot import the package.
        from gold_trader.fx import load_fx

        with tempfile.TemporaryDirectory() as tmp:
            mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5 GBPUSD.m")
            reading = load_fx(tmp, "GBPUSD")
            self.assertEqual(reading.rate, 1.3377)
            self.assertEqual(reading.source, "MT5 GBPUSD.m")
            self.assertFalse(reading.is_stale(self.NOW))

    def test_the_fx_file_is_written_with_unix_line_endings(self):
        # A "\r" inside a git tree entry is what corrupted the data branch once.
        with tempfile.TemporaryDirectory() as tmp:
            path = mt5_export.write_fx(tmp, "GBPUSD", 1.3377, self._at(0), "MT5")
            with open(path, "rb") as fh:
                self.assertNotIn(b"\r", fh.read())


if __name__ == "__main__":
    unittest.main()


class TheBridgeMustLeaveATraceOnThePC(unittest.TestCase):
    """A task that ran and died looks exactly like a task that never fired.

    Everything mt5_export prints goes to stdout, and under Task Scheduler
    stdout goes nowhere. So on 2026-09-18, with the bridge silent for an hour
    and the PC on the whole time, there was no way to tell whether Windows was
    starting the task at all -- the same absence this project keeps finding,
    this time on the machine rather than in the cloud.

    The log is local and never pushed, because when the push is what is broken
    a pushed log cannot report it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name

    def test_a_crash_is_recorded(self):
        mt5_export.log_run(self.repo, "error", "RuntimeError: boom")
        self.assertIn("RuntimeError: boom", self._log())

    def test_a_success_is_recorded_too(self):
        # A quiet run and a missing run must not look the same -- the same rule
        # the cloud heartbeat follows.
        mt5_export.log_run(self.repo, "ok")
        self.assertIn("ok", self._log())

    def test_every_line_is_timestamped(self):
        # Without the time, the log answers "did it ever work" but not "is it
        # running now", which is the actual question.
        mt5_export.log_run(self.repo, "ok")
        self.assertRegex(self._log(), r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_logging_never_raises(self):
        # A logging failure must not become the thing that stops a candle push.
        mt5_export.log_run(os.path.join(self.repo, "no", "such", "dir"), "ok")

    def test_the_log_is_rotated_not_grown_forever(self):
        path = os.path.join(self.repo, mt5_export.RUN_LOG_FILENAME)
        with open(path, "w") as fh:
            fh.write("x" * (mt5_export.RUN_LOG_MAX_BYTES + 10))
        mt5_export.log_run(self.repo, "ok")
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), 1000)

    def test_the_repo_is_found_without_argparse(self):
        # The log has to work even when argparse is what rejected the
        # arguments, or a mistyped scheduled task stays invisible.
        self.assertEqual(mt5_export._repo_from(["--repo", "C:/aurum", "--push"]), "C:/aurum")
        self.assertEqual(mt5_export._repo_from(["--repo=C:/aurum"]), "C:/aurum")

    def test_the_log_is_gitignored(self):
        # It must never be pushed: it is the witness for a broken push.
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn(mt5_export.RUN_LOG_FILENAME, fh.read())

    def _log(self):
        with open(os.path.join(self.repo, mt5_export.RUN_LOG_FILENAME), encoding="utf-8") as fh:
            return fh.read()
