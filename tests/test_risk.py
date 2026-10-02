import unittest

from investment_pipeline.config import RiskLimits
from investment_pipeline.risk import screen, screen_orders
from investment_pipeline.schemas import OrderIntent, Portfolio, Position, TradeIdea


def idea(symbol="AAA", **kw):
    base = dict(
        symbol=symbol,
        asset_class="equity",
        sector="technology",
        side="buy",
        conviction=0.8,
        target_weight_pct=3.0,
        horizon_days=90,
        thesis="t",
        catalysts=[],
        key_risks=[],
        invalidation="i",
    )
    base.update(kw)
    return TradeIdea(**base)


def portfolio(**kw):
    base = dict(nav_usd=100_000_000.0, cash_pct=20.0, drawdown_pct=0.0, positions=[])
    base.update(kw)
    return Portfolio(**base)


class PerIdeaGates(unittest.TestCase):
    def test_restricted_symbol_is_blocked_hard(self):
        limits = RiskLimits(restricted_symbols=frozenset({"AAA"}))
        result = screen([idea("AAA")], portfolio(), limits)
        self.assertTrue(result.ideas[0].blocked)
        self.assertTrue(result.has_hard_breach)
        self.assertEqual(result.ideas[0].breaches[0].code, "RESTRICTED_SYMBOL")

    def test_asset_class_outside_mandate_is_blocked(self):
        limits = RiskLimits(allowed_asset_classes=frozenset({"equity"}))
        result = screen([idea("BBB", asset_class="fx")], portfolio(), limits)
        self.assertTrue(result.ideas[0].blocked)
        self.assertEqual(result.ideas[0].breaches[0].code, "ASSET_CLASS_NOT_PERMITTED")

    def test_conviction_below_floor_is_not_actionable(self):
        result = screen([idea(conviction=0.2)], portfolio(), RiskLimits())
        self.assertTrue(result.ideas[0].blocked)
        self.assertEqual(result.ideas[0].breaches[0].code, "CONVICTION_BELOW_FLOOR")

    def test_position_limit_accounts_for_the_existing_holding(self):
        held = portfolio(
            positions=[Position(symbol="AAA", asset_class="equity", sector="technology", weight_pct=4.0)]
        )
        result = screen([idea("AAA", target_weight_pct=3.0)], held, RiskLimits(max_position_weight_pct=5.0))
        self.assertAlmostEqual(result.ideas[0].allowed_weight_pct, 1.0)
        self.assertEqual(result.ideas[0].breaches[0].code, "POSITION_LIMIT")

    def test_reduction_cannot_exceed_the_held_weight(self):
        held = portfolio(
            positions=[Position(symbol="AAA", asset_class="equity", sector="technology", weight_pct=2.0)]
        )
        result = screen([idea("AAA", side="sell", target_weight_pct=5.0)], held, RiskLimits())
        self.assertAlmostEqual(result.ideas[0].allowed_weight_pct, 2.0)
        self.assertEqual(result.ideas[0].breaches[0].code, "OVERSIZED_REDUCTION")


class KillSwitch(unittest.TestCase):
    def test_blocks_risk_adding_but_allows_risk_reducing(self):
        held = portfolio(
            drawdown_pct=18.0,
            positions=[Position(symbol="BBB", asset_class="equity", sector="technology", weight_pct=3.0)],
        )
        result = screen(
            [idea("AAA", side="buy"), idea("BBB", side="sell", target_weight_pct=3.0)],
            held,
            RiskLimits(max_drawdown_pct=15.0),
        )
        by_symbol = {i.symbol: i for i in result.ideas}
        self.assertTrue(result.kill_switch_active)
        self.assertTrue(by_symbol["AAA"].blocked)
        self.assertFalse(by_symbol["BBB"].blocked)
        self.assertTrue(result.has_hard_breach)


class PortfolioLimits(unittest.TestCase):
    def test_sector_cap_scales_the_offending_group_pro_rata(self):
        limits = RiskLimits(max_sector_weight_pct=10.0, max_position_weight_pct=100.0)
        ideas = [
            idea("AAA", target_weight_pct=8.0, sector="technology"),
            idea("BBB", target_weight_pct=8.0, sector="technology"),
        ]
        result = screen(ideas, portfolio(cash_pct=90.0), limits)
        total = sum(i.allowed_weight_pct for i in result.ideas)
        self.assertAlmostEqual(total, 10.0, places=4)
        self.assertTrue(all(i.breaches[0].code == "SECTOR_LIMIT" for i in result.ideas))

    def test_gross_exposure_cap_trims_additions(self):
        held = portfolio(
            cash_pct=5.0,
            positions=[Position(symbol="ZZZ", asset_class="equity", sector="other", weight_pct=95.0)],
        )
        limits = RiskLimits(
            max_gross_exposure_pct=100.0,
            max_position_weight_pct=100.0,
            max_sector_weight_pct=100.0,
            min_cash_pct=0.0,
            max_daily_turnover_pct=100.0,
        )
        result = screen([idea("AAA", target_weight_pct=10.0)], held, limits)
        self.assertAlmostEqual(result.ideas[0].allowed_weight_pct, 5.0, places=4)
        self.assertAlmostEqual(result.projected_gross_pct, 100.0, places=4)

    def test_cash_floor_trims_buys(self):
        limits = RiskLimits(
            min_cash_pct=10.0,
            max_position_weight_pct=100.0,
            max_sector_weight_pct=100.0,
            max_daily_turnover_pct=100.0,
        )
        result = screen([idea("AAA", target_weight_pct=20.0)], portfolio(cash_pct=15.0), limits)
        self.assertAlmostEqual(result.ideas[0].allowed_weight_pct, 5.0, places=4)
        self.assertAlmostEqual(result.projected_cash_pct, 10.0, places=4)

    def test_new_position_budget_keeps_the_highest_conviction_names(self):
        limits = RiskLimits(max_new_positions=2, max_sector_weight_pct=100.0, max_position_weight_pct=100.0)
        ideas = [
            idea("AAA", conviction=0.9, target_weight_pct=1.0),
            idea("BBB", conviction=0.8, target_weight_pct=1.0),
            idea("CCC", conviction=0.6, target_weight_pct=1.0),
        ]
        result = screen(ideas, portfolio(), limits)
        by_symbol = {i.symbol: i for i in result.ideas}
        self.assertFalse(by_symbol["AAA"].blocked)
        self.assertFalse(by_symbol["BBB"].blocked)
        self.assertTrue(by_symbol["CCC"].blocked)
        self.assertEqual(by_symbol["CCC"].breaches[0].code, "NEW_POSITION_BUDGET")

    def test_turnover_cap_limits_the_run(self):
        limits = RiskLimits(
            max_daily_turnover_pct=5.0,
            max_position_weight_pct=100.0,
            max_sector_weight_pct=100.0,
            min_cash_pct=0.0,
        )
        ideas = [idea("AAA", target_weight_pct=6.0), idea("BBB", target_weight_pct=6.0)]
        result = screen(ideas, portfolio(cash_pct=80.0), limits)
        self.assertAlmostEqual(result.turnover_pct, 5.0, places=4)


class OrderPostCheck(unittest.TestCase):
    def order(self, **kw):
        base = dict(
            symbol="AAA",
            side="buy",
            target_notional_usd=1_000_000.0,
            order_type="vwap",
            limit_price=None,
            time_in_force="day",
            slice_count=5,
            participation_rate_pct=None,
            rationale="r",
        )
        base.update(kw)
        return OrderIntent(**base)

    def test_rejects_symbols_the_risk_stage_never_approved(self):
        check = screen_orders([self.order(symbol="ZZZ")], {"AAA": 1_000_000.0}, RiskLimits())
        self.assertEqual(check.accepted, [])
        self.assertEqual(check.rejected[0]["code"], "UNAPPROVED_SYMBOL")

    def test_rejects_notional_above_the_approved_amount(self):
        check = screen_orders([self.order(target_notional_usd=1_500_000.0)], {"AAA": 1_000_000.0}, RiskLimits())
        self.assertEqual(check.rejected[0]["code"], "EXCEEDS_APPROVED_NOTIONAL")

    def test_rejects_orders_above_the_per_order_cap(self):
        limits = RiskLimits(max_order_notional_usd=500_000.0)
        check = screen_orders([self.order()], {"AAA": 1_000_000.0}, limits)
        self.assertEqual(check.rejected[0]["code"], "ORDER_NOTIONAL_LIMIT")

    def test_rejects_limit_orders_without_a_price(self):
        check = screen_orders(
            [self.order(order_type="limit", limit_price=None)], {"AAA": 1_000_000.0}, RiskLimits()
        )
        self.assertEqual(check.rejected[0]["code"], "MISSING_LIMIT_PRICE")

    def test_accepts_a_conforming_order(self):
        check = screen_orders([self.order()], {"AAA": 1_000_000.0}, RiskLimits())
        self.assertEqual(len(check.accepted), 1)
        self.assertEqual(check.rejected, [])


if __name__ == "__main__":
    unittest.main()
