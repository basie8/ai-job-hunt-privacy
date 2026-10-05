"""Synthetic candle builders so the gold tests never need a feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from gold_trader.feed import Candle, MarketSnapshot, Series, timeframe_minutes

START = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


def candles(
    closes: Sequence[float],
    *,
    start: datetime = START,
    step_min: int = 60,
    spread: float = 2.0,
) -> List[Candle]:
    out: List[Candle] = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        out.append(
            Candle(
                ts=start + timedelta(minutes=step_min * i),
                open=prev,
                high=max(prev, close) + spread,
                low=min(prev, close) - spread,
                close=close,
                volume=100.0,
            )
        )
    return out


def series(closes: Sequence[float], timeframe: str = "h1", **kw) -> Series:
    return Series(timeframe, candles(closes, **kw), source="test")


def ramp(start_price: float, n: int, step: float) -> List[float]:
    return [start_price + step * i for i in range(n)]


def snapshot_from(
    closes: Sequence[float],
    timeframes: Sequence[str] = ("h1", "m15"),
    source: str = "test",
    end: Optional[datetime] = None,
) -> MarketSnapshot:
    """Build a snapshot whose newest candle sits at ``end`` (default: START-based).

    Each timeframe is stepped at its own interval so staleness and bar counts
    behave the way the pipeline expects.
    """
    built = {}
    for tf in timeframes:
        step = timeframe_minutes(tf)
        start = (
            end - timedelta(minutes=step * (len(closes) - 1)) if end else START
        )
        built[tf] = series(closes, tf, start=start, step_min=step)
    newest = max(s.last.ts for s in built.values())
    return MarketSnapshot(
        as_of=newest,
        spot=closes[-1],
        series=built,
        source=source,
        max_staleness_min=10_000_000,
    )


class StubFeed:
    """A Feed that returns a prepared snapshot."""

    name = "stub"

    def __init__(self, snapshot: MarketSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self, timeframes) -> MarketSnapshot:
        return self._snapshot
