# SMC Liquidity Raid + CHoCH — XAUUSD

One setup. Traded in both directions. Nothing else.

This is a deliberately narrow EA, separate from the adaptive agent in
`MQL5/Experts/SMCAgent/`. There is no machine learning, no confluence
scoring and no playbook selection — just the raid-and-reverse sequence,
executed the same way every time so that its results mean something.

## The rule

**BUY**

1. **Raid.** A closed candle's low trades *below* a sell-side liquidity pool
   and its close comes back *above* it, leaving a rejection wick of at least
   `InpMinRejection` of the candle's range. That is stop-loss liquidity being
   taken, not a breakdown.
2. **Change of character.** Within `InpConfirmBars` bars, a candle closes
   *above* the swing high that was standing at the moment of the raid. The
   level is fixed when the raid happens and never moves afterwards, and it
   must sit genuinely ahead of the close — a level price has already passed
   would be "broken" by the next candle whatever it did. If price instead
   trades through where the stop would go (the raid low less the same 0.15
   median-candle buffer the entry uses), the setup is void immediately.
3. **Execute.** Enter at the confirmation close. Stop goes beyond the raid
   low (plus a buffer of 0.15 median candles and the spread). Target is the
   nearest *unswept* buy-side pool at least `InpMinRR` away; if none lies far
   enough, a measured `InpFallbackRR` multiple of the risk is used instead.

**SELL** is the exact mirror: a buy-side pool raided and rejected, then a
close below the standing swing low, stop above the raid high.

### Pools it hunts

Previous day high/low, previous week high/low, the Asian session high/low
(00:00–07:00 London, computed from the real DST rules, and published only
once that session has actually closed), equal highs/lows within 0.15 of a
median candle, and the eight most recent swing highs and lows. Each can be
switched off individually. An equal pair replaces the swing it grew out of
rather than sitting a few cents beside it, and the day and week levels are
added first so a busy chart can never crowd them out.

## Nothing is optimised to a fixed price

The only numbers tied to price are derived from the chart itself each bar:

- **One candle** = the median true range of the last 400 closed bars. Stop
  width limits, buffers and equal-level tolerance are all expressed in these
  units, so the EA behaves the same on a quiet day and a volatile one.
- **Pivot length** defaults to whichever value between 2 and 6 produces about
  one pivot every eight candles on the current chart. Set `InpPivotLen` to a
  number ≥ 2 to fix it instead.

Calibration reads **closed bars only**. Bar 0 is still forming and including
it drags every statistic toward zero.

## Risk

- `InpRiskPercent` of balance per trade, sized from
  `SYMBOL_TRADE_TICK_VALUE_LOSS` and the actual stop distance, normalised to
  the broker's volume step (not hard-coded to two decimals), re-checked
  against min/max volume and reduced until the margin fits.
- A stop narrower than the broker's minimum distance is refused rather than
  sized into an enormous position.
- `InpMaxDailyLossPct` freezes new entries for the rest of the server day
  once equity is that far below the day's opening equity. Open positions are
  still managed.
- Optional partial at `InpPartialAtR`, break-even at `InpBreakEvenAtR`,
  structural trailing after `InpTrailAfterR`, and a time stop.

## What you see

**On the chart:** every tracked pool as a horizontal segment (red above,
blue below, dotted grey once swept) with its name; a blue/orange arrow at
each raid; a gold dashed line at the CHoCH level it needs to break, drawn
only as far as the confirmation window reaches; a large arrow at each entry.
Raid and CHoCH marks are never moved once drawn — they are history, not
forecasts — and are only removed when they scroll out of the loaded data.

**In the panel:** server time and detected GMT offset, session, state,
structure, standing swings, the median candle, pivot length, pool counts,
spread as a fraction of a candle, the armed setup with its rejection quality
and countdown, the open position with its live R, the account, the day's P/L
against the limit, a running tally, and the last decision in plain words.

**In the Experts log:** one `BAR |` line per closed bar with what the EA is
reading, plus `RAID`, `CHoCH`, `ENTRY`, `SKIP`, `VOID`, `EXPIRE`, `PARTIAL`,
`BE`, `TRAIL`, `TIME`, `CLOSED` and `BLOCK` lines. Every rejection says why.

Each `ENTRY` reports the risk it asked for against the risk the rounded lot
size actually carries, and warns when the 0.01 step costs more than a fifth of
the budget. Each `CLOSED` carries the running record: wins, losses, net and
profit factor. The panel shows the same record on its `Results` row - because
how many setups fired and whether they made money are different questions, and
only the second one decides anything.

## Install

1. Copy `SMC_Raid_CHoCH.mq5` into
   `MQL5/Experts/` inside your terminal's data folder
   (**File → Open Data Folder** in MetaTrader 5).
2. Compile it in MetaEditor (F7). It is a single self-contained file; the
   only include is MetaTrader's own `Trade/Trade.mqh`.
3. Attach it to an **XAUUSD M15** chart with algorithmic trading enabled.

The rules themselves are timeframe agnostic, but the confirmation window,
stop-width limit and pool set were chosen with M15 gold in mind.

## Inputs worth knowing

| Input | Default | Why you would change it |
|---|---|---|
| `InpConfirmBars` | 6 | Longer window = more trades, weaker reversals |
| `InpMinRejection` | 0.25 | Raise it to demand a more violent rejection |
| `InpPivotLen` | 0 (adaptive) | Fix it if you want identical structure to another tool |
| `InpKillzonesOnly` | false | Restrict to the London (07:00–10:00) and New York (08:00–11:00) killzones, local to each city and DST-correct |
| `InpMaxStopUnits` | 4.0 | Cap how wide a stop the setup may ask for |
| `InpMinRR` | 1.5 | Minimum reward:risk to the first pool |
| `InpFallbackRR` | 2.0 | Set to 0 to skip trades with no pool objective |
| `InpMaxTargetR` | 6.0 | Reject a setup whose objective sits further than this; 0 disables |
| `InpRequireHtfAgree` | false | Demand the H4 swing trend agrees; fewer, cleaner trades |
| `InpRiskPercent` | 0.5 | Risk per trade |
| `InpMaxDailyLossPct` | 3.0 | Set to 3.0 or lower on a 5% daily-limit account |

## What the audit changed

The first version was written straight through and then audited line by
line. Three of the fourteen findings would have stopped it working as
designed, and are worth knowing about if you compare against that first cut:

- The already-swept scan included bar 1 — the exact candle the raid detector
  judges — so **every raid arrived pre-marked "swept" and no setup could ever
  fire**. The scan now stops at bar 2.
- The time stop counted bars from the moment the order was *sent*, but the
  previous bar's open time is always earlier than that, so the count broke on
  its first pass and **held was permanently zero**. It now counts from the bar
  the trade was opened on.
- Pool eviction at the 40-pool cap removed from the front of the list, and the
  day and week levels are added first — so **PDH, PDL, PWH and PWL were the
  first things thrown away** on a chart with many swings.

The rest: a previous-week level older than the loaded M15 window was never
checked for sweeps at all; equal highs were published alongside the swing
they were built from; the Asian range was published while it was still
forming; a fixed lot size bypassed volume-step normalisation; stop and target
distances were checked against the wrong side of the spread and ignored the
freeze level; break-even and trailing moves could ask for a stop the broker
would refuse; panel rows ran past the background and the panel was fully
deleted and rebuilt twice a second; several inputs could be set to values
that silently prevented any trade; and the one-letter bar accessors were
renamed (`C()` sat one character away from MQL5's `C'r,g,b'` colour syntax).

## Honest limits

- This has not been compiled in MetaEditor or run through the strategy
  tester from here. Compile it and backtest it before it sees money.
- The trade rate is whatever the market offers. A narrow setup on M15 gold
  typically fires a handful of times a week; there is no minimum-frequency
  mechanism forcing trades, by design.
- Structure is read from closed bars, so the EA is always one bar behind a
  break. That is the cost of not repainting.
- The daily loss governor takes its reference equity from the first bar close
  after the EA sees a new server day. Attach it mid-session and the day's
  earlier losses are not counted against the limit until the next day rolls.
