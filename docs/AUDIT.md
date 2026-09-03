# Code audit — live data path, staleness and placeholders

Scope: confirm the agent reads live price action, behaves as specified, and
contains no placeholders or stale data. Performed on the full source tree
(12 files, ~4,970 lines) with static analysis plus a line-by-line read of the
data path, the risk envelope and the learning loop.

**What this audit could not do:** the environment has no MetaEditor, so the code
was **not compiled here**, and no live or backtest run was performed. Findings
below are from source analysis and from numerical simulation of ported logic.

**Compile status:** `SMC_AI_Agent_SingleFile.mq5` compiled clean in MetaEditor —
no errors — reported by the user on 2026-09-03. That closes the "may still
surface diagnostics" caveat for the single-file build. It does **not** close
the others: no backtest and no live run has been performed on any build, and a
clean compile says nothing about whether the strategy has an edge.

---

## 1. Does it read live price action? — confirmed

| Check | Result |
|---|---|
| Indicator handles / `CopyBuffer` / `iMA` / `iRSI` / `iATR` … | **none anywhere** — the agent is pure price action |
| Market data sources | `CopyRates` (entry/mid/high TF, D1, W1, M15) and `SymbolInfoDouble` bid/ask/tick data only |
| Hardcoded prices or levels | none |
| Re-read frequency | `CMarketState::Refresh()` re-pulls all three timeframes on **every bar close**; all three SMC engines re-run `Analyze()` from scratch on that fresh copy |
| Cached collections | swings, structure events, zones and liquidity are `ArrayFree`d and rebuilt every `Analyze()` — nothing survives a bar |
| Live prices for execution | entry, spread and position P/L read from `SymbolInfoDouble` / `PositionGetDouble` at the moment of use |

**Repainting:** verified that no structural decision reads bar index 0 (the
forming bar). Structure mapping, order blocks, FVGs, sweeps, mitigation and
confirmation candles all operate on index ≥ 1. Index 0 is used only to set the
right-hand extent of drawn objects.

## 2. Defects found and fixed

Nine issues, all real, all fixed.

### 2.1 Forming bar contaminated the self-calibration — *fixed*
`SmcEngine::Calibrate` and `MarketState::BuildStats` began their statistics
windows at index 0, the **incomplete** bar. On a bar close that bar has a
near-zero range, body and volume.

Impact was concentrated in the 20-bar volatility window that feeds the
volatility-regime factor and the panel: one zero-range sample in 20 shifts the
median materially and always in the same direction (understating volatility).
The 400-bar percentiles, the body distribution behind the displacement factor and
the tick-volume median behind the participation factor were biased the same way.
The imbalance-threshold scan also reached into bar 0.

All statistics windows now start at index 1.

### 2.2 Stale probability could reach the panel — *fixed*
`CConfluence::Evaluate` reset `valid`, `dir`, `rationale` and `model` but left
`prob`, `raw_score`, `rr1`, `rr2`, entry/stop/target and the inducement fields
untouched. On a bar with no directional hypothesis the panel therefore printed
the **previous** signal's probability and R multiples next to the current
reading. Every field is now cleared at the top of the evaluation.

### 2.3 The learner could be taught a false loss — *fixed (most serious)*
`HarvestClosedTrades` ignored the return value of `ClosedResult`. When a position
disappears, `OnTrade` frequently fires **before** the closing deal reaches the
terminal's history; `HistorySelectByPosition` then returns nothing, `profit`
stayed `0.0`, and the code labelled the trade `y = 0` — a **loss** — and fed it
to the model. A winning trade could train the model as a loser, and the risk
manager's streak logic was fed a zero result.

`ClosedResult` now requires an actual closing deal (`DEAL_ENTRY_OUT` /
`OUT_BY` / `INOUT`) before returning true. The caller retries on the next tick,
logs once, and after 600 unsuccessful attempts drops the entry **without
training the model** rather than labelling it blind.

### 2.4 Wrong key for the history lookup — *fixed*
The position **ticket** was passed to `HistorySelectByPosition`, which is indexed
by `POSITION_IDENTIFIER`. These coincide in hedging mode but not necessarily in
netting mode. The identifier is now captured at open and used for history.

### 2.5 Risk sized off the profit tick value — *fixed*
Position sizing used `SYMBOL_TRADE_TICK_VALUE`. MT5 publishes separate profit and
loss tick values, and on some gold accounts they differ — sizing a stop off the
profit value understates the loss. Sizing, the worst-case check and the open-risk
calculation now use `SYMBOL_TRADE_TICK_VALUE_LOSS` with a fallback.

### 2.6 A failed data read silently consumed the bar — *fixed*
`g_last_bar` was advanced before processing, so a bar where `CopyRates` was not
ready was skipped entirely with only a warning. `OnBarClose` now returns a status
and the bar is retried on the next tick.

### 2.7 Signal overlay outlived the trade — *fixed*
Entry/stop/target lines were drawn on execution and only removed by the next
execution, so a finished trade's plan stayed on the chart indefinitely. They are
now cleared once the agent is flat and holds no signal.

### 2.8 File field separator relied on an undocumented default — *fixed*
Model and state files were opened without an explicit delimiter. The separator is
now stated (`SMC_FIELD_SEP`), with the old default still accepted on read so an
existing file is not orphaned.

### 2.9 Phase capital taken from the current balance — *fixed (breach risk)*
`m_initial` defaulted to the **current** balance. FTMO's limits are percentages of
the capital the phase *started* with, so attaching the agent to a 100,000 challenge
that was already 3% down produced an overall floor of 87,300 while the firm closes
the account at 90,000 — the agent would have kept trading 2,700 **below** the real
breach point, and chased a 106,700 target instead of 110,000.

The capital is now read from the account's own opening deposit
(`DEAL_TYPE_BALANCE`), falling back to the balance only when no such record exists
and warning when the account already has closed trades. Two related defects went
with it: the state file's 50% tolerance would restore a stored 100,000 onto a live
140,000 account, and the single global state file let two accounts share capital,
trading days and streaks. A stored value may now only confirm the detected one
(within 1%), and state/model files are keyed by account login and symbol.

### Also removed
Two superseded helpers (`SmcGmtHour`, `SmcGmtHourF`) that predate the daylight
saving rework. They were unused, and using them for session windows would have
silently reintroduced the winter offset bug.

## 2b. Capital-dependent chain — exhaustive verification

The capital → risk → lot-size chain was ported to `tools/verify_sizing.py` and
driven across **64,800 combinations**: 8 account sizes (1,000 → 200,000), 5 broker
specifications (standard gold, micro, 0.001 volume step, 0.10 step/minimum,
3-digit tick), 9 stop distances, 5 confidence levels, 4 loss-streak states, 3
target-progress states and 3 equity states.

Invariants asserted on every sized trade:

| Invariant | Result |
|---|---|
| Realised risk never exceeds the computed budget (rounding is always down) | hold |
| Never exceeds ⅓ of the remaining daily budget or ⅕ of the remaining hard budget | hold |
| Volume is an exact multiple of the broker's step and inside `[min,max]` | hold |
| A trade that passes the worst-case check cannot breach a floor at 1.25× its stop | hold |
| Floors and targets exactly proportional to phase capital | hold |
| Intended risk % identical across all account sizes | hold |
| Lot size monotonic in capital | hold |

**0 failures.** 37,977 combinations sized a position; 26,823 were correctly
refused because the position would have fallen below the broker's minimum.

Structural separation was proven by inspection: `Confluence.mqh`, where stops and
targets are computed, contains **no reference** to account, balance, equity or
capital; `SmcEngine.mqh` and `MarketState.mqh` likewise; and `RiskManager.mqh`
never sets a stop or target price — it only reads an open position's stop for
risk accounting. Stop and target *prices* are therefore identical on a 1,000 and
a 100,000 account; only volume differs.

**Precision limit, not an error.** Rounding down to the broker's volume step means
realised risk sits at or below target. Measured on standard gold at p=0.62:

| Capital | realised risk vs intended (min / mean) |
|---|---|
| 5,000 | 69% / 84% |
| 10,000 | 58% / 81% |
| 25,000 | 69% / 90% |
| 100,000 | 92% / 97% |
| 200,000 | 97% / 99% |

Smaller accounts under-risk in a lumpy way because one lot step is a large
fraction of the budget. This is conservative in every case — never the reverse.

### Two defects found by the hostile-input pass — *fixed*

- **A degenerate stop could size an enormous position.** With a stop of one tick,
  `risk ÷ loss-per-lot` produced 500 lots, clamped to the broker maximum. The
  strategy layer already refuses such a stop, but sizing must not depend on an
  upstream caller getting it right. `Lots()` now refuses any stop below
  `max(SYMBOL_TRADE_STOPS_LEVEL, 2 × spread)`.
- **Clamping to the maximum lot could land below the minimum** on a malformed
  symbol specification (`vmax < vmin`), producing an order the server would
  reject. The minimum is now re-checked after the clamp.

After the fixes, all twelve degenerate cases (zero/negative tick value, tick size,
budget, stop; zero volume step; `vmax < vmin`; one-tick stop; stop equal to the
spread; enormous stop; budget far above the maximum lot) either refuse to size or
size within budget. **0 failures.**

## 3. Checks that passed unchanged

| Check | Result |
|---|---|
| Placeholder / TODO / stub / dummy markers | none |
| Unresolved function calls (static name resolution over 314 definitions) | none |
| Argument-count mismatches on every `Smc*` helper call site | none |
| All 17 confluence factors written on **both** the signal and the no-signal path | 17/17 on both |
| Unguarded divisions on the hot path | none — every ratio uses `SmcSafeDiv` or a `MathMax(x, 1e-10)` denominator, and the three raw divisions sit behind explicit zero checks |
| Brace/paren balance across all 12 files | balanced |
| Timezone rules vs the IANA database, 2026–2027 hourly | 0 mismatches in 17,520 hours |

## 4. Risk envelope, verified numerically

The FTMO logic was ported and driven to its limits on a 100,000 phase-1 account:

```
soft_daily   97,500  (-2.50%)      target      110,000  (+10.00%)
hard_daily   96,500  (-3.50%)      soft_max     93,000  (-7.00%)
FTMO daily   95,000  (-5.00%)      FTMO max     90,000  (-10.00%)
```

Per-trade risk at day start ranges 0.100% (p=0.55, three losses deep) to 0.670%
(p=0.85, no losses) — the conviction and streak scaling behave as specified.

Worst-case day, every trade losing its full planned risk **plus a 25% stop
overshoot**: trading halts after 12 consecutive losses at **−2.40%**. An open
position could then still run to the hard floor at **−3.50%**, leaving
**1.50% of capital in headroom** against the FTMO 5% daily limit. The 5% rule is
unreachable by construction, not by discipline.

Expectancy gate: `p=0.50 → 1.80R`, `p=0.55 → 1.47R`, `p≥0.60 → 1.30R` floor.
Frequency governor: threshold falls from 0.620 (Monday) to 0.555 (Friday midday,
no trades taken) and never below the 0.550 floor.

## 5. Known limitations (unchanged, by design)

- Not compiled and not backtested in this environment.
- The model is linear in its 17 factors — interpretable and stable on small
  samples, but it cannot discover an interaction no factor expresses.
- Broker GMT offset auto-detection rounds to whole hours.
- `TimeGMT()` depends on the terminal machine's clock; a jump larger than one
  hour is now flagged as an error, and `InpGmtOffsetHours` pins it outright.
- Five general math helpers (`SmcMedian`, `SmcRank`, `SmcStdev`, `SmcSquash`,
  `SmcDayOfWeek`) are defined but currently unused — utility surface, not defects.
