"""Model tiering, pricing and risk limits for the signal-to-execution pipeline.

Each of the four stages gets its own model tier. The rule of thumb encoded
here: spend reasoning tokens where a wrong answer is expensive and hard to
detect (analysis, risk), and spend as few as possible where the work is a
mechanical transform of an already-approved decision (execution, reporting).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, FrozenSet, Optional

Stage = str

ANALYST = "analyst"
RISK_MANAGER = "risk_manager"
EXECUTOR = "executor"
REPORTER = "reporter"

STAGES = (ANALYST, RISK_MANAGER, EXECUTOR, REPORTER)


@dataclass(frozen=True)
class ModelSpec:
    """One stage's model assignment and the knobs that model actually accepts."""

    model_id: str
    max_tokens: int
    # output_config.effort. None for models that reject the field (Haiku 4.5).
    effort: Optional[str] = None
    # thinking parameter, or None to omit it entirely.
    thinking: Optional[Dict[str, Any]] = None
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0

    # Cache pricing is expressed as a multiple of the input rate. These are the
    # standard Anthropic multipliers; re-check them against the pricing page if
    # you start optimising on cache spend specifically.
    cache_write_multiplier: float = 1.25
    cache_read_multiplier: float = 0.10

    def output_config(self) -> Optional[Dict[str, Any]]:
        return {"effort": self.effort} if self.effort else None

    def cost_usd(self, usage: Dict[str, int]) -> float:
        """Cost of one call from a usage dict (missing keys count as zero)."""
        inp = usage.get("input_tokens", 0) or 0
        out = usage.get("output_tokens", 0) or 0
        cache_write = usage.get("cache_creation_input_tokens", 0) or 0
        cache_read = usage.get("cache_read_input_tokens", 0) or 0
        per_token_in = self.input_usd_per_mtok / 1_000_000
        per_token_out = self.output_usd_per_mtok / 1_000_000
        return (
            inp * per_token_in
            + out * per_token_out
            + cache_write * per_token_in * self.cache_write_multiplier
            + cache_read * per_token_in * self.cache_read_multiplier
        )


# Prices are USD per million tokens, Anthropic first-party API rates.
OPUS_5 = ModelSpec(
    model_id="claude-opus-5",
    max_tokens=16000,
    effort="high",
    thinking={"type": "adaptive", "display": "summarized"},
    input_usd_per_mtok=5.00,
    output_usd_per_mtok=25.00,
)

SONNET_5 = ModelSpec(
    model_id="claude-sonnet-5",
    max_tokens=8000,
    effort="low",
    thinking={"type": "adaptive"},
    input_usd_per_mtok=2.00,
    output_usd_per_mtok=10.00,
)

HAIKU_4_5 = ModelSpec(
    model_id="claude-haiku-4-5",
    max_tokens=4000,
    # Haiku 4.5 rejects output_config.effort and uses the older budget_tokens
    # form of thinking; the reporter needs neither, so both stay off.
    effort=None,
    thinking=None,
    input_usd_per_mtok=1.00,
    output_usd_per_mtok=5.00,
)


#: Default stage -> model assignment.
#:
#: analyst       Opus 5 @ high     open-ended synthesis over messy market data.
#: risk_manager  Opus 5 @ max      the veto gate; a miss here is the costly one.
#: executor      Sonnet 5 @ low    mechanical: approved decision -> order list.
#: reporter      Haiku 4.5         summarises an audit trail that is already facts.
DEFAULT_MODEL_TIERS: Dict[Stage, ModelSpec] = {
    ANALYST: OPUS_5,
    RISK_MANAGER: replace(OPUS_5, effort="max"),
    EXECUTOR: SONNET_5,
    REPORTER: HAIKU_4_5,
}

_MODELS_BY_ID = {m.model_id: m for m in (OPUS_5, SONNET_5, HAIKU_4_5)}


def resolve_model_tiers(
    overrides: Optional[Dict[Stage, str]] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[Stage, ModelSpec]:
    """Stage -> ModelSpec, with per-stage overrides.

    Precedence: explicit ``overrides`` argument, then the environment variable
    ``PIPELINE_MODEL_<STAGE>`` (e.g. ``PIPELINE_MODEL_EXECUTOR=claude-opus-5``),
    then the defaults above. Promoting a stage keeps that stage's effort level.
    """
    env = os.environ if env is None else env
    tiers = dict(DEFAULT_MODEL_TIERS)
    for stage in STAGES:
        model_id = (overrides or {}).get(stage) or env.get(f"PIPELINE_MODEL_{stage.upper()}")
        if not model_id:
            continue
        if model_id not in _MODELS_BY_ID:
            raise ValueError(
                f"unknown model id {model_id!r} for stage {stage!r}; "
                f"known: {sorted(_MODELS_BY_ID)}"
            )
        target = _MODELS_BY_ID[model_id]
        current = tiers[stage]
        # Keep the stage's effort intent where the target model supports effort.
        effort = current.effort if target.effort is not None else None
        tiers[stage] = replace(target, effort=effort, max_tokens=current.max_tokens)
    return tiers


@dataclass(frozen=True)
class RiskLimits:
    """Exposure controls enforced in code, not by the model.

    Percentages are of portfolio net asset value unless stated otherwise.
    """

    max_position_weight_pct: float = 5.0
    max_sector_weight_pct: float = 25.0
    max_gross_exposure_pct: float = 120.0
    max_net_exposure_pct: float = 100.0
    min_cash_pct: float = 2.0
    max_new_positions: int = 8
    max_daily_turnover_pct: float = 20.0
    max_order_notional_usd: float = 25_000_000.0
    #: Kill switch: at or beyond this drawdown the pipeline refuses to open risk.
    max_drawdown_pct: float = 15.0
    #: Minimum conviction the analyst must express for an idea to be actionable.
    min_conviction: float = 0.55
    restricted_symbols: FrozenSet[str] = frozenset()
    allowed_asset_classes: FrozenSet[str] = frozenset(
        {"equity", "etf", "fx", "rates", "credit", "commodity"}
    )

    def as_prompt_block(self) -> str:
        """Human-readable limits, injected into the risk manager's context."""
        restricted = ", ".join(sorted(self.restricted_symbols)) or "(none)"
        classes = ", ".join(sorted(self.allowed_asset_classes))
        return (
            f"- Max single position weight: {self.max_position_weight_pct:.2f}% of NAV\n"
            f"- Max sector weight: {self.max_sector_weight_pct:.2f}% of NAV\n"
            f"- Max gross exposure: {self.max_gross_exposure_pct:.2f}% of NAV\n"
            f"- Max net exposure: {self.max_net_exposure_pct:.2f}% of NAV\n"
            f"- Minimum cash: {self.min_cash_pct:.2f}% of NAV\n"
            f"- Max new positions per run: {self.max_new_positions}\n"
            f"- Max daily turnover: {self.max_daily_turnover_pct:.2f}% of NAV\n"
            f"- Max single order notional: ${self.max_order_notional_usd:,.0f}\n"
            f"- Drawdown kill switch: {self.max_drawdown_pct:.2f}%\n"
            f"- Minimum actionable conviction: {self.min_conviction:.2f}\n"
            f"- Restricted symbols: {restricted}\n"
            f"- Permitted asset classes: {classes}"
        )


@dataclass(frozen=True)
class PipelineConfig:
    limits: RiskLimits = field(default_factory=RiskLimits)
    model_tiers: Dict[Stage, ModelSpec] = field(default_factory=resolve_model_tiers)
    #: Still run the reporter when nothing survived risk. A no-trade run is
    #: usually the one you most want a written record of, so this defaults on.
    report_on_empty_book: bool = True
    #: Written as append-only JSONL; one file per run is the intended usage.
    audit_log_path: str = "audit/pipeline.jsonl"
