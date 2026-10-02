import argparse
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gold_trader.fx import (
    FX_FILENAME, MAX_DEVIATION_PCT, STALE_AFTER_HOURS, FxReading, load_fx, with_live_rate, write_fx,
)
from gold_trader.risk import TradingLimits

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def _stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class ReadingAge(unittest.TestCase):
    def test_a_fresh_reading_is_not_stale(self):
        reading = FxReading("GBPUSD", 1.34, _stamp(2), "MT5 GBPUSD")
        self.assertAlmostEqual(reading.age_hours(NOW), 2.0, places=3)
        self.assertFalse(reading.is_stale(NOW))

    def test_an_old_reading_is_stale(self):
        reading = FxReading("GBPUSD", 1.34, _stamp(STALE_AFTER_HOURS + 1), "MT5 GBPUSD")
        self.assertTrue(reading.is_stale(NOW))

    def test_an_unparseable_stamp_is_treated_as_stale_not_as_fresh(self):
        # Failing open here would present an unknown-age rate as current.
        reading = FxReading("GBPUSD", 1.34, "not a date", "MT5 GBPUSD")
        self.assertTrue(reading.is_stale(NOW))
        self.assertIn("age unknown", reading.provenance(NOW))
        self.assertIsNone(reading.to_dict(NOW)["age_hours"])

    def test_a_naive_stamp_is_read_as_utc(self):
        reading = FxReading("GBPUSD", 1.34, "2026-09-17T09:00:00", "MT5 GBPUSD")
        self.assertAlmostEqual(reading.age_hours(NOW), 3.0, places=3)


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_what_the_bridge_writes_is_what_the_reader_reads(self):
        write_fx(self.tmp.name, "GBPUSD", 1.3377, _stamp(1), "MT5 GBPUSD.m")
        reading = load_fx(self.tmp.name)
        self.assertEqual(reading.rate, 1.3377)
        self.assertEqual(reading.source, "MT5 GBPUSD.m")

    def test_a_second_pair_does_not_clobber_the_first(self):
        write_fx(self.tmp.name, "GBPUSD", 1.3377, _stamp(1), "MT5")
        write_fx(self.tmp.name, "EURUSD", 1.1000, _stamp(1), "MT5")
        self.assertEqual(load_fx(self.tmp.name, "GBPUSD").rate, 1.3377)
        self.assertEqual(load_fx(self.tmp.name, "EURUSD").rate, 1.1000)

    def test_a_missing_file_returns_none_rather_than_raising(self):
        self.assertIsNone(load_fx(self.tmp.name))

    def test_a_corrupt_file_returns_none_rather_than_guessing(self):
        with open(os.path.join(self.tmp.name, FX_FILENAME), "w") as fh:
            fh.write("{ this is not json")
        self.assertIsNone(load_fx(self.tmp.name))

    def test_a_corrupt_file_is_replaced_not_appended_to(self):
        with open(os.path.join(self.tmp.name, FX_FILENAME), "w") as fh:
            fh.write("garbage")
        write_fx(self.tmp.name, "GBPUSD", 1.33, _stamp(1), "MT5")
        with open(os.path.join(self.tmp.name, FX_FILENAME)) as fh:
            self.assertEqual(list(json.load(fh)), ["GBPUSD"])

    def test_a_missing_pair_returns_none(self):
        write_fx(self.tmp.name, "EURUSD", 1.1, _stamp(1), "MT5")
        self.assertIsNone(load_fx(self.tmp.name, "GBPUSD"))


class Resolution(unittest.TestCase):
    """with_live_rate must never substitute a rate silently."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.limits = TradingLimits(account_currency="GBP", fx_to_usd=1.3377)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_live_rate_replaces_the_static_one_and_records_its_provenance(self):
        write_fx(self.tmp.name, "GBPUSD", 1.3450, _stamp(1), "MT5 GBPUSD.m")
        limits, note = with_live_rate(self.limits, self.tmp.name, now=NOW)
        self.assertEqual(limits.fx_to_usd, 1.3450)
        self.assertIn("MT5 GBPUSD.m", limits.fx_as_of)
        self.assertFalse(note.startswith("FX WARNING"))

    def test_no_bridge_file_keeps_the_static_rate_and_says_so_loudly(self):
        limits, note = with_live_rate(self.limits, self.tmp.name, now=NOW)
        self.assertEqual(limits.fx_to_usd, 1.3377)
        self.assertTrue(note.startswith("FX WARNING"))
        self.assertIn(FX_FILENAME, note)

    def test_a_stale_rate_is_used_but_warned_about(self):
        # A day-old rate still beats a hardcoded one; a silent one does not.
        write_fx(self.tmp.name, "GBPUSD", 1.3450, _stamp(STALE_AFTER_HOURS + 5), "MT5")
        limits, note = with_live_rate(self.limits, self.tmp.name, now=NOW)
        self.assertEqual(limits.fx_to_usd, 1.3450)
        self.assertTrue(note.startswith("FX WARNING"))
        self.assertIn("bridge may have stopped", note)

    def test_an_absurd_rate_is_refused_as_a_misread_symbol(self):
        # MT5 symbol resolution could land on the wrong instrument. A wrong rate
        # rescales the entire book, so it is rejected rather than applied.
        write_fx(self.tmp.name, "GBPUSD", 4362.0, _stamp(1), "MT5 XAUUSD.m")
        limits, note = with_live_rate(self.limits, self.tmp.name, now=NOW)
        self.assertEqual(limits.fx_to_usd, 1.3377)
        self.assertTrue(note.startswith("FX WARNING"))
        self.assertIn("misread symbol", note)

    def test_a_rate_just_inside_the_deviation_band_is_accepted(self):
        rate = 1.3377 * (1 + (MAX_DEVIATION_PCT - 1) / 100.0)
        write_fx(self.tmp.name, "GBPUSD", rate, _stamp(1), "MT5")
        limits, _ = with_live_rate(self.limits, self.tmp.name, now=NOW)
        self.assertAlmostEqual(limits.fx_to_usd, rate)

    def test_a_usd_account_needs_no_rate_and_reads_no_file(self):
        usd = TradingLimits(account_currency="USD", fx_to_usd=1.0)
        limits, note = with_live_rate(usd, self.tmp.name, now=NOW)
        self.assertEqual(limits.fx_to_usd, 1.0)
        self.assertFalse(note.startswith("FX WARNING"))


class CliWiring(unittest.TestCase):
    """The CLI built TradingLimits with a field that had become a property,
    so every command raised TypeError while the suite stayed green."""

    def test_the_cli_can_build_a_config_with_no_overrides(self):
        from gold_trader.cli import _config

        config = _config(argparse.Namespace())
        self.assertEqual(config.limits.account_currency, "GBP")
        self.assertTrue(config.fx_note)

    def test_cli_overrides_do_not_discard_the_other_defaults(self):
        from gold_trader.cli import _config

        config = _config(argparse.Namespace(account=50_000.0, risk_pct=0.5))
        self.assertEqual(config.limits.account_value, 50_000.0)
        self.assertEqual(config.limits.risk_per_trade_pct, 0.5)
        # The floor is a default the override path must not drop.
        self.assertEqual(config.limits.min_equity_pct_of_start, 60.0)

    def test_every_cli_command_builds_its_config_without_raising(self):
        import gold_trader.cli as cli

        for name in [n for n in dir(cli) if n.startswith("cmd_")]:
            with self.subTest(command=name):
                cli._config(argparse.Namespace(state_dir=self.id()))


if __name__ == "__main__":
    unittest.main()
