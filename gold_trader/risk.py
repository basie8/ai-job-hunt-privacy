"""Single-instrument trade risk controls for XAUUSD.

The portfolio engine in ``investment_pipeline`` sizes a book by weight. A gold
trade is sized by stop distance instead: you decide what you are willing to lose,
the stop decides where you are wrong, and the position size falls out of the two.
Everything here is deterministic and runs after the model has spoken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .journal import Journal
from .learning import LearningState
from .macro import BlackoutPolicy, MacroCalendar


@dataclass(frozen=True)
class TradingLimits:
    account_usd: float = 100_000.0
    #: Risked on one trade, before any learned reduction.
    risk_per_trade_pct: float = 0.5
    #: Stop trading for the day once cumulative realised loss hits this many R.
    max_daily_loss_r: float = 2.0
    max_open_positions: int = 2
    max_signals_per_day: int = 4
    min_reward_risk: float = 1.5
    #: Stop distance must sit inside this band, measured in ATR.
    min_stop_atr_mult: float = 0.6
    max_stop_atr_mult: float = 3.0
    #: Refuse to act on prices older than this.
    max_staleness_min: int = 90
    #: A level read off a screenshot cannot support a high-conviction call.
    manual_source_max_conviction: float = 0.5
    blackout: BlackoutPolicy = field(default_factory=BlackoutPolicy)

    @property
    def base_risk_usd(self) -> float:
        return self.account_usd * self.risk_per_trade_pct / 100.0

    def as_prompt_block(self) -> str:
        return (
            f"- Account: ${self.account_usd:,.0f}; base risk per trade "
            f"{self.risk_per_trade_pct:.2f}% (${self.base_risk_usd:,.0f})\n"
            f"- Minimum reward:risk {self.min_reward_risk:.2f}\n"
            f"- Stop distance must be between {self.min_stop_atr_mult:.1f}x and "
            f"{self.max_stop_atr_mult:.1f}x ATR\n"
            f"- Max {self.max_open_positions} open positions, "
            f"{self.max_signals_per_day} signals per day\n"
            f"- Daily stop: trading halts at -{self.max_daily_loss_r:.1f}R realised\n"
            f"- Entry blackout: {self.blackout.before_high}min before / "
            f"{self.blackout.after_high}min after a high-impact release\n"
            f"- Prices older than {self.max_staleness_min}min are not actionable"
        )


@dataclass(frozen=True)
class Breach:
    code: str
    severity: str  # "hard" | "warning"
    detail: str

    def to_dict(self) -> Dict[str, object]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass
class RiskDecision:
    approved: bool
    direction: str
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    size_units: float = 0.0
    risk_usd: float = 0.0
    reward_risk: Optional[float] = None
    conviction: float = 0.0
    breaches: List[Breach] = field(default_factory=list)
    multipliers: Dict[str, float] = field(default_factory=dict)

    @property
    def hard_breaches(self) -> List[Breach]:
        return [b for b in self.breaches if b.severity == "hard"]

    def to_dict(self) -> Dict[str, object]:
        return {
            "approved": self.approved,
            "direction": self.direction,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "size_units": round(self.size_units, 4),
            "risk_usd": round(self.risk_usd, 2),
            "reward_risk": round(self.reward_risk, 3) if self.reward_risk else None,
            "conviction": round(self.conviction, 4),
            "multipliers": {k: round(v, 4) for k, v in self.multipliers.items()},
            "breaches": [b.to_dict() for b in self.breaches],
        }


def realised_r_today(journal: Journal, now: datetime) -> float:
    today = now.date().isoformat()
    total = 0.0
    for record in journal.closed():
        if (record.exit_ts or "")[:10] == today:
            total += record.r_multiple or 0.0
    return total


def signals_today(journal: Journal, now: datetime) -> int:
    today = now.date().isoformat()
    return sum(1 for r in journal.records if r.ts[:10] == today and r.direction != "flat")


def evaluate(
    *,
    direction: str,
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    conviction: float,
    setup_type: str,
    atr: Optional[float],
    spot: float,
    data_source: str,
    staleness_min: float,
    now: datetime,
    limits: TradingLimits,
    calendar: MacroCalendar,
    journal: Journal,
    learning: LearningState,
) -> RiskDecision:
    """Every gate, applied in order. A hard breach means no trade, full stop."""
    now = now.astimezone(timezone.utc)
    breaches: List[Breach] = []
    decision = RiskDecision(
        approved=False, direction=direction, entry=entry, stop=stop, target=target,
        conviction=conviction,
    )

    if direction == "flat":
        decision.breaches.append(Breach("NO_SIGNAL", "warning", "The analyst proposed no trade."))
        return decision

    # -- data quality ----------------------------------------------------
    if staleness_min > limits.max_staleness_min:
        breaches.append(
            Breach(
                "STALE_PRICES",
                "hard",
                f"Price data is {staleness_min:.0f} minutes old against a "
                f"{limits.max_staleness_min}-minute limit. Not actionable.",
            )
        )
    if data_source == "manual" and conviction > limits.manual_source_max_conviction:
        conviction = limits.manual_source_max_conviction
        breaches.append(
            Breach(
                "MANUAL_SOURCE_CAP",
                "warning",
                f"Levels were read by hand, so conviction is capped at "
                f"{limits.manual_source_max_conviction:.2f}.",
            )
        )

    # -- event blackout ---------------------------------------------------
    blocker = calendar.blackout(now, limits.blackout)
    if blocker:
        breaches.append(
            Breach(
                "EVENT_BLACKOUT",
                "hard",
                f"{blocker.name} is {blocker.minutes_until(now):+.0f} minutes away; "
                f"new entries are blocked inside its window.",
            )
        )
    if calendar.confidence in ("stale", "derived_only"):
        breaches.append(
            Breach(
                "CALENDAR_INCOMPLETE",
                "warning",
                f"Event calendar is {calendar.confidence}; an unlisted release may be pending.",
            )
        )

    # -- session budgets --------------------------------------------------
    realised = realised_r_today(journal, now)
    if realised <= -abs(limits.max_daily_loss_r):
        breaches.append(
            Breach(
                "DAILY_LOSS_LIMIT",
                "hard",
                f"Realised {realised:+.2f}R today against a -{limits.max_daily_loss_r:.1f}R "
                "daily stop. Done for the day.",
            )
        )
    open_count = len(journal.open_signals())
    if open_count >= limits.max_open_positions:
        breaches.append(
            Breach(
                "MAX_OPEN_POSITIONS",
                "hard",
                f"{open_count} positions already open against a limit of "
                f"{limits.max_open_positions}.",
            )
        )
    if signals_today(journal, now) >= limits.max_signals_per_day:
        breaches.append(
            Breach(
                "SIGNAL_BUDGET",
                "hard",
                f"{limits.max_signals_per_day} signals already issued today.",
            )
        )

    # -- learned gates ----------------------------------------------------
    if setup_type in learning.blocked_setups():
        breaches.append(
            Breach(
                "SETUP_BLOCKED_BY_RECORD",
                "hard",
                f"Setup {setup_type!r} has a measured negative expectancy over "
                f"{learning.setups[setup_type].n} trades and is blocked.",
            )
        )

    # -- trade geometry ---------------------------------------------------
    if entry is None or stop is None:
        breaches.append(Breach("MISSING_LEVELS", "hard", "Entry and stop are both required."))
        decision.breaches = breaches
        return decision

    long = direction == "long"
    if (long and stop >= entry) or (not long and stop <= entry):
        breaches.append(
            Breach("STOP_WRONG_SIDE", "hard", f"A {direction} stop at {stop} cannot sit on the wrong side of entry {entry}.")
        )
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        breaches.append(Breach("ZERO_STOP", "hard", "Stop distance is zero."))
        decision.breaches = breaches
        return decision

    if target is not None:
        if (long and target <= entry) or (not long and target >= entry):
            breaches.append(
                Breach("TARGET_WRONG_SIDE", "hard", f"A {direction} target at {target} is not beyond entry {entry}.")
            )
        else:
            rr = abs(target - entry) / stop_distance
            decision.reward_risk = rr
            if rr < limits.min_reward_risk:
                breaches.append(
                    Breach(
                        "REWARD_RISK_TOO_LOW",
                        "hard",
                        f"Reward:risk {rr:.2f} is below the {limits.min_reward_risk:.2f} minimum.",
                    )
                )
    else:
        breaches.append(Breach("NO_TARGET", "hard", "A target is required to size the trade."))

    if atr:
        mult = stop_distance / atr
        if mult < limits.min_stop_atr_mult:
            breaches.append(
                Breach(
                    "STOP_TOO_TIGHT",
                    "hard",
                    f"Stop is {mult:.2f}x ATR, inside the {limits.min_stop_atr_mult:.1f}x floor; "
                    "it would be noise-stopped.",
                )
            )
        elif mult > limits.max_stop_atr_mult:
            breaches.append(
                Breach(
                    "STOP_TOO_WIDE",
                    "hard",
                    f"Stop is {mult:.2f}x ATR, beyond the {limits.max_stop_atr_mult:.1f}x ceiling.",
                )
            )
    else:
        breaches.append(
            Breach("NO_ATR", "warning", "No ATR available, so stop width could not be sanity-checked.")
        )

    if entry and spot and abs(entry - spot) / spot > 0.02:
        breaches.append(
            Breach(
                "ENTRY_FAR_FROM_SPOT",
                "hard",
                f"Entry {entry:.2f} is more than 2% from spot {spot:.2f}.",
            )
        )

    # -- sizing -----------------------------------------------------------
    conviction_mult = learning.conviction_multiplier()
    size_mult = learning.size_multiplier(setup_type)
    adjusted_conviction = max(0.0, min(1.0, conviction * conviction_mult))
    risk_usd = limits.base_risk_usd * size_mult
    size_units = risk_usd / stop_distance

    decision.conviction = adjusted_conviction
    decision.risk_usd = risk_usd
    decision.size_units = size_units
    decision.multipliers = {
        "conviction_from_calibration": conviction_mult,
        "size_from_setup_record": size_mult,
    }
    decision.breaches = breaches
    decision.approved = not any(b.severity == "hard" for b in breaches)
    if not decision.approved:
        decision.size_units = 0.0
        decision.risk_usd = 0.0
    return decision
