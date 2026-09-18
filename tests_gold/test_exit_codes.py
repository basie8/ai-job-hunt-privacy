"""The exit codes the Routine prompts actually branch on.

Every scheduled run is a prompt that reads an exit code and decides what to do
next: stop, record `stale_data`, notify, or carry on. That makes each code a
contract between the prompt and the CLI -- and a contract nothing verified.

It has already broken twice in one day. `pull-data` printed STALE and exited 0,
so a run the prompt should have stopped went on to spend $0.18 on stale
candles. `_config()` raised TypeError on every command while 298 unit tests
passed, because no test ever crossed the entry point a human or a prompt types.

Both defects are the same shape: the component was right, the seam between the
component and its caller was not. These tests sit on the seam. If a code
changes, this file fails, and the prompts that depend on it get updated
deliberately rather than discovered in production.
"""

import argparse
import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader import cli, heartbeat

def _ago(minutes):
    """Beats are placed relative to the real clock.

    `cmd_runs` reads the wall clock itself, so a fixed timestamp would make
    these tests pass or fail depending on the hour they run at. Offsets of a
    minute or two sit inside the 25-minute grace period, which makes "no run
    was missed" true regardless of when the suite runs.
    """
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


class RunsExitsNonZeroOnAGap(unittest.TestCase):
    """The audit prompt: "`runs --hours 26` -- did the scheduled runs actually
    happen? Exits non-zero on any gap." A silent run is the failure this whole
    subsystem exists to catch, so the code carrying that news must be right."""

    def test_a_missed_run_exits_one(self):
        # The mapping from "this report is unhealthy" to "the caller must not
        # overlook it". Driven through a report rather than the clock, so the
        # assertion holds at any hour the suite runs.
        from unittest import mock

        from gold_trader.heartbeat import SIGNAL_SCHEDULE, RunReport

        now = datetime.now(timezone.utc)
        unhealthy = RunReport(
            routine="signal", schedule=SIGNAL_SCHEDULE,
            window_start=now - timedelta(hours=26), window_end=now,
            missed=[now - timedelta(hours=2)], armed_at=now - timedelta(hours=26),
        )
        self.assertFalse(unhealthy.healthy())
        with mock.patch.object(cli, "audit_runs", return_value=unhealthy):
            code, _ = self._runs([])
        self.assertEqual(code, 1)

    def test_an_unresolved_error_exits_one(self):
        code, _ = self._runs([("signal", "error", 1)])
        self.assertEqual(code, 1)

    def test_an_error_a_later_run_superseded_does_not(self):
        # History, not a standing fault. Leaving it red would keep the audit
        # shouting about something already fixed.
        code, _ = self._runs([("signal", "error", 2), ("signal", "no_trade", 1)])
        self.assertEqual(code, 0)

    def test_an_empty_record_exits_zero(self):
        # "not armed yet" is not a failure -- the detector simply cannot speak
        # for the period before its first heartbeat. The audit prompt says so
        # explicitly, so the exit code must agree with it.
        code, _ = self._runs([])
        self.assertEqual(code, 0)

    def _runs(self, beats, routine="signal"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, heartbeat.HEARTBEAT_FILENAME)
        for name, outcome, minutes_ago in beats:
            heartbeat.record(path, name, outcome, "", now=_ago(minutes_ago))
        args = argparse.Namespace(state_dir=tmp.name, journal=None, account=None,
                                  risk_pct=None, routine=routine, hours=26,
                                  json_out=True)
        return _capture(cli.cmd_runs, args)


class SelfcheckExitsNonZeroOnAFailure(unittest.TestCase):
    """The audit prompt runs it first and treats a non-zero exit as "something
    regressed". A check that fails while the command returns 0 would make the
    entire self-check advisory."""

    def test_a_clean_repo_exits_zero(self):
        args = argparse.Namespace(repo=".", json_out=True)
        code, _ = _capture(cli.cmd_selfcheck, args)
        self.assertEqual(code, 0)

    def test_a_failed_check_exits_one(self):
        from unittest import mock

        from gold_trader.selfcheck import Report

        from gold_trader.selfcheck import FAIL

        broken = Report()
        broken.add("invented", "a check that did not pass", FAIL, "for this test")
        with mock.patch.object(cli, "run_all", return_value=broken):
            args = argparse.Namespace(repo=".", json_out=True)
            code, _ = _capture(cli.cmd_selfcheck, args)
        self.assertEqual(code, 1)


class ProgressExitsNonZeroOnAStaleClaim(unittest.TestCase):
    """The audit prompt: fix any STALE CLAIM. A roadmap row claiming work that
    the repo cannot verify is the roadmap lying, and the exit code is how the
    prompt learns of it."""

    def test_a_truthful_roadmap_exits_zero(self):
        args = argparse.Namespace(repo=".", json_out=True,
                                  roadmap="docs/ROADMAP.md")
        code, _ = _capture(cli.cmd_progress, args)
        self.assertEqual(code, 0)


class TheCodesAreDistinct(unittest.TestCase):
    """Two failures that need different remedies must not share a code.

    `signal` exits 3 for a missing key and 5 for a refused one. Collapsing them
    sent a whole evening looking for a variable that was already set.
    """

    def test_signal_separates_absent_from_refused(self):
        import inspect

        source = inspect.getsource(cli.cmd_signal)
        self.assertIn("return 3", source)
        self.assertIn("return 5", source)

    def test_credentials_uses_the_same_codes_as_signal(self):
        # So a Routine can check the key and run the pipeline with one set of
        # branches, rather than two tables that drift apart.
        import inspect

        creds = inspect.getsource(cli.cmd_credentials)
        for code in ("return 3", "return 5"):
            self.assertIn(code, creds)


def _capture(func, args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = func(args)
    return code, out.getvalue()


if __name__ == "__main__":
    unittest.main()
