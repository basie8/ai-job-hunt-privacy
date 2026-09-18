"""What the MT5 terminal said about itself, and whether it matters.

The bridge writes `data/bridge.json` every run. It reports facts and judges
none of them, because judging needs gold's trading hours and the bridge cannot
count on having a timezone database: `zoneinfo` on Windows falls back to the
`tzdata` package, which may not be installed. This module does the judging,
where the hours are already known exactly.

The distinction that matters, and the reason this exists:

    disconnected + market closed  ->  normal. The terminal drops the broker
                                      connection at the close every day.
    disconnected + market open    ->  the feed is dead and candles are frozen.

Without the connection state those two are indistinguishable from outside: both
produce a bridge that runs, finds no new candles, and pushes nothing. On
2026-09-17 the data branch had a four-hour gap with the PC on the whole time,
and there was no way to tell which it had been. That is the same shape as every
other defect found that day -- an absence that looks expected.

A second, quieter use: this file is rewritten on every run whether or not the
candles moved, so its own freshness is proof the bridge executed. A stale
`bridge.json` means the bridge itself stopped, which is different again from a
bridge that ran and had nothing to say.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from .sessions import market_closed

STATUS_FILENAME = "bridge.json"

#: The bridge runs every 15 minutes, so a status file older than this means the
#: bridge process itself is not running -- distinct from a bridge that ran and
#: found nothing. Generous enough to absorb a missed tick or two.
STALE_AFTER_MIN = 45

#: One late tick is noise; a whole cycle missed is a pattern. Between this and
#: STALE_AFTER_MIN the bridge is late enough to say so without claiming it is
#: dead.
#:
#: Without this tier the report read "ok" for the first 45 minutes -- three
#: missed runs -- and then jumped straight to critical. At 01:12 on 2026-09-18
#: the bridge had not run for 40 minutes, having been started by hand once and
#: never picked up by Task Scheduler, and the dashboard showed green while
#: saying "last checked 40min ago" in the same breath. A number that contradicts
#: the verdict beside it teaches the reader to stop reading the verdict.
LATE_AFTER_MIN = 20

OK = "ok"
WARNING = "warning"
CRITICAL = "critical"


@dataclass(frozen=True)
class BridgeStatus:
    as_of: str
    connected: Optional[bool]
    server: str = ""
    ping_ms: Optional[float] = None
    terminal_build: Optional[int] = None
    symbol: str = ""
    trade_allowed: Optional[bool] = None
    read_error: str = ""

    def age_min(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        try:
            stamped = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        return (now - stamped).total_seconds() / 60.0

    def to_dict(self, now: Optional[datetime] = None) -> Dict[str, object]:
        age = self.age_min(now)
        severity, message = assess(self, now)
        return {
            "as_of": self.as_of,
            "connected": self.connected,
            "server": self.server,
            "ping_ms": self.ping_ms,
            "terminal_build": self.terminal_build,
            "symbol": self.symbol,
            "read_error": self.read_error,
            "age_min": None if age == float("inf") else round(age, 1),
            "severity": severity,
            "message": message,
        }


def load_status(directory: str) -> Optional[BridgeStatus]:
    """Read the bridge's own report. None rather than raising or guessing."""
    path = os.path.join(directory, STATUS_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        if not isinstance(blob, dict):
            return None
        return BridgeStatus(
            as_of=str(blob.get("as_of", "")),
            connected=blob.get("connected"),
            server=str(blob.get("server", "") or ""),
            ping_ms=blob.get("ping_ms"),
            terminal_build=blob.get("terminal_build"),
            symbol=str(blob.get("symbol", "") or ""),
            trade_allowed=blob.get("trade_allowed"),
            read_error=str(blob.get("read_error", "") or ""),
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def assess(status: Optional[BridgeStatus], now: Optional[datetime] = None):
    """Return (severity, message). The whole point of the module.

    Ordered so the most actionable finding wins: a bridge that is not running
    at all outranks a terminal that is merely disconnected, because the second
    cannot be trusted if the first is true -- a stale file's `connected` flag
    describes a moment that has passed.
    """
    now = now or datetime.now(timezone.utc)
    closed = market_closed(now)

    if status is None:
        return WARNING, (
            "The bridge has never written a status file. Update the bridge on "
            "the Windows PC (UPDATE.bat) so it reports the terminal's state."
        )

    age = status.age_min(now)
    if age == float("inf"):
        return WARNING, "The bridge status file has an unreadable timestamp."

    if age > STALE_AFTER_MIN:
        return CRITICAL, (
            f"The bridge has not run for {age:.0f} minutes (it should run every 15). "
            "This is the bridge process itself, not the market: check the PC, "
            "Task Scheduler, and that MetaTrader 5 is open."
        )

    if age > LATE_AFTER_MIN and not closed:
        missed = int(age // 15)
        return WARNING, (
            f"The bridge last ran {age:.0f} minutes ago and should run every 15: "
            f"{missed} scheduled run(s) missed. Not yet long enough to call it "
            "dead, but it is not keeping its cadence -- check Task Scheduler's "
            "Last Run Result for the AURUM bridge task (0x0 is success)."
        )

    if status.read_error:
        return WARNING, (
            f"The bridge ran but could not read the terminal's state: {status.read_error}"
        )

    if status.connected is False:
        if closed:
            return OK, (
                f"Terminal disconnected, which is expected: the market is closed "
                f"({closed.replace('_', ' ')}). It reconnects at the reopen."
            )
        return CRITICAL, (
            "The terminal is DISCONNECTED from the broker while the market is open. "
            "Candles are frozen and the pipeline will refuse to signal. Check the "
            "connection indicator in MetaTrader 5, bottom right."
        )

    if status.connected is None:
        return WARNING, "The bridge did not report whether the terminal is connected."

    where = f" to {status.server}" if status.server else ""
    ping = f", ping {status.ping_ms:.0f}ms" if status.ping_ms else ""
    return OK, f"Terminal connected{where}{ping}, last checked {age:.0f}min ago."
