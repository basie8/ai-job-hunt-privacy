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
