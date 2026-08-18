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

## Presets

| File | Use |
|---|---|
| `Phase1_Challenge.set` | 10% target, 0.5% risk. The default. |
| `Phase2_Verification.set` | 5% target, 0.4% risk, tighter guards. |
| `Funded_Conservative.set` | 0.3% risk, 2 trades/day, no quota mode. |

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

Optimise these, in this order, and **stop early** — more parameters tuned means
more curve fit:

1. `InpScoreThreshold` (55–75, step 2)
2. `InpDominanceMargin` (12–30, step 2)
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
| Partial close never fires | Position too small to split. Either raise risk or set `InpUsePartial = false`. |
