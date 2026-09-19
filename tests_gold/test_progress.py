import os
import tempfile
import unittest

from gold_trader.progress import (
    VERDICT_OK, VERDICT_PENDING, VERDICT_STALE, VERDICT_UNVERIFIED, audit, parse_roadmap,
)

ROADMAP = """\
# Roadmap

Some prose that must be ignored.

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| INF-01 | A real file | done | `file:present.txt` | fine |
| INF-02 | A missing file | done | `file:absent.txt` | lying |
| INF-03 | Not started | outstanding | `file:absent.txt` | later |
| OPS-01 | Human only | done | `routine` | confirm by hand |
| LRN-01 | Needs trades | blocked | `journal:20` | waiting |
"""


class Parsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ROADMAP.md")
        with open(self.path, "w") as fh:
            fh.write(ROADMAP)
        open(os.path.join(self.tmp.name, "present.txt"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_task_rows_are_parsed(self):
        tasks = parse_roadmap(self.path)
        self.assertEqual([t.id for t in tasks], ["INF-01", "INF-02", "INF-03", "OPS-01", "LRN-01"])

    def test_a_missing_roadmap_yields_no_tasks(self):
        self.assertEqual(parse_roadmap("/nonexistent/ROADMAP.md"), [])

    def test_a_verified_claim_reads_ok(self):
        result = audit(self.path, self.tmp.name)
        task = next(t for t in result.tasks if t.id == "INF-01")
        self.assertEqual(task.verdict, VERDICT_OK)
        self.assertTrue(task.complete)

    def test_a_false_done_claim_is_reported_stale(self):
        # The whole reason this module exists.
        result = audit(self.path, self.tmp.name)
        task = next(t for t in result.tasks if t.id == "INF-02")
        self.assertEqual(task.verdict, VERDICT_STALE)
        self.assertFalse(task.complete)
        self.assertEqual([t.id for t in result.stale], ["INF-02"])

    def test_an_unstarted_task_is_pending_not_stale(self):
        result = audit(self.path, self.tmp.name)
        task = next(t for t in result.tasks if t.id == "INF-03")
        self.assertEqual(task.verdict, VERDICT_PENDING)
        self.assertIn(task, result.outstanding)

    def test_a_human_only_task_is_flagged_unverified(self):
        result = audit(self.path, self.tmp.name)
        task = next(t for t in result.tasks if t.id == "OPS-01")
        self.assertEqual(task.verdict, VERDICT_UNVERIFIED)
        self.assertIn(task, result.unverified)

    def test_every_task_appears_in_exactly_one_bucket(self):
        # A task that falls through every bucket is invisible in the report.
        result = audit(self.path, self.tmp.name)
        self.assertTrue(result.accounted_for())

    def test_the_rendered_report_names_every_task(self):
        rendered = audit(self.path, self.tmp.name).render()
        for task_id in ("INF-01", "INF-02", "INF-03", "OPS-01", "LRN-01"):
            self.assertIn(task_id, rendered)

    def test_the_summary_counts_add_up(self):
        summary = audit(self.path, self.tmp.name).summary()
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["stale_claims"], 1)
        self.assertEqual(summary["unverified"], 1)


class NoRecursion(unittest.TestCase):
    def test_a_tests_predicate_does_not_re_enter_the_suite(self):
        # The roadmap references this very suite. Without the guard, auditing it
        # from inside a test run forks until the machine falls over -- which is
        # exactly what happened the first time this module was written.
        from gold_trader.progress import _GUARD, Task, verify

        previous = os.environ.get(_GUARD)
        os.environ[_GUARD] = "1"
        try:
            task = verify(Task("TST-01", "suite", "done", "tests:tests_gold:1"), ".")
        finally:
            if previous is None:
                os.environ.pop(_GUARD, None)
            else:
                os.environ[_GUARD] = previous
        self.assertEqual(task.verdict, VERDICT_UNVERIFIED)
        self.assertIn("not run", task.detail)

    def test_run_tests_false_skips_the_suite_entirely(self):
        from gold_trader.progress import Task, verify

        task = verify(Task("TST-01", "suite", "done", "tests:tests_gold:1"), ".", run_tests=False)
        self.assertEqual(task.verdict, VERDICT_UNVERIFIED)


class RealRoadmap(unittest.TestCase):
    """Guards the project's own roadmap. run_tests=False keeps these cheap."""

    def _audit(self):
        repo = os.path.join(os.path.dirname(__file__), "..")
        return audit(os.path.join(repo, "docs/ROADMAP.md"), repo, run_tests=False)

    def test_the_projects_own_roadmap_parses_and_accounts_for_everything(self):
        result = self._audit()
        self.assertGreater(len(result.tasks), 10)
        self.assertTrue(result.accounted_for())

    def test_the_projects_own_roadmap_has_no_stale_claims(self):
        """If this fails, the roadmap claims something that is not true.

        Rows verified by `data:` are excluded. Their freshness depends on a PC
        in another country being awake, so asserting on them here makes the
        suite fail whenever the bridge is off -- which it legitimately is every
        night and all weekend. The suite is meant to be offline and
        deterministic; a test that goes red because someone closed a laptop is
        neither, and would train us to ignore a red suite.

        The freshness of those rows is still checked, by `gold_trader progress`
        against live data, where a stale bridge is a finding rather than a test
        failure.
        """
        stale = [t.id for t in self._audit().stale if not t.verify.startswith("data:")]
        self.assertEqual(stale, [])

    def test_the_critical_path_task_is_machine_verified(self):
        # DAT-04 (the bridge delivering candles) is what everything waited on.
        # It went green on 2026-09-17 when real candles arrived. The guard now
        # is that it can never be marked done on a human's say-so: its predicate
        # must actually test the thing the row claims.
        task = next(t for t in self._audit().tasks if t.id == "DAT-04")
        self.assertNotIn(task.verify, ("manual", "routine"),
                         "the critical path must not be self-certified")
        self.assertTrue(task.verify.startswith("data:"),
                        f"DAT-04 should verify candle freshness, not {task.verify!r}")

    def test_the_bridge_predicate_fails_when_candles_are_missing(self):
        # The predicate has to be able to fail, or it proves nothing.
        from gold_trader.progress import Task, verify
        with tempfile.TemporaryDirectory() as empty:
            task = verify(Task("DAT-04", "bridge", "done", "data:180"), empty)
            self.assertEqual(task.verdict, VERDICT_STALE)
            self.assertIn("has not delivered", task.detail)


if __name__ == "__main__":
    unittest.main()
