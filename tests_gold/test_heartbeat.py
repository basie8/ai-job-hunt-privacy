"""A run that dies before doing anything leaves no commit, no alert and no
trace. These pin the detector that notices."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.heartbeat import (
    AUDIT_SCHEDULE, GRACE_MIN, SIGNAL_SCHEDULE, Schedule, audit_all, audit_runs, load, record,
)

# A Thursday, chosen so weekday/weekend behaviour is exercisable either way.
NOW = datetime(2026, 9, 17, 19, 0, tzinfo=timezone.utc)


def at(day, hour, minute=23):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


class ScheduleExpansion(unittest.TestCase):
    def test_the_signal_cadence_matches_the_routine(self):
        # cron: 23 7-19/2 * * 1-5. The 21:23 slot was removed on 2026-09-17:
        # it fell inside gold's daily rollover break, so it could never produce
        # a tradeable signal and would have reported a false gap every evening.
        self.assertEqual(list(SIGNAL_SCHEDULE.hours), [7, 9, 11, 13, 15, 17, 19])
        self.assertEqual(SIGNAL_SCHEDULE.minute, 23)
        self.assertEqual(tuple(SIGNAL_SCHEDULE.weekdays), (0, 1, 2, 3, 4))

    def test_the_audit_cadence_matches_the_routine(self):
        # cron: 41 6 * * *. The 18:41 slot was dropped on 2026-09-22 -- the
        # audit went to once a day, so a second firing would now report a gap
        # for a run the Routine no longer makes.
        self.assertEqual(list(AUDIT_SCHEDULE.hours), [6])
        self.assertEqual(AUDIT_SCHEDULE.minute, 41)
        self.assertEqual(len(AUDIT_SCHEDULE.weekdays), 7)

    def test_a_full_weekday_expands_to_every_slot(self):
        moments = SIGNAL_SCHEDULE.expected_between(at(17, 0, 0), at(17, 23, 59))
        self.assertEqual([m.hour for m in moments], [7, 9, 11, 13, 15, 17, 19])

    def test_the_weekend_is_not_expected_to_run(self):
        # 19 Sep 2026 is a Saturday.
        self.assertEqual(SIGNAL_SCHEDULE.expected_between(at(19, 0, 0), at(20, 23, 59)), [])

    def test_the_audit_runs_at_the_weekend(self):
        self.assertEqual(len(AUDIT_SCHEDULE.expected_between(at(19, 0, 0), at(19, 23, 59))), 1)

    def test_a_day_expects_exactly_one_audit(self):
        # The window the audit itself checks is 26 hours, which straddles two
        # daily slots. Both must be expected, or a healthy pair reads as a gap.
        moments = AUDIT_SCHEDULE.expected_between(at(17, 4, 30), at(18, 6, 45))
        self.assertEqual([(m.day, m.hour) for m in moments], [(17, 6), (18, 6)])

    def test_the_window_is_half_open_so_a_boundary_is_not_double_counted(self):
        exact = at(17, 9)
        self.assertNotIn(exact, SIGNAL_SCHEDULE.expected_between(exact, at(17, 10)))
        self.assertIn(exact, SIGNAL_SCHEDULE.expected_between(at(17, 8), exact))

    def test_an_inverted_window_is_empty_rather_than_an_error(self):
        self.assertEqual(SIGNAL_SCHEDULE.expected_between(at(17, 12), at(17, 6)), [])


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state", "heartbeat.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_beat_round_trips(self):
        record(self.path, "signal", "no_trade", "analyst flat", now=NOW)
        beats = load(self.path)
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0].outcome, "no_trade")
        self.assertEqual(beats[0].detail, "analyst flat")

    def test_recording_creates_the_directory(self):
        record(self.path, "signal", "no_trade", now=NOW)
        self.assertTrue(os.path.exists(self.path))

    def test_an_unknown_outcome_is_refused(self):
        # Otherwise a typo becomes a category nobody ever queries.
        with self.assertRaises(ValueError):
            record(self.path, "signal", "fine", now=NOW)

    def test_an_unknown_routine_is_refused(self):
        with self.assertRaises(ValueError):
            record(self.path, "hourly", "no_trade", now=NOW)

    def test_a_corrupt_line_does_not_lose_the_rest(self):
        record(self.path, "signal", "no_trade", now=NOW)
        with open(self.path, "a") as fh:
            fh.write("{not json\n")
        record(self.path, "signal", "signal", now=NOW)
        self.assertEqual(len(load(self.path)), 2)

    def test_a_missing_file_reads_as_no_beats(self):
        self.assertEqual(load(os.path.join(self.tmp.name, "absent.jsonl")), [])

    def test_the_file_is_written_with_unix_line_endings(self):
        record(self.path, "signal", "no_trade", now=NOW)
        with open(self.path, "rb") as fh:
            self.assertNotIn(b"\r", fh.read())


class GapDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "heartbeat.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _beat(self, when, outcome="no_trade", routine="signal", detail=""):
        record(self.path, routine, outcome, detail, now=when)

    def test_nothing_recorded_means_not_armed_not_broken(self):
        # The detector cannot speak for a period it was not watching. Reporting
        # the whole pre-history as missed would fire a false alarm on the first
        # audit, which is how a real alert gets learned into background noise.
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertFalse(report.armed)
        self.assertEqual(report.missed, [])
        self.assertIn("not armed", report.render())

    def test_a_complete_day_reports_no_gaps(self):
        for hour in (7, 9, 11, 13, 15, 17):
            self._beat(at(17, hour, 25))
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertTrue(report.armed)
        self.assertEqual(report.missed, [])
        self.assertTrue(report.healthy())

    def test_one_missing_run_is_found_and_named(self):
        for hour in (7, 9, 11, 13, 17):   # 15:23 never ran
            self._beat(at(17, hour, 25))
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertEqual([m.hour for m in report.missed], [15])
        self.assertFalse(report.healthy())
        self.assertIn("MISSED", report.render())

    def test_the_usage_limit_case_is_exactly_this(self):
        # The defect that prompted the whole module: a run rejected for hitting
        # the account usage limit dies in seconds, writes nothing, and alerts
        # nobody. It is invisible except as an absence.
        self._beat(at(17, 15, 25))
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertEqual([m.hour for m in report.missed], [17])

    def test_a_run_still_inside_its_grace_period_is_not_yet_missed(self):
        self._beat(at(17, 15, 25))
        just_after = at(17, 17, 23) + timedelta(minutes=GRACE_MIN - 5)
        report = audit_runs(self.path, "signal", now=just_after)
        self.assertEqual(report.missed, [])

    def test_a_run_past_its_grace_period_is_missed(self):
        self._beat(at(17, 15, 25))
        well_after = at(17, 17, 23) + timedelta(minutes=GRACE_MIN + 5)
        report = audit_runs(self.path, "signal", now=well_after)
        self.assertEqual([m.hour for m in report.missed], [17])

    def test_a_late_run_inside_its_grace_window_still_counts(self):
        # Runs are staggered by a few minutes; that is not a failure.
        self._beat(at(17, 15, 23) + timedelta(minutes=GRACE_MIN - 1))
        report = audit_runs(self.path, "signal", now=at(17, 16, 0))
        self.assertEqual(report.missed, [])

    def test_runs_before_the_detector_existed_are_not_blamed(self):
        # Armed at 15:25; 07:23 through 13:23 predate it and cannot be judged.
        self._beat(at(17, 15, 25))
        self._beat(at(17, 17, 25))
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertEqual(report.missed, [])

    def test_an_errored_run_is_surfaced_even_though_it_was_recorded(self):
        self._beat(at(17, 15, 25))
        self._beat(at(17, 17, 25), outcome="error", detail="anthropic API 529")
        report = audit_runs(self.path, "signal", now=NOW)
        self.assertEqual(report.missed, [])
        self.assertEqual(len(report.errors), 1)
        self.assertIn("529", report.render())
        self.assertFalse(report.healthy())

    def test_a_quiet_run_and_a_missing_run_are_not_confused(self):
        # The whole point: "nothing to report" must not look like "never ran".
        self._beat(at(17, 15, 25), outcome="no_trade")
        quiet = audit_runs(self.path, "signal", now=at(17, 16, 0))
        self.assertTrue(quiet.healthy())
        self.assertEqual(quiet.to_dict()["outcomes"], {"no_trade": 1})

    def test_the_stale_data_path_still_records(self):
        # The signal Routine stops early when the bridge is stalled. That run
        # happened, and must not read as a platform failure.
        self._beat(at(17, 15, 25), outcome="stale_data", detail="newest bar 340min old")
        report = audit_runs(self.path, "signal", now=at(17, 16, 0))
        self.assertTrue(report.healthy())
        self.assertEqual(report.to_dict()["outcomes"], {"stale_data": 1})

    def test_the_two_routines_are_audited_independently(self):
        self._beat(at(17, 15, 25), routine="signal")
        # The next morning at 07:30: the audit's single 06:41 slot is past its
        # grace period, and so are the signal slots either side of the night.
        later = datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)
        reports = {r.routine: r for r in audit_all(self.path, now=later)}
        self.assertEqual(sorted(reports), ["audit", "signal"])
        # The audit routine has recorded nothing of its own, but the file is
        # armed, so its 06:41 slot is genuinely missing.
        self.assertEqual([(m.day, m.hour) for m in reports["audit"].missed], [(18, 6)])
        # The signal routine's own slots are missing too, reported apart.
        # 07:23 is absent from the list: at 07:30 it is still inside its grace
        # period, and a run is not late until the grace period has passed.
        self.assertEqual(
            [(m.day, m.hour) for m in reports["signal"].missed],
            [(17, 17), (17, 19)])

    def test_the_report_serialises_for_the_dashboard(self):
        self._beat(at(17, 15, 25))
        blob = json.dumps(audit_runs(self.path, "signal", now=NOW).to_dict())
        self.assertIn("missed", json.loads(blob))


class CoherenceWithTheRoutines(unittest.TestCase):
    """The schedules here are a restatement of the cron expressions on the live
    Routines. Nothing enforces that from inside the repo, so the restatement is
    documented and pinned rather than assumed."""

    def test_the_schedules_are_documented_where_they_can_be_checked(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "docs", "RUNTIME.md")) as fh:
            runtime = fh.read()
        self.assertIn("23 7-19/2 * * 1-5", runtime)
        self.assertIn("41 6 * * *", runtime)

    def test_the_documented_hours_are_checked_not_just_the_minute(self):
        # The coherence check compared minutes only until 2026-09-22, so a
        # cadence change -- the drift most likely to happen -- went unseen.
        from gold_trader.selfcheck import _cron_hours

        self.assertEqual(_cron_hours("6"), [6])
        self.assertEqual(_cron_hours("6,18"), [6, 18])
        self.assertEqual(_cron_hours("7-19/2"), [7, 9, 11, 13, 15, 17, 19])
        self.assertEqual(sorted(AUDIT_SCHEDULE.hours), _cron_hours("6"))
        self.assertEqual(sorted(SIGNAL_SCHEDULE.hours), _cron_hours("7-19/2"))

    def test_a_schedule_describes_itself_readably(self):
        described = Schedule(minute=5, hours=(9,)).describe()
        self.assertIn("09:05", described)


if __name__ == "__main__":
    unittest.main()


class StateIsCommittable(unittest.TestCase):
    """The heartbeat is only evidence once it is pushed. It was gitignored on
    the day it was written, along with the journal and the audit log, which
    made every `git add gold_trader/state/` in the scheduled runs a no-op."""

    def _repo(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_no_state_file_is_gitignored(self):
        import subprocess

        paths = [
            "gold_trader/state/journal.jsonl",
            "gold_trader/state/audit.jsonl",
            "gold_trader/state/heartbeat.jsonl",
            "gold_trader/state/calendar.json",
        ]
        result = subprocess.run(
            ["git", "-C", self._repo(), "check-ignore", "--no-index", *paths],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.stdout.strip(), "",
            "gitignored state cannot be committed, and a container that cannot "
            "commit its state starts every run from nothing",
        )

    def test_the_gitignore_says_why_the_exclusion_was_removed(self):
        # So nobody re-adds the pattern in good faith.
        with open(os.path.join(self._repo(), ".gitignore")) as fh:
            self.assertIn("durable state", fh.read())


class ErrorsThatLaterRunsFixed(unittest.TestCase):
    """An error a later run superseded is history, not a fault. Left standing
    it sits on the dashboard shouting about something already fixed, until it
    ages out of the window -- which is how a reader learns to scroll past red."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "heartbeat.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _beat(self, hour, outcome, detail=""):
        record(self.path, "signal", outcome, detail, now=at(17, hour, 25))

    def test_an_error_with_nothing_after_it_is_unresolved(self):
        self._beat(15, "error", "no credentials")
        report = audit_runs(self.path, "signal", now=at(17, 16, 0))
        self.assertEqual(len(report.unresolved_errors), 1)
        self.assertFalse(report.healthy())

    def test_a_later_successful_run_resolves_it(self):
        self._beat(15, "error", "no credentials")
        self._beat(17, "no_trade", "analyst flat")
        report = audit_runs(self.path, "signal", now=at(17, 18, 0))
        self.assertEqual(report.unresolved_errors, [])
        self.assertTrue(report.healthy())

    def test_the_error_is_still_in_the_record(self):
        # Resolved is not erased. The history stays queryable.
        self._beat(15, "error", "no credentials")
        self._beat(17, "no_trade")
        report = audit_runs(self.path, "signal", now=at(17, 18, 0))
        self.assertEqual(len(report.errors), 1)
        self.assertIn("a later run succeeded", report.render())

    def test_a_later_error_does_not_resolve_an_earlier_one(self):
        self._beat(15, "error", "first")
        self._beat(17, "error", "second")
        report = audit_runs(self.path, "signal", now=at(17, 18, 0))
        self.assertEqual(len(report.unresolved_errors), 2)

    def test_a_stale_data_run_counts_as_a_successful_run(self):
        # It is a legitimate outcome: the run happened and reported correctly.
        self._beat(15, "error", "no credentials")
        self._beat(17, "stale_data", "bridge quiet")
        report = audit_runs(self.path, "signal", now=at(17, 18, 0))
        self.assertTrue(report.healthy())

    def test_resolution_is_exposed_to_the_dashboard(self):
        self._beat(15, "error", "boom")
        self._beat(17, "no_trade")
        blob = audit_runs(self.path, "signal", now=at(17, 18, 0)).to_dict()
        self.assertEqual(blob["unresolved_errors"], [])
        self.assertEqual(len(blob["errors"]), 1)
