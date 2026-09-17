"""XAUUSD pipeline CLI.

    python -m gold_trader doctor                      # what data is actually available
    python -m gold_trader signal   --csv-dir data/    # run all four stages
    python -m gold_trader resolve  --csv-dir data/    # score open trades, no model calls
    python -m gold_trader learn                       # the measured track record
    python -m gold_trader status                      # open positions and budgets
    python -m gold_trader calendar                    # the event diary as loaded
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

from .feed import KNOWN_VENDORS, CsvFeed, Feed, FeedUnavailable, InlineFeed
from .journal import Journal, resolve_all
from .learning import learn
from .macro import MacroCalendar
from .pipeline import GoldConfig, run_signal
from .fx import with_live_rate
from .risk import (
    TradingLimits, equity_usd, realised_pnl_usd, realised_r_today, signals_today,
)
from .sync import DATA_BRANCH, pull_data_branch, describe_data_dir
from .progress import audit
from .selfcheck import run_all
from .dashboard import build as build_dashboard
from .dashboard_html import render as render_dashboard
from .heartbeat import OUTCOMES, SCHEDULES, audit_all, audit_runs, record


def _data_dir(args: argparse.Namespace) -> str:
    """Where the bridge drops candles and fx.json."""
    return getattr(args, "csv_dir", None) or getattr(args, "data_dir", None) or "data"


def _config(args: argparse.Namespace) -> GoldConfig:
    """Build the run config. Overrides are applied on top of the shipped
    defaults, so adding a limit never silently drops it from the CLI path."""
    overrides = {}
    if getattr(args, "account", None):
        overrides["account_value"] = args.account
    if getattr(args, "risk_pct", None):
        overrides["risk_per_trade_pct"] = args.risk_pct
    limits = TradingLimits(**overrides)
    limits, note = with_live_rate(limits, _data_dir(args))
    if note.startswith("FX WARNING"):
        print(note, file=sys.stderr)
    config = GoldConfig(limits=limits)
    config.fx_note = note
    if getattr(args, "journal", None):
        config.journal_path = args.journal
    if getattr(args, "state_dir", None):
        config.journal_path = os.path.join(args.state_dir, "journal.jsonl")
        config.audit_path = os.path.join(args.state_dir, "audit.jsonl")
        config.calendar_path = os.path.join(args.state_dir, "calendar.json")
        config.heartbeat_path = os.path.join(args.state_dir, "heartbeat.jsonl")
    return config


def _feed(args: argparse.Namespace) -> Feed:
    if getattr(args, "csv_dir", None):
        return CsvFeed(args.csv_dir)
    if getattr(args, "json", None):
        return InlineFeed.from_json(args.json)
    raise SystemExit(
        "No data source. Pass --csv-dir <dir> with XAUUSD_<tf>.csv exports, or --json <file>.\n"
        "Run `python -m gold_trader doctor` to see what this environment can reach."
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    print("XAUUSD pipeline - data availability\n")
    print("Live vendor feeds:")
    for vendor, (host, key_var) in sorted(KNOWN_VENDORS.items()):
        has_key = "key set" if os.environ.get(key_var) else f"{key_var} unset"
        print(f"  {vendor:<14} host {host:<26} {has_key}")
    print(
        "\n  All of the above require the session's egress policy to allow the host.\n"
        "  As shipped, this environment returns 403 on CONNECT for every one of them,\n"
        "  so HttpFeed refuses rather than returning stale or invented prices.\n"
    )
    print("Offline sources that work now:")
    for directory in ("data", "gold_trader/examples"):
        if os.path.isdir(directory):
            files = sorted(f for f in os.listdir(directory) if f.endswith(".csv") or f.endswith(".json"))
            print(f"  {directory}/: {', '.join(files) if files else '(empty)'}")
        else:
            print(f"  {directory}/: not present")
    config = _config(args)
    print("\nState:")
    for label, path in (
        ("journal", config.journal_path),
        ("audit", config.audit_path),
        ("calendar", config.calendar_path),
    ):
        exists = "present" if os.path.exists(path) else "absent"
        print(f"  {label:<9} {path} ({exists})")
    cal = MacroCalendar.build(datetime.now(timezone.utc), config.calendar_path)
    print(f"  calendar confidence: {cal.confidence}")
    return 0


def cmd_signal(args: argparse.Namespace) -> int:
    from investment_pipeline.llm import AnthropicStageClient

    config = _config(args)
    try:
        result = run_signal(_feed(args), AnthropicStageClient(), config=config)
    except FeedUnavailable as exc:
        print(f"Feed unavailable: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        json.dump(result.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    alert = result.alert
    if alert:
        print(alert.headline)
        print("=" * min(len(alert.headline), 90))
        print(alert.action_line)
        print()
        print(alert.body)
        print()
        print(alert.risk_line)
        if alert.watch_items:
            print("\nWatch:")
            for item in alert.watch_items:
                print(f"  - {item}")
        if alert.learning_note:
            print(f"\nLearning: {alert.learning_note}")
    if result.decision and result.decision.breaches:
        print("\nRisk engine:")
        for b in result.decision.breaches:
            print(f"  [{b.severity}] {b.code}: {b.detail}")
    print(f"\nrun {result.run_id} | model spend ${result.audit.total_cost_usd():.4f}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    config = _config(args)
    journal = Journal(config.journal_path)
    feed = _feed(args)
    snapshot = feed.snapshot(config.timeframes)
    series = snapshot.series.get(config.resolution_timeframe)
    if series is None:
        print(f"No {config.resolution_timeframe} series to resolve against.", file=sys.stderr)
        return 2
    resolved = resolve_all(journal, series)
    if not resolved:
        print(f"Nothing to resolve. {len(journal.open_signals())} still open.")
        return 0
    for r in resolved:
        print(f"{r.id} {r.setup_type:<22} {r.status:<10} {r.r_multiple:+.2f}R  ({r.resolution})")
    print(f"\n{len(resolved)} resolved. Journal: {json.dumps(journal.summary())}")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    config = _config(args)
    journal = Journal(config.journal_path)
    state = learn(journal, min_samples=config.min_samples)
    if args.json_out:
        json.dump(state.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(state.lessons_block())
    print("\nClamps now in force:")
    print(f"  conviction multiplier: {state.conviction_multiplier():.2f}")
    for setup in sorted(state.setups):
        print(f"  size multiplier [{setup}]: {state.size_multiplier(setup):.2f}")
    if state.blocked_setups():
        print(f"  blocked: {', '.join(state.blocked_setups())}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    journal = Journal(config.journal_path)
    now = datetime.now(timezone.utc)
    limits = config.limits
    print(json.dumps(journal.summary(), indent=2))
    equity = equity_usd(journal, limits)
    floor = limits.account_usd * limits.min_equity_pct_of_start / 100.0
    print(f"\n{config.fx_note}")
    print(f"Equity: ${equity:,.2f} "
          f"(start ${limits.account_usd:,.2f} {realised_pnl_usd(journal):+,.2f} realised; "
          f"floor ${floor:,.2f})")
    print(f"Next trade risks {limits.risk_per_trade_pct:.2f}% of equity = "
          f"${max(0.0, equity) * limits.risk_per_trade_pct / 100.0:,.2f} before any learned reduction")
    print(f"Realised today: {realised_r_today(journal, now):+.2f}R "
          f"(daily stop -{config.limits.max_daily_loss_r:.1f}R)")
    print(f"Signals today: {signals_today(journal, now)} / {config.limits.max_signals_per_day}")
    for record in journal.open_signals():
        print(f"  OPEN {record.id} {record.direction} {record.entry} "
              f"stop {record.stop} target {record.target} ({record.setup_type})")
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    config = _config(args)
    now = datetime.now(timezone.utc)
    print(MacroCalendar.build(now, config.calendar_path).as_prompt_block(now))
    return 0


def cmd_pull_data(args: argparse.Namespace) -> int:
    """Fetch the candles the local MT5 bridge pushed to the data branch."""
    try:
        changed = pull_data_branch(args.repo, args.branch, args.data_dir)
    except RuntimeError as exc:
        print(f"Could not pull {args.branch}: {exc}", file=sys.stderr)
        return 2
    print(f"{'Updated' if changed else 'Already current'} from origin/{args.branch}")
    rows = describe_data_dir(args.data_dir)
    if not rows:
        print(f"No XAUUSD_*.csv under {args.data_dir}. Is the bridge running?", file=sys.stderr)
        return 2
    for row in rows:
        flag = "  STALE" if row["age_min"] > args.max_age_min else ""
        print(
            f"  {row['timeframe']:<4} {row['bars']:>4} bars, last {row['last_ts']} "
            f"({row['age_min']:.0f}min old, close {row['last_close']}){flag}"
        )
    freshest = min(r["age_min"] for r in rows)
    if freshest > args.max_age_min:
        print(
            f"\nEvery series is older than {args.max_age_min}min. The pipeline will refuse "
            "to signal on this. Check the bridge on your machine.",
            file=sys.stderr,
        )
        return 3
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    """Re-verify every roadmap claim against the repository."""
    result = audit(args.roadmap, args.repo)
    if not result.tasks:
        print(f"No tasks parsed from {args.roadmap}.", file=sys.stderr)
        return 2
    if args.json_out:
        json.dump(
            {"summary": result.summary(), "tasks": [t.to_dict() for t in result.tasks]},
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(result.render())
    # Non-zero when the roadmap is lying about something.
    return 1 if result.stale else 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    """Audit every component for errors, placeholders and cross-artifact drift."""
    report = run_all(args.repo)
    if args.json_out:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print("Component self-check\n")
        print(report.render(verbose=args.verbose))
    return 1 if report.failures else 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Export everything the operations dashboard shows, errors included."""
    payload = build_dashboard(args.repo)
    if args.html:
        page = render_dashboard(payload)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(page)
        print(f"wrote {args.html} ({len(page):,} bytes, health={payload['health']})")
        return 1 if payload["health"] == "critical" else 0
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f"wrote {args.out}")
    else:
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    # Non-zero when the system is unhealthy, so a caller cannot miss it.
    return 1 if payload["health"] == "critical" else 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    """Record that a scheduled run happened, whatever it concluded.

    Every run calls this, including the ones that produce nothing else. A run
    that leaves no trace is indistinguishable from a run that never started,
    and the one that never started is the one worth knowing about.
    """
    config = _config(args)
    beat = record(config.heartbeat_path, args.routine, args.outcome, args.detail or "")
    print(f"recorded {beat.routine} {beat.outcome} at {beat.ts}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """Report scheduled runs that left no trace, and runs that errored.

    Exits non-zero when a run is missing, so a caller cannot overlook it.
    """
    config = _config(args)
    reports = ([audit_runs(config.heartbeat_path, args.routine, args.hours)]
               if args.routine else audit_all(config.heartbeat_path, args.hours))
    if args.json_out:
        json.dump([r.to_dict() for r in reports], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print("Scheduled run health\n")
        for report in reports:
            print(report.render())
            print()
    return 0 if all(r.healthy() for r in reports) else 1


def _common(parser: argparse.ArgumentParser, data: bool = False) -> None:
    parser.add_argument("--state-dir", default=None, help="Directory for journal/audit/calendar.")
    parser.add_argument("--journal", default=None)
    parser.add_argument("--account", type=float, default=None)
    parser.add_argument("--risk-pct", type=float, default=None)
    if data:
        parser.add_argument("--csv-dir", default=None, help="Directory of XAUUSD_<tf>.csv exports.")
        parser.add_argument("--json", dest="json", default=None, help="Inline candle JSON file.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="gold_trader", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="Report what data this environment can actually reach.")
    _common(p)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("signal", help="Run all four stages and emit an alert.")
    _common(p, data=True)
    p.add_argument("--json-out", action="store_true")
    p.set_defaults(func=cmd_signal)

    p = sub.add_parser("resolve", help="Score open trades against new candles (no model calls).")
    _common(p, data=True)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("learn", help="Show the measured track record and active clamps.")
    _common(p)
    p.add_argument("--json-out", action="store_true")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("status", help="Open positions and session budgets.")
    _common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("pull-data", help="Fetch candles the local bridge pushed.")
    p.add_argument("--repo", default=".")
    p.add_argument("--branch", default=DATA_BRANCH)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--max-age-min", type=int, default=90)
    p.set_defaults(func=cmd_pull_data)

    p = sub.add_parser("progress", help="Audit the roadmap, verifying each claim.")
    p.add_argument("--roadmap", default="docs/ROADMAP.md")
    p.add_argument("--repo", default=".")
    p.add_argument("--json-out", action="store_true")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("heartbeat", help="Record that a scheduled run happened.")
    _common(p)
    p.add_argument("--routine", required=True, choices=sorted(SCHEDULES))
    p.add_argument("--outcome", required=True, choices=list(OUTCOMES))
    p.add_argument("--detail", default="", help="Error text, or a one-line note.")
    p.set_defaults(func=cmd_heartbeat)

    p = sub.add_parser("runs", help="Report scheduled runs that never happened.")
    _common(p)
    p.add_argument("--routine", default=None, choices=sorted(SCHEDULES))
    p.add_argument("--hours", type=int, default=26)
    p.add_argument("--json-out", action="store_true")
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("selfcheck", help="Audit all components for errors and placeholders.")
    p.add_argument("--repo", default=".")
    p.add_argument("--verbose", action="store_true", help="Show passing checks too.")
    p.add_argument("--json-out", action="store_true")
    p.set_defaults(func=cmd_selfcheck)

    p = sub.add_parser("dashboard", help="Export dashboard data as JSON.")
    p.add_argument("--repo", default=".")
    p.add_argument("--out", default=None, help="Write JSON to a file instead of stdout.")
    p.add_argument("--html", default=None, help="Render the dashboard page to this path.")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("calendar", help="The event diary as currently loaded.")
    _common(p)
    p.set_defaults(func=cmd_calendar)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
