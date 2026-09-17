"""Single-instrument trade risk controls for XAUUSD.

The portfolio engine in ``investment_pipeline`` sizes a book by weight. A gold
trade is sized by stop distance instead: you decide what you are willing to lose,
the stop decides where you are wrong, and the position size falls out of the two.
Everything here is deterministic and runs after the model has spoken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .journal import Journal
from .learning import LearningState
from .sessions import market_closed
from .macro import BlackoutPolicy, MacroCalendar


@dataclass(frozen=True)
class TradingLimits:
    #: "paper" is the only supported mode. Nothing in this repository can place
    #: an order, so every result is a simulated outcome against later candles.
    #: The field exists so the mode is stamped on every signal, alert and
    #: dashboard rather than being an unstated assumption.
    mode: str = "paper"
    #: Notional the paper book is sized against, in ``account_currency``. It
    #: scales the dollar figures only -- performance is measured in R, which is
    #: invariant to it.
    account_value: float = 10_000.0
    account_currency: str = "GBP"
    #: Gold is quoted in USD, so a non-USD notional needs a rate to size in
    #: ounces. Sizing mixes currencies without it, which is the kind of error
    #: that looks fine until the numbers matter.
    fx_to_usd: float = 1.3377
    #: Where and when the rate came from. Refreshed in the weekly review; the
    #: rate only scales displayed cash, so drift does not affect R.
    fx_as_of: str = "2026-09-17, GBPUSD mid ~1.3377 (day range 1.3350-1.3407)"
    #: Risked on one trade as a percent of CURRENT EQUITY (starting notional
    #: plus realised P&L), before any learned reduction. Fixed-fractional: the
    #: cash at risk shrinks after losses and grows after wins, while every trade
    #: still risks exactly 1R by definition, so the journal's R maths is
    #: unaffected.
    risk_per_trade_pct: float = 1.0
    #: Stop the book entirely once equity falls to this fraction of the starting
    #: notional. Fixed-fractional sizing never mathematically reaches zero, so
    #: without a floor a ruined book keeps trading in ever-smaller size and the
    #: record becomes meaningless.
    min_equity_pct_of_start: float = 60.0
    #: Stop trading for the day once cumulative realised loss hits this many R.
    max_daily_loss_r: float = 2.0
    max_open_positions: int = 2
    max_signals_per_day: int = 4
    min_reward_risk: float = 1.5
    #: Stop distance must sit inside this band, measured in ATR.
    min_stop_atr_mult: float = 0.6
    max_stop_atr_mult: float = 3.0
    #: Fallback band as a percent of spot, used when ATR cannot be computed
    #: (a hand-read level, or too few candles). Without this, losing ATR would
    #: silently remove the only stop-width check -- a 10-cent stop on $4300 gold
    #: would size 5000oz and be taken out by the spread.
    #:
    #: Calibrated against real XAUUSD (2026-09-17, spot 4362): the ATR band
    #: permits 0.12%-0.61% on M15 and 0.28%-1.40% on H1, so a fallback ceiling
    #: of 0.60% would have refused every legitimate H1 stop. The band now spans
    #: M15 through H1. H4 swing stops (up to 2.86% of spot) still fall outside
    #: it on purpose: a multi-day stop should not be set from a screenshot.
    min_stop_pct_of_spot: float = 0.12
    max_stop_pct_of_spot: float = 1.50
    #: Refuse to act on prices older than this.
    max_staleness_min: int = 90
    #: A level read off a screenshot cannot support a high-conviction call.
    manual_source_max_conviction: float = 0.5
    blackout: BlackoutPolicy = field(default_factory=BlackoutPolicy)

    @property
    def account_usd(self) -> float:
        """The notional in USD, which is what gold is sized against."""
        return self.account_value * self.fx_to_usd

    @property
    def base_risk(self) -> float:
        """Risk on the first trade, in the account's currency (no P&L yet)."""
        return self.account_value * self.risk_per_trade_pct / 100.0

    @property
    def base_risk_usd(self) -> float:
        """Risk on the first trade, in USD. Later trades size off equity."""
        return self.account_usd * self.risk_per_trade_pct / 100.0

    def as_prompt_block(self) -> str:
        return (
            f"- Mode: {self.mode.upper()} — outcomes are simulated against later candles, "
            "no orders are placed\n"
            f"- Paper account: {self.account_currency} {self.account_value:,.0f} "
            f"(${self.account_usd:,.0f} at {self.fx_to_usd:.4f}); base risk per trade "
            f"{self.risk_per_trade_pct:.2f}% of equity "
            f"(opening at {self.account_currency} {self.base_risk:,.0f} / "
            f"${self.base_risk_usd:,.0f})\n"
            f"- Minimum reward:risk {self.min_reward_risk:.2f}\n"
            f"- Stop distance must be between {self.min_stop_atr_mult:.1f}x and "
            f"{self.max_stop_atr_mult:.1f}x ATR, or between "
            f"{self.min_stop_pct_of_spot:.2f}% and {self.max_stop_pct_of_spot:.2f}% of spot "
            f"when no ATR is available\n"
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


def realised_pnl_usd(journal: Journal) -> float:
    """Closed P&L in USD: each trade's R multiple against the cash it risked.

    Risk is recorded per signal, so a trade taken when equity was larger
    contributes proportionally more -- which is what fixed-fractional sizing
    means and what a naive sum of R multiples would get wrong.
    """
    return sum((r.r_multiple or 0.0) * (r.risk_usd or 0.0) for r in journal.closed())


def equity_usd(journal: Journal, limits: "TradingLimits") -> float:
    return limits.account_usd + realised_pnl_usd(journal)


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

    # -- is there a market at all ----------------------------------------
    # Checked first, and in code rather than in a prompt. Until 2026-09-17 the
    # weekend was only mentioned to the analyst and the daily rollover was not
    # modelled at all, so nothing stopped a signal being issued into a shut
    # market. An entry nobody can take is worse than no entry: it is journalled,
    # resolved against candles that do not represent tradeable prices, and
    # quietly poisons the track record the learning loop is built on.
    closure = market_closed(now)
    if closure:
        detail = {
            "weekend": ("Gold is closed for the weekend (Friday 17:00 to Sunday "
                        "18:00 New York). No entry is possible."),
            "daily_break": ("Gold is in its daily rollover break (17:00-18:00 New "
                            "York). There is no tradeable market for the next hour, "
                            "and quotes either side of it are unreliable."),
        }[closure]
        breaches.append(Breach("MARKET_CLOSED", "hard", detail))

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
    if calendar.confidence in ("stale", "derived_only", "invalid"):
        breaches.append(
            Breach(
                "CALENDAR_INCOMPLETE",
                "warning",
                f"Event calendar is {calendar.confidence}"
                + (f" ({len(calendar.load_errors)} parse errors)" if calendar.load_errors else "")
                + "; an unlisted release may be pending.",
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

    # Stop width must always be checked against something. ATR is the good
    # measure; percent-of-spot is the fallback. Losing both is a hard block,
    # never a pass -- less information must mean more scrutiny, not less.
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
    elif spot and spot > 0:
        pct = stop_distance / spot * 100.0
        breaches.append(
            Breach(
                "NO_ATR",
                "info",
                f"No ATR available; stop width checked against the percent-of-spot band "
                f"({limits.min_stop_pct_of_spot:.2f}%-{limits.max_stop_pct_of_spot:.2f}%) instead.",
            )
        )
        if pct < limits.min_stop_pct_of_spot:
            breaches.append(
                Breach(
                    "STOP_TOO_TIGHT",
                    "hard",
                    f"Stop is {pct:.3f}% of spot ({stop_distance:.2f}), inside the "
                    f"{limits.min_stop_pct_of_spot:.2f}% floor; spread alone would take it out.",
                )
            )
        elif pct > limits.max_stop_pct_of_spot:
            breaches.append(
                Breach(
                    "STOP_TOO_WIDE",
                    "hard",
                    f"Stop is {pct:.3f}% of spot ({stop_distance:.2f}), beyond the "
                    f"{limits.max_stop_pct_of_spot:.2f}% ceiling.",
                )
            )
    else:
        breaches.append(
            Breach(
                "STOP_UNVERIFIABLE",
                "hard",
                "Neither ATR nor spot is available, so the stop width cannot be checked at all.",
            )
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

    equity = equity_usd(journal, limits)
    floor = limits.account_usd * limits.min_equity_pct_of_start / 100.0
    if equity <= floor:
        breaches.append(
            Breach(
                "EQUITY_FLOOR",
                "hard",
                f"Equity ${equity:,.0f} is at or below the "
                f"{limits.min_equity_pct_of_start:.0f}% floor (${floor:,.0f}). "
                "The paper book is done; review before restarting it.",
            )
        )
    risk_usd = max(0.0, equity) * limits.risk_per_trade_pct / 100.0 * size_mult
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
