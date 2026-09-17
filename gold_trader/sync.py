"""Moving candles from the local bridge to the scheduled session.

The bridge on your machine pushes CSVs to a dedicated ``market-data`` branch.
The cloud session pulls just that directory out of it. Keeping the data on its
own branch means a bridge push and a journal push can never conflict.
"""

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from typing import Dict, List

DATA_BRANCH = "market-data"


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result


def pull_data_branch(repo: str = ".", branch: str = DATA_BRANCH, data_dir: str = "data") -> bool:
    """Check the data directory out of ``branch`` without switching branches.

    Returns True when the working tree actually changed.
    """
    before = _snapshot(os.path.join(repo, data_dir))
    _git(repo, "fetch", "origin", branch)
    rel = data_dir.replace(os.sep, "/")
    _git(repo, "checkout", f"origin/{branch}", "--", rel)
    return _snapshot(os.path.join(repo, data_dir)) != before


def _snapshot(directory: str) -> Dict[str, str]:
    """Content hashes, not sizes: a fresh bar often has the same byte count."""
    if not os.path.isdir(directory):
        return {}
    out: Dict[str, str] = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                out[name] = hashlib.sha256(fh.read()).hexdigest()
    return out


#: How often each series produces a bar. A bar cannot be fresher than its own
#: interval, so judging every timeframe against one threshold is a category
#: error: at a flat 90 minutes, an h4 bar reads STALE for roughly two thirds of
#: its perfectly normal life, and a reader who sees that nightly stops believing
#: the word.
TIMEFRAME_MINUTES = {
    "m1": 1, "m5": 5, "m15": 15, "m30": 30,
    "h1": 60, "h2": 120, "h4": 240, "h8": 480, "d1": 1440,
}

#: Allowed on top of the interval: the bar has to close, the bridge runs every
#: 15 minutes, and the push takes a moment.
STALENESS_GRACE_MIN = 30


def expected_age_min(timeframe: str, grace: float = STALENESS_GRACE_MIN) -> float:
    """The oldest a series' newest bar can legitimately be.

    An unknown timeframe falls back to the grace alone, which is deliberately
    strict: better to question an unrecognised series than to wave it through.
    """
    return TIMEFRAME_MINUTES.get(timeframe.lower(), 0) + grace


def describe_data_dir(data_dir: str, now: datetime = None) -> List[Dict[str, object]]:
    """Freshness of each XAUUSD series on disk, newest bar first."""
    now = now or datetime.now(timezone.utc)
    rows: List[Dict[str, object]] = []
    if not os.path.isdir(data_dir):
        return rows
    for name in sorted(os.listdir(data_dir)):
        if not (name.startswith("XAUUSD_") and name.endswith(".csv")):
            continue
        path = os.path.join(data_dir, name)
        with open(path, newline="", encoding="utf-8-sig") as fh:
            records = list(csv.DictReader(fh))
        if not records:
            continue
        last = records[-1]
        ts_raw = str(last.get("time") or last.get("date") or "").replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        rows.append(
            {
                "timeframe": name[len("XAUUSD_") : -len(".csv")],
                "bars": len(records),
                "last_ts": ts.isoformat(),
                "last_close": last.get("close"),
                "age_min": (now - ts).total_seconds() / 60.0,
                "expected_max_min": expected_age_min(
                    name[len("XAUUSD_") : -len(".csv")]),
                "stale": (now - ts).total_seconds() / 60.0
                > expected_age_min(name[len("XAUUSD_") : -len(".csv")]),
            }
        )
    return rows
