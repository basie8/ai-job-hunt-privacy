"""Structured payloads exchanged between pipeline stages.

Every model call in this pipeline is schema-constrained: each stage returns one
of these types via ``output_config.format``, so the next stage consumes data
rather than prose. Keep the field sets narrow -- they double as the JSON schema
the API validates against.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Side = Literal["buy", "sell", "short", "cover"]
AssetClass = Literal["equity", "etf", "fx", "rates", "credit", "commodity"]
Severity = Literal["info", "warning", "hard"]


# --------------------------------------------------------------------------
# Stage 1: Analyst
# --------------------------------------------------------------------------

class TradeIdea(BaseModel):
    symbol: str = Field(description="Ticker or instrument identifier, uppercase.")
    asset_class: AssetClass
    sector: str = Field(description="Sector or risk bucket, e.g. 'technology', 'rates'.")
    side: Side
    conviction: float = Field(ge=0.0, le=1.0, description="0-1 confidence in the thesis.")
    target_weight_pct: float = Field(
        ge=0.0, le=100.0, description="Requested position size as % of NAV, always positive."
    )
    horizon_days: int = Field(ge=1, le=750)
    thesis: str = Field(description="Two to four sentences on why this trade works now.")
    catalysts: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    invalidation: str = Field(description="The observation that would kill this thesis.")


class AnalystOutput(BaseModel):
    regime: Literal["risk_on", "risk_off", "neutral", "transitioning"]
    regime_rationale: str
    market_summary: str
    ideas: List[TradeIdea] = Field(default_factory=list)
    data_gaps: List[str] = Field(
        default_factory=list,
        description="Inputs that were missing or stale enough to weaken the analysis.",
    )


# --------------------------------------------------------------------------
# Stage 2: Risk manager
# --------------------------------------------------------------------------

class RiskFinding(BaseModel):
    code: str = Field(description="Short stable identifier, e.g. 'CONCENTRATION'.")
    severity: Severity
    symbol: Optional[str] = None
    detail: str
    recommended_action: str


class RiskAdjustment(BaseModel):
    symbol: str
    approved: bool
    approved_weight_pct: float = Field(
        ge=0.0, le=100.0, description="0 when the idea is rejected outright."
    )
    reason: str


class RiskManagerOutput(BaseModel):
    verdict: Literal["approve", "approve_with_changes", "reject"]
    portfolio_commentary: str
    findings: List[RiskFinding] = Field(default_factory=list)
    adjustments: List[RiskAdjustment] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Stage 3: Executor
# --------------------------------------------------------------------------

class OrderIntent(BaseModel):
    symbol: str
    side: Side
    target_notional_usd: float = Field(ge=0.0)
    order_type: Literal["market", "limit", "vwap", "twap", "pov"]
    limit_price: Optional[float] = Field(
        default=None, description="Required for limit orders, null otherwise."
    )
    time_in_force: Literal["day", "gtc", "ioc", "opg", "cls"]
    slice_count: int = Field(ge=1, le=50, description="Child orders to split the parent into.")
    participation_rate_pct: Optional[float] = Field(
        default=None, ge=0.0, le=50.0, description="For pov orders; null otherwise."
    )
    rationale: str = Field(description="Why this execution style for this order.")


class ExecutorOutput(BaseModel):
    orders: List[OrderIntent] = Field(default_factory=list)
    total_gross_notional_usd: float = Field(ge=0.0)
    execution_notes: str
    skipped: List[str] = Field(
        default_factory=list,
        description="Approved symbols that could not be turned into an order, with the reason.",
    )


# --------------------------------------------------------------------------
# Stage 4: Reporter
# --------------------------------------------------------------------------

class ReportDecision(BaseModel):
    symbol: str
    outcome: Literal["executed", "reduced", "rejected", "skipped"]
    detail: str


class ReporterOutput(BaseModel):
    headline: str
    executive_summary: str
    decisions: List[ReportDecision] = Field(default_factory=list)
    risk_highlights: List[str] = Field(default_factory=list)
    follow_ups: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Inputs (validated locally, never model-generated)
# --------------------------------------------------------------------------

class Position(BaseModel):
    symbol: str
    asset_class: AssetClass
    sector: str
    weight_pct: float = Field(description="Signed: negative for shorts.")


class Portfolio(BaseModel):
    nav_usd: float = Field(gt=0.0)
    cash_pct: float = Field(ge=-100.0, le=100.0)
    drawdown_pct: float = Field(
        ge=0.0, le=100.0, description="Current drawdown from high-water mark."
    )
    positions: List[Position] = Field(default_factory=list)

    def weight_of(self, symbol: str) -> float:
        return sum(p.weight_pct for p in self.positions if p.symbol == symbol)

    def gross_exposure_pct(self) -> float:
        return sum(abs(p.weight_pct) for p in self.positions)

    def net_exposure_pct(self) -> float:
        return sum(p.weight_pct for p in self.positions)

    def sector_of(self, symbol: str) -> Optional[str]:
        for p in self.positions:
            if p.symbol == symbol:
                return p.sector
        return None

    def sector_weights(self) -> dict:
        out: dict = {}
        for p in self.positions:
            out[p.sector] = out.get(p.sector, 0.0) + abs(p.weight_pct)
        return out


class MarketSignal(BaseModel):
    source: str
    symbol: Optional[str] = None
    headline: str
    detail: str = ""
    observed_at: Optional[str] = None


class PipelineInput(BaseModel):
    as_of: str
    portfolio: Portfolio
    signals: List[MarketSignal] = Field(default_factory=list)
    mandate: str = Field(
        default="Long/short multi-asset book with a medium-term horizon.",
        description="Investment mandate the analyst must respect.",
    )
