import unittest
from datetime import datetime, timedelta, timezone

from investment_pipeline.audit import AuditLog, verify_records
from gold_trader.journal import Journal
from gold_trader.macro import MacroCalendar
from gold_trader.pipeline import GoldConfig, run_signal
from gold_trader.risk import TradingLimits
from gold_trader.schemas import ChartRead, ExecutionPlan, RiskVerdict, TradeAlert
from tests.fake_client import FakeStageClient
from tests_gold.helpers import StubFeed, ramp, snapshot_from

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def chart_read(**kw):
    base = dict(
        bias="long", regime="trending_up", setup_type="bos_continuation", conviction=0.75,
        entry=2400.0, stop=2390.0, target=2420.0,
        technical_read="Higher lows into the 20 EMA.", macro_read="No release inside the horizon.",
        invalidation="A close below 2388.", key_levels=[2390.0, 2420.0], data_concerns=[],
    )
    base.update(kw)
    return ChartRead(**base)


def verdict(**kw):
    base = dict(verdict="approve", adjusted_conviction=0.75, commentary="Clean.", findings=[])
    base.update(kw)
    return RiskVerdict(**base)


def plan(**kw):
    base = dict(action="buy", order_type="limit", entry=2400.0, stop=2390.0, target=2420.0,
                valid_hours=6, notes="Wait for the pullback.")
    base.update(kw)
    return ExecutionPlan(**base)


ALERT = TradeAlert(
    headline="BUY XAUUSD 2400", action_line="BUY XAUUSD 2400.00, stop 2390.00, target 2420.00",
    body="Trend pullback into the 20 EMA.", risk_line="50 oz, $500 risk.",
    watch_items=[], learning_note="",
)


def make_client(read=None, rm=None, execution=None):
    return FakeStageClient(
        {
            "analyst": read or chart_read(),
            "risk_manager": rm or verdict(),
            "executor": execution or plan(),
            "reporter": ALERT,
        }
    )


def run(client, *, feed=None, config=None, journal=None, now=NOW):
    snapshot = snapshot_from(ramp(2360.0, 120, 0.4), timeframes=("h1", "m15"), end=now)
    config = config or GoldConfig(limits=TradingLimits(account_currency="USD", account_value=100_000, fx_to_usd=1.0, risk_per_trade_pct=0.5))
    log = AuditLog()
    return (
        run_signal(
            feed or StubFeed(snapshot), client, config=config, now=now,
            log=log, journal=journal if journal is not None else Journal(),
        ),
        log,
    )


class HappyPath(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.result, self.log = run(self.client)

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

    def test_the_trade_is_approved_sized_and_journalled(self):
        self.assertTrue(self.result.actionable)
        self.assertAlmostEqual(self.result.decision.size_units, 50.0)
        self.assertIsNotNone(self.result.record)
        self.assertEqual(self.result.record.setup_type, "bos_continuation")

    def test_the_journalled_signal_carries_the_feature_snapshot(self):
        self.assertIn("timeframes", self.result.record.features)
        self.assertIn("h1", self.result.record.features["timeframes"])

    def test_the_analyst_reads_its_track_record_before_deciding(self):
        message = self.client.user_message_for("analyst")
        self.assertIn("TRACK RECORD", message)
        self.assertIn("TECHNICAL FEATURES", message)
        self.assertIn("MACRO DIARY", message)

    def test_the_audit_chain_covers_the_run_and_verifies(self):
        ok, problem = verify_records(self.log.records)
        self.assertTrue(ok, problem)
        events = [r["event"] for r in self.log.records]
        self.assertEqual(events[0], "run_started")
        self.assertEqual(events[-1], "run_completed")
        for expected in ("state", "features", "calendar", "decision", "signal_recorded"):
            self.assertIn(expected, events)
        self.assertEqual(len(self.log.events("llm_call")), 4)

    def test_the_notification_text_is_one_actionable_block(self):
        text = self.result.notification_text()
        self.assertIn("BUY XAUUSD", text)
        self.assertIn("stop", text)


class EnforcementBeatsTheModel(unittest.TestCase):
    def test_the_risk_manager_may_tighten_the_stop(self):
        result, _ = run(make_client(rm=verdict(verdict="approve_with_changes", adjusted_stop=2394.0)))
        self.assertAlmostEqual(result.decision.stop, 2394.0)

    def test_a_widened_stop_is_discarded_and_logged(self):
        result, log = run(make_client(rm=verdict(adjusted_stop=2380.0)))
        self.assertAlmostEqual(result.decision.stop, 2390.0)
        attempts = log.events("override_attempt")
        self.assertEqual(attempts[0]["payload"]["attempts"][0]["field"], "stop")

    def test_an_extended_target_is_discarded(self):
        result, log = run(make_client(rm=verdict(adjusted_target=2500.0)))
        self.assertAlmostEqual(result.decision.target, 2420.0)
        self.assertTrue(log.events("override_attempt"))

    def test_a_raised_conviction_is_discarded(self):
        result, log = run(make_client(rm=verdict(adjusted_conviction=0.99)))
        self.assertLessEqual(result.decision.conviction, 0.75)
        self.assertTrue(log.events("override_attempt"))

    def test_a_reject_verdict_stops_the_trade(self):
        client = make_client(rm=verdict(verdict="reject", commentary="Too close to CPI."))
        result, _ = run(client)
        self.assertFalse(result.actionable)
        self.assertIsNone(result.record)
        self.assertNotIn("executor", client.stages_called())

    def test_a_flat_read_skips_the_executor_but_still_reports(self):
        client = make_client(read=chart_read(bias="flat", entry=None, stop=None, target=None))
        result, _ = run(client)
        self.assertFalse(result.actionable)
        self.assertIn("reporter", client.stages_called())
        self.assertNotIn("executor", client.stages_called())

    def test_a_geometry_breach_blocks_the_trade_despite_approval(self):
        client = make_client(read=chart_read(target=2403.0))  # reward:risk 0.3
        result, _ = run(client)
        self.assertFalse(result.actionable)
        self.assertIn("REWARD_RISK_TOO_LOW", {b.code for b in result.decision.breaches})


class ExecutorIsRechecked(unittest.TestCase):
    def test_an_executor_that_moves_the_stop_has_its_plan_discarded(self):
        result, log = run(make_client(execution=plan(stop=2385.0)))
        self.assertEqual(result.plan.action, "no_trade")
        self.assertIsNone(result.record)
        self.assertTrue(log.events("plan_rejected"))

    def test_an_executor_that_flips_direction_is_discarded(self):
        result, _ = run(make_client(execution=plan(action="sell")))
        self.assertEqual(result.plan.action, "no_trade")

    def test_an_executor_declining_to_trade_is_respected(self):
        result, _ = run(make_client(execution=plan(action="no_trade", order_type="none")))
        self.assertFalse(result.actionable)
        self.assertIsNone(result.record)


class LearningRunsFirst(unittest.TestCase):
    def test_open_trades_are_resolved_before_the_analyst_is_called(self):
        snapshot = snapshot_from(ramp(2360.0, 120, 0.4), timeframes=("h1", "m15"), end=NOW)
        first_ts = snapshot.series["m15"].candles[0].ts
        journal = Journal()
        journal.new_signal(
            direction="long", setup_type="bos_continuation", conviction=0.6,
            entry=2362.0, stop=2358.0, target=2370.0,
            ts=(first_ts).isoformat(),
        )
        client = make_client()
        result, log = run(client, feed=StubFeed(snapshot), journal=journal)
        self.assertEqual(len(result.resolved), 1)
        self.assertTrue(log.events("outcomes_resolved"))
        # The resolution record precedes the analyst's call in the trail.
        events = [r["event"] for r in log.records]
        self.assertLess(events.index("outcomes_resolved"), events.index("llm_call"))

    def test_a_blocked_setup_cannot_be_traded_even_if_the_models_agree(self):
        from tests_gold.test_journal_learning import journal_with

        journal = journal_with("range_fade", 80, -1.0)
        client = make_client(read=chart_read(setup_type="range_fade"))
        config = GoldConfig(limits=TradingLimits(max_open_positions=99, max_signals_per_day=99))
        result, _ = run(client, config=config, journal=journal)
        self.assertFalse(result.actionable)
        self.assertIn("SETUP_BLOCKED_BY_RECORD", {b.code for b in result.decision.breaches})


if __name__ == "__main__":
    unittest.main()
