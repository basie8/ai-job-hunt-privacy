# Research notes — what the agent was built from

Everything the agent does traces back to something in this file. The point of the
research was **not** to find parameters to optimise, but to find the *structural*
edges that survive when a market changes character — because the agent is required
to read the chart live rather than replay a fitted configuration.

Research was carried out in September 2026 across four buckets: the reference
implementation of the indicator suite the user asked to see (LuxAlgo Smart Money
Concepts), the institutional / ICT literature that the SMC vocabulary comes from,
published statistics and backtests on the individual SMC components, and the
prop-firm rulebook the agent must survive inside (FTMO 2-step).

---

## 1. The SMC picture that must be on the chart (LuxAlgo reference)

The LuxAlgo *Smart Money Concepts* script is the de-facto reference for what
traders expect to see. Its feature set defines the visual contract of this EA:

| LuxAlgo element | Implemented in | Notes |
|---|---|---|
| Swing market structure, BOS / CHoCH | `SmcEngine.mqh :: MapStructure` | BOS = break with the trend, CHoCH = first break against it |
| Internal (minor) structure | `SmcEngine.mqh :: MapStructure` (second pivot length) | drawn dotted, labelled `(i)` |
| Swing and internal order blocks | `SmcEngine.mqh :: BuildOrderBlock` | last opposing candle before the displacement that broke structure |
| Fair value gaps / imbalances | `SmcEngine.mqh :: MapFvg` | 3-candle imbalance, filtered by the live gap distribution |
| Equal highs / equal lows | `SmcEngine.mqh :: MapLiquidity` | tolerance derived from the median true range, not a fixed pip value |
| Inducement (IDM) | `SmcEngine.mqh :: FindInducement` | not a LuxAlgo object; added from the ICT / structure-mapping literature (see §2b) |
| Premium / discount / equilibrium | `SmcEngine.mqh :: MapRange` | drawn over the current dealing range |
| Multi-timeframe highs and lows | `Confluence.mqh :: LoadKeyLevels` | PDH/PDL, PWH/PWL, Asian range |

Key definitions used verbatim from the reference: a **BOS** labels a structure break
in the direction of the current trend (continuation); a **CHoCH** labels the first
break against it (the earliest reversal warning); **order blocks** are the price
zones where large participants initiated, and they act as magnets for liquidity;
**FVGs** are the imbalances left by aggressive institutional orders; **premium and
discount zones** are the relative-value halves of a range used to time entries.

Sources:
- <https://www.tradingview.com/script/CnB3fSph-Smart-Money-Concepts-SMC-LuxAlgo/>
- <https://www.luxalgo.com/library/indicator/smart-money-concepts-smc/>
- <https://www.luxalgo.com/blog/smart-money-concept-indicator-for-tradingview-free/>
- <https://www.luxalgo.com/library/indicator/luxalgo-price-action-concepts/>

## 2. Institutional / ICT literature, applied to gold

The ICT body of work supplies the *sequence* the agent trades, not just the objects:
liquidity is engineered first, then structure shifts, then price returns to the
origin of the move.

Findings that made it into the code:

- **Kill zones.** Gold's institutional windows are the London open (roughly
  07:00–10:00 GMT) and the New York open / London overlap (roughly 12:00–15:00 GMT).
  These are the windows where inducement sweeps, BOS events and trend-setting moves
  cluster. → `Confluence.mqh :: SessionScore`.
- **Liquidity sweeps / Judas swings.** As price approaches obvious highs, lows or
  session boundaries, the high-probability action is to wait for the brief break of
  that level (stops triggered) and the rejection back inside — the reversal *after*
  the sweep is the signal, not the break itself. → `SmcEngine.mqh :: DetectSweep`
  and playbook A.
- **Session personality.** A setup that behaves well in the quiet Asian session is
  frequently destroyed by the liquidity wick at the NY open; volatility is not
  evenly distributed across the day, with extreme expansion in the 13:00–17:00 GMT
  window when US data prints and COMEX opens. → the session factor plus the
  volatility-regime factor.
- **AMD / accumulation range.** The Asian range is treated as the accumulation
  phase whose high and low are the first liquidity objectives of the London
  session. → `MarketState.mqh :: AsianRange`, pools `ASIA-H` / `ASIA-L`.

Sources:
- <https://www.ictkillzone.com/ict-gold-xauusd>
- <https://fxnx.com/en/blog/ict-killzones-master-xauusd-timing-maximum-profit>
- <https://zayecapitalmarkets.com/kill-zone-in-ict-trading/>
- <https://hw.online/faq/comprehensive-review-ict-trading-strategy-applied-gold-xauusd/>
- <https://medium.com/@fxmbrand/ict-smart-money-concepts-finally-explained-like-youre-5-for-gold-trading-the-ultimate-2026-6517ea11c7c7>
- <https://fxnx.com/en/blog/gold-vs-forex-volatility-xauusd-data-guide>

## 2b. Inducement (IDM)

Inducement is the piece that turns "price is in an order block" into "price was
*drawn* to this order block". The definition used in the code is the mechanical one:
**the first valid pullback inside the leg that produced the BOS or CHoCH**. Traders
who buy that shallow pullback leave their stops just behind it, which turns the
pocket into a small liquidity pool — one price is expected to collect on the way to
the real point of interest. In strict structure-mapping models the zone behind the
inducement is not treated as valid until that pullback has been run.

Implementation consequences:

- `SmcEngine::FindInducement` scans the interior of the creating leg from the order
  block forward and returns the first minor pivot it finds (internal pivot length
  first, then a single-bar pivot as a fallback). No pullback in the leg means no
  inducement — a clean impulse leaves nothing resting in front of the zone.
- `UpdateZones` re-resolves `idm_taken` on every bar, so a zone flips from
  *resting* to *armed* the moment price runs the pullback.
- The stop is placed beyond an untaken inducement, never in front of it.
- It is a **scored factor, not a hard veto**: on a raid-driven setup the major
  liquidity grab has already done the trapping, so an untaken inducement is a
  penalty rather than a disqualification. On a continuation retest it is close to
  disqualifying. Where it bites hardest in practice is the wide gold order block
  whose inducement sits inside the zone — the case where price taps the proximal
  edge, runs the pullback below it, and only then reverses.

Sources:
- <https://www.luxalgo.com/library/concept/inducement/>
- <https://www.equiti.com/sc-en/news/trading-ideas/inducement-in-smc-explained-how-smart-money-traps-work/>
- <https://www.litefinance.org/blog/for-beginners/what-is-inducement-in-trading/>
- <https://tradingfinder.com/education/forex/inducement/>
- <https://3commas.io/blog/what-is-inducement-in-smart-money-concepts>

## 3. What the statistics say about the individual components

This is where the **factor priors** come from. The published numbers are not precise
enough to hard-code as thresholds — which is exactly why they are used as *starting
weights* for a model that then re-learns them from the live account.

- Confluence beats any single element: when price returns to an **overlapping order
  block + fair value gap** with the higher-timeframe bias in favour, reported win
  rates exceed 65%, materially above either element alone; stacked setups
  consistently outperform single-confluence entries. → highest priors go to
  structure confirmation, sweep quality, HTF alignment, then OB/FVG overlap.
- **Fair value gaps fill roughly 70% of the time**, which is why an unfilled
  imbalance is treated as a magnet (objective) as well as an entry zone.
- Broad SMC backtests cluster around **50–65% win rate with profit factors above
  1.5** — i.e. a real but modest edge that only survives with disciplined R
  multiples. This is why the agent enforces an *expectancy* gate
  (`R_min = max(1.30, (1-p)/p × 1.8)`) instead of a fixed reward:risk setting.
- Order-block validity is a function of the **displacement** that followed it and
  whether it remains unmitigated — both are measured directly rather than assumed.

Sources:
- <https://medium.com/@QuantumAlgo/i-backtested-2-600-trades-using-smart-money-concepts-heres-what-actually-works-bb3c671098c6>
- <https://forextester.com/blog/fair-value-gap/>
- <https://liquidityfinder.com/news/anatomy-of-a-valid-order-block-in-smart-money-concepts-67221>
- <https://www.quantum-algo.com/blog/order-blocks-fair-value-gaps-explained/>
- <https://www.strike.money/technical-analysis/smart-money-concepts>

## 4. FTMO 2-step rulebook (the hard constraint)

| Objective | 2-step programme | Where enforced |
|---|---|---|
| Phase 1 profit target | **10%** | `RiskManager :: TargetEquity`, input `InpPhase` |
| Phase 2 profit target | **5%** | same |
| Maximum daily loss | **5% of initial capital**, recalculated at midnight CE(S)T from the balance recorded at that moment, floating P/L included | `RiskManager :: DailyFloor`, `NewDayCheck` |
| Maximum overall loss | **10% of initial capital, static** (not trailing) | `RiskManager :: OverallFloor` |
| Minimum trading days | **4 per phase**, no time limit | `RiskManager :: TradingDays`, surfaced on the panel |
| News trading | unrestricted during Challenge and Verification; on a **funded Standard account a 2-minute window before and after selected high-impact releases** is off limits for opening *and* closing affected instruments (Swing accounts exempt) | `NewsFilter` + `InpFlattenBeforeNews`, which steps aside *before* the window opens so the agent never needs to act inside it |

Because a breach is terminal, the agent never trades to the limit. It uses a
three-layer envelope (soft stop → hard floor → absolute rule) described in
`STRATEGY.md`.

Sources:
- <https://ftmo.com/en/trading-objectives/>
- <https://academy.ftmo.com/lesson/maximum-daily-loss/>
- <https://tradetanto.com/learn/ftmo-rules-evaluation-process>
- <https://propfirmcircle.com/blog/ftmo-news-trading-rules>
- <https://forexmt4indicators.com/ftmo-rules/>

## 5. News handling in MQL5

The MetaTrader 5 economic calendar is queried with `CalendarValueHistory` for the
window around now, and each value is resolved to its event with `CalendarEventById`
so importance can be filtered (`CALENDAR_IMPORTANCE_HIGH`). Two practical points
from the literature shaped the implementation:

1. **Currency filtering matters** — an EA should not stand aside for news that
   cannot move its instrument. Gold is a USD-denominated macro asset, so the agent
   watches USD first, with EUR and GBP included because they move the dollar index.
2. **The calendar is not available in every context** (notably the strategy tester
   and some brokers), so a CSV fallback in the common files folder is supported.
3. **The calendar publishes in GMT while everything else in an EA is server time.**
   The documented correction is the difference between the trade server's timezone
   and GMT (`TimeTradeServer() - TimeGMT()`), which is what the agent applies once
   per cached event and re-detects daily so broker daylight-saving changes are
   picked up automatically. `TimeTradeServer()` is used rather than `TimeCurrent()`
   because the latter is the last tick's timestamp and stalls when the book is quiet.

Sources:
- <https://www.mql5.com/en/docs/calendar/calendarvaluehistory>
- <https://www.mql5.com/en/articles/21235>
- <https://www.mql5.com/en/articles/22580>
- <https://www.mql5.com/en/articles/9874>
- <https://www.mql5.com/en/book/common/timing/timing_gmt>
- <https://www.mql5.com/en/docs/dateandtime/timegmt>

## 6. Machine learning approach

The requirement was a agent that *learns and observes* rather than one that is
optimised offline. The relevant published work in the MQL5 ecosystem points to
online logistic regression as the right tool for trade-signal filtering: it updates
per resolved trade, it works with tiny samples, its coefficients stay interpretable,
and it is honest about being linear in its features. Reported implementations reach
usable calibration (ROC-AUC ≈ 0.77) with a handful of features, and the standard
pattern is exactly the one used here — the EA collects the feature vector at signal
time, waits for the outcome, and feeds the pair back to the model.

Design consequences:
- **Warm-up before voting.** The model observes resolved setups (real *and* paper)
  before it is allowed to move the decision.
- **Prior anchoring instead of plain L2.** Regularisation pulls weights toward the
  researched priors, not toward zero, so a bad streak cannot erase the structure of
  the strategy.
- **Replay memory.** Resolved observations are kept and re-visited, which stabilises
  learning when trades are scarce (2–4 per week).

Sources:
- <https://www.mql5.com/en/articles/23700>
- <https://www.mql5.com/en/articles/20235>
- <https://www.mql5.com/en/articles/18660>

---

### What was deliberately *not* taken from the research

- **Fixed indicator triggers** (RSI levels, MA crosses, fixed ATR multiples). They
  are the thing the brief rules out, and they are also the first thing to break when
  gold's volatility regime changes.
- **Fixed pip distances** for equal highs/lows, stop buffers or "significant" gaps.
  All of these are replaced by percentiles of the live candle distribution.
- **Grid / martingale recovery.** Incompatible with a 5% daily ceiling.
