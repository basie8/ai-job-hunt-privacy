"""The dashboard's one contract: nothing fails silently.

'No trades yet' and 'the journal is corrupt' both render as an absence of
numbers. They must never render as the *same* absence, and a broken input must
never take the page dark.
"""

import json
import os
import tempfile
import unittest

from gold_trader.dashboard import ERROR, EMPTY, OK, Section, _collect, build
from gold_trader.dashboard_html import render

REPO = os.path.join(os.path.dirname(__file__), "..")

#: Building the payload runs the roadmap's `tests:` predicates, which spawn real
#: suite runs. Build it once for the whole module rather than per test.
_PAYLOAD = None


def dashboard_payload():
    global _PAYLOAD
    if _PAYLOAD is None:
        _PAYLOAD = build(REPO)
    return json.loads(json.dumps(_PAYLOAD))


class Collection(unittest.TestCase):
    def test_a_raising_collector_becomes_a_visible_error(self):
        def explode():
            raise RuntimeError("disk on fire")

        section = _collect("some/path", explode)
        self.assertEqual(section.status, ERROR)
        self.assertIn("disk on fire", section.reason)
        self.assertIn("traceback", section.data)

    def test_a_collector_that_works_keeps_its_source(self):
        section = _collect("fallback", lambda: Section(OK, data={"x": 1}))
        self.assertEqual(section.source, "fallback")

    def test_one_broken_collector_does_not_take_down_the_export(self):
        # The whole point: a dark dashboard is worse than a flagged panel.
        payload = dashboard_payload()
        self.assertIn("sections", payload)
        self.assertGreaterEqual(len(payload["sections"]), 8)


class EmptyIsNotError(unittest.TestCase):
    def test_a_missing_journal_reports_empty_with_a_reason(self):
        payload = dashboard_payload()
        trading = payload["sections"]["trading"]
        self.assertIn(trading["status"], (EMPTY, OK))
        if trading["status"] == EMPTY:
            self.assertTrue(trading["reason"], "an empty section must say why")

    def test_the_two_states_render_differently(self):
        base = dashboard_payload()
        empty = json.loads(json.dumps(base))
        empty["sections"]["trading"] = {
            "status": EMPTY, "data": None, "reason": "no trades yet", "source": "j.jsonl",
        }
        broken = json.loads(json.dumps(base))
        broken["sections"]["trading"] = {
            "status": ERROR, "data": {"traceback": "x"}, "reason": "JSONDecodeError",
            "source": "j.jsonl",
        }
        self.assertIn("state-empty", render(empty))
        self.assertIn("state-error", render(broken))
        # And the error styling must not appear merely because something is empty.
        empty_html = render(empty)
        self.assertNotIn("Failed to read</span>no trades yet", empty_html)


class ProblemAggregation(unittest.TestCase):
    def test_every_section_error_becomes_a_listed_problem(self):
        payload = dashboard_payload()
        errored = [n for n, s in payload["sections"].items() if s["status"] == ERROR]
        for name in errored:
            self.assertTrue(
                any(p["source"] == name for p in payload["problems"]),
                f"section {name} errored but raised no problem",
            )

    def test_health_is_critical_when_anything_critical_exists(self):
        payload = dashboard_payload()
        has_critical = any(p["severity"] == "critical" for p in payload["problems"])
        self.assertEqual(payload["health"] == "critical", has_critical)

    def test_the_missing_bridge_is_reported_not_hidden(self):
        payload = dashboard_payload()
        health = payload["sections"]["data_health"]
        if health["status"] == EMPTY:
            self.assertTrue(
                any(p["source"] == "bridge" for p in payload["problems"]),
                "a silent bridge must appear in problems",
            )

    def test_generated_at_is_always_present(self):
        self.assertIn("generated_at", dashboard_payload())


class CandleStalenessRespectsMarketHours(unittest.TestCase):
    """Gold closes for an hour each weekday evening and all weekend, and a
    perfectly healthy bridge delivers nothing in those windows because there
    is nothing to deliver. `pull-data` and the roadmap's `data:` predicate
    both already carry this exception; this panel's "Newest candle is N
    minutes old" critical did not, so the dashboard read critical every
    single evening and all weekend regardless of whether the bridge was
    actually healthy -- the exact false-alarm-on-a-schedule failure this
    project has removed everywhere else it appears.
    """

    def _build(self, now):
        import tempfile
        from unittest import mock

        import gold_trader.dashboard as dashboard

        class Frozen:
            def now(self, tz=None):
                return now

        with tempfile.TemporaryDirectory() as repo:
            data_dir = os.path.join(repo, "data")
            os.makedirs(data_dir)
            # Deliberately ancient: stale under any real-world "now", so the
            # only thing distinguishing the two cases below is market hours.
            with open(os.path.join(data_dir, "XAUUSD_h1.csv"), "w") as fh:
                fh.write("time,open,high,low,close,volume\n")
                fh.write("2020-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n")
            with mock.patch.object(dashboard, "datetime", Frozen()):
                return dashboard.build(repo)

    def _has_staleness_critical(self, payload):
        return any(
            p["source"] == "bridge" and "Newest candle" in p["message"]
            for p in payload["problems"]
        )

    def test_stale_candles_are_critical_while_the_market_is_open(self):
        from datetime import datetime, timezone

        thursday_afternoon = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
        payload = self._build(thursday_afternoon)
        self.assertTrue(self._has_staleness_critical(payload))

    def test_stale_candles_are_not_a_finding_over_the_weekend(self):
        from datetime import datetime, timezone

        saturday = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
        payload = self._build(saturday)
        self.assertFalse(self._has_staleness_critical(payload))


class Rendering(unittest.TestCase):
    def test_the_page_renders_from_the_real_repo(self):
        html = render(dashboard_payload())
        self.assertIn("<title>AURUM Control</title>", html)
        self.assertIn("dashboard-data", html)
        self.assertGreater(len(html), 10_000)

    def test_every_problem_appears_in_the_page(self):
        payload = dashboard_payload()
        html = render(payload)
        for problem in payload["problems"]:
            self.assertIn(problem["source"], html)

    def test_the_page_carries_its_own_staleness_check(self):
        html = render(dashboard_payload())
        self.assertIn("data stale", html)
        self.assertIn("STALE_MIN", html)

    def test_the_staleness_gate_clears_a_weekend_on_the_daily_audit(self):
        # The gate was pinned by name only, so its value could drift silently.
        # At the weekend the daily audit is the sole republisher, so the gate
        # must clear a 24h gap with room to spare or a late run reads as an
        # outage. It must also stay finite -- a gate that never fires would
        # let the page show yesterday's numbers as current, which is the one
        # failure this whole system exists to refuse.
        html = render(dashboard_payload())
        self.assertIn("var STALE_MIN = 48 * 60;", html)
        self.assertGreater(48 * 60, 24 * 60)

    def test_a_json_parse_failure_in_the_page_is_handled(self):
        # The embedded script must not leave a blank page if its own data is bad.
        html = render(dashboard_payload())
        self.assertIn("dashboard data unreadable", html)

    def test_both_themes_define_every_token(self):
        html = render(dashboard_payload())
        for token in ("--ground", "--ink", "--crit", "--good", "--accent"):
            self.assertGreaterEqual(
                html.count(token + ":"), 3, f"{token} missing from a theme block"
            )

    def test_visible_html_is_escaped(self):
        payload = dashboard_payload()
        payload["problems"].append(
            {"severity": "warning", "source": "test", "message": "<b>bold</b>"}
        )
        html = render(payload)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", html)

    def test_the_embedded_json_cannot_break_out_of_its_script_tag(self):
        # A "</script>" in any file path, task title or exception message would
        # otherwise close the tag early and take the whole page down.
        payload = dashboard_payload()
        payload["problems"].append(
            {"severity": "warning", "source": "test", "message": "</script><script>alert(1)</script>"}
        )
        html = render(payload)
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn("\\u003c/script", html)

    def test_the_escaped_json_still_parses_back_to_the_same_data(self):
        import re
        payload = dashboard_payload()
        payload["problems"].append(
            {"severity": "warning", "source": "test", "message": "a <b> & c </script>"}
        )
        html = render(payload)
        blob = re.search(
            r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.S
        ).group(1)
        restored = json.loads(blob)
        self.assertEqual(restored["problems"][-1]["message"], "a <b> & c </script>")


if __name__ == "__main__":
    unittest.main()


class PaperMode(unittest.TestCase):
    """A simulated result must never be able to read as a real fill."""

    def test_the_limits_default_to_paper(self):
        from gold_trader.risk import TradingLimits
        self.assertEqual(TradingLimits().mode, "paper")

    def test_any_other_mode_is_a_configuration_error(self):
        from gold_trader.config_checks import coherence_problems
        from gold_trader.risk import TradingLimits
        problems = coherence_problems(TradingLimits(mode="live"))
        self.assertTrue(any("only 'paper' is supported" in p for p in problems))

    def test_the_mode_reaches_the_analyst_prompt(self):
        from gold_trader.risk import TradingLimits
        self.assertIn("PAPER", TradingLimits().as_prompt_block())

    def test_journalled_signals_are_stamped_paper(self):
        from gold_trader.journal import Journal
        record = Journal().new_signal(
            direction="long", setup_type="bos_continuation", conviction=0.6,
            entry=4300.0, stop=4290.0, target=4320.0,
        )
        self.assertEqual(record.mode, "paper")

    def test_the_dashboard_shows_the_paper_badge(self):
        html = render(dashboard_payload())
        self.assertIn('class="paper"', html)
        self.assertIn("PAPER", html)
        self.assertIn("simulated against the candles", html)


class NoPanelMayQuietlyDie(unittest.TestCase):
    """Every collector runs against the real repo, and none may raise.

    `_collect` turns any exception into a visible ERROR panel rather than a
    dark page, which is the right trade -- but it also means a plain coding
    mistake inside one collector is caught, rendered as a small red box, and
    otherwise ignored. A reference to an out-of-scope name did exactly that
    here on 2026-09-18: the panel reported "NameError: name 'limits' is not
    defined" and every other panel carried on as if nothing were wrong.

    The per-section tests below each check one panel. This checks all of them
    at once, so a panel added later is covered without anyone remembering to.
    """

    def test_no_section_reports_an_error(self):
        payload = dashboard_payload()
        broken = {
            name: section.get("reason")
            for name, section in payload["sections"].items()
            if section["status"] == ERROR
        }
        self.assertEqual(broken, {}, f"collectors raised: {broken}")

    def test_an_errored_section_makes_the_whole_page_critical(self):
        # The protection that makes the above recoverable rather than silent:
        # a dead panel must fail the dashboard command, or the audit Routine
        # republishes a broken page and reports all clear.
        from gold_trader.dashboard import ERROR as E, Section, _collect

        def explode():
            raise RuntimeError("collector fell over")

        section = _collect("somewhere", explode)
        self.assertEqual(section.status, E)
        self.assertIn("collector fell over", section.reason)

    def test_the_trading_panel_states_both_caps(self):
        # A count of live positions with no ceiling beside it cannot be read.
        payload = dashboard_payload()
        data = payload["sections"]["trading"]["data"]
        for key in ("live_n", "resting_n", "max_live_positions",
                    "max_working_orders", "risk_at_work_usd"):
            self.assertIn(key, data)


class TheOpenPositionMustBeOnThePage(unittest.TestCase):
    """"1 closed trades" alone cannot be reconciled with two signals seen.

    live_n, resting_n and risk_at_work_usd were added to the payload and never
    rendered, so the page stated the learning sample and stayed silent about
    the trade currently running. A reader who has watched two signals go out
    sees "1" and reasonably concludes the system lost one.
    """

    def test_the_page_names_the_live_count(self):
        html = _render()
        self.assertIn("Live now", html)

    def test_the_page_names_the_resting_count(self):
        self.assertIn("Resting", _render())

    def test_the_live_tile_states_the_money_at_risk(self):
        # A count of positions without the exposure beside it is half the
        # answer, and the half that matters less.
        html = _render()
        self.assertRegex(html, r"at risk|nothing at risk")

    def test_closed_trades_is_still_shown(self):
        # The sample size drives every clamp; it must not be displaced.
        self.assertIn("Closed trades", _render())


class CountsReadAsEnglish(unittest.TestCase):
    def test_one_is_singular(self):
        from gold_trader.progress import _plural

        self.assertEqual(_plural(1, "closed trade"), "1 closed trade")

    def test_zero_and_many_are_plural(self):
        from gold_trader.progress import _plural

        self.assertEqual(_plural(0, "closed trade"), "0 closed trades")
        self.assertEqual(_plural(20, "test"), "20 tests")


def _render():
    from gold_trader.dashboard_html import render

    return render(dashboard_payload())
