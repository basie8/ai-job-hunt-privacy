"""The four-stage orchestrator: signal in, risk-checked orders and a report out.

    Analyst (Opus 5, high)      market signals        -> sized trade ideas
    Risk Manager (Opus 5, max)  ideas + limit engine  -> approved, clamped book
    Executor (Sonnet 5, low)    approved book         -> order intents
    Reporter (Haiku 4.5)        audit trail           -> the written record

Between stage 2 and stage 3 sits the part that is deliberately not a model:
``_enforce`` intersects the risk manager's judgement with the deterministic
engine's ceilings and takes the tighter of the two, every time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from . import prompts, risk
from .audit import AuditLog, sha256_of
from .config import (
    ANALYST,
    EXECUTOR,
    REPORTER,
    RISK_MANAGER,
    PipelineConfig,
)
from .llm import StageClient, run_stage
from .schemas import (
    AnalystOutput,
    ExecutorOutput,
    OrderIntent,
    PipelineInput,
    ReporterOutput,
    RiskManagerOutput,
)

#: Weights below this (in % of NAV) are not worth an order ticket.
MIN_ACTIONABLE_WEIGHT_PCT = 0.01


@dataclass
class ApprovedTrade:
    symbol: str
    side: str
    asset_class: str
    sector: str
    weight_pct: float
    notional_usd: float
    engine_ceiling_pct: float
    analyst_request_pct: float
    risk_manager_pct: Optional[float]
    binding_constraint: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    run_id: str
    analyst: Optional[AnalystOutput] = None
    screen: Optional[risk.RiskScreen] = None
    risk_manager: Optional[RiskManagerOutput] = None
    approved: List[ApprovedTrade] = field(default_factory=list)
    executor: Optional[ExecutorOutput] = None
    orders: List[OrderIntent] = field(default_factory=list)
    rejected_orders: List[Dict[str, Any]] = field(default_factory=list)
    report: Optional[ReporterOutput] = None
    halted_reason: Optional[str] = None
    audit: Optional[AuditLog] = None

    def cost_usd(self) -> float:
        return self.audit.total_cost_usd() if self.audit else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "halted_reason": self.halted_reason,
            "analyst": self.analyst.model_dump() if self.analyst else None,
            "risk_screen": self.screen.to_dict() if self.screen else None,
            "risk_manager": self.risk_manager.model_dump() if self.risk_manager else None,
            "approved": [t.to_dict() for t in self.approved],
            "orders": [o.model_dump() for o in self.orders],
            "rejected_orders": self.rejected_orders,
            "report": self.report.model_dump() if self.report else None,
            "audit": self.audit.summary() if self.audit else None,
        }


# ---------------------------------------------------------------------------
# Prompt bodies (volatile context; kept out of the cached system prefix)
# ---------------------------------------------------------------------------

def _portfolio_block(data: PipelineInput) -> str:
    p = data.portfolio
    rows = (
        "\n".join(
            f"  {pos.symbol} ({pos.asset_class}/{pos.sector}): {pos.weight_pct:+.2f}% of NAV"
            for pos in p.positions
        )
        or "  (no open positions)"
    )
    return (
        f"NAV: ${p.nav_usd:,.0f}\n"
        f"Cash: {p.cash_pct:.2f}% of NAV\n"
        f"Gross exposure: {p.gross_exposure_pct():.2f}% | "
        f"Net exposure: {p.net_exposure_pct():+.2f}%\n"
        f"Drawdown from high-water mark: {p.drawdown_pct:.2f}%\n"
        f"Positions:\n{rows}"
    )


def build_analyst_message(data: PipelineInput) -> str:
    signals = "\n".join(
        f"- [{s.source}{'/' + s.symbol if s.symbol else ''}"
        f"{' @ ' + s.observed_at if s.observed_at else ''}] {s.headline}"
        + (f"\n    {s.detail}" if s.detail else "")
        for s in data.signals
    ) or "- (no signals supplied)"
    return (
        f"As of: {data.as_of}\n\n"
        f"MANDATE\n{data.mandate}\n\n"
        f"PORTFOLIO\n{_portfolio_block(data)}\n\n"
        f"MARKET SIGNALS\n{signals}\n\n"
        "Produce your analysis and trade ideas."
    )


def build_risk_message(
    data: PipelineInput, analyst: AnalystOutput, screen: risk.RiskScreen, limits
) -> str:
    ideas = "\n".join(
        f"- {i.symbol} {i.side} {i.target_weight_pct:.2f}% "
        f"({i.asset_class}/{i.sector}, conviction {i.conviction:.2f}, "
        f"{i.horizon_days}d)\n"
        f"    thesis: {i.thesis}\n"
        f"    risks: {'; '.join(i.key_risks) or 'none stated'}\n"
        f"    invalidation: {i.invalidation}"
        for i in analyst.ideas
    ) or "- (the analyst proposed no trades)"

    engine = "\n".join(
        f"- {s.symbol}: requested {s.idea.target_weight_pct:.2f}% -> "
        f"engine allows {s.allowed_weight_pct:.2f}%"
        + (
            "\n    " + "\n    ".join(f"{b.severity.upper()} {b.code}: {b.detail}" for b in s.breaches)
            if s.breaches
            else ""
        )
        for s in screen.ideas
    ) or "- (nothing to screen)"

    portfolio_level = "\n".join(
        f"- {b.severity.upper()} {b.code}: {b.detail}" for b in screen.portfolio_breaches
    ) or "- (no portfolio-level breaches)"

    return (
        f"As of: {data.as_of}\n\n"
        f"MANDATE\n{data.mandate}\n\n"
        f"PORTFOLIO\n{_portfolio_block(data)}\n\n"
        f"EXPOSURE LIMITS\n{limits.as_prompt_block()}\n\n"
        f"MARKET REGIME (from the analyst)\n{analyst.regime}: {analyst.regime_rationale}\n\n"
        f"PROPOSED IDEAS\n{ideas}\n\n"
        f"DETERMINISTIC LIMIT ENGINE - PORTFOLIO LEVEL\n{portfolio_level}\n\n"
        f"DETERMINISTIC LIMIT ENGINE - PER IDEA (these weights are ceilings)\n{engine}\n\n"
        f"PROJECTED IF ALL ENGINE-ALLOWED IDEAS TRADE\n"
        f"gross {screen.projected_gross_pct:.2f}%, net {screen.projected_net_pct:+.2f}%, "
        f"cash {screen.projected_cash_pct:.2f}%, turnover {screen.turnover_pct:.2f}%\n\n"
        f"ANALYST DATA GAPS\n"
        + ("\n".join(f"- {g}" for g in analyst.data_gaps) or "- (none reported)")
        + "\n\nReview these ideas and return your verdict."
    )


def build_executor_message(data: PipelineInput, approved: List[ApprovedTrade]) -> str:
    book = "\n".join(
        f"- {t.symbol} {t.side} ${t.notional_usd:,.0f} "
        f"({t.weight_pct:.2f}% of NAV, {t.asset_class}/{t.sector})\n"
        f"    approved because: {t.reason}"
        for t in approved
    )
    return (
        f"As of: {data.as_of}\n"
        f"NAV: ${data.portfolio.nav_usd:,.0f}\n\n"
        f"APPROVED BOOK - execute exactly this, nothing more\n{book}\n\n"
        "Return the order intents."
    )


def build_reporter_message(data: PipelineInput, log: AuditLog) -> str:
    summary = log.summary()
    return (
        f"Run {log.run_id}, as of {data.as_of}.\n\n"
        f"AUDIT TRAIL\n{log.narrative()}\n\n"
        f"RUN TOTALS\n"
        f"records: {summary['records']}, "
        f"model spend: ${summary['total_cost_usd']:.4f}, "
        f"by stage: {json.dumps(summary['cost_by_stage'])}\n\n"
        "Write the run report."
    )


# ---------------------------------------------------------------------------
# Enforcement: the deterministic engine wins every disagreement
# ---------------------------------------------------------------------------

def _enforce(
    screen: risk.RiskScreen,
    verdict: RiskManagerOutput,
    nav_usd: float,
    log: AuditLog,
) -> List[ApprovedTrade]:
    adjustments = {a.symbol.upper(): a for a in verdict.adjustments}
    approved: List[ApprovedTrade] = []
    overrides: List[Dict[str, Any]] = []
    unreviewed: List[str] = []

    for s in screen.ideas:
        symbol = s.symbol.upper()
        ceiling = s.allowed_weight_pct
        adj = adjustments.get(symbol)

        if adj is None:
            # Silence is not approval: an idea the risk stage did not address
            # does not trade.
            unreviewed.append(symbol)
            continue

        if adj.approved_weight_pct > ceiling + 1e-6:
            overrides.append(
                {
                    "symbol": symbol,
                    "requested_by_risk_manager_pct": adj.approved_weight_pct,
                    "engine_ceiling_pct": round(ceiling, 6),
                    "detail": "Risk manager asked for more than the limit engine allows; clamped.",
                }
            )

        if verdict.verdict == "reject" or not adj.approved or s.blocked:
            continue

        final = min(adj.approved_weight_pct, ceiling)
        if final < MIN_ACTIONABLE_WEIGHT_PCT:
            continue

        # Which of the two gates actually did the trimming, for the report.
        if final >= s.idea.target_weight_pct - 1e-9:
            binding = "none"
        elif ceiling <= adj.approved_weight_pct + 1e-9:
            binding = "limit_engine"
        else:
            binding = "risk_manager"

        approved.append(
            ApprovedTrade(
                symbol=s.idea.symbol,
                side=s.idea.side,
                asset_class=s.idea.asset_class,
                sector=s.idea.sector,
                weight_pct=round(final, 6),
                notional_usd=round(nav_usd * final / 100.0, 2),
                engine_ceiling_pct=round(ceiling, 6),
                analyst_request_pct=s.idea.target_weight_pct,
                risk_manager_pct=adj.approved_weight_pct,
                binding_constraint=binding,
                reason=adj.reason,
            )
        )

    if overrides:
        log.record(RISK_MANAGER, "override_attempt", {"attempts": overrides})
    if unreviewed:
        log.record(
            RISK_MANAGER,
            "unreviewed_ideas",
            {"symbols": unreviewed, "detail": "Not addressed by the risk manager; not traded."},
        )
    log.record(
        RISK_MANAGER,
        "enforcement",
        {
            "verdict": verdict.verdict,
            "approved": [t.to_dict() for t in approved],
            "approved_count": len(approved),
            "approved_gross_pct": round(sum(t.weight_pct for t in approved), 4),
        },
    )
    return approved


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(
    data: PipelineInput,
    client: StageClient,
    config: Optional[PipelineConfig] = None,
    log: Optional[AuditLog] = None,
) -> PipelineResult:
    config = config or PipelineConfig()
    log = log or AuditLog(path=config.audit_log_path)
    tiers = config.model_tiers
    result = PipelineResult(run_id=log.run_id, audit=log)

    log.record(
        "pipeline",
        "run_started",
        {
            "as_of": data.as_of,
            "input_sha256": sha256_of(data.model_dump()),
            "nav_usd": data.portfolio.nav_usd,
            "model_tiers": {
                stage: {"model": spec.model_id, "effort": spec.effort}
                for stage, spec in tiers.items()
            },
            "limits": {
                k: (sorted(v) if isinstance(v, frozenset) else v)
                for k, v in config.limits.__dict__.items()
            },
        },
    )

    # -- Stage 1: Analyst ---------------------------------------------------
    analyst: AnalystOutput = run_stage(
        client,
        log,
        stage=ANALYST,
        spec=tiers[ANALYST],
        system=prompts.ANALYST_SYSTEM,
        user=build_analyst_message(data),
        output_format=AnalystOutput,
    )
    result.analyst = analyst
    log.record(
        ANALYST,
        "stage_output",
        {
            "regime": analyst.regime,
            "idea_count": len(analyst.ideas),
            "ideas": [
                {
                    "symbol": i.symbol,
                    "side": i.side,
                    "sector": i.sector,
                    "requested_weight_pct": i.target_weight_pct,
                    "conviction": i.conviction,
                }
                for i in analyst.ideas
            ],
            "data_gaps": analyst.data_gaps,
        },
    )

    # -- Deterministic screen (no model involved) ---------------------------
    screen = risk.screen(analyst.ideas, data.portfolio, config.limits)
    result.screen = screen
    log.record(RISK_MANAGER, "deterministic_screen", screen.to_dict())

    # -- Stage 2: Risk manager ---------------------------------------------
    verdict: RiskManagerOutput = run_stage(
        client,
        log,
        stage=RISK_MANAGER,
        spec=tiers[RISK_MANAGER],
        system=prompts.RISK_MANAGER_SYSTEM,
        user=build_risk_message(data, analyst, screen, config.limits),
        output_format=RiskManagerOutput,
    )
    result.risk_manager = verdict
    log.record(
        RISK_MANAGER,
        "stage_output",
        {
            "verdict": verdict.verdict,
            "findings": [f.model_dump() for f in verdict.findings],
            "adjustments": [a.model_dump() for a in verdict.adjustments],
        },
    )

    approved = _enforce(screen, verdict, data.portfolio.nav_usd, log)
    result.approved = approved

    # -- Stage 3: Executor --------------------------------------------------
    if not approved:
        result.halted_reason = (
            "risk manager rejected the book"
            if verdict.verdict == "reject"
            else "no idea survived the exposure controls"
        )
        log.record(EXECUTOR, "stage_skipped", {"reason": result.halted_reason})
        if not config.report_on_empty_book:
            log.record("pipeline", "run_completed", log.summary())
            return result
    else:
        execution: ExecutorOutput = run_stage(
            client,
            log,
            stage=EXECUTOR,
            spec=tiers[EXECUTOR],
            system=prompts.EXECUTOR_SYSTEM,
            user=build_executor_message(data, approved),
            output_format=ExecutorOutput,
        )
        result.executor = execution
        log.record(
            EXECUTOR,
            "stage_output",
            {
                "order_count": len(execution.orders),
                "total_gross_notional_usd": execution.total_gross_notional_usd,
                "skipped": execution.skipped,
            },
        )

        check = risk.screen_orders(
            execution.orders,
            {t.symbol.upper(): t.notional_usd for t in approved},
            config.limits,
        )
        result.orders = list(check.accepted)
        result.rejected_orders = check.rejected
        log.record(
            EXECUTOR,
            "order_check",
            {
                "accepted": [o.model_dump() for o in check.accepted],
                "rejected": check.rejected,
            },
        )

    return _finish(data, result, client, config, log)


def _finish(
    data: PipelineInput,
    result: PipelineResult,
    client: StageClient,
    config: PipelineConfig,
    log: AuditLog,
) -> PipelineResult:
    """Stage 4 plus the closing audit record. Runs even on a halted book."""
    report: ReporterOutput = run_stage(
        client,
        log,
        stage=REPORTER,
        spec=config.model_tiers[REPORTER],
        system=prompts.REPORTER_SYSTEM,
        user=build_reporter_message(data, log),
        output_format=ReporterOutput,
    )
    result.report = report
    log.record("pipeline", "run_completed", log.summary())
    return result
