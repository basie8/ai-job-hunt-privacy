# Audit tooling

There is no MetaTrader in CI, so these two scripts enforce what a compiler and a
careful reviewer would otherwise catch. Run both from the repository root before
every commit that touches the EA.

```
python3 tools/audit_static.py
python3 tools/audit_api.py
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
