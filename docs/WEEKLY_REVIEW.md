# Weekly review

**This is the highest-value thing you do for the system.** Everything else is
automated; this is the input only you can supply.

Cadence: once a week, ~15 minutes. Paste the filled template into a session and
say "weekly review". I update the journal, the learning log and the roadmap from it.

---

## Why this matters more than the automation

This is a **paper** book: no orders are placed, and outcomes are resolved
automatically against the candles that followed the signal. So there are no fills
to reconcile — which removes the tedious half of a trading review and leaves the
half that actually matters.

The journal knows what the pipeline *proposed* and what the candles then did. It
does not know:

- whether a loss was a bad read or ordinary variance
- what you saw on the chart that the computed features missed
- whether you would have taken the trade at all, and why not
- what spread and slippage would have cost in reality

That last one matters more than it looks. **Paper results are systematically
optimistic**, because a simulated fill has no spread and no slippage. On a $10
stop, a $0.30 spread is 3% of every R. Give me your real spread and I can report
a cost-adjusted expectancy alongside the raw one.

The post-mortems are what improve the system permanently. A losing trade tells
the learning loop "this setup lost." **You** telling me *why* it lost is what
changes a rule.

---

## Template

```markdown
## Week ending YYYY-MM-DD

### 1. Would you have taken it?
The paper book takes every approved signal. You would not have.
| Signal ID | Would you take it? | Why not |
|-----------|--------------------|---------|
| a1b2c3    | yes                | — |
| d4e5f6    | no                 | H4 still bearish, M15 CHoCH looked like noise |

### 2. Loss post-mortems
For each loser, pick ONE. Be blunt.
- **Thesis wrong** — the read was bad. What did I miss?
- **Level wrong** — the direction was right, the entry or stop was not.
- **Variance** — good process, bad outcome. No change needed.

| Signal ID | Verdict | What the features missed |
|-----------|---------|--------------------------|
| a1b2c3    | thesis  | H4 was still bearish; M15 CHoCH was noise |

### 3. Macro readings (I cannot fetch these)
- DXY: level, direction over the week
- US 10y real yield: level, direction
- VIX / risk tone: risk-on or risk-off
- Anything geopolitical actually moving gold

### 4. GBPUSD rate — nothing for you to do any more
The bridge now reads GBPUSD from MT5 at the same time as the candles and writes
it to `data/fx.json`, so the rate arrives with the prices. Nothing to fill in.

What to check instead: if `python -m gold_trader status` prints a line starting
`FX WARNING`, say so in the review. It means one of three things — the bridge is
not running, your MT5 has no GBPUSD symbol, or the rate it returned was so far
from the static fallback that it was refused as a misread symbol. In all three
cases the system keeps the last documented static rate (which only scales
displayed cash — R is unaffected), but a warning that persists for a week
usually means the bridge stopped.

### 5. Broker reality (for cost-adjusting the paper results)
- Typical XAUUSD spread this week: ___
- Typical spread around news: ___
- Commission per lot, if any: ___
(Only needs restating when it changes. Paper R ignores all of it, so this is how
we find out what the edge would survive.)

### 6. Calendar
- Confirmed CPI/PCE/PPI dates for the next 3 weeks
- Anything unscheduled that moved gold

### 7. Your call
- Setups that felt right but the engine refused — which, and why you disagreed
- Setups the engine allowed that you'd have skipped
- Anything about AURUM's reasoning that read as wrong or lazy
```

---

## What I do with it

| Your input | What changes |
|---|---|
| Would you have taken it | A signal you'd have skipped is flagged; a pattern of skips is a rule the system is missing |
| Loss post-mortems | `thesis` losses drive prompt/rule changes; `variance` changes nothing, deliberately |
| Macro readings | Written into `state/calendar.json` as readings the analyst sees |
| A persistent `FX WARNING` | I chase the bridge or the MT5 symbol name; the static rate is only a floor, not a plan |
| Broker reality | Cost-adjusted expectancy reported alongside raw paper R |
| Calendar | Blackout windows become accurate instead of `derived_only` |
| Your call | Disagreements are logged; three of the same disagreement is a rule change |

## The one rule

**Don't let me change a rule off a single trade.** If you tell me a setup is
broken after two losses, I should push back and say the sample is too small —
and if I don't, push back on me. The whole design of the learning loop is that it
refuses to move on small samples. The weekly review must hold the same line, or
it becomes the hole through which curve-fitting gets in.
