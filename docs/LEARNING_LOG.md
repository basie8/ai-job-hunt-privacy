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

## 2026-09-17 — Fixed-fractional sizing, and a whole CLI that never ran

**Evidence:** 0 closed trades. Two configuration changes and one defect found
while making them.

**Change 1 — sizing is now a percent of current equity.** Risk per trade moved to
1.00% of *equity* (starting notional plus realised P&L), from a flat percent of
the starting notional. After a loss the next trade risks slightly less; after a
win, slightly more. R is untouched: every trade still risks exactly 1R by
definition, so the journal's arithmetic and the whole track record are unaffected
— only the cash figures compound.

This needed a companion. Fixed-fractional sizing never mathematically reaches
zero: a ruined book keeps trading forever in ever-smaller size, and the record
fills with trades that mean nothing. Added a hard `EQUITY_FLOOR` breach at 60% of
the starting notional. It is a *hard* breach, not a warning, because the failure
it prevents is a slow one that nobody notices.

**Change 2 — GBPUSD comes from MT5 now.** The rate was hardcoded with a dated
provenance string and a line in the weekly review asking Pieter to refresh it.
The terminal already had the number. The bridge now reads GBPUSD at the same time
as the candles and writes `data/fx.json`; the pipeline prefers it.

Three ways that can go wrong, all handled as *visible* fallbacks rather than
silent ones: no file (bridge not running) → static rate plus `FX WARNING`; a rate
more than 15% from the static one → refused as a misread symbol, because MT5
symbol resolution landing on the wrong instrument would silently rescale the
entire book; a rate older than 36h → used anyway, but warned about, since an old
real rate still beats a hardcoded one.

**Defect found: `_config()` in the CLI raised `TypeError` on every single
command.** Last session's rename turned `account_usd` from a field into a
property. The CLI still passed it as a constructor keyword. Every command —
`signal`, `status`, `learn`, `doctor`, `calendar` — crashed on the first line.
290 tests were green throughout.

The tests exercised the pipeline and the risk engine directly, never through the
entry point a human actually types. The whole system was unusable and the suite
reported perfect health. Two guards added: a test that every `cmd_*` function can
build its config, and a self-check on the same. The self-check matters more — it
runs on the schedule, against the shipped code.

The recurring lesson gets a second clause. Degraded input must increase scrutiny
— and *a test that never crosses the boundary a human crosses is not testing the
system they use*.

**Hypotheses affected:** none. No trading evidence in this entry.

---

## 2026-09-17 — A run that never happened

**Evidence:** one Routine run, rejected in five seconds.

The 17:23 signal run failed with `You've hit your session limit · resets 5:30pm
(UTC)`. Not a code fault — the account's usage limit, hit while a foreground
session was working. It was found by hand, while answering a question about
whether notifications were configured. Nothing in the system had noticed.

**Why it was invisible.** The run died before `git pull`. It wrote no journal
entry, no audit-log line, no commit, and produced nothing to notify about. The
only trace it left anywhere was the absence of a trace. The dashboard would have
aged past 26 hours and turned red eventually, but only if the outage lasted a
day; a handful of lost runs inside a day would have gone unremarked entirely.

Every failure detector in this system to date watches *output*: a stale claim, a
failing check, an old candle. None of them could see a run that produced no
output at all. Absence has to be measured against an expectation, and the
expectation — the schedule — lived only on the Routine, outside the repo.

**Change.** Every run now records a heartbeat before it finishes, on every path,
including the paths that produce nothing else. The detector compares the
schedule against the record; a scheduled slot with no beat inside its grace
window is a run that never happened.

Two design decisions are worth stating because both were tempting to get wrong:

*Detection reads the repo, not the API.* The Routines API knows **why** a run
failed and is genuinely better evidence — but a detector that depended on it
would go blind in exactly the sessions where the tool might be unavailable.
Expected-versus-recorded needs a clock and a file. The API is an enrichment, and
the audit prompt says to note its absence rather than guess.

*The detector refuses to speak about time it was not watching.* The first
implementation reported every scheduled run since the beginning of the window as
missed, because none of them had heartbeats — nine false alarms on the first
run. A detector that cries wolf on day one is worse than no detector: it teaches
you to ignore the channel before it has ever been right. It now reports "not
armed" until the first heartbeat lands.

**The general lesson**, and the third clause on the standing one: *a system can
only detect failures in the things it produces. To detect a failure to produce
anything, something must independently know what was expected.*

### Found the same day: the state directory was gitignored

Chasing the first defect turned up a worse one. `gold_trader/state/*.jsonl` was
in `.gitignore`, so the journal, the audit log and the brand-new heartbeat could
never be committed. Every `git add gold_trader/state/` in both scheduled
Routines had been a silent no-op since the day they were written.

Containers are ephemeral. `RUNTIME.md` states it plainly — "the repository is
the only durable store in this system" — and the `.gitignore` quietly
contradicted it. Nothing failed, nothing warned. The first signal would have
been journalled, committed to nothing, and gone. The journal would have read
zero trades forever; the learning loop could never have left cold start no
matter how many months it ran; LRN-03 was unreachable by construction. The
system would have looked healthy the entire time, because every check it had
was measuring things that were working.

It was invisible for the same reason as the missed run: **the absence of an
effect looks exactly like a thing that has not happened yet.** An empty journal
during cold start is the expected state, so an empty journal that can never fill
is indistinguishable from it — until something asks whether the write could have
worked at all, which nothing did.

Removed the pattern, with the reasoning written into `.gitignore` itself so
nobody re-adds it in good faith. Guarded by a self-check and a test that run
`git check-ignore` against every state path.

**Hypotheses affected:** none. No trading evidence in this entry.

---

## 2026-09-17 — The pipeline has never run

**Evidence:** the 19:23 signal run, which reported `no Anthropic credentials in
env` and recorded an `error` heartbeat.

The four stages call the Anthropic API directly. That needs a credential of
their own, and a Claude Code session does not provide one: the session
authenticates through the claude.ai subscription, which covers the agent
*driving* the run but is invisible to the pipeline it invokes. Every scheduled
signal run since the Routines were created has failed at the first model call.

**So the journal is empty for two reasons, not one.** It is early — but also the
pipeline has never once completed. I had been attributing the empty journal and
empty audit log entirely to cold start, which was the available explanation and
happened to be true on its own terms. It was not the whole truth, and nothing
distinguished the two until a run finally reported why it stopped.

That is the same shape as the two defects found earlier today, for the third
time: **an expected-looking absence concealing a different cause.** An empty
journal during cold start looks exactly like an empty journal that can never
fill — whether the cause is a gitignore rule, a run that never started, or a
pipeline that cannot authenticate. The run record is what separated them here,
which is the first return on having built it.

**Two fixes, neither of which supplies the key** — that part needs a human:

*The failure now arrives early and explains itself.* The SDK constructs happily
without credentials and raises `TypeError` from inside `_validate_headers` on
the first request, so the error surfaced late and named a header problem rather
than a missing key. `signal` now checks the resolved credential before doing any
feature work and prints what to do about it.

*Verified rather than assumed.* The failing run reported the TypeError as coming
from "client construction before any model call". It does not — construction
succeeds. Writing the guard against that description would have put it in the
wrong place, and it would have passed review while catching nothing. There is
now a test that asserts the SDK constructs without credentials, so if a future
version starts failing earlier, the guard's placement is re-examined rather than
silently redundant.

**Also worth recording:** the run that found this reported it. Push reached the
phone with the error text. The heartbeat it wrote was lost, because that run
predated the gitignore fix by six minutes — but the alert arrived, which is the
first time the notification path has done its actual job.

**Hypotheses affected:** none. Still no trading evidence, and now a documented
reason why there is none.

---

## 2026-09-17 — Gold is not open all the time

**Evidence:** Pieter, unprompted: *"XAUUSD closed between 21:00 - 22:00 UTC."*

Domain knowledge the system did not have, and it invalidated three things at
once.

**The last scheduled run of the day fired inside the close.** The signal Routine
ran at 21:23 UTC, in the middle of the daily rollover. It could never have
produced a tradeable signal. Worse, once the run detector shipped this
afternoon, that slot would have been reported as a missed run *every single
evening* — a false alarm on a schedule, which is precisely how a real alert gets
learned into background noise. Schedule now ends at 19:23.

**The weekend was advice, not a rule.** `is_weekend` existed and fed a line into
the analyst's prompt. The risk engine — the part that actually enforces — had no
concept of a closed market at all. Nothing but the analyst's judgement stopped a
signal being issued into a shut market. That is backwards for this system, whose
whole design is that models advise and code decides. `MARKET_CLOSED` is now a
hard breach covering both closures.

**And candle freshness was judged against the wall clock.** Over a weekend a
perfectly healthy bridge delivers nothing for 48 hours, so DAT-04 and SMC-03
would have reported as stale claims every Saturday. Freshness is not judged
while the market is shut; a bridge that dies during a closure is undetectable
until the reopen anyway, because no candle is expected either way.

**The correction I made to the correction.** 21:00–22:00 UTC is right today and
wrong from November: the close is anchored to 17:00–18:00 *New York*, so the UTC
hour shifts with US daylight saving. Implemented in ET through `zoneinfo`, like
the killzones already were, and the self-check verifies the schedule clears the
break in both summer and winter. Taking the reported UTC hours literally would
have produced a bug that surfaced once, in November, and looked like nothing.

**The pattern, for the fourth time today:** *an absence that looks expected.* No
signals in the evening looked like a quiet market. No candles at the weekend
looked like a quiet market. Neither was — one was a run that could never work,
the other a detector about to cry wolf. Every instance today has been something
the system could not distinguish from normal, and every one was found by
something outside the system: a user's domain knowledge, a failed run's error
text, a dirty git tree.

**Worth stating plainly:** this came from Pieter, not from the code, the tests or
the audits. None of them could have found it — they all encode the same
assumption. The weekly review exists for exactly this, and this is the first
time it has paid.

**Hypotheses affected:** none directly. H1 (stop band) gains a caveat: ATR
computed across a rollover gap spans a discontinuity, so evening H1 readings may
overstate volatility. Worth checking once there are closed trades.

---

## 2026-09-17 — Telling a dead feed from a quiet one

**Evidence:** a four-hour gap in the `market-data` branch (18:39 to 22:43 UTC)
with the Windows PC on throughout, and no way to say what caused it.

The bridge only commits when candle content changes. So a terminal that has
dropped its broker connection and a market that simply is not moving produce the
identical artefact: a bridge that runs every fifteen minutes, finds nothing new,
and pushes nothing. From GitHub the two are indistinguishable. I guessed at the
cause in conversation, which was the wrong thing to do — the right thing was to
make the system able to answer.

**Change:** the bridge now writes `data/bridge.json` every run, carrying the
terminal's connection state, server, ping and build.

**The design decision worth recording: the bridge reports and the pipeline
judges.** The obvious implementation puts the verdict in the bridge — it has the
connection state right there. But whether a disconnection matters depends on
gold's trading hours, and the bridge runs on Windows where `zoneinfo` falls back
to a `tzdata` package that may not be installed. A verdict computed there would
be wrong in exactly the timezone-sensitive way this project has already been bitten
by twice today. Facts travel; judgement stays where the domain knowledge is.

**And the judgement needed Pieter's correction to be right at all.** My first
instinct was that a disconnected terminal is a fault. He said: *"terminal
disconnects from broker when market is closed."* Under the obvious rule this
system would have paged him every single evening and twice at weekends — a false
alarm on a schedule, for the third time today. Disconnection is only a finding
while the market is open.

One further distinction fell out of it: a *stale status file* means the bridge
process is not running, which is a different failure from a dropped link and
outranks it, because a stale file's `connected` flag describes a moment that has
passed. That also gives the bridge a liveness proof independent of whether any
candle moved — the file is rewritten every run regardless.

**The running lesson, fifth instance:** every defect today has been an absence
that looked expected. What is new here is the fix's shape. The earlier ones were
answered by recording more (a heartbeat, a run record). This one needed
recording *and* a rule for reading it, and the rule came from the user, not the
code. A system cannot infer which absences are normal in a domain it only sees
through data.

**Hypotheses affected:** none. No trading evidence.

---

## 2026-09-18 — First closed trade

**Evidence:** 1 closed trade (paper). Long `ob_retest`, entry 4353.00, stop
4339.50, target 4374.00 (R:R 1.56), conviction 0.30 (cold-start clamp).
Signalled 00:37 UTC, filled 00:45, stopped out 03:15 at 4339.50. Result
-1.00R. MFE +0.94R before reversing; MAE -1.39R (the simulated fill's
intra-candle excursion ran past the eventual stop print, which is normal for
worst-case-in-candle resolution and not itself a defect). This is a paper
result — no order was placed, and the fill and stop-out are both simulated
against the candles that followed the signal.

**Observation:** the trade got most of the way to target (+0.94R) before
giving it back and hitting the stop. One trade proves nothing about whether
that pattern (a good excursion that reverses) is real or noise — it needs a
real sample.

Calibration on this single trade: stated conviction 0.30 vs realized outcome
0 (loss), Brier 0.090, nominally "overconfident by 0.30." This is n=1 and is
recorded only because the dashboard and `gold_trader learn` compute it either
way — it is not evidence for or against H5 and must not be read as such
until the 20-trade floor.

**Change:** none. LRN-03 (first 20 closed trades) is now at 1/20 and
genuinely accumulating — this is the first evidence Phase 2 is moving, not
just configured to move.

**Hypotheses affected:** none confirmed or contradicted. Sample is 1;
the floor for any read is 20 (H1-H6) or 40-60 (setup-level, hillclimb). Noted
here only because "first closed trade" is itself the milestone.

---

## Template for future entries

```markdown
## YYYY-MM-DD — <short title>

**Evidence:** n closed trades, <statistic>
**Observation:** what the data actually showed
**Change:** what was altered in code/prompt/limits, or "none — sample too small"
**Hypothesis affected:** H<n>, confirmed / contradicted / still open
```
