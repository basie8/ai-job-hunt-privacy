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

    #: When price first traded at the entry, or None while the order rests.
    #:
    #: Persisted rather than recomputed. resolve_against derives it by walking
    #: candles, but the candle files hold a rolling window -- once the filling
    #: bar ages out of the CSV, a trade that really was entered would read as
    #: never filled and silently stop being scored. A fact this important must
    #: be written down the first time it is known.
    filled_at: Optional[str] = None

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
        """Everything still unresolved: resting orders and live positions both."""
        return [r for r in self.records if r.status == OPEN and r.direction != "flat"]

    def resting(self) -> List[SignalRecord]:
        """Orders price has not reached. No money is at risk in these."""
        return [r for r in self.open_signals() if r.filled_at is None]

    def live(self) -> List[SignalRecord]:
        """Positions actually entered. These are the ones carrying risk."""
        return [r for r in self.open_signals() if r.filled_at is not None]

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

    A signal is only live once price has traded at its entry. Until then it is
    a resting order, and nothing about it can win or lose.

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

    # A fill already on the record is authoritative. Re-deriving it every run
    # would lose it as soon as the filling bar rolls out of the candle window.
    filled = record.filled_at is not None
    filled_at: Optional[str] = record.filled_at
    if filled:
        fill_ts = datetime.fromisoformat(record.filled_at.replace("Z", "+00:00"))
        if fill_ts.tzinfo is None:
            fill_ts = fill_ts.replace(tzinfo=timezone.utc)
        forward = [c for c in forward if c.ts >= fill_ts]

    for candle in forward:
        # Nothing happens until price actually trades at the entry.
        #
        # Without this the book scored every signal as if it were filled the
        # instant it was written, and the error is one-sided: a stop always
        # sits beyond the entry, so price must pass through the entry to reach
        # it and a loss is always genuinely filled -- but a target can be
        # reached without price ever coming back to the entry at all. So the
        # omission manufactures wins and never manufactures losses.
        #
        # The first signal this system ever produced, on 2026-09-18, was a
        # limit at 4353.00 with spot at 4358.81 and a target at 4374.00. Gold
        # rising straight from 4358 to 4374 would have booked +1.56R on a trade
        # nobody was ever in. An optimistic bias in the very first data point,
        # compounding into every clamp the learning loop later derives from it.
        if not filled:
            if not (candle.low <= record.entry <= candle.high):
                continue
            filled = True
            filled_at = candle.ts.isoformat()
            # Fall through: the bar that fills can also stop out, and the
            # unfavourable branch is assumed for the same reason as below --
            # bar data cannot order intrabar touches.

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
                "filled_at": filled_at,
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
                "filled_at": filled_at,
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
        if last.ts >= expiry and not filled:
            # An idea price never reached is not a trade, and must not be
            # counted as one. CANCELLED is outside CLOSED_STATES, so it stays
            # out of the win rate, the expectancy and every per-setup sample --
            # a run of unfilled limits should shrink the sample, not pad it
            # with zeroes that drag expectancy toward nothing.
            return {
                "status": CANCELLED,
                "exit_price": None,
                "exit_ts": last.ts.isoformat(),
                "r_multiple": None,
                "mae_r": 0.0,
                "mfe_r": 0.0,
                "resolution": "expired_unfilled",
            }
        if last.ts >= expiry:
            r = record.r_of(last.close) or 0.0
            return {
                "status": EXPIRED,
                "filled_at": filled_at,
                "exit_price": last.close,
                "exit_ts": last.ts.isoformat(),
                "r_multiple": round(r, 4),
                "mae_r": round(mae_r, 4),
                "mfe_r": round(mfe_r, 4),
                "resolution": "expired_at_close",
            }

    # Unresolved -- but if the order filled during this walk, that is a change
    # worth writing down even though the trade is still running. Returning None
    # here would discard it and the order would keep reading as resting while a
    # real position sat open.
    if filled_at != record.filled_at:
        return {"filled_at": filled_at}
    return None


def resolve_all(journal: Journal, series: Series,
                max_live: Optional[int] = None) -> List[SignalRecord]:
    """Resolve every open signal it can against a candle series.

    ``max_live`` enforces the live-position cap at the moment of fill, which is
    the only place it can actually be enforced. The risk engine checks the cap
    when a signal is *written*, and that is not enough: orders rest, and
    several resting orders can fill before any of them resolves. With a limit
    of two live positions and four working orders, all four could fill and
    leave 4R at risk under a limit that says 2 -- a limit raised without anyone
    deciding to raise it.

    An order that would breach the cap is cancelled rather than filled, which
    is what a desk with a position limit actually does. Cancelled sits outside
    CLOSED_STATES, so it never enters the track record: it was never a trade,
    and counting it as a flat outcome would dilute the sample with events that
    say nothing about whether the setup works.
    """
    resolved: List[SignalRecord] = []
    for record in journal.open_signals():
        changes = resolve_against(record, series.candles)
        if not changes:
            continue

        newly_filled = (changes.get("filled_at") is not None
                        and record.filled_at is None)
        if newly_filled and max_live is not None and len(journal.live()) >= max_live:
            journal.update_outcome(
                record,
                status=CANCELLED,
                exit_ts=changes.get("filled_at"),
                resolution="live_cap_reached",
            )
            resolved.append(record)
            continue

        journal.update_outcome(record, **changes)
        # A fill is persisted but is not a resolution: the trade is still
        # running. Reporting it as resolved would announce a closed trade that
        # has not closed, and every caller here formats an R multiple that a
        # fill does not have.
        if record.status != OPEN:
            resolved.append(record)
    return resolved
