# AURUM roadmap and task audit

Status here is **verified, not asserted**. Every row carries a machine-checkable
predicate, and `python -m gold_trader progress` re-evaluates it against the
repository. A row marked `done` whose check fails is reported as a **STALE
CLAIM** — that is the point, because a progress doc that only self-reports is
the easiest thing in the world to fool yourself with.

```bash
python -m gold_trader progress           # roadmap audit (verifies each claim)
python -m gold_trader selfcheck          # component audit (errors, placeholders, drift)
python -m gold_trader progress --json    # machine readable
```

Statuses: `done` · `in_progress` · `outstanding` · `blocked`

---

## Infrastructure

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| INF-01 | Four-stage pipeline with tiered models | done | `file:gold_trader/pipeline.py` | Opus 5 / Opus 5 max / Sonnet 5 / Haiku 4.5 |
| INF-02 | Hash-chained audit log | done | `file:investment_pipeline/audit.py` | Tamper-evident, verifiable |
| INF-03 | Deterministic risk engine | done | `file:gold_trader/risk.py` | Size from stop distance, never from a model |
| INF-04 | Schema-constrained stage outputs | done | `file:gold_trader/schemas.py` | All four stages |

## Market data

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| DAT-01 | Feed adapters (CSV / inline / manual / http) | done | `file:gold_trader/feed.py` | HttpFeed refuses rather than guessing |
| DAT-02 | MT5 bridge | done | `file:gold_trader/bridge/mt5_export.py` | Plumbing-only push, never touches your tree |
| DAT-06 | Windows install kit | done | `files:gold_trader/bridge/windows_kit/SETUP.bat,gold_trader/bridge/windows_kit/README.txt` | Zip with one-click setup; needs no clone of the project |
| DAT-03 | market-data branch sync | done | `file:gold_trader/sync.py` | Round-trip tested over real git repos |
| DAT-08 | Terminal link state reported and judged | done | `file:gold_trader/bridge_status.py` | Bridge writes `data/bridge.json`; disconnection only a fault while the market is open |
| DAT-07 | GBPUSD sourced from MT5 | done | `file:gold_trader/fx.py` | Bridge writes `data/fx.json`; a missing or absurd rate falls back loudly |
| DAT-04 | Bridge running on Pieter's machine | done | `data:180` | Confirmed 2026-09-17: market-data branch live, newest bar minutes old |
| OPS-08 | Anthropic API key in the cloud environment | outstanding | `manual` | **Needs you.** Without it the four stages cannot run at all — see docs/INSTALL.md part 2 |
| DAT-05 | Live vendor feed (egress + key) | outstanding | `manual` | Optional. Only if you want runs independent of your PC being on. |

## Structure and context

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| SMC-01 | CHoCH / BOS / OB / FVG / sweeps | done | `file:gold_trader/smc.py` | One documented interpretation, computed identically each run |
| SMC-05 | Market hours enforced, not advised | done | `file:gold_trader/sessions.py` | Weekend + daily rollover are a hard MARKET_CLOSED breach; DST-correct via New York |
| SMC-02 | Sessions, killzones, session ranges | done | `file:gold_trader/sessions.py` | DST-correct via zoneinfo |
| SMC-03 | Detectors validated against real gold data | done | `data:180` | Run against real XAUUSD 2026-09-17; findings in LEARNING_LOG |
| SMC-04 | Significance filter for structure events | outstanding | `manual` | 183 BOS/CHoCH per 500 H1 bars is too frequent to mean much |
| MAC-01 | Event calendar with blackout windows | done | `file:gold_trader/macro.py` | NFP/claims derived; FOMC/CPI/PCE from file |
| MAC-02 | Calendar file filled through year-end | outstanding | `file:gold_trader/state/calendar.json` | **Needs you.** CPI/PCE dates from BLS/BEA. |
| MAC-03 | DXY / real-yield / VIX readings supplied weekly | outstanding | `manual` | **Needs you.** Weekly review covers this. |

## Learning loop

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| LRN-01 | Journal with feature snapshots | done | `file:gold_trader/journal.py` | Pessimistic same-bar resolution |
| LRN-02 | Calibration and per-setup clamps | done | `file:gold_trader/learning.py` | Can only reduce risk, never increase |
| LRN-03 | First 20 closed trades | blocked | `journal:20` | Unblocked by DAT-04; now accumulating |
| LRN-04 | Learning state leaves warm-up | blocked | `learning:active` | Clamps stay inert until LRN-03 |
| LRN-05 | Setup taxonomy validated against real outcomes | outstanding | `journal:40` | Some setups may prove undetectable or useless |

## Operations

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| OPS-01 | Signal Routine (2-hourly, weekdays) | done | `routine` | trig_01D5MB5sgfneCfBgVGrjACfb |
| OPS-02 | Progress Routine (12-hourly) | done | `routine` | Reports this audit |
| OPS-03 | Weekly review cadence running | outstanding | `manual` | **Needs you.** Template: docs/WEEKLY_REVIEW.md |
| OPS-04 | Risk limits tuned to the account | done | `file:gold_trader/risk.py` | GBP 10,000 @ 1% of **current equity**, 60% ruin floor |

## Quality

| ID | Task | Status | Verify | Notes |
|----|------|--------|--------|-------|
| TST-01 | Gold test suite | done | `tests:tests_gold:360` | Offline, no network |
| TST-02 | Pipeline test suite | done | `tests:tests:44` | Offline, no network |
| TST-03 | Component self-check | done | `file:gold_trader/selfcheck.py` | Placeholders, config coherence, cross-artifact drift |
| TST-04 | Config coherence checks | done | `file:gold_trader/config_checks.py` | Limits that contradict each other |
| EVL-01 | Backtest harness over historical candles | outstanding | `file:gold_trader/backtest.py` | Would let setups be scored before risking money |
| EVL-02 | Prompt hillclimb against the journal | outstanding | `journal:60` | Needs a real sample first |
| DOC-01 | AURUM operating doc wired to the prompt | done | `file:docs/AURUM.md` | Editing it changes how the analyst thinks |
| DOC-02 | Phased development plan | done | `file:docs/DEVELOPMENT_PLAN.md` | Machine-checkable gate per phase |
| DOC-03 | Runtime topology documented | done | `file:docs/RUNTIME.md` | Where each component runs and how it fails |
| DOC-04 | Full installation guide | done | `file:docs/INSTALL.md` | Start-to-finish, Windows side |
| OPS-05 | Live operations dashboard | done | `file:gold_trader/dashboard_html.py` | Republished by both Routines |
| OPS-07 | Runs that never happen are detected | done | `file:gold_trader/heartbeat.py` | Every run records a heartbeat; `gold_trader runs` finds the gaps. Built after a usage-limit rejection went unnoticed |
| OPS-06 | Paper mode stamped end to end | done | `file:gold_trader/config_checks.py` | Only 'paper' is a valid mode |

---

## The critical path

Everything blocked traces to one row: **DAT-04**. Until the bridge pushes
candles, the pipeline has nothing to read, the journal stays empty, the learning
loop stays at cold start, and the SMC detectors remain unvalidated against real
gold.

No amount of conversation substitutes for that. It is roughly ten minutes of
setup on your side.
