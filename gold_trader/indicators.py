"""Deterministic technical features.

Pure functions over candle series. Nothing here calls a model: the analyst
stage is given computed numbers, not asked to eyeball a chart, so the same
input always yields the same features and the journal can replay them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from datetime import datetime

from .feed import Candle, Series, timeframe_minutes
from .sessions import SessionRead, read_sessions
from .smc import SmcRead, read_structure


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> List[float]:
    """Full EMA series, seeded with the SMA of the first ``period`` values."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def ema(values: Sequence[float], period: int) -> Optional[float]:
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI."""
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for a, b in zip(values, values[1:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_ranges(candles: Sequence[Candle]) -> List[float]:
    out: List[float] = []
    for prev, cur in zip(candles, candles[1:]):
        out.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    """Wilder's ATR -- the unit every stop and target in this system is sized in."""
    trs = true_ranges(candles)
    if len(trs) < period:
        return None
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def swing_points(candles: Sequence[Candle], lookback: int = 2) -> Dict[str, List[float]]:
    """Fractal swing highs and lows, confirmed ``lookback`` bars either side."""
    highs: List[float] = []
    lows: List[float] = []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback : i + lookback + 1]
        pivot = candles[i]
        if pivot.high == max(c.high for c in window) and pivot.high > candles[i - 1].high:
            highs.append(pivot.high)
        if pivot.low == min(c.low for c in window) and pivot.low < candles[i - 1].low:
            lows.append(pivot.low)
    return {"highs": highs, "lows": lows}


def donchian(candles: Sequence[Candle], period: int = 20) -> Optional[Dict[str, float]]:
    if len(candles) < period:
        return None
    window = candles[-period:]
    high = max(c.high for c in window)
    low = min(c.low for c in window)
    return {"upper": high, "lower": low, "mid": (high + low) / 2.0}


def structure(candles: Sequence[Candle], lookback: int = 2) -> str:
    """Crude market structure read from the last two confirmed swings."""
    swings = swing_points(candles, lookback)
    highs, lows = swings["highs"], swings["lows"]
    if len(highs) < 2 or len(lows) < 2:
        return "indeterminate"
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return "uptrend"
    if lh and ll:
        return "downtrend"
    return "range"


def trend_state(closes: Sequence[float], fast: int = 20, slow: int = 50) -> str:
    f, s = ema(closes, fast), ema(closes, slow)
    if f is None or s is None:
        return "indeterminate"
    spread_pct = (f - s) / s * 100.0
    if spread_pct > 0.15:
        return "bullish"
    if spread_pct < -0.15:
        return "bearish"
    return "neutral"


@dataclass
class TimeframeFeatures:
    timeframe: str
    close: float
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None
    rsi14: Optional[float] = None
    atr14: Optional[float] = None
    atr_pct: Optional[float] = None
    donchian20: Optional[Dict[str, float]] = None
    structure: str = "indeterminate"
    trend: str = "indeterminate"
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    bars: int = 0

    def to_dict(self) -> Dict[str, object]:
        def r(x, n=2):
            return round(x, n) if isinstance(x, (int, float)) else x

        return {
            "timeframe": self.timeframe,
            "close": r(self.close),
            "ema20": r(self.ema20),
            "ema50": r(self.ema50),
            "ema200": r(self.ema200),
            "rsi14": r(self.rsi14, 1),
            "atr14": r(self.atr14),
            "atr_pct": r(self.atr_pct, 3),
            "donchian20": {k: r(v) for k, v in self.donchian20.items()} if self.donchian20 else None,
            "structure": self.structure,
            "trend": self.trend,
            "swing_high": r(self.swing_high),
            "swing_low": r(self.swing_low),
            "bars": self.bars,
        }


def features_for(series: Series) -> TimeframeFeatures:
    candles = series.candles
    closes = series.closes
    swings = swing_points(candles)
    atr14 = atr(candles, 14)
    close = candles[-1].close
    return TimeframeFeatures(
        timeframe=series.timeframe,
        close=close,
        ema20=ema(closes, 20),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi14=rsi(closes, 14),
        atr14=atr14,
        atr_pct=(atr14 / close * 100.0) if atr14 and close else None,
        donchian20=donchian(candles, 20),
        structure=structure(candles),
        trend=trend_state(closes),
        swing_high=swings["highs"][-1] if swings["highs"] else None,
        swing_low=swings["lows"][-1] if swings["lows"] else None,
        bars=len(candles),
    )


@dataclass
class FeatureSet:
    """The full deterministic read handed to the analyst and stored in the journal."""

    spot: float
    per_timeframe: Dict[str, TimeframeFeatures] = field(default_factory=dict)
    smc: Dict[str, SmcRead] = field(default_factory=dict)
    session: Optional[SessionRead] = None

    def primary(self, preferred: str = "h1") -> Optional[TimeframeFeatures]:
        return self.per_timeframe.get(preferred) or next(iter(self.per_timeframe.values()), None)

    def alignment(self) -> str:
        """Do the timeframes agree? Disagreement is a reason to size down."""
        trends = {f.trend for f in self.per_timeframe.values() if f.trend != "indeterminate"}
        if not trends:
            return "unknown"
        if trends == {"bullish"}:
            return "aligned_bullish"
        if trends == {"bearish"}:
            return "aligned_bearish"
        if trends <= {"neutral"}:
            return "neutral"
        return "conflicted"

    def smc_alignment(self) -> str:
        """Do the timeframes agree on structural bias?"""
        biases = {r.bias for r in self.smc.values() if r.bias != "unknown"}
        if not biases:
            return "unknown"
        if len(biases) == 1:
            return f"aligned_{biases.pop()}"
        return "conflicted"

    def to_dict(self) -> Dict[str, object]:
        return {
            "spot": round(self.spot, 2),
            "alignment": self.alignment(),
            "smc_alignment": self.smc_alignment(),
            "timeframes": {tf: f.to_dict() for tf, f in self.per_timeframe.items()},
            "smc": {tf: r.to_dict() for tf, r in self.smc.items()},
            "session": self.session.to_dict() if self.session else None,
        }

    def as_prompt_block(self) -> str:
        lines = [
            f"Spot: {self.spot:.2f}",
            f"EMA trend alignment: {self.alignment()}",
            f"SMC structural alignment: {self.smc_alignment()}",
        ]
        for tf, f in self.per_timeframe.items():
            parts = [
                f"close {f.close:.2f}",
                f"EMA20 {f.ema20:.2f}" if f.ema20 else "EMA20 n/a",
                f"EMA50 {f.ema50:.2f}" if f.ema50 else "EMA50 n/a",
                f"EMA200 {f.ema200:.2f}" if f.ema200 else "EMA200 n/a",
                f"RSI14 {f.rsi14:.1f}" if f.rsi14 else "RSI14 n/a",
                f"ATR14 {f.atr14:.2f} ({f.atr_pct:.2f}%)" if f.atr14 else "ATR14 n/a",
                f"structure {f.structure}",
                f"trend {f.trend}",
            ]
            if f.donchian20:
                parts.append(
                    f"20-bar range {f.donchian20['lower']:.2f}-{f.donchian20['upper']:.2f}"
                )
            if f.swing_high:
                parts.append(f"last swing high {f.swing_high:.2f}")
            if f.swing_low:
                parts.append(f"last swing low {f.swing_low:.2f}")
            lines.append(f"  [{tf.upper()}, {f.bars} bars] " + ", ".join(parts))

        if self.smc:
            lines.append("")
            lines.append("STRUCTURE (Smart Money Concepts, computed)")
            for tf in self.per_timeframe:
                if tf in self.smc:
                    lines.extend(self.smc[tf].as_prompt_lines(self.spot))
        if self.session:
            lines.append("")
            lines.append("SESSION")
            lines.append(self.session.as_prompt_block(self.spot))
        return "\n".join(lines)


def build_features(snapshot, now: Optional[datetime] = None) -> FeatureSet:
    """Indicators, structure and session context from one market snapshot."""
    usable = {tf: s for tf, s in snapshot.series.items() if len(s) >= 2}
    moment = now or snapshot.as_of
    # Session ranges come off the finest timeframe available.
    finest = (
        min(usable.values(), key=lambda s: timeframe_minutes(s.timeframe)) if usable else None
    )
    return FeatureSet(
        spot=snapshot.spot,
        per_timeframe={tf: features_for(s) for tf, s in usable.items()},
        smc={tf: read_structure(s.candles, tf) for tf, s in usable.items()},
        session=read_sessions(finest.candles, moment) if finest else None,
    )
