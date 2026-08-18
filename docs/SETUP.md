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
timing — depends on this being right.**

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
| Trades at the wrong hours | GMT offset wrong. See step 5. |
| `order REJECTED: Invalid stops` | Broker stop level exceeds the ATR stop. Raise `InpMinStopAtr`. |
| Partial close never fires | Position too small to split. Either raise risk or set `InpUsePartial = false`. |
