# Learning log

Append-only record of what has actually been learned and what changed as a
result. Distinct from the journal (per-trade outcomes) and the roadmap (task
status). This is the *why*.

Rules for entries:

- Every change cites its evidence — a sample size, a statistic, or a named observation.
- "Felt wrong" is not evidence. It can be a hypothesis, logged as such.
- Hypotheses stay hypotheses until a sample tests them.
- Nothing is removed. Superseded entries are marked, not deleted.

---

## Current state

**Closed trades: 0.** Phase 1 of `DEVELOPMENT_PLAN.md`, blocked on the bridge.
The learning loop is at cold start. Every statement below
is a hypothesis carried in from design, not a measured finding. Nothing here has
earned its place yet.

---

## 2026-09-17 — Baseline established

**What was built:** four-stage pipeline, deterministic risk engine, SMC structure
detection, session/killzone context, macro blackouts, journal with calibration
and per-setup clamps.

**Design hypotheses now in force** (all untested against real gold):

| # | Hypothesis | How it will be tested |
|---|---|---|
| H1 | Stops between 0.6x and 3.0x ATR avoid both noise-stops and unjustifiable risk | Distribution of MAE in R across 40+ closed trades |
| H2 | A 1.5 minimum reward:risk is achievable on gold without starving the sample | Fraction of signals refused on RR alone |
| H3 | The stated setup taxonomy maps to real, distinguishable edges | Per-setup expectancy separating after 40+ trades |
| H4 | 60min/30min event blackout is the right width for gold | Adverse excursion on trades held through releases |
| H5 | The analyst will be overconfident and need shrinking | Calibration curve after 20+ trades |
| H6 | Structural alignment across H4/H1/M15 predicts better outcomes | Win rate split by `smc_alignment` at entry |

**Known weaknesses, stated now so they are not discovered as surprises:**

- SMC detectors have only run on synthetic random walks. Their behaviour on real
  gold — particularly how many order blocks and FVGs a live session generates —
  is unknown. If they produce 40 zones per run, the prompt becomes noise.
- The swing `lookback=2` fractal is arbitrary. It may be too sensitive on M15.
- Session ranges assume the loaded candles cover the session. With 240 M15 bars
  (~60 hours) that holds; with fewer it silently returns nothing.
- `event_fade` and `range_fade` may prove undetectable without discretion.

**Corrections made during the build** (found by tests, not by review):

1. Snapshot staleness measured against wall clock rather than the run clock —
   made replays non-reproducible.
2. Data-freshness check compared file sizes; a new bar usually has the same byte
   count, so real updates reported as "already current".
3. The bridge's first implementation left the user's repo checked out on the data
   branch. Rewritten to use git plumbing and touch nothing.
4. The roadmap auditor recursed into its own test suite — 447 processes spawned
   before it was caught. Guarded.
5. Tasks marked done with an unverifiable predicate vanished from the audit report
   entirely. Now surfaced in their own section.

---

## 2026-09-17 — Component audit: three defects, all the same shape

**Evidence:** static analysis plus a probe of every documented entry point. No
trades involved — this is a code audit, not a trading finding.

**Observation:** three defects, and all three shared a failure pattern worth
naming, because it will recur.

| # | Defect | Why it mattered |
|---|---|---|
| 1 | With no ATR available, the stop-width check silently disappeared | A 10-cent stop on $4305 gold was **approved at 5000oz**. Spread alone would have taken it out. The least reliable input path had the fewest checks. |
| 2 | A malformed `state/calendar.json` raised `JSONDecodeError` and killed the whole run | That file is hand-edited weekly, so it *will* be malformed eventually. A typo would have silently stopped every scheduled signal. |
| 3 | An event row missing a key raised `KeyError` | Same cause, same consequence, from one bad line in an otherwise fine file. |

**The pattern:** *degraded input reduced scrutiny instead of increasing it.* Less
data meant fewer gates, and a hand-edited file was trusted to be well-formed.
Both are backwards.

**Change:**
- Stop width now falls back to a percent-of-spot band (0.12%–0.60%) when ATR is
  unavailable, and is a **hard block** when neither ATR nor spot exists.
- Calendar loading degrades per-row: a bad event is dropped and recorded, the
  derived NFP/claims events survive, confidence reports `invalid`, and the parse
  errors reach the analyst prompt, the risk engine and the audit log.
- Added `gold_trader/selfcheck.py` (20 checks) and `config_checks.py` to catch
  this class mechanically: placeholders in shipped source, limits that contradict
  each other, and cross-artifact drift between code and docs.
- 25 regression tests in `tests_gold/test_degradation.py`.

**Hypothesis affected:** none of H1–H6. This was a robustness finding, not a
market one. H1's stop band is now enforced through two measures rather than one,
which makes it *more* testable, not less.

**Also found and fixed:** the self-check flagged itself (it grepped for the word
`NotImplementedError`, which its own source contains); dead code in
`build_features`; eight unused imports.

**Standing lesson for future audits:** probe the *degraded* paths, not the happy
one. All three defects sat on paths that only execute when something is already
missing — which is exactly when a wrong answer does the most damage.

---

## Template for future entries

```markdown
## YYYY-MM-DD — <short title>

**Evidence:** n closed trades, <statistic>
**Observation:** what the data actually showed
**Change:** what was altered in code/prompt/limits, or "none — sample too small"
**Hypothesis affected:** H<n>, confirmed / contradicted / still open
```
