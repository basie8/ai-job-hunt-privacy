"""Market data adapters for XAUUSD.

This container cannot reach any market data host (the egress policy returns 403
on CONNECT for Yahoo, stooq, Twelve Data, Polygon, Alpha Vantage, OANDA, Tiingo
and FMP alike), so the feed is a pluggable seam rather than a hardcoded client.

Three adapters work today with no network at all:

* ``CsvFeed``       -- an MT4/MT5/TradingView/Dukascopy OHLCV export on disk.
* ``InlineFeed``    -- candles pasted straight into a call or a JSON file.
* ``SnapshotFeed``  -- a hand-entered snapshot, for when all you have is a chart
                       screenshot and the levels read off it.

``HttpFeed`` is the fourth and stays inert until two things are true: the egress
policy allows the vendor host, and the vendor's key is in the environment. It
raises a message naming both rather than silently returning stale or invented
prices.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

INSTRUMENT = "XAUUSD"

#: Vendor -> (host that must be allowed by egress, env var holding the key).
KNOWN_VENDORS: Dict[str, tuple] = {
    "twelvedata": ("api.twelvedata.com", "TWELVEDATA_API_KEY"),
    "polygon": ("api.polygon.io", "POLYGON_API_KEY"),
    "alphavantage": ("www.alphavantage.co", "ALPHAVANTAGE_API_KEY"),
    "oanda": ("api-fxtrade.oanda.com", "OANDA_API_TOKEN"),
    "tiingo": ("api.tiingo.com", "TIINGO_API_KEY"),
}


class FeedUnavailable(RuntimeError):
    """Raised instead of guessing when real prices cannot be obtained."""


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"candle at {self.ts}: high {self.high} below low {self.low}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"candle at {self.ts}: open {self.open} outside [{self.low},{self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"candle at {self.ts}: close {self.close} outside [{self.low},{self.high}]")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ts": self.ts.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class Series:
    """An ordered, same-timeframe candle series. Oldest first."""

    timeframe: str
    candles: List[Candle]
    instrument: str = INSTRUMENT
    source: str = "unknown"

    def __post_init__(self) -> None:
        for a, b in zip(self.candles, self.candles[1:]):
            if b.ts <= a.ts:
                raise ValueError(f"{self.timeframe}: candles out of order at {b.ts}")

    def __len__(self) -> int:
        return len(self.candles)

    @property
    def closes(self) -> List[float]:
        return [c.close for c in self.candles]

    @property
    def highs(self) -> List[float]:
        return [c.high for c in self.candles]

    @property
    def lows(self) -> List[float]:
        return [c.low for c in self.candles]

    @property
    def last(self) -> Candle:
        if not self.candles:
            raise FeedUnavailable(f"{self.timeframe} series is empty")
        return self.candles[-1]

    def tail(self, n: int) -> "Series":
        return Series(self.timeframe, self.candles[-n:], self.instrument, self.source)

    def age(self, now: Optional[datetime] = None) -> timedelta:
        now = now or datetime.now(timezone.utc)
        return now - self.last.ts

    def to_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "source": self.source,
            "count": len(self.candles),
            "first_ts": self.candles[0].ts.isoformat() if self.candles else None,
            "last_ts": self.candles[-1].ts.isoformat() if self.candles else None,
        }


@dataclass(frozen=True)
class MarketSnapshot:
    """Everything the analyst stage is allowed to see about price."""

    as_of: datetime
    spot: float
    series: Dict[str, Series]
    source: str
    #: Worst-case staleness the caller is prepared to accept, in minutes.
    max_staleness_min: int = 90

    def staleness_min(self, now: Optional[datetime] = None) -> float:
        """Age of the newest candle against the run clock, not wall clock.

        The reference time is passed in so a run is reproducible: replaying the
        same snapshot with the same ``now`` gives the same answer tomorrow.
        """
        reference = now or datetime.now(timezone.utc)
        return (reference - self.as_of).total_seconds() / 60.0

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        return self.staleness_min(now) > self.max_staleness_min

    def to_dict(self, now: Optional[datetime] = None) -> Dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "spot": self.spot,
            "source": self.source,
            "staleness_min": round(self.staleness_min(now), 1),
            "series": {tf: s.to_dict() for tf, s in self.series.items()},
        }


class Feed:
    """Interface the pipeline depends on."""

    name = "abstract"

    def snapshot(self, timeframes: Sequence[str]) -> MarketSnapshot:
        raise NotImplementedError


def _parse_ts(raw: str) -> datetime:
    raw = raw.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(raw) if fmt is None else datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError(f"unrecognised timestamp {raw!r}")


def candles_from_rows(rows: Iterable[Dict[str, str]]) -> List[Candle]:
    """Build candles from dict rows, tolerating the usual column spellings."""
    aliases = {
        "ts": ("ts", "time", "date", "datetime", "timestamp", "<date>", "local time"),
        "open": ("open", "o", "<open>"),
        "high": ("high", "h", "<high>"),
        "low": ("low", "l", "<low>"),
        "close": ("close", "c", "<close>", "price"),
        "volume": ("volume", "vol", "v", "<vol>", "tickvol", "<tickvol>"),
    }
    out: List[Candle] = []
    for row in rows:
        lower = {str(k).strip().lower(): v for k, v in row.items() if k}
        picked: Dict[str, object] = {}
        for field, names in aliases.items():
            for name in names:
                if name in lower and str(lower[name]).strip() != "":
                    picked[field] = lower[name]
                    break
        missing = [f for f in ("ts", "open", "high", "low", "close") if f not in picked]
        if missing:
            raise ValueError(f"row missing {missing}: {row}")
        out.append(
            Candle(
                ts=_parse_ts(str(picked["ts"])),
                open=float(picked["open"]),
                high=float(picked["high"]),
                low=float(picked["low"]),
                close=float(picked["close"]),
                volume=float(picked.get("volume", 0) or 0),
            )
        )
    out.sort(key=lambda c: c.ts)
    return out


class CsvFeed(Feed):
    """Reads ``<dir>/XAUUSD_<timeframe>.csv`` exports.

    Works with MT4/MT5 "Save as CSV", TradingView "Export chart data", and
    Dukascopy downloads without editing, since the column names are aliased.
    """

    name = "csv"

    def __init__(self, directory: str, instrument: str = INSTRUMENT) -> None:
        self.directory = directory
        self.instrument = instrument

    def _path(self, timeframe: str) -> str:
        return os.path.join(self.directory, f"{self.instrument}_{timeframe}.csv")

    def load(self, timeframe: str) -> Series:
        path = self._path(timeframe)
        if not os.path.exists(path):
            raise FeedUnavailable(
                f"no {timeframe} data at {path}. Export {self.instrument} {timeframe} candles "
                f"from your platform and save them there."
            )
        with open(path, newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.DictReader(fh, dialect=dialect))
        candles = candles_from_rows(rows)
        if not candles:
            raise FeedUnavailable(f"{path} contained no usable candles")
        return Series(timeframe, candles, self.instrument, source=f"csv:{os.path.basename(path)}")

    def snapshot(self, timeframes: Sequence[str]) -> MarketSnapshot:
        series = {tf: self.load(tf) for tf in timeframes}
        newest = max(s.last.ts for s in series.values())
        spot = min(series.values(), key=lambda s: _tf_minutes(s.timeframe)).last.close
        return MarketSnapshot(as_of=newest, spot=spot, series=series, source=self.name)


class InlineFeed(Feed):
    """Candles handed over directly -- pasted into a call or read from JSON."""

    name = "inline"

    def __init__(self, data: Dict[str, Sequence[Dict[str, object]]], instrument: str = INSTRUMENT) -> None:
        self.series = {
            tf: Series(tf, candles_from_rows([dict(r) for r in rows]), instrument, source="inline")
            for tf, rows in data.items()
        }

    @classmethod
    def from_json(cls, path: str) -> "InlineFeed":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def snapshot(self, timeframes: Sequence[str]) -> MarketSnapshot:
        missing = [tf for tf in timeframes if tf not in self.series]
        if missing:
            raise FeedUnavailable(f"inline data has no {missing} series")
        chosen = {tf: self.series[tf] for tf in timeframes}
        newest = max(s.last.ts for s in chosen.values())
        spot = min(chosen.values(), key=lambda s: _tf_minutes(s.timeframe)).last.close
        return MarketSnapshot(as_of=newest, spot=spot, series=chosen, source=self.name)


class SnapshotFeed(Feed):
    """A single hand-entered read, for when the only input is a chart image.

    Levels read off a screenshot are approximate by nature, so this adapter
    records ``source='manual'`` and the pipeline treats manual reads as lower
    confidence and refuses tight stops against them.
    """

    name = "manual"

    def __init__(self, as_of: datetime, spot: float, levels: Dict[str, float]) -> None:
        self.as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        self.spot = spot
        self.levels = levels

    def snapshot(self, timeframes: Sequence[str]) -> MarketSnapshot:
        return MarketSnapshot(
            as_of=self.as_of, spot=self.spot, series={}, source=self.name, max_staleness_min=240
        )


class HttpFeed(Feed):
    """Inert until egress is opened for the vendor and its key is set.

    It refuses loudly rather than returning anything, because a trading signal
    computed from an unavailable or stale feed is worse than no signal.
    """

    name = "http"

    def __init__(self, vendor: str, env: Optional[Dict[str, str]] = None) -> None:
        if vendor not in KNOWN_VENDORS:
            raise ValueError(f"unknown vendor {vendor!r}; known: {sorted(KNOWN_VENDORS)}")
        self.vendor = vendor
        self.host, self.key_var = KNOWN_VENDORS[vendor]
        self.env = os.environ if env is None else env

    def preflight(self) -> None:
        if not self.env.get(self.key_var):
            raise FeedUnavailable(
                f"{self.vendor}: {self.key_var} is not set. "
                f"Also confirm the session's egress policy allows {self.host}."
            )
        raise FeedUnavailable(
            f"{self.vendor}: {self.host} is blocked by this session's egress policy "
            f"(403 on CONNECT). Ask for {self.host} to be allowed for this environment, "
            f"then wire the vendor call here."
        )

    def snapshot(self, timeframes: Sequence[str]) -> MarketSnapshot:
        self.preflight()
        raise AssertionError("unreachable")  # pragma: no cover


_TF_MINUTES = {
    "m1": 1, "m5": 5, "m15": 15, "m30": 30,
    "h1": 60, "h4": 240, "d1": 1440, "w1": 10080,
}


def _tf_minutes(timeframe: str) -> int:
    key = timeframe.strip().lower()
    if key not in _TF_MINUTES:
        raise ValueError(f"unknown timeframe {timeframe!r}; known: {sorted(_TF_MINUTES)}")
    return _TF_MINUTES[key]


def timeframe_minutes(timeframe: str) -> int:
    return _tf_minutes(timeframe)
