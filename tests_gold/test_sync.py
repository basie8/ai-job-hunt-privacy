"""Round-trips the bridge -> data branch -> session pull over real git repos."""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gold_trader", "bridge"))
import mt5_export  # noqa: E402

from gold_trader.sync import DATA_BRANCH, describe_data_dir, pull_data_branch


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{' '.join(args)}\n{result.stderr}{result.stdout}")
    return result


def init_clone(origin, path):
    run("git", "clone", origin, path)
    run("git", "-C", path, "config", "user.email", "test@example.com")
    run("git", "-C", path, "config", "user.name", "Test")
    return path


def bars(n, end, step_min=60, start_price=2400.0):
    first = end - timedelta(minutes=step_min * (n - 1))
    return [
        {
            "time": (first + timedelta(minutes=step_min * i)).isoformat(),
            "open": start_price + i, "high": start_price + i + 2,
            "low": start_price + i - 2, "close": start_price + i + 1, "volume": 100,
        }
        for i in range(n)
    ]


class BridgeRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        run("git", "init", "--bare", "-b", "main", self.origin)

        seed = init_clone(self.origin, os.path.join(root, "seed"))
        with open(os.path.join(seed, "README.md"), "w") as fh:
            fh.write("# seed\n")
        run("git", "-C", seed, "add", "-A")
        run("git", "-C", seed, "commit", "-m", "init")
        run("git", "-C", seed, "push", "origin", "main")

        self.local = init_clone(self.origin, os.path.join(root, "local"))   # the bridge machine
        self.cloud = init_clone(self.origin, os.path.join(root, "cloud"))   # the scheduled session
        self.now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_local(self, end, timeframes=("h1", "m15")):
        data_dir = os.path.join(self.local, "data")
        for tf in timeframes:
            step = 60 if tf == "h1" else 15
            mt5_export.write_csv(
                bars(40, end, step_min=step),
                os.path.join(data_dir, f"XAUUSD_{tf}.csv"),
            )
        return data_dir

    def test_the_bridge_push_reaches_the_session_pull(self):
        data_dir = self._write_local(self.now)
        self.assertTrue(mt5_export.push_data_branch(self.local, data_dir, "candles"))

        self.assertTrue(pull_data_branch(self.cloud, DATA_BRANCH, "data"))
        pulled = os.path.join(self.cloud, "data")
        self.assertTrue(os.path.exists(os.path.join(pulled, "XAUUSD_h1.csv")))
        self.assertTrue(os.path.exists(os.path.join(pulled, "XAUUSD_m15.csv")))

        rows = describe_data_dir(pulled, now=self.now)
        self.assertEqual({r["timeframe"] for r in rows}, {"h1", "m15"})
        self.assertTrue(all(r["bars"] == 40 for r in rows))
        self.assertTrue(all(r["age_min"] < 1 for r in rows))

    def test_the_bridge_leaves_the_working_tree_untouched(self):
        # The bridge runs on a schedule on your machine; it must never disturb
        # the branch you are on or the edits you have in flight.
        data_dir = self._write_local(self.now)
        with open(os.path.join(self.local, "WIP.txt"), "w") as fh:
            fh.write("uncommitted work")
        before_head = run("git", "-C", self.local, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        before_status = run("git", "-C", self.local, "status", "--porcelain").stdout

        mt5_export.push_data_branch(self.local, data_dir, "candles")

        after_head = run("git", "-C", self.local, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.assertEqual(before_head, "main")
        self.assertEqual(after_head, "main")
        self.assertEqual(before_status, run("git", "-C", self.local, "status", "--porcelain").stdout)
        with open(os.path.join(self.local, "WIP.txt")) as fh:
            self.assertEqual(fh.read(), "uncommitted work")

    def test_the_data_branch_carries_only_the_candles(self):
        data_dir = self._write_local(self.now)
        mt5_export.push_data_branch(self.local, data_dir, "candles")
        run("git", "-C", self.cloud, "fetch", "origin", DATA_BRANCH)
        listing = run(
            "git", "-C", self.cloud, "ls-tree", "-r", "--name-only", f"origin/{DATA_BRANCH}"
        ).stdout.split()
        self.assertTrue(listing)
        self.assertTrue(all(name.startswith("data/") for name in listing), listing)
        self.assertNotIn("README.md", listing)

    def test_an_unchanged_export_produces_no_commit(self):
        data_dir = self._write_local(self.now)
        mt5_export.push_data_branch(self.local, data_dir, "first")
        before = run(
            "git", "-C", self.local, "rev-list", "--count", f"origin/{DATA_BRANCH}"
        ).stdout.strip()
        # Same candles again: nothing should be committed.
        self._write_local(self.now)
        self.assertFalse(mt5_export.push_data_branch(self.local, data_dir, "second"))
        after = run(
            "git", "-C", self.local, "rev-list", "--count", f"origin/{DATA_BRANCH}"
        ).stdout.strip()
        self.assertEqual(before, after)

    def test_a_later_bar_propagates_on_the_next_pull(self):
        data_dir = self._write_local(self.now)
        mt5_export.push_data_branch(self.local, data_dir, "first")
        pull_data_branch(self.cloud, DATA_BRANCH, "data")

        later = self.now + timedelta(hours=3)
        self._write_local(later)
        self.assertTrue(mt5_export.push_data_branch(self.local, data_dir, "second"))

        self.assertTrue(pull_data_branch(self.cloud, DATA_BRANCH, "data"))
        rows = describe_data_dir(os.path.join(self.cloud, "data"), now=later)
        self.assertTrue(all(r["age_min"] < 1 for r in rows))

    def test_a_same_size_update_is_still_detected_as_a_change(self):
        # Content hashes, not file sizes: a new bar often has the same byte count.
        data_dir = self._write_local(self.now)
        mt5_export.push_data_branch(self.local, data_dir, "first")
        pull_data_branch(self.cloud, DATA_BRANCH, "data")
        sizes_before = {
            n: os.path.getsize(os.path.join(self.cloud, "data", n))
            for n in os.listdir(os.path.join(self.cloud, "data"))
        }

        self._write_local(self.now + timedelta(hours=1))
        mt5_export.push_data_branch(self.local, data_dir, "second")
        self.assertTrue(pull_data_branch(self.cloud, DATA_BRANCH, "data"))
        sizes_after = {
            n: os.path.getsize(os.path.join(self.cloud, "data", n))
            for n in os.listdir(os.path.join(self.cloud, "data"))
        }
        self.assertEqual(sizes_before, sizes_after)

    def test_pulled_candles_feed_the_pipeline_unchanged(self):
        from gold_trader.feed import CsvFeed
        data_dir = self._write_local(self.now)
        mt5_export.push_data_branch(self.local, data_dir, "candles")
        pull_data_branch(self.cloud, DATA_BRANCH, "data")

        snapshot = CsvFeed(os.path.join(self.cloud, "data")).snapshot(("h1", "m15"))
        self.assertAlmostEqual(snapshot.staleness_min(self.now), 0.0, places=3)
        self.assertEqual(len(snapshot.series["h1"]), 40)

    def test_the_bridge_works_from_a_repo_holding_no_project_files(self):
        """The Windows kit ships only the script -- no clone of the project.

        SETUP.bat does `git init` plus `git remote add` and nothing else, so the
        bridge must push from a folder that contains the script, a data
        directory and a .git, and nothing more. If this ever stops being true
        the zip stops working.
        """
        root = os.path.join(self.tmp.name, "minimal")
        run("git", "init", "-q", root)
        run("git", "-C", root, "remote", "add", "origin", self.origin)
        run("git", "-C", root, "config", "user.email", "test@example.com")
        run("git", "-C", root, "config", "user.name", "Test")

        data_dir = os.path.join(root, "data")
        for tf, step in (("h1", 60), ("m15", 15)):
            mt5_export.write_csv(
                bars(30, self.now, step_min=step),
                os.path.join(data_dir, f"XAUUSD_{tf}.csv"),
            )
        # The only things in the folder are .git and data/.
        self.assertEqual(
            sorted(n for n in os.listdir(root) if n != ".git"), ["data"]
        )

        self.assertTrue(mt5_export.push_data_branch(root, data_dir, "from a minimal repo"))
        self.assertTrue(pull_data_branch(self.cloud, DATA_BRANCH, "data"))
        rows = describe_data_dir(os.path.join(self.cloud, "data"), now=self.now)
        self.assertEqual({r["timeframe"] for r in rows}, {"h1", "m15"})

    def test_a_missing_branch_reports_rather_than_crashing(self):
        with self.assertRaises(RuntimeError):
            pull_data_branch(self.cloud, "no-such-branch", "data")

    def test_describe_ignores_unrelated_files(self):
        data_dir = os.path.join(self.local, "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "notes.txt"), "w") as fh:
            fh.write("hello")
        mt5_export.write_csv(bars(5, self.now), os.path.join(data_dir, "XAUUSD_h1.csv"))
        rows = describe_data_dir(data_dir, now=self.now)
        self.assertEqual([r["timeframe"] for r in rows], ["h1"])


if __name__ == "__main__":
    unittest.main()


class PerTimeframeFreshness(unittest.TestCase):
    """A bar cannot be fresher than its own interval. Judging every timeframe
    against one flat threshold made h4 read STALE for roughly two thirds of its
    normal life -- and a reader who sees that nightly stops believing the word."""

    def test_each_timeframe_gets_its_own_limit(self):
        from gold_trader.sync import STALENESS_GRACE_MIN, expected_age_min

        self.assertEqual(expected_age_min("m15"), 15 + STALENESS_GRACE_MIN)
        self.assertEqual(expected_age_min("h1"), 60 + STALENESS_GRACE_MIN)
        self.assertEqual(expected_age_min("h4"), 240 + STALENESS_GRACE_MIN)

    def test_the_limit_is_case_insensitive(self):
        from gold_trader.sync import expected_age_min

        self.assertEqual(expected_age_min("H4"), expected_age_min("h4"))

    def test_an_unknown_timeframe_is_judged_strictly_not_waved_through(self):
        # Better to question an unrecognised series than to assume it is fine.
        from gold_trader.sync import STALENESS_GRACE_MIN, expected_age_min

        self.assertEqual(expected_age_min("w1"), STALENESS_GRACE_MIN)

    def test_a_two_hour_old_h4_bar_is_not_stale(self):
        # The exact false positive: 114 minutes read STALE under the flat rule.
        rows = self._describe({"h4": 120, "m15": 10})
        self.assertFalse(self._row(rows, "h4")["stale"])

    def test_an_h4_bar_past_its_own_cadence_is_stale(self):
        rows = self._describe({"h4": 300})
        self.assertTrue(self._row(rows, "h4")["stale"])

    def test_an_m15_bar_at_ninety_minutes_is_stale_though_the_old_rule_allowed_it(self):
        # The flat 90-minute rule cut both ways: it was too lax for m15.
        rows = self._describe({"m15": 90})
        self.assertTrue(self._row(rows, "m15")["stale"])

    def _row(self, rows, timeframe):
        return next(r for r in rows if r["timeframe"] == timeframe)

    def _describe(self, ages_min):
        """Write CSVs whose newest bar is N minutes old, then describe them."""
        import csv as _csv
        import os as _os
        import tempfile as _tempfile
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        from gold_trader.sync import describe_data_dir

        now = _dt(2026, 9, 17, 22, 54, tzinfo=_tz.utc)
        tmp = _tempfile.mkdtemp()
        for timeframe, age in ages_min.items():
            path = _os.path.join(tmp, f"XAUUSD_{timeframe}.csv")
            with open(path, "w", newline="") as fh:
                writer = _csv.writer(fh)
                writer.writerow(["time", "open", "high", "low", "close", "volume"])
                writer.writerow([(now - _td(minutes=age)).isoformat(),
                                 1, 2, 0.5, 1.5, 10])
        return describe_data_dir(tmp, now)


class TheExitCodeMustNotWaitForTheSlowestSeries(unittest.TestCase):
    """`pull-data` gates the whole scheduled run: the Routine stops at step 3
    on a non-zero exit and never calls a model. It used to exit non-zero only
    when EVERY series was behind, which sounds conservative and is the exact
    opposite.

    Each series is judged against its own cadence, so on a dead feed m15 goes
    stale after 45 minutes, h1 after 90 and h4 after 270. Requiring all three
    to agree means the gate can never fire sooner than the slowest one -- four
    and a half hours after the bridge stopped.

    It cost a run on 2026-09-18: m15 87 minutes old against a 45 minute
    allowance, STALE printed, exit 0, and the pipeline spent $0.18 reasoning
    about hour-and-a-half-old candles. The risk manager stood aside and caught
    it, which is the last line of defence doing the first one's job.
    """

    OPEN = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)      # Thursday, London/NY
    CLOSED = datetime(2026, 9, 19, 23, 0, tzinfo=timezone.utc)    # Friday night

    def test_one_stale_series_fails_the_gate(self):
        code, err = self._pull({"m15": 90, "h1": 30, "h4": 60}, now=self.OPEN)
        self.assertEqual(code, 3)
        self.assertIn("m15", err)

    def test_the_fresh_series_are_not_reported_as_the_problem(self):
        # The per-row listing names every series; the diagnosis must name only
        # the ones actually behind, or the reader cannot tell what to chase.
        _, text = self._pull({"m15": 90, "h1": 30, "h4": 60}, now=self.OPEN)
        diagnosis = text.split("behind its own cadence")[0].rsplit("\n", 1)[-1]
        self.assertEqual(diagnosis.strip(), "m15")

    def test_all_series_fresh_passes(self):
        code, _ = self._pull({"m15": 10, "h1": 30, "h4": 120}, now=self.OPEN)
        self.assertEqual(code, 0)

    def test_every_series_stale_still_fails(self):
        # The old condition was not wrong, only far too narrow.
        code, _ = self._pull({"m15": 300, "h1": 300, "h4": 400}, now=self.OPEN)
        self.assertEqual(code, 3)

    def test_staleness_while_the_market_is_shut_is_not_a_failure(self):
        # Gold stops printing bars at the close. Failing here would stop a run
        # every weekday evening and all weekend, and an alarm that fires
        # nightly is one nobody reads by Friday.
        code, out = self._pull({"m15": 300, "h1": 300, "h4": 400}, now=self.CLOSED)
        self.assertEqual(code, 0)
        self.assertIn("market is closed", out)

    def test_the_closed_message_says_which_series_and_why(self):
        _, out = self._pull({"m15": 300}, now=self.CLOSED)
        self.assertIn("m15", out)
        self.assertIn("expected", out)

    def test_the_open_message_points_at_the_bridge_not_the_market(self):
        # The remedy is on the Windows PC. Saying "stale data" without saying
        # where to look is the report that wastes the evening.
        _, err = self._pull({"m15": 90}, now=self.OPEN)
        self.assertIn("bridge", err)
        self.assertIn("MetaTrader", err)

    def _pull(self, ages_min, now):
        """Drive cmd_pull_data over a real data directory, capturing both streams."""
        import argparse
        import io
        import contextlib
        from unittest import mock

        from gold_trader import cli

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = os.path.join(tmp.name, "data")
        os.makedirs(data_dir)
        step = {"m15": 15, "h1": 60, "h4": 240}
        for timeframe, age in ages_min.items():
            last = now - timedelta(minutes=age)
            mt5_export.write_csv(bars(5, last, step_min=step[timeframe]),
                                 os.path.join(data_dir, f"XAUUSD_{timeframe}.csv"))

        args = argparse.Namespace(repo=".", branch=DATA_BRANCH, data_dir=data_dir,
                                  max_age_min=None)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "pull_data_branch", return_value=False), \
             mock.patch.object(cli, "describe_data_dir",
                               side_effect=lambda d, **kw: describe_data_dir(d, now=now)), \
             mock.patch.object(cli, "datetime", _FrozenClock(now)), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.cmd_pull_data(args)
        return code, out.getvalue() + err.getvalue()


class _FrozenClock:
    """Only what cmd_pull_data asks of datetime: now(tz)."""

    def __init__(self, moment):
        self._moment = moment

    def now(self, tz=None):
        return self._moment


class ThePullMustNotTouchTheIndex(unittest.TestCase):
    """`data/` is owned by the data branch and must never be tracked here.

    The pull used `git checkout origin/<branch> -- data/`, and that form of
    checkout updates the index as well as the working tree -- by definition,
    not by accident. So every pull re-added the candles to the index, they
    became tracked on the working branch, and `.gitignore` was powerless:
    gitignore has no say over a path already in the index.

    `data/` was untracked on 2026-09-17, came back, was untracked again on
    2026-09-18, and came back inside the same hour. Neither time was somebody
    forgetting to untrack it. The pull put it back, and would have kept putting
    it back forever.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        run("git", "init", "--bare", "-b", "main", self.origin)

        seed = init_clone(self.origin, os.path.join(root, "seed"))
        with open(os.path.join(seed, "README.md"), "w") as fh:
            fh.write("project\n")
        with open(os.path.join(seed, ".gitignore"), "w") as fh:
            fh.write("data/\n")
        run("git", "-C", seed, "add", "-A")
        run("git", "-C", seed, "commit", "-m", "seed")
        run("git", "-C", seed, "push", "origin", "main")

        # A data branch carrying only candles, as the bridge builds it.
        data = init_clone(self.origin, os.path.join(root, "data"))
        run("git", "-C", data, "checkout", "--orphan", DATA_BRANCH)
        run("git", "-C", data, "rm", "-rf", "--quiet", ".")
        os.makedirs(os.path.join(data, "data"))
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        mt5_export.write_csv(bars(5, self.now),
                             os.path.join(data, "data", "XAUUSD_h1.csv"))
        run("git", "-C", data, "add", "-A")
        run("git", "-C", data, "commit", "-m", "candles")
        run("git", "-C", data, "push", "origin", DATA_BRANCH)

        self.work = init_clone(self.origin, os.path.join(root, "work"))

    def test_a_pull_leaves_the_candles_untracked(self):
        pull_data_branch(self.work, DATA_BRANCH, "data")
        self.assertEqual(self._tracked_data(), [])

    def test_the_candles_still_arrive_in_the_working_tree(self):
        # The index must stay clean, but the files are the point of the pull.
        pull_data_branch(self.work, DATA_BRANCH, "data")
        self.assertTrue(os.path.exists(
            os.path.join(self.work, "data", "XAUUSD_h1.csv")))

    def test_a_pull_leaves_nothing_staged(self):
        # Otherwise the next `git add -A` in a scheduled run commits whatever
        # candles that container happened to hold.
        pull_data_branch(self.work, DATA_BRANCH, "data")
        staged = run("git", "-C", self.work, "diff", "--cached", "--name-only")
        self.assertEqual(staged.stdout.strip(), "")

    def test_repeated_pulls_never_start_tracking_them(self):
        for _ in range(3):
            pull_data_branch(self.work, DATA_BRANCH, "data")
        self.assertEqual(self._tracked_data(), [])

    def test_an_updated_candle_still_propagates(self):
        # The fix must not cost the pull its actual job.
        pull_data_branch(self.work, DATA_BRANCH, "data")
        data = init_clone(self.origin, os.path.join(self.tmp.name, "data2"))
        run("git", "-C", data, "checkout", DATA_BRANCH)
        later = self.now + timedelta(hours=1)
        mt5_export.write_csv(bars(6, later),
                             os.path.join(data, "data", "XAUUSD_h1.csv"))
        run("git", "-C", data, "add", "-A")
        run("git", "-C", data, "commit", "-m", "later bar")
        run("git", "-C", data, "push", "origin", DATA_BRANCH)

        self.assertTrue(pull_data_branch(self.work, DATA_BRANCH, "data"))
        rows = describe_data_dir(os.path.join(self.work, "data"), now=later)
        self.assertEqual(rows[0]["bars"], 6)
        self.assertEqual(self._tracked_data(), [])

    def _tracked_data(self):
        listed = run("git", "-C", self.work, "ls-files", "data/")
        return [line for line in listed.stdout.splitlines() if line.strip()]
