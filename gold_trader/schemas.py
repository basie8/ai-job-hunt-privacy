"""Schema-constrained outputs for the four gold stages."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Bias = Literal["long", "short", "flat"]
#: The learning loop buckets performance by these, so they are the vocabulary
#: the whole system reasons in. Changing them resets per-setup statistics.
SetupType = Literal[
    "bos_continuation",          # break of structure, entering the continuation
    "choch_reversal",            # change of character, entering the reversal
    "ob_retest",                 # retest of an unmitigated order block
    "fvg_fill",                  # entry into an unmitigated fair value gap
    "liquidity_sweep_reversal",  # stops taken beyond a swing, close back inside
    "range_fade",                # fading a session or consolidation range
    "event_fade",                # post-release reversion once the spike settles
    "no_setup",
]
Regime = Literal["trending_up", "trending_down", "range_bound", "event_driven", "unclear"]


class ChartRead(BaseModel):
    """Stage 1 -- what the price action and the macro diary say."""

    bias: Bias
    regime: Regime
    setup_type: SetupType
    conviction: float = Field(ge=0.0, le=1.0, description="Evidence-weighted, not enthusiasm.")
    entry: Optional[float] = Field(default=None, description="Null when bias is flat.")
    stop: Optional[float] = Field(default=None, description="Where the idea is wrong. Null when flat.")
    target: Optional[float] = Field(default=None, description="First objective. Null when flat.")
    technical_read: str = Field(description="What the computed features actually show.")
    macro_read: str = Field(description="How the event diary and dollar/rate backdrop bear on gold.")
    invalidation: str = Field(description="The observation that kills this idea.")
    key_levels: List[float] = Field(default_factory=list, max_length=8)
    data_concerns: List[str] = Field(
        default_factory=list, description="Missing or stale inputs that weaken this read."
    )


class RiskFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "hard"]
    detail: str


class RiskVerdict(BaseModel):
    """Stage 2 -- the veto gate. May tighten, never loosen."""

    verdict: Literal["approve", "approve_with_changes", "reject"]
    adjusted_stop: Optional[float] = None
    adjusted_target: Optional[float] = None
    adjusted_conviction: float = Field(ge=0.0, le=1.0)
    findings: List[RiskFinding] = Field(default_factory=list)
    commentary: str


class ExecutionPlan(BaseModel):
    """Stage 3 -- how the approved idea reaches the market."""

    action: Literal["buy", "sell", "no_trade"]
    order_type: Literal["market", "limit", "stop", "none"]
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    valid_hours: int = Field(default=8, ge=1, le=72, description="How long the level stays live.")
    notes: str


class TradeAlert(BaseModel):
    """Stage 4 -- the notification payload and the written record."""

    headline: str = Field(max_length=90, description="One line, notification-ready.")
    action_line: str = Field(description="e.g. 'BUY XAUUSD 4312.50, stop 4296.00, target 4345.00'.")
    body: str = Field(description="Two to five sentences a human can act on.")
    risk_line: str = Field(description="Size, dollar risk, and what would cancel the idea.")
    watch_items: List[str] = Field(default_factory=list, max_length=6)
    learning_note: str = Field(
        default="",
        description="What this run's track record implies, if anything changed.",
    )
