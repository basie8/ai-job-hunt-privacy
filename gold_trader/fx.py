"""The account-currency rate, sourced from MT5 alongside the candles.

Gold is priced in USD and the paper book is denominated in GBP, so a rate is
needed to size in ounces. Hardcoding one means carrying a number that silently
goes stale; the terminal already supplies GBPUSD, so the bridge reads it at the
same time as the candles and writes it next to them.

The rate only scales displayed cash -- R is invariant to it -- so a stale rate is
a warning rather than a blocker. It is still reported, because a rate that has
not updated in a week usually means the bridge stopped, and that *is* worth
knowing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

FX_FILENAME = "fx.json"

#: Beyond this the rate is reported as stale. Generous on purpose: a day-old
#: GBPUSD moves the displayed cash by well under a percent.
STALE_AFTER_HOURS = 36


@dataclass(frozen=True)
class FxReading:
    pair: str
    rate: float
    as_of: str
    source: str

    def age_hours(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        try:
            stamped = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        return (now - stamped).total_seconds() / 3600.0

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        return self.age_hours(now) > STALE_AFTER_HOURS

    def provenance(self, now: Optional[datetime] = None) -> str:
        age = self.age_hours(now)
        age_text = "age unknown" if age == float("inf") else f"{age:.1f}h old"
        return f"{self.pair} {self.rate:.4f} from {self.source} ({age_text})"

    def to_dict(self, now: Optional[datetime] = None) -> Dict[str, object]:
        return {
            "pair": self.pair,
            "rate": self.rate,
            "as_of": self.as_of,
            "source": self.source,
            "age_hours": None if self.age_hours(now) == float("inf") else round(self.age_hours(now), 2),
            "stale": self.is_stale(now),
        }


def write_fx(directory: str, pair: str, rate: float, as_of: str, source: str) -> str:
    """Write (or merge into) the FX file the bridge produces."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, FX_FILENAME)
    blob: Dict[str, Dict[str, object]] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                blob = loaded
        except (json.JSONDecodeError, OSError):
            blob = {}
    blob[pair] = {"rate": float(rate), "as_of": as_of, "source": source}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def load_fx(directory: str, pair: str = "GBPUSD") -> Optional[FxReading]:
    """Read the bridge's rate. Returns None rather than raising or guessing."""
    path = os.path.join(directory, FX_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        entry = blob[pair]
        return FxReading(
            pair=pair,
            rate=float(entry["rate"]),
            as_of=str(entry["as_of"]),
            source=str(entry.get("source", "unknown")),
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None


#: A rate this far from the configured static one is treated as a misread
#: rather than a market move. GBPUSD has never moved 15% in a day, so a reading
#: that does has almost certainly resolved to the wrong MT5 symbol -- and a
#: wrong rate rescales the whole book.
MAX_DEVIATION_PCT = 15.0


def with_live_rate(limits, directory: str = "data", now: Optional[datetime] = None):
    """Prefer the bridge's MT5 rate over the static one baked into ``limits``.

    Returns ``(limits, note)``. The note is always populated and always worth
    printing: silently falling back to a hardcoded rate is exactly the failure
    this function exists to make visible.
    """
    import dataclasses

    currency = (limits.account_currency or "USD").upper()
    if currency == "USD":
        return limits, f"FX: account is USD, no rate needed (fx_to_usd {limits.fx_to_usd:.4f})"

    pair = f"{currency}USD"
    reading = load_fx(directory, pair=pair)
    if reading is None:
        return limits, (
            f"FX WARNING: no {pair} rate from the bridge in {directory}/{FX_FILENAME}; "
            f"using the static {limits.fx_to_usd:.4f} ({limits.fx_as_of}). "
            "Cash figures may be off; R is unaffected."
        )

    deviation = abs(reading.rate - limits.fx_to_usd) / limits.fx_to_usd * 100.0
    if reading.rate <= 0 or deviation > MAX_DEVIATION_PCT:
        return limits, (
            f"FX WARNING: bridge reported {pair} {reading.rate:.4f}, which is "
            f"{deviation:.1f}% from the static {limits.fx_to_usd:.4f} -- refusing it as a "
            f"misread symbol (source {reading.source}). Keeping the static rate."
        )

    note = f"FX: {reading.provenance(now)}"
    if reading.is_stale(now):
        note = (
            f"FX WARNING: {reading.provenance(now)} is older than {STALE_AFTER_HOURS}h "
            "-- the bridge may have stopped. Using it anyway; it beats the static rate."
        )
    return dataclasses.replace(limits, fx_to_usd=reading.rate, fx_as_of=reading.provenance(now)), note
