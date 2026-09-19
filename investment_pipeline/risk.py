"""Deterministic exposure controls.

Nothing in this module calls a model. The risk-manager stage gets an LLM *and*
this engine, and the two are combined with an AND: the model may tighten a
position but it can never loosen one, and a hard breach here is not overridable
by any model output. Keeping the enforcement in plain Python is what makes the
pipeline auditable -- every clamp below is reproducible from the inputs.

Sizing convention
-----------------
``TradeIdea.target_weight_pct`` is always positive and means:

* ``buy`` / ``short`` -- the exposure to *add*, as % of NAV.
* ``sell`` / ``cover`` -- the exposure to *remove*, capped at what is held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import RiskLimits
from .schemas import Portfolio, TradeIdea

RISK_ADDING = ("buy", "short")
RISK_REDUCING = ("sell", "cover")


@dataclass(frozen=True)
class Breach:
    code: str
    severity: str  # "info" | "warning" | "hard"
    detail: str
    symbol: Optional[str] = None
    limit: Optional[float] = None
    observed: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "symbol": self.symbol,
            "detail": self.detail,
            "limit": self.limit,
            "observed": self.observed,
        }


@dataclass
class ScreenedIdea:
    idea: TradeIdea
    allowed_weight_pct: float
    breaches: List[Breach] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return self.idea.symbol

    @property
    def blocked(self) -> bool:
        return self.allowed_weight_pct <= 0.0

    def block(self, breach: Breach) -> None:
        self.allowed_weight_pct = 0.0
        self.breaches.append(breach)

    def clamp(self, ceiling: float, breach: Breach) -> None:
        if self.allowed_weight_pct > ceiling:
            self.allowed_weight_pct = max(0.0, ceiling)
            self.breaches.append(breach)

    def to_dict(self) -> Dict[str, object]:
        return {
            "symbol": self.symbol,
            "side": self.idea.side,
            "requested_weight_pct": self.idea.target_weight_pct,
            "allowed_weight_pct": round(self.allowed_weight_pct, 4),
            "breaches": [b.to_dict() for b in self.breaches],
        }


@dataclass
class RiskScreen:
    ideas: List[ScreenedIdea]
    portfolio_breaches: List[Breach]
    kill_switch_active: bool
    projected_gross_pct: float
    projected_net_pct: float
    projected_cash_pct: float
    turnover_pct: float

    @property
    def allowed(self) -> List[ScreenedIdea]:
        return [i for i in self.ideas if not i.blocked]

    @property
    def has_hard_breach(self) -> bool:
        if any(b.severity == "hard" for b in self.portfolio_breaches):
            return True
        return any(b.severity == "hard" for i in self.ideas for b in i.breaches)

    def ceiling_for(self, symbol: str) -> float:
        """Highest weight this engine will permit for ``symbol`` (0 if blocked)."""
        return max((i.allowed_weight_pct for i in self.ideas if i.symbol == symbol), default=0.0)

    def all_breaches(self) -> List[Breach]:
        out = list(self.portfolio_breaches)
        for i in self.ideas:
            out.extend(i.breaches)
        return out

    def to_dict(self) -> Dict[str, object]:
        return {
            "kill_switch_active": self.kill_switch_active,
            "projected_gross_pct": round(self.projected_gross_pct, 4),
            "projected_net_pct": round(self.projected_net_pct, 4),
            "projected_cash_pct": round(self.projected_cash_pct, 4),
            "turnover_pct": round(self.turnover_pct, 4),
            "portfolio_breaches": [b.to_dict() for b in self.portfolio_breaches],
            "ideas": [i.to_dict() for i in self.ideas],
        }


def _scale_down(
    candidates: Sequence[ScreenedIdea], excess: float, breach_factory
) -> None:
    """Pro-rata reduce ``candidates`` so their combined weight drops by ``excess``."""
    total = sum(c.allowed_weight_pct for c in candidates)
    if total <= 0 or excess <= 0:
        return
    factor = max(0.0, (total - excess) / total)
    for c in candidates:
        before = c.allowed_weight_pct
        c.allowed_weight_pct = round(before * factor, 6)
        if c.allowed_weight_pct < before:
            c.breaches.append(breach_factory(c, before, c.allowed_weight_pct))


def screen(
    ideas: Sequence[TradeIdea], portfolio: Portfolio, limits: RiskLimits
) -> RiskScreen:
    """Apply every exposure control, in order, to a batch of analyst ideas."""
    screened = [ScreenedIdea(idea=i, allowed_weight_pct=float(i.target_weight_pct)) for i in ideas]
    portfolio_breaches: List[Breach] = []

    kill_switch = portfolio.drawdown_pct >= limits.max_drawdown_pct
    if kill_switch:
        portfolio_breaches.append(
            Breach(
                code="DRAWDOWN_KILL_SWITCH",
                severity="hard",
                detail=(
                    f"Drawdown {portfolio.drawdown_pct:.2f}% is at or beyond the "
                    f"{limits.max_drawdown_pct:.2f}% limit; risk-adding trades are blocked."
                ),
                limit=limits.max_drawdown_pct,
                observed=portfolio.drawdown_pct,
            )
        )

    # --- per-idea gates -------------------------------------------------
    for s in screened:
        idea = s.idea
        symbol = idea.symbol.upper()

        if symbol in {r.upper() for r in limits.restricted_symbols}:
            s.block(
                Breach(
                    code="RESTRICTED_SYMBOL",
                    severity="hard",
                    symbol=symbol,
                    detail=f"{symbol} is on the restricted list.",
                )
            )
            continue

        if idea.asset_class not in limits.allowed_asset_classes:
            s.block(
                Breach(
                    code="ASSET_CLASS_NOT_PERMITTED",
                    severity="hard",
                    symbol=symbol,
                    detail=f"Asset class {idea.asset_class!r} is outside the mandate.",
                )
            )
            continue

        if kill_switch and idea.side in RISK_ADDING:
            s.block(
                Breach(
                    code="DRAWDOWN_KILL_SWITCH",
                    severity="hard",
                    symbol=symbol,
                    detail="Risk-adding trade blocked while the drawdown kill switch is active.",
                    limit=limits.max_drawdown_pct,
                    observed=portfolio.drawdown_pct,
                )
            )
            continue

        if idea.conviction < limits.min_conviction:
            s.block(
                Breach(
                    code="CONVICTION_BELOW_FLOOR",
                    severity="warning",
                    symbol=symbol,
                    detail=(
                        f"Conviction {idea.conviction:.2f} is below the actionable floor "
                        f"{limits.min_conviction:.2f}."
                    ),
                    limit=limits.min_conviction,
                    observed=idea.conviction,
                )
            )
            continue

        held = abs(portfolio.weight_of(symbol))
        if idea.side in RISK_REDUCING:
            # Cannot close more than is held.
            s.clamp(
                held,
                Breach(
                    code="OVERSIZED_REDUCTION",
                    severity="warning",
                    symbol=symbol,
                    detail=f"Reduction capped at the held weight of {held:.2f}%.",
                    limit=held,
                    observed=idea.target_weight_pct,
                ),
            )
            continue

        projected = held + s.allowed_weight_pct
        if projected > limits.max_position_weight_pct:
            ceiling = max(0.0, limits.max_position_weight_pct - held)
            s.clamp(
                ceiling,
                Breach(
                    code="POSITION_LIMIT",
                    severity="warning",
                    symbol=symbol,
                    detail=(
                        f"Position would reach {projected:.2f}% of NAV against a "
                        f"{limits.max_position_weight_pct:.2f}% cap; trimmed to {ceiling:.2f}%."
                    ),
                    limit=limits.max_position_weight_pct,
                    observed=projected,
                ),
            )

    # --- new-position budget -------------------------------------------
    held_symbols = {p.symbol.upper() for p in portfolio.positions if p.weight_pct != 0}
    new_entries = [
        s
        for s in screened
        if not s.blocked
        and s.idea.side in RISK_ADDING
        and s.symbol.upper() not in held_symbols
    ]
    if len(new_entries) > limits.max_new_positions:
        # Keep the highest-conviction names; drop the rest.
        ranked = sorted(new_entries, key=lambda s: s.idea.conviction, reverse=True)
        for s in ranked[limits.max_new_positions :]:
            s.block(
                Breach(
                    code="NEW_POSITION_BUDGET",
                    severity="warning",
                    symbol=s.symbol,
                    detail=(
                        f"Only {limits.max_new_positions} new positions permitted per run; "
                        f"dropped as the lower-conviction name."
                    ),
                    limit=float(limits.max_new_positions),
                    observed=float(len(new_entries)),
                )
            )

    # --- sector caps ----------------------------------------------------
    sector_now = portfolio.sector_weights()
    by_sector: Dict[str, List[ScreenedIdea]] = {}
    for s in screened:
        if s.blocked or s.idea.side not in RISK_ADDING:
            continue
        by_sector.setdefault(s.idea.sector, []).append(s)
    for sector, group in by_sector.items():
        added = sum(g.allowed_weight_pct for g in group)
        projected = sector_now.get(sector, 0.0) + added
        if projected > limits.max_sector_weight_pct:
            excess = projected - limits.max_sector_weight_pct
            _scale_down(
                group,
                excess,
                lambda c, before, after, _sector=sector, _p=projected: Breach(
                    code="SECTOR_LIMIT",
                    severity="warning",
                    symbol=c.symbol,
                    detail=(
                        f"Sector {_sector!r} would reach {_p:.2f}% of NAV against a "
                        f"{limits.max_sector_weight_pct:.2f}% cap; "
                        f"trimmed {before:.2f}% -> {after:.2f}%."
                    ),
                    limit=limits.max_sector_weight_pct,
                    observed=_p,
                ),
            )

    # --- gross exposure --------------------------------------------------
    adders = [s for s in screened if not s.blocked and s.idea.side in RISK_ADDING]
    reducers = [s for s in screened if not s.blocked and s.idea.side in RISK_REDUCING]

    def projected_gross() -> float:
        return (
            portfolio.gross_exposure_pct()
            + sum(a.allowed_weight_pct for a in adders)
            - sum(r.allowed_weight_pct for r in reducers)
        )

    gross = projected_gross()
    if gross > limits.max_gross_exposure_pct:
        excess = gross - limits.max_gross_exposure_pct
        _scale_down(
            adders,
            excess,
            lambda c, before, after, _g=gross: Breach(
                code="GROSS_EXPOSURE_LIMIT",
                severity="warning",
                symbol=c.symbol,
                detail=(
                    f"Projected gross {_g:.2f}% exceeds the "
                    f"{limits.max_gross_exposure_pct:.2f}% cap; "
                    f"trimmed {before:.2f}% -> {after:.2f}%."
                ),
                limit=limits.max_gross_exposure_pct,
                observed=_g,
            ),
        )

    # --- net exposure ----------------------------------------------------
    def signed_delta(s: ScreenedIdea) -> float:
        side = s.idea.side
        if side == "buy":
            return s.allowed_weight_pct
        if side == "short":
            return -s.allowed_weight_pct
        if side == "sell":
            return -s.allowed_weight_pct
        return s.allowed_weight_pct  # cover closes a short, so net rises

    net = portfolio.net_exposure_pct() + sum(signed_delta(s) for s in screened if not s.blocked)
    if abs(net) > limits.max_net_exposure_pct:
        longs = [s for s in screened if not s.blocked and s.idea.side == "buy"]
        shorts = [s for s in screened if not s.blocked and s.idea.side == "short"]
        group = longs if net > 0 else shorts
        excess = abs(net) - limits.max_net_exposure_pct
        _scale_down(
            group,
            excess,
            lambda c, before, after, _n=net: Breach(
                code="NET_EXPOSURE_LIMIT",
                severity="warning",
                symbol=c.symbol,
                detail=(
                    f"Projected net {_n:.2f}% exceeds the "
                    f"{limits.max_net_exposure_pct:.2f}% cap; "
                    f"trimmed {before:.2f}% -> {after:.2f}%."
                ),
                limit=limits.max_net_exposure_pct,
                observed=_n,
            ),
        )

    # --- cash floor -------------------------------------------------------
    # Longs consume cash; sells release it. Shorts are treated as cash-neutral
    # here (they consume margin, which the gross-exposure cap governs instead).
    buys = [s for s in screened if not s.blocked and s.idea.side == "buy"]
    cash_out = sum(b.allowed_weight_pct for b in buys)
    cash_in = sum(s.allowed_weight_pct for s in screened if not s.blocked and s.idea.side == "sell")
    projected_cash = portfolio.cash_pct - cash_out + cash_in
    if projected_cash < limits.min_cash_pct:
        excess = limits.min_cash_pct - projected_cash
        _scale_down(
            buys,
            excess,
            lambda c, before, after, _c=projected_cash: Breach(
                code="CASH_FLOOR",
                severity="warning",
                symbol=c.symbol,
                detail=(
                    f"Projected cash {_c:.2f}% would fall below the "
                    f"{limits.min_cash_pct:.2f}% floor; "
                    f"trimmed {before:.2f}% -> {after:.2f}%."
                ),
                limit=limits.min_cash_pct,
                observed=_c,
            ),
        )

    # --- turnover ---------------------------------------------------------
    live = [s for s in screened if not s.blocked]
    turnover = sum(s.allowed_weight_pct for s in live)
    if turnover > limits.max_daily_turnover_pct:
        excess = turnover - limits.max_daily_turnover_pct
        _scale_down(
            [s for s in live if s.idea.side in RISK_ADDING],
            excess,
            lambda c, before, after, _t=turnover: Breach(
                code="TURNOVER_LIMIT",
                severity="warning",
                symbol=c.symbol,
                detail=(
                    f"Run turnover {_t:.2f}% exceeds the "
                    f"{limits.max_daily_turnover_pct:.2f}% cap; "
                    f"trimmed {before:.2f}% -> {after:.2f}%."
                ),
                limit=limits.max_daily_turnover_pct,
                observed=_t,
            ),
        )

    # Anything scaled to (near) zero is no longer actionable.
    for s in screened:
        if 0.0 < s.allowed_weight_pct < 1e-6:
            s.allowed_weight_pct = 0.0

    live = [s for s in screened if not s.blocked]
    final_cash = (
        portfolio.cash_pct
        - sum(s.allowed_weight_pct for s in live if s.idea.side == "buy")
        + sum(s.allowed_weight_pct for s in live if s.idea.side == "sell")
    )
    final_gross = (
        portfolio.gross_exposure_pct()
        + sum(s.allowed_weight_pct for s in live if s.idea.side in RISK_ADDING)
        - sum(s.allowed_weight_pct for s in live if s.idea.side in RISK_REDUCING)
    )
    final_net = portfolio.net_exposure_pct() + sum(signed_delta(s) for s in live)

    return RiskScreen(
        ideas=screened,
        portfolio_breaches=portfolio_breaches,
        kill_switch_active=kill_switch,
        projected_gross_pct=final_gross,
        projected_net_pct=final_net,
        projected_cash_pct=final_cash,
        turnover_pct=sum(s.allowed_weight_pct for s in live),
    )


@dataclass
class OrderCheck:
    accepted: List[object] = field(default_factory=list)
    rejected: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "accepted_count": len(self.accepted),
            "rejected": self.rejected,
        }


def screen_orders(
    orders: Sequence,
    approved_notional: Dict[str, float],
    limits: RiskLimits,
    tolerance_pct: float = 1.0,
) -> OrderCheck:
    """Post-execution-stage gate.

    The executor is a cheap model translating an already-approved decision, so
    its output is re-checked rather than trusted: every order must map to an
    approved symbol, stay within the per-order notional cap, and not exceed the
    approved notional by more than ``tolerance_pct`` (rounding headroom).
    """
    check = OrderCheck()
    for order in orders:
        symbol = order.symbol.upper()
        approved = approved_notional.get(symbol)
        if approved is None:
            check.rejected.append(
                {
                    "symbol": order.symbol,
                    "code": "UNAPPROVED_SYMBOL",
                    "detail": "Order references a symbol the risk stage did not approve.",
                }
            )
            continue
        if symbol in {r.upper() for r in limits.restricted_symbols}:
            check.rejected.append(
                {"symbol": order.symbol, "code": "RESTRICTED_SYMBOL", "detail": "Restricted list."}
            )
            continue
        if order.target_notional_usd > limits.max_order_notional_usd:
            check.rejected.append(
                {
                    "symbol": order.symbol,
                    "code": "ORDER_NOTIONAL_LIMIT",
                    "detail": (
                        f"${order.target_notional_usd:,.0f} exceeds the per-order cap of "
                        f"${limits.max_order_notional_usd:,.0f}."
                    ),
                }
            )
            continue
        ceiling = approved * (1.0 + tolerance_pct / 100.0)
        if order.target_notional_usd > ceiling:
            check.rejected.append(
                {
                    "symbol": order.symbol,
                    "code": "EXCEEDS_APPROVED_NOTIONAL",
                    "detail": (
                        f"${order.target_notional_usd:,.0f} exceeds the approved "
                        f"${approved:,.0f} (+{tolerance_pct:.1f}% tolerance)."
                    ),
                }
            )
            continue
        if order.order_type == "limit" and order.limit_price is None:
            check.rejected.append(
                {
                    "symbol": order.symbol,
                    "code": "MISSING_LIMIT_PRICE",
                    "detail": "Limit order submitted without a limit price.",
                }
            )
            continue
        check.accepted.append(order)
    return check
