# Optimisation Procedure

Follow the phases in order. **Phase 1 is a gate** — if it fails, nothing after it
is meaningful, and optimising anyway will produce a confident-looking result
fitted to a handful of trades.

Every `.set` file referenced here lives in `MQL5/Presets/` and is generated:

```
python3 tools/make_optimisation_sets.py      # rebuild all of them
python3 tools/audit_static.py                # validates every range
```

Never hand-edit a `.set` file — edit the `STAGES` table in the generator and
rebuild, or the audit will fail and your change will be lost.

---

## Phase 0 — Install and compile

Copy **one file** into `<Terminal Data Folder>/MQL5/Experts/`:

```
MQL5/Experts/XAUUSD_FTMO_Confluence_EA.mq5
```

Open it in MetaEditor, press **F7**. It has no `#include` of any kind, so there
is nothing else to copy.

**Confirm you are on the new build** — the journal must show this at startup:

```
[Broker] XAUUSD contract specification:
[Time]   broker server clock is GMT+N
[Time]   resolved session windows:
```

If those lines are absent you are running an older binary and everything below
will measure the wrong thing.

### Strategy Tester settings that matter

| Setting | Value | Why |
|---|---|---|
| Modelling | **Every tick based on real ticks** | anything less will not model partial exits or the trail |
| Period | **12 months minimum** | see the degrees-of-freedom table below |
| Deposit | your challenge size | drawdown guards are percentages of it |
| Leverage | match FTMO (1:100 typical) | affects the margin check |
| Optimisation | *Disabled* for single runs | |
| `InpUseManualGmtOffset` | **true**, with your broker's offset | `TimeGMT()` is simulated in the tester |

---

## Phase 1 — Baseline, and the uptime gate

Run `Phase1_Challenge.set` as a **single test** over your full period.

Then analyse it:

```
python3 tools/analyse_tester_report.py <testergraph.report.csv>
```

Record: **trade count, trading days, win rate, payoff ratio, profit factor.**

### The gate

| Check | Threshold | If it fails |
|---|---|---|
| Trades in sample | **≥ 150** | go to Phase 2 |
| Trading days | **≥ 40% of session days** | go to Phase 2 |

A previous run traded on **13 days out of 379** and produced 16 trades. No
optimisation of that data would have meant anything. **If you are below the
threshold, stop and diagnose — do not proceed to Phase 3.**

The console's `WHY NOT TRADING` panel and the daily `[Why]` journal line name the
dominant blocker directly:

```
[Why] today: 32 evaluated bars, 0 trades taken.
        gate: ATR above ceiling     28  (88%)
```

---

## Phase 2 — Diagnose low uptime

Only if Phase 1 failed the gate. Run each over the **same period** and compare
trade counts. Each file opens one more gate than the last.

| File | Opens | If the count jumps here |
|---|---|---|
| `Diagnose_1_NoVolFilter.set` | volatility band off | the ATR gate was the cause — fix it in Phase 5 Stage 3 |
| `Diagnose_2_NoVolNoNews.set` | + news filter off | the calendar was blocking; check the feed and the GMT offset |
| `Diagnose_3_AllGatesOpen.set` | every gate to its limit | this is the **ceiling** on achievable trades |

If even `Diagnose_3` barely trades, the cause is **not a filter**. Look at
history data quality, the resolved session windows in the journal, or a risk
guard holding trading down.

> These are diagnostics, not trading configurations. `Diagnose_2` and `_3`
> disable the news filter, which is not FTMO compliant.

---

## Phase 3 — Choose the exit structure

Three structures, one run each, same period:

| File | Structure |
|---|---|
| `Compare_Exit_A_Scaled.set` | 40% off at 1R, runner to 2.2R, trail from 1.05R |
| `Compare_Exit_B_Runner.set` | no scale-out; whole position runs behind a trail |
| `Compare_Exit_C_Tight.set` | 50% at 0.8R, runner to 1.8R, tighter stop |

**Judge on the payoff ratio (avg win ÷ avg loss), not net profit.** That is the
number that was broken: an earlier build delivered **0.50** where it needs to
exceed **1.0** simply to survive, and around **1.6** to be worth trading.

The payoff you need depends on your win rate:

| Win rate | Payoff needed for PF 1.35 |
|---|---|
| 40% | 2.02 |
| 45% | 1.65 |
| 50% | 1.35 |
| 55% | 1.10 |

Freeze the winner into the later stages.

---

## Phase 4 — Choose the timeframe

| File | Execution / intermediate / macro |
|---|---|
| `Compare_TF_M5.set` | M5 / M30 / H4 |
| `Compare_TF_M15.set` | M15 / H1 / H4 |
| `Compare_TF_M30.set` | M30 / H4 / D1 |

One run each. Pick on **profit factor and max drawdown together** — never profit
alone.

> Timeframes are compared, never swept. `ENUM_TIMEFRAMES` values are not
> contiguous (`PERIOD_M30` is 30, `PERIOD_H1` is 16385), so a stepped sweep would
> iterate thousands of invalid values and waste the run. The ATR band is relative,
> so it needs no rescaling between timeframes.

---

## Phase 5 — Staged optimisation

Run in order. **Freeze each stage's winner into the next file before running it.**

| Order | File | Sweeps | Passes |
|---|---|---|---|
| 1 | `Optimise_Stage1_Signal.set` | score threshold, dominance margin, ADX floor | 1,056 |
| 2 | `Optimise_Stage2_Exits.set` | SL ATR mult, TP2 R, trail start R, trail ATR mult | 3,969 |
| 3 | `Optimise_Stage3_Volatility.set` | ATR min/max relative, max extension | 616 |
| 4 | `Optimise_Stage4_EntryQuality.set` | volume factor, swing lookback, partial %, TP1 R | 1,225 |
| 5 | `Optimise_Stage5_Cadence.set` | entry spacing, trades per day | 40 |
| | | **total** | **6,906** |

In the tester: tick **Optimisation → Slow complete algorithm** (or *Fast genetic*
for Stage 2), and set the criterion to **Custom max** or **Profit factor**.

### Never optimise for net profit

It selects the highest-risk parameter set every time.

### Never optimise risk

`InpRiskPercent`, both drawdown ladders, the FTMO limits, the news window and all
twelve confluence weights are **locked in every generated file**, and
`audit_static.py` fails the build if any of them ever carries a sweep flag. Risk
is a decision about what you can afford to lose, not a variable to fit. An
optimiser handed a risk parameter returns the largest value the sample happened
to survive.

### Respect degrees of freedom

Roughly **40 closed trades per optimised parameter**:

| Stage | Params | Trades needed |
|---|---|---|
| 1 Signal | 3 | 120 |
| 2 Exits | 4 | 160 |
| 3 Volatility | 3 | 120 |
| 4 Entry quality | 4 | 160 |
| 5 Cadence | 2 | 80 |

### Prefer a plateau to a peak

If the best value is 24 and both 22 and 26 are poor, that is noise. Take the
middle of a broad region of decent results. The tester's 2-D surface view is the
right tool — a good parameter looks like a hill, not a spike.

---

## Phase 6 — Walk-forward

Non-negotiable. A parameter set that has not seen out-of-sample data is a
hypothesis, not a strategy.

1. Re-run Stages 1–2 on **months 1–8 only**.
2. Test the winner, **unchanged**, on months 9–12.
3. Out-of-sample profit factor must be **≥ 70% of in-sample**.

If it collapses, the parameters are overfit. **Widen the thresholds rather than
tuning harder** — a wider setting that works on both halves beats a narrow one
that works on neither.

---

## Phase 7 — Monte Carlo and demo

1. Shuffle the trade sequence 1,000 times. If the 95th-percentile worst drawdown
   exceeds **8%**, cut `InpRiskPercent` until it does not.
2. **Demo on the real FTMO server for 4+ weeks.** This is the only step that
   tests the live news feed, the real spread, and the server timezone together.
   WebRequest does not work in the tester, so the news filter is *stricter* live
   than in any backtest — your backtest slightly overstates performance.

---

## Acceptance criteria

Accept a parameter set only if **all** hold:

| Metric | Threshold |
|---|---|
| Profit factor | ≥ 1.35 |
| Max drawdown | < 5% of initial capital |
| Payoff ratio (avg win ÷ avg loss) | ≥ 1.3 |
| Trades in sample | ≥ 40 × optimised parameters |
| Out-of-sample PF | ≥ 70% of in-sample |
| Neighbouring parameter values | also profitable |
| Trading days | ≥ 4 per FTMO phase |

The last three are the ones people skip, and they are the ones that decide
whether the result survives a live account.

---

## Realistic expectations

At 0.5% risk with ~1.3R average return and 1–2 trades a day, a 10% target takes
roughly **6–10 weeks**. Anything promising it in a week is describing a gamble.

And the honest limit of all of this: optimisation can only find the best settings
*for the data you have*. It cannot tell you whether the entry logic has an edge
that persists. Only Phase 6 and Phase 7 speak to that.
