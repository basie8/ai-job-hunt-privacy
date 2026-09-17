# Weekly review

**This is the highest-value thing you do for the system.** Everything else is
automated; this is the input only you can supply.

Cadence: once a week, ~15 minutes. Paste the filled template into a session and
say "weekly review". I update the journal, the learning log and the roadmap from it.

---

## Why this matters more than the automation

The journal knows what the pipeline *proposed*. It does not know:

- which signals you actually took, and at what fill
- why you skipped one, or overrode one
- whether a loss was a bad thesis, bad execution, or ordinary variance
- what the spread and slippage actually cost you
- what you saw on the chart that the computed features missed

That last category is the one that improves the system permanently. A losing
trade tells the learning loop "this setup lost." **You** telling me *why* it lost
is what changes a rule.

---

## Template

```markdown
## Week ending YYYY-MM-DD

### 1. Signals vs. reality
| Signal ID | Took it? | Actual fill | Actual exit | Why deviated |
|-----------|----------|-------------|-------------|--------------|
| a1b2c3    | yes      | 4312.80     | 4296.00     | slipped 0.30 on entry |
| d4e5f6    | no       | —           | —           | didn't like the H4 context |

### 2. Loss post-mortems
For each loser, pick ONE. Be blunt.
- **Thesis wrong** — the read was bad. What did I miss?
- **Execution wrong** — the read was fine, the entry/stop/timing was not.
- **Variance** — good process, bad outcome. No change needed.

| Signal ID | Verdict | What the features missed |
|-----------|---------|--------------------------|
| a1b2c3    | thesis  | H4 was still bearish; M15 CHoCH was noise |

### 3. Macro readings (I cannot fetch these)
- DXY: level, direction over the week
- US 10y real yield: level, direction
- VIX / risk tone: risk-on or risk-off
- Anything geopolitical actually moving gold

### 4. Broker reality
- Typical XAUUSD spread this week: ___
- Worst slippage seen: ___
- Commission per lot: ___
(Only needs restating when it changes. It shifts real R.)

### 5. Calendar
- Confirmed CPI/PCE/PPI dates for the next 3 weeks
- Anything unscheduled that moved gold

### 6. Your call
- Setups that felt right but the engine refused — which, and why you disagreed
- Setups the engine allowed that you'd have skipped
- Anything about AURUM's reasoning that read as wrong or lazy
```

---

## What I do with it

| Your input | What changes |
|---|---|
| Signals vs. reality | Journal outcomes corrected to *your* fills, not theoretical ones |
| Loss post-mortems | `thesis` losses drive prompt/rule changes; `variance` changes nothing, deliberately |
| Macro readings | Written into `state/calendar.json` as readings the analyst sees |
| Broker reality | Risk limits and minimum reward:risk re-tuned to real costs |
| Calendar | Blackout windows become accurate instead of `derived_only` |
| Your call | Disagreements are logged; three of the same disagreement is a rule change |

## The one rule

**Don't let me change a rule off a single trade.** If you tell me a setup is
broken after two losses, I should push back and say the sample is too small —
and if I don't, push back on me. The whole design of the learning loop is that it
refuses to move on small samples. The weekly review must hold the same line, or
it becomes the hole through which curve-fitting gets in.
