import unittest

from investment_pipeline.audit import AuditLog, verify_records
from investment_pipeline.config import PipelineConfig, RiskLimits
from investment_pipeline.pipeline import run
from investment_pipeline.schemas import (
    AnalystOutput,
    ExecutorOutput,
    MarketSignal,
    OrderIntent,
    PipelineInput,
    Portfolio,
    Position,
    ReporterOutput,
    RiskAdjustment,
    RiskManagerOutput,
    TradeIdea,
)
from tests.fake_client import FakeStageClient

NAV = 100_000_000.0


def pipeline_input(**kw):
    base = dict(
        as_of="2026-09-17",
        mandate="Test mandate.",
        portfolio=Portfolio(
            nav_usd=NAV,
            cash_pct=25.0,
            drawdown_pct=0.0,
            positions=[
                Position(symbol="HELD", asset_class="equity", sector="energy", weight_pct=2.0)
            ],
        ),
        signals=[MarketSignal(source="test", headline="a signal")],
    )
    base.update(kw)
    return PipelineInput(**base)


def trade_idea(symbol="AAA", **kw):
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


def analyst_output(ideas):
    return AnalystOutput(
        regime="neutral",
        regime_rationale="r",
        market_summary="s",
        ideas=ideas,
        data_gaps=[],
    )


def risk_output(verdict="approve", adjustments=(), findings=()):
    return RiskManagerOutput(
        verdict=verdict,
        portfolio_commentary="c",
        findings=list(findings),
        adjustments=list(adjustments),
    )


def order(symbol="AAA", notional=3_000_000.0, **kw):
    base = dict(
        symbol=symbol,
        side="buy",
        target_notional_usd=notional,
        order_type="vwap",
        limit_price=None,
        time_in_force="day",
        slice_count=6,
        participation_rate_pct=None,
        rationale="r",
    )
    base.update(kw)
    return OrderIntent(**base)


def executor_output(orders):
    return ExecutorOutput(
        orders=list(orders),
        total_gross_notional_usd=sum(o.target_notional_usd for o in orders),
        execution_notes="n",
        skipped=[],
    )


REPORT = ReporterOutput(
    headline="Run complete",
    executive_summary="summary",
    decisions=[],
    risk_highlights=[],
    follow_ups=[],
)


def make_client(analyst, risk_manager, executor=None):
    outputs = {"analyst": analyst, "risk_manager": risk_manager, "reporter": REPORT}
    if executor is not None:
        outputs["executor"] = executor
    return FakeStageClient(outputs)


def run_pipeline(client, data=None, limits=None):
    log = AuditLog()
    config = PipelineConfig(limits=limits or RiskLimits())
    return run(data or pipeline_input(), client, config=config, log=log), log


class HappyPath(unittest.TestCase):
    def setUp(self):
        self.client = make_client(
            analyst_output([trade_idea("AAA", target_weight_pct=3.0)]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="ok")],
            ),
            executor_output([order("AAA", 3_000_000.0)]),
        )
        self.result, self.log = run_pipeline(self.client)

    def test_all_four_stages_run_in_order(self):
        self.assertEqual(
            self.client.stages_called(), ["analyst", "risk_manager", "executor", "reporter"]
        )

    def test_each_stage_uses_its_assigned_tier(self):
        by_stage = {c["stage"]: c for c in self.client.calls}
        self.assertEqual(by_stage["analyst"]["model"], "claude-opus-5")
        self.assertEqual(by_stage["risk_manager"]["effort"], "max")
        self.assertEqual(by_stage["executor"]["model"], "claude-sonnet-5")
        self.assertEqual(by_stage["reporter"]["model"], "claude-haiku-4-5")

    def test_the_approved_trade_reaches_an_accepted_order(self):
        self.assertEqual(len(self.result.approved), 1)
        self.assertAlmostEqual(self.result.approved[0].weight_pct, 3.0)
        self.assertAlmostEqual(self.result.approved[0].notional_usd, 3_000_000.0)
        self.assertEqual(len(self.result.orders), 1)
        self.assertEqual(self.result.rejected_orders, [])

    def test_the_audit_chain_covers_the_run_and_verifies(self):
        ok, problem = verify_records(self.log.records)
        self.assertTrue(ok, problem)
        events = [r["event"] for r in self.log.records]
        self.assertEqual(events[0], "run_started")
        self.assertEqual(events[-1], "run_completed")
        for expected in (
            "llm_call",
            "deterministic_screen",
            "enforcement",
            "order_check",
            "stage_output",
        ):
            self.assertIn(expected, events)
        self.assertEqual(len(self.log.events("llm_call")), 4)
        self.assertGreater(self.log.total_cost_usd(), 0.0)
        self.assertEqual(set(self.log.cost_by_stage()), {"analyst", "risk_manager", "executor", "reporter"})

    def test_the_risk_stage_is_shown_the_engine_ceilings(self):
        message = self.client.user_message_for("risk_manager")
        self.assertIn("these weights are ceilings", message)
        self.assertIn("AAA", message)


class EnforcementBeatsTheModel(unittest.TestCase):
    def test_the_engine_ceiling_wins_when_the_risk_manager_asks_for_more(self):
        limits = RiskLimits(max_position_weight_pct=2.0)
        client = make_client(
            analyst_output([trade_idea("AAA", target_weight_pct=5.0)]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=5.0, reason="ok")],
            ),
            executor_output([order("AAA", 2_000_000.0)]),
        )
        result, log = run_pipeline(client, limits=limits)
        self.assertAlmostEqual(result.approved[0].weight_pct, 2.0)
        self.assertEqual(result.approved[0].binding_constraint, "limit_engine")
        overrides = log.events("override_attempt")
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["payload"]["attempts"][0]["symbol"], "AAA")

    def test_the_risk_manager_may_still_size_below_the_ceiling(self):
        client = make_client(
            analyst_output([trade_idea("AAA", target_weight_pct=4.0)]),
            risk_output(
                "approve_with_changes",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=1.0, reason="crowded")],
            ),
            executor_output([order("AAA", 1_000_000.0)]),
        )
        result, log = run_pipeline(client)
        self.assertAlmostEqual(result.approved[0].weight_pct, 1.0)
        self.assertEqual(result.approved[0].binding_constraint, "risk_manager")
        self.assertEqual(log.events("override_attempt"), [])

    def test_the_engine_gets_the_credit_when_the_risk_manager_echoes_its_ceiling(self):
        limits = RiskLimits(max_position_weight_pct=2.0)
        client = make_client(
            analyst_output([trade_idea("AAA", target_weight_pct=5.0)]),
            risk_output(
                "approve_with_changes",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=2.0, reason="at the cap")],
            ),
            executor_output([order("AAA", 2_000_000.0)]),
        )
        result, log = run_pipeline(client, limits=limits)
        self.assertEqual(result.approved[0].binding_constraint, "limit_engine")
        self.assertEqual(log.events("override_attempt"), [])

    def test_a_reject_verdict_stops_every_trade(self):
        client = make_client(
            analyst_output([trade_idea("AAA")]),
            risk_output(
                "reject",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="n/a")],
            ),
        )
        result, log = run_pipeline(client)
        self.assertEqual(result.approved, [])
        self.assertEqual(result.orders, [])
        self.assertIn("rejected", result.halted_reason)
        self.assertNotIn("executor", client.stages_called())
        self.assertEqual(len(log.events("stage_skipped")), 1)

    def test_the_reporter_still_runs_on_a_no_trade_run(self):
        client = make_client(analyst_output([]), risk_output("reject"))
        result, _ = run_pipeline(client)
        self.assertIsNotNone(result.report)
        self.assertIn("reporter", client.stages_called())

    def test_an_idea_the_risk_manager_ignored_does_not_trade(self):
        client = make_client(
            analyst_output([trade_idea("AAA"), trade_idea("BBB")]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="ok")],
            ),
            executor_output([order("AAA", 3_000_000.0)]),
        )
        result, log = run_pipeline(client)
        self.assertEqual([t.symbol for t in result.approved], ["AAA"])
        unreviewed = log.events("unreviewed_ideas")
        self.assertEqual(unreviewed[0]["payload"]["symbols"], ["BBB"])

    def test_a_hard_engine_block_survives_risk_manager_approval(self):
        limits = RiskLimits(restricted_symbols=frozenset({"AAA"}))
        client = make_client(
            analyst_output([trade_idea("AAA")]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="ok")],
            ),
        )
        result, _ = run_pipeline(client, limits=limits)
        self.assertEqual(result.approved, [])
        self.assertNotIn("executor", client.stages_called())


class ExecutorOutputIsRechecked(unittest.TestCase):
    def test_an_order_for_an_unapproved_symbol_is_dropped(self):
        client = make_client(
            analyst_output([trade_idea("AAA")]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="ok")],
            ),
            executor_output([order("AAA", 3_000_000.0), order("ZZZ", 1_000_000.0)]),
        )
        result, log = run_pipeline(client)
        self.assertEqual([o.symbol for o in result.orders], ["AAA"])
        self.assertEqual(result.rejected_orders[0]["code"], "UNAPPROVED_SYMBOL")
        self.assertEqual(len(log.events("order_check")), 1)

    def test_an_oversized_order_is_dropped(self):
        client = make_client(
            analyst_output([trade_idea("AAA")]),
            risk_output(
                "approve",
                [RiskAdjustment(symbol="AAA", approved=True, approved_weight_pct=3.0, reason="ok")],
            ),
            executor_output([order("AAA", 9_000_000.0)]),
        )
        result, _ = run_pipeline(client)
        self.assertEqual(result.orders, [])
        self.assertEqual(result.rejected_orders[0]["code"], "EXCEEDS_APPROVED_NOTIONAL")


if __name__ == "__main__":
    unittest.main()
