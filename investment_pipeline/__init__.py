"""Four-stage LLM investment pipeline: Analyst -> Risk Manager -> Executor -> Reporter."""

from .config import (
    ANALYST,
    EXECUTOR,
    REPORTER,
    RISK_MANAGER,
    DEFAULT_MODEL_TIERS,
    ModelSpec,
    PipelineConfig,
    RiskLimits,
    resolve_model_tiers,
)
from .audit import AuditLog, verify_log, verify_records
from .pipeline import ApprovedTrade, PipelineResult, run
from .risk import Breach, RiskScreen, screen, screen_orders
from .schemas import (
    AnalystOutput,
    ExecutorOutput,
    MarketSignal,
    OrderIntent,
    PipelineInput,
    Portfolio,
    Position,
    ReporterOutput,
    RiskManagerOutput,
    TradeIdea,
)

__all__ = [
    "ANALYST",
    "RISK_MANAGER",
    "EXECUTOR",
    "REPORTER",
    "DEFAULT_MODEL_TIERS",
    "ModelSpec",
    "PipelineConfig",
    "RiskLimits",
    "resolve_model_tiers",
    "AuditLog",
    "verify_log",
    "verify_records",
    "run",
    "PipelineResult",
    "ApprovedTrade",
    "screen",
    "screen_orders",
    "RiskScreen",
    "Breach",
    "PipelineInput",
    "Portfolio",
    "Position",
    "MarketSignal",
    "TradeIdea",
    "AnalystOutput",
    "RiskManagerOutput",
    "ExecutorOutput",
    "OrderIntent",
    "ReporterOutput",
]
