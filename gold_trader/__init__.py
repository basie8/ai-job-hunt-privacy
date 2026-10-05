"""XAUUSD signal pipeline with a measured, self-correcting feedback loop."""

from .feed import Candle, CsvFeed, Feed, FeedUnavailable, InlineFeed, MarketSnapshot, Series, SnapshotFeed, HttpFeed
from .indicators import FeatureSet, build_features, atr, ema, rsi
from .journal import Journal, SignalRecord, resolve_all, resolve_against
from .learning import LearningState, learn, wilson_lower_bound
from .macro import BlackoutPolicy, MacroCalendar, MacroEvent
from .pipeline import GoldConfig, SignalResult, run_signal
from .risk import Breach, RiskDecision, TradingLimits, evaluate
from .schemas import ChartRead, ExecutionPlan, RiskVerdict, TradeAlert

__all__ = [
    "Feed", "CsvFeed", "InlineFeed", "SnapshotFeed", "HttpFeed", "FeedUnavailable",
    "Candle", "Series", "MarketSnapshot",
    "build_features", "FeatureSet", "ema", "rsi", "atr",
    "MacroCalendar", "MacroEvent", "BlackoutPolicy",
    "Journal", "SignalRecord", "resolve_against", "resolve_all",
    "learn", "LearningState", "wilson_lower_bound",
    "TradingLimits", "RiskDecision", "Breach", "evaluate",
    "GoldConfig", "SignalResult", "run_signal",
    "ChartRead", "RiskVerdict", "ExecutionPlan", "TradeAlert",
]
