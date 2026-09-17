import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.journal import Journal
from gold_trader.learning import learn
from gold_trader.macro import BlackoutPolicy, MacroCalendar, MacroEvent
from gold_trader.risk import TradingLimits, evaluate
from tests_gold.helpers import START
from tests_gold.test_journal_learning import journal_with

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
CLEAR_CALENDAR = MacroCalendar(events=[], confidence="current")


def assess(**kw):
    base = dict(
        direction="long", entry=2400.0, stop=2390.0, target=2420.0, conviction=0.7,
        setup_type="bos_continuation", atr=8.0, spot=2400.0, data_source="csv",
        staleness_min=5.0, now=NOW, limits=TradingLimits(), calendar=CLEAR_CALENDAR,
        journal=Journal(), learning=learn(Journal()),
    )
    base.update(kw)
    return evaluate(**base)


def codes(decision):
    return {b.code for b in decision.breaches}


class HappyPath(unittest.TestCase):
    def test_a_clean_trade_is_approved_and_sized_from_the_stop(self):
        # Pinned limits: sizing arithmetic must not move when defaults change.
        decision = assess(limits=TradingLimits(account_currency="USD", account_value=100_000, fx_to_usd=1.0, risk_per_trade_pct=0.5))
        self.assertTrue(decision.approved)
        # $100k account, 0.5% risk = $500, over a $10 stop = 50 oz.
        self.assertAlmostEqual(decision.risk_usd, 500.0)
        self.assertAlmostEqual(decision.size_units, 50.0)
        self.assertAlmostEqual(decision.reward_risk, 2.0)

    def test_a_flat_read_is_not_a_breach(self):
        decision = assess(direction="flat")
        self.assertFalse(decision.approved)
        self.assertEqual(codes(decision), {"NO_SIGNAL"})


class Geometry(unittest.TestCase):
    def test_a_stop_on_the_wrong_side_is_rejected(self):
        self.assertIn("STOP_WRONG_SIDE", codes(assess(stop=2410.0)))

    def test_a_target_on_the_wrong_side_is_rejected(self):
        self.assertIn("TARGET_WRONG_SIDE", codes(assess(target=2380.0)))

    def test_a_thin_reward_to_risk_is_rejected(self):
        self.assertIn("REWARD_RISK_TOO_LOW", codes(assess(target=2405.0)))

    def test_a_stop_inside_the_noise_band_is_rejected(self):
        self.assertIn("STOP_TOO_TIGHT", codes(assess(stop=2397.0, atr=20.0)))

    def test_an_absurdly_wide_stop_is_rejected(self):
        self.assertIn("STOP_TOO_WIDE", codes(assess(stop=2300.0, atr=8.0, target=2600.0)))

    def test_an_entry_far_from_spot_is_rejected(self):
        self.assertIn("ENTRY_FAR_FROM_SPOT", codes(assess(entry=2600.0, stop=2590.0, target=2620.0)))

    def test_a_missing_target_is_rejected(self):
        self.assertIn("NO_TARGET", codes(assess(target=None)))

    def test_missing_levels_are_rejected(self):
        self.assertIn("MISSING_LEVELS", codes(assess(stop=None)))

    def test_a_missing_atr_only_warns(self):
        decision = assess(atr=None)
        self.assertIn("NO_ATR", codes(decision))
        self.assertTrue(decision.approved)

    def test_short_geometry_is_checked_with_the_sign_flipped(self):
        decision = assess(direction="short", entry=2400.0, stop=2410.0, target=2380.0)
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.reward_risk, 2.0)


class DataQuality(unittest.TestCase):
    def test_stale_prices_block_the_trade(self):
        self.assertIn("STALE_PRICES", codes(assess(staleness_min=500.0)))

    def test_a_hand_read_level_caps_conviction(self):
        decision = assess(data_source="manual", conviction=0.95)
        self.assertIn("MANUAL_SOURCE_CAP", codes(decision))
        self.assertLessEqual(decision.conviction, 0.5)
        self.assertTrue(decision.approved)


class EventGates(unittest.TestCase):
    def test_an_imminent_high_impact_release_blocks_entries(self):
        calendar = MacroCalendar(
            events=[MacroEvent("FOMC", "FOMC", NOW + timedelta(minutes=30), "high")],
            confidence="current",
        )
        decision = assess(calendar=calendar)
        self.assertIn("EVENT_BLACKOUT", codes(decision))
        self.assertFalse(decision.approved)

    def test_an_incomplete_calendar_warns_but_does_not_block(self):
        decision = assess(calendar=MacroCalendar(events=[], confidence="derived_only"))
        self.assertIn("CALENDAR_INCOMPLETE", codes(decision))
        self.assertTrue(decision.approved)


class SessionBudgets(unittest.TestCase):
    def test_the_daily_loss_limit_halts_trading(self):
        journal = Journal()
        for i in range(3):
            record = journal.new_signal(
                direction="long", setup_type="bos_continuation", conviction=0.6,
                entry=2400.0, stop=2390.0, target=2420.0,
            )
            journal.update_outcome(
                record, status="lost", r_multiple=-1.0, exit_ts=NOW.isoformat()
            )
        self.assertIn("DAILY_LOSS_LIMIT", codes(assess(journal=journal)))

    def test_too_many_open_positions_blocks_a_new_one(self):
        journal = Journal()
        for _ in range(2):
            journal.new_signal(direction="long", setup_type="bos_continuation", conviction=0.6,
                               entry=2400.0, stop=2390.0, target=2420.0)
        self.assertIn("MAX_OPEN_POSITIONS", codes(assess(journal=journal)))

    def test_the_daily_signal_budget_is_enforced(self):
        journal = Journal()
        limits = TradingLimits(max_open_positions=99)
        for _ in range(4):
            journal.new_signal(
                direction="long", setup_type="bos_continuation", conviction=0.6,
                entry=2400.0, stop=2390.0, target=2420.0,
                ts=NOW.isoformat(),
            )
        self.assertIn("SIGNAL_BUDGET", codes(assess(journal=journal, limits=limits)))


class LearnedGates(unittest.TestCase):
    def test_a_blocked_setup_cannot_trade(self):
        learning = learn(journal_with("range_fade", 80, -1.0), min_samples=20)
        decision = assess(setup_type="range_fade", learning=learning)
        self.assertIn("SETUP_BLOCKED_BY_RECORD", codes(decision))
        self.assertFalse(decision.approved)

    def test_a_losing_setup_reduces_the_size(self):
        learning = learn(journal_with("fvg_fill", 30, -1.0), min_samples=20)
        decision = assess(setup_type="fvg_fill", learning=learning)
        self.assertTrue(decision.approved)
        self.assertLess(decision.risk_usd, TradingLimits().base_risk_usd)
        self.assertLess(decision.multipliers["size_from_setup_record"], 1.0)

    def test_overconfidence_shrinks_the_recorded_conviction(self):
        learning = learn(journal_with("bos_continuation", 40, -1.0, conviction=0.9), min_samples=20)
        decision = assess(conviction=0.9, learning=learning)
        self.assertLess(decision.conviction, 0.9)

    def test_a_rejected_trade_is_sized_to_zero(self):
        decision = assess(staleness_min=999.0)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.size_units, 0.0)
        self.assertEqual(decision.risk_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
