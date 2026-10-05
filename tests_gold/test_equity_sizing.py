"""Fixed-fractional sizing: risk is a percent of CURRENT equity, not of the
starting notional. The difference only shows up once trades have closed, which
is exactly when nobody is looking, so it is pinned here."""

import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.journal import Journal
from gold_trader.learning import learn
from gold_trader.macro import MacroCalendar
from gold_trader.risk import TradingLimits, equity_usd, evaluate, realised_pnl_usd

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
CLEAR_CALENDAR = MacroCalendar(events=[], confidence="current")
#: $10,000 flat, 1% risk, $10 stop -- every number below is checkable by hand.
LIMITS = TradingLimits(
    account_currency="USD", account_value=10_000.0, fx_to_usd=1.0,
    risk_per_trade_pct=1.0, min_equity_pct_of_start=60.0,
)


def closed_journal(results):
    """results: list of (r_multiple, risk_usd) for trades closed long ago."""
    journal = Journal()
    for i, (r_multiple, risk_usd) in enumerate(results):
        record = journal.new_signal(
            direction="long", setup_type="bos_continuation", conviction=0.7,
            entry=2400.0, stop=2390.0, target=2420.0, risk_usd=risk_usd,
            ts=(NOW - timedelta(days=30 - i)).isoformat(),
        )
        journal.update_outcome(
            record, status="won" if r_multiple > 0 else "lost", r_multiple=r_multiple,
            exit_ts=(NOW - timedelta(days=30 - i, hours=-4)).isoformat(),
        )
    return journal


def assess(journal, limits=LIMITS, **kw):
    base = dict(
        direction="long", entry=2400.0, stop=2390.0, target=2420.0, conviction=0.7,
        setup_type="bos_continuation", atr=8.0, spot=2400.0, data_source="csv",
        staleness_min=5.0, now=NOW, limits=limits, calendar=CLEAR_CALENDAR,
        journal=journal, learning=learn(journal),
    )
    base.update(kw)
    return evaluate(**base)


class EquityMaths(unittest.TestCase):
    def test_an_empty_journal_leaves_equity_at_the_starting_notional(self):
        self.assertEqual(equity_usd(Journal(), LIMITS), 10_000.0)
        self.assertEqual(realised_pnl_usd(Journal()), 0.0)

    def test_realised_pnl_is_r_times_the_cash_that_was_at_risk(self):
        journal = closed_journal([(-1.0, 100.0), (2.0, 99.0)])
        self.assertAlmostEqual(realised_pnl_usd(journal), -100.0 + 198.0)

    def test_an_open_trade_does_not_move_equity(self):
        # Only realised P&L counts; marking open risk to market would let a
        # single floating winner inflate the next position.
        journal = closed_journal([(-1.0, 100.0)])
        journal.new_signal(direction="long", setup_type="bos_continuation",
                           conviction=0.7, entry=2400.0, stop=2390.0,
                           target=2420.0, risk_usd=100.0, ts=NOW.isoformat())
        self.assertAlmostEqual(equity_usd(journal, LIMITS), 9_900.0)


class SizingCompounds(unittest.TestCase):
    def test_the_first_trade_risks_one_percent_of_the_notional(self):
        decision = assess(Journal())
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.risk_usd, 100.0)
        self.assertAlmostEqual(decision.size_units, 10.0)

    def test_risk_shrinks_after_a_loss(self):
        decision = assess(closed_journal([(-1.0, 100.0)]))
        self.assertAlmostEqual(decision.risk_usd, 99.0)   # 1% of 9,900
        self.assertAlmostEqual(decision.size_units, 9.9)

    def test_risk_grows_after_a_win(self):
        decision = assess(closed_journal([(2.0, 100.0)]))
        self.assertAlmostEqual(decision.risk_usd, 102.0)  # 1% of 10,200

    def test_a_losing_streak_never_sizes_up(self):
        previous = float("inf")
        journal = Journal()
        results = []
        for _ in range(5):
            risk = assess(closed_journal(results)).risk_usd
            self.assertLess(risk, previous)
            previous = risk
            results.append((-1.0, risk))
        del journal


class RuinFloor(unittest.TestCase):
    def _drawn_down_to(self, fraction):
        loss = 10_000.0 * (1 - fraction)
        return closed_journal([(-1.0, loss)])

    def test_trading_continues_above_the_floor(self):
        self.assertTrue(assess(self._drawn_down_to(0.65)).approved)

    def test_trading_halts_at_the_floor(self):
        decision = assess(self._drawn_down_to(0.60))
        self.assertFalse(decision.approved)
        self.assertIn("EQUITY_FLOOR", {b.code for b in decision.breaches})

    def test_the_floor_breach_is_hard_not_a_warning(self):
        decision = assess(self._drawn_down_to(0.50))
        breach = next(b for b in decision.breaches if b.code == "EQUITY_FLOOR")
        self.assertEqual(breach.severity, "hard")

    def test_a_ruined_book_cannot_size_a_trade(self):
        # Without a floor, fixed-fractional sizing never reaches zero: the book
        # would keep trading forever in meaningless size.
        decision = assess(closed_journal([(-1.0, 9_999.0)]))
        self.assertFalse(decision.approved)


class CurrencyConversion(unittest.TestCase):
    def test_a_gbp_notional_sizes_against_its_usd_value(self):
        limits = TradingLimits(account_currency="GBP", account_value=10_000.0,
                               fx_to_usd=1.3377, risk_per_trade_pct=1.0)
        self.assertAlmostEqual(limits.account_usd, 13_377.0)
        self.assertAlmostEqual(assess(Journal(), limits).risk_usd, 133.77)

    def test_r_is_invariant_to_the_rate(self):
        # The whole reason a stale rate is a warning and not a blocker.
        cheap = TradingLimits(account_currency="GBP", account_value=10_000.0,
                              fx_to_usd=1.20, risk_per_trade_pct=1.0)
        dear = TradingLimits(account_currency="GBP", account_value=10_000.0,
                             fx_to_usd=1.40, risk_per_trade_pct=1.0)
        a, b = assess(Journal(), cheap), assess(Journal(), dear)
        self.assertAlmostEqual(a.size_units * 10.0 / a.risk_usd,
                               b.size_units * 10.0 / b.risk_usd)


if __name__ == "__main__":
    unittest.main()
