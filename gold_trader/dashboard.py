"""Dashboard data export.

Collects everything the operations dashboard shows into one JSON document, with
one rule running through it: **nothing fails silently.**

Every section either carries data or carries an explicit error, and the two are
never confused. A section that could not be read reports `status: "error"` with
the exception text. A section that read fine but has nothing in it yet reports
`status: "empty"` with the reason. Those render differently on the page, because
"no trades yet, Phase 2 hasn't started" and "the journal is corrupt" look
identical as a zero and must never look identical to a human.

Collection itself is defensive for the same reason: one unreadable file must not
take down the whole export, or the dashboard would go dark exactly when something
is wrong.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

OK = "ok"
EMPTY = "empty"
ERROR = "error"

#: Terminal outcomes a run can reach, in funnel order. These are the investment
#: decision process made countable.
FUNNEL_STAGES = (
    ("runs", "Runs started"),
    ("analysed", "Analyst produced a read"),
    ("proposed", "Direction proposed (not flat)"),
    ("risk_passed", "Risk manager approved"),
    ("engine_passed", "Limit engine approved"),
    ("ordered", "Order intent issued"),
)


@dataclass
class Section:
    """One panel's worth of data, or the reason there isn't any."""

    status: str
    data: Any = None
    reason: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "data": self.data, "reason": self.reason, "source": self.source}


def _collect(source: str, fn: Callable[[], Section]) -> Section:
    """Run one collector; convert any unexpected failure into a visible error."""
    try:
        section = fn()
        section.source = section.source or source
        return section
    except Exception as exc:  # noqa: BLE001 - a dark dashboard is the worse failure
        return Section(
            status=ERROR,
            reason=f"{type(exc).__name__}: {exc}",
            source=source,
            data={"traceback": traceback.format_exc(limit=3)},
        )


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_tasks(repo: str) -> Section:
    from .progress import audit

    roadmap = os.path.join(repo, "docs/ROADMAP.md")
    if not os.path.exists(roadmap):
        return Section(EMPTY, reason="docs/ROADMAP.md is missing", source="docs/ROADMAP.md")

    result = audit(roadmap, repo, run_tests=True)
    if not result.tasks:
        return Section(EMPTY, reason="no task rows parsed from the roadmap", source="docs/ROADMAP.md")

    buckets = {
        "done": [t.to_dict() for t in result.done],
        "in_progress": [t.to_dict() for t in result.tasks if t.status == "in_progress"],
        "outstanding": [
            t.to_dict() for t in result.outstanding if t.status not in ("blocked", "in_progress")
        ],
        "blocked": [t.to_dict() for t in result.blocked],
        "stale": [t.to_dict() for t in result.stale],
        "unverified": [t.to_dict() for t in result.unverified],
    }
    return Section(
        OK,
        data={"summary": result.summary(), "buckets": buckets, "accounted_for": result.accounted_for()},
        source="docs/ROADMAP.md",
    )


def collect_selfcheck(repo: str) -> Section:
    from .selfcheck import run_all

    report = run_all(repo)
    return Section(
        OK,
        data={
            "total": len(report.results),
            "failed": len(report.failures),
            "warned": len(report.warnings),
            "results": [
                {"component": r.component, "check": r.check, "status": r.status, "detail": r.detail}
                for r in report.results
            ],
        },
        source="gold_trader/selfcheck.py",
    )


def collect_phase(repo: str) -> Section:
    """Parse the phase table out of the development plan."""
    path = os.path.join(repo, "docs/DEVELOPMENT_PLAN.md")
    if not os.path.exists(path):
        return Section(EMPTY, reason="docs/DEVELOPMENT_PLAN.md is missing", source=path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    phases = []
    for match in re.finditer(r"^\|\s*(\d)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$",
                             text, re.MULTILINE):
        number, name, gate, state = match.groups()
        state = state.strip()
        phases.append({
            "number": int(number),
            "name": name.strip(),
            "gate": gate.strip(),
            "complete": "✅" in state,
            "blocked": "🔴" in state,
            "waiting": "⏸" in state,
        })
    if not phases:
        return Section(EMPTY, reason="no phase rows parsed", source=path)

    current = next((p for p in phases if not p["complete"]), phases[-1])
    return Section(OK, data={"phases": phases, "current": current}, source=path)


def collect_trading(repo: str) -> Section:
    from .journal import Journal
    from .learning import calibration_of, learn, setup_stats

    path = os.path.join(repo, "gold_trader/state/journal.jsonl")
    journal = Journal(path if os.path.exists(path) else None)
    closed = journal.closed()

    if not journal.records:
        return Section(
            EMPTY,
            reason=(
                "No signals journalled yet. Expected while the MT5 bridge is not "
                "delivering candles (Phase 1)."
            ),
            source="gold_trader/state/journal.jsonl",
            data={"open": 0, "closed": 0},
        )

    state = learn(journal)
    stats = setup_stats(closed)
    calibration = calibration_of(closed)

    # Equity curve in R, ordered by exit.
    ordered = sorted(closed, key=lambda r: r.exit_ts or r.ts)
    equity, running = [], 0.0
    for record in ordered:
        running += record.r_multiple or 0.0
        equity.append({
            "ts": record.exit_ts or record.ts,
            "cumulative_r": round(running, 4),
            "r": round(record.r_multiple or 0.0, 4),
            "setup": record.setup_type,
            "id": record.id,
        })

    peak, max_drawdown = 0.0, 0.0
    for point in equity:
        peak = max(peak, point["cumulative_r"])
        max_drawdown = min(max_drawdown, point["cumulative_r"] - peak)

    return Section(
        OK if closed else EMPTY,
        reason="" if closed else f"{len(journal.records)} signals recorded, none closed yet",
        data={
            "summary": journal.summary(),
            "learning_status": state.status(),
            "closed_n": len(closed),
            "open_positions": [
                {
                    "id": r.id, "direction": r.direction, "entry": r.entry, "stop": r.stop,
                    "target": r.target, "setup": r.setup_type, "ts": r.ts,
                    "size_units": r.size_units, "risk_usd": r.risk_usd,
                    # A resting limit is not a position and carries no risk.
                    # The dashboard showed both identically, so a page reading
                    # "1 open position, $133.60 at risk" could mean nothing was
                    # at risk at all.
                    "filled_at": r.filled_at,
                    "state": "live" if r.filled_at else "resting",
                }
                for r in journal.open_signals()
            ],
            "live_n": len(journal.live()),
            "resting_n": len(journal.resting()),
            "risk_at_work_usd": round(sum(r.risk_usd for r in journal.live()), 2),
            "equity_curve": equity,
            "max_drawdown_r": round(max_drawdown, 3),
            "setups": {k: v.to_dict() for k, v in sorted(stats.items())},
            "calibration": calibration.to_dict(),
            "conviction_multiplier": state.conviction_multiplier(),
            "size_multipliers": {k: state.size_multiplier(k) for k in sorted(stats)},
            "blocked_setups": state.blocked_setups(),
        },
        source="gold_trader/state/journal.jsonl",
    )


def collect_funnel(repo: str) -> Section:
    """Rebuild the decision funnel from the audit log."""
    path = os.path.join(repo, "gold_trader/state/audit.jsonl")
    if not os.path.exists(path):
        return Section(
            EMPTY,
            reason="No pipeline runs recorded yet. The audit log appears on the first run.",
            source=path,
        )

    counts = {key: 0 for key, _ in FUNNEL_STAGES}
    refusals: Dict[str, int] = {}
    runs: Dict[str, Dict[str, Any]] = {}
    malformed = 0

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            run_id = entry.get("run_id", "?")
            run = runs.setdefault(run_id, {"analysed": False, "proposed": False,
                                           "risk_passed": False, "engine_passed": False,
                                           "ordered": False, "codes": []})
            event, stage, payload = entry.get("event"), entry.get("stage"), entry.get("payload", {})

            if event == "stage_output" and stage == "analyst":
                run["analysed"] = True
                if payload.get("bias") not in (None, "flat"):
                    run["proposed"] = True
            elif event == "stage_output" and stage == "risk_manager":
                if payload.get("verdict") != "reject":
                    run["risk_passed"] = True
            elif event == "decision":
                if payload.get("approved"):
                    run["engine_passed"] = True
                for breach in payload.get("breaches", []):
                    if breach.get("severity") == "hard":
                        run["codes"].append(breach.get("code", "UNKNOWN"))
            elif event == "signal_recorded":
                run["ordered"] = True

    counts["runs"] = len(runs)
    for run in runs.values():
        for key in ("analysed", "proposed", "risk_passed", "engine_passed", "ordered"):
            if run[key]:
                counts[key] += 1
        for code in run["codes"]:
            refusals[code] = refusals.get(code, 0) + 1

    if not runs:
        return Section(EMPTY, reason="audit log present but contains no runs", source=path)

    return Section(
        OK,
        data={
            "stages": [{"key": k, "label": label, "count": counts[k]} for k, label in FUNNEL_STAGES],
            "refusals": dict(sorted(refusals.items(), key=lambda kv: -kv[1])),
            "malformed_lines": malformed,
        },
        reason=f"{malformed} unreadable audit lines skipped" if malformed else "",
        source=path,
    )


def collect_data_health(repo: str) -> Section:
    from .sync import describe_data_dir

    data_dir = os.path.join(repo, "data")
    if not os.path.isdir(data_dir):
        return Section(
            EMPTY,
            reason=(
                "No data/ directory. The MT5 bridge has never pushed candles — this is "
                "the current blocker (DAT-04)."
            ),
            source="data/",
        )
    rows = describe_data_dir(data_dir)
    if not rows:
        return Section(EMPTY, reason="data/ exists but holds no XAUUSD_*.csv", source="data/")

    # The terminal's own account of itself. Without it, a disconnected feed and
    # a quiet market look identical from here.
    from .bridge_status import assess, load_status

    status = load_status(data_dir)
    severity, message = assess(status)
    return Section(
        OK,
        data={
            "series": rows,
            "freshest_min": min(r["age_min"] for r in rows),
            "link": {"severity": severity, "message": message,
                     **(status.to_dict() if status else {})},
        },
        source="data/",
    )


def collect_runs(repo: str) -> Section:
    """Scheduled runs that happened, and scheduled runs that never did.

    A run rejected for an account usage limit dies in seconds and writes
    nothing. Without this panel its only symptom is the page slowly ageing.
    """
    from .heartbeat import HEARTBEAT_FILENAME, audit_all

    path = os.path.join(repo, "gold_trader", "state", HEARTBEAT_FILENAME)
    reports = audit_all(path)
    if not any(r.armed for r in reports):
        return Section(
            EMPTY,
            reason=("No run has recorded a heartbeat yet. The detector starts watching "
                    "from the first recorded run — it cannot speak for the runs before it."),
            source=f"state/{HEARTBEAT_FILENAME}",
        )
    return Section(
        OK,
        data={
            "routines": [r.to_dict() for r in reports],
            "missed_total": sum(len(r.missed) for r in reports),
            "error_total": sum(len(r.unresolved_errors) for r in reports),
        },
        source=f"state/{HEARTBEAT_FILENAME}",
    )


def collect_calendar(repo: str) -> Section:
    from .macro import MacroCalendar

    now = datetime.now(timezone.utc)
    path = os.path.join(repo, "gold_trader/state/calendar.json")
    calendar = MacroCalendar.build(now, path if os.path.exists(path) else None)
    return Section(
        OK,
        data={
            "confidence": calendar.confidence,
            "load_errors": calendar.load_errors,
            "upcoming": [e.to_dict() for e in calendar.upcoming(now, 72)],
        },
        source=path if os.path.exists(path) else "(derived only — no calendar file)",
    )


def collect_config(repo: str) -> Section:
    from .config_checks import coherence_problems
    from .pipeline import GoldConfig
    from .risk import TradingLimits

    from .fx import with_live_rate

    limits, fx_note = with_live_rate(TradingLimits(), os.path.join(repo, "data"))
    config = GoldConfig()
    return Section(
        OK,
        data={
            "coherence_problems": coherence_problems(limits),
            "fx_note": fx_note,
            "fx_live": not fx_note.startswith("FX WARNING"),
            "min_equity_pct_of_start": limits.min_equity_pct_of_start,
            "mode": limits.mode,
            "account_value": limits.account_value,
            "account_currency": limits.account_currency,
            "fx_to_usd": limits.fx_to_usd,
            "fx_as_of": limits.fx_as_of,
            "account_usd": limits.account_usd,
            "base_risk": limits.base_risk,
            "risk_per_trade_pct": limits.risk_per_trade_pct,
            "base_risk_usd": limits.base_risk_usd,
            "min_reward_risk": limits.min_reward_risk,
            "max_open_positions": limits.max_open_positions,
            "max_signals_per_day": limits.max_signals_per_day,
            "max_daily_loss_r": limits.max_daily_loss_r,
            "stages": {
                stage: {"model": spec.model_id, "effort": spec.effort}
                for stage, spec in config.model_tiers.items()
            },
        },
        source="gold_trader/config.py",
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build(repo: str = ".") -> Dict[str, Any]:
    sections = {
        "tasks": _collect("docs/ROADMAP.md", lambda: collect_tasks(repo)),
        "selfcheck": _collect("gold_trader/selfcheck.py", lambda: collect_selfcheck(repo)),
        "phase": _collect("docs/DEVELOPMENT_PLAN.md", lambda: collect_phase(repo)),
        "trading": _collect("state/journal.jsonl", lambda: collect_trading(repo)),
        "funnel": _collect("state/audit.jsonl", lambda: collect_funnel(repo)),
        "data_health": _collect("data/", lambda: collect_data_health(repo)),
        "runs": _collect("state/heartbeat.jsonl", lambda: collect_runs(repo)),
        "calendar": _collect("state/calendar.json", lambda: collect_calendar(repo)),
        "config": _collect("gold_trader/config.py", lambda: collect_config(repo)),
    }

    # Every problem in the whole system, gathered in one place so the page never
    # has to hunt for them and no single panel can bury one.
    problems: List[Dict[str, str]] = []
    for name, section in sections.items():
        if section.status == ERROR:
            problems.append({
                "severity": "critical", "source": name,
                "message": f"Could not read {section.source}: {section.reason}",
            })

    selfcheck = sections["selfcheck"]
    if selfcheck.status == OK:
        for result in selfcheck.data["results"]:
            if result["status"] == "FAIL":
                problems.append({
                    "severity": "critical", "source": "selfcheck",
                    "message": f"{result['component']}/{result['check']}: {result['detail']}",
                })

    feed = sections["data_health"]
    if feed.status == OK:
        link = feed.data.get("link") or {}
        if link.get("severity") in ("critical", "warning"):
            problems.append({
                "severity": link["severity"], "source": "bridge",
                "message": link["message"],
            })

    runs = sections["runs"]
    if runs.status == OK:
        for routine in runs.data["routines"]:
            for moment in routine["missed"]:
                problems.append({
                    "severity": "critical", "source": "runs",
                    "message": (f"The {routine['routine']} run scheduled for "
                                f"{moment[:16].replace('T', ' ')} UTC never happened — it left "
                                "no trace, so it died before reaching the pipeline "
                                "(account usage limit, provisioning failure, or an outage)."),
                })
            for beat in routine["unresolved_errors"]:
                problems.append({
                    "severity": "critical", "source": "runs",
                    "message": (f"The {routine['routine']} run at {beat['ts'][:16]} "
                                f"reported an error: {beat['detail'] or '(no detail)'}"),
                })

    tasks = sections["tasks"]
    if tasks.status == OK:
        for task in tasks.data["buckets"]["stale"]:
            problems.append({
                "severity": "critical", "source": "roadmap",
                "message": f"{task['id']} claims done but the check fails: {task['detail']}",
            })

    health = sections["data_health"]
    if health.status == EMPTY:
        problems.append({"severity": "warning", "source": "bridge", "message": health.reason})
    elif health.status == OK and health.data["freshest_min"] > 90:
        problems.append({
            "severity": "critical", "source": "bridge",
            "message": (
                f"Newest candle is {health.data['freshest_min']:.0f} minutes old; "
                "the pipeline will refuse to signal."
            ),
        })

    calendar = sections["calendar"]
    if calendar.status == OK:
        for error in calendar.data["load_errors"]:
            problems.append({"severity": "warning", "source": "calendar", "message": error})
        if calendar.data["confidence"] in ("derived_only", "stale", "invalid"):
            problems.append({
                "severity": "warning", "source": "calendar",
                "message": (
                    f"Event calendar is {calendar.data['confidence']}; FOMC/CPI/PCE dates may "
                    "be missing and blackout windows are narrower than intended."
                ),
            })

    config = sections["config"]
    if config.status == OK:
        for problem in config.data["coherence_problems"]:
            problems.append({"severity": "critical", "source": "config", "message": problem})

    critical = [p for p in problems if p["severity"] == "critical"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "health": "critical" if critical else ("warning" if problems else "ok"),
        "problems": problems,
        "sections": {name: section.to_dict() for name, section in sections.items()},
    }
