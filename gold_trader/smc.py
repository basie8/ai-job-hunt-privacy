"""Smart Money Concepts, computed deterministically.

SMC vocabulary is not rigorously standardised -- practitioners define CHoCH,
inducement and order blocks differently. This module commits to one explicit
interpretation, documents it, and computes it the same way every time. The point
is not to be canonical; it is that the analyst stage reasons over a *stable*
structural read instead of re-eyeballing a chart and getting a different answer
on each run.

Definitions used here
---------------------
swing      A fractal pivot: a high with ``lookback`` lower highs either side
           (or a low with higher lows).
BOS        Break of Structure. A close beyond the most recent swing in the
           direction of the prevailing bias. Continuation.
CHoCH      Change of Character. The first close beyond the most recent
           *protected* swing against the prevailing bias. Potential reversal.
FVG        Fair Value Gap. A three-candle imbalance where candle 1 and candle 3
           do not overlap; the untouched space between them is the gap.
OB         Order Block. The last opposing candle before the impulse that caused
           a BOS or CHoCH. Zone is that candle's full range.
sweep      Liquidity sweep. Price trades beyond a prior swing but closes back
           inside it -- stops taken, no acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from .feed import Candle

BULLISH = "bullish"
BEARISH = "bearish"


@dataclass(frozen=True)
class Swing:
    index: int
    ts: datetime
    price: float
    kind: str  # "high" | "low"

    def to_dict(self) -> Dict[str, object]:
        return {"ts": self.ts.isoformat(), "price": round(self.price, 2), "kind": self.kind}


@dataclass(frozen=True)
class StructureEvent:
    kind: str  # "BOS" | "CHoCH"
    direction: str
    index: int
    ts: datetime
    broken_level: float
    close: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "ts": self.ts.isoformat(),
            "broken_level": round(self.broken_level, 2),
            "close": round(self.close, 2),
        }


@dataclass(frozen=True)
class Zone:
    kind: str  # "FVG" | "OB"
    direction: str
    top: float
    bottom: float
    ts: datetime
    index: int
    mitigated: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return self.top - self.bottom

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def distance_from(self, price: float) -> float:
        """Zero inside the zone, otherwise the gap to its nearest edge."""
        if self.contains(price):
            return 0.0
        return self.bottom - price if price < self.bottom else price - self.top

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "top": round(self.top, 2),
            "bottom": round(self.bottom, 2),
            "ts": self.ts.isoformat(),
            "mitigated": self.mitigated,
        }


@dataclass(frozen=True)
class Sweep:
    direction: str  # "bullish" = lows swept, "bearish" = highs swept
    index: int
    ts: datetime
    swept_level: float
    extreme: float
    close: float

    @property
    def penetration(self) -> float:
        return abs(self.extreme - self.swept_level)

    def to_dict(self) -> Dict[str, object]:
        return {
            "direction": self.direction,
            "ts": self.ts.isoformat(),
            "swept_level": round(self.swept_level, 2),
            "extreme": round(self.extreme, 2),
            "close": round(self.close, 2),
            "penetration": round(self.penetration, 2),
        }


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def find_swings(candles: Sequence[Candle], lookback: int = 2) -> List[Swing]:
    """Fractal pivots, oldest first. A pivot needs ``lookback`` bars either side."""
    swings: List[Swing] = []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback : i + lookback + 1]
        pivot = candles[i]
        if pivot.high >= max(c.high for c in window) and pivot.high > candles[i - 1].high:
            swings.append(Swing(i, pivot.ts, pivot.high, "high"))
        elif pivot.low <= min(c.low for c in window) and pivot.low < candles[i - 1].low:
            swings.append(Swing(i, pivot.ts, pivot.low, "low"))
    return swings


def structure_events(
    candles: Sequence[Candle], lookback: int = 2
) -> List[StructureEvent]:
    """Walk the candles and label each structural break as BOS or CHoCH.

    Bias starts unknown. The first break in either direction sets it; after that
    a break with the bias is a BOS and a break against it is a CHoCH (which then
    flips the bias).
    """
    swings = find_swings(candles, lookback)
    if not swings:
        return []

    events: List[StructureEvent] = []
    bias: Optional[str] = None
    # The swing levels currently protecting each side, and where they were set.
    high_level: Optional[Swing] = None
    low_level: Optional[Swing] = None

    for i, candle in enumerate(candles):
        # Only swings already confirmed by this bar can be broken by it.
        for swing in swings:
            if swing.index + lookback > i:
                break
            if swing.kind == "high" and (high_level is None or swing.index > high_level.index):
                high_level = swing
            elif swing.kind == "low" and (low_level is None or swing.index > low_level.index):
                low_level = swing

        if high_level and candle.close > high_level.price:
            kind = "CHoCH" if bias == BEARISH else "BOS"
            events.append(
                StructureEvent(kind, BULLISH, i, candle.ts, high_level.price, candle.close)
            )
            bias = BULLISH
            high_level = None
        elif low_level and candle.close < low_level.price:
            kind = "CHoCH" if bias == BULLISH else "BOS"
            events.append(
                StructureEvent(kind, BEARISH, i, candle.ts, low_level.price, candle.close)
            )
            bias = BEARISH
            low_level = None

    return events


def fair_value_gaps(
    candles: Sequence[Candle], min_height: float = 0.0
) -> List[Zone]:
    """Three-candle imbalances. ``mitigated`` marks gaps price has since filled."""
    zones: List[Zone] = []
    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        if a.high < c.low and (c.low - a.high) > min_height:
            zones.append(Zone("FVG", BULLISH, top=c.low, bottom=a.high, ts=candles[i - 1].ts, index=i - 1))
        elif a.low > c.high and (a.low - c.high) > min_height:
            zones.append(Zone("FVG", BEARISH, top=a.low, bottom=c.high, ts=candles[i - 1].ts, index=i - 1))

    return [_mark_mitigated(z, candles) for z in zones]


def _mark_mitigated(zone: Zone, candles: Sequence[Candle]) -> Zone:
    """A zone is mitigated once price has traded back into it."""
    for candle in candles[zone.index + 2 :]:
        if candle.low <= zone.top and candle.high >= zone.bottom:
            return Zone(
                zone.kind, zone.direction, zone.top, zone.bottom, zone.ts, zone.index, mitigated=True
            )
    return zone


def order_blocks(candles: Sequence[Candle], lookback: int = 2) -> List[Zone]:
    """The last opposing candle before each structural break."""
    zones: List[Zone] = []
    for event in structure_events(candles, lookback):
        want_down = event.direction == BULLISH
        for j in range(event.index - 1, max(-1, event.index - 20), -1):
            candle = candles[j]
            is_down = candle.close < candle.open
            if is_down == want_down:
                zones.append(
                    Zone(
                        "OB",
                        event.direction,
                        top=candle.high,
                        bottom=candle.low,
                        ts=candle.ts,
                        index=j,
                    )
                )
                break
    return [_mark_mitigated(z, candles) for z in zones]


def liquidity_sweeps(
    candles: Sequence[Candle], lookback: int = 2, min_penetration: float = 0.0
) -> List[Sweep]:
    """Wicks beyond a prior swing that close back inside it."""
    swings = find_swings(candles, lookback)
    sweeps: List[Sweep] = []
    for i, candle in enumerate(candles):
        confirmed = [s for s in swings if s.index + lookback < i]
        if not confirmed:
            continue
        highs = [s for s in confirmed if s.kind == "high"]
        lows = [s for s in confirmed if s.kind == "low"]
        if highs:
            level = highs[-1].price
            if candle.high > level >= candle.close and (candle.high - level) > min_penetration:
                sweeps.append(Sweep(BEARISH, i, candle.ts, level, candle.high, candle.close))
        if lows:
            level = lows[-1].price
            if candle.low < level <= candle.close and (level - candle.low) > min_penetration:
                sweeps.append(Sweep(BULLISH, i, candle.ts, level, candle.low, candle.close))
    return sweeps


# ---------------------------------------------------------------------------
# The read handed to the analyst
# ---------------------------------------------------------------------------

@dataclass
class SmcRead:
    timeframe: str
    bias: str = "unknown"
    last_event: Optional[StructureEvent] = None
    recent_events: List[StructureEvent] = field(default_factory=list)
    unmitigated_zones: List[Zone] = field(default_factory=list)
    recent_sweeps: List[Sweep] = field(default_factory=list)
    swing_high: Optional[Swing] = None
    swing_low: Optional[Swing] = None

    def nearest_zone(self, price: float, direction: Optional[str] = None) -> Optional[Zone]:
        candidates = [
            z for z in self.unmitigated_zones if direction is None or z.direction == direction
        ]
        return min(candidates, key=lambda z: z.distance_from(price), default=None)

    def to_dict(self) -> Dict[str, object]:
        return {
            "timeframe": self.timeframe,
            "bias": self.bias,
            "last_event": self.last_event.to_dict() if self.last_event else None,
            "recent_events": [e.to_dict() for e in self.recent_events],
            "unmitigated_zones": [z.to_dict() for z in self.unmitigated_zones],
            "recent_sweeps": [s.to_dict() for s in self.recent_sweeps],
            "swing_high": self.swing_high.to_dict() if self.swing_high else None,
            "swing_low": self.swing_low.to_dict() if self.swing_low else None,
        }

    def as_prompt_lines(self, price: float) -> List[str]:
        lines = [f"  [{self.timeframe.upper()}] SMC bias: {self.bias}"]
        if self.last_event:
            e = self.last_event
            lines.append(
                f"    last structure: {e.kind} {e.direction} through {e.broken_level:.2f} "
                f"at {e.ts.isoformat(timespec='minutes')}"
            )
        else:
            lines.append("    last structure: none confirmed in this window")
        if self.swing_high and self.swing_low:
            lines.append(
                f"    protected swings: high {self.swing_high.price:.2f} / "
                f"low {self.swing_low.price:.2f}"
            )
        for zone in self.unmitigated_zones[:4]:
            distance = zone.distance_from(price)
            where = "price inside" if distance == 0 else f"{distance:.2f} away"
            lines.append(
                f"    unmitigated {zone.direction} {zone.kind} "
                f"{zone.bottom:.2f}-{zone.top:.2f} ({where})"
            )
        if not self.unmitigated_zones:
            lines.append("    no unmitigated FVG or order block in this window")
        for sweep in self.recent_sweeps[-2:]:
            lines.append(
                f"    liquidity sweep {sweep.direction}: took {sweep.swept_level:.2f}, "
                f"closed back at {sweep.close:.2f} ({sweep.penetration:.2f} penetration)"
            )
        return lines


def read_structure(
    candles: Sequence[Candle],
    timeframe: str,
    lookback: int = 2,
    max_zones: int = 6,
    recent_bars: int = 40,
) -> SmcRead:
    """Full SMC read for one timeframe."""
    if len(candles) < lookback * 2 + 3:
        return SmcRead(timeframe=timeframe)

    events = structure_events(candles, lookback)
    swings = find_swings(candles, lookback)
    cutoff = len(candles) - recent_bars

    # Consecutive structure breaks often resolve to the same preceding candle,
    # so the same order block can be found more than once. Showing it twice
    # wastes prompt space and makes one zone read as two confirmations.
    seen, zones = set(), []
    for zone in fair_value_gaps(candles) + order_blocks(candles, lookback):
        if zone.mitigated:
            continue
        key = (zone.kind, zone.direction, round(zone.top, 4), round(zone.bottom, 4))
        if key in seen:
            continue
        seen.add(key)
        zones.append(zone)
    zones.sort(key=lambda z: z.index, reverse=True)

    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]

    return SmcRead(
        timeframe=timeframe,
        bias=events[-1].direction if events else "unknown",
        last_event=events[-1] if events else None,
        recent_events=[e for e in events if e.index >= cutoff][-4:],
        unmitigated_zones=zones[:max_zones],
        recent_sweeps=[s for s in liquidity_sweeps(candles, lookback) if s.index >= cutoff][-3:],
        swing_high=highs[-1] if highs else None,
        swing_low=lows[-1] if lows else None,
    )
