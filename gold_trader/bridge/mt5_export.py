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
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

DEFAULT_TIMEFRAMES = ("m15", "h1", "h4")
DEFAULT_BARS = {"m15": 500, "h1": 500, "h4": 400}
DATA_BRANCH = "market-data"
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


def git(repo: str, *args: str, stdin: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run git. stdin is sent as raw bytes, deliberately.

    With ``text=True`` Python translates "\\n" to "\\r\\n" on Windows when
    writing to a child's stdin. ``git mktree`` reads one entry per line and
    treats the stray "\\r" as part of the filename, so the pushed tree ends up
    holding 'data\\r/XAUUSD_h1.csv\\r'. It looks fine on the pushing machine and
    breaks every reader. Encoding here bypasses the translation entirely.
    """
    payload = stdin.encode("utf-8") if stdin is not None else None
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, input=payload)
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

    names = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".csv"))
    if not names:
        print(f"No CSVs in {data_dir}; nothing to push.")
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
    parser.add_argument("--push", action="store_true", help="Commit and push to the data branch.")
    parser.add_argument(
        "--from-dir", default=None,
        help="Skip MT5 and push an existing directory of CSVs (non-Windows path).",
    )
    args = parser.parse_args(argv)

    repo = os.path.abspath(args.repo)
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


if __name__ == "__main__":
    raise SystemExit(main())
