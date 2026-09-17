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

**Closed trades: 0.** Phase 2 of `DEVELOPMENT_PLAN.md` — the bridge is live as
of 2026-09-17 and signals are now accumulating. The learning loop is at cold start. Every statement below
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

## 2026-09-17 — First real gold data. Two bugs, one hypothesis contradicted.

**Evidence:** 500 H1 bars (2026-08-19 to 2026-09-17), 400 H4, 500 M15, from
Pieter's live MT5 feed. Spot 4362.10. Still zero closed trades — this is a
measurement of the *detectors*, not of any edge.

### The bridge worked, then didn't

The `market-data` branch appeared on the first attempt, with paths
`"data\r/XAUUSD_h1.csv\r"`. Carriage returns baked into the git tree.

**Cause:** `subprocess.run(..., text=True)` translates `\n` to `\r\n` when
writing a child's stdin **on Windows**. `git mktree` reads one entry per line and
took the stray `\r` as part of each filename. Every Linux test passed; the bug
only exists on the platform the bridge actually runs on.

**Change:** stdin is now sent as raw bytes, `_mktree` refuses any entry
containing a line break, and three regression tests assert the call shape rather
than the platform behaviour. The already-pushed branch was repaired from here.

**Lesson worth keeping:** a test suite that runs only on the developer's platform
cannot cover a cross-platform boundary. The guard had to move from *the output*
to *the call*.

### H-SMC-1 (zone count) — CONTRADICTED, and that is good news

The open worry was that live gold would generate so many order blocks and fair
value gaps that the analyst's prompt would become noise. Measured:

| TF | bars | FVGs found | unmitigated | OBs found | unmitigated |
|---|---|---|---|---|---|
| H4 | 400 | 97 | **5** | 131 | **0** |
| H1 | 500 | 115 | **5** | 183 | **13** |
| M15 | 500 | 104 | **5** | 181 | **7** |

The mitigation filter does the whole job: ~100 zones collapse to a handful, and
the display cap of 6 is rarely reached. **No significance filter is needed for
zones.** The concern was misplaced.

### New concern: structure events are far too frequent

183 BOS/CHoCH events across 500 H1 bars is **one structural break every 2.7
bars**. Structure that changes every three candles is not structure. This traces
to swing sensitivity: `lookback=2` produces 24–27 swings per 100 bars on every
timeframe, so the break detector re-arms almost immediately.

**Consequence for H6** (structural alignment predicts outcomes): both alignment
readings currently say "conflicted", and with breaks this frequent that may be
noise rather than signal. H6 is not yet testable in a meaningful way.

**Change:** none to the detector — that is a larger change than a live-data
observation justifies, and there are no closed trades to validate it against.
Logged as roadmap **SMC-04**.

### Bug: duplicate order blocks

Consecutive structure breaks often resolve to the same preceding candle, so the
same zone was emitted twice — visible in the prompt as the identical OB listed
back to back. One zone reading as two confirmations is worse than a wasted line.
Deduplicated on (kind, direction, top, bottom).

### H1 (stop band) — partially answered, and a mis-calibration found

Real ATR by timeframe, with the stop range the 0.6x–3.0x band permits:

| TF | ATR14 | as % of spot | permitted stop | as % of spot |
|---|---|---|---|---|
| M15 | $8.81 | 0.202% | $5.29–$26.43 | 0.121%–0.606% |
| H1 | $20.40 | 0.468% | $12.24–$61.20 | 0.281%–1.403% |
| H4 | $41.54 | 0.952% | $24.92–$124.61 | 0.571%–2.857% |

The ATR band itself looks sane. But the **percent-of-spot fallback** — added last
audit for when ATR is unavailable — was set to 0.12%–0.60%, calibrated against
synthetic data whose ATR was tiny. That ceiling happens to match M15 almost
exactly and would have **refused every legitimate H1 stop**, and every H4 one.

**Change:** fallback band widened to 0.12%–1.50%, covering M15 through H1. H4
swing stops stay outside it deliberately — a multi-day stop should not be set
from a screenshot, which is the only path where the fallback applies.

This is a widened bound, so stating the reasoning explicitly: the ATR band is the
primary check and is unchanged; the fallback exists to *approximate* it when ATR
is missing, and it demonstrably did not. Correcting an approximation to match its
target is not the same as relaxing a limit.

**Hypotheses affected:** H-SMC-1 contradicted (no filter needed). H1 still open —
the band looks plausible but needs MAE data from closed trades. H6 now doubtful
for the reason above.

---

## Template for future entries

```markdown
## YYYY-MM-DD — <short title>

**Evidence:** n closed trades, <statistic>
**Observation:** what the data actually showed
**Change:** what was altered in code/prompt/limits, or "none — sample too small"
**Hypothesis affected:** H<n>, confirmed / contradicted / still open
```
