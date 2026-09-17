"""Regressions for the failure modes the component audit found.

Common theme: when an input degrades, the system must apply *more* scrutiny, not
less, and must never die because a hand-edited file was malformed.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from gold_trader.journal import Journal
from gold_trader.learning import learn
from gold_trader.macro import MacroCalendar
from gold_trader.risk import TradingLimits, evaluate

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
CLEAR = MacroCalendar(events=[], confidence="current")


def assess(**kw):
    base = dict(
        direction="long", entry=4305.0, stop=4295.0, target=4335.0, conviction=0.7,
        setup_type="bos_continuation", atr=None, spot=4305.0, data_source="csv",
        staleness_min=1.0, now=NOW, limits=TradingLimits(), calendar=CLEAR,
        journal=Journal(), learning=learn(Journal()),
    )
    base.update(kw)
    return evaluate(**base)


def codes(decision):
    return {b.code for b in decision.breaches}


class StopWidthWithoutAtr(unittest.TestCase):
    """Losing ATR must not silently remove the only stop-width check."""

    def test_an_absurdly_tight_stop_is_blocked_without_atr(self):
        # Before this was fixed: approved, 5000oz, taken out by the spread.
        decision = assess(stop=4304.9, target=4400.0)
        self.assertFalse(decision.approved)
        self.assertIn("STOP_TOO_TIGHT", codes(decision))
        self.assertEqual(decision.size_units, 0.0)

    def test_an_absurdly_wide_stop_is_blocked_without_atr(self):
        decision = assess(stop=3800.0, target=5000.0)
        self.assertFalse(decision.approved)
        self.assertIn("STOP_TOO_WIDE", codes(decision))

    def test_a_sane_stop_still_passes_without_atr(self):
        decision = assess(stop=4295.0, target=4335.0)  # $10 = 0.23% of spot
        self.assertTrue(decision.approved)
        self.assertAlmostEqual(decision.size_units, 50.0)

    def test_the_fallback_is_announced_rather_than_silent(self):
        decision = assess()
        no_atr = next(b for b in decision.breaches if b.code == "NO_ATR")
        self.assertEqual(no_atr.severity, "info")
        self.assertIn("percent-of-spot", no_atr.detail)

    def test_losing_both_atr_and_spot_is_a_hard_block(self):
        decision = assess(atr=None, spot=0.0)
        self.assertFalse(decision.approved)
        self.assertIn("STOP_UNVERIFIABLE", codes(decision))

    def test_atr_takes_precedence_when_available(self):
        # With ATR present the percent band must not fire.
        decision = assess(atr=8.0, stop=4295.0, target=4335.0)
        self.assertNotIn("NO_ATR", codes(decision))
        self.assertTrue(decision.approved)


class MalformedCalendar(unittest.TestCase):
    """The calendar is hand-edited weekly, so it will be broken sooner or later."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, content: str) -> str:
        path = os.path.join(self.tmp.name, "calendar.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_unparseable_json_degrades_instead_of_raising(self):
        calendar = MacroCalendar.build(NOW, self._write("{not json"))
        self.assertEqual(calendar.confidence, "invalid")
        self.assertTrue(calendar.load_errors)

    def test_the_derived_events_survive_a_broken_file(self):
        # NFP and claims are computed, so they must still be there.
        calendar = MacroCalendar.build(NOW, self._write("{not json"))
        self.assertTrue(calendar.events)

    def test_a_json_array_is_rejected_without_raising(self):
        calendar = MacroCalendar.build(NOW, self._write(json.dumps([1, 2, 3])))
        self.assertEqual(calendar.confidence, "invalid")
        self.assertIn("not a JSON object", " ".join(calendar.load_errors))

    def test_one_bad_event_does_not_discard_the_good_ones(self):
        path = self._write(json.dumps({
            "covers_through": "2026-12-31T00:00:00Z",
            "events": [
                {"kind": "FOMC", "when": "2026-09-18T18:00:00Z"},
                {"kind": "CPI"},  # missing `when`
            ],
        }))
        calendar = MacroCalendar.build(NOW, path)
        self.assertTrue(any(e.kind == "FOMC" for e in calendar.events))
        self.assertEqual(len(calendar.load_errors), 1)

    def test_a_bad_reading_is_dropped_not_fatal(self):
        path = self._write(json.dumps({
            "covers_through": "2026-12-31T00:00:00Z",
            "readings": [{"name": "DXY"}],  # missing value/as_of
        }))
        calendar = MacroCalendar.build(NOW, path)
        self.assertEqual(calendar.readings, [])
        self.assertTrue(calendar.load_errors)

    def test_an_unparseable_horizon_is_reported(self):
        path = self._write(json.dumps({"covers_through": "not-a-date", "events": []}))
        calendar = MacroCalendar.build(NOW, path)
        self.assertEqual(calendar.confidence, "invalid")

    def test_parse_errors_reach_the_analyst_prompt(self):
        calendar = MacroCalendar.build(NOW, self._write("{not json"))
        self.assertIn("failed to parse", calendar.as_prompt_block(NOW))

    def test_parse_errors_reach_the_risk_engine(self):
        calendar = MacroCalendar.build(NOW, self._write("{not json"))
        decision = assess(calendar=calendar, atr=8.0)
        incomplete = next(b for b in decision.breaches if b.code == "CALENDAR_INCOMPLETE")
        self.assertIn("parse error", incomplete.detail)

    def test_parse_errors_reach_the_audit_log(self):
        calendar = MacroCalendar.build(NOW, self._write("{not json"))
        self.assertTrue(calendar.to_dict(NOW)["load_errors"])


class ManualSourceIsScrutinised(unittest.TestCase):
    """A hand-read level is the least reliable input, so it gets the most checks."""

    def test_conviction_is_capped_and_stop_width_still_enforced(self):
        decision = assess(data_source="manual", conviction=0.95, stop=4304.9, target=4400.0)
        self.assertIn("MANUAL_SOURCE_CAP", codes(decision))
        self.assertIn("STOP_TOO_TIGHT", codes(decision))
        self.assertFalse(decision.approved)

    def test_a_sane_manual_trade_is_allowed_at_capped_conviction(self):
        decision = assess(data_source="manual", conviction=0.95)
        self.assertTrue(decision.approved)
        self.assertLessEqual(decision.conviction, 0.5)




class SelfCheckPasses(unittest.TestCase):
    """The component audit must stay green, and must stay honest about itself."""

    def _report(self):
        from gold_trader.selfcheck import run_all
        return run_all(os.path.join(os.path.dirname(__file__), ".."))

    def test_every_component_check_passes(self):
        report = self._report()
        failures = [f"{r.component}/{r.check}: {r.detail}" for r in report.failures]
        self.assertEqual(failures, [], "component self-check regressed")

    def test_the_audit_covers_every_major_component(self):
        covered = {r.component for r in self._report().results}
        for component in ("source", "config", "docs", "cli", "feed", "risk",
                          "macro", "learning", "sessions", "smc", "pipeline"):
            self.assertIn(component, covered)

    def test_the_stub_check_does_not_flag_itself(self):
        # It greps for the raise statement, not the bare word, or it would.
        from gold_trader.selfcheck import check_stubs, Report
        report = Report()
        check_stubs(report, os.path.join(os.path.dirname(__file__), ".."))
        self.assertEqual(report.failures, [])


class ConfigCoherence(unittest.TestCase):
    def test_the_shipped_defaults_are_coherent(self):
        from gold_trader.config_checks import coherence_problems
        self.assertEqual(coherence_problems(), [])

    def test_an_inverted_stop_band_is_caught(self):
        from gold_trader.config_checks import coherence_problems
        problems = coherence_problems(TradingLimits(min_stop_atr_mult=5.0, max_stop_atr_mult=1.0))
        self.assertTrue(any("min_stop_atr_mult" in p for p in problems))

    def test_an_unreachable_daily_loss_limit_is_caught(self):
        # 2 signals a day cannot lose 10R; one of the two controls is dead weight.
        from gold_trader.config_checks import coherence_problems
        problems = coherence_problems(TradingLimits(max_signals_per_day=2, max_daily_loss_r=10.0))
        self.assertTrue(any("cannot be reached" in p for p in problems))

    def test_a_negative_risk_percent_is_caught(self):
        from gold_trader.config_checks import coherence_problems
        self.assertTrue(coherence_problems(TradingLimits(risk_per_trade_pct=-1.0)))

    def test_an_inverted_blackout_is_caught(self):
        from gold_trader.config_checks import coherence_problems
        from gold_trader.macro import BlackoutPolicy
        problems = coherence_problems(
            TradingLimits(blackout=BlackoutPolicy(before_high=5, before_medium=60))
        )
        self.assertTrue(any("narrower" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
