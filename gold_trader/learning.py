"""Learning from the journal.

This is the feedback loop, and it is deliberately unglamorous. No weights are
updated and nothing rewrites its own code. What happens instead:

1. Closed trades are scored: win rate, expectancy in R, and calibration
   (did a stated conviction of 0.8 actually win 80% of the time?).
2. Those measurements are compiled into a lessons block that the analyst stage
   reads *before* it forms a view, so the model sees its own track record.
3. The measurements also drive multipliers that the code applies mechanically
   afterwards, so a model that says "0.9 conviction" on a setup that has lost
   money does not get to act on it.

Three guards keep this from becoming curve-fitting:

* **Learning can only reduce risk.** Every size multiplier is capped at 1.0.
  A good run never increases position size; only the base risk setting does.
* **Minimum samples.** Nothing adjusts until a setup has ``min_samples`` closed
  trades, and a setup is only blocked outright on twice that.
* **Walk-forward.** Statistics used for gating are fit on the older portion of
  the journal and reported against the newer one, so the numbers driving the
  clamps are not the same trades that produced them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .journal import Journal, SignalRecord

Z95 = 1.959963984540054


def wilson_lower_bound(wins: int, n: int, z: float = Z95) -> float:
    """Lower bound of the 95% CI on a win rate. Honest about small samples."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


@dataclass
class SetupStats:
    setup_type: str
    n: int
    wins: int
    total_r: float

    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / self.n if self.n else None

    @property
    def expectancy_r(self) -> Optional[float]:
        return self.total_r / self.n if self.n else None

    @property
    def win_rate_lower(self) -> float:
        return wilson_lower_bound(self.wins, self.n)

    def to_dict(self) -> Dict[str, object]:
        return {
            "setup_type": self.setup_type,
            "n": self.n,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "win_rate_lower_95": round(self.win_rate_lower, 4),
            "expectancy_r": round(self.expectancy_r, 4) if self.expectancy_r is not None else None,
            "total_r": round(self.total_r, 3),
        }


@dataclass
class Calibration:
    n: int
    mean_conviction: Optional[float]
    realized_win_rate: Optional[float]
    brier: Optional[float]
    bins: List[Dict[str, object]] = field(default_factory=list)

    @property
    def overconfidence(self) -> Optional[float]:
        if self.mean_conviction is None or self.realized_win_rate is None:
            return None
        return self.mean_conviction - self.realized_win_rate

    def to_dict(self) -> Dict[str, object]:
        return {
            "n": self.n,
            "mean_conviction": round(self.mean_conviction, 4) if self.mean_conviction else None,
            "realized_win_rate": round(self.realized_win_rate, 4)
            if self.realized_win_rate is not None
            else None,
            "overconfidence": round(self.overconfidence, 4)
            if self.overconfidence is not None
            else None,
            "brier": round(self.brier, 4) if self.brier is not None else None,
            "bins": self.bins,
        }


def calibration_of(records: Sequence[SignalRecord]) -> Calibration:
    scored = [r for r in records if r.r_multiple is not None]
    if not scored:
        return Calibration(0, None, None, None, [])
    outcomes = [1.0 if (r.r_multiple or 0) > 0 else 0.0 for r in scored]
    convictions = [max(0.0, min(1.0, r.conviction)) for r in scored]
    brier = sum((c - o) ** 2 for c, o in zip(convictions, outcomes)) / len(scored)

    edges = [(0.0, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]
    bins = []
    for lo, hi in edges:
        members = [(c, o) for c, o in zip(convictions, outcomes) if lo <= c < hi]
        if not members:
            continue
        bins.append(
            {
                "range": f"{lo:.2f}-{min(hi, 1.0):.2f}",
                "n": len(members),
                "mean_conviction": round(sum(c for c, _ in members) / len(members), 4),
                "realized_win_rate": round(sum(o for _, o in members) / len(members), 4),
            }
        )
    return Calibration(
        n=len(scored),
        mean_conviction=sum(convictions) / len(convictions),
        realized_win_rate=sum(outcomes) / len(outcomes),
        brier=brier,
        bins=bins,
    )


def setup_stats(records: Sequence[SignalRecord]) -> Dict[str, SetupStats]:
    buckets: Dict[str, SetupStats] = {}
    for r in records:
        if r.r_multiple is None:
            continue
        stats = buckets.setdefault(r.setup_type, SetupStats(r.setup_type, 0, 0, 0.0))
        stats.n += 1
        stats.wins += 1 if r.r_multiple > 0 else 0
        stats.total_r += r.r_multiple
    return buckets


def walk_forward_split(
    records: Sequence[SignalRecord], train_frac: float = 0.7
) -> Tuple[List[SignalRecord], List[SignalRecord]]:
    """Oldest ``train_frac`` fits the clamps; the newest portion checks them."""
    ordered = sorted(records, key=lambda r: r.ts)
    if len(ordered) < 10:
        return list(ordered), []
    cut = int(len(ordered) * train_frac)
    return ordered[:cut], ordered[cut:]


@dataclass
class LearningState:
    """Everything learned from the journal, and the clamps it implies."""

    min_samples: int = 20
    closed_n: int = 0
    calibration: Calibration = field(default_factory=lambda: Calibration(0, None, None, None, []))
    setups: Dict[str, SetupStats] = field(default_factory=dict)
    holdout_calibration: Optional[Calibration] = None
    holdout_n: int = 0

    # -- the clamps ------------------------------------------------------
    def conviction_multiplier(self) -> float:
        """Shrink stated conviction toward what actually happened.

        Only shrinks. A model that has been *under*confident does not get a
        boost, because a small sample of lucky wins is not evidence of skill.
        """
        cal = self.calibration
        if cal.n < self.min_samples or cal.overconfidence is None:
            return 1.0
        if cal.overconfidence <= 0.05:
            return 1.0
        if not cal.mean_conviction:
            return 1.0
        return max(0.5, min(1.0, (cal.realized_win_rate or 0.0) / cal.mean_conviction))

    def size_multiplier(self, setup_type: str) -> float:
        """Per-setup risk scaler, capped at 1.0 -- learning never sizes up."""
        stats = self.setups.get(setup_type)
        if stats is None or stats.n < self.min_samples:
            return 1.0
        expectancy = stats.expectancy_r or 0.0
        if expectancy >= 0.0 and stats.win_rate_lower >= 0.35:
            return 1.0
        if expectancy < -0.20 and stats.n >= 2 * self.min_samples:
            return 0.25
        if expectancy < 0.0:
            return 0.5
        return 0.75

    def blocked_setups(self) -> List[str]:
        """Setups with enough evidence that they lose money to stop trading."""
        return sorted(
            name
            for name, s in self.setups.items()
            if s.n >= 2 * self.min_samples and (s.expectancy_r or 0.0) < -0.20
        )

    def status(self) -> str:
        if self.closed_n == 0:
            return "cold_start"
        if self.closed_n < self.min_samples:
            return "warming_up"
        return "active"

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status(),
            "closed_n": self.closed_n,
            "min_samples": self.min_samples,
            "conviction_multiplier": round(self.conviction_multiplier(), 4),
            "blocked_setups": self.blocked_setups(),
            "calibration": self.calibration.to_dict(),
            "holdout_n": self.holdout_n,
            "holdout_calibration": self.holdout_calibration.to_dict()
            if self.holdout_calibration
            else None,
            "setups": {k: v.to_dict() for k, v in sorted(self.setups.items())},
            "size_multipliers": {k: self.size_multiplier(k) for k in sorted(self.setups)},
        }

    # -- what the model reads --------------------------------------------
    def lessons_block(self) -> str:
        """The track record, written for the analyst stage to read first."""
        if self.status() == "cold_start":
            return (
                "TRACK RECORD: none yet. No closed trades have been journalled, so there is no "
                "evidence about which setups work here. Size conservatively, prefer the clearest "
                "setups, and state low conviction until a record exists."
            )

        lines = [f"TRACK RECORD: {self.closed_n} closed trades."]
        if self.status() == "warming_up":
            lines.append(
                f"  Sample is below the {self.min_samples}-trade threshold, so these numbers are "
                "indicative only and no automatic adjustment is active yet. Do not over-read them."
            )

        cal = self.calibration
        if cal.realized_win_rate is not None and cal.mean_conviction is not None:
            lines.append(
                f"  Calibration: mean stated conviction {cal.mean_conviction:.2f} vs realized "
                f"win rate {cal.realized_win_rate:.2f} (Brier {cal.brier:.3f})."
            )
            if (cal.overconfidence or 0) > 0.05:
                multiplier = self.conviction_multiplier()
                effect = (
                    f"Your stated conviction is being multiplied by {multiplier:.2f} downstream."
                    if multiplier < 1.0
                    else "No automatic adjustment is active yet (sample still below threshold)."
                )
                lines.append(
                    f"  You have been OVERCONFIDENT by {cal.overconfidence:.2f}. {effect} "
                    "State conviction you can defend, not conviction you hope for."
                )
            elif (cal.overconfidence or 0) < -0.05:
                lines.append(
                    "  You have been underconfident. No boost is applied (a small sample of wins "
                    "is not evidence of skill), but do not talk yourself out of clean setups."
                )

        if self.setups:
            lines.append("  By setup type:")
            for name, s in sorted(self.setups.items(), key=lambda kv: -(kv[1].expectancy_r or 0)):
                verdict = ""
                if s.n >= self.min_samples:
                    if (s.expectancy_r or 0) < -0.20:
                        verdict = "  <- losing money; require materially stronger evidence"
                    elif (s.expectancy_r or 0) > 0.20:
                        verdict = "  <- your best edge so far"
                lines.append(
                    f"    {name}: {s.n} trades, {(s.win_rate or 0):.0%} win "
                    f"(95% lower bound {s.win_rate_lower:.0%}), "
                    f"expectancy {(s.expectancy_r or 0):+.2f}R{verdict}"
                )

        blocked = self.blocked_setups()
        if blocked:
            lines.append(
                f"  BLOCKED by the risk layer on measured performance: {', '.join(blocked)}. "
                "Do not propose these; if you believe the regime has changed, say so in your "
                "rationale and propose a playbook change instead of a trade."
            )

        if self.holdout_calibration and self.holdout_n:
            hc = self.holdout_calibration
            lines.append(
                f"  Out-of-sample check ({self.holdout_n} most recent trades): realized win rate "
                f"{(hc.realized_win_rate or 0):.2f}. If this is far below the in-sample figure, "
                "the earlier lessons are not generalising."
            )
        return "\n".join(lines)


def learn(journal: Journal, min_samples: int = 20, train_frac: float = 0.7) -> LearningState:
    closed = journal.closed()
    train, holdout = walk_forward_split(closed, train_frac)
    return LearningState(
        min_samples=min_samples,
        closed_n=len(closed),
        calibration=calibration_of(train or closed),
        setups=setup_stats(train or closed),
        holdout_calibration=calibration_of(holdout) if holdout else None,
        holdout_n=len(holdout),
    )
