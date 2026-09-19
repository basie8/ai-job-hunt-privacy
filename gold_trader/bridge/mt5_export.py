"""Local MT5 -> repo bridge.

Runs on YOUR machine (where MetaTrader 5 is installed), pulls XAUUSD candles,
writes them as CSVs the pipeline's ``CsvFeed`` reads, and pushes them to a
dedicated ``market-data`` branch. The scheduled cloud session pulls that branch,
so prices reach the pipeline without any egress change.

    python mt5_export.py --repo C:\\path\\to\\ai-job-hunt-privacy --push

Three things this handles that a naive exporter does not:

* **Symbol naming.** Brokers call gold XAUUSD, GOLD, XAUUSD.m, XAUUSDm, XAUUSD#
  and worse. The symbol is discovered rather than assumed.
* **Server time.** MT5 bar timestamps are in *broker server* time, typically
  UTC+2 or UTC+3, not UTC. Getting this wrong silently shifts every bar and
  breaks both staleness checks and event blackouts, so the offset is detected
  from the broker's own tick clock and can be overridden.
* **Idempotent commits.** Nothing is committed when the candles have not
  changed, so the branch does not fill with empty commits between bars.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

DEFAULT_TIMEFRAMES = ("m15", "h1", "h4")
DEFAULT_BARS = {"m15": 500, "h1": 500, "h4": 400}
DATA_BRANCH = "market-data"
#: Brokers suffix FX pairs the same way they suffix metals.
FX_SUFFIXES = ("", ".m", "m", "#", ".raw", "_", ".pro", ".ecn")

CANDIDATE_SYMBOLS = (
    "XAUUSD", "GOLD", "XAUUSD.m", "XAUUSDm", "XAUUSD#", "XAUUSD.raw",
    "XAUUSD_", "XAUUSD.pro", "GOLD.spot", "XAU/USD",
)


def _mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        sys.exit(
            "MetaTrader5 package not found. On the Windows machine running MT5:\n"
            "    pip install MetaTrader5\n"
            "It is Windows-only. On macOS/Linux, export candles from your platform by hand\n"
            "and use --from-dir to push an existing directory of CSVs instead."
        )
    return mt5


def resolve_symbol(mt5, requested: Optional[str] = None) -> str:
    """Find what this broker actually calls spot gold."""
    if requested:
        if mt5.symbol_select(requested, True):
            return requested
        sys.exit(f"Symbol {requested!r} was not accepted by this broker.")
    available = {s.name for s in (mt5.symbols_get() or [])}
    for candidate in CANDIDATE_SYMBOLS:
        if candidate in available and mt5.symbol_select(candidate, True):
            return candidate
    gold_like = sorted(s for s in available if "XAU" in s.upper() or "GOLD" in s.upper())
    if gold_like:
        sys.exit(
            "Could not auto-pick a gold symbol. Candidates this broker offers:\n  "
            + "\n  ".join(gold_like)
            + "\nRe-run with --symbol <name>."
        )
    sys.exit("This broker exposes no XAU/GOLD symbol. Check the Market Watch list in MT5.")


def resolve_fx_symbol(mt5, pair: str) -> Optional[str]:
    """Find what this broker calls the account-currency pair, if it offers it."""
    available = {s.name for s in (mt5.symbols_get() or [])}
    for suffix in FX_SUFFIXES:
        candidate = pair + suffix
        if candidate in available and mt5.symbol_select(candidate, True):
            return candidate
    return None


def read_fx_rate(mt5, symbol: str) -> Optional[float]:
    """Mid price from the current tick. None rather than a guess."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    bid, ask = getattr(tick, "bid", 0.0) or 0.0, getattr(tick, "ask", 0.0) or 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return bid or ask or None


def detect_server_offset_hours(mt5, symbol: str) -> float:
    """Broker server time minus UTC, from the newest tick.

    MT5 reports tick.time in server time. Comparing it to the wall clock at the
    moment of the call gives the offset to the nearest half hour, which is all
    any broker uses.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or not tick.time:
        return 0.0
    server = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    delta_hours = (server - datetime.now(timezone.utc)).total_seconds() / 3600.0
    return round(delta_hours * 2) / 2.0


def fetch(mt5, symbol: str, timeframe: str, bars: int, offset_hours: float) -> List[Dict[str, object]]:
    constants = {
        "m1": mt5.TIMEFRAME_M1, "m5": mt5.TIMEFRAME_M5, "m15": mt5.TIMEFRAME_M15,
        "m30": mt5.TIMEFRAME_M30, "h1": mt5.TIMEFRAME_H1, "h4": mt5.TIMEFRAME_H4,
        "d1": mt5.TIMEFRAME_D1,
    }
    if timeframe not in constants:
        sys.exit(f"Unsupported timeframe {timeframe!r}. Known: {sorted(constants)}")
    rates = mt5.copy_rates_from_pos(symbol, constants[timeframe], 0, bars)
    if rates is None or len(rates) == 0:
        sys.exit(f"MT5 returned no {timeframe} data for {symbol}: {mt5.last_error()}")

    rows: List[Dict[str, object]] = []
    for r in rates:
        # Reported in server time; shift back to real UTC.
        ts = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc) - timedelta(hours=offset_hours)
        rows.append(
            {
                "time": ts.isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
            }
        )
    return rows


def write_csv(rows: Sequence[Dict[str, object]], path: str) -> bool:
    """Write the file. Returns True when the contents actually changed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    lines = ["time,open,high,low,close,volume"]
    for row in rows:
        lines.append(
            f"{row['time']},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']}"
        )
    payload = "\n".join(lines) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            if fh.read() == payload:
                return False
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(payload)
    return True


#: The rate ticks constantly. Rewriting it on every run would push a commit every
#: 15 minutes even when no candle changed, which is exactly the noise the
#: content-hash check was added to avoid. So write it only when it has actually
#: moved, or when the stored one is old enough that the reader would start
#: calling it stale.
FX_MIN_MOVE_PCT = 0.05
FX_REFRESH_HOURS = 6


#: The bridge reports the terminal's state and judges none of it. Whether a
#: disconnection matters depends on whether the market should be open, which
#: needs a timezone database this script cannot count on having: zoneinfo on
#: Windows falls back to the `tzdata` package, and that may not be installed.
#: The pipeline already knows gold's hours exactly, so it does the judging.
STATUS_FILENAME = "bridge.json"


def read_terminal_state(mt5, symbol: str = "") -> dict:
    """What the terminal says about itself. Never raises -- a status read that
    breaks the bridge would be worse than no status at all."""
    state = {"connected": None, "server": "", "ping_ms": None,
             "terminal_build": None, "symbol": symbol, "trade_allowed": None}
    try:
        info = mt5.terminal_info()
        if info is not None:
            state["connected"] = bool(getattr(info, "connected", False))
            state["terminal_build"] = getattr(info, "build", None)
            state["trade_allowed"] = bool(getattr(info, "trade_allowed", False))
            ping = getattr(info, "ping_last", None)
            if ping:
                state["ping_ms"] = round(ping / 1000.0, 1)  # MT5 reports microseconds
    except Exception as exc:  # noqa: BLE001 - never let this stop a candle push
        state["read_error"] = f"{type(exc).__name__}: {exc}"
    try:
        account = mt5.account_info()
        if account is not None:
            state["server"] = str(getattr(account, "server", "") or "")
    except Exception:  # noqa: BLE001
        pass
    return state


def write_status(directory: str, state: dict, now_iso: str) -> str:
    """Write the terminal state next to the candles, every run without
    exception. This file existing and being fresh is itself the evidence that
    the bridge ran; a gap in it is a gap in the bridge."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, STATUS_FILENAME)
    payload = dict(state)
    payload["as_of"] = now_iso
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def fx_needs_writing(directory: str, pair: str, rate: float, now_iso: str) -> str:
    """Return why the rate should be written, or "" to leave the file alone."""
    path = os.path.join(directory, "fx.json")
    try:
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)[pair]
        previous = float(entry["rate"])
        stamped = datetime.fromisoformat(str(entry["as_of"]))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return "first reading"
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    age_hours = (datetime.fromisoformat(now_iso) - stamped).total_seconds() / 3600.0
    if previous <= 0 or abs(rate - previous) / previous * 100.0 >= FX_MIN_MOVE_PCT:
        return f"moved from {previous:.5f}"
    if age_hours >= FX_REFRESH_HOURS:
        return f"refreshed after {age_hours:.1f}h"
    return ""


def write_fx(directory: str, pair: str, rate: float, as_of: str, source: str) -> str:
    """Write the rate next to the candles. Mirrors gold_trader/fx.py's reader."""
    path = os.path.join(directory, "fx.json")
    blob = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                blob = loaded
        except (json.JSONDecodeError, OSError):
            blob = {}
    blob[pair] = {"rate": float(rate), "as_of": as_of, "source": source}
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


#: Where Git for Windows puts itself when it is not on PATH.
#:
#: The installer offers "Use Git from Git Bash only", which deliberately keeps
#: git off the system PATH. Git Bash then works perfectly and every other
#: launcher -- cmd, a .bat, Task Scheduler -- cannot find git at all. A bridge
#: run started by hand from Git Bash succeeds; the identical run started by
#: Windows fails at the push and nowhere else.
GIT_FALLBACK_PATHS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
)

_GIT_EXE: Optional[str] = None


def git_exe() -> str:
    """The git to run, found explicitly rather than trusted to PATH.

    Task Scheduler gives a task a different environment from an interactive
    shell -- often a different account's PATH, sometimes almost none. Resolving
    git here means the bridge works the same however it was started, and says
    something useful when it genuinely cannot find it.
    """
    global _GIT_EXE
    if _GIT_EXE:
        return _GIT_EXE
    found = shutil.which("git")
    if not found:
        for candidate in GIT_FALLBACK_PATHS:
            expanded = os.path.expandvars(candidate)
            if os.path.exists(expanded):
                found = expanded
                break
    if not found:
        local = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")
        if os.path.exists(local):
            found = local
    if not found:
        raise RuntimeError(
            "git was not found on PATH or in any standard install location. "
            "If Git for Windows was installed with 'Use Git from Git Bash only', "
            "git works inside Git Bash and nowhere else -- including Task "
            "Scheduler. Re-run the Git installer and choose 'Git from the "
            "command line and also from 3rd-party software'."
        )
    _GIT_EXE = found
    return found


def git(repo: str, *args: str, stdin: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run git. stdin is sent as raw bytes, deliberately.

    With ``text=True`` Python translates "\\n" to "\\r\\n" on Windows when
    writing to a child's stdin. ``git mktree`` reads one entry per line and
    treats the stray "\\r" as part of the filename, so the pushed tree ends up
    holding 'data\\r/XAUUSD_h1.csv\\r'. It looks fine on the pushing machine and
    breaks every reader. Encoding here bypasses the translation entirely.
    """
    payload = stdin.encode("utf-8") if stdin is not None else None
    result = subprocess.run([git_exe(), "-C", repo, *args], capture_output=True, input=payload)
    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(stderr or stdout).strip()}")
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, stderr)


def _mktree(repo: str, entries: Sequence[str]) -> str:
    for entry in entries:
        if "\r" in entry or "\n" in entry.rstrip("\n"):
            raise RuntimeError(f"tree entry contains a line break: {entry!r}")
    return git(repo, "mktree", stdin="\n".join(entries) + "\n").stdout.strip()


def push_data_branch(
    repo: str, data_dir: str, message: str, branch: str = DATA_BRANCH, remote: str = "origin"
) -> bool:
    """Commit the CSVs to a dedicated branch using plumbing only.

    This deliberately never checks out, stashes, or switches branches: it builds
    the blobs, trees and commit directly and pushes the resulting object. Your
    working tree and current branch are untouched, so running the bridge on a
    schedule can never disturb whatever you happen to be editing. The branch
    holds nothing but the data directory, so a bridge push can never conflict
    with a journal push from the scheduled session.

    Returns True when a new commit was actually pushed.
    """
    rel = os.path.relpath(os.path.abspath(data_dir), os.path.abspath(repo)).replace(os.sep, "/")
    if rel.startswith(".."):
        raise RuntimeError(f"{data_dir} is outside the repository at {repo}")

    names = sorted(
        f for f in os.listdir(data_dir)
        if f.lower().endswith(".csv") or f.lower() in ("fx.json", "bridge.json")
    )
    if not names:
        print(f"No candle files in {data_dir}; nothing to push.")
        return False

    entries = []
    for name in names:
        blob = git(repo, "hash-object", "-w", "--", os.path.join(data_dir, name)).stdout.strip()
        entries.append(f"100644 blob {blob}\t{name}")
    tree = _mktree(repo, entries)
    # Nest the tree back under its path, deepest component first.
    for part in reversed(rel.split("/")):
        tree = _mktree(repo, [f"040000 tree {tree}\t{part}"])

    git(repo, "fetch", remote, branch, check=False)
    parent = git(repo, "rev-parse", "--verify", "--quiet", f"{remote}/{branch}", check=False).stdout.strip()

    if parent:
        previous = git(repo, "rev-parse", f"{parent}^{{tree}}", check=False).stdout.strip()
        if previous == tree:
            print("No candle changes since the last push.")
            return False

    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    commit = git(repo, *args).stdout.strip()
    git(repo, "push", remote, f"{commit}:refs/heads/{branch}")
    print(f"Pushed {rel}/ ({len(names)} files) to {remote}/{branch} as {commit[:10]}")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Path to your clone of the repository.")
    parser.add_argument("--symbol", default=None, help="Override the broker's gold symbol.")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--bars", type=int, default=None, help="Bars per timeframe.")
    parser.add_argument(
        "--server-offset-hours", type=float, default=None,
        help="Broker server time minus UTC. Auto-detected when omitted.",
    )
    parser.add_argument(
        "--fx-pair", default="GBPUSD",
        help="Account-currency pair to read alongside the candles. Empty string to skip.",
    )
    parser.add_argument("--push", action="store_true", help="Commit and push to the data branch.")
    parser.add_argument(
        "--check", action="store_true",
        help="Report the environment this process runs in and stop. Touches nothing.",
    )
    parser.add_argument(
        "--from-dir", default=None,
        help="Skip MT5 and push an existing directory of CSVs (non-Windows path).",
    )
    args = parser.parse_args(argv)

    repo = os.path.abspath(args.repo)
    if args.check:
        # Before the repo check, so a misconfigured repo is reported rather
        # than being the thing that stops the report.
        return preflight(repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit(f"{repo} is not a git repository.")
    data_dir = args.from_dir or os.path.join(repo, "data")

    if not args.from_dir:
        mt5 = _mt5()
        if not mt5.initialize():
            sys.exit(
                f"Could not connect to MT5: {mt5.last_error()}\n"
                "Make sure the terminal is running and logged in, and that\n"
                "Tools -> Options -> Expert Advisors -> 'Allow algorithmic trading' is enabled."
            )
        try:
            symbol = resolve_symbol(mt5, args.symbol)
            # Read and write the terminal's state before anything else can fail.
            # A run that dies mid-way should still have said whether the
            # terminal was connected when it started.
            state = read_terminal_state(mt5, symbol)
            write_status(data_dir, state,
                         datetime.now(timezone.utc).isoformat(timespec="seconds"))
            changed = True  # the status file moves every run, by design
            link = "connected" if state["connected"] else "DISCONNECTED"
            ping = f", ping {state['ping_ms']}ms" if state.get("ping_ms") else ""
            server = f" [{state['server']}]" if state.get("server") else ""
            print(f"  link {link}{server}{ping}")
            if state["connected"] is False:
                print("       The terminal is not connected to the broker. Candles will "
                      "not update until it is. This is normal while the market is closed.")
            offset = (
                args.server_offset_hours
                if args.server_offset_hours is not None
                else detect_server_offset_hours(mt5, symbol)
            )
            print(f"Symbol: {symbol} | server offset: UTC{offset:+.1f}h")
            changed = False
            for timeframe in [t.strip().lower() for t in args.timeframes.split(",") if t.strip()]:
                bars = args.bars or DEFAULT_BARS.get(timeframe, 500)
                rows = fetch(mt5, symbol, timeframe, bars, offset)
                path = os.path.join(data_dir, f"XAUUSD_{timeframe}.csv")
                wrote = write_csv(rows, path)
                changed = changed or wrote
                age = datetime.now(timezone.utc) - datetime.fromisoformat(rows[-1]["time"])
                print(
                    f"  {timeframe:<4} {len(rows):>4} bars, last {rows[-1]['time']} "
                    f"({age.total_seconds() / 60:.0f}min old, close {rows[-1]['close']}) "
                    f"{'updated' if wrote else 'unchanged'}"
                )
            # The account is denominated in GBP and gold in USD, so the rate
            # belongs with the candles rather than hardcoded downstream.
            if args.fx_pair:
                fx_symbol = resolve_fx_symbol(mt5, args.fx_pair)
                if fx_symbol is None:
                    print(
                        f"  fx   {args.fx_pair} not offered by this broker; "
                        "the configured fallback rate stays in use"
                    )
                else:
                    rate = read_fx_rate(mt5, fx_symbol)
                    if rate is None:
                        print(f"  fx   {fx_symbol} gave no tick; leaving the previous rate")
                    else:
                        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        reason = fx_needs_writing(data_dir, args.fx_pair, rate, stamp)
                        if reason:
                            write_fx(data_dir, args.fx_pair, rate, stamp, f"MT5 {fx_symbol}")
                            changed = True
                        print(f"  fx   {args.fx_pair} {rate:.5f} from {fx_symbol} "
                              f"{reason or 'unchanged'}")
        finally:
            mt5.shutdown()
        if not changed and not args.push:
            return 0
    else:
        print(f"Pushing existing CSVs from {data_dir}")

    if args.push:
        stamp = datetime.now(timezone.utc).isoformat(timespec="minutes")
        push_data_branch(repo, data_dir, f"XAUUSD candles @ {stamp}")
    return 0


def preflight(repo: str) -> int:
    """Report the environment this process is actually running in.

    The point is that it runs *as the scheduled task*, not as you. Every
    difference between a run that works by hand and a run that fails under Task
    Scheduler is somewhere in this output: a different account, a different
    PATH, a python that resolves elsewhere, a git that cannot be found, a
    credential helper that is not there.

    Written to the run log as well as printed, so a scheduled run leaves the
    answer behind even though nobody was watching the console.
    """
    lines = ["AURUM bridge preflight"]

    def say(label: str, value: object) -> None:
        lines.append(f"  {label:<16} {value}")

    say("user", os.environ.get("USERNAME") or os.environ.get("USER") or "?")
    say("python", sys.executable)
    say("version", sys.version.split()[0])
    say("cwd", os.getcwd())
    say("repo", repo)
    say("repo is git", os.path.isdir(os.path.join(repo, ".git")))

    try:
        exe = git_exe()
        version = subprocess.run([exe, "--version"], capture_output=True, text=True)
        say("git", f"{exe}  ({version.stdout.strip()})")
    except RuntimeError as exc:
        say("git", f"NOT FOUND -- {exc}")

    try:
        import MetaTrader5  # noqa: F401

        say("MetaTrader5 pkg", "importable")
    except Exception as exc:  # noqa: BLE001 - reporting, not failing
        say("MetaTrader5 pkg", f"NOT importable -- {type(exc).__name__}: {exc}")

    # The push is the step most likely to work by hand and fail on a schedule,
    # because credentials are per-account and a scheduled task may run as
    # someone else. Asking the remote is the only honest way to know.
    try:
        probe = subprocess.run(
            [git_exe(), "-C", repo, "ls-remote", "--exit-code", "origin", "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        say("remote reachable",
            "yes" if probe.returncode == 0
            else f"NO -- {(probe.stderr or probe.stdout).strip()[:200]}")
    except Exception as exc:  # noqa: BLE001
        say("remote reachable", f"NO -- {type(exc).__name__}: {exc}")

    report = "\n".join(lines)
    print(report)
    for line in lines[1:]:
        log_run(repo, "check", line.strip())
    return 0


#: A local record of every invocation, whatever happened.
#:
#: Everything this script says goes to stdout, and under Task Scheduler stdout
#: goes nowhere. So a scheduled run that failed left no trace on the PC and no
#: trace in the repository -- indistinguishable from a task that never fired.
#:
#: The log is deliberately LOCAL and never pushed. When the thing that is
#: broken is the push itself, a pushed log cannot report it.
RUN_LOG_FILENAME = "bridge-run.log"

#: Keep roughly a week of 15-minute runs, then start the file again. Small
#: enough to open in Notepad, long enough to show a pattern.
RUN_LOG_MAX_BYTES = 256 * 1024


def log_run(repo: str, outcome: str, detail: str = "") -> None:
    """Append one line for this run. Never raises: a logging failure must not
    be the thing that stops a candle push."""
    try:
        path = os.path.join(repo, RUN_LOG_FILENAME)
        if os.path.exists(path) and os.path.getsize(path) > RUN_LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{stamp}  {outcome:<7} {detail}".rstrip()
        with open(path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - see docstring
        pass


def _run_and_log(argv=None) -> int:
    """Wrap main() so that every outcome reaches the log, including the ones
    that produce nothing else.

    A task that runs and dies and a task that never ran look identical from
    outside. This is the line that tells them apart, and it is the whole point
    of the file: if `bridge-run.log` has no entry for the last hour, Task
    Scheduler is not starting the task. If it has entries and they say `error`,
    the task is starting and something downstream is failing -- most often the
    push, because a scheduled task may not see the Windows Credential Manager
    that your own session uses.
    """
    repo = os.path.abspath(_repo_from(argv))
    try:
        code = main(argv)
    except SystemExit as exc:
        # argparse and the sys.exit() calls above both land here. A string
        # argument is the message; an int is a status.
        detail = "" if exc.code in (0, None) else str(exc.code)
        log_run(repo, "ok" if exc.code in (0, None) else "error", detail)
        raise
    except Exception as exc:  # noqa: BLE001 - the log is the only witness
        log_run(repo, "error", f"{type(exc).__name__}: {exc}")
        raise
    log_run(repo, "ok" if code == 0 else "error", "" if code == 0 else f"exit {code}")
    return code


def _repo_from(argv) -> str:
    """Find --repo without running argparse, so the log works even when
    argparse is what rejected the arguments."""
    items = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(items):
        if item == "--repo" and index + 1 < len(items):
            return items[index + 1]
        if item.startswith("--repo="):
            return item.split("=", 1)[1]
    return "."


if __name__ == "__main__":
    raise SystemExit(_run_and_log())
