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

## 5. Files it writes (common files folder)

| File | Purpose |
|---|---|
| `smc_agent_model.csv` | learned weights, bias, update count and replay memory. If the feature count ever changes (as it did when inducement was added), the loader detects the mismatch, warns, and restarts from the research priors |
| `smc_agent_state.csv` | phase capital, trading days, streaks, equity peak |
| `smc_agent_log.txt` | decision log, when `InpLogToFile` is on |
| `smc_news.csv` | *optional input*: fallback calendar, `YYYY.MM.DD HH:MM;CUR;IMPORTANCE;NAME` |

Delete the first two to start a phase from scratch (or set `InpResetModel`).

## 6. Backtesting notes

- The MT5 **economic calendar is not served inside the strategy tester**. Either
  supply `smc_news.csv` in the common folder or accept that the news factor is
  neutral in tests. Live behaviour will differ around releases.
- Use **every tick based on real ticks** and a broker feed with realistic gold
  spreads. The spread gate and the execution factor are meaningful here.
- The learning loop is stateful: a backtest continues from whatever model file
  exists. Set `InpResetModel = true` for a clean run.
- `OnTester` returns an FTMO-shaped criterion (profit discounted by relative equity
  drawdown, zero below 10 trades, negative if drawdown reached 10%).

## 7. Operating notes and honest limitations

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
