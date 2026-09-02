# SMC AI Agent — installation and operating guide

MetaTrader 5 expert advisor for **XAUUSD**, built around Smart Money Concepts and an
FTMO 2-step risk envelope. It reads live candles rather than fixed technical
parameters, scores its own confluence, learns from every resolved setup, and shows
all of it on the chart and in the console.

## 1. Install

Copy the two folders into your MetaTrader 5 data folder
(*File → Open Data Folder* in the terminal):

```
<MT5 data folder>/MQL5/Experts/SMCAgent/SMC_AI_Agent.mq5
<MT5 data folder>/MQL5/Include/SMCAgent/*.mqh
```

Then in MetaEditor open `SMC_AI_Agent.mq5` and press **F7** (Compile). It has no
external dependencies beyond the standard `Trade/Trade.mqh` library.

Attach it to an **XAUUSD** chart. The recommended entry timeframe is **M15**
(the agent then reads H1 and H4 automatically); M5 and H1 also work — the higher
timeframes are chosen for you.

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

| Row | Meaning |
|---|---|
| `MODE` | `WARM-UP` (model still observing), `LIVE` (model trained), `LOCKED` (day closed by the risk envelope) |
| `STRUCTURE` | swing bias on the higher, intermediate and entry timeframes |
| `DEALING` | the current dealing range, where price sits in it, and the last liquidity raid |
| `PLAYBOOK` | which of the three setups is on the table right now |
| factor table | all 17 confluence factors: score bar, signed score, **learned** weight, and a plain reading. `Inducement` reads `armed` once the pullback guarding the zone has been run, `still resting` while the trap is unsprung |
| `WEIGHTED SCORE` | the sum of contributions and the resulting probability |
| `FTMO Pn` | day P/L %, the hard daily floor price, total P/L %, target progress, trading days |
| `BUDGET` | money left before the soft stop and the hard floor, risk currently open, trades this week |
| `NEWS` | next high-impact release relevant to gold |
| `SIGNAL` | the live plan, or the reason there is none |
| `ACTION` | what the agent last did |

## 4. Inputs

Nothing here is a technical trading parameter — these are account, compliance,
policy and display settings.

### FTMO 2-step compliance
| Input | Default | Notes |
|---|---|---|
| `InpInitialCapital` | 0 | 0 = use the current balance as the phase capital |
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

### Trade management, news, visuals
See the input groups in the EA — partial/break-even/trail R multiples, the news
window and importance filter, the CSV fallback name, panel position and log level
(`3` = full decision log, `4` = adds observation-book detail).

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
| `smc_agent_model.csv` | learned weights, bias, update count and replay memory. If the feature count ever changes (as it did when inducement was added), the loader detects the mismatch, warns, and restarts from the research priors |
| `smc_agent_state.csv` | phase capital, trading days, streaks, equity peak |
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
