# Installation & Setup

## 1. Install the files

Copy the EA folder into your terminal's data directory (MetaTrader 5 →
*File → Open Data Folder*):

```
<Terminal Data Folder>/MQL5/Experts/XAUUSD_FTMO/
    XAUUSD_FTMO_Confluence_EA.mq5
    Include/
        CoreDefs.mqh
        NewsFilter.mqh
        RiskGuard.mqh
        ConfluenceEngine.mqh
        TradeExecutor.mqh
        Dashboard.mqh
```

Keep the `Include/` sub-folder where it is — the EA includes by relative path.

Open `XAUUSD_FTMO_Confluence_EA.mq5` in MetaEditor and press **F7**. It should
compile with zero errors.

## 2. Whitelist the ForexFactory feed

*Tools → Options → Expert Advisors → **Allow WebRequest for listed URL***, add:

```
https://nfs.faireconomy.media
```

Without this the FF feed returns error 4014 and the EA falls back to the MT5
built-in calendar. The journal tells you which sources came up.

## 3. Enable the MT5 economic calendar

*View → Toolbox → Calendar*. If it is empty, your broker does not serve it and
the FF feed is doing all the work — check the dashboard's event count is non-zero.

## 4. Attach it

Drop the EA on an **XAUUSD M15** chart. In the *Common* tab tick **Allow
Algo Trading**, and make sure the terminal's *Algo Trading* button is green.

## 5. Verify before trading

Check the on-chart dashboard reads sensibly:

- `News` shows a non-zero event count and a plausible next event.
- `Spread` is in the 15–35 point range during London/NY.
- `Daily DD` / `Total DD` show 0.00%.
- The journal line `[Init] server-GMT offset resolved to +N hours` matches your
  broker (FTMO servers are typically GMT+2 in winter, GMT+3 in summer).

If the GMT offset is wrong, set `InpUseManualGmtOffset = true` and
`InpGmtOffsetHours` to the correct value. **Everything — sessions, news, quota
timing, and the FTMO daily reset — depends on this being right.**

---

## The Aurum console

The on-chart panel is the EA's control surface — gold on warm near-black, framed,
with two-column rows. Everything the EA is thinking is on it, so a live challenge
never has to be audited from the journal.

### Status banner

The line under the header is the single authoritative statement of what the EA is
doing. It is set at every decision point in `OnTick`, so the panel and the trade
logic can never disagree.

| Banner | Colour | Meaning |
|---|---|---|
| `ACTIVE` | bright gold | In session, guards clear, hunting. The detail line shows the current confluence score and what it still needs. |
| `IN TRADE` | green | Position open and being managed. |
| `PAUSED - NEWS` | red | High-impact blackout. Shows the event and when it clears. |
| `CLOSED - SESSION` | grey | Outside every enabled session. |
| `PAUSED - RISK GUARD` | amber | A soft drawdown guard is holding trading. |
| `PAUSED - LIMIT` | amber | Trade cap, entry spacing, spread, or loss streak. |
| `CLOSED - WEEKEND` | grey | Friday cutoff or weekend flat. |
| `TARGET REACHED` | green | Phase target hit, standing down. |
| `HALTED` | red | A hard guard tripped — flat and stopped. |

Under each is a detail line with the specific reason, e.g. `spread 61 pts > 45
limit` or `USD Core CPI m/m`.

Because `OnTick` does not run when no ticks arrive, the timer re-derives the
session, news and weekend states every 20 seconds — the banner stays correct over
a weekend or a long blackout.

### Sections

- **FTMO PROGRESS** — target progress, daily and total drawdown against both the
  soft and hard guards, trading days against FTMO's minimum of 4, today's trades
  and realised P/L, and the risk that will be used on the next trade including
  the loss-streak factor.
- **MARKET** — session status (open, or which one is next and in how long), clock
  and DST state, spread against the limit, live ATR/ADX/RSI, VWAP.
- **NEWS** — events loaded and the next one, or the active blackout and its clear
  time.
- **POSITIONS** — open count and each position's management stage.
- **METRICS** — toggled with the `STATS` button, see below.
- **STRATEGY PARAMETERS** — toggled with the `PARAMS` button.

### The two buttons

`PARAMS` and `STATS` in the header bar toggle their blocks. `InpShowParamsBlock`
and `InpShowMetricsBlock` set the startup state.

**`PARAMS` is the pre-flight check.** It prints what is actually loaded —
timeframes, confluence gate, hard gates, risk basis, stop and target construction,
both guard ladders against the real FTMO limits, trade limits, enabled sessions,
quota settings, and the news configuration. Open it once after loading a preset to
confirm you are running what you think you are running. It turns the sessions row
red if none are enabled and the news row red if the filter is off.

### Metrics

| Metric | Note |
|---|---|
| Closed trades | W / L / breakeven |
| Win rate | green ≥60%, amber ≥45%, red below |
| Profit factor | green ≥1.35, amber ≥1.0, red below |
| Avg win / avg loss | with the payoff ratio; green ≥1.3 |
| Expectancy | **in R**, with sample size |
| Avg R win / loss | the asymmetry, made explicit |
| Total R | cumulative |
| Best / worst | largest single win and loss |
| Streaks | current, plus max win and loss streaks |
| Closed-equity drawdown | peak-to-trough on closed trades |

Money metrics are rebuilt from account history on startup
(`InpRebuildStatsOnInit`, `InpStatsHistoryDays`), grouping deals by position id so
a scaled-out trade counts once rather than three times. **R metrics start fresh
after a restart** — the entry risk of a historical trade is not recoverable from
the deal record, so it is reported with its own sample count rather than
estimated. The journal says so when it rebuilds.

Judge the strategy on **profit factor and expectancy in R**, not win rate. See
`docs/STRATEGY.md` §4.


---

## Time alignment and sessions

### How the offset is resolved

The EA detects the broker's GMT offset from `TimeTradeServer() - TimeGMT()`,
rounds to the nearest half hour, range-checks it, and **re-checks it on every
timer tick** so a DST transition is picked up while running. On startup it prints
every resolved window to the journal:

```
[Time] broker server clock is GMT+2 (offset +2.0 h).
[Time] FTMO day boundary: server time minus CE(S)T = +0.0 h (auto).
[Time] resolved session windows:
   Asia      disabled
   London    09:00-13:00 server   (London local 08:00-12:00, currently GMT+1)
   New York  14:00-18:00 server   (New York local 08:00-12:00, currently GMT-5)
   Fri stop  16:00 server   (GMT 15:00)
   Fri flat  20:00 server   (GMT 19:00)
   Quota     15:30 server   (GMT 14:30)
[Time] DST state: Europe standard, US standard.
```

**Check this block against your broker before trading.** It is the fastest way to
catch a wrong offset. The dashboard `Clock` row shows the same information live
and turns red if detection failed.

### The three sessions

| Input | Default | Meaning |
|---|---|---|
| `InpUseAsiaSession` | `false` | Tokyo 09:00–15:00 JST. Thin and choppy — off by default. |
| `InpUseLondonSession` | `true` | London 08:00–12:00 local. |
| `InpUseNewYorkSession` | `true` | New York 08:00–12:00 local — includes the 08:30 ET data window and the whole London/NY overlap. |

Each has its own start/end input. A trade is allowed if **any** enabled session is
open.

### `InpSessionTimeBase`

| Value | Meaning |
|---|---|
| `SESSION_TB_MARKET_LOCAL` | **Default.** Times are in each session's own market clock and converted with live DST. Set and forget. |
| `SESSION_TB_GMT` | Times are fixed GMT. Ignores market DST — your windows drift an hour twice a year. |
| `SESSION_TB_SERVER` | Times are literal broker server time. No conversion at all. |

**If you change the time base away from `MARKET_LOCAL`, re-enter the session
times** — the defaults are market-local values and will be wrong read as anything
else.

The Friday cutoff, weekend flatten and quota trigger are **always GMT**,
regardless of this setting. They are risk controls, not market sessions, so they
should not move with a market clock.

### The FTMO daily reset

`InpAutoCetOffset` (default `true`) derives the 00:00 CE(S)T boundary from the
detected server offset and the EU DST state — on an FTMO server this resolves to
`+0h` year-round. Set it to `false` and use `InpCetOffsetHours` only if your
broker's clock is not CE(S)T.

A boundary shift is **deferred** until no position is open and no trade has been
taken that day, because moving it mid-session would reset the daily loss counter.
The journal says so when it defers.

### Why this matters — the DST gap

EU and US clocks change on dates about two weeks apart, so for ~3 weeks a year the
London/NY relationship is an hour different. On a CE(S)T broker with the defaults:

| Date | Server | London (server) | New York (server) |
|---|---|---|---|
| mid-January | GMT+1 | 09:00–13:00 | 14:00–18:00 |
| **12 March** (US on DST, EU not) | GMT+1 | 09:00–13:00 | **13:00–17:00** |
| mid-July | GMT+2 | 09:00–13:00 | 14:00–18:00 |
| **28 October** (EU off DST, US still on) | GMT+1 | 09:00–13:00 | **13:00–17:00** |

With `MARKET_LOCAL` this is handled automatically. With fixed GMT you would be
trading the wrong hour in both gap periods.

---

## Broker compatibility

The EA validates the broker's contract specification at startup and **refuses to
initialise** rather than trading blind. The journal prints:

```
[Broker] XAUUSD contract specification:
   digits 2, point 0.01000, tick size 0.01000, tick value 1.00000 USD
   contract size 100.00, base XAU, profit USD, account USD
   volume  min 0.01  max 50.00  step 0.01  limit 0.00
   stops level 0 pts (0.00 price), freeze level 0 pts (0.00 price)
   current spread 18 pts (0.18 price)
   filling modes: FOK IOC  | execution mode 2
```

Init **fails** on: trading disabled, close-only, zero point, no usable volume
min/step, or a point value that cannot be converted to money (usually an
unsubscribed symbol). It **warns** on long-only or short-only symbols, and on a
live spread more than 3x the configured limit — the condition that would
otherwise block every trade forever.

### Decimal places

Gold is quoted to **2 decimals** by most brokers and **3** by some. The EA is
digit-independent:

- Prices are rounded with `SYMBOL_TRADE_TICK_SIZE`, not a hardcoded digit count.
- Stop and target distances are derived from ATR in **price**, never in pips.
- `InpMaxSpreadPrice`, `InpMinAtrPrice`, `InpMaxAtrPrice` are all in **quote
  currency (USD)**, so they mean the same thing on a 2- and a 3-digit feed.

> A points-based spread limit is a trap here. The same 30-cent spread reads as 30
> points on a 2-digit feed and 300 on a 3-digit one, so a limit tuned on one
> silently blocks every trade on the other. That is why this setting is in price.

### Lot sizing

Volume is normalised against `VOLUME_MIN`, `VOLUME_MAX`, `VOLUME_STEP` **and**
`VOLUME_LIMIT` (stricter than max on some brokers), with an epsilon before the
floor. Without that epsilon, `0.29 / 0.01` evaluates to `28.999999999999996` in
binary floating point and a bare `MathFloor` silently drops a whole lot step —
it affects roughly half of ordinary gold volumes.

### No silent skips

Every path that declines to trade names its cause in the journal **and** on the
console status line. The most important is the one small accounts hit constantly:

```
[Trade] SIGNAL SKIPPED (BUY XAUUSD at 3287.40): min lot 0.01 would risk 48.20
(0.48% of initial) but only 21.00 (0.21%) is allowed - raise InpRiskPercent,
tighten the stop, or trade a smaller account tier
```

That is a **correct** refusal — taking it would breach your risk rule — but it
must be visible, because on a small account with a wide ATR stop it can silence
the EA for days.

Trade management is equally explicit. A partial that cannot be split, a breakeven
blocked by the broker's stop or freeze level, and a failed trail update are all
logged. **A failed breakeven does not advance the trade's stage**, so it is
retried on the next tick rather than abandoning a position that is supposed to be
risk-free.


---

## Presets

| File | Use |
|---|---|
| `Phase1_Challenge.set` | 10% target, 0.5% risk. The default. |
| `Phase2_Verification.set` | 5% target, 0.4% risk, tighter guards. |
| `Funded_Conservative.set` | 0.3% risk, 2 trades/day, no quota mode. |
| `Optimise_Stage*.set` | Staged optimisation sweeps — see `docs/OPTIMISATION.md`. |
| `Compare_TF_*.set` | Timeframe comparison runs (M5 / M15 / M30). |

Load via the EA's *Inputs* tab → **Load**.

The presets are plain `name=value` text — read them, they double as a summary of
what each phase changes.

---

## FTMO-specific settings checklist

| Input | Phase 1 | Phase 2 | Funded |
|---|---|---|---|
| `InpProfitTargetPct` | 10.0 | 5.0 | 100.0 (never auto-stop) |
| `InpRiskPercent` | 0.50 | 0.40 | 0.30 |
| `InpInitialCapital` | 0 (auto) | 0 (auto) | 0 (auto) |
| `InpSoftDailyLossPct` | 2.0 | 2.0 | 1.5 |
| `InpHardDailyLossPct` | 3.0 | 3.0 | 2.5 |
| `InpMaxTradesPerDay` | 3 | 3 | 2 |
| `InpNewsSource` | BOTH | BOTH | BOTH |

**`InpInitialCapital` must be the challenge's starting capital, not your current
balance**, or the drawdown guards drift as the account grows. Leaving it at `0`
reads the balance at attach time — correct on day one, wrong if you re-attach
later in the phase. Set it explicitly once you are underway.

`InpCetOffsetHours` is *server time minus CE(S)T*. On an FTMO MT5 server this is
normally `0`, because their server clock already runs on CE(S)T. Confirm it, since
it decides when the daily loss counter resets.

---

## Backtesting

Strategy Tester settings that matter:

- **Modelling:** *Every tick based on real ticks*. Anything less will not model
  the partial exits or the trailing stop correctly.
- **Period:** at least 12 months, ideally spanning both a trending and a ranging
  gold regime.
- **Deposit:** the challenge size, in the challenge currency.
- **Leverage:** match FTMO (1:100 on the standard XAUUSD offering).
- **Time:** `TimeGMT()` is simulated in the tester, so set
  `InpUseManualGmtOffset = true` and `InpGmtOffsetHours` to your broker's offset.
  Note this pins one offset for the whole run, so backtests spanning a DST change
  will have session windows an hour off for part of the period.

WebRequest does not work in the tester, so the FF feed is unavailable there. The
EA falls back to the MT5 calendar (which *does* work in the tester) or the cached
JSON file if one exists. **This means backtest results slightly overstate
performance versus live, where the news filter is stricter.**

To backtest with the FF feed's data, run the EA on a live chart once so it writes
`MQL5/Files/XAUUSD_FTMO_ff_calendar.json`, then copy that file into the tester's
agent folder (`Tester/Agent-.../MQL5/Files/`).

---

## Optimisation guidance

**Full protocol: `docs/OPTIMISATION.md`.** Generated staged files live in
`MQL5/Presets/`. In short — optimise these, in this order, and **stop early** — more parameters tuned means
more curve fit:

1. `InpScoreThreshold` (62–80, step 2)
2. `InpDominanceMargin` (20–40, step 2)
3. `InpSlAtrMult` (1.2–2.4, step 0.2)
4. `InpTp2R` (2.0–4.0, step 0.5)
5. `InpAdxMin` (16–28, step 2)

Optimise for **profit factor** or **custom max** — never for net profit, which
will hand you the highest-risk parameter set every time.

Leave the weights (`InpW*`) alone unless you have a specific reason. Eleven
weights is more free parameters than a year of M15 data can honestly support.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `News 0 events` | FF URL not whitelisted **and** broker calendar empty. Use `InpNewsManualCsv`. |
| No trades at all | Check the dashboard `State` line — it always names the blocking condition. |
| "risk budget exhausted or lot below the broker minimum" | Risk % too small for the account size, or a drawdown guard is throttling size. |
| Trades at the wrong hours | GMT offset wrong, or the time base does not match the times you entered. Read the `[Time] resolved session windows` block in the journal. |
| `Clock` row is red | Offset detection failed. Set `InpUseManualGmtOffset = true`. |
| Session windows shift by an hour in March/October | Expected — that is the EU/US DST gap being handled correctly. |
| `order REJECTED: Invalid stops` | Broker stop level exceeds the ATR stop. Raise `InpMinStopAtr`. |
| `SIGNAL SKIPPED ... min lot would risk` | One minimum lot exceeds your risk rule. Raise `InpRiskPercent`, tighten the stop, or use a larger account. |
| Init fails with `[Broker] FATAL` | The symbol cannot support the EA — read the printed spec. Usually an unsubscribed symbol or a close-only contract. |
| `breakeven deferred` repeatedly | Price is sitting inside the broker's stop/freeze distance. It retries; if it persists the broker's stop level is unusually wide. |
| Partial close never fires | Position too small to split. Either raise risk or set `InpUsePartial = false`. |
| Console buttons do nothing | `OnChartEvent` does not fire in the Strategy Tester. Live and demo charts only. |
| Metrics show 0 after restart | `InpRebuildStatsOnInit` off, or the trades are older than `InpStatsHistoryDays`. |
| R metrics blank | Expected right after a restart — R needs the entry risk, which only live-tracked trades carry. |
