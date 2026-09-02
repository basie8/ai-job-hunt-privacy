# SMC AI Agent — Pine Script port

TradingView strategy port of the MQL5 expert advisor in `../MQL5/`. Same seven
steps, same 17-factor reasoning layer, same FTMO envelope, same design rule that
no fixed technical parameter drives a decision.

## Install

1. TradingView → **Pine Editor** → paste `SMC_AI_Agent.pine`
2. **Save**, then **Add to chart**
3. Chart: **XAUUSD**, **15 minute** (matches the EA's recommended setup — the
   script derives H1 and H4 from it automatically)
4. Set the strategy's **initial capital** in the script settings to your phase
   capital; the FTMO floors are computed from it

## What is the same as the EA

- Self-calibration on closed bars: median true range as the "unit", adaptive
  pivot length chosen by pivot density, imbalance significance from the live gap
  distribution, volatility regime from the 20-bar window
- Swing and internal structure, BOS / CHoCH, order blocks with displacement and
  participation scoring, fair value gaps, mitigation counted only after price
  displaces away
- Liquidity: equal highs/lows, swing pools, PDH/PDL, PWH/PWL, Asian range
- Stop raids, **inducement**, dealing range with premium / equilibrium / discount
- The three playbooks: raid → CHoCH, post-release raid, continuation into origin
- 17 confluence factors → online logistic regression anchored to the research
  priors, with warm-up blending
- Expectancy gate `R_min = max(1.30, (1−p)/p × 1.8)`, frequency governor
- FTMO layered envelope, conviction and loss-streak sizing, partial at 1R,
  break even, structural trail, time stop
- Decision panel with the factor table, probability, threshold and FTMO position

## What is better here

- **Daylight saving is exact.** Sessions use TradingView's IANA database
  (`Europe/London`, `America/New_York`) instead of the hand-rolled DST rules the
  MQL5 build needs.
- Backtesting, equity curve and trade list come free with the strategy tester.

## What is worse here — genuine limitations

| Limitation | Consequence |
|---|---|
| **No persistence.** Pine cannot write files. | The learned model rebuilds from the research priors on every compile or chart reload. It learns forward through history, then forgets. The MQL5 build keeps its weights. |
| **No economic calendar.** Pine has no news feed. | High-impact releases must be pasted into the input as `YYYY-MM-DD HH:MM` (UTC), one per line, or the news factor stays neutral. |
| **No live spread.** | The execution-cost factor is held at 0 and the tester's commission/slippage settings stand in for it. |
| **No real account.** | The FTMO envelope runs on `strategy.equity`. It proves the logic; it does not protect a funded account. |
| **Compact HTF bias.** | Higher timeframes get a structure read via `request.security`, not the full three-engine analysis. |
| **Position units, not lots.** | `qty` is in instrument units. On XAUUSD 1 unit = 1 ounce, so **0.01 MT5 lots = 1 unit here**. Check the tester's position sizes against your broker before comparing results. |

## Which to use for what

- **Pine version** — research, visual validation against a LuxAlgo overlay,
  fast iteration on the SMC reads, and getting a first read on whether the edge
  exists at all.
- **MQL5 version** — anything involving a real or funded account: it persists its
  learning, reads the real calendar, sees the live spread, and enforces the FTMO
  rules against actual equity.

Validate the reads here, then trade the MQL5 build.

## Known Pine constraints handled in the code

- **A function may not assign to a global.** The model's mutable scalars (learned
  bias, update count, scored, correct) therefore live inside a `ST` array:
  mutating the contents of a global object is allowed, rebinding the name is not.
  The weight vector `W`, the feature vector `X` and the zone/pool collections are
  arrays for the same reason.

## Not verified

This script has been compiled far enough to clear `CE10088`, but has **not been
fully compiled or backtested.** Structure, bracket balance, indentation, function resolution and
input references were checked statically. Expect to clear a diagnostic or two on
first paste.
