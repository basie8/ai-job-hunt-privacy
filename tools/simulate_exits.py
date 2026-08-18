#!/usr/bin/env python3
"""Faithful port of CTradeExecutor::Manage() run over synthetic price paths.

Proves the exit engine produces the R-multiple distribution documented in
docs/STRATEGY.md - the claim the whole 'small losses, larger wins' design
rests on. Run after any change to TradeExecutor.mqh.
"""
import sys

TP1R, TP2R      = 1.0, 3.0
PARTIAL_PCT     = 50.0
BE_LOCK_R       = 0.10
TRAIL_START_R   = 1.5
TRAIL_ATR_MULT  = 2.0
TRAIL_STEP      = 0.20
MIN_LOT, LOT_STEP = 0.01, 0.01
USE_PARTIAL, USE_TRAIL = True, True

def norm(v):
    import math
    v = math.floor(v/LOT_STEP + 1e-8)*LOT_STEP
    return 0.0 if v < MIN_LOT-1e-8 else round(v, 2)

def run(path, atr, is_buy=True, volume=1.00, be_fails_ticks=0, label=""):
    """path: list of prices. Returns realised R and an event log."""
    entry = path[0]
    risk  = atr*1.6                      # InpSlAtrMult
    sl    = entry - risk if is_buy else entry + risk
    tp    = entry + risk*TP2R if is_buy else entry - risk*TP2R
    lock  = risk*BE_LOCK_R
    stage, realisedR, events = 0, 0.0, []
    open_vol = volume
    highest, lowest = entry, entry

    for t, px in enumerate(path):
        highest = max(highest, px); lowest = min(lowest, px)

        # ---- broker-side exits first ----
        hit_sl = (px <= sl) if is_buy else (px >= sl)
        hit_tp = (px >= tp) if is_buy else (px <= tp)
        if hit_sl:
            r = ((sl-entry) if is_buy else (entry-sl))/risk
            realisedR += r*open_vol/volume
            events.append(f"t{t} STOP @{sl:.2f} ({r:+.2f}R on {open_vol:.2f})")
            open_vol = 0.0; break
        if hit_tp:
            realisedR += TP2R*open_vol/volume
            events.append(f"t{t} TP2 @{tp:.2f} (+{TP2R:.2f}R on {open_vol:.2f})")
            open_vol = 0.0; break

        fav = (px-entry) if is_buy else (entry-px)
        rM  = fav/risk

        # ---- STAGE 0: one-shot partial ----
        if stage == 0:
            if rM < TP1R: continue
            if USE_PARTIAL:
                cv = norm(open_vol*PARTIAL_PCT/100.0); rem = norm(open_vol-cv)
                if cv >= MIN_LOT and rem >= MIN_LOT:
                    realisedR += rM*cv/volume
                    events.append(f"t{t} TP1 partial {cv:.2f} @{rM:+.2f}R")
                    open_vol = rem
                else:
                    events.append(f"t{t} partial skipped (too small)")
            stage = 1

        # ---- STAGE 1: breakeven, retried ----
        if stage == 1:
            new_sl = entry+lock if is_buy else entry-lock
            already = (sl >= new_sl) if is_buy else (sl <= new_sl)
            if already:
                stage = 2
            elif t < be_fails_ticks:
                events.append(f"t{t} BE deferred (broker)")
            else:
                sl = new_sl; stage = 2
                events.append(f"t{t} BE set @{sl:.2f}")
            if stage < 2: continue

        # ---- STAGE 2+: chandelier trail with step gate ----
        if not USE_TRAIL or rM < TRAIL_START_R: continue
        trail = (highest - atr*TRAIL_ATR_MULT) if is_buy else (lowest + atr*TRAIL_ATR_MULT)
        beats = (trail > sl+TRAIL_STEP) if is_buy else (trail < sl-TRAIL_STEP)
        beyond= (trail >= entry+lock) if is_buy else (trail <= entry-lock)
        if beats and beyond:
            sl = trail
            if stage < 3:
                stage = 3; events.append(f"t{t} trail engaged @{sl:.2f}")

    if open_vol > 0:                      # still open at path end
        px = path[-1]; rM = ((px-entry) if is_buy else (entry-px))/risk
        realisedR += rM*open_vol/volume
        events.append(f"end open {open_vol:.2f} @{rM:+.2f}R")
    return realisedR, events

ATR = 3.0; E = 3300.0; R = ATR*1.6      # risk = 4.80
def up(n):   return [E + R*i/4 for i in range(n)]
def down(n): return [E - R*i/4 for i in range(n)]

CASES = [
 ("straight to stop",        down(6),                      -1.00),
 ("1R then back to BE",      up(5)+[E+R*1.05]+down(0)+[E+R*0.10], 0.55),
 ("straight to TP2 (3R)",    up(14),                        2.00),
 ("1R, BE fails 3 ticks",    up(5)+[E+R]*4+[E+R*0.10],      0.55),
]

print(f"entry {E:.2f}  ATR {ATR:.2f}  risk {R:.2f}  (1R = ${R:.2f})\n")
fails = 0
for label, path, expected in CASES:
    be_fail = 3 if "BE fails" in label else 0
    got, ev = run(path, ATR, be_fails_ticks=be_fail, label=label)
    ok = abs(got-expected) < 0.06
    fails += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label:26s} -> {got:+.2f}R (expected {expected:+.2f}R)")
    for e in ev: print(f"          {e}")
    print()

# --- invariants over many random paths ---
import random
random.seed(7)
worst = 0.0; scaled_twice = 0
for i in range(4000):
    px = E; path=[E]
    for _ in range(60):
        px += random.gauss(0, ATR*0.35); path.append(px)
    for be_fail in (0, 5):
        for is_buy in (True, False):
            r, ev = run(path, ATR, is_buy=is_buy, be_fails_ticks=be_fail)
            worst = min(worst, r)
            if sum(1 for e in ev if "partial" in e and "skipped" not in e) > 1:
                scaled_twice += 1
print(f"random paths: 16,000 runs")
print(f"  worst realised outcome : {worst:+.2f}R   (must never be worse than -1.00R)")
print(f"  double scale-outs      : {scaled_twice}   (must be 0)")
if worst < -1.001: fails += 1
if scaled_twice:  fails += 1
print("\nEXIT ENGINE:", "PASS" if fails == 0 else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
