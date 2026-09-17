"""Coherence checks on the risk configuration.

A limit set can be individually valid and collectively impossible -- a minimum
stop wider than the maximum makes every trade unreachable, and no single unit
test would notice because each value is fine on its own. These checks run in the
self-check and can be called directly after any limits change.
"""

from __future__ import annotations

from typing import List, Optional

from .macro import BlackoutPolicy
from .risk import TradingLimits


def coherence_problems(limits: Optional[TradingLimits] = None) -> List[str]:
    """Contradictions in a limit set. Empty means the configuration is usable."""
    limits = limits or TradingLimits()
    problems: List[str] = []

    if limits.min_stop_atr_mult >= limits.max_stop_atr_mult:
        problems.append(
            f"min_stop_atr_mult ({limits.min_stop_atr_mult}) is not below "
            f"max_stop_atr_mult ({limits.max_stop_atr_mult}); no stop could pass"
        )
    if limits.min_stop_pct_of_spot >= limits.max_stop_pct_of_spot:
        problems.append(
            f"min_stop_pct_of_spot ({limits.min_stop_pct_of_spot}) is not below "
            f"max_stop_pct_of_spot ({limits.max_stop_pct_of_spot})"
        )
    if limits.account_usd <= 0:
        problems.append("account_usd must be positive")
    if not 0 < limits.risk_per_trade_pct <= 100:
        problems.append(f"risk_per_trade_pct ({limits.risk_per_trade_pct}) is outside (0, 100]")
    if limits.max_daily_loss_r <= 0:
        problems.append("max_daily_loss_r must be positive")
    if limits.max_open_positions < 1:
        problems.append("max_open_positions must allow at least one trade")
    if limits.max_signals_per_day < 1:
        problems.append("max_signals_per_day must allow at least one signal")
    if limits.min_reward_risk <= 0:
        problems.append("min_reward_risk must be positive")
    if not 0 <= limits.manual_source_max_conviction <= 1:
        problems.append("manual_source_max_conviction must be a probability")
    if limits.max_staleness_min <= 0:
        problems.append("max_staleness_min must be positive")

    # The daily loss stop must be reachable before the position cap makes it
    # moot, otherwise one of the two controls is dead weight.
    max_losable_r = float(limits.max_signals_per_day)
    if limits.max_daily_loss_r > max_losable_r:
        problems.append(
            f"max_daily_loss_r ({limits.max_daily_loss_r}R) cannot be reached: at most "
            f"{limits.max_signals_per_day} signals a day means at most {max_losable_r}R of loss"
        )

    problems.extend(_blackout_problems(limits.blackout))
    return problems


def _blackout_problems(policy: BlackoutPolicy) -> List[str]:
    problems: List[str] = []
    for name, value in (
        ("before_high", policy.before_high),
        ("after_high", policy.after_high),
        ("before_medium", policy.before_medium),
        ("after_medium", policy.after_medium),
    ):
        if value < 0:
            problems.append(f"blackout.{name} cannot be negative")
    if policy.before_high < policy.before_medium:
        problems.append(
            "blackout window for high-impact events is narrower than for medium-impact ones"
        )
    if policy.after_high < policy.after_medium:
        problems.append(
            "post-event blackout for high-impact events is narrower than for medium-impact ones"
        )
    return problems
