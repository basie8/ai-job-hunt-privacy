"""Session and killzone context.

Gold's character changes by session: the Asian range is thin and often becomes
the liquidity that London runs, London carries the day's expansion, and the
London/NY overlap holds the deepest liquidity of the day.

Killzones are defined in New York time, which is the convention, and resolved
through ``zoneinfo`` so they track US daylight saving rather than drifting an
hour twice a year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from .feed import Candle

try:  # pragma: no cover - platform dependent
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = None

#: name -> (start, end) in New York local time. Windows may cross midnight.
KILLZONES: Dict[str, tuple] = {
    "asian_killzone": (time(20, 0), time(0, 0)),
    "london_killzone": (time(2, 0), time(5, 0)),
    "ny_killzone": (time(7, 0), time(10, 0)),
    "london_close": (time(10, 0), time(12, 0)),
}

SESSIONS: Dict[str, tuple] = {
    "asian": (time(19, 0), time(4, 0)),
    "london": (time(3, 0), time(11, 30)),
    "new_york": (time(8, 0), time(17, 0)),
}

#: Where the deepest liquidity sits, and how each window tends to behave.
SESSION_NOTES = {
    "asian": "Thin and range-bound. The range it builds is usually the liquidity London runs.",
    "london": "The day's expansion usually starts here; first move often sweeps the Asian range.",
    "new_york": "Second expansion; reverses or extends London depending on the data calendar.",
    "overlap": "London/NY overlap - deepest liquidity of the day, cleanest fills, fastest moves.",
}


def _to_et(moment: datetime) -> datetime:
    moment = moment.astimezone(timezone.utc)
    if ET is None:  # pragma: no cover - fall back to EST
        return moment - timedelta(hours=5)
    return moment.astimezone(ET)


def _in_window(local: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= local < end
    return local >= start or local < end  # crosses midnight


def active_sessions(moment: datetime) -> List[str]:
    local = _to_et(moment).time()
    names = [name for name, (s, e) in SESSIONS.items() if _in_window(local, s, e)]
    if "london" in names and "new_york" in names:
        names.append("overlap")
    return names


def active_killzone(moment: datetime) -> Optional[str]:
    local = _to_et(moment).time()
    for name, (start, end) in KILLZONES.items():
        if _in_window(local, start, end):
            return name
    return None


#: Gold stops trading for an hour each weekday evening while the venue rolls
#: over to the next session. Defined in New York time, like the weekend close,
#: because that is what it is actually anchored to: 21:00-22:00 UTC during US
#: daylight saving, 22:00-23:00 UTC once the clocks go back. Hardcoding the UTC
#: hours would be correct for half the year and silently wrong for the other.
DAILY_BREAK_START = time(17, 0)
DAILY_BREAK_END = time(18, 0)


def is_daily_break(moment: datetime) -> bool:
    """True during the weekday rollover, when there is no tradeable market.

    Friday's 17:00 and Sunday's reopen are the weekend's business; this covers
    the Monday-to-Thursday break and Sunday evening is excluded because the
    weekly reopen happens at exactly the hour this window would otherwise sit in.
    """
    et = _to_et(moment)
    if et.weekday() in (4, 5, 6):  # Fri/Sat/Sun belong to is_weekend
        return False
    return DAILY_BREAK_START <= et.time() < DAILY_BREAK_END


def market_closed(moment: datetime) -> Optional[str]:
    """Why the market is shut, or None when it is open.

    One function so no caller can check the weekend and forget the daily break.
    """
    if is_weekend(moment):
        return "weekend"
    if is_daily_break(moment):
        return "daily_break"
    return None


def is_weekend(moment: datetime) -> bool:
    """Gold is closed from Friday's NY close to Sunday evening."""
    et = _to_et(moment)
    if et.weekday() == 5:  # Saturday
        return True
    if et.weekday() == 4 and et.time() >= time(17, 0):  # Friday after the close
        return True
    if et.weekday() == 6 and et.time() < time(18, 0):  # Sunday before the reopen
        return True
    return False


@dataclass(frozen=True)
class SessionRange:
    name: str
    high: float
    low: float
    start: datetime
    end: datetime
    bars: int

    @property
    def size(self) -> float:
        return self.high - self.low

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "high": round(self.high, 2),
            "low": round(self.low, 2),
            "size": round(self.size, 2),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "bars": self.bars,
        }


def session_range(
    candles: Sequence[Candle], session: str, moment: datetime
) -> Optional[SessionRange]:
    """High/low of the most recent occurrence of ``session`` before ``moment``.

    Returns None rather than a partial range when the session is still running,
    because a range that is still forming is not yet liquidity.
    """
    if session not in SESSIONS:
        raise ValueError(f"unknown session {session!r}; known: {sorted(SESSIONS)}")
    start_t, end_t = SESSIONS[session]

    members = [c for c in candles if c.ts < moment and _in_window(_to_et(c.ts).time(), start_t, end_t)]
    if not members:
        return None

    # Keep only the latest contiguous run, so an older day's session is excluded.
    run = [members[-1]]
    for candle in reversed(members[:-1]):
        if (run[0].ts - candle.ts) <= timedelta(hours=2):
            run.insert(0, candle)
        else:
            break

    if _in_window(_to_et(moment).time(), start_t, end_t):
        return None  # still forming

    return SessionRange(
        name=session,
        high=max(c.high for c in run),
        low=min(c.low for c in run),
        start=run[0].ts,
        end=run[-1].ts,
        bars=len(run),
    )


@dataclass
class SessionRead:
    moment: datetime
    sessions: List[str] = field(default_factory=list)
    killzone: Optional[str] = None
    weekend: bool = False
    daily_break: bool = False
    ranges: Dict[str, SessionRange] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "et_time": _to_et(self.moment).isoformat(timespec="minutes"),
            "sessions": self.sessions,
            "killzone": self.killzone,
            "weekend": self.weekend,
            "daily_break": self.daily_break,
            "ranges": {k: v.to_dict() for k, v in self.ranges.items()},
        }

    def as_prompt_block(self, price: float) -> str:
        et = _to_et(self.moment)
        lines = [
            f"Time: {et.isoformat(timespec='minutes')} New York "
            f"({self.moment.astimezone(timezone.utc).isoformat(timespec='minutes')} UTC)"
        ]
        if self.weekend:
            lines.append("  MARKET CLOSED for the weekend. No entries.")
            return "\n".join(lines)
        if self.daily_break:
            lines.append("  MARKET CLOSED for the daily rollover (17:00-18:00 New York). "
                         "No entries; quotes either side of it are unreliable.")
            return "\n".join(lines)
        lines.append(f"  Active: {', '.join(self.sessions) or 'between sessions'}")
        for name in self.sessions:
            if name in SESSION_NOTES:
                lines.append(f"    {name}: {SESSION_NOTES[name]}")
        lines.append(f"  Killzone: {self.killzone or 'none'}")
        for name, rng in self.ranges.items():
            if rng.size <= 0:
                continue
            if price > rng.high:
                where = f"price {price - rng.high:.2f} above the range high"
            elif price < rng.low:
                where = f"price {rng.low - price:.2f} below the range low"
            else:
                where = "price inside the range"
            lines.append(
                f"  {name} range {rng.low:.2f}-{rng.high:.2f} ({rng.size:.2f} wide) - {where}"
            )
        if not self.ranges:
            lines.append("  No completed session range in the loaded candles.")
        return "\n".join(lines)


def read_sessions(
    candles: Sequence[Candle], moment: datetime, wanted: Sequence[str] = ("asian", "london")
) -> SessionRead:
    ranges: Dict[str, SessionRange] = {}
    for name in wanted:
        found = session_range(candles, name, moment)
        if found:
            ranges[name] = found
    return SessionRead(
        moment=moment,
        sessions=active_sessions(moment),
        killzone=active_killzone(moment),
        weekend=is_weekend(moment),
        daily_break=is_daily_break(moment),
        ranges=ranges,
    )
