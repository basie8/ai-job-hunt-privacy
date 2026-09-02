# SMC AI Agent — installation and operating guide

MetaTrader 5 expert advisor for **XAUUSD**, built around Smart Money Concepts and an
FTMO 2-step risk envelope. It reads live candles rather than fixed technical
parameters, scores its own confluence, learns from every resolved setup, and shows
all of it on the chart and in the console.

## 1. Install

Two ways. Pick one.

### Option A — single file (simplest)

Copy **one** file anywhere under `MQL5/Experts/`:

```
<MT5 data folder>/MQL5/Experts/SMC_AI_Agent_SingleFile.mq5
```

Open it in MetaEditor and press **F7**. Nothing else to place — every module is
inlined. This is the build to use if you just want it running.

### Option B — modular (for editing)

Copy **both** folders into your MetaTrader 5 data folder
(*File → Open Data Folder* in the terminal — do **not** use the MetaEditor folder
or `Program Files`):

```
<MT5 data folder>/MQL5/Experts/SMCAgent/SMC_AI_Agent.mq5
<MT5 data folder>/MQL5/Include/SMCAgent/Defs.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/TimeZones.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/Logger.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/MarketState.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/SmcEngine.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/NewsFilter.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/Learner.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/RiskManager.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/Confluence.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/TradeManager.mqh
<MT5 data folder>/MQL5/Include/SMCAgent/Visuals.mqh
```

`#include <SMCAgent/Defs.mqh>` resolves relative to `MQL5\Include\`, so the
folder must be named exactly **SMCAgent** and sit directly inside **Include**.

> **`file 'Include\SMCAgent\Defs.mqh' not found`** means the eleven `.mqh`
> files are not in `MQL5\Include\SMCAgent\`. Copying only the `.mq5` is the
> usual cause. After copying, right-click the Navigator in MetaEditor →
> **Refresh**, then compile again.

After editing any module, regenerate the single-file build with
`python3 tools/build_single_file.py`.

Either build has no external dependencies beyond the standard `Trade/Trade.mqh`
library that ships with MetaTrader.

### Which chart to attach it to

**One chart only.** The agent is multi-timeframe internally — attaching a second
copy on another period does not add analysis, it just doubles your risk.

**Recommended: XAUUSD M15.** The chart period you choose becomes the *entry*
timeframe, and the two higher ones are derived from it automatically:

| Chart (entry) TF | Intermediate | Higher | Notes |
|---|---|---|---|
| M1 | M15 | H1 | too noisy for gold, spread dominates |
| M5 | M30 | H4 | workable, more setups, tighter stops |
| **M15** | **H1** | **H4** | **recommended** |
| M30 | H4 | D1 | fewer, larger setups |
| H1 | H4 | D1 | swing pace, may miss 2 trades/week |
| H4 | D1 | W1 | too slow for a weekly cadence |

On top of whichever hierarchy is chosen, the agent **always** reads three more
series regardless of the chart period: **D1** for the previous day's high and low,
**W1** for the previous week's, and **M15** for the accumulation ("Asian") range.
So an M15 chart has the agent working across M15, H1, H4, D1 and W1 at once.

Why M15 for gold: the stop distances it produces (roughly 1.5–4.5 median candles)
are wide enough to survive gold's noise, small enough to size on a modest account,
and the bar cadence lines up with the London and New York killzones — which is what
makes the two-trades-a-week target realistic. On H1 the setups are better but
rarer; on M5 the spread becomes a large fraction of the stop.

The startup log states the hierarchy it picked:

```
Timeframes | entry PERIOD_M15, intermediate PERIOD_H1, higher PERIOD_H4. Daily and weekly levels from D1/W1, accumulation range from M15 - all read internally, attach to ONE chart only.
```

**Changing the chart period changes everything downstream** — the calibration, the
swing sensitivity, the stop sizes and the setup population. The learned model is
therefore stored per symbol *and* per timeframe
(`smc_agent_model_<symbol>_<period>.csv`), so switching from M15 to H1 starts a
fresh warm-up rather than carrying over weights learned on a different population.

Enable **AutoTrading**, and in *Tools → Options → Expert Advisors* allow
`Algo Trading`. The agent writes its model and state to the **common files** folder,
so nothing is lost when you move it between charts or terminals.

## 2. First run — what you should see

1. The journal prints the calibration and the FTMO envelope it computed:
   `FTMO envelope: initial 100000.00  daily floor 95000.00  overall floor 90000.00  target 110000.00`
2. The chart fills with order blocks, imbalances, BOS/CHoCH labels, liquidity lines
   and the premium/discount range.
3. The panel appears top-left showing `MODE WARM-UP 0/25`.
4. On each bar close a decision block is printed:

```
------------------------------------------------------------
BAR CLOSE 2026.09.01 13:15  XAUUSD  PERIOD_M15  price 4328.40
READ   | PERIOD_H4 BULLISH | PERIOD_H1 BULLISH | entry swing BEARISH internal BULLISH | volatility 1.34x | raid on ASIA-L 2 bars ago
FACTORS| HTF structure +0.20; Liquidity raid +0.24; Entry structure +0.30; Premium/discount +0.14; ...
PLAN   | BUY A - liquidity raid + CHoCH. sell-side liquidity taken at ASIA-L then structure shifted BULLISH. Trading from the BULLISH OB at 4321.10-4324.60 towards EQH for 2.41R. Model confidence 68%. Top evidence: Entry structure(+0.30) Liquidity raid(+0.24) HTF structure(+0.20).
MODEL  | probability 68.0% vs acceptance 62.0% (warm-up, 7 observations, accuracy 57%)
SIZE   | risking 512.30 (0.51% of the phase capital) with 0.42 lots, stop 12.20 away
EXECUTE| #123456789 BUY 0.42 lots @ 4333.55
```

When it stands aside it says exactly why:

```
DECIDE | stand aside: reward 1.18R below the 1.42R that a 56% setup must earn
DECIDE | stand aside: inside the release window of Non-Farm Payrolls (USD) (+8 min)
DECIDE | stand aside: risk envelope: soft daily stop
```

## 3. Reading the panel

The panel is laid out on a fixed character grid in a monospace font, so columns
line up on every terminal and nothing spills past the background:

```
SMC AI Agent v1.00  XAUUSD PERIOD_M15  2026.09.02 14:15
MODE      LIVE      model trained  acc 61%  accept 62%
CLOCKS    srv 14:15 GMT+2 / LDN 13:15 / NY 08:15 / you 14:15
-- MARKET --------------------------------------------------------------------
BIAS      H4 BULLISH / H1 BULLISH / entry BULLISH / int BULLISH
RANGE     4321.10 - 4356.40   price 38% (discount)
RAID      ASIA-L BULLISH 2 bars ago  quality 0.72
PLAYBOOK  A - liquidity raid + CHoCH
-- CONFLUENCE ----------------------------------------------------------------
FACTOR               -  +     SCORE WEIGHT READING
HTF structure     [    ++++]  +0.90  +0.26 PERIOD_H4 is BULLISH (conviction ..
Entry structure   [    ++++]  +1.00  +0.31 CHoCH in trade direction after th..
Liquidity raid    [    +++ ]  +0.84  +0.28 ASIA-L swept 2 bars ago, rejectio..
Premium/discount  [    +   ]  +0.36  +0.20 entry at 38% of the dealing range
Inducement        [    ++++]  +1.00  +0.20 inducement at 4325.60 has been run
Confirmation      [   -    ]  -0.32  +0.14 close in the 34% of the bar range
SCORE     +1.284 weighted  ->  probability 71.2%  (bias -0.31)
-- RISK ----------------------------------------------------------------------
FTMO P1   day +0.20%  total +1.80%  target 18%  days 3/4
FLOORS    soft 97500.00  hard 96500.00  room 4300 / 5300
CAPITAL   100000.00 (opening deposit)  eq 101800.00  open risk 0
NEWS      USD Non-Farm Payrolls in 142m  [GMT+2]
-- DECISION ------------------------------------------------------------------
SIGNAL    BUY  entry 4333.55  sl 4321.35  tp 4358.90 (2.41R)
READING   BUY A - liquidity raid + CHoCH. sell-side liquidity taken at
          ASIA-L then structure shifted BULLISH. Trading from the OB.
ACTION    BUY 0.42 lots @ 4333.55   open 1
```

| Row | Meaning |
|---|---|
| `MODE` | `WARM-UP` (model still observing), `LIVE` (model trained), `LOCKED` (day closed by the risk envelope), plus rolling accuracy and the live acceptance threshold |
| `CLOCKS` | server, London, New York and your own local time side by side |
| `BIAS` | swing bias on the higher, intermediate and entry timeframes |
| `RANGE` | the dealing range and where price sits inside it |
| `RAID` | the liquidity raid arming the current hypothesis, its age and rejection quality |
| `PLAYBOOK` | which of the three setups is on the table |
| factor table | all 17 factors. The bar is signed — `[  --  ]` reads against the trade, `[  ++  ]` for it. Then the score, the **learned** weight, and a plain reading |
| `SCORE` | weighted sum, resulting probability, and the model's learned bias |
| `FTMO Pn` | day and total P/L %, target progress, trading days |
| `FLOORS` | soft and hard floor prices, and the money left before each |
| `CAPITAL` | phase capital and where it was detected from, live equity, risk currently open |
| `NEWS` | next high-impact release, with the broker offset in use |
| `SIGNAL` | the live plan, or the reason there is none |
| `READING` | the agent's reasoning in plain English, word-wrapped over up to three lines |
| `ACTION` | what the agent last did |

Two inputs control the fit: **`InpPanelFontSize`** (6–14 — raise it on a 4K
screen; the panel resizes itself from the font) and **`InpPanelCompact`**, which
drops the per-factor reading column and narrows the panel from 78 to 54
characters for a crowded chart.

## 4. Inputs

Nothing here is a technical trading parameter — these are account, compliance,
policy and display settings.

### FTMO 2-step compliance
| Input | Default | Notes |
|---|---|---|
| `InpInitialCapital` | 0 | 0 = detect automatically from the account's opening deposit (see §4b). Set it explicitly if the account was funded in stages or the phase is already under way |
| `InpPhase` | 1 | 1 = Challenge (10% target), 2 = Verification (5%) |
| `InpTargetPct` | 0 | 0 = derive from the phase |
| `InpDailyLossPct` | 5.0 | the FTMO limit — informational, never approached |
| `InpMaxLossPct` | 10.0 | the FTMO static limit |
| `InpSoftDailyPct` | 2.5 | stop trading for the day here |
| `InpHardDailyPct` | 3.5 | flatten everything here |
| `InpSoftMaxPct` | 7.0 | protective overall floor |
| `InpBaseRiskPct` | 0.5 | base risk per trade, before conviction and streak scaling |
| `InpDailyResetHour` | 0 | server hour of the FTMO reset (midnight CE(S)T — on a GMT+2/+3 broker this is 0) |
| `InpGmtOffsetHours` | 99 | broker GMT offset; 99 = auto-detect and re-check daily. Pin it for backtests |
| `InpMinTradingDays` | 4 | phase requirement, surfaced on the panel |

### Agent behaviour
| Input | Default | Notes |
|---|---|---|
| `InpMaxPositions` | 1 | gold does not need stacking |
| `InpMinProbability` | 0.62 | acceptance threshold at full selectivity |
| `InpMinProbFloor` | 0.55 | the governor never goes below this |
| `InpTargetTradesWeek` | 2 | the brief's minimum cadence |
| `InpWarmupSamples` | 25 | resolved setups before the model outweighs the priors |
| `InpVirtualLearning` | true | learn from setups that were skipped |
| `InpResetModel` | false | discard the stored model and restart from the priors |

### Notifications

| Input | Default | Notes |
|---|---|---|
| `InpNotifyPush` | false | Push to the MetaTrader mobile app. Needs your MetaQuotes ID in *Tools → Options → Notifications* |
| `InpNotifyEmail` | false | Email. Needs SMTP in *Tools → Options → Email* |
| `InpNotifyPopup` | false | Terminal popup alert |
| `InpNotifyEntries` | true | on buy / sell entries |
| `InpNotifyExits` | true | when a trade closes |
| `InpNotifyRisk` | true | when the risk envelope locks the day or flattens |

All three channels are **off by default** — switch on the one you want. What you
get:

```
XAUUSD PERIOD_M15 BUY 0.42 lots @ 4333.55 | SL 4321.35  TP 4358.90 (2.41R)  p 71%  A - liquidity raid + CHoCH
XAUUSD PERIOD_M15 closed +1234.56 | day +1.23%  total +3.45%  equity 101234.56
XAUUSD PERIOD_M15 RISK LOCK | soft daily stop  day -2.51%  no further trades today
```

**Dry run notifies too**, always tagged, so a simulated fill can never be
mistaken for a real one:

```
[DRY RUN] XAUUSD PERIOD_M15 BUY 0.42 lots @ 4333.55 | SL 4321.35  TP 4358.90 (2.41R)  p 71%  A - liquidity raid + CHoCH  - simulated, nothing sent
```

Push and email leave through the **terminal's** own channels, not through the
expert, so neither needs a whitelisted URL and the agent still makes no HTTP
calls of its own. Notifications are suppressed in the strategy tester and
optimiser, which serve none of them. If a channel is misconfigured the agent says
so in the journal with the error code rather than failing quietly.

### Dry run

| Input | Default | Notes |
|---|---|---|
| `InpDryRun` | false | Run the entire pipeline and **log** every trade it would take instead of sending it. Works on an unfunded or disconnected terminal |
| `InpDryRunCapital` | 100000 | Phase capital to assume while dry running |

A dry run is not a paper-trade toy: the agent sizes each trade exactly as it
would live, marks it to market against real candles, moves a simulated equity
curve, applies the FTMO floors to that curve, counts trading days, and trains the
model on the outcome at full weight. The only difference is that nothing reaches
the broker.

```
DRY RUN| WOULD OPEN BUY 0.42 lots @ 4333.55  sl 4321.35  tp 4358.90  risk 512.40  (nothing sent)
DRY RUN| simulated result +1234.56, equity now 101234.56
```

Use it to exercise the agent on an account with no equity, to watch the decision
logic on a fresh install before funding, or to sanity check sizing against your
broker's contract specs. The panel shows `MODE  DRY RUN` throughout so a dry run
can never be mistaken for live trading.

**Note on forcing live orders instead:** there is deliberately no switch to send
real orders on a zero-equity account. The server rejects them for want of margin,
so it would produce a log full of `TRADE_RETCODE_NO_MONEY` and teach you nothing
a dry run does not.

### Trade management, news, visuals
See the input groups in the EA — partial/break-even/trail R multiples, the news
window and importance filter, the CSV fallback name, panel position and log level
(`3` = full decision log, `4` = adds observation-book detail).

## 4b. How the account size is determined

Every FTMO limit is a percentage of the capital the phase **started** with, not of
the balance right now — so getting this number right is the difference between the
agent's floors matching the firm's and sitting below them.

With `InpInitialCapital = 0` (default) the agent resolves it in this order:

1. **The account's opening deposit.** It scans the account's own deal history for
   the earliest balance operation (`DEAL_TYPE_BALANCE`, a credit) and uses that
   amount. This is the authoritative starting capital and is what the prop firm's
   own limits key off.
2. **The current balance**, only if no balance operation exists in history. If the
   account already has closed trades, this is flagged as a **warning**, because on
   an account that is already under way it makes every floor wrong.

Setting `InpInitialCapital` explicitly always wins and is the right move if your
account was funded in stages, or you are attaching the agent mid-phase to a
terminal whose history has been trimmed.

**Why the fallback is dangerous.** Attach the agent to a 100,000 challenge that is
already 3% down and the naive answer, "capital = balance = 97,000", produces:

```
agent overall floor  = 97,000 - 10%  = 87,300
FTMO closes the account at              90,000
-> the agent would keep trading 2,700 BELOW the real breach point
   and would chase a 106,700 target instead of 110,000
```

Reading the opening deposit instead gives 100,000, a floor of exactly 90,000, and
the correct 110,000 target.

**Guards around it**

- Start-up logs the number and where it came from:
  `Phase capital 100000.00 (detected from the opening deposit of 2026.08.15). Balance now 97000.00, equity 97000.00.`
- The panel carries a `CAPITAL` row with the same information, live.
- If equity is already below the phase's overall floor at start-up, that is logged
  as an **error** — the account looks breached and the capital figure should be
  checked before trading.
- The stored state file may only **confirm** the detected capital (within 1%). A
  materially different stored value is ignored with a warning instead of silently
  redefining the floors.
- State files are now named per account and symbol
  (`smc_agent_state_<login>_<symbol>.csv`) and the model per symbol
  (`smc_agent_model_<symbol>.csv`), so two challenges running side by side cannot
  inherit each other's capital, trading days or streaks.

## 4c. What scales with account size — and what cannot

**Scales exactly, automatically, from the detected phase capital:**

| Quantity | How |
|---|---|
| Daily / overall floors, protective floors | percentages of phase capital |
| Phase profit target | percentage of phase capital |
| Per-trade risk budget | `capital × InpBaseRiskPct%`, then conviction, loss-streak and target-progress scaling |
| Remaining-budget caps | ⅓ of what is left to the soft stop, ⅕ to the hard floor |
| **Lot size** | `risk money ÷ (stop distance × value per lot)` — recomputed for every trade |
| Worst-case pre-trade check | scales with the lot size |

A 1,000, a 10,000 and a 100,000 account produce the same decisions and the same
stop and target *prices*; only the volume differs.

**Does not scale — by design:**

Stop and target distances. The stop sits where the idea is invalidated (order
block boundary, sweep extreme, untaken inducement, plus a volatility buffer) and
the target sits at the next unswept liquidity pool. Those are properties of the
chart, not of your balance. Making the stop tighter because the account is small
would not reduce risk, it would just lose more often.

**The hard floor: minimum lot size**

Because the stop distance is fixed by the market, the broker's minimum lot puts a
floor under the smallest risk that can be expressed. On XAUUSD (100 oz contract,
0.01 minimum lot, $1 per $1 move per 0.01 lot) one minimum lot on a $15 stop risks
$15 — and that is the same $15 on every account:

| Phase capital | $15 stop at 0.01 lot | Lots wanted at 0.5% risk | Result |
|---|---|---|---|
| 1,000 | **1.50%** of capital | 0.0033 | **every setup skipped** |
| 5,000 | 0.30% | 0.0167 | works, coarse |
| 10,000 | 0.15% | 0.0333 | works |
| 25,000 | 0.06% | 0.0833 | comfortable |
| 100,000 | 0.015% | 0.3333 | comfortable |

At 0.5% risk with typical gold stops the practical minimum is roughly **3,000–5,000
of capital to place a trade at all, and 6,000–10,000 for usable granularity**. A
1,000 account can only trade this strategy at ~1.5% risk per trade, which is a
different risk profile than the one this agent was designed around — that is your
decision to make, not one the agent will make for you.

**The agent tells you at start-up** rather than silently skipping trades forever.
It measures your broker's real contract specs and the current volatility and prints
a verdict:

```
Sizing | phase capital 10000.00, risk budget 50.00 (0.50%). Typical stop 15.20, deepest accepted 36.98.
Sizing | one minimum lot (0.01) risks 15.20 on that stop = 0.15% of phase capital. Agent wants 0.0329 lots.
Sizing | comfortable: 3.3 lot steps fit inside the risk budget.
```

and on an account that cannot support it:

```
Sizing | NOT TRADEABLE at this risk: the smallest position the broker allows risks 1.52% but the budget is 0.50%. Every setup will be skipped.
Sizing | Fix it one of two ways: raise InpBaseRiskPct to at least 1.52%, or run this strategy on at least 3040 of capital (about 6080 for usable granularity).
Sizing | The agent will NOT raise your risk on its own - that decision is yours.
```

If it still happens at run time, three consecutive skips trigger the same message
with the live numbers, so a silently idle agent is impossible.

## 5. Time, news sources and broker-clock alignment

**Where the news comes from.** One primary source and one fallback:

| Source | When it is used | Function |
|---|---|---|
| **MetaTrader 5 built-in economic calendar** (the MQL5 calendar service your broker's terminal subscribes to) | always, when the terminal serves it | `CalendarValueHistory` for the window −3 to +10 days, each value resolved to its event with `CalendarEventById` so importance can be filtered |
| **`smc_news.csv`** in the common files folder | only when the calendar returns nothing (strategy tester, or a broker that does not serve it) | `CNewsFilter::LoadFromCsv` |

There is no third-party feed, no web request and no API key — the EA cannot make
outbound HTTP calls and does not try to. The panel tells you which source is live:
a `[csv]` prefix means the fallback is in use, `calendar unavailable` means neither
worked and only the time-of-day protection is left.

**Which events.** Filtered by currency, not "all news": USD first (gold is a
USD-denominated macro asset), plus EUR and GBP because they move the dollar index.
Importance is filtered by `InpNewsImportance` (default 3 = high impact only).

**Time base — this is the part that has to be right.** The MT5 calendar publishes
event times in **GMT**; every timestamp inside the agent is **server time**. The
conversion is a single offset, applied once when events are cached:

```
server_event_time = calendar_time_GMT + (server_time − GMT)
```

- The offset is **auto-detected** from `TimeTradeServer() − TimeGMT()` and rounded
  to the nearest hour. `TimeTradeServer()` is used deliberately rather than
  `TimeCurrent()`: the latter is the timestamp of the last tick and goes stale over
  weekends and quiet books, which would shift every event.
- It is **re-detected every timer tick and applied only when it changes**, so a
  broker daylight-saving switch is self-correcting: the change is logged and the
  whole calendar cache is rebuilt with the new offset.
- The same offset drives the killzones and the session factor, so news and sessions
  can never disagree with each other.
- `InpGmtOffsetHours` (default 99 = auto) pins it manually. Use it for backtests,
  where `TimeGMT()` is not reliable, or if your terminal's own timezone is wrong.
- On startup the journal prints the alignment so you can verify it in one line:
  `Clock: server 2026.09.02 14:15 = GMT+2. Calendar events are published in GMT and
  shifted by +2 h to server time.` The panel's news row also carries `[GMT+2]`.

**CSV fallback format** — `YYYY.MM.DD HH:MM;CUR;IMPORTANCE;NAME`, one event per
line, `#` for comments. **Times must be in GMT**, exactly like the MT5 calendar;
the same offset is applied to them, so both paths behave identically:

```
# 2026.09.05 12:30;USD;3;Non-Farm Payrolls
2026.09.05 12:30;USD;3;Non-Farm Payrolls
2026.09.10 18:00;USD;3;FOMC Rate Decision
```

**Known limits of the alignment**

- `TimeGMT()` reads the *terminal machine's* timezone settings. A VPS with a wrong
  clock or timezone produces a wrong offset — check the startup line, and pin
  `InpGmtOffsetHours` if it looks wrong.
- The offset is rounded to whole hours. Brokers on a half-hour offset are not
  supported by the auto-detection; set it manually (and note the input only takes
  whole hours, so such a broker will be 30 minutes out on killzones).
- In the strategy tester the calendar is not served at all and `TimeGMT()` is
  unreliable — supply the CSV and pin the offset.

## 5b. Killzones and daylight saving

Killzones belong to an exchange, not to GMT. The London open is 08:00 London local
all year and the New York cash open is 09:30 New York local all year — in GMT those
move an hour twice a year, and the two regions do not switch on the same date. So
the windows are defined in **exchange-local time** and each follows its own rule:

| Window | Defined as | DST rule applied |
|---|---|---|
| London killzone | 07:00–10:00 **Europe/London** | last Sunday in March 01:00 UTC → last Sunday in October 01:00 UTC (EU Directive 2000/84/EC) |
| New York killzone | 08:00–11:00 **America/New_York** | second Sunday in March 02:00 EST → first Sunday in November 02:00 EDT (Energy Policy Act 2005) |
| Accumulation ("Asian") range | 00:00–07:00 **Europe/London** | as London |
| Friday liquidity drain | from 15:00 **America/New_York** | as New York |

`TimeZones.mqh` computes these rules arithmetically — no network call, no lookup
table to age out. They were validated hour by hour against the IANA time zone
database for 2026–2027: **0 mismatches in 17,520 hours**, and the computed
transitions reproduce the published dates (US 2026-03-08 → 2026-11-01,
EU 2026-03-29 → 2026-10-25, and the 2025 and 2027 equivalents).

`SmcTimezoneSelfTest()` re-asserts those transitions, the three-week spring window
where the US has switched and Europe has not, and a local→UTC→local round trip
**every time the EA starts**. If any assertion fails the EA refuses to initialise
rather than trade on session windows it cannot justify. The startup log states the
mapping in plain language:

```
Timezone self test: all timezone assertions passed (US and EU transitions 2026-2027, cross-region mismatch window, round trip)
Clock: server 2026.09.02 14:15 = GMT+2. Calendar events are published in GMT and shifted by +2 h to server time.
Sessions: London killzone 07:00-10:00 London local (BST), New York killzone 08:00-11:00 New York local (EDT). Right now it is 13.25 in London and 8.25 in New York.
```

**Why not a time API.** An HTTP time service would be strictly worse here:
`WebRequest()` cannot be called from the strategy tester at all, it requires the URL
to be whitelisted in *Tools → Options → Expert Advisors* on every terminal, it is
commonly blocked on prop-firm VPS images, and it introduces a timeout and a failure
mode into the decision path on bar close. The DST rules are legislated and
deterministic, so computing them offline is exactly as accurate as querying a server
and cannot fail. The only genuinely external quantity is the broker's own offset,
which comes from the terminal itself (`TimeTradeServer() − TimeGMT()`) and can be
pinned with `InpGmtOffsetHours` if the machine's clock is untrustworthy.

*Maintenance note:* if the EU ever adopts its proposal to abolish seasonal clock
changes, or the US adopts permanent DST, update the two rule functions in
`TimeZones.mqh` and add the new transition to the self test.

### Running the EA from a different country

**The agent's decisions do not depend on where you are, and that is deliberate.**
A killzone is a property of an exchange, not of the trader. The London open is the
London open whether you watch it from Cape Town, Dubai, London or Sydney, so the
windows are anchored to `Europe/London` and `America/New_York` and every instance of
this EA reaches the same conclusion at the same instant anywhere on earth. If the
sessions followed your local clock instead, a user in Sydney would get a "London
killzone" in the middle of the Australian afternoon.

There are four clocks in play, and only one of them touches a decision:

| Clock | Used for | Affects trading? |
|---|---|---|
| **Broker server time** | every internal timestamp, bar times, the FTMO daily reset | yes — the working frame |
| **Exchange local** (London, New York) | killzones, accumulation range, Friday drain | yes — anchored, location-independent |
| **GMT** (`TimeGMT()`, from this machine's clock and timezone) | the single reference used to derive the broker offset | indirectly — see below |
| **Your PC local time** (`TimeLocal()`) | display only | no |

So your location changes nothing except what you read on the panel. Your machine's
**timezone setting**, however, is the reference the terminal uses for GMT, so a VPS
with a wrong clock or timezone yields a wrong broker offset and would shift the news
windows. Three protections:

1. Start-up prints every clock on one line, plus both killzones translated into
   server time *and* your own time, so a misconfiguration is visible immediately:

```
Clock   | server 14:15 (GMT+2) | GMT 12:15 | this PC 14:15 (GMT+2) | London 13:15 (BST) | New York 08:15 (EDT)
Session | London killzone 07:00-10:00 London local = 08:00-11:00 server = 08:00-11:00 on this PC
Session | New York killzone 08:00-11:00 New York local = 14:00-17:00 server = 14:00-17:00 on this PC
```

2. The panel carries a live `CLOCKS` row with server, London, New York and your own
   time side by side.
3. A broker offset that moves by more than one hour is flagged as an error rather
   than accepted — a daylight saving change is exactly one hour, so a larger jump is
   a machine clock fault.

If your terminal's clock cannot be trusted, pin `InpGmtOffsetHours` to your broker's
real offset and nothing else in the agent depends on the PC at all.

*Note for backtests:* in the strategy tester `TimeLocal()` mirrors the modelled
server time, so the "this PC" column is not meaningful there.

## 6. Files it writes (common files folder)

| File | Purpose |
|---|---|
| `smc_agent_model_<symbol>.csv` | learned weights, bias, update count and replay memory. If the feature count ever changes (as it did when inducement was added), the loader detects the mismatch, warns, and restarts from the research priors |
| `smc_agent_state_<login>_<symbol>.csv` | phase capital, trading days, streaks, equity peak — one per account and symbol |
| `smc_agent_log.txt` | decision log, when `InpLogToFile` is on |
| `smc_news.csv` | *optional input*: fallback calendar in **GMT**, `YYYY.MM.DD HH:MM;CUR;IMPORTANCE;NAME` (see §5) |

Delete the first two to start a phase from scratch (or set `InpResetModel`).

## 7. Backtesting notes

- The MT5 **economic calendar is not served inside the strategy tester**. Either
  supply `smc_news.csv` in the common folder (GMT timestamps) or accept that the
  news factor is neutral in tests. Live behaviour will differ around releases.
- `TimeGMT()` is unreliable in the tester, so pin `InpGmtOffsetHours` to your
  broker's real offset for any backtest you intend to trust on session timing.
- Use **every tick based on real ticks** and a broker feed with realistic gold
  spreads. The spread gate and the execution factor are meaningful here.
- The learning loop is stateful: a backtest continues from whatever model file
  exists. Set `InpResetModel = true` for a clean run.
- `OnTester` returns an FTMO-shaped criterion (profit discounted by relative equity
  drawdown, zero below 10 trades, negative if drawdown reached 10%).

## 8. Operating notes and honest limitations

- **Two trades a week is a target, not a promise.** The frequency governor relaxes
  selectivity as the week progresses but stops at `InpMinProbFloor`. In a dead,
  compressed tape the agent will trade less rather than force setups.
- **The daily reset hour matters.** FTMO recalculates at midnight CE(S)T. On a
  GMT+2/GMT+3 broker server that is hour 0; if your broker sits elsewhere, set
  `InpDailyResetHour` to the server hour that corresponds to midnight CET.
- **Killzones are mapped in GMT** and converted with the detected server offset.
  They do not track US daylight-saving transitions to the minute; the NY window is
  approximated as 12:00–15:00 GMT.
- **The model is linear** in its 17 factors — interpretable and stable on small
  samples, but it cannot discover a pattern that none of the factors expresses.
- **Slippage and gaps are real.** The worst-case check assumes a 25% overshoot
  beyond the stop; a weekend gap can still exceed that. Nothing in software can make
  a leveraged gold position gap-proof.
- This is trading software for a simulated prop-firm evaluation. It is not
  investment advice, and it has not been validated against a live FTMO account by
  the author of this repository.
