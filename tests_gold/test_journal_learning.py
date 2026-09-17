import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.feed import Candle, Series
from gold_trader.journal import Journal, SignalRecord, resolve_against, resolve_all
from gold_trader.learning import calibration_of, learn, setup_stats, walk_forward_split, wilson_lower_bound
from tests_gold.helpers import START


def bar(offset_h, low, high, close=None):
    close = close if close is not None else (low + high) / 2
    return Candle(START + timedelta(hours=offset_h), open=(low + high) / 2, high=high, low=low, close=close)


def long_signal(**kw):
    base = dict(
        id="s1", ts=START.isoformat(), direction="long", setup_type="bos_continuation",
        conviction=0.7, entry=2400.0, stop=2390.0, target=2420.0,
    )
    base.update(kw)
    return SignalRecord(**base)


class OutcomeResolution(unittest.TestCase):
    def test_target_hit_scores_the_full_r(self):
        out = resolve_against(long_signal(), [bar(1, 2398, 2425)])
        self.assertEqual(out["status"], "won")
        self.assertAlmostEqual(out["r_multiple"], 2.0)

    def test_stop_hit_scores_minus_one_r(self):
        out = resolve_against(long_signal(), [bar(1, 2385, 2405)])
        self.assertEqual(out["status"], "lost")
        self.assertAlmostEqual(out["r_multiple"], -1.0)

    def test_a_bar_covering_both_resolves_as_a_loss(self):
        # Bar data cannot order intrabar touches, so the unfavourable branch wins.
        out = resolve_against(long_signal(), [bar(1, 2385, 2425)])
        self.assertEqual(out["status"], "lost")
        self.assertEqual(out["resolution"], "stop_and_target_same_bar")

    def test_short_trades_score_with_the_sign_flipped(self):
        short = long_signal(direction="short", entry=2400.0, stop=2410.0, target=2380.0)
        out = resolve_against(short, [bar(1, 2375, 2395)])
        self.assertEqual(out["status"], "won")
        self.assertAlmostEqual(out["r_multiple"], 2.0)

    def test_an_untouched_trade_stays_open(self):
        self.assertIsNone(resolve_against(long_signal(), [bar(1, 2398, 2405)]))

    def test_candles_before_entry_are_ignored(self):
        early = Candle(START - timedelta(hours=2), 2400, 2430, 2380, 2400)
        self.assertIsNone(resolve_against(long_signal(), [early]))

    def test_expiry_closes_at_the_last_close(self):
        record = long_signal(valid_until=(START + timedelta(hours=2)).isoformat())
        out = resolve_against(record, [bar(1, 2398, 2404, close=2402), bar(3, 2399, 2405, close=2403)])
        self.assertEqual(out["status"], "expired")
        self.assertAlmostEqual(out["r_multiple"], 0.3)

    def test_mae_and_mfe_are_recorded(self):
        out = resolve_against(long_signal(), [bar(1, 2395, 2410), bar(2, 2385, 2425)])
        self.assertLess(out["mae_r"], 0)
        self.assertGreater(out["mfe_r"], 0)

    def test_a_flat_signal_never_resolves(self):
        self.assertIsNone(resolve_against(long_signal(direction="flat"), [bar(1, 2000, 2500)]))


class JournalPersistence(unittest.TestCase):
    def test_signals_and_outcomes_round_trip_through_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            journal = Journal(path)
            record = journal.new_signal(
                direction="long", setup_type="bos_continuation", conviction=0.8,
                entry=2400.0, stop=2390.0, target=2420.0,
            )
            journal.update_outcome(record, status="won", r_multiple=2.0, exit_ts=START.isoformat())

            reloaded = Journal(path)
            self.assertEqual(len(reloaded.records), 1)
            self.assertEqual(reloaded.records[0].status, "won")
            self.assertAlmostEqual(reloaded.records[0].r_multiple, 2.0)
            self.assertEqual(reloaded.summary()["wins"], 1)

    def test_open_signals_exclude_flat_and_closed(self):
        journal = Journal()
        journal.new_signal(direction="long", setup_type="bos_continuation", conviction=0.6,
                           entry=2400.0, stop=2390.0, target=2420.0)
        journal.new_signal(direction="flat", setup_type="no_setup", conviction=0.0)
        self.assertEqual(len(journal.open_signals()), 1)

    def test_resolve_all_updates_every_touched_trade(self):
        journal = Journal()
        journal.new_signal(direction="long", setup_type="bos_continuation", conviction=0.6,
                           entry=2400.0, stop=2390.0, target=2420.0,
                           ts=START.isoformat())
        series = Series("m15", [bar(1, 2398, 2425)], source="test")
        self.assertEqual(len(resolve_all(journal, series)), 1)
        self.assertEqual(journal.closed()[0].status, "won")


class Statistics(unittest.TestCase):
    def test_wilson_bound_is_below_the_point_estimate_on_small_samples(self):
        self.assertLess(wilson_lower_bound(3, 4), 0.75)

    def test_wilson_bound_tightens_as_the_sample_grows(self):
        self.assertLess(wilson_lower_bound(6, 8), wilson_lower_bound(600, 800))

    def test_wilson_bound_of_nothing_is_zero(self):
        self.assertEqual(wilson_lower_bound(0, 0), 0.0)

    def test_calibration_detects_overconfidence(self):
        records = [
            SignalRecord(id=str(i), ts=START.isoformat(), direction="long",
                         setup_type="bos_continuation", conviction=0.9,
                         r_multiple=(2.0 if i < 3 else -1.0))
            for i in range(10)
        ]
        cal = calibration_of(records)
        self.assertAlmostEqual(cal.mean_conviction, 0.9)
        self.assertAlmostEqual(cal.realized_win_rate, 0.3)
        self.assertGreater(cal.overconfidence, 0.5)

    def test_setup_stats_separate_the_buckets(self):
        records = [
            SignalRecord(id="a", ts=START.isoformat(), direction="long",
                         setup_type="bos_continuation", conviction=0.7, r_multiple=2.0),
            SignalRecord(id="b", ts=START.isoformat(), direction="long",
                         setup_type="range_fade", conviction=0.7, r_multiple=-1.0),
        ]
        stats = setup_stats(records)
        self.assertAlmostEqual(stats["bos_continuation"].expectancy_r, 2.0)
        self.assertAlmostEqual(stats["range_fade"].expectancy_r, -1.0)

    def test_walk_forward_holds_out_the_newest_trades(self):
        records = [
            SignalRecord(id=str(i), ts=(START + timedelta(days=i)).isoformat(),
                         direction="long", setup_type="bos_continuation", conviction=0.7, r_multiple=1.0)
            for i in range(20)
        ]
        train, holdout = walk_forward_split(records, 0.7)
        self.assertEqual(len(train), 14)
        self.assertEqual(len(holdout), 6)
        self.assertLess(train[-1].ts, holdout[0].ts)

    def test_walk_forward_does_not_split_a_tiny_journal(self):
        records = [SignalRecord(id="a", ts=START.isoformat(), direction="long",
                                setup_type="bos_continuation", conviction=0.7, r_multiple=1.0)]
        train, holdout = walk_forward_split(records)
        self.assertEqual(holdout, [])


def journal_with(setup, n, r_each, conviction=0.7):
    journal = Journal()
    for i in range(n):
        record = journal.new_signal(
            direction="long", setup_type=setup, conviction=conviction,
            entry=2400.0, stop=2390.0, target=2420.0,
            ts=(START + timedelta(days=i)).isoformat(),
        )
        journal.update_outcome(
            record, status="won" if r_each > 0 else "lost", r_multiple=r_each,
            exit_ts=(START + timedelta(days=i, hours=4)).isoformat(),
        )
    return journal


class LearningGuarantees(unittest.TestCase):
    def test_cold_start_applies_no_clamps(self):
        state = learn(Journal())
        self.assertEqual(state.status(), "cold_start")
        self.assertEqual(state.conviction_multiplier(), 1.0)
        self.assertEqual(state.size_multiplier("bos_continuation"), 1.0)
        self.assertIn("none yet", state.lessons_block())

    def test_a_small_sample_does_not_move_anything(self):
        state = learn(journal_with("bos_continuation", 5, -1.0), min_samples=20)
        self.assertEqual(state.status(), "warming_up")
        self.assertEqual(state.conviction_multiplier(), 1.0)
        self.assertEqual(state.size_multiplier("bos_continuation"), 1.0)

    def test_overconfidence_shrinks_conviction_once_the_sample_is_large(self):
        journal = journal_with("bos_continuation", 40, -1.0, conviction=0.9)
        state = learn(journal, min_samples=20)
        self.assertLess(state.conviction_multiplier(), 1.0)
        self.assertIn("OVERCONFIDENT", state.lessons_block())

    def test_learning_never_sizes_above_one(self):
        # A flawless record must not increase risk beyond the base setting.
        state = learn(journal_with("bos_continuation", 100, 3.0), min_samples=20)
        self.assertEqual(state.size_multiplier("bos_continuation"), 1.0)
        self.assertEqual(state.conviction_multiplier(), 1.0)

    def test_a_losing_setup_is_sized_down(self):
        state = learn(journal_with("range_fade", 30, -1.0), min_samples=20)
        self.assertLess(state.size_multiplier("range_fade"), 1.0)

    def test_a_persistently_losing_setup_is_blocked(self):
        state = learn(journal_with("range_fade", 80, -1.0), min_samples=20)
        self.assertIn("range_fade", state.blocked_setups())
        self.assertIn("BLOCKED", state.lessons_block())

    def test_an_unknown_setup_is_never_blocked(self):
        state = learn(journal_with("range_fade", 80, -1.0), min_samples=20)
        self.assertEqual(state.size_multiplier("bos_continuation"), 1.0)
        self.assertNotIn("bos_continuation", state.blocked_setups())

    def test_lessons_block_reports_the_holdout(self):
        state = learn(journal_with("bos_continuation", 40, 1.0), min_samples=20)
        self.assertGreater(state.holdout_n, 0)
        self.assertIn("Out-of-sample", state.lessons_block())


if __name__ == "__main__":
    unittest.main()
