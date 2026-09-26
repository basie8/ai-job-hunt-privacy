# XAUUSD signal pipeline with a measured feedback loop

Four model stages over spot gold, with the exposure controls enforced in code,
the macro diary treated as a risk control, and every signal scored against what
actually happened so the next run is constrained by the last hundred.

```
   candles + macro diary + the track record so far
                       |
                       v
   [0] resolve open trades, re-score the journal      (no model)
                       |
                       v
   [1] Analyst        opus-5   effort=high   -> bias, setup, entry/stop/target
                       |
                       v
   [2] Risk Manager   opus-5   effort=max    -> tighten or veto
                       |
        enforcement: tighter of the two, then the limit engine   (no model)
                       |
                       v
   [3] Executor       sonnet-5 effort=low    -> order type, how long it lives
                       |
        drift check: levels must match what was approved         (no model)
                       |
                       v
   [4] Reporter       haiku-4-5              -> the alert you receive
```

## Read this first: what this environment can and cannot do

**There is no live price feed here.** The session's egress policy returns 403 on
CONNECT for every market data host tried — Yahoo Finance, stooq, Twelve Data,
Polygon, Alpha Vantage, OANDA, Tiingo. `python -m gold_trader doctor` prints the
current state. Web search returns *narrative* gold prices that disagreed by about
2% across sources at the time of writing; that is wider than most intraday
ranges, so it cannot place an entry or a stop and this package will not pretend
otherwise. `HttpFeed` raises `FeedUnavailable` naming the blocked host and the
missing key rather than returning anything.

**What works today, with no network:**

| Adapter | Input | Use |
|---|---|---|
| `CsvFeed` | `XAUUSD_h1.csv` etc. from MT4/MT5, TradingView, Dukascopy | The main offline path. Column spellings are aliased, so exports need no editing. |
| `InlineFeed` | candles as JSON or a Python list | Pasting a handful of bars straight in. |
| `SnapshotFeed` | one hand-entered price and a few levels | When all you have is a chart screenshot. Conviction is capped at 0.5 and the source is recorded as `manual`. |

**To go live** two things must both be true: the egress policy allows one vendor
host, and that vendor's key is in the environment. `KNOWN_VENDORS` in `feed.py`
lists the host and env var for each. Until then the pipeline runs on supplied data.

## The feedback loop

This is the part that improves. It is a measured loop, not self-modifying code:
nothing rewrites its own weights or its own source.

**1. Every signal is journalled** with the full deterministic feature snapshot
that produced it — EMAs, RSI, ATR, structure, the macro diary, the data source.
An outcome can therefore be attributed to the conditions that were actually
present, not to a remembered version of them.

**2. Outcomes are resolved against later candles** before the next run's analyst
is called. When one bar's range covers both the stop and the target, the stop is
assumed: bar data cannot order intrabar touches, and optimistic tie-breaking is
how backtests learn to lie.

**3. The record is compiled into a lessons block** that the analyst reads *before*
forming a view — its own win rate and expectancy per setup type, and its
calibration (did a stated 0.85 conviction actually win 85% of the time?).

**4. The same measurements drive clamps the code applies afterwards**, so a model
that says "0.9 conviction" on a setup that has lost money does not get to act on it.

Three guards stop this becoming curve-fitting:

- **Learning can only reduce risk.** Every size multiplier is capped at 1.0. A
  flawless record never increases position size; only the base risk setting does.
  A losing record cuts it.
- **Minimum samples.** Nothing adjusts below 20 closed trades; a setup is only
  blocked outright at 40. Win rates are reported with a Wilson 95% lower bound so
  a 3-from-4 start does not read as a 75% edge.
- **Walk-forward.** Clamps are fit on the older 70% of the journal and reported
  against the newer 30%, so the numbers driving the clamps are not the same
  trades that produced them.

See it close, with no API calls and no market data:

```bash
python gold_trader/examples/demo_learning_loop.py
```

At 10 closed trades it reports but does not act. At 30 the conviction multiplier
drops to 0.50 on measured overconfidence. At 90 the losing setup is sized to 0.50
while the winning one stays at 1.00 — never above.

## Risk controls (enforced in code, not by a model)

| Control | Default | On breach |
|---|---|---|
| Event blackout | 60min before / 30min after high-impact | Hard block |
| Stale prices | 90 minutes | Hard block |
| Stop distance | 0.6x–3.0x ATR | Hard block (too tight is noise; too wide is not a stop) |
| Reward:risk | 1.5 minimum | Hard block |
| Entry vs spot | within 2% | Hard block |
| Daily loss | -2.0R realised | Hard block for the rest of the day |
| Open positions | 2 | Hard block |
| Signals per day | 4 | Hard block |
| Setup blocked by record | 40 trades, < -0.20R | Hard block |
| Hand-read levels | conviction capped at 0.5 | Warning + cap |
| Calendar incomplete | — | Warning |

Position size is never chosen by a model. It falls out of the stop:
`size = (account × risk% × learned_multiplier) / stop_distance`.

The risk manager may tighten a stop, pull in a target or cut conviction. Attempts
to widen any of them are discarded and written to the audit log as
`override_attempt`. The executor may choose order mechanics only — if its plan
comes back with different levels, the plan is discarded, not the levels.

## Macro events

Gold's sharpest moves cluster around scheduled US releases, so the diary is a
risk control before it is an analysis input.

- **Derived automatically**: NFP (first Friday, 08:30 ET) and jobless claims
  (Thursdays, 08:30 ET).
- **Loaded from `state/calendar.json`**: FOMC, CPI, PPI, PCE. Copy
  `examples/calendar.example.json` and keep it current. It ships with the two
  remaining 2026 FOMC dates, sourced from federalreserve.gov; the CPI/PCE entries
  are placeholders you must fill.
- When that file is missing or its `covers_through` has lapsed, the calendar
  reports `derived_only` / `stale` and the analyst is told the diary is
  incomplete rather than being allowed to assume it is clear.

`DRIVER_NOTES` in `macro.py` gives each release's transmission channel to gold —
real yields and the dollar — so the analyst reasons about mechanism, not just
"there is an event".

## Usage

```bash
pip install -r investment_pipeline/requirements.txt
export ANTHROPIC_API_KEY=...          # or `ant auth login`

python -m gold_trader doctor                              # what data is reachable
python -m gold_trader signal   --csv-dir data/            # all four stages
python -m gold_trader resolve  --csv-dir data/            # score open trades, no model calls
python -m gold_trader learn                               # the record and active clamps
python -m gold_trader status                              # open positions, daily budgets
python -m gold_trader calendar                            # the diary as loaded
```

`resolve` and `learn` make no API calls, so the loop can be kept current for free
and only `signal` costs anything.

As a library:

```python
from gold_trader import CsvFeed, GoldConfig, TradingLimits, run_signal
from investment_pipeline.llm import AnthropicStageClient

config = GoldConfig(limits=TradingLimits(account_usd=50_000, risk_per_trade_pct=0.4))
result = run_signal(CsvFeed("data/"), AnthropicStageClient(), config=config)

print(result.notification_text())
print(result.decision.to_dict())
```

## Cost

Four calls per signal. The analyst and risk stages carry the context, so a run
lands near **$0.30–0.45** at the published rates, dominated by the risk stage at
`max` effort. `resolve` and `learn` are free. The audit log's `cost_by_stage()`
gives the measured figure once you have run it.

## What this is not

- **No broker connectivity.** Stage 3 produces an order *intent*. Nothing is sent
  anywhere and nothing can trade by accident.
- **No backtest.** The prompts, the limits and the setup taxonomy are a starting
  configuration, not a validated strategy. The learning loop measures live
  results; it does not tell you the configuration was ever any good to begin with.
- **The learning loop needs trades to learn from.** At 20 closed signals it is
  still warming up. Expect it to be honest about that rather than useful early.
- **Signal generation, not advice.** Every output is a proposal with the reasoning
  and the binding constraint attached, for a human to accept or ignore.
