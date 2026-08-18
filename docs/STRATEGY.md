# XAUUSD FTMO Confluence EA — Strategy Specification

> **Read this before risking money.** The section *"The 70% question"* explains
> what this EA can and cannot promise, and it is the most important part of the
> document.

---

## 1. The brief, and how each requirement is met

| Requirement | How it is implemented |
|---|---|
| Trades XAUUSD | M15 execution with H1/H4 context; every default is tuned to gold's volatility |
| Session control | Named London / New York / Asia sessions, DST-aware, Asia off by default |
| At least one trade a day | Daily-quota mode relaxes the score threshold after 14:30 GMT if nothing has traded, at reduced size |
| Meets FTMO 2-step rules | Layered soft/hard guards that trip at 2%/3% daily and 5%/7% total — well inside the 5%/10% limits |
| Strong confluence | 11 weighted components across 3 timeframes |
| Not too restrictive | Weighted **scoring**, not a boolean AND-chain — see §3 |
| Small losses, larger wins | Scaled exits: partial at 1R, breakeven lock, runner to 3R — see §5 |
| ForexFactory news filter | Weekly FF JSON feed + MT5 built-in calendar + manual CSV fallback — see §6 |
| Risk management | ATR/structure stops, streak de-risking, per-trade budget capped by remaining drawdown room |

---

## 2. Timeframe, sessions, and time alignment

Gold's intraday behaviour drove both choices.

**Timeframe.** Published backtest surveys of XAUUSD consistently find that daily
and higher timeframes produce the best profit factors, while M1–M5 gets eaten by
gold's spread and noise. M15 is the compromise that still generates enough setups
for a daily trade: it filters most of the noise, its ATR is large enough that a
1.6×ATR stop clears the spread comfortably, and H1/H4 provide the trend context
that a single timeframe cannot.

**Sessions.** Gold's volatility is heavily concentrated, so the EA has three
named, independently switchable sessions:

| Session | Default window (market local) | Default | Why |
|---|---|---|---|
| **Asia** (Tokyo) | 09:00–15:00 JST | **off** | Thin, range-bound, prone to fake breakouts. Available if you want the Shanghai/Tokyo gold fix, but it is the weakest window. |
| **London** | 08:00–12:00 London | **on** | European institutional flow arrives; the first real directional push of the day. |
| **New York** | 08:00–12:00 New York | **on** | Covers the 08:30 ET data window and the whole London/NY overlap — the highest liquidity and volatility of the day, and the tightest spreads. |

Late NY (after 12:00 ET) is excluded by default: liquidity drains and trends decay.

Trading only these windows is itself a risk control: it removes the hours where
gold's stop-hunting behaviour is worst.

### Time alignment and DST

Session windows are expressed in **each market's own local time and converted at
runtime**, because three clocks move independently:

- The **broker server** (FTMO runs on CE(S)T) switches on the last Sunday in
  March and October.
- **London** switches on the same EU dates.
- **New York** switches on the *second* Sunday in March and the *first* Sunday in
  November.

The EU and US dates are about two weeks apart, so for roughly three weeks a year
the London/NY relationship is an hour different from the rest of the year. A
window pinned to fixed GMT is therefore wrong for part of every year. Worked
example, on a CE(S)T broker with the defaults above:

| Date | Server | London (server) | New York (server) | Asia (server) |
|---|---|---|---|---|
| mid-January (both standard) | GMT+1 | 09:00–13:00 | 14:00–18:00 | 01:00–07:00 |
| **12 March (US on DST, EU not)** | GMT+1 | 09:00–13:00 | **13:00–17:00** | 01:00–07:00 |
| mid-July (both on DST) | GMT+2 | 09:00–13:00 | 14:00–18:00 | 02:00–08:00 |
| **28 October (EU off DST, US still on)** | GMT+1 | 09:00–13:00 | **13:00–17:00** | 01:00–07:00 |

London stays fixed in server terms because the London and CE(S)T clocks move
together. New York shifts by an hour during the two gap periods. Asia shifts
because Tokyo has no DST while the server does.

The same conversion drives three other things:

1. **The ForexFactory feed.** Its timestamps are ISO-8601 with a US-Eastern
   offset; the parser reads the offset, converts to UTC, then applies the
   detected broker offset. (The MT5 built-in calendar already returns server
   time and needs no conversion.)
2. **The FTMO daily-loss boundary.** The 00:00 CE(S)T reset is derived from the
   detected server offset and the EU DST state, not hand-entered. Because moving
   the boundary mid-session would reset the day's loss counter, a shift is
   deferred until no position is open and no trade has been taken that day.
3. **The Friday cutoff, weekend flatten, and daily-quota trigger**, which are
   deliberately anchored to **fixed GMT** — they are risk controls, not market
   sessions, so they should not drift with a market clock.

The broker offset is detected from `TimeTradeServer() - TimeGMT()`, rounded to
the nearest half hour, range-checked, and **re-checked on every timer tick** — so
a DST transition is picked up while the EA is running rather than silently
shifting every window by an hour until the next restart. When the offset changes,
the news table is rebuilt, because the stored event times were converted under
the old offset.

If detection fails (no connection, or the tester's simulated GMT), the EA logs a
warning, falls back to the manual value, and turns the dashboard clock row red
rather than trading on a guess.

On startup the journal prints every window as it will actually be applied:

```
[Time] broker server clock is GMT+2 (offset +2.0 h).
[Time] FTMO day boundary: server time minus CE(S)T = +0.0 h (auto).
[Time] resolved session windows:
   Asia      disabled
   London    09:00-13:00 server   (London local 08:00-12:00, currently GMT+1)
   New York  14:00-18:00 server   (New York local 08:00-12:00, currently GMT-5)
   Fri stop  16:00 server   (GMT 15:00)
   Fri flat  20:00 server   (GMT 19:00)
   Quota     15:30 server   (GMT 14:30)
[Time] DST state: Europe standard, US standard.
```

That block is the first thing to check if trades appear at the wrong hour.


---

## 3. The confluence engine — why a score, not an AND-chain

This is the central design decision, and it is what the brief's *"many indicators
without becoming too restrictive"* actually requires.

Eleven indicators wired as `A && B && C && … && K` would fire perhaps twice a
month. That fails the "one trade a day" requirement outright, and it also
overfits: you end up demanding a configuration of the market that has barely
occurred historically.

So each component awards **weighted points** to a bull score and a bear score,
both normalised to 0–100. A trade requires:

```
winning_score >= ScoreThreshold        (default 66)
winning_score - losing_score >= Margin (default 22)
```

The margin requirement matters as much as the threshold — it rejects the
"everything is half-confirmed in both directions" chop that destroys gold
accounts.

### The eleven components

| # | Component | Weight | Bullish condition | Why gold |
|---|---|---|---|---|
| 1 | H4 regime | 12 | EMA50 > EMA200, full points if close > EMA50 | Gold trends persist on H4; this is the macro filter |
| 2 | H1 trend | 12 | EMA21 > EMA50, full points if EMA21 rising | Intermediate structure; slope catches decaying trends |
| 3 | M15 trend + trigger | 10 | EMA8 > EMA21, close > EMA21, full points on a close through the prior bar high | The actual entry trigger |
| 4 | ADX / DI | 12 | ADX ≥ 20 (hard gate) and DI+ > DI− | Gold ranges violently; ADX is the single best chop filter |
| 5 | RSI zone | 8 | RSI in 45–78 and rising | Trend-following zone, **not** a contrarian overbought read |
| 6 | MACD | 10 | Histogram > 0 and expanding | Momentum confirmation independent of price location |
| 7 | Stochastic | 8 | %K crosses %D from below 45 | Times the *pullback entry* so we buy dips, not tops |
| 8 | Daily VWAP | 8 | Close > session VWAP | Much of gold's volume is benchmarked to VWAP |
| 9 | Bollinger location | 6 | Between the mid and upper band; **only 20% of points above the upper band** | Explicitly penalises chasing an over-extended move |
| 10 | Structure | 8 | Above the daily pivot and above the prior-day midpoint | Institutional reference levels |
| 11 | Volume | 6 | Signal-bar tick volume ≥ 1.1× the 20-bar average | Separates real breaks from drift |

### Hard gates (these veto regardless of score)

These are about *tradeability*, not direction, so a score cannot buy its way past
them:

- **ADX < 20** → no trend to ride.
- **ATR outside 1.20–14.00 price** → market either dead or unmanageably wild.
- **Price more than 2.2 ATR from the M15 EMA21** → too extended; the reward is
  gone and the mean-reversion risk is at its peak.
- Spread above 45 points, outside session hours, or inside a news blackout.

---

## 4. The 70% question — read this

**No EA can guarantee a 70% win rate, and any vendor who tells you otherwise is
selling a curve fit.** The honest position:

A 70% win rate *and* "small losses vs larger wins" are in direct tension. The
usual way to reach 70% is to take small profits and hold losers — which is
exactly the behaviour that fails FTMO. The expectancy formula is what matters:

```
Expectancy = (WinRate × AvgWin) − (LossRate × AvgLoss)
```

A 70% win rate at 1:0.5 R:R loses money. A 45% win rate at 1:2 makes money.

**How this EA reconciles the two requirements** — by scaling out, so a single
trade produces a *distribution* of outcomes rather than one:

| Outcome | Result | Counts as |
|---|---|---|
| Stop hit before 1R | **−1.00R** | loss |
| TP1 hit, then stopped at breakeven+lock | **+0.50R** | win |
| TP1 hit, then trailed out | **+0.5R to +2.0R** | win |
| TP1 hit, then TP2 at 3R | **+2.00R** | win |

Every trade that touches 1R is booked green and can no longer lose. So the
*percentage of green trades* tracks "how often does price reach 1R", which for a
trend-pullback entry with a 1.6-ATR stop is realistically **55–70%**, while the
average win stays comfortably above the average loss.

The number to judge this EA on is **profit factor and max drawdown**, not win
rate. Targets worth holding it to:

- Profit factor ≥ 1.35
- Max drawdown < 5% of initial capital
- Average win ÷ average loss ≥ 1.3
- At least 4 trading days per phase (an FTMO requirement)

§9 gives the protocol for measuring these on your own broker's data.

---

## 5. Risk management — the part that actually passes challenges

### Position sizing

Default: **0.50% of the initial capital per trade**, sized off the actual stop
distance so risk is constant in money terms regardless of volatility.

Sizing is the **minimum** of three numbers:

1. The configured risk per trade;
2. 70% of the room remaining before the soft *daily* guard;
3. 70% of the room remaining before the soft *total* guard.

Clause 3 is what stops a drawdown compounding: as equity falls toward the floor,
the position size automatically shrinks. You cannot reach the FTMO limit in a
straight line.

### Loss-streak de-risking

After consecutive losses, risk is multiplied by `0.6^(streak−1)` (floored at
0.25×). Two losses → 60% size. Three → 36%. Three consecutive losses also stops
trading for the day entirely.

### The guard ladder

| Level | Daily | Total | Action |
|---|---|---|---|
| Soft | 2.0% | 5.0% | No new trades; open positions still managed |
| Hard | 3.0% | 7.0% | Flatten everything immediately |
| **FTMO rule** | **5.0%** | **10.0%** | **Account breached** |

The 2% gap between the hard guard and the real limit absorbs slippage, a weekend
gap, and swap. The daily figure is measured against the balance at **00:00
CE(S)T** and **includes floating P/L** — matching how FTMO actually calculates it.
When a position is carried across midnight, the EA takes the lower of balance and
equity as the day's anchor, which is the conservative reading.

### Other controls

- Max 3 trades/day, max 1 position at a time, 45 minutes minimum between entries.
- Everything flat by 19:00 GMT Friday — no weekend gap risk.
- No new trades after 15:00 GMT Friday.
- Trading stops once the phase target is reached (`InpStopAtTarget`). There is no
  reason to keep risking a passed challenge.

---

## 6. The news filter

FTMO's restriction: **no trades opened or closed within 2 minutes either side of
a high-impact release on the affected instrument.** Yellow/orange folder events
do not trigger a violation. This EA uses a **30-minute window on each side** by
default — far wider than required, because the *trading* reason to avoid the
release (gold routinely spikes $10–20 on CPI/NFP, blowing through stops with
slippage) is stronger than the compliance reason.

### Three sources, layered

1. **ForexFactory weekly JSON** — `https://nfs.faireconomy.media/ff_calendar_thisweek.json`.
   Must be whitelisted in *Tools → Options → Expert Advisors → Allow WebRequest
   for listed URL*. The feed is rate-limited to 2 downloads per 5 minutes, so the
   EA fetches every 4 hours by default and caches the body to
   `MQL5/Files/XAUUSD_FTMO_ff_calendar.json`.
2. **MT5 built-in economic calendar** (`CalendarValueHistory`) — no whitelisting,
   works in the Strategy Tester, but some brokers ship it empty.
3. **Manual CSV** — `YYYY.MM.DD HH:MM,CCY,IMPACT,Title` per line, for a
   hand-curated FOMC/NFP/CPI list when nothing else is reachable.

Running **both** (the default) means a feed outage does not silently disable the
filter. Events are de-duplicated across sources.

Because FTMO also forbids *closing* inside the window, the EA flattens **5 minutes
before** a blackout opens rather than being trapped inside it.

**Timezone handling** is the classic failure point. FF timestamps are ISO-8601 with
a US-Eastern offset; the EA parses the offset, converts to UTC, then applies the
detected broker GMT offset. Verify this on a live chart before trusting it — the
dashboard shows the next scheduled event and its countdown.

---

## 7. Why these specific indicators for gold

Every indicator here answers a distinct question. Redundant indicators inflate a
confluence score without adding information — that is the most common flaw in
multi-indicator systems.

| Question | Indicator |
|---|---|
| What is the dominant regime? | H4 EMA 50/200 |
| Is the intermediate trend intact and accelerating? | H1 EMA 21/50 + slope |
| Is there a trend *right now*, or just noise? | ADX + DI (hard gate) |
| Is momentum with us? | MACD histogram |
| Is momentum over-stretched? | RSI zone bounds, Bollinger position |
| Is this a pullback entry or a chase? | Stochastic cross, ATR extension gate |
| Where is fair value today? | Session VWAP |
| Where will other traders act? | Daily pivot, prior-day high/low |
| Is the move real? | Tick volume vs 20-bar average |
| How wide should the stop be? | ATR |

ATR earns its place twice: as a volatility *regime filter* and as the stop-sizing
input. Gold's ATR can triple between a quiet August session and a CPI week —
a fixed pip stop is unusable on this instrument.

---

## 8. Known limitations

- **Trend-following systems suffer in ranges.** ADX and the ATR band mitigate
  this, they do not eliminate it. Expect losing streaks of 3–4.
- **Quota mode deliberately lowers the bar** to satisfy "one trade a day". These
  are statistically weaker trades, which is why they are taken at 60% size. If you
  do not need a daily trade, set `InpUseDailyQuota = false` — the EA will be more
  selective and probably more profitable per trade.
- **Tick-volume is not real volume.** On a broker with poor tick density,
  component 11 degrades; lower `InpWVolume` if so.
- **VWAP is anchored to broker midnight**, not the CME session. On a GMT+2/+3
  server this is close enough for intraday work; on an exotic offset, verify it.
- **DST detection assumes current EU and US rules.** If either region abolishes
  seasonal clock changes, `TimeZones.mqh` needs updating — the transition dates
  are computed from the rules, not from a lookup table, so the fix is one edit.
- **`TimeGMT()` is simulated in the Strategy Tester.** Offset detection may be
  unreliable there; set `InpUseManualGmtOffset = true` for backtests.
- **The MT5 calendar is not available on every broker.** Check the journal on
  startup — the EA logs which sources initialised.
- **Backtest quality.** MT5's "Open prices only" mode will not model the partial
  and trailing logic correctly. Use **Every tick based on real ticks**, and treat
  any backtest not run on your own FTMO broker's data as indicative only.

---

## 9. Validation protocol before spending money on a challenge

Do not skip this. Run it in order.

1. **Compile** in MetaEditor. Zero errors, and read the warnings.
2. **Visual-mode backtest**, 1 month, *Every tick based on real ticks*. Watch the
   trades. Confirm: stops sit behind structure, TP1 partials fire, breakeven moves
   happen, news windows are skipped.
3. **12-month backtest** on your FTMO broker's XAUUSD data. Record profit factor,
   max drawdown, avg win ÷ avg loss, trades per day, worst losing streak.
4. **Walk-forward:** optimise on months 1–8, validate untouched on 9–12. If
   performance collapses out-of-sample, the parameters are overfit — widen the
   thresholds rather than tuning harder.
5. **Monte Carlo** the trade sequence (shuffle 1,000 times). If the 95th-percentile
   worst drawdown exceeds 8%, cut `InpRiskPercent` until it does not.
6. **FTMO free trial or demo, 4+ weeks**, on the real server. This is the only step
   that tests the news feed, the spread, and the server timezone in the conditions
   that count.
7. Only then, a funded challenge.

A realistic expectation: **0.5% risk per trade with ~1.3R average return and 1–2
trades a day takes roughly 6–10 weeks to reach a 10% target.** Anyone promising it
in a week is describing a gamble, not a strategy.

---

## 10. Sources

- [FTMO Trading Objectives](https://ftmo.com/en/trading-objectives/)
- [FTMO Rules 2026: 1-Step & 2-Step Challenge Rules](https://tradetanto.com/learn/ftmo-rules-evaluation-process)
- [FTMO Rules & Drawdown Limits (2026) — PropJournal](https://propjournal.net/prop-firms/ftmo/rules)
- [FTMO News Trading Rules Explained (2026)](https://propfirmcircle.com/blog/ftmo-news-trading-rules)
- [FTMO EA Rules Explained 2026 — EAFunded](https://www.eafunded.com/blog/ftmo-ea-rules)
- [Does FTMO Have a Consistency Rule?](https://propvator.com/blog/does-ftmo-have-a-consistency-rule/)
- [Day Trading Gold (XAU/USD): 2026 Strategy & Timing Guide](https://arongroups.co/forex-articles/day-trading-gold-xauusd/)
- [Best Time to Trade Gold (XAUUSD) — NordFX](https://nordfx.com/traders-guide/best-time-to-trade-gold-xauusd-sessions-volatility-news)
- [XAUUSD Trading Strategies: 3 Backtested Approaches (8,693 Trades)](https://quant-signals.com/xauusd-trading-strategies/)
- [Forex Risk-to-Reward Ratio: Why a 30% Win Rate Beats 70%](https://fxnx.com/en/blog/the-expectancy-edge-why-a-30-win-rate-beats-70-in-forex)
- [MQL5 Docs — CalendarValueHistory](https://www.mql5.com/en/docs/calendar/calendarvaluehistory)
- [MQL5 Cookbook — Economic Calendar](https://www.mql5.com/en/articles/9874)
- [ForexFactory weekly calendar feed](https://nfs.faireconomy.media/ff_calendar_thisweek.json)
