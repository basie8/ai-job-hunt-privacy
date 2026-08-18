# XAUUSD FTMO Confluence EA

A MetaTrader 5 Expert Advisor for **XAUUSD (gold)**, built around the **FTMO
2-step evaluation** rule set. M15 execution with H1/H4 context, an 11-component
weighted confluence engine, scaled exits, and a high-impact news blackout driven
by the ForexFactory feed plus the MT5 economic calendar.

```
MQL5/Experts/XAUUSD_FTMO/
    XAUUSD_FTMO_Confluence_EA.mq5   main EA
    Include/CoreDefs.mqh            shared types and math helpers
    Include/TimeZones.mqh           DST-aware clock alignment
    Include/Statistics.mqh          win rate, profit factor, R expectancy
    Include/Dashboard.mqh           the Aurum console
    Include/ConfluenceEngine.mqh    11-component weighted signal engine
    Include/RiskGuard.mqh           FTMO compliance and position sizing
    Include/TradeExecutor.mqh       entries, partials, breakeven, trailing
    Include/NewsFilter.mqh          ForexFactory + MT5 calendar blackout
MQL5/Presets/                       Phase 1 / Phase 2 / Funded .set files
docs/STRATEGY.md                    full strategy specification and rationale
docs/SETUP.md                       installation, configuration, backtesting
```

## What it does

**Signal.** Eleven components — H4 regime, H1 trend, M15 trend + trigger,
ADX/DI, RSI, MACD, Stochastic, session VWAP, Bollinger location, pivot/prior-day
structure, and volume — each award weighted points to a bull score and a bear
score (0–100). A trade needs a high score *and* a clear margin over the opposite
side. Scoring rather than an AND-chain is what keeps eleven indicators from
reducing the system to two trades a month.

Four conditions are hard vetoes regardless of score: ADX below 20, ATR outside
its band, price more than 2.2 ATR from the M15 EMA21, and any news blackout.

**Exits.** Every position scales out — partial at 1R, stop to breakeven plus a
lock, ATR chandelier trail, runner to 3R. A trade that reaches 1R can no longer
lose. That is how a high proportion of green trades coexists with an average win
well above the average loss.

**Risk.** 0.5% per trade by default, sized off the actual stop distance and
capped by whatever room remains under the drawdown guards, so position size
shrinks automatically as equity falls. Losing streaks cut size further. Guards
trip at 2%/3% daily and 5%/7% total, against FTMO's 5%/10% limits.

**News.** 30-minute blackout each side of high-impact releases, from the
ForexFactory weekly JSON feed and the MT5 built-in calendar together, with a
manual CSV fallback. Positions are flattened 5 minutes *before* a window opens,
because FTMO forbids closing inside it too.

**Sessions and time alignment.** Three named sessions — **London** and **New
York** on by default, **Asia** optional and off. Times are entered in each
market's own local clock and converted at runtime, so the windows stay correct
through DST: the broker (CE(S)T), London, and New York all switch on *different*
dates, and for ~3 weeks a year the London/NY relationship is an hour off from the
rest of the year. The broker's GMT offset is auto-detected, range-checked, and
re-checked while running, and the FTMO 00:00 CE(S)T daily-loss boundary is
derived from it rather than hand-entered. Every resolved window is printed to the
journal at startup.

**One trade a day.** If nothing has triggered by 14:30 GMT, quota mode lowers the
threshold at 60% size. Switch it off (`InpUseDailyQuota = false`) if you would
rather be selective.

**The Aurum console.** A framed gold-on-black on-chart panel carrying a single
authoritative status banner — `ACTIVE`, `IN TRADE`, `PAUSED - NEWS`,
`CLOSED - SESSION`, `PAUSED - RISK GUARD`, `PAUSED - LIMIT`, `CLOSED - WEEKEND`,
`TARGET REACHED`, `HALTED` — each with the specific reason underneath. Sections
for FTMO progress, market state, news, and positions, plus two toggle buttons: a
**STATS** block (win rate, profit factor, avg win/loss, expectancy in R, streaks,
closed-equity drawdown) and a **PARAMS** block that prints the loaded strategy
configuration so a wrong preset is visible without opening the Inputs tab.

## Start here

1. **[docs/STRATEGY.md](docs/STRATEGY.md)** — the design and its rationale.
   Section 4, *"The 70% question"*, is the one to read first.
2. **[docs/SETUP.md](docs/SETUP.md)** — installation, the WebRequest whitelist,
   presets, and the backtesting protocol.

## Before you risk money

This EA has been written against the MQL5 API and the current FTMO rule set, but
**it has not been compiled or backtested in this environment** — there is no
MetaTrader installation here. Compile it in MetaEditor, then work through the
seven-step validation protocol in `docs/STRATEGY.md` §9 before it goes anywhere
near a paid challenge.

No expert advisor can guarantee a win rate. The parameters that ship here are
reasoned defaults for gold, not optimised values — treat them as a starting point
for your own walk-forward testing on your own broker's data.

## Verify the rules yourself

Prop-firm rules change. Confirm the current objectives at
[ftmo.com/en/trading-objectives](https://ftmo.com/en/trading-objectives/) and set
`InpProfitTargetPct`, `InpFtmoDailyLossPct` and `InpFtmoMaxLossPct` to match
before you begin a phase.
