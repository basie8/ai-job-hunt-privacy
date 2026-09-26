"""Macro event awareness for gold.

Gold's sharpest moves cluster around a short list of scheduled US releases, so
the event calendar is a risk control before it is an analysis input: entries are
blocked inside a blackout window around high-impact prints, in code, regardless
of what the analyst thinks of the setup.

Two kinds of events:

* **Derivable** -- Non-Farm Payrolls (first Friday, 08:30 ET) and initial
  jobless claims (Thursdays, 08:30 ET) follow rules, so they are computed.
* **Scheduled** -- FOMC decisions, CPI, PPI and PCE do not follow a rule you can
  safely derive, so they are read from ``state/calendar.json``. When that file
  is missing or its horizon has run out, ``calendar_confidence`` drops to
  ``"stale"`` and the pipeline treats every session as if an unknown event may
  be pending rather than assuming the diary is clear.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

try:  # pragma: no cover - platform dependent
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = None

HIGH_IMPACT = ("FOMC", "NFP", "CPI", "PCE", "FOMC_MINUTES", "POWELL")
MEDIUM_IMPACT = ("PPI", "RETAIL_SALES", "ISM", "GDP", "CLAIMS")

#: Why each release moves gold. Injected into the analyst prompt so the model
#: reasons about transmission, not just "there is an event".
DRIVER_NOTES = {
    "FOMC": "Rate path and dot plot drive real yields and the dollar; gold is short real yields.",
    "FOMC_MINUTES": "Re-prices the rate path at the margin; smaller but same direction of effect.",
    "POWELL": "Unscheduled guidance; can reprice the path as hard as the decision itself.",
    "NFP": "Labour strength lifts real yields and the dollar, usually gold-negative; misses cut both.",
    "CPI": "Inflation surprises move real yields; the nominal-vs-real split decides gold's sign.",
    "PCE": "The Fed's preferred gauge; same channel as CPI with a slower market reaction.",
    "PPI": "Leads CPI; second-order for gold.",
    "CLAIMS": "Weekly labour pulse; matters most when it confirms or contradicts the last NFP.",
    "RETAIL_SALES": "Growth proxy feeding the rate path.",
    "ISM": "Growth proxy feeding the rate path.",
    "GDP": "Backward-looking; matters when it shifts the rate path.",
}


@dataclass(frozen=True)
class MacroEvent:
    name: str
    kind: str
    when: datetime
    impact: str

    def minutes_until(self, now: datetime) -> float:
        return (self.when - now).total_seconds() / 60.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "when": self.when.isoformat(),
            "impact": self.impact,
        }


@dataclass(frozen=True)
class MacroReading:
    """A gold driver the caller supplied. Never invented, never guessed."""

    name: str
    value: str
    as_of: str
    source: str

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "value": self.value, "as_of": self.as_of, "source": self.source}


@dataclass(frozen=True)
class BlackoutPolicy:
    """Entry blackout around scheduled releases, in minutes."""

    before_high: int = 60
    after_high: int = 30
    before_medium: int = 15
    after_medium: int = 10

    def window_for(self, impact: str) -> tuple:
        if impact == "high":
            return self.before_high, self.after_high
        if impact == "medium":
            return self.before_medium, self.after_medium
        return 0, 0


def _et_to_utc(day: date, hour: int, minute: int) -> datetime:
    if ET is None:  # pragma: no cover - fall back to EST if tzdata is missing
        return datetime(day.year, day.month, day.day, hour + 5, minute, tzinfo=timezone.utc)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


def nfp_dates(start: date, months: int = 3) -> List[date]:
    """First Friday of each month from ``start``'s month forward."""
    out: List[date] = []
    year, month = start.year, start.month
    for _ in range(months):
        day = date(year, month, 1)
        while day.weekday() != 4:  # Friday
            day += timedelta(days=1)
        out.append(day)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def claims_dates(start: date, weeks: int = 6) -> List[date]:
    """Thursdays from ``start`` forward."""
    day = start
    while day.weekday() != 3:  # Thursday
        day += timedelta(days=1)
    return [day + timedelta(weeks=w) for w in range(weeks)]


@dataclass
class MacroCalendar:
    events: List[MacroEvent] = field(default_factory=list)
    confidence: str = "derived_only"
    scheduled_horizon: Optional[str] = None
    readings: List[MacroReading] = field(default_factory=list)
    #: Parse problems in the hand-edited calendar file. Non-empty means some
    #: events were dropped and the blackout windows are narrower than intended.
    load_errors: List[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        now: datetime,
        scheduled_path: Optional[str] = None,
        horizon_days: int = 21,
    ) -> "MacroCalendar":
        now = now.astimezone(timezone.utc)
        today = now.date()
        events: List[MacroEvent] = []

        for day in nfp_dates(today, months=2):
            events.append(
                MacroEvent("Non-Farm Payrolls", "NFP", _et_to_utc(day, 8, 30), "high")
            )
        for day in claims_dates(today, weeks=4):
            events.append(
                MacroEvent("Initial Jobless Claims", "CLAIMS", _et_to_utc(day, 8, 30), "medium")
            )

        confidence = "derived_only"
        horizon: Optional[str] = None
        readings: List[MacroReading] = []

        errors: List[str] = []
        if scheduled_path and os.path.exists(scheduled_path):
            # This file is hand-edited every week, so it WILL be malformed at
            # some point. A bad row must degrade the calendar, never take down
            # a scheduled run: one dropped event is a narrower blackout window,
            # a raised exception is no signal at all.
            blob = None
            try:
                with open(scheduled_path, encoding="utf-8") as fh:
                    blob = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"could not read {os.path.basename(scheduled_path)}: {exc}")

            if not isinstance(blob, dict):
                if blob is not None:
                    errors.append("calendar file is not a JSON object")
                blob = {}

            horizon = blob.get("covers_through")
            for index, raw in enumerate(blob.get("events") or []):
                try:
                    when = datetime.fromisoformat(str(raw["when"]).replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    kind = str(raw["kind"]).upper()
                    events.append(
                        MacroEvent(raw.get("name", kind), kind, when, raw.get("impact", "high"))
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"event {index}: {exc}")

            for index, raw in enumerate(blob.get("readings") or []):
                try:
                    readings.append(
                        MacroReading(
                            raw["name"], str(raw["value"]), raw["as_of"],
                            raw.get("source", "supplied"),
                        )
                    )
                except (KeyError, TypeError) as exc:
                    errors.append(f"reading {index}: {exc}")

            if errors:
                confidence = "invalid"
            elif horizon:
                try:
                    covers = datetime.fromisoformat(str(horizon).replace("Z", "+00:00"))
                    if covers.tzinfo is None:
                        covers = covers.replace(tzinfo=timezone.utc)
                    confidence = "current" if covers >= now else "stale"
                except (TypeError, ValueError) as exc:
                    errors.append(f"covers_through: {exc}")
                    confidence = "invalid"
            else:
                confidence = "stale"

        cutoff = now + timedelta(days=horizon_days)
        events = sorted(
            (e for e in events if now - timedelta(hours=6) <= e.when <= cutoff),
            key=lambda e: e.when,
        )
        return cls(
            events=events, confidence=confidence, scheduled_horizon=horizon,
            readings=readings, load_errors=errors,
        )

    def upcoming(self, now: datetime, within_hours: int = 48) -> List[MacroEvent]:
        limit = now + timedelta(hours=within_hours)
        return [e for e in self.events if now <= e.when <= limit]

    def blackout(self, now: datetime, policy: BlackoutPolicy) -> Optional[MacroEvent]:
        """The event currently blocking new entries, if any."""
        for event in self.events:
            before, after = policy.window_for(event.impact)
            delta = event.minutes_until(now)
            if -after <= delta <= before:
                return event
        return None

    def as_prompt_block(self, now: datetime) -> str:
        lines = [f"Calendar confidence: {self.confidence}"]
        if self.load_errors:
            lines.append(
                "  WARNING: the calendar file failed to parse cleanly, so some events were "
                "dropped and the blackout windows are narrower than intended:"
            )
            for err in self.load_errors[:5]:
                lines.append(f"    - {err}")
        if self.confidence == "stale":
            lines.append(
                "  WARNING: the scheduled-event file is out of date. FOMC/CPI/PCE dates may be "
                "missing. Treat the diary as unknown and require a wider margin of safety."
            )
        elif self.confidence == "derived_only":
            lines.append(
                "  WARNING: only NFP and jobless claims are derived. No FOMC/CPI/PCE dates are "
                "loaded. Treat the diary as incomplete."
            )
        upcoming = self.upcoming(now, within_hours=72)
        if upcoming:
            lines.append("Next 72 hours:")
            for e in upcoming:
                hours = e.minutes_until(now) / 60.0
                note = DRIVER_NOTES.get(e.kind, "")
                lines.append(f"  - T{hours:+.1f}h {e.name} [{e.impact}] {note}")
        else:
            lines.append("No scheduled events in the next 72 hours (per the loaded calendar).")
        if self.readings:
            lines.append("Supplied gold drivers:")
            for r in self.readings:
                lines.append(f"  - {r.name}: {r.value} (as of {r.as_of}, {r.source})")
        else:
            lines.append(
                "No DXY / real-yield / positioning readings were supplied. Do not assume values "
                "for them; reason only from what is here and flag the gap."
            )
        return "\n".join(lines)

    def to_dict(self, now: datetime) -> Dict[str, object]:
        return {
            "confidence": self.confidence,
            "load_errors": self.load_errors,
            "scheduled_horizon": self.scheduled_horizon,
            "upcoming": [e.to_dict() for e in self.upcoming(now, 72)],
            "readings": [r.to_dict() for r in self.readings],
        }
