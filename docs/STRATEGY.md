# Strategy specification — how the agent decides

> One sentence: **on every bar close the agent re-reads the raw candles, rebuilds the
> Smart Money picture from scratch, proposes a direction, measures 17 confluence
> factors, converts them into a probability, and only trades when that probability
> pays for the reward it can actually reach — inside an FTMO envelope that cannot
> lose 5% in a day.**

---

## 0. Why there are no technical parameters

A conventional EA hard-codes numbers that were fitted to history: `ATR(14) * 1.5`,
`RSI < 30`, `swing lookback = 5`, `equal highs within 20 points`. Those numbers are
the strategy, and they decay.

This agent replaces every one of them with a measurement of the chart in front of
it. The calibration runs on each bar close over the visible window
(`MarketState::BuildStats`, `SmcEngine::Calibrate`):

| Quantity a normal EA would hard-code | What the agent does instead |
|---|---|
| ATR period and multiplier | median true range of the observation window = **1 "unit"**; everything is expressed in units |
| Swing lookback | tries pivot lengths 2…6 and keeps the one whose pivot **density matches the market's own rhythm** (~1 pivot per 8 candles) |
| "Significant" imbalance size | 70th percentile of the imbalances actually present in the window |
| Equal-high tolerance | 0.15 units |
| Stop buffer | 0.35 units + 2× current spread |
| "Big candle" / displacement | measured against the 80th percentile of candle bodies |
| Volume threshold | ratio to the median tick volume of the window |
| Volatility regime | median TR of the last 20 bars ÷ median TR of the window |
| Session windows in fixed GMT | exchange-local windows, US and EU daylight saving computed from the legislated rules and self-tested at start-up |
| Minimum reward:risk | derived from the model's own probability (see §4) |

The only numbers a user sets are **account, compliance and policy** values — risk
per trade, FTMO percentages, how many trades per week to aim for, what to draw.

## 0b. The seven steps, and where each one lives

The agent executes the classic SMC sequence in order. Nothing is skipped and
nothing is implicit:

| Step | Implementation | Notes |
|---|---|---|
| 1. Structure mapping & trend | `SmcEngine::MapStructure`, `Confluence::EngineBias` | swing + internal pivots, BOS/CHoCH, run independently on three timeframes |
| 2. Liquidity zone analysis | `SmcEngine::MapLiquidity` + `Confluence::FeedExternalLiquidity` | EQH/EQL, swing pools, PDH/PDL, PWH/PWL, Asian range |
| 3. Test of the liquidity zone | `SmcEngine::DetectSweep` | wick through the pool, close back inside, scored on rejection wick, pool weight, freshness |
| 4. **Inducement (IDM)** | `SmcEngine::FindInducement`, factor 16 | the first valid pullback inside the leg that broke structure; the zone behind it is not armed until that pullback has been run |
| 5. Imbalance | `SmcEngine::MapFvg`, factors 5 and 4 | significance measured against the live gap distribution |
| 6. Order block | `SmcEngine::BuildOrderBlock`, factor 4 | last opposing candle before the displacement, scored on displacement, imbalance, participation, tightness |
| 7. Trade execution | eight gates → `RiskManager` sizing → `CTradeExec` | then partial, break even, structural trail, time stop |

Steps 1-6 are *measurements*; step 7 is the only one that can put money at risk,
and it is the one wrapped in the FTMO envelope.

## 1. What the agent reads (three timeframes)

The chart timeframe is the **entry** timeframe. Two higher timeframes are picked
automatically (M15 → H1 → H4, H1 → H4 → D1, …). Each one gets its own independent
SMC engine, self-calibrated to its own candles:

- swing structure and internal structure, with every **BOS** and **CHoCH**
- **order blocks** — the last opposing candle before the displacement that broke
  structure, scored on displacement size, imbalance backing, participation and
  tightness
- **fair value gaps** — filtered by the live gap distribution
- **liquidity pools** — equal highs/lows, recent swing extremes, plus PDH/PDL,
  PWH/PWL and the Asian range high/low fed in from higher timeframes
- **sweeps** — a pool taken and rejected within the same candle, scored by wick
  size relative to the candle and by freshness
- **inducement** — for every order block, the first valid pullback inside the leg
  that produced it, plus whether that pullback has since been run
- the **dealing range** with premium / equilibrium / discount

## 2. Playbooks (the directional hypothesis)

Only three shapes are ever proposed. If none of them is present, the agent prints
what it sees and does nothing.

**A — Liquidity raid → change of character → discount/premium zone**
The primary setup. Sell-side liquidity (Asian low, PDL, equal lows) is taken and
rejected, structure then shifts bullish (CHoCH, or BOS/internal shift in the same
direction), and price is back inside a bullish order block or imbalance located in
the discount half of the dealing range. Mirrored for shorts.

**B — Post-release raid**
The same shape, but the raid was engineered by a high-impact macro print in the
last 60 minutes. Gold's most reliable expansions come from the liquidity taken on
the release, not from the release itself; the news factor turns strongly positive
here, while entries *inside* the release window remain blocked.

**C — Trend continuation into origin**
No reversal required: the entry timeframe is in a BOS sequence that agrees with the
higher timeframe, and price has returned to the fresh order block / imbalance that
produced the break. This is the playbook most exposed to the premature-tap failure,
so an untaken inducement is penalised hardest here (−0.90 against −0.45 for the
raid-driven playbooks): the trap in front of the zone has to be sprung first.

## 3. The 17 confluence factors

Each factor is measured for the *proposed direction* and normalised to −1…+1
(positive = supports the trade). The prior column is the research-based starting
weight (see `RESEARCH.md`); the model owns the weight after warm-up.

| # | Factor | Prior | What is measured |
|---|---|---|---|
| 0 | HTF structure | 0.26 | higher-timeframe trend and its conviction, reduced when price sits at the wrong end of the HTF range |
| 1 | Mid structure | 0.18 | same on the intermediate timeframe |
| 2 | Entry structure | 0.30 | CHoCH after the raid (best) > BOS > internal shift > unconfirmed |
| 3 | Liquidity raid | 0.28 | which pool was taken, rejection wick as a fraction of the candle, bars since |
| 4 | Order block | 0.22 | displacement that created it, imbalance backing, participation, tightness, untouched or already tapped |
| 5 | Imbalance | 0.16 | order block stacked inside an unfilled FVG (or vice versa) |
| 6 | Premium/discount | 0.20 | position of the entry inside the dealing range relative to equilibrium |
| 7 | Displacement | 0.18 | largest body in the trade direction over the recent leg vs the 80th-percentile body |
| 8 | Session | 0.12 | killzones evaluated in **exchange-local time** (London 07:00–10:00 Europe/London, New York 08:00–11:00 America/New_York, each with its own DST rule), Asian accumulation and late session negative, Friday close and weekend strongly negative |
| 9 | Volatility regime | 0.10 | compressed tape and violent expansion both penalised |
| 10 | Execution cost | 0.10 | spread as a fraction of the planned stop |
| 11 | Reward:risk | 0.16 | R to the first unswept liquidity objective |
| 12 | Key levels | 0.14 | distance from the zone to PDH/PDL/PWH/PWL/Asian range |
| 13 | Confirmation | 0.14 | where the confirmation candle closed in its range, size of its rejection wick |
| 14 | Participation | 0.08 | tick volume of the confirmation bar vs the median |
| 15 | News context | 0.16 | negative approaching a release, strongly positive on a post-release raid |
| 16 | Inducement | 0.20 | +1.0 when the inducement guarding the zone has been run, −0.45 when it is still resting after a major raid, −0.90 when it is still resting on a continuation entry, +0.15 when the creating leg had no interior pullback at all |

The weighted sum plus the model bias goes through a logistic function to produce
`p`, the probability that the setup reaches its first objective before its stop.

## 4. Gates that must all pass before an order is sent

1. **Expectancy gate** — the mapped objective must be worth at least
   `R_min = max(1.30, (1 − p) / p × 1.8)`. A 55% setup must find 1.5R; a 70% setup
   may take 1.3R. This replaces a fixed take-profit setting.
2. **Acceptance gate** — `p` must clear the live acceptance threshold (§6).
3. **Stop sanity** — the invalidation may not be deeper than 4.5 units of local
   volatility. Inducement that has not been run is resting liquidity, so the stop is
   pushed beyond it rather than in front of it — and if that makes the stop too deep,
   the setup is rejected by this same rule instead of being taken with liquidity
   sitting inside the risk.
4. **Objective exists** — there must be unswept liquidity to aim at.
5. **News gate** — no entries inside the release window (default −15 / +10 minutes
   around high-impact events).
6. **Spread gate** — the spread may not exceed 20% of the planned risk.
7. **Risk envelope** — §5 must allow a new position.
8. **Worst case** — position size × 1.25 × stop distance, plus the risk already
   open, must still leave the account above the hard daily floor *and* the
   protective overall floor.

Anything that fails is logged with the exact reason, and — if virtual learning is
on — is still tracked as a paper trade so the agent learns from what it skipped.

## 5. The FTMO risk envelope

```
initial capital  (phase capital, detected or set)
│
├── profit target        +10% (phase 1) / +5% (phase 2)   → capital-preservation mode
│
├── daily reference      balance at the daily reset, taken as min(balance, equity)
│   ├── soft daily stop  −2.5%  → no new trades for the rest of the day
│   ├── hard daily floor −3.5%  → flatten everything immediately
│   └── FTMO daily limit −5.0%  → never reached by construction
│
└── overall
    ├── protective floor −7%    → flatten and stop
    └── FTMO static limit −10%  → never reached by construction
```

Position sizing (`RiskManager::RiskMoney`) starts from the base risk (default 0.5%
of phase capital) and then:

- scales with conviction (0.45× at the acceptance threshold → 1.35× at p = 0.85);
- halves after losses (×0.75 / ×0.55 / ×0.40 for a 1 / 2 / 3+ loss streak) —
  never the reverse, there is no martingale anywhere in this code base;
- shrinks to 0.65× past 70% of the phase target and 0.45× past 90%;
- is capped at ⅓ of what remains before the soft daily stop and ⅕ of what remains
  before the hard floor.

If the compliant size rounds below the broker's minimum lot, the trade is skipped —
the agent never rounds *up* into a rule breach.

Additionally, every tick: if equity touches the hard daily floor or the protective
overall floor, all positions are closed and the day is locked. If a high-impact
release is approaching and `InpFlattenBeforeNews` is on, exposure is released
*before* the FTMO 2-minute funded-account window opens, so the agent is never in a
position where it is forbidden to act.

## 6. Trade frequency governor (≥2 trades per week)

Selectivity is dynamic instead of fixed:

```
threshold = InpMinProbability                       (default 0.62)
          − min(0.10, 0.035 × trades_behind_pace)   (fall behind → get less picky)
          + 0.02 × loss_streak      (max +0.06)
          + 0.03 if the daily budget is more than half spent
          + 0.04 if the phase is more than 85% complete
threshold = clamp(threshold, InpMinProbFloor, 0.90) (default floor 0.55)
```

`trades_behind_pace` compares trades taken this week against
`InpTargetTradesWeek × (fraction of the trading week elapsed)`. The floor is a hard
quality guarantee: the agent will miss its weekly target rather than take a setup it
believes is negative-expectancy.

## 7. Trade management

- **Partial** at +1.0R (default 50% of the position) — the first liquidity objective.
- **Break even** at +1.0R, offset by the current spread.
- **Structural trail** after +1.5R: the stop follows the most recent opposing swing
  (minus 0.3 units), never a fixed distance.
- **Time stop**: if the position has not reached +0.5R after ~8 pivot lengths of
  bars, the raid failed to expand and the risk is released.
- The remainder runs to the second objective (the far side of the dealing range).

## 8. The learning loop

```
signal → feature vector x stored with the position
       → outcome resolved (real: profit sign; paper: TP or SL hit first)
       → logistic SGD update, learning rate 0.06/√(1+0.05·n)
       → L2 pull toward the research priors (0.010)
       → one replay pass over the memory (up to 400 resolved observations)
       → model written to MQL5/Files/Common/smc_agent_model.csv
```

**Warm-up.** Until `InpWarmupSamples` outcomes have been observed (default 25), the
probability is a blend that starts at the pure research priors and shifts linearly
toward the learned model. The panel shows `WARM-UP n/25`. The agent still trades
during warm-up — the priors are a real strategy — it simply does not let a
half-trained model override them.

**Observation without risk.** Every setup that was rejected by a gate is added to
the paper book and resolved bar by bar against real candles, at 0.6 sample weight.
This is what lets the agent learn on a 2-trades-per-week diet without needing
hundreds of live trades first.

**Honest limits.** The model is linear in its features: it can learn that "sweeps
matter more than sessions on this account", but it cannot discover an interaction
that no factor expresses. That is a deliberate trade for stability and for the
readability of the panel.

## 9. What is drawn

Chart layer: order blocks and imbalances (fading label when tapped), the inducement
line guarding each order block labelled `IDM resting` / `IDM taken`, BOS / CHoCH
lines (dotted for internal structure), liquidity pools with their names and a
`swept` marker, the dealing range with premium / equilibrium / discount, an arrow
on the raid that armed the current hypothesis, killzone shading, and — while a
signal is live — entry, stop and both objectives with their R multiples.

Panel: mode and model state, structure on all three timeframes, dealing range and
raid, active playbook, the full 17-factor table with score bars, learned weights,
contributions and a plain-English reading of each factor, the weighted score and
probability, the complete FTMO position (day P/L, floors, remaining budget, open
risk, target progress, trading days, trades this week), the news line, the signal
or the reason there is none, and the last action taken.

Console: one block per bar close — what was read, which factors contributed, the
plan in plain English, the model's probability against the current acceptance
threshold, the sizing arithmetic, and the decision.
