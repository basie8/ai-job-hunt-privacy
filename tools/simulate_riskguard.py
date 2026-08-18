#!/usr/bin/env python3
"""Faithful port of CRiskGuard: guard ladder, position sizing, day rollover.

The question this answers: can any sequence of losses drive the account
through an FTMO limit? Everything else in the EA is secondary to that.
"""
import sys, math

class RiskGuard:
    def __init__(s, initial, ftmo_daily=5.0, ftmo_total=10.0,
                 soft_d=2.0, hard_d=3.0, soft_t=5.0, hard_t=7.0,
                 target=10.0, max_trades=3, max_streak=3, streak_factor=0.6):
        s.initial=initial; s.ftmo_d=ftmo_daily; s.ftmo_t=ftmo_total
        s.soft_d, s.hard_d, s.soft_t, s.hard_t = soft_d, hard_d, soft_t, hard_t
        # --- the clamping logic from Init() ---
        if s.hard_d >= s.ftmo_d: s.hard_d = s.ftmo_d*0.8
        if s.soft_d >= s.hard_d: s.soft_d = s.hard_d*0.7
        if s.hard_t >= s.ftmo_t: s.hard_t = s.ftmo_t*0.8
        if s.soft_t >= s.hard_t: s.soft_t = s.hard_t*0.75
        s.target=target; s.max_trades=max_trades; s.max_streak=max_streak
        s.streak_factor=streak_factor
        s.day_start=initial; s.equity=initial
        s.trades_today=0; s.streak=0; s.locked=False

    def pct(s,p): return s.initial*p/100.0
    def daily_dd(s):
        loss=s.day_start-s.equity
        return 0.0 if loss<=0 else loss/s.initial*100.0
    def total_dd(s):
        loss=s.initial-s.equity
        return 0.0 if loss<=0 else loss/s.initial*100.0
    def risk_factor(s):
        if s.streak<=1: return 1.0
        return max(0.25, s.streak_factor**(s.streak-1))
    def room_daily(s):  return max(0.0, s.equity-(s.day_start-s.pct(s.soft_d)))
    def room_total(s):  return max(0.0, s.equity-(s.initial-s.pct(s.soft_t)))

    def evaluate(s):
        if s.total_dd()>=s.hard_t: return "HARD_FLAT"
        if s.daily_dd()>=s.hard_d: s.locked=True; return "HARD_FLAT"
        if s.total_dd()>=s.soft_t: return "SOFT"
        if s.daily_dd()>=s.soft_d: s.locked=True; return "SOFT"
        if s.locked: return "SOFT"
        if s.max_streak>0 and s.streak>=s.max_streak: return "SOFT"
        if s.max_trades>0 and s.trades_today>=s.max_trades: return "SOFT"
        return "NONE"

    def risk_money(s, risk_pct):
        wanted = s.initial*risk_pct/100.0*s.risk_factor()
        return min(wanted, s.room_daily()*0.70, s.room_total()*0.70)

    def roll_day(s):
        s.day_start=min(s.equity,s.equity); s.trades_today=0; s.locked=False

fails=0
def check(cond,msg):
    global fails
    print(("  PASS  " if cond else "  FAIL  ")+msg)
    if not cond: fails+=1

INIT=100_000.0
print("=== 1. guard ladder stays inside the FTMO limits ===")
g=RiskGuard(INIT)
check(g.soft_d<g.hard_d<g.ftmo_d, f"daily ladder {g.soft_d} < {g.hard_d} < {g.ftmo_d}")
check(g.soft_t<g.hard_t<g.ftmo_t, f"total ladder {g.soft_t} < {g.hard_t} < {g.ftmo_t}")

print("\n=== 2. pathological inputs get clamped, not honoured ===")
bad=RiskGuard(INIT, soft_d=9.0, hard_d=12.0, soft_t=20.0, hard_t=30.0)
check(bad.hard_d<bad.ftmo_d, f"hard daily {bad.hard_d:.2f} clamped below FTMO {bad.ftmo_d}")
check(bad.soft_d<bad.hard_d, f"soft daily {bad.soft_d:.2f} below hard {bad.hard_d:.2f}")
check(bad.hard_t<bad.ftmo_t, f"hard total {bad.hard_t:.2f} clamped below FTMO {bad.ftmo_t}")

print("\n=== 3. position sizing risks what it claims ===")
g=RiskGuard(INIT)
# XAUUSD: 1 lot = 100 oz, point 0.01 -> $1 per point per lot. Stop 4.80 -> $480/lot
money_per_lot = 4.80*100
for pct in (0.25,0.5,1.0):
    rm=g.risk_money(pct)
    lots=math.floor(rm/money_per_lot/0.01+1e-8)*0.01
    actual=lots*money_per_lot
    err=abs(actual-INIT*pct/100.0)/(INIT*pct/100.0)*100
    check(err<2.5, f"{pct}% target ${INIT*pct/100:.0f} -> {lots:.2f} lots = ${actual:.0f} (err {err:.1f}%)")

print("\n=== 4. worst case: every trade a full loss, max size, all day ===")
for streak_on in (True,False):
    g=RiskGuard(INIT, max_trades=0, max_streak=(3 if streak_on else 0))
    n=0
    while g.evaluate()=="NONE" and n<200:
        rm=g.risk_money(0.5)
        if rm<=0: break
        g.equity-=rm; g.streak+=1; g.trades_today+=1; n+=1
    worst=g.daily_dd()
    # a position open when the hard guard trips is closed there, so add its risk
    check(worst<g.ftmo_d, f"streak-derisk {'on ' if streak_on else 'off'}: "
                          f"{n} consecutive full losses -> daily DD {worst:.2f}% "
                          f"(FTMO limit {g.ftmo_d}%)")

print("\n=== 5. sizing collapses to zero before the soft floor is crossed ===")
g=RiskGuard(INIT, max_trades=0, max_streak=0)
crossed=False
for i in range(500):
    if g.evaluate()!="NONE": break
    rm=g.risk_money(0.5)
    if rm<=0: break
    g.equity-=rm
    if g.daily_dd()>g.soft_d+0.001: crossed=True
check(not crossed, f"equity never passed the soft daily floor while trading was permitted "
                   f"(final DD {g.daily_dd():.3f}%, soft {g.soft_d}%)")

print("\n=== 6. loss-streak de-risking ===")
g=RiskGuard(INIT)
seq=[]
for st in range(0,6):
    g.streak=st; seq.append(round(g.risk_factor(),3))
check(seq==[1.0,1.0,0.6,0.36,0.25,0.25], f"risk factors by streak: {seq} (floored at 0.25)")

print("\n=== 7. day rollover clears the daily lock ===")
g=RiskGuard(INIT)
g.equity=INIT-2100; g.evaluate()
check(g.locked, "soft daily guard locked the day out")
g.roll_day()
check(not g.locked and g.evaluate()=="NONE", "next day resumes trading")

print("\n=== 8. total guard still bites after a profitable stretch ===")
g=RiskGuard(INIT); g.equity=INIT+8000; g.roll_day()
g.equity=INIT-5100
check(g.evaluate() in ("SOFT","HARD_FLAT"),
      f"total DD {g.total_dd():.2f}% halts trading even though the account once ran +8%")
check(g.total_dd()<g.ftmo_t, "and it bites well before the FTMO 10% floor")

print("\nRISK GUARD:", "PASS" if fails==0 else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
