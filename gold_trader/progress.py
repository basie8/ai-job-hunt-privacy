"""Task audit that verifies its own claims.

A roadmap where status is whatever the last editor typed is a wish list. Every
row here carries a machine-checkable ``verify`` predicate, and ``audit()``
re-evaluates it against the actual repository. A row marked ``done`` whose
predicate fails is reported as ``STALE`` -- which is the whole point, because
that is the failure mode a progress doc normally hides.

Predicates
----------
``file:<path>``           the path exists
``files:<a>,<b>``         every path exists
``tests:<dir>:<n>``       at least n tests pass under that directory
``journal:<n>``           at least n closed trades in the journal
``data:<minutes>``        candles on disk newer than that many minutes
``learning:active``       the learning state has left warm-up
``routine``               a scheduled Routine exists (human-confirmed)
``manual``                only a human can confirm this
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DONE = "done"
IN_PROGRESS = "in_progress"
OUTSTANDING = "outstanding"
BLOCKED = "blocked"

VALID_STATUS = (DONE, IN_PROGRESS, OUTSTANDING, BLOCKED)

VERDICT_OK = "OK"
VERDICT_STALE = "STALE"
VERDICT_UNVERIFIED = "UNVERIFIED"
VERDICT_PENDING = "PENDING"


@dataclass
class Task:
    id: str
    title: str
    status: str
    verify: str
    notes: str = ""
    verdict: str = VERDICT_UNVERIFIED
    detail: str = ""

    @property
    def complete(self) -> bool:
        return self.status == DONE and self.verdict == VERDICT_OK

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "verify": self.verify,
            "verdict": self.verdict,
            "detail": self.detail,
            "notes": self.notes,
        }


ROW = re.compile(r"^\|\s*([A-Z]{2,4}-\d{2})\s*\|(.+)$")


def parse_roadmap(path: str) -> List[Task]:
    """Read the roadmap's task tables. Non-table prose is ignored."""
    tasks: List[Task] = []
    if not os.path.exists(path):
        return tasks
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            match = ROW.match(line.strip())
            if not match:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                continue
            task_id, title, status, verify = cells[0], cells[1], cells[2].lower(), cells[3]
            if status not in VALID_STATUS:
                status = OUTSTANDING
            tasks.append(
                Task(
                    id=task_id,
                    title=title,
                    status=status,
                    verify=verify.strip("`"),
                    notes=cells[4] if len(cells) > 4 else "",
                )
            )
    return tasks


#: Set in the child process so a `tests:` predicate evaluated from inside a test
#: run cannot re-enter the suite that is evaluating it. Without this, auditing a
#: roadmap that references its own test suite forks until the box falls over.
_GUARD = "GOLD_TRADER_AUDIT_RUNNING"


def _count_tests(repo: str, directory: str) -> Optional[int]:
    if os.environ.get(_GUARD):
        return None
    env = dict(os.environ, **{_GUARD: "1"})
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", directory, "-t", "."],
        cwd=repo, capture_output=True, text=True, env=env, timeout=600,
    )
    match = re.search(r"^Ran (\d+) tests?", result.stderr or "", re.MULTILINE)
    if not match:
        return None
    return int(match.group(1)) if result.returncode == 0 else -int(match.group(1))


def _closed_trades(repo: str) -> int:
    try:
        sys.path.insert(0, repo)
        from gold_trader.journal import Journal

        return len(Journal(os.path.join(repo, "gold_trader/state/journal.jsonl")).closed())
    except Exception:
        return 0


def verify(task: Task, repo: str = ".", run_tests: bool = True) -> Task:
    """Re-evaluate one task's predicate against the repository.

    ``run_tests=False`` skips ``tests:`` predicates, which spawn real suite runs.
    Those rows then report as unverified rather than as failures.
    """
    predicate = task.verify
    expected_done = task.status == DONE

    def settle(ok: bool, detail: str) -> Task:
        if not expected_done:
            task.verdict = VERDICT_PENDING
        else:
            task.verdict = VERDICT_OK if ok else VERDICT_STALE
        task.detail = detail
        return task

    if predicate in ("manual", "routine"):
        task.verdict = VERDICT_UNVERIFIED if expected_done else VERDICT_PENDING
        task.detail = "needs human confirmation"
        return task

    if predicate.startswith("file:") or predicate.startswith("files:"):
        paths = predicate.split(":", 1)[1].split(",")
        missing = [p for p in paths if not os.path.exists(os.path.join(repo, p.strip()))]
        return settle(not missing, "present" if not missing else f"missing {missing}")

    if predicate.startswith("tests:"):
        _, directory, minimum = predicate.split(":")
        if not run_tests or os.environ.get(_GUARD):
            task.verdict = VERDICT_UNVERIFIED if expected_done else VERDICT_PENDING
            task.detail = "suite not run"
            return task
        count = _count_tests(repo, directory)
        if count is None:
            task.verdict = VERDICT_UNVERIFIED if expected_done else VERDICT_PENDING
            task.detail = "suite not run (nested audit)"
            return task
        if count < 0:
            return settle(False, f"{-count} tests ran, suite FAILED")
        return settle(count >= int(minimum), f"{count} tests pass (need {minimum})")

    if predicate.startswith("journal:"):
        minimum = int(predicate.split(":", 1)[1])
        count = _closed_trades(repo)
        return settle(count >= minimum, f"{count} closed trades (need {minimum})")

    if predicate.startswith("data:"):
        max_age = float(predicate.split(":", 1)[1])
        try:
            from .sync import describe_data_dir

            rows = describe_data_dir(os.path.join(repo, "data"))
        except Exception as exc:  # noqa: BLE001
            return settle(False, f"could not read data/: {exc}")
        if not rows:
            return settle(False, "no candles in data/ — the bridge has not delivered")
        freshest = min(r["age_min"] for r in rows)
        # Candle age cannot be judged while the market is shut. Gold closes for
        # an hour each weekday evening and all weekend, and during those windows
        # a perfectly healthy bridge delivers nothing -- there is nothing to
        # deliver. Judging age against the wall clock anyway would mark this row
        # a stale claim every weekend and every evening: a false alarm on a
        # schedule, which is how a real alert gets learned into background noise.
        #
        # A bridge that dies while the market is closed is genuinely undetectable
        # until it reopens, because no new candle is expected either way. The
        # first run after the reopen catches it.
        from datetime import datetime, timezone

        from .sessions import market_closed

        closure = market_closed(datetime.now(timezone.utc))
        if closure:
            return settle(
                True,
                f"{len(rows)} series, newest bar {freshest:.0f}min old; "
                f"market closed ({closure.replace('_', ' ')}), so age is not judged",
            )
        return settle(
            freshest <= max_age,
            f"{len(rows)} series, newest bar {freshest:.0f}min old (limit {max_age:.0f})",
        )

    if predicate == "learning:active":
        count = _closed_trades(repo)
        return settle(count >= 20, f"{count} closed trades (need 20 to leave warm-up)")

    return settle(False, f"unknown predicate {predicate!r}")


@dataclass
class Audit:
    tasks: List[Task] = field(default_factory=list)

    @property
    def done(self) -> List[Task]:
        return [t for t in self.tasks if t.complete]

    @property
    def stale(self) -> List[Task]:
        return [t for t in self.tasks if t.verdict == VERDICT_STALE]

    @property
    def outstanding(self) -> List[Task]:
        return [t for t in self.tasks if t.status in (OUTSTANDING, IN_PROGRESS, BLOCKED)]

    @property
    def blocked(self) -> List[Task]:
        return [t for t in self.tasks if t.status == BLOCKED]

    @property
    def unverified(self) -> List[Task]:
        """Claimed done but no machine check exists. Never let these go unseen."""
        return [t for t in self.tasks if t.status == DONE and t.verdict == VERDICT_UNVERIFIED]

    def accounted_for(self) -> bool:
        """Every task must appear in exactly one bucket of the report."""
        seen = {t.id for t in self.done + self.stale + self.outstanding + self.unverified}
        return seen == {t.id for t in self.tasks}

    def summary(self) -> Dict[str, object]:
        return {
            "total": len(self.tasks),
            "done": len(self.done),
            "outstanding": len(self.outstanding),
            "blocked": len(self.blocked),
            "stale_claims": len(self.stale),
            "unverified": len(self.unverified),
            "percent_complete": round(100 * len(self.done) / len(self.tasks), 1)
            if self.tasks
            else 0.0,
        }

    def render(self) -> str:
        s = self.summary()
        lines = [
            f"Roadmap audit: {s['done']}/{s['total']} verified complete "
            f"({s['percent_complete']}%), {s['outstanding']} outstanding, "
            f"{s['blocked']} blocked, {s['stale_claims']} stale claims, "
            f"{s['unverified']} unverified",
            "",
        ]
        if self.stale:
            lines.append("STALE CLAIMS - marked done but the check fails:")
            for t in self.stale:
                lines.append(f"  {t.id}  {t.title}  ({t.detail})")
            lines.append("")
        if self.blocked:
            lines.append("BLOCKED:")
            for t in self.blocked:
                lines.append(f"  {t.id}  {t.title}  - {t.notes}")
            lines.append("")
        pending = [t for t in self.outstanding if t.status != BLOCKED]
        if pending:
            lines.append("OUTSTANDING:")
            for t in pending:
                marker = "~" if t.status == IN_PROGRESS else " "
                lines.append(f" {marker}{t.id}  {t.title}  ({t.detail or t.verify})")
            lines.append("")
        if self.unverified:
            lines.append("DONE BUT UNVERIFIABLE - no machine check exists, confirm by hand:")
            for t in self.unverified:
                lines.append(f"  {t.id}  {t.title}  - {t.notes}")
            lines.append("")
        lines.append("COMPLETE:")
        for t in self.done:
            lines.append(f"  {t.id}  {t.title}  ({t.detail})")
        return "\n".join(lines)


def audit(roadmap_path: str, repo: str = ".", run_tests: bool = True) -> Audit:
    return Audit(tasks=[verify(t, repo, run_tests) for t in parse_roadmap(roadmap_path)])
