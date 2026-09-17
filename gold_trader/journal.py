"""The trade journal: every signal, and what actually happened to it.

Append-only JSONL, same discipline as the pipeline's audit log. A signal is
written the moment it is produced, with the full feature snapshot that produced
it, so an outcome can later be attributed to the conditions that were actually
present rather than to a remembered version of them.

Outcome resolution is deliberately pessimistic: when one candle's range covers
both the stop and the target, bar data cannot say which was touched first, so
the stop is assumed. Optimistic tie-breaking is how backtests learn to lie.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from .feed import Candle, Series

OPEN = "open"
WON = "won"
LOST = "lost"
BREAKEVEN = "breakeven"
EXPIRED = "expired"
CANCELLED = "cancelled"
CLOSED_STATES = (WON, LOST, BREAKEVEN, EXPIRED)


@dataclass
class SignalRecord:
    id: str
    ts: str
    direction: str  # "long" | "short" | "flat"
    setup_type: str
    conviction: float
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    size_units: float = 0.0
    risk_usd: float = 0.0
    regime: str = "unknown"
    rationale: str = ""
    invalidation: str = ""
    valid_until: Optional[str] = None
    features: Dict[str, object] = field(default_factory=dict)
    macro: Dict[str, object] = field(default_factory=dict)
    audit_run_id: Optional[str] = None
    data_source: str = "unknown"
    #: Stamped so a simulated result can never be mistaken for a real fill.
    mode: str = "paper"

    # Outcome, filled in later.
    status: str = OPEN
    exit_price: Optional[float] = None
    exit_ts: Optional[str] = None
    r_multiple: Optional[float] = None
    mae_r: Optional[float] = None
    mfe_r: Optional[float] = None
    resolution: Optional[str] = None

    @property
    def risk_per_unit(self) -> Optional[float]:
        if self.entry is None or self.stop is None:
            return None
        distance = abs(self.entry - self.stop)
        return distance if distance > 0 else None

    def r_of(self, price: float) -> Optional[float]:
        per_unit = self.risk_per_unit
        if per_unit is None:
            return None
        move = price - self.entry if self.direction == "long" else self.entry - price
        return move / per_unit

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class Journal:
    """JSONL-backed signal store with an in-memory materialised view."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self.records: List[SignalRecord] = []
        if path:
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            if os.path.exists(path):
                self._load()

    def _load(self) -> None:
        by_id: Dict[str, SignalRecord] = {}
        order: List[str] = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                kind = entry.get("kind")
                payload = entry.get("payload", {})
                if kind == "signal":
                    record = SignalRecord(**payload)
                    by_id[record.id] = record
                    order.append(record.id)
                elif kind == "outcome":
                    existing = by_id.get(payload.get("id"))
                    if existing:
                        for key, value in payload.items():
                            if key != "id" and hasattr(existing, key):
                                setattr(existing, key, value)
        self.records = [by_id[i] for i in order]

    def _append(self, kind: str, payload: Dict[str, object]) -> None:
        if not self.path:
            return
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "kind": kind,
                        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "payload": payload,
                    },
                    default=str,
                )
                + "\n"
            )

    def add(self, record: SignalRecord) -> SignalRecord:
        self.records.append(record)
        self._append("signal", record.to_dict())
        return record

    def new_signal(self, **kwargs) -> SignalRecord:
        kwargs.setdefault("id", uuid.uuid4().hex[:12])
        kwargs.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return self.add(SignalRecord(**kwargs))

    def update_outcome(self, record: SignalRecord, **changes) -> SignalRecord:
        for key, value in changes.items():
            setattr(record, key, value)
        payload = {"id": record.id, **changes}
        self._append("outcome", payload)
        return record

    # -- views -----------------------------------------------------------
    def open_signals(self) -> List[SignalRecord]:
        return [r for r in self.records if r.status == OPEN and r.direction != "flat"]

    def closed(self) -> List[SignalRecord]:
        return [r for r in self.records if r.status in CLOSED_STATES and r.r_multiple is not None]

    def by_setup(self, setup_type: str) -> List[SignalRecord]:
        return [r for r in self.closed() if r.setup_type == setup_type]

    def summary(self) -> Dict[str, object]:
        closed = self.closed()
        wins = [r for r in closed if r.r_multiple and r.r_multiple > 0]
        total_r = sum(r.r_multiple or 0.0 for r in closed)
        return {
            "total_signals": len(self.records),
            "open": len(self.open_signals()),
            "closed": len(closed),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(closed), 4) if closed else None,
            "total_r": round(total_r, 3),
            "expectancy_r": round(total_r / len(closed), 3) if closed else None,
        }


def resolve_against(
    record: SignalRecord, candles: Sequence[Candle], now: Optional[datetime] = None
) -> Optional[Dict[str, object]]:
    """Walk candles after entry and decide the outcome.

    Returns the outcome changes, or ``None`` if the trade is still open.
    A candle spanning both stop and target resolves as a loss: bar data cannot
    order intrabar touches, so the unfavourable branch is assumed.
    """
    if record.direction == "flat" or record.entry is None or record.stop is None:
        return None
    per_unit = record.risk_per_unit
    if per_unit is None:
        return None

    entry_ts = datetime.fromisoformat(record.ts.replace("Z", "+00:00"))
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.replace(tzinfo=timezone.utc)
    forward = [c for c in candles if c.ts > entry_ts]
    if not forward:
        return None

    long = record.direction == "long"
    mae_r = 0.0
    mfe_r = 0.0

    for candle in forward:
        adverse = candle.low if long else candle.high
        favourable = candle.high if long else candle.low
        mae_r = min(mae_r, record.r_of(adverse) or 0.0)
        mfe_r = max(mfe_r, record.r_of(favourable) or 0.0)

        hit_stop = candle.low <= record.stop if long else candle.high >= record.stop
        hit_target = (
            record.target is not None
            and (candle.high >= record.target if long else candle.low <= record.target)
        )

        if hit_stop:
            return {
                "status": LOST,
                "exit_price": record.stop,
                "exit_ts": candle.ts.isoformat(),
                "r_multiple": round(record.r_of(record.stop) or -1.0, 4),
                "mae_r": round(mae_r, 4),
                "mfe_r": round(mfe_r, 4),
                "resolution": "stop_and_target_same_bar" if hit_target else "stop_hit",
            }
        if hit_target:
            return {
                "status": WON,
                "exit_price": record.target,
                "exit_ts": candle.ts.isoformat(),
                "r_multiple": round(record.r_of(record.target) or 0.0, 4),
                "mae_r": round(mae_r, 4),
                "mfe_r": round(mfe_r, 4),
                "resolution": "target_hit",
            }

    if record.valid_until:
        expiry = datetime.fromisoformat(record.valid_until.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        last = forward[-1]
        if last.ts >= expiry:
            r = record.r_of(last.close) or 0.0
            return {
                "status": EXPIRED,
                "exit_price": last.close,
                "exit_ts": last.ts.isoformat(),
                "r_multiple": round(r, 4),
                "mae_r": round(mae_r, 4),
                "mfe_r": round(mfe_r, 4),
                "resolution": "expired_at_close",
            }
    return None


def resolve_all(journal: Journal, series: Series) -> List[SignalRecord]:
    """Resolve every open signal it can against a candle series."""
    resolved: List[SignalRecord] = []
    for record in journal.open_signals():
        changes = resolve_against(record, series.candles)
        if changes:
            journal.update_outcome(record, **changes)
            resolved.append(record)
    return resolved
