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
