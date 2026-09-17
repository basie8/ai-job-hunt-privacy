"""Proof that a scheduled run happened, and detection of the ones that didn't.

A Routine run that dies before doing anything -- an account usage limit, a
container that never provisioned, an API outage -- produces no commit, no alert
and no trace. The dashboard ages slowly and nothing says why. That is the exact
failure mode this system is built to refuse, and it was live for a day before
anyone noticed.

So every run records that it ran, whatever its outcome, including the outcomes
that produce nothing else. A run that was never recorded is a run that failed
before reaching this code, and the gap between the schedule and the record is
the evidence.

Detection is deliberately repo-only. The Routines API knows *why* a run failed
and is worth consulting when it is reachable, but a detector that depends on it
would go blind in exactly the sessions where it matters. Expected-versus-recorded
needs nothing but a clock and a file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

HEARTBEAT_FILENAME = "heartbeat.jsonl"

#: Outcomes a signal run can legitimately end with. All of them are recorded --
#: a quiet run and a missing run must never look the same.
OUTCOMES = (
    "signal",        # an actionable paper signal was produced
    "no_trade",      # analyst flat, risk manager rejected, or a hard block
    "resolved",      # no new signal, but an open paper position closed
    "stale_data",    # the bridge is not delivering; the run stopped early
    "error",         # something failed unexpectedly, with the text recorded
)

#: A run is only counted as missed once it is this far past its scheduled time.
#: Runs are staggered by a few minutes and a run takes minutes to finish, so a
#: tighter window would report a run that is merely in progress.
GRACE_MIN = 25


@dataclass(frozen=True)
class Schedule:
    """The subset of cron the Routines actually use, stated explicitly.

    A general cron parser would be more code and less clear about what is
    scheduled. If a Routine's cadence changes, this changes with it -- and the
    coherence check exists so the two cannot drift apart silently.
    """

    minute: int
    hours: Sequence[int]
    #: Monday is 0, matching datetime.weekday().
    weekdays: Sequence[int] = (0, 1, 2, 3, 4)

    def expected_between(self, start: datetime, end: datetime) -> List[datetime]:
        """Every scheduled instant in (start, end]. Both must be UTC-aware."""
        if end <= start:
            return []
        out: List[datetime] = []
        day = start.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        last = end.astimezone(timezone.utc)
        while day <= last:
            if day.weekday() in self.weekdays:
                for hour in sorted(self.hours):
                    moment = day.replace(hour=hour, minute=self.minute)
                    if start < moment <= end:
                        out.append(moment)
            day += timedelta(days=1)
        return out

    def describe(self) -> str:
        hours = ", ".join(f"{h:02d}:{self.minute:02d}" for h in sorted(self.hours))
        days = "weekdays" if tuple(self.weekdays) == (0, 1, 2, 3, 4) else "daily"
        return f"{hours} UTC, {days}"


#: The signal Routine: every two hours, 07:23-19:23 UTC, Monday to Friday.
#: It used to end at 21:23, which lands inside gold's daily rollover break
#: (17:00-18:00 New York). A run there can produce nothing tradeable, and the
#: detector would have reported a missed run every single evening -- a false
#: alarm a day, which is how a real alert gets learned into background noise.
SIGNAL_SCHEDULE = Schedule(minute=23, hours=tuple(range(7, 20, 2)))

#: The audit Routine: 06:41 and 18:41 UTC, every day.
AUDIT_SCHEDULE = Schedule(minute=41, hours=(6, 18), weekdays=(0, 1, 2, 3, 4, 5, 6))

SCHEDULES: Dict[str, Schedule] = {"signal": SIGNAL_SCHEDULE, "audit": AUDIT_SCHEDULE}


@dataclass(frozen=True)
class Beat:
    ts: str
    routine: str
    outcome: str
    detail: str = ""

    def when(self) -> Optional[datetime]:
        try:
            stamped = datetime.fromisoformat(self.ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        return stamped if stamped.tzinfo else stamped.replace(tzinfo=timezone.utc)

    def to_dict(self) -> Dict[str, object]:
        return {"ts": self.ts, "routine": self.routine,
                "outcome": self.outcome, "detail": self.detail}


def record(path: str, routine: str, outcome: str, detail: str = "",
           now: Optional[datetime] = None) -> Beat:
    """Append one run to the record. Called by every run, on every path."""
    if routine not in SCHEDULES:
        raise ValueError(f"unknown routine {routine!r}; expected one of {sorted(SCHEDULES)}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {list(OUTCOMES)}")
    now = now or datetime.now(timezone.utc)
    beat = Beat(ts=now.isoformat(timespec="seconds"), routine=routine,
                outcome=outcome, detail=detail)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(beat.to_dict(), sort_keys=True) + "\n")
    return beat


def load(path: str) -> List[Beat]:
    """Read the record. A corrupt line is skipped, never fatal -- losing the
    detector because one line is malformed would be the worse failure."""
    if not os.path.exists(path):
        return []
    beats: List[Beat] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                blob = json.loads(line)
                beats.append(Beat(ts=str(blob["ts"]), routine=str(blob["routine"]),
                                  outcome=str(blob.get("outcome", "unknown")),
                                  detail=str(blob.get("detail", ""))))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return beats


@dataclass
class RunReport:
    routine: str
    schedule: Schedule
    window_start: datetime
    window_end: datetime
    recorded: List[Beat] = field(default_factory=list)
    missed: List[datetime] = field(default_factory=list)
    errors: List[Beat] = field(default_factory=list)
    #: When the detector started watching. Nothing before this can be judged --
    #: reporting the whole pre-history as missed would fire a false alarm on the
    #: first audit, which is how an alert gets learned into background noise.
    armed_at: Optional[datetime] = None

    @property
    def armed(self) -> bool:
        return self.armed_at is not None

    @property
    def expected(self) -> int:
        return len(self.recorded) + len(self.missed)

    def healthy(self) -> bool:
        """Unarmed is not healthy and not a failure: it is 'cannot say yet'."""
        return not self.missed and not self.errors

    def to_dict(self) -> Dict[str, object]:
        return {
            "routine": self.routine,
            "schedule": self.schedule.describe(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "armed": self.armed,
            "armed_at": self.armed_at.isoformat() if self.armed_at else None,
            "expected": self.expected,
            "recorded": len(self.recorded),
            "missed": [m.isoformat() for m in self.missed],
            "errors": [b.to_dict() for b in self.errors],
            "outcomes": _tally(self.recorded),
            "healthy": self.healthy(),
        }

    def render(self) -> str:
        lines = [f"{self.routine} ({self.schedule.describe()})"]
        lines.append(f"  window: {self.window_start:%Y-%m-%d %H:%M} to "
                     f"{self.window_end:%Y-%m-%d %H:%M} UTC")
        if not self.armed:
            lines.append("  not armed yet - no run has recorded a heartbeat, so nothing "
                         "can be said about the runs before now. The first recorded run "
                         "starts the clock.")
            return "\n".join(lines)
        lines.append(f"  {len(self.recorded)} of {self.expected} scheduled runs recorded")
        for outcome, count in sorted(_tally(self.recorded).items()):
            lines.append(f"    {outcome:<11} {count}")
        for moment in self.missed:
            lines.append(f"  MISSED  {moment:%Y-%m-%d %H:%M} UTC - "
                         "the run left no trace, so it died before reaching the pipeline")
        for beat in self.errors:
            lines.append(f"  ERROR   {beat.ts} - {beat.detail or '(no detail recorded)'}")
        if self.healthy():
            lines.append("  no gaps")
        return "\n".join(lines)


def _tally(beats: Sequence[Beat]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for beat in beats:
        out[beat.outcome] = out.get(beat.outcome, 0) + 1
    return out


def audit_runs(path: str, routine: str, hours: int = 26,
               now: Optional[datetime] = None) -> RunReport:
    """Compare what the schedule expected against what actually ran.

    The default window covers a full day plus the gap between audits, so two
    consecutive audits cannot leave a period unexamined.
    """
    now = now or datetime.now(timezone.utc)
    schedule = SCHEDULES[routine]
    start = now - timedelta(hours=hours)
    # A run scheduled moments ago may still be running. Only count one as
    # missed once the grace period has passed.
    cutoff = now - timedelta(minutes=GRACE_MIN)

    everything = load(path)
    all_stamps = [b.when() for b in everything if b.when()]
    # The detector is armed by the first heartbeat any routine records. Before
    # that it was not watching, and it says so rather than inventing failures.
    armed_at = min(all_stamps) if all_stamps else None

    beats = [b for b in everything if b.routine == routine]
    stamps = [b.when() for b in beats]
    recorded = [b for b, when in zip(beats, stamps) if when and start < when <= now]

    missed: List[datetime] = []
    if armed_at is not None:
        for moment in schedule.expected_between(max(start, armed_at), cutoff):
            window_end = moment + timedelta(minutes=GRACE_MIN)
            if not any(when and moment <= when <= window_end for when in stamps):
                missed.append(moment)

    return RunReport(
        routine=routine, schedule=schedule, window_start=start, window_end=now,
        recorded=recorded, missed=missed,
        errors=[b for b in recorded if b.outcome == "error"],
        armed_at=armed_at,
    )


def audit_all(path: str, hours: int = 26,
              now: Optional[datetime] = None) -> List[RunReport]:
    return [audit_runs(path, routine, hours, now) for routine in sorted(SCHEDULES)]
