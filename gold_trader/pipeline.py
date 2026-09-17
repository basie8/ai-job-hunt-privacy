"""The XAUUSD signal pipeline.

    Analyst (Opus 5, high)   features + diary + track record -> a chart read
    Risk Manager (Opus 5, max)  the read                     -> tighten or veto
    deterministic gates (no model)                           -> size or refuse
    Executor (Sonnet 5, low)  approved plan                  -> order mechanics
    Reporter (Haiku 4.5)      audit trail                    -> the alert

Two things happen before the analyst is called at all: open signals are resolved
against the newest candles, and the journal is re-scored. The model therefore
reads an up-to-date record of its own performance before forming a view, and the
clamps derived from that record are already in force when it answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from investment_pipeline.audit import AuditLog, sha256_of
from investment_pipeline.config import ModelSpec, resolve_model_tiers
from investment_pipeline.llm import StageClient, run_stage

from . import prompts, risk as gold_risk
from .feed import Feed, FeedUnavailable, MarketSnapshot
from .indicators import FeatureSet, build_features
from .journal import Journal, SignalRecord, resolve_all
from .learning import LearningState, learn
from .macro import MacroCalendar
from .schemas import ChartRead, ExecutionPlan, RiskVerdict, TradeAlert

ANALYST = "analyst"
RISK_MANAGER = "risk_manager"
EXECUTOR = "executor"
REPORTER = "reporter"

DEFAULT_TIMEFRAMES = ("h4", "h1", "m15")


@dataclass
class GoldConfig:
    limits: gold_risk.TradingLimits = field(default_factory=gold_risk.TradingLimits)
    model_tiers: Dict[str, ModelSpec] = field(default_factory=resolve_model_tiers)
    timeframes: tuple = DEFAULT_TIMEFRAMES
    journal_path: str = "gold_trader/state/journal.jsonl"
    audit_path: str = "gold_trader/state/audit.jsonl"
    calendar_path: str = "gold_trader/state/calendar.json"
    min_samples: int = 20
    #: Timeframe whose candles resolve open trades.
    resolution_timeframe: str = "m15"


@dataclass
class SignalResult:
    run_id: str
    snapshot: Optional[MarketSnapshot] = None
    features: Optional[FeatureSet] = None
    calendar: Optional[MacroCalendar] = None
    learning: Optional[LearningState] = None
    read: Optional[ChartRead] = None
    verdict: Optional[RiskVerdict] = None
    decision: Optional[gold_risk.RiskDecision] = None
    plan: Optional[ExecutionPlan] = None
    alert: Optional[TradeAlert] = None
    record: Optional[SignalRecord] = None
    resolved: List[SignalRecord] = field(default_factory=list)
    audit: Optional[AuditLog] = None

    @property
    def actionable(self) -> bool:
        return bool(self.decision and self.decision.approved and self.plan and self.plan.action != "no_trade")

    def notification_text(self) -> str:
        if self.alert:
            return f"{self.alert.headline}\n{self.alert.action_line}\n{self.alert.risk_line}"
        return "Gold run completed with no alert generated."

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "actionable": self.actionable,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "features": self.features.to_dict() if self.features else None,
            "read": self.read.model_dump() if self.read else None,
            "verdict": self.verdict.model_dump() if self.verdict else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "plan": self.plan.model_dump() if self.plan else None,
            "alert": self.alert.model_dump() if self.alert else None,
            "signal_id": self.record.id if self.record else None,
            "resolved_ids": [r.id for r in self.resolved],
            "learning": self.learning.to_dict() if self.learning else None,
            "audit": self.audit.summary() if self.audit else None,
        }


# ---------------------------------------------------------------------------
# Prompt bodies
# ---------------------------------------------------------------------------

def build_analyst_message(
    snapshot: MarketSnapshot,
    features: FeatureSet,
    calendar: MacroCalendar,
    learning: LearningState,
    limits: gold_risk.TradingLimits,
    now: datetime,
) -> str:
    staleness = snapshot.staleness_min(now)
    quality = (
        f"Source: {snapshot.source}. Data is {staleness:.0f} minutes old"
        + (" -- STALE, treat every level as indicative only." if snapshot.is_stale(now) else ".")
    )
    return (
        f"Instrument: XAUUSD (spot gold)\nNow: {now.isoformat(timespec='minutes')}\n"
        f"{quality}\n\n"
        f"TECHNICAL FEATURES (computed, not estimated)\n{features.as_prompt_block()}\n\n"
        f"MACRO DIARY\n{calendar.as_prompt_block(now)}\n\n"
        f"{learning.lessons_block()}\n\n"
        f"RISK FRAME (the engine enforces these after you answer)\n{limits.as_prompt_block()}\n\n"
        "Return your read of XAUUSD."
    )


def build_risk_message(
    read: ChartRead,
    features: FeatureSet,
    calendar: MacroCalendar,
    learning: LearningState,
    limits: gold_risk.TradingLimits,
    now: datetime,
) -> str:
    primary = features.primary("h1")
    atr = primary.atr14 if primary else None
    stop_atr = (
        f"{abs((read.entry or 0) - (read.stop or 0)) / atr:.2f}x ATR"
        if atr and read.entry and read.stop
        else "n/a"
    )
    rr = (
        f"{abs((read.target or 0) - (read.entry or 0)) / abs((read.entry or 0) - (read.stop or 0)):.2f}"
        if read.entry and read.stop and read.target and read.entry != read.stop
        else "n/a"
    )
    return (
        f"Now: {now.isoformat(timespec='minutes')}\n\n"
        f"ANALYST READ\n"
        f"  bias {read.bias}, regime {read.regime}, setup {read.setup_type}, "
        f"conviction {read.conviction:.2f}\n"
        f"  entry {read.entry}, stop {read.stop}, target {read.target}\n"
        f"  stop width: {stop_atr}; reward:risk {rr}\n"
        f"  technical: {read.technical_read}\n"
        f"  macro: {read.macro_read}\n"
        f"  invalidation: {read.invalidation}\n"
        f"  data concerns: {'; '.join(read.data_concerns) or 'none stated'}\n\n"
        f"TECHNICAL FEATURES\n{features.as_prompt_block()}\n\n"
        f"MACRO DIARY\n{calendar.as_prompt_block(now)}\n\n"
        f"{learning.lessons_block()}\n\n"
        f"RISK FRAME\n{limits.as_prompt_block()}\n\n"
        "You may tighten the stop, pull in the target, or cut conviction. You may not "
        "loosen any of them. Return your verdict."
    )


def build_executor_message(
    decision: gold_risk.RiskDecision, calendar: MacroCalendar, now: datetime
) -> str:
    upcoming = calendar.upcoming(now, 24)
    next_event = (
        f"{upcoming[0].name} in {upcoming[0].minutes_until(now) / 60:.1f}h"
        if upcoming
        else "none in the next 24h"
    )
    rr = f"{decision.reward_risk:.2f}" if decision.reward_risk else "n/a"
    return (
        f"Now: {now.isoformat(timespec='minutes')}\n\n"
        f"APPROVED PLAN - place exactly this\n"
        f"  direction {decision.direction}\n"
        f"  entry {decision.entry}\n"
        f"  stop {decision.stop}\n"
        f"  target {decision.target}\n"
        f"  size {decision.size_units:.4f} oz (${decision.risk_usd:,.0f} at risk)\n"
        f"  reward:risk {rr}\n\n"
        f"Next high-impact event: {next_event}\n\n"
        "Choose order type and how long the level stays live."
    )


def build_reporter_message(log: AuditLog, result: "SignalResult", now: datetime) -> str:
    return (
        f"XAUUSD run {log.run_id} at {now.isoformat(timespec='minutes')}.\n\n"
        f"AUDIT TRAIL\n{log.narrative()}\n\n"
        f"RESOLVED THIS RUN: {len(result.resolved)} "
        f"({', '.join(f'{r.id} {r.status} {r.r_multiple:+.2f}R' for r in result.resolved) or 'none'})\n\n"
        "Write the alert."
    )


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

def _tighter(read: ChartRead, verdict: RiskVerdict, log: AuditLog) -> Dict[str, Optional[float]]:
    """Take the tighter of the analyst's and the risk manager's levels."""
    long = read.bias == "long"
    stop, target = read.stop, read.target
    overrides: List[Dict[str, object]] = []

    if verdict.adjusted_stop is not None and stop is not None:
        tighter = max(stop, verdict.adjusted_stop) if long else min(stop, verdict.adjusted_stop)
        if tighter != verdict.adjusted_stop:
            overrides.append(
                {
                    "field": "stop",
                    "analyst": stop,
                    "risk_manager": verdict.adjusted_stop,
                    "detail": "Risk manager tried to widen the stop; kept the analyst's.",
                }
            )
        stop = tighter

    if verdict.adjusted_target is not None and target is not None:
        tighter = (
            min(target, verdict.adjusted_target) if long else max(target, verdict.adjusted_target)
        )
        if tighter != verdict.adjusted_target:
            overrides.append(
                {
                    "field": "target",
                    "analyst": target,
                    "risk_manager": verdict.adjusted_target,
                    "detail": "Risk manager tried to extend the target; kept the analyst's.",
                }
            )
        target = tighter

    conviction = min(read.conviction, verdict.adjusted_conviction)
    if verdict.adjusted_conviction > read.conviction:
        overrides.append(
            {
                "field": "conviction",
                "analyst": read.conviction,
                "risk_manager": verdict.adjusted_conviction,
                "detail": "Risk manager tried to raise conviction; kept the analyst's.",
            }
        )

    if overrides:
        log.record(RISK_MANAGER, "override_attempt", {"attempts": overrides})
    return {"stop": stop, "target": target, "conviction": conviction}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_signal(
    feed: Feed,
    client: StageClient,
    config: Optional[GoldConfig] = None,
    now: Optional[datetime] = None,
    log: Optional[AuditLog] = None,
    journal: Optional[Journal] = None,
) -> SignalResult:
    config = config or GoldConfig()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    log = log or AuditLog(path=config.audit_path)
    journal = journal if journal is not None else Journal(config.journal_path)
    tiers = config.model_tiers
    result = SignalResult(run_id=log.run_id, audit=log)

    snapshot = feed.snapshot(config.timeframes)
    result.snapshot = snapshot
    log.record("pipeline", "run_started", {"as_of": now.isoformat(), "market": snapshot.to_dict(now)})

    # -- learn before deciding -------------------------------------------
    resolution_series = snapshot.series.get(config.resolution_timeframe)
    if resolution_series:
        result.resolved = resolve_all(journal, resolution_series)
        if result.resolved:
            log.record(
                "learning",
                "outcomes_resolved",
                {
                    "resolved": [
                        {
                            "id": r.id,
                            "setup": r.setup_type,
                            "status": r.status,
                            "r_multiple": r.r_multiple,
                            "resolution": r.resolution,
                        }
                        for r in result.resolved
                    ]
                },
            )

    learning = learn(journal, min_samples=config.min_samples)
    result.learning = learning
    log.record("learning", "state", learning.to_dict())

    features = build_features(snapshot)
    result.features = features
    log.record("market", "features", features.to_dict())

    calendar = MacroCalendar.build(now, config.calendar_path)
    result.calendar = calendar
    log.record("market", "calendar", calendar.to_dict(now))

    # -- Stage 1: Analyst -------------------------------------------------
    read: ChartRead = run_stage(
        client, log,
        stage=ANALYST, spec=tiers[ANALYST], system=prompts.ANALYST_SYSTEM,
        user=build_analyst_message(snapshot, features, calendar, learning, config.limits, now),
        output_format=ChartRead,
    )
    result.read = read
    log.record(ANALYST, "stage_output", read.model_dump())

    # -- Stage 2: Risk manager --------------------------------------------
    verdict: RiskVerdict = run_stage(
        client, log,
        stage=RISK_MANAGER, spec=tiers[RISK_MANAGER], system=prompts.RISK_SYSTEM,
        user=build_risk_message(read, features, calendar, learning, config.limits, now),
        output_format=RiskVerdict,
    )
    result.verdict = verdict
    log.record(RISK_MANAGER, "stage_output", verdict.model_dump())

    merged = _tighter(read, verdict, log)
    primary = features.primary("h1")

    if verdict.verdict == "reject" or read.bias == "flat":
        decision = gold_risk.RiskDecision(
            approved=False,
            direction="flat",
            breaches=[
                gold_risk.Breach(
                    "RISK_MANAGER_REJECT" if verdict.verdict == "reject" else "NO_SETUP",
                    "hard",
                    verdict.commentary if verdict.verdict == "reject" else "Analyst returned flat.",
                )
            ],
        )
    else:
        decision = gold_risk.evaluate(
            direction=read.bias,
            entry=read.entry,
            stop=merged["stop"],
            target=merged["target"],
            conviction=merged["conviction"],
            setup_type=read.setup_type,
            atr=primary.atr14 if primary else None,
            spot=snapshot.spot,
            data_source=snapshot.source,
            staleness_min=snapshot.staleness_min(now),
            now=now,
            limits=config.limits,
            calendar=calendar,
            journal=journal,
            learning=learning,
        )
    result.decision = decision
    log.record("risk_engine", "decision", decision.to_dict())

    # -- Stage 3: Executor -------------------------------------------------
    if decision.approved:
        plan: ExecutionPlan = run_stage(
            client, log,
            stage=EXECUTOR, spec=tiers[EXECUTOR], system=prompts.EXECUTOR_SYSTEM,
            user=build_executor_message(decision, calendar, now),
            output_format=ExecutionPlan,
        )
        drift = _plan_drift(plan, decision)
        if drift:
            log.record(EXECUTOR, "plan_rejected", {"reasons": drift})
            plan = ExecutionPlan(
                action="no_trade", order_type="none",
                notes="Executor altered approved levels; plan discarded. " + "; ".join(drift),
            )
        result.plan = plan
        log.record(EXECUTOR, "stage_output", plan.model_dump())

        if plan.action != "no_trade":
            result.record = journal.new_signal(
                direction=decision.direction,
                setup_type=read.setup_type,
                conviction=decision.conviction,
                entry=decision.entry,
                stop=decision.stop,
                target=decision.target,
                size_units=decision.size_units,
                risk_usd=decision.risk_usd,
                regime=read.regime,
                rationale=read.technical_read,
                invalidation=read.invalidation,
                valid_until=(now + timedelta(hours=plan.valid_hours)).isoformat(timespec="seconds"),
                features=features.to_dict(),
                macro=calendar.to_dict(now),
                audit_run_id=log.run_id,
                data_source=snapshot.source,
            )
            log.record("journal", "signal_recorded", {"signal_id": result.record.id})
    else:
        log.record(EXECUTOR, "stage_skipped", {"reason": "no approved trade"})

    # -- Stage 4: Reporter --------------------------------------------------
    alert: TradeAlert = run_stage(
        client, log,
        stage=REPORTER, spec=tiers[REPORTER], system=prompts.REPORTER_SYSTEM,
        user=build_reporter_message(log, result, now),
        output_format=TradeAlert,
    )
    result.alert = alert
    log.record("pipeline", "run_completed", log.summary())
    return result


def _plan_drift(plan: ExecutionPlan, decision: gold_risk.RiskDecision, tol: float = 0.01) -> List[str]:
    """The executor may choose mechanics, not levels. Catch it if it changes them."""
    if plan.action == "no_trade":
        return []
    reasons: List[str] = []
    expected_action = "buy" if decision.direction == "long" else "sell"
    if plan.action != expected_action:
        reasons.append(f"action {plan.action!r} does not match approved direction {decision.direction!r}")
    for field_name, approved in (("entry", decision.entry), ("stop", decision.stop), ("target", decision.target)):
        proposed = getattr(plan, field_name)
        if approved is None or proposed is None:
            continue
        if abs(proposed - approved) > tol:
            reasons.append(f"{field_name} {proposed} differs from approved {approved}")
    return reasons
