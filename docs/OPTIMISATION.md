# Optimisation Protocol

> **Read §1 before running anything.** Optimisation is the easiest way to destroy
> a working strategy, and the default instinct — sweep everything, keep the top
> result — reliably produces a system that backtests beautifully and loses money.

Generated files live in `MQL5/Presets/`. Regenerate them after any input change:

```
python3 tools/make_optimisation_sets.py
python3 tools/audit_static.py          # validates every range
```

---

## 1. The rules that matter more than the ranges

**Optimise for profit factor or a custom metric — never net profit.** Net profit
selects the highest-risk parameter set every single time.

**Never optimise risk.** `InpRiskPercent` and every drawdown guard are locked in
all generated files, and `tools/audit_static.py` fails the build if any of them
carries a sweep flag. Risk is a decision about how much you can afford to lose,
not a variable to be fitted. An optimiser handed a risk parameter will always
return the largest value the sample happened to survive.

**Never optimise the 12 confluence weights.** Twelve free parameters is more
degrees of freedom than a year of M15 data can honestly support; you would be
fitting noise. They are locked too.

**Respect degrees of freedom.** Rough rule: **40 closed trades per optimised
parameter**, minimum.

| Stage | Params | Trades needed in sample |
|---|---|---|
| Stage 1 Signal | 3 | 120 |
| Stage 2 Exits | 4 | 160 |
| Stage 3 Volatility | 3 | 120 |
| Stage 4 Entry quality | 4 | 160 |
| Stage 5 Cadence | 2 | 80 |

At 1–2 trades a day, twelve months gives roughly 300–500 trades. That supports
these stages. It does **not** support optimising twenty parameters at once.

**Prefer a plateau to a peak.** If a parameter's best value is 24 and both 22 and
26 are terrible, that is noise. Take the middle of a broad region of decent
results, not the single tallest bar. The Strategy Tester's 2-D surface view is
the right tool for this.

---

## 2. Why the files are staged

Sweeping everything at once is combinatorially impossible and statistically
worthless. The 12 confluence weights alone, at 5 values each, are 244 million
passes — and any "winner" is a curve fit.

Each stage instead optimises a small group that shares a purpose, ordered by how
much the outcome depends on it. **Freeze each stage's winner into the next file
before running it.**

| File | Sweeps | Passes |
|---|---|---|
| `Optimise_Stage1_Signal.set` | score threshold, dominance margin, ADX floor | 1,056 |
| `Optimise_Stage2_Exits.set` | SL ATR mult, TP2 R, trail start R, trail ATR mult | 2,205 |
| `Optimise_Stage3_Volatility.set` | ATR floor, ATR ceiling, max extension | 567 |
| `Optimise_Stage4_EntryQuality.set` | volume factor, swing lookback, partial %, TP1 R | 1,225 |
| `Optimise_Stage5_Cadence.set` | minutes between entries, trades per day | 40 |
| | **total** | **5,093** |

That is a few hours of brute force, or minutes with the genetic algorithm — as
opposed to never.

---

## 3. Timeframes are compared, not swept

`ENUM_TIMEFRAMES` values are **not contiguous**: `PERIOD_M30` is 30 but
`PERIOD_H1` is 16385. A step-based sweep between them would iterate thousands of
invalid values and waste the entire run. This is the single most common mistake
in hand-written MT5 optimisation files.

So timeframes are three discrete single runs:

| File | Execution / intermediate / macro | ATR band |
|---|---|---|
| `Compare_TF_M5.set` | M5 / M30 / H4 | 0.70 – 8.00 |
| `Compare_TF_M15.set` | M15 / H1 / H4 | 1.20 – 14.00 |
| `Compare_TF_M30.set` | M30 / H4 / D1 | 1.70 – 20.00 |

Run each once, compare profit factor and drawdown, then optimise only the winner.

The ATR bands are scaled by √period from the M15 baseline, because ATR grows with
the square root of the bar interval. They are a **starting point** — re-run
Stage 3 on whichever timeframe wins.

---

## 4. Calibrating the ATR band — do this first

`InpMinAtrPrice` and `InpMaxAtrPrice` are absolute prices in USD, so the correct
values depend on where gold is trading. A band tuned at $2,000 gold is wrong at
$4,000.

**This is why Stage 3 sweeps them across a deliberately wide range rather than
trusting a hardcoded default** — the optimiser reads the right band off your own
data. As a sanity check before you start:

1. Open XAUUSD on your execution timeframe.
2. Add ATR(14) and read it across a quiet session and a CPI/NFP day.
3. `InpMinAtrPrice` ≈ the quiet-session reading; `InpMaxAtrPrice` ≈ 3–4× the busy one.
4. Confirm the Stage 3 range brackets both. Widen the file if not.

If the console shows `ATR below floor` on most bars, the floor is too high for
the current regime — the fastest way to make the EA look broken.

> **A design note worth acting on later.** An absolute ATR band needs
> recalibrating whenever gold re-rates. Expressing it as a percentage of price,
> or relative to ATR's own moving average, would make it self-adjusting. That is
> a code change, not a settings change, so it is out of scope here — but it is
> the right fix if you intend to run this across years.

---

## 5. The run order

1. **Baseline.** `Phase1_Challenge.set`, single run, 12 months, *Every tick based
   on real ticks*. Record profit factor, max drawdown, trade count. If the trade
   count is below 120, extend the period before optimising anything.
2. **Timeframe.** Run the three `Compare_TF_*.set` files. Pick the winner on
   profit factor **and** drawdown, not profit.
3. **Stage 1 → 5**, in order, freezing each winner into the next file.
4. **Walk-forward.** Re-run stages 1–2 on months 1–8 only, then test the winner
   untouched on months 9–12. If it collapses out of sample, the parameters are
   overfit — widen the thresholds rather than tuning harder.
5. **Monte Carlo.** Shuffle the trade sequence 1,000 times. If the 95th-percentile
   worst drawdown exceeds 8%, cut `InpRiskPercent` until it does not.
6. **Demo, 4+ weeks**, on the real FTMO server. This is the only step that tests
   the news feed, the spread, and the server timezone together.

Steps 4–6 are not optional. A parameter set that has not survived out-of-sample
data is a hypothesis, not a strategy.

---

## 6. Reading a result

Accept a parameter set only if **all** of these hold:

| Metric | Threshold |
|---|---|
| Profit factor | ≥ 1.35 |
| Max drawdown | < 5% of initial capital |
| Avg win ÷ avg loss | ≥ 1.3 |
| Trades in sample | ≥ 40 × optimised parameters |
| Out-of-sample profit factor | ≥ 70% of in-sample |
| Neighbouring parameter values | also profitable (a plateau, not a spike) |

The last two are the ones people skip, and they are the two that decide whether
the result survives contact with a live account.

---

## 7. Regenerating

The `.set` files are generated from the EA source so names and defaults cannot
drift. To change a range, edit the `STAGES` table in
`tools/make_optimisation_sets.py` and re-run it — do not hand-edit the `.set`
files, or the next regeneration will silently discard your change.

`tools/audit_static.py` validates every generated file: keys must be real inputs,
ranges must be ordered with a positive step, the seed value must sit inside its
own range, no risk/compliance/weight parameter may carry a sweep flag, and no
single file may exceed 60,000 passes.
