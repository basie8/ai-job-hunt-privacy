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
        # The bar must span the entry, or the order never fills: it used to
        # read (2375, 2395), which reaches the target without ever trading at
        # 2400 -- a win on a position nobody held.
        out = resolve_against(short, [bar(1, 2375, 2405)])
        self.assertEqual(out["status"], "won")
        self.assertAlmostEqual(out["r_multiple"], 2.0)

    def test_an_untouched_trade_stays_open(self):
        # That bar spans the entry, so the order fills and the fill is
        # persisted -- but nothing resolves, which is what this asserts.
        out = resolve_against(long_signal(), [bar(1, 2398, 2405)])
        self.assertIsNone(out.get("status"))

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


class AnUnfilledOrderIsNotATrade(unittest.TestCase):
    """A signal only becomes a position when price trades at its entry.

    Scoring from the moment the signal is written is not a neutral
    simplification, it is a one-sided one. A stop always sits beyond the entry,
    so price must pass through the entry to reach it and a loss is always
    genuinely filled. A target does not: price can run straight to it from
    wherever spot was. So the omission manufactures wins and never manufactures
    losses, and every clamp the learning loop later derives inherits the bias.

    The first signal this system ever produced was exactly this shape: a limit
    at 4353.00 with spot at 4358.81 and a target at 4374.00.
    """

    def test_a_target_reached_without_a_fill_is_not_a_win(self):
        # Price runs up from above the entry and never comes back. The old code
        # booked +2R here.
        out = resolve_against(long_signal(), [bar(1, 2402, 2425)])
        self.assertIsNone(out)

    def test_the_same_move_after_a_fill_is_a_win(self):
        out = resolve_against(long_signal(), [bar(1, 2395, 2425)])
        self.assertEqual(out["status"], "won")

    def test_a_stop_cannot_be_hit_without_a_fill(self):
        # Not a rule, a consequence: for a long, stop < entry, so any bar low
        # that reaches the stop has already crossed the entry. Stated as a test
        # because it is the asymmetry that makes the bias one-directional.
        out = resolve_against(long_signal(), [bar(1, 2385, 2405)])
        self.assertEqual(out["status"], "lost")

    def test_a_fill_and_a_stop_on_the_same_bar_is_a_loss(self):
        # The bar that fills can also stop out, and bar data cannot order
        # intrabar touches, so the unfavourable branch is assumed -- the same
        # rule already used when one bar spans stop and target.
        out = resolve_against(long_signal(), [bar(1, 2385, 2401)])
        self.assertEqual(out["status"], "lost")

    def test_a_fill_on_a_later_bar_still_scores(self):
        out = resolve_against(long_signal(), [bar(1, 2402, 2408), bar(2, 2395, 2425)])
        self.assertEqual(out["status"], "won")

    def test_excursions_are_measured_from_the_fill_not_the_signal(self):
        # MAE/MFE before a fill describe a position that did not exist.
        out = resolve_against(long_signal(),
                              [bar(1, 2403, 2420), bar(2, 2385, 2405)])
        self.assertEqual(out["status"], "lost")
        self.assertAlmostEqual(out["mfe_r"], 0.5)   # 2405 on the filling bar
        self.assertNotAlmostEqual(out["mfe_r"], 2.0)  # not 2420, before the fill

    def test_an_order_that_expires_unfilled_is_cancelled_not_expired(self):
        signal = long_signal()
        signal.valid_until = (START + timedelta(hours=3)).isoformat()
        out = resolve_against(signal, [bar(1, 2402, 2408), bar(4, 2402, 2408)])
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(out["resolution"], "expired_unfilled")
        self.assertIsNone(out["r_multiple"])

    def test_a_cancelled_order_stays_out_of_the_track_record(self):
        # It must shrink the sample, not pad it with a zero that drags
        # expectancy toward nothing. CANCELLED is outside CLOSED_STATES.
        from gold_trader.journal import CANCELLED, CLOSED_STATES

        self.assertNotIn(CANCELLED, CLOSED_STATES)

    def test_a_filled_order_that_expires_is_still_scored_at_the_close(self):
        # The existing behaviour, which the fill gate must not disturb.
        signal = long_signal()
        signal.valid_until = (START + timedelta(hours=3)).isoformat()
        out = resolve_against(signal, [bar(1, 2395, 2405), bar(4, 2398, 2406)])
        self.assertEqual(out["status"], "expired")
        self.assertIsNotNone(out["r_multiple"])


class RestingIsNotTheSameAsLive(unittest.TestCase):
    """Whether an order filled is a fact the system must keep, not recompute.

    `resolve_against` worked out the fill and then dropped it on the floor, so
    five separate consumers -- the position cap, `status`, the dashboard, the
    journal summary and the resolve report -- all saw one undifferentiated
    "open". A reader could not answer "is money at risk right now", which is
    the first question any of them exists to answer.
    """

    def test_a_fill_is_persisted_even_though_nothing_resolved(self):
        out = resolve_against(long_signal(), [bar(1, 2395, 2405)])
        self.assertIsNotNone(out)
        self.assertIn("filled_at", out)

    def test_an_untouched_order_persists_nothing(self):
        self.assertIsNone(resolve_against(long_signal(), [bar(1, 2402, 2408)]))

    def test_a_known_fill_is_not_re_derived_from_the_candles(self):
        # The candle files are a rolling window. Once the filling bar ages out,
        # re-deriving would read a live position as never filled and silently
        # stop scoring it.
        signal = long_signal()
        signal.filled_at = START.isoformat()
        out = resolve_against(signal, [bar(1, 2402, 2425)])
        self.assertEqual(out["status"], "won")

    def test_the_resolution_carries_the_fill_that_produced_it(self):
        out = resolve_against(long_signal(), [bar(1, 2395, 2425)])
        self.assertIsNotNone(out["filled_at"])

    def test_a_fill_is_not_reported_as_a_resolution(self):
        # resolve_all's callers format an R multiple a fill does not have, and
        # announcing a closed trade that has not closed is its own lie.
        journal = Journal(os.path.join(self.dir, "journal.jsonl"))
        record = self._journalled(journal)
        resolved = resolve_all(journal, self._series([bar(1, 2395, 2405)]))
        self.assertEqual(resolved, [])
        self.assertIsNotNone(journal.records[0].filled_at)

    def test_the_views_separate_the_two(self):
        journal = Journal(os.path.join(self.dir, "journal.jsonl"))
        self._journalled(journal)
        self.assertEqual(len(journal.resting()), 1)
        self.assertEqual(len(journal.live()), 0)

        resolve_all(journal, self._series([bar(1, 2395, 2405)]))
        self.assertEqual(len(journal.resting()), 0)
        self.assertEqual(len(journal.live()), 1)

    def test_both_are_still_open_signals(self):
        # open_signals keeps its meaning -- unresolved -- so the position cap
        # and every other existing consumer behave exactly as before until
        # someone deliberately changes them.
        journal = Journal(os.path.join(self.dir, "journal.jsonl"))
        self._journalled(journal)
        self.assertEqual(len(journal.open_signals()), 1)
        resolve_all(journal, self._series([bar(1, 2395, 2405)]))
        self.assertEqual(len(journal.open_signals()), 1)

    def test_the_fill_survives_a_reload(self):
        path = os.path.join(self.dir, "journal.jsonl")
        journal = Journal(path)
        self._journalled(journal)
        resolve_all(journal, self._series([bar(1, 2395, 2405)]))
        self.assertIsNotNone(Journal(path).records[0].filled_at)

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def _journalled(self, journal):
        record = long_signal()
        journal.add(record)
        return record

    def _series(self, candles):
        from gold_trader.feed import Series

        return Series(timeframe="m15", candles=candles)
