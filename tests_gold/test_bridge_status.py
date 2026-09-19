"""A disconnected terminal and a quiet market look identical from GitHub: both
produce a bridge that runs, finds no new candles, and pushes nothing. On
2026-09-17 the data branch had a four-hour gap with the PC on throughout, and
there was no way to tell which it had been.

The terminal disconnects from the broker at every close, so disconnection is
only a finding while the market is open. Getting that backwards would page the
owner every single evening."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.bridge_status import (
    CRITICAL, OK, STALE_AFTER_MIN, WARNING, BridgeStatus, assess, load_status,
)

MARKET_OPEN = datetime(2026, 9, 17, 20, 30, tzinfo=timezone.utc)      # Thursday, open
DAILY_BREAK = datetime(2026, 9, 17, 21, 30, tzinfo=timezone.utc)      # 17:30 New York
WEEKEND = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)           # Saturday


def status(connected, minutes_ago=5, now=MARKET_OPEN, **kw):
    return BridgeStatus(
        as_of=(now - timedelta(minutes=minutes_ago)).isoformat(),
        connected=connected, **kw,
    )


class TheDistinctionThatMatters(unittest.TestCase):
    def test_disconnected_while_open_is_critical(self):
        severity, message = assess(status(False), MARKET_OPEN)
        self.assertEqual(severity, CRITICAL)
        self.assertIn("DISCONNECTED", message)
        self.assertIn("market is open", message)

    def test_disconnected_during_the_daily_break_is_fine(self):
        # The terminal drops the connection at every close. Reporting that as a
        # fault would fire an alert every evening.
        severity, message = assess(status(False, now=DAILY_BREAK), DAILY_BREAK)
        self.assertEqual(severity, OK)
        self.assertIn("expected", message)

    def test_disconnected_at_the_weekend_is_fine(self):
        severity, message = assess(status(False, now=WEEKEND), WEEKEND)
        self.assertEqual(severity, OK)
        self.assertIn("weekend", message)

    def test_connected_while_open_is_fine_and_names_the_server(self):
        severity, message = assess(status(True, server="ICMarkets", ping_ms=31.0), MARKET_OPEN)
        self.assertEqual(severity, OK)
        self.assertIn("ICMarkets", message)
        self.assertIn("31ms", message)


class TheBridgeItselfStopping(unittest.TestCase):
    """Distinct from the terminal disconnecting, and it outranks it: a stale
    file's `connected` flag describes a moment that has passed."""

    def test_a_stale_status_file_is_critical_even_if_it_says_connected(self):
        severity, message = assess(
            status(True, minutes_ago=STALE_AFTER_MIN + 10), MARKET_OPEN)
        self.assertEqual(severity, CRITICAL)
        self.assertIn("has not run", message)
        self.assertNotIn("DISCONNECTED", message)

    def test_a_stale_file_is_critical_even_at_the_weekend(self):
        # The market being shut excuses a disconnection, never a bridge that
        # is not running: the PC is meant to be on regardless.
        severity, _ = assess(
            status(True, minutes_ago=STALE_AFTER_MIN + 10, now=WEEKEND), WEEKEND)
        self.assertEqual(severity, CRITICAL)

    def test_a_genuinely_fresh_file_is_not_stale(self):
        severity, _ = assess(status(True, minutes_ago=5), MARKET_OPEN)
        self.assertEqual(severity, OK)

    def test_inside_the_critical_window_but_past_a_whole_cycle_warns(self):
        # This used to assert OK at STALE_AFTER_MIN - 5, i.e. 40 minutes and
        # two missed runs, because there was nothing between fine and dead. The
        # assumption was the defect, not the assertion.
        severity, _ = assess(status(True, minutes_ago=STALE_AFTER_MIN - 5), MARKET_OPEN)
        self.assertEqual(severity, WARNING)

    def test_no_status_file_at_all_asks_for_the_bridge_to_be_updated(self):
        severity, message = assess(None, MARKET_OPEN)
        self.assertEqual(severity, WARNING)
        self.assertIn("UPDATE.bat", message)


class Degradation(unittest.TestCase):
    def test_an_unreadable_timestamp_is_a_warning_not_a_crash(self):
        severity, _ = assess(BridgeStatus(as_of="not a date", connected=True), MARKET_OPEN)
        self.assertEqual(severity, WARNING)

    def test_a_terminal_read_error_is_reported_verbatim(self):
        severity, message = assess(
            status(None, read_error="RuntimeError: IPC closed"), MARKET_OPEN)
        self.assertEqual(severity, WARNING)
        self.assertIn("IPC closed", message)

    def test_an_unknown_connection_state_is_a_warning(self):
        severity, _ = assess(status(None), MARKET_OPEN)
        self.assertEqual(severity, WARNING)


class RoundTrip(unittest.TestCase):
    """Two implementations of one file format: the bridge ships standalone on
    Windows and cannot import this package."""

    def test_what_the_bridge_writes_the_pipeline_reads(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                        "gold_trader", "bridge"))
        import mt5_export

        class Info:
            connected, build, trade_allowed, ping_last = True, 4620, True, 31500

        class Account:
            server = "ICMarkets-Live12"

        class FakeMT5:
            def terminal_info(self):
                return Info()

            def account_info(self):
                return Account()

        with tempfile.TemporaryDirectory() as tmp:
            state = mt5_export.read_terminal_state(FakeMT5(), "XAUUSD")
            mt5_export.write_status(tmp, state, MARKET_OPEN.isoformat())
            loaded = load_status(tmp)
            self.assertTrue(loaded.connected)
            self.assertEqual(loaded.server, "ICMarkets-Live12")
            self.assertEqual(loaded.symbol, "XAUUSD")
            self.assertAlmostEqual(loaded.ping_ms, 31.5)
            self.assertEqual(assess(loaded, MARKET_OPEN)[0], OK)

    def test_the_status_file_uses_unix_line_endings(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                        "gold_trader", "bridge"))
        import mt5_export

        with tempfile.TemporaryDirectory() as tmp:
            path = mt5_export.write_status(tmp, {"connected": True}, MARKET_OPEN.isoformat())
            with open(path, "rb") as fh:
                self.assertNotIn(b"\r", fh.read())

    def test_a_corrupt_status_file_reads_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bridge.json"), "w") as fh:
                fh.write("{broken")
            self.assertIsNone(load_status(tmp))

    def test_a_missing_file_reads_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_status(tmp))

    def test_the_status_serialises_for_the_dashboard(self):
        blob = json.dumps(status(True, server="X").to_dict(MARKET_OPEN))
        self.assertIn("severity", json.loads(blob))


if __name__ == "__main__":
    unittest.main()


class LateIsNotDeadAndNotFine(unittest.TestCase):
    """A bridge keeping no cadence used to report "ok" for 45 minutes.

    The bridge runs every 15 minutes. With only an ok/critical split, three
    missed runs in a row still read green -- and the message said so out loud,
    "Terminal connected, last checked 40min ago", a number flatly contradicting
    the verdict printed beside it. A reader who sees that learns to stop reading
    the verdict.

    Found at 01:12 on 2026-09-18: the bridge had been started by hand once and
    Task Scheduler never picked it up, so it sat at 40 minutes old, silent and
    green.
    """

    def test_one_late_tick_is_still_ok(self):
        # A single missed tick is noise, and an alarm for noise is worse than
        # no alarm.
        severity, _ = self._assess(age_min=18)
        self.assertEqual(severity, OK)

    def test_a_whole_cycle_missed_warns(self):
        severity, _ = self._assess(age_min=40)
        self.assertEqual(severity, WARNING)

    def test_the_warning_counts_the_missed_runs(self):
        _, message = self._assess(age_min=40)
        self.assertIn("2 scheduled run(s) missed", message)

    def test_the_warning_names_where_to_look(self):
        # The remedy is on the Windows PC, and saying "late" without saying
        # where is the report that wastes the evening.
        _, message = self._assess(age_min=40)
        self.assertIn("Task Scheduler", message)
        self.assertIn("0x0", message)

    def test_long_enough_is_still_critical(self):
        severity, _ = self._assess(age_min=90)
        self.assertEqual(severity, CRITICAL)

    def test_lateness_while_the_market_is_shut_is_not_reported(self):
        # The terminal drops the broker at the close and the bridge has nothing
        # to do. Warning nightly is how a real alert becomes background noise.
        closed = datetime(2026, 9, 19, 23, 0, tzinfo=timezone.utc)  # Friday night
        severity, _ = self._assess(age_min=40, now=closed)
        self.assertEqual(severity, OK)

    def test_the_tiers_are_ordered(self):
        from gold_trader.bridge_status import LATE_AFTER_MIN, STALE_AFTER_MIN

        self.assertLess(LATE_AFTER_MIN, STALE_AFTER_MIN)
        # Late must be longer than one cadence, or a bridge that is merely
        # running slightly behind trips it every time.
        self.assertGreater(LATE_AFTER_MIN, 15)

    def _assess(self, age_min, now=None):
        now = now or datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)  # Thursday
        status = BridgeStatus(
            as_of=(now - timedelta(minutes=age_min)).isoformat(),
            connected=True, server="PepperstoneUK-Live", ping_ms=15.4,
        )
        return assess(status, now)
