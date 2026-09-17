"""Component audit: errors, placeholders and cross-artifact drift.

Deliberately *not* a second test suite. The unit tests check that each component
behaves correctly in isolation. This checks the things that slip between them:

* **Placeholders** left in shipped source (TODO, FIXME, FILL ME, bare stubs).
* **Config coherence** -- limits that contradict each other, like a minimum stop
  wider than the maximum, which no single test would catch.
* **Cross-artifact drift** -- the setup taxonomy in `schemas.py` diverging from
  the one documented in `AURUM.md`, or a doc naming a CLI command that no longer
  exists. Both artifacts are individually valid; together they are a lie.
* **Entry points** -- every documented path actually runs end to end.

Run weekly, and after any change that touches more than one module:

    python -m gold_trader selfcheck
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

#: Markers that must not appear in shipped source. Example and template files
#: are allowed to contain them -- that is what makes them templates.
PLACEHOLDER_MARKERS = ("TODO", "FIXME", "XXX", "HACK", "FILL ME", "PLACEHOLDER")
PLACEHOLDER_EXEMPT = ("examples/", "docs/", "README", "selfcheck.py", "tests")


@dataclass
class Result:
    component: str
    check: str
    status: str
    detail: str = ""

    def line(self) -> str:
        return f"  [{self.status}] {self.component:<16} {self.check:<38} {self.detail}"


@dataclass
class Report:
    results: List[Result] = field(default_factory=list)

    def add(self, component: str, check: str, status: str, detail: str = "") -> None:
        self.results.append(Result(component, check, status, detail))

    @property
    def failures(self) -> List[Result]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def warnings(self) -> List[Result]:
        return [r for r in self.results if r.status == WARN]

    def render(self, verbose: bool = False) -> str:
        lines = []
        shown = self.results if verbose else [r for r in self.results if r.status != PASS]
        for r in shown:
            lines.append(r.line())
        if not shown:
            lines.append("  all checks passed")
        lines.append("")
        lines.append(
            f"{len(self.results)} checks: "
            f"{len(self.results) - len(self.failures) - len(self.warnings)} pass, "
            f"{len(self.warnings)} warn, {len(self.failures)} fail"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "total": len(self.results),
            "failed": len(self.failures),
            "warned": len(self.warnings),
            "results": [
                {"component": r.component, "check": r.check, "status": r.status, "detail": r.detail}
                for r in self.results
            ],
        }


def _guard(report: Report, component: str, check: str) -> Callable:
    """Run a check, turning an unexpected exception into a FAIL rather than a crash."""

    def run(fn: Callable[[], Optional[str]]) -> None:
        try:
            detail = fn()
            report.add(component, check, PASS, detail or "")
        except AssertionError as exc:
            report.add(component, check, FAIL, str(exc))
        except Exception as exc:  # noqa: BLE001 - the audit must survive anything
            report.add(component, check, FAIL, f"{type(exc).__name__}: {exc}")

    return run


# ---------------------------------------------------------------------------
# Individual audits
# ---------------------------------------------------------------------------

def check_placeholders(report: Report, repo: str) -> None:
    """No unresolved markers in shipped source."""
    offenders = []
    for root, dirs, files in os.walk(os.path.join(repo, "gold_trader")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "state")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, repo)
            if any(part in rel for part in PLACEHOLDER_EXEMPT):
                continue
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    for marker in PLACEHOLDER_MARKERS:
                        if marker in line:
                            offenders.append(f"{rel}:{number} {marker}")
    if offenders:
        report.add("source", "no placeholder markers", FAIL, "; ".join(offenders[:5]))
    else:
        report.add("source", "no placeholder markers", PASS, "clean")


#: Matches the statement, not the word -- otherwise this module flags itself for
#: containing the name of the thing it looks for.
_STUB = re.compile(r"^\s*raise\s+NotImplementedError", re.MULTILINE)


def check_stubs(report: Report, repo: str) -> None:
    """Every raised NotImplementedError must be an abstract base, not a gap."""
    allowed = {"gold_trader/feed.py", "investment_pipeline/llm.py"}
    found = []
    for package in ("gold_trader", "investment_pipeline"):
        for root, dirs, files in os.walk(os.path.join(repo, package)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(root, name), repo).replace(os.sep, "/")
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    if _STUB.search(fh.read()) and rel not in allowed:
                        found.append(rel)
    if found:
        report.add("source", "no unfinished code paths", FAIL, f"unexpected stubs in {found}")
    else:
        report.add("source", "no unfinished code paths", PASS, "only abstract bases")


def check_config_coherence(report: Report) -> None:
    """Limits that contradict each other would make every trade impossible."""
    from .config_checks import coherence_problems  # local import keeps the module light

    problems = coherence_problems()
    if problems:
        report.add("config", "limits are self-consistent", FAIL, "; ".join(problems))
    else:
        report.add("config", "limits are self-consistent", PASS, "")


def check_taxonomy_drift(report: Report, repo: str) -> None:
    """The setup names in code, the doc and the demo must be the same set."""
    from .schemas import SetupType

    in_code = set(SetupType.__args__)
    doc_path = os.path.join(repo, "docs/AURUM.md")
    with open(doc_path, encoding="utf-8") as fh:
        doc = fh.read()
    documented = {name for name in in_code if f"`{name}`" in doc}
    missing = in_code - documented
    if missing:
        report.add(
            "docs", "AURUM documents every setup type", FAIL,
            f"undocumented: {sorted(missing)}",
        )
    else:
        report.add("docs", "AURUM documents every setup type", PASS, f"{len(in_code)} types")

    stray = set(re.findall(r"`([a-z_]{6,})`", doc)) & {
        "trend_pullback", "mean_reversion", "momentum_continuation", "breakout",
    }
    if stray:
        report.add("docs", "no retired setup names in docs", FAIL, f"stale: {sorted(stray)}")
    else:
        report.add("docs", "no retired setup names in docs", PASS, "")


def check_cli_commands(report: Report, repo: str) -> None:
    """Every command the READMEs advertise must still exist."""
    from .cli import main

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            main(["--help"])
    except SystemExit:
        pass
    help_text = buffer.getvalue()
    advertised = set()
    for doc in ("gold_trader/README.md", "docs/ROADMAP.md", "gold_trader/bridge/README.md"):
        path = os.path.join(repo, doc)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                advertised |= set(re.findall(r"python -m gold_trader (\w[\w-]*)", fh.read()))
    missing = sorted(c for c in advertised if c not in help_text)
    if missing:
        report.add("cli", "documented commands exist", FAIL, f"missing: {missing}")
    else:
        report.add("cli", "documented commands exist", PASS, f"{len(advertised)} commands")


def check_feeds(report: Report) -> None:
    from .feed import KNOWN_VENDORS, CsvFeed, FeedUnavailable, HttpFeed, InlineFeed, SnapshotFeed

    run = _guard(report, "feed", "http vendors refuse cleanly")
    def _http():
        for vendor in KNOWN_VENDORS:
            try:
                HttpFeed(vendor, env={}).snapshot(["h1"])
            except FeedUnavailable:
                continue
            raise AssertionError(f"{vendor} did not refuse")
        return f"{len(KNOWN_VENDORS)} vendors"
    run(_http)

    run = _guard(report, "feed", "inline feed parses and snapshots")
    def _inline():
        feed = InlineFeed({"h1": [
            {"time": "2026-09-17T10:00:00Z", "open": 4300, "high": 4310, "low": 4295, "close": 4305},
            {"time": "2026-09-17T11:00:00Z", "open": 4305, "high": 4315, "low": 4300, "close": 4312},
        ]})
        assert len(feed.snapshot(["h1"]).series["h1"]) == 2, "wrong candle count"
        return "2 candles"
    run(_inline)

    run = _guard(report, "feed", "missing csv names the remedy")
    def _missing():
        with tempfile.TemporaryDirectory() as tmp:
            try:
                CsvFeed(tmp).load("h1")
            except FeedUnavailable as exc:
                assert "Export" in str(exc), "error does not say what to do"
                return "actionable error"
        raise AssertionError("a missing file did not raise")
    run(_missing)

    run = _guard(report, "feed", "manual snapshot is usable")
    def _manual():
        snap = SnapshotFeed(datetime.now(timezone.utc), 4312.0, {"swing_low": 4296.0}).snapshot(["h1"])
        assert snap.source == "manual", "source not tagged manual"
        return "tagged manual"
    run(_manual)


def check_degradation(report: Report) -> None:
    """Degraded inputs must tighten the gates, not loosen them."""
    from .journal import Journal
    from .learning import learn
    from .macro import MacroCalendar
    from .risk import TradingLimits, evaluate

    now = datetime.now(timezone.utc)

    def assess(**kw):
        base = dict(
            direction="long", entry=4305.0, stop=4295.0, target=4335.0, conviction=0.7,
            setup_type="bos_continuation", atr=None, spot=4305.0, data_source="csv",
            staleness_min=1.0, now=now, limits=TradingLimits(),
            calendar=MacroCalendar(events=[], confidence="current"),
            journal=Journal(), learning=learn(Journal()),
        )
        base.update(kw)
        return evaluate(**base)

    run = _guard(report, "risk", "stop width checked without ATR")
    def _no_atr():
        blocked = assess(stop=4304.9, target=4400.0)
        assert not blocked.approved, "a 10-cent stop was approved with no ATR"
        assert blocked.size_units == 0.0, "a blocked trade was still sized"
        return "percent-of-spot fallback active"
    run(_no_atr)

    run = _guard(report, "risk", "unverifiable stop is a hard block")
    def _no_anchor():
        assert not assess(atr=None, spot=0.0).approved, "stop passed with nothing to check against"
        return ""
    run(_no_anchor)

    run = _guard(report, "macro", "broken calendar degrades not raises")
    def _broken():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w") as fh:
                fh.write("{not json")
            calendar = MacroCalendar.build(now, path)
            assert calendar.confidence == "invalid", "a broken file did not report invalid"
            assert calendar.events, "derived events were lost with the file"
            return f"{len(calendar.load_errors)} errors recorded"
    run(_broken)


def check_money(report: Report) -> None:
    """Sizing and the rate behind it. Both scale real cash, and both have a
    fallback path that only runs when something upstream is already missing."""
    import argparse

    from .fx import with_live_rate, write_fx
    from .journal import Journal
    from .learning import learn
    from .macro import MacroCalendar
    from .risk import TradingLimits, equity_usd, evaluate

    now = datetime.now(timezone.utc)

    def assess(journal, limits):
        return evaluate(
            direction="long", entry=2400.0, stop=2390.0, target=2420.0, conviction=0.7,
            setup_type="bos_continuation", atr=8.0, spot=2400.0, data_source="csv",
            staleness_min=1.0, now=now, limits=limits,
            calendar=MacroCalendar(events=[], confidence="current"),
            journal=journal, learning=learn(journal),
        )

    run = _guard(report, "risk", "sizing compounds off realised equity")
    def _compounds():
        limits = TradingLimits(account_currency="USD", account_value=10_000.0,
                               fx_to_usd=1.0, risk_per_trade_pct=1.0)
        journal = Journal()
        first = assess(journal, limits).risk_usd
        record = journal.new_signal(direction="long", setup_type="bos_continuation",
                                    conviction=0.7, entry=2400.0, stop=2390.0,
                                    target=2420.0, risk_usd=first)
        journal.update_outcome(record, status="lost", r_multiple=-1.0,
                               exit_ts=now.isoformat())
        after = assess(journal, limits).risk_usd
        assert after < first, "risk did not shrink after a loss"
        assert abs(equity_usd(journal, limits) - (10_000.0 - first)) < 1e-6
        return f"${first:,.2f} then ${after:,.2f}"
    run(_compounds)

    run = _guard(report, "risk", "a ruined book stops trading")
    def _floor():
        limits = TradingLimits(account_currency="USD", account_value=10_000.0,
                               fx_to_usd=1.0, risk_per_trade_pct=1.0)
        journal = Journal()
        record = journal.new_signal(direction="long", setup_type="bos_continuation",
                                    conviction=0.7, entry=2400.0, stop=2390.0,
                                    target=2420.0, risk_usd=5_000.0)
        journal.update_outcome(record, status="lost", r_multiple=-1.0,
                               exit_ts=now.isoformat())
        decision = assess(journal, limits)
        assert not decision.approved, "trading continued below the equity floor"
        assert "EQUITY_FLOOR" in {b.code for b in decision.breaches}
        return f"floor at {limits.min_equity_pct_of_start:.0f}% of start"
    run(_floor)

    run = _guard(report, "fx", "a missing rate is reported, never assumed")
    def _fx_fallback():
        limits = TradingLimits(account_currency="GBP", fx_to_usd=1.3377)
        with tempfile.TemporaryDirectory() as tmp:
            kept, note = with_live_rate(limits, tmp, now=now)
            assert kept.fx_to_usd == limits.fx_to_usd, "a rate was invented"
            assert note.startswith("FX WARNING"), "a fallback rate was reported as live"
            write_fx(tmp, "GBPUSD", 4362.0, now.isoformat(), "MT5 wrong symbol")
            kept, note = with_live_rate(limits, tmp, now=now)
            assert kept.fx_to_usd == limits.fx_to_usd, "an absurd rate was applied"
            assert "misread symbol" in note
            write_fx(tmp, "GBPUSD", 1.3400, now.isoformat(), "MT5 GBPUSD")
            live, note = with_live_rate(limits, tmp, now=now)
            assert live.fx_to_usd == 1.34, "a live rate was ignored"
            assert not note.startswith("FX WARNING")
        return "fallback, misread and live paths all distinguishable"
    run(_fx_fallback)

    run = _guard(report, "cli", "the CLI can build its config")
    def _cli_config():
        from .cli import _config
        config = _config(argparse.Namespace())
        assert config.limits.min_equity_pct_of_start > 0, "defaults were dropped"
        assert config.fx_note, "the run recorded no FX provenance"
        return f"{config.limits.account_currency} {config.limits.account_value:,.0f} loaded"
    run(_cli_config)


def check_run_health(report: Report, repo: str) -> None:
    """The detector for runs that never happened. It only ever runs when
    something has already gone wrong, so it gets exercised here on every audit."""
    from .heartbeat import GRACE_MIN, SCHEDULES, audit_runs, record

    run = _guard(report, "runs", "a missing run is detected")
    def _detects():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "heartbeat.jsonl")
            base = datetime(2026, 9, 17, tzinfo=timezone.utc)
            for hour in (7, 9, 11, 13):
                record(path, "signal", "no_trade", now=base.replace(hour=hour, minute=25))
            # 15:23 never ran; 17:00 is well past its grace period.
            result = audit_runs(path, "signal", now=base.replace(hour=17))
            assert [m.hour for m in result.missed] == [15], f"missed {result.missed}"
            assert not result.healthy(), "a gap did not make the report unhealthy"
            return f"{len(result.recorded)} recorded, 1 gap found"
    run(_detects)

    run = _guard(report, "runs", "a quiet run is not mistaken for a missing one")
    def _quiet():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "heartbeat.jsonl")
            base = datetime(2026, 9, 17, 15, 25, tzinfo=timezone.utc)
            record(path, "signal", "no_trade", "analyst flat", now=base)
            result = audit_runs(path, "signal", now=base.replace(hour=16))
            assert result.healthy(), "a run that reported nothing was counted as failed"
            return "no_trade recorded and accepted"
    run(_quiet)

    run = _guard(report, "runs", "a fixed error stops shouting")
    def _resolves():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "heartbeat.jsonl")
            base = datetime(2026, 9, 17, 15, 25, tzinfo=timezone.utc)
            record(path, "signal", "error", "boom", now=base)
            broken = audit_runs(path, "signal", now=base + timedelta(minutes=30))
            assert not broken.healthy(), "a standing error was not reported"
            record(path, "signal", "no_trade", "flat", now=base + timedelta(hours=2))
            fixed = audit_runs(path, "signal", now=base + timedelta(hours=2, minutes=30))
            assert fixed.healthy(), "an error a later run superseded still reads critical"
            assert len(fixed.errors) == 1, "the error was erased rather than resolved"
            return "resolved errors kept in the record, out of the alarm"
    run(_resolves)

    run = _guard(report, "runs", "unarmed reports nothing rather than everything")
    def _unarmed():
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_runs(os.path.join(tmp, "absent.jsonl"), "signal")
            assert not result.armed, "an empty record claimed to be watching"
            assert result.missed == [], "an empty record invented failures"
            return "cold start is silent"
    run(_unarmed)

    run = _guard(report, "runs", "schedules match the documented cron")
    def _cron():
        # The Schedule objects restate the live Routines' cron expressions.
        # Nothing in the repo can read the Routine, so the cron string in
        # RUNTIME.md is the reference both sides are checked against.
        with open(os.path.join(repo, "docs/RUNTIME.md"), encoding="utf-8") as fh:
            runtime = fh.read()
        expected = {"signal": "23 7-19/2 * * 1-5", "audit": "41 6,18 * * *"}
        for name, cron in expected.items():
            assert cron in runtime, f"{name} cron {cron!r} is not documented in RUNTIME.md"
            minute, hours, _, _, _ = cron.split()
            schedule = SCHEDULES[name]
            assert schedule.minute == int(minute), f"{name} minute drifted from {cron!r}"
        assert GRACE_MIN > 0
        return f"{len(SCHEDULES)} schedules pinned to RUNTIME.md"
    run(_cron)


def check_state_is_committable(report: Report, repo: str) -> None:
    """The durable state must actually be committable.

    Containers are ephemeral; the repository is the only thing that survives
    them. `gold_trader/state/*.jsonl` was gitignored until 2026-09-17, which
    made every `git add gold_trader/state/` in the scheduled runs a silent
    no-op. Nothing failed, nothing warned -- the journal simply could never
    accumulate a trade across runs, so the learning loop could never have left
    cold start no matter how long it ran.
    """
    import subprocess

    run = _guard(report, "state", "durable state is not gitignored")
    def _not_ignored():
        paths = [
            "gold_trader/state/journal.jsonl",
            "gold_trader/state/audit.jsonl",
            "gold_trader/state/heartbeat.jsonl",
            "gold_trader/state/calendar.json",
        ]
        result = subprocess.run(
            ["git", "-C", repo, "check-ignore", "--no-index", *paths],
            capture_output=True, text=True,
        )
        # check-ignore exits 0 and lists paths when any IS ignored.
        ignored = [line for line in result.stdout.splitlines() if line.strip()]
        assert not ignored, (
            "these are ignored and so can never be committed, which silently "
            f"discards the system's only durable state: {ignored}"
        )
        assert result.returncode in (1, 128), f"git check-ignore failed: {result.stderr.strip()}"
        return f"{len(paths)} state paths committable"
    run(_not_ignored)


def check_credentials_path(report: Report) -> None:
    """A run without an API key must say so, not raise from library internals.

    The four stages need their own Anthropic credential; a Claude Code session's
    subscription login does not provide one. The SDK constructs happily without
    it and raises TypeError on the first request, so the failure arrives late
    and unexplained unless something checks first.
    """
    from .cli import CREDENTIALS_REMEDY, _has_credentials

    run = _guard(report, "credentials", "a missing key is detected, not stumbled on")
    def _detects():
        class _Bare:
            api_key = None
            auth_token = None

        class _Keyed:
            api_key = "sk-ant-placeholder"
            auth_token = None

        assert not _has_credentials(_Bare()), "a credential-less client read as authenticated"
        assert _has_credentials(_Keyed()), "a real key read as missing"
        return "both directions distinguishable"
    run(_detects)

    run = _guard(report, "credentials", "the remedy names the fix, not the symptom")
    def _remedy():
        for needle in ("AURUM_ANTHROPIC_API_KEY", "console.anthropic.com",
                       "reserved inside a Claude Code session", "RUNTIME.md"):
            assert needle in CREDENTIALS_REMEDY, f"remedy does not mention {needle!r}"
        # The commands that work without a key, so a missing key does not read
        # as a total outage.
        for command in ("resolve", "status", "learn", "runs", "dashboard"):
            assert command in CREDENTIALS_REMEDY, f"remedy omits working command {command!r}"
        # The trap: ANTHROPIC_API_KEY looks obviously right and is silently
        # dropped by the platform. The remedy must lead with the name that works.
        aurum = CREDENTIALS_REMEDY.index("AURUM_ANTHROPIC_API_KEY")
        assert "Use AURUM_ANTHROPIC_API_KEY, not ANTHROPIC_API_KEY" in CREDENTIALS_REMEDY, (
            "the remedy does not warn against the reserved variable name")
        assert aurum < CREDENTIALS_REMEDY.index("console.anthropic.com"), (
            "the working variable name is not named before the console link")
        return f"{len(CREDENTIALS_REMEDY.splitlines())} lines, names the unreserved variable"
    run(_remedy)


def check_market_hours(report: Report) -> None:
    """Gold is not open all the time, and a signal into a shut market is worse
    than no signal: it is journalled, then resolved against candles that do not
    represent tradeable prices."""
    from .journal import Journal
    from .learning import learn
    from .macro import MacroCalendar
    from .risk import TradingLimits, evaluate
    from .sessions import market_closed

    def assess(now):
        return evaluate(
            direction="long", entry=4350.0, stop=4330.0, target=4400.0, conviction=0.7,
            setup_type="bos_continuation", atr=20.0, spot=4350.0, data_source="csv",
            staleness_min=5.0, now=now, limits=TradingLimits(),
            calendar=MacroCalendar(events=[], confidence="current"),
            journal=Journal(), learning=learn(Journal()),
        )

    run = _guard(report, "market", "a closed market is a hard block")
    def _closed():
        open_dt = datetime(2026, 9, 17, 20, 30, tzinfo=timezone.utc)
        break_dt = datetime(2026, 9, 17, 21, 30, tzinfo=timezone.utc)
        weekend_dt = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        assert assess(open_dt).approved, "a clean trade was refused while the market was open"
        for moment, label in ((break_dt, "daily break"), (weekend_dt, "weekend")):
            decision = assess(moment)
            assert not decision.approved, f"a trade was approved during the {label}"
            codes = {b.code for b in decision.breaches}
            assert "MARKET_CLOSED" in codes, f"{label} did not raise MARKET_CLOSED"
            assert decision.size_units == 0.0, f"a {label} trade was still sized"
        return "weekend and rollover both enforced in code"
    run(_closed)

    run = _guard(report, "market", "the rollover follows New York, not UTC")
    def _dst():
        # 17:00 New York is 21:00 UTC in summer and 22:00 UTC in winter. A
        # hardcoded UTC hour would be right for half the year.
        summer = datetime(2026, 9, 17, 21, 30, tzinfo=timezone.utc)
        winter = datetime(2026, 12, 15, 22, 30, tzinfo=timezone.utc)
        winter_by_summer_clock = datetime(2026, 12, 15, 21, 30, tzinfo=timezone.utc)
        assert market_closed(summer) == "daily_break", "summer rollover not detected"
        assert market_closed(winter) == "daily_break", "winter rollover not detected"
        assert market_closed(winter_by_summer_clock) is None, "rollover did not shift with DST"
        return "21:00 UTC in summer, 22:00 UTC in winter"
    run(_dst)

    run = _guard(report, "market", "no scheduled run lands in the rollover")
    def _schedule():
        from .heartbeat import SIGNAL_SCHEDULE
        # A run scheduled inside the break can never produce a tradeable signal,
        # and the gap detector would report it missing every single evening.
        # Checked in both halves of the year: the cron is fixed UTC but the
        # closure it must avoid moves an hour when the US changes its clocks,
        # so a schedule that clears the break in September could sit inside it
        # in December.
        for year, month, day, label in ((2026, 9, 17, "summer"), (2026, 12, 17, "winter")):
            for hour in SIGNAL_SCHEDULE.hours:
                moment = datetime(year, month, day, hour, SIGNAL_SCHEDULE.minute,
                                  tzinfo=timezone.utc)
                assert market_closed(moment) is None, (
                    f"in {label} the {hour:02d}:{SIGNAL_SCHEDULE.minute} run falls "
                    "inside a market closure")
        return f"{len(SIGNAL_SCHEDULE.hours)} slots clear in both summer and winter"
    run(_schedule)


def check_bridge_link(report: Report) -> None:
    """A dead feed and a quiet market must not look the same.

    The terminal drops its broker connection at every close, so the state alone
    means nothing -- it only becomes a finding when the market should be open.
    Getting that backwards would page the owner every single evening.
    """
    from .bridge_status import CRITICAL, OK, STALE_AFTER_MIN, BridgeStatus, assess

    open_dt = datetime(2026, 9, 17, 20, 30, tzinfo=timezone.utc)
    break_dt = datetime(2026, 9, 17, 21, 30, tzinfo=timezone.utc)

    def at(connected, minutes_ago, now):
        return BridgeStatus(
            as_of=(now - timedelta(minutes=minutes_ago)).isoformat(), connected=connected)

    run = _guard(report, "bridge", "a dead feed is told apart from a quiet market")
    def _distinguishes():
        down_open = assess(at(False, 5, open_dt), open_dt)
        down_shut = assess(at(False, 5, break_dt), break_dt)
        assert down_open[0] == CRITICAL, "a disconnected terminal was not flagged while open"
        assert down_shut[0] == OK, "a closed-market disconnection was reported as a fault"
        assert down_open[1] != down_shut[1], "both closures produced the same message"
        return "disconnection judged against market hours"
    run(_distinguishes)

    run = _guard(report, "bridge", "a stopped bridge outranks a dropped link")
    def _stale_wins():
        # A stale file's connected flag describes a moment that has passed, so
        # it cannot be trusted to excuse anything.
        stale = assess(at(True, STALE_AFTER_MIN + 10, open_dt), open_dt)
        assert stale[0] == CRITICAL, "a bridge that stopped running was not flagged"
        assert "has not run" in stale[1], "the stale case was reported as something else"
        weekend = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        assert assess(at(True, STALE_AFTER_MIN + 10, weekend), weekend)[0] == CRITICAL, (
            "the weekend excused a bridge that was not running")
        return f"stale beyond {STALE_AFTER_MIN}min is critical in any market state"
    run(_stale_wins)


def check_freshness_is_per_timeframe(report: Report) -> None:
    """A bar cannot be fresher than its own interval."""
    from .sync import STALENESS_GRACE_MIN, expected_age_min

    run = _guard(report, "feed", "freshness is judged per timeframe")
    def _per_tf():
        assert expected_age_min("h4") > expected_age_min("h1") > expected_age_min("m15"), (
            "timeframes are not ordered by their own cadence")
        # The exact false positive this replaced: a 114-minute-old h4 bar read
        # STALE under a flat 90-minute rule, every single evening.
        assert expected_age_min("h4") > 114, "an h4 bar two hours old would still read stale"
        assert expected_age_min("m15") < 90, "the m15 limit is looser than the old flat rule"
        assert expected_age_min("nonsense") == STALENESS_GRACE_MIN, (
            "an unrecognised timeframe was waved through instead of questioned")
        return "m15/h1/h4 each judged against their own cadence"
    run(_per_tf)


def check_learning_guarantees(report: Report) -> None:
    """The three anti-overfitting guards, verified as properties not examples."""
    from .journal import Journal
    from .learning import learn

    def journal_with(setup, n, r_each, conviction=0.7):
        journal = Journal()
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        for i in range(n):
            record = journal.new_signal(
                direction="long", setup_type=setup, conviction=conviction,
                entry=4300.0, stop=4290.0, target=4320.0,
                ts=(start + timedelta(days=i)).isoformat(timespec="seconds"),
            )
            journal.update_outcome(
                record, status="won" if r_each > 0 else "lost", r_multiple=r_each,
                exit_ts=(start + timedelta(days=i, hours=4)).isoformat(timespec="seconds"),
            )
        return journal

    run = _guard(report, "learning", "never sizes above 1.0")
    def _never_up():
        state = learn(journal_with("bos_continuation", 120, 3.0), min_samples=20)
        multiplier = state.size_multiplier("bos_continuation")
        assert multiplier <= 1.0, f"a perfect record produced a {multiplier} multiplier"
        return "capped at 1.0 on a flawless record"
    run(_never_up)

    run = _guard(report, "learning", "inert below the sample floor")
    def _floor():
        state = learn(journal_with("range_fade", 5, -1.0), min_samples=20)
        assert state.size_multiplier("range_fade") == 1.0, "clamped on 5 trades"
        assert state.conviction_multiplier() == 1.0, "shrank conviction on 5 trades"
        return "no adjustment under 20 trades"
    run(_floor)

    run = _guard(report, "learning", "blocks a proven loser")
    def _block():
        state = learn(journal_with("range_fade", 80, -1.0), min_samples=20)
        assert "range_fade" in state.blocked_setups(), "a setup losing 80 in a row was not blocked"
        return "blocked at 2x the sample floor"
    run(_block)


def check_pipeline(report: Report) -> None:
    """The whole chain runs and the enforcement layer still wins."""
    run = _guard(report, "pipeline", "end-to-end with enforcement")

    def _run():
        import sys

        sys.path.insert(0, os.getcwd())
        from investment_pipeline.audit import AuditLog, verify_records
        from tests.fake_client import FakeStageClient
        from tests_gold.helpers import StubFeed, ramp, snapshot_from
        from tests_gold.test_pipeline import ALERT, chart_read, plan, verdict
        from .journal import Journal
        from .pipeline import GoldConfig, run_signal

        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        snapshot = snapshot_from(ramp(4300.0, 120, 0.4), timeframes=("h1", "m15"), end=now)
        spot = snapshot.spot
        client = FakeStageClient({
            "analyst": chart_read(entry=spot, stop=spot - 9.0, target=spot + 20.0),
            # The risk manager tries to widen the stop; enforcement must refuse.
            "risk_manager": verdict(adjusted_stop=spot - 30.0, adjusted_conviction=0.7),
            "executor": plan(entry=spot, stop=spot - 9.0, target=spot + 20.0),
            "reporter": ALERT,
        })
        log = AuditLog()
        result = run_signal(feed=StubFeed(snapshot), client=client, config=GoldConfig(),
                            now=now, log=log, journal=Journal())
        assert result.decision.stop == spot - 9.0, "a widened stop was accepted"
        assert log.events("override_attempt"), "the override was not logged"
        ok, problem = verify_records(log.records)
        assert ok, f"audit chain broken: {problem}"
        assert len(log.events("llm_call")) == 4, "not all four stages ran"
        return "4 stages, override refused, chain intact"

    run(_run)


def check_smc_and_sessions(report: Report) -> None:
    from .sessions import active_killzone, is_weekend
    from .smc import read_structure

    run = _guard(report, "sessions", "killzones track daylight saving")
    def _dst():
        summer = active_killzone(datetime(2026, 7, 15, 7, tzinfo=timezone.utc))
        winter = active_killzone(datetime(2026, 1, 15, 8, tzinfo=timezone.utc))
        assert summer == "london_killzone", f"summer killzone wrong: {summer}"
        assert winter == "london_killzone", f"winter killzone wrong: {winter}"
        return "London killzone correct in both halves of the year"
    run(_dst)

    run = _guard(report, "sessions", "weekend closure detected")
    def _weekend():
        assert is_weekend(datetime(2026, 9, 19, 12, tzinfo=timezone.utc)), "Saturday read as open"
        assert not is_weekend(datetime(2026, 9, 18, 14, tzinfo=timezone.utc)), "Friday read as shut"
        return ""
    run(_weekend)

    run = _guard(report, "smc", "degrades on too little data")
    def _thin():
        from .feed import Candle

        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        thin = [Candle(start + timedelta(hours=i), 100, 101, 99, 100) for i in range(3)]
        read = read_structure(thin, "h1")
        assert read.bias == "unknown", "claimed a bias from 3 candles"
        return "returns unknown rather than inventing structure"
    run(_thin)


def run_all(repo: str = ".") -> Report:
    report = Report()
    check_placeholders(report, repo)
    check_stubs(report, repo)
    check_config_coherence(report)
    check_taxonomy_drift(report, repo)
    check_cli_commands(report, repo)
    check_feeds(report)
    check_degradation(report)
    check_money(report)
    check_run_health(report, repo)
    check_state_is_committable(report, repo)
    check_credentials_path(report)
    check_market_hours(report)
    check_bridge_link(report)
    check_freshness_is_per_timeframe(report)
    check_learning_guarantees(report)
    check_smc_and_sessions(report)
    check_pipeline(report)
    return report
