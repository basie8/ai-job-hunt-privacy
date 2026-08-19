# Audit tooling

There is no MetaTrader in CI, so these two scripts enforce what a compiler and a
careful reviewer would otherwise catch. Run both from the repository root before
every commit that touches the EA.

```
python3 tools/audit_static.py
python3 tools/audit_api.py
python3 tools/simulate_exits.py
python3 tools/simulate_riskguard.py
python3 tools/simulate_confluence.py
```

Both exit non-zero on any finding.

## audit_static.py

| Check | Catches |
|---|---|
| placeholder | TODO/FIXME/STUB markers, empty function bodies |
| balance | unbalanced braces, parens, brackets (string- and comment-aware) |
| encoding | non-ASCII bytes that a heredoc or paste may have introduced |
| inputs | duplicate input names, and inputs declared but never referenced |
| methods | class methods declared in a header but never defined |
| deadcode | free functions defined but never called |
| presets | `.set` keys that are not real EA inputs, duplicates, malformed lines |
| includes | missing include targets, headers without an include guard |

## audit_api.py

Verifies argument counts for every MQL5 built-in the EA calls against the
documented signature — 64 distinct functions. Catches the class of error where a
call looks plausible but has the wrong arity.

## What these do NOT check

They are not a compiler. They cannot verify type correctness, MQL5-specific
semantics, or that the strategy is profitable. Compiling in MetaEditor and
working through the validation protocol in `docs/STRATEGY.md` §9 remains
mandatory before risking money.

## simulate_exits.py

A faithful port of `CTradeExecutor::Manage()` run over synthetic price paths.
Verifies the exit engine produces the documented R-multiple distribution
(−1.00R / +0.55R / +2.00R) and asserts two invariants over 16,000 randomised
paths, in both directions and with the breakeven modify both succeeding and
failing:

- no outcome is ever worse than −1.00R;
- no position is ever scaled out more than once.

Run it after any change to `TradeExecutor.mqh`. It caught a real defect: the
partial and the breakeven shared a stage, so a broker rejecting the stop modify
left the stage unadvanced and the next tick took another partial — scaling the
position out of existence one tick at a time.

## make_optimisation_sets.py

Generates **every** `.set` file in `MQL5/Presets/` — the three phase presets, the
five staged optimisation sweeps, and the timeframe and exit-structure comparison
runs — from the EA's compiled defaults plus a small table of deliberate
overrides per file.

    python3 tools/make_optimisation_sets.py            # regenerate
    python3 tools/make_optimisation_sets.py --check    # fail if any file is stale

**Never hand-edit a `.set` file.** The phase presets used to be maintained by
hand and they drifted: after the exit geometry was retuned, `Phase1_Challenge.set`
still pinned the old 1.6 ATR stop and 3.0R target, so loading it silently
restored the configuration that had produced a losing backtest. Deriving them
from the EA defaults makes that class of bug impossible, and `--check` (wired
into `audit_static.py`) fails the build if anyone edits one by hand.

## simulate_riskguard.py

Ports `CRiskGuard` and asks the only question that really matters for a funded
account: can any sequence of losses drive the balance through an FTMO limit?
Checks the guard ladder ordering, that pathological inputs are clamped rather
than honoured, that position sizing risks what it claims (within 0.2%), that
sizing collapses to zero before the soft floor is crossed, the loss-streak
de-risking curve, day rollover, and that the total guard still bites after a
profitable stretch.

## simulate_confluence.py

Ports the scoring in `CConfluenceEngine::Evaluate()` plus the hard gates. Answers
what a static read cannot: is the threshold reachable at all, can both sides
score highly at once, and how much more often does an aligned state fire than
noise. The separation figure it reports is what drove the 66/22 -> 72/30 default
change; re-run it after changing any weight or threshold.

## analyse_tester_report.py

    python3 tools/analyse_tester_report.py <testergraph.report.csv>

Reconstructs closed trades from a Strategy Tester equity export and reports the
numbers that decide whether the exit design can work: win rate, payoff ratio,
profit factor, and the win rate that payoff would need in order to break even.
Splits multiple runs in one file, and folds MT5's per-open commission rows into
the following trade — counting those as trades inflates the loss count several
times over.

It was written to diagnose a losing backtest and immediately found two things a
glance at the equity curve did not: the EA had traded on only 13 days out of
379, and every winner was exiting at breakeven behind its partial.

## verify_manifest.py

    python3 tools/verify_manifest.py "<Terminal Data Folder>/MQL5/Experts/XAUUSD_FTMO"

Compares a deployed copy against `MANIFEST.txt` and names any file that is
missing or stale. Written after a compile produced 40 `undeclared identifier`
errors that were entirely caused by a new `.mq5` sitting next to old `.mqh`
files — none of the errors pointed at the real problem.

Regenerate the manifest whenever a source file changes:

    python3 - <<'EOF'
    import hashlib,glob,os
    # see the block in the commit that introduced MANIFEST.txt
    EOF

## build_single_file.py

    python3 tools/build_single_file.py            # rebuild the bundle
    python3 tools/build_single_file.py --check    # fail if it is stale

Concatenates the eight `Include/*.mqh` modules and the EA into a single
self-contained `MQL5/Experts/XAUUSD_FTMO_Confluence_EA.mq5` — stripping project
includes, include guards, version stamps and stray `#property` lines, which must
sit at the top of a file.

The modular sources stay the source of truth because they are easier to review
and test. The bundle is the install artefact because a folder of headers that
must stay in step is fragile — a new `.mq5` beside one stale `.mqh` produced
forty misleading compile errors. `audit_static.py` runs `--check`, so the two
cannot disagree, and it also asserts the bundle contains no `#include` at all.
