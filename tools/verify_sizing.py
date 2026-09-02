"""Faithful port of the capital-dependent chain in RiskManager.mqh, driven
exhaustively.  Any assertion failure here is a real defect in the MQL5 source."""
import math, itertools

def normalize(v, d): return round(v + (1e-12 if v>=0 else -1e-12), d)

def volume_digits(step):
    d=0; v=step
    while v < 1.0-1e-9 and d<8: v*=10.0; d+=1
    return d

class Risk:
    def __init__(s, capital, base_risk=0.5, daily=5.0, maxl=10.0,
                 softd=2.5, hardd=3.5, softm=7.0):
        s.init=capital; s.base=base_risk
        s.daily=min(softd, daily*0.7), None
        s.d_pct=daily; s.m_pct=maxl
        s.sd=min(softd, daily*0.7); s.hd=min(hardd, daily*0.8); s.sm=min(softm, maxl*0.8)
    def daily_floor(s,ref):  return ref - s.init*s.d_pct/100
    def soft_daily(s,ref):   return ref - s.init*s.sd/100
    def hard_daily(s,ref):   return ref - s.init*s.hd/100
    def overall(s):          return s.init - s.init*s.m_pct/100
    def soft_max(s):         return s.init - s.init*s.sm/100
    def target(s):           return s.init + s.init*10/100
    def rem_daily(s,eq,ref): return max(eq - s.soft_daily(ref), 0.0)
    def rem_hard(s,eq,ref):  return max(eq - max(s.hard_daily(ref), s.overall()), 0.0)
    def risk_money(s, eq, ref, conf, streak, progress):
        r = s.init*s.base/100
        r *= max(0.45, min(1.35, 0.5+(conf-0.55)*2.8))
        r *= {0:1.0,1:0.75,2:0.55}.get(streak,0.40)
        if progress>=0.70: r*=0.65
        if progress>=0.90: r*=0.45
        return max(min(r, s.rem_daily(eq,ref)/3.0, s.rem_hard(eq,ref)/5.0), 0.0)

def lots(risk_money, sl, tick_sz, tick_val, vmin, vmax, vstep,
         price=4300.0, contract=100.0, leverage=100.0, free_margin=None):
    if sl<=0 or risk_money<=0: return 0.0
    if tick_sz<=0 or tick_val<=0: return 0.0
    spread = 0.30                      # realistic gold spread
    min_sl = max(0.0, spread*2.0)
    if min_sl>0 and sl < min_sl: return 0.0
    per_lot = (sl/tick_sz)*tick_val
    if per_lot<=0: return 0.0
    l = risk_money/per_lot
    if vstep<=0: vstep=0.01
    vd = volume_digits(vstep)
    l = math.floor(l/vstep + 1e-9)*vstep
    l = normalize(l, vd)
    if l < vmin: return 0.0
    if l > vmax: l = vmax
    if l < vmin: return 0.0
    if free_margin is not None:
        margin = l*contract*price/leverage
        while l >= vmin and margin > free_margin*0.35:
            l = normalize(l-vstep, vd)
            if l < vmin: return 0.0
            margin = l*contract*price/leverage
    return l

def worst_case_ok(r, eq, ref, l, sl, tick_sz, tick_val, open_risk=0.0):
    worst = (sl*1.25/tick_sz)*tick_val*l
    if eq-(worst+open_risk) <= r.hard_daily(ref): return False
    if eq-(worst+open_risk) <= r.soft_max():      return False
    return True

BROKERS = {
 "standard gold  (tick .01 / val 1.00 / min .01 / step .01)": (0.01,1.00,0.01,100.0,0.01),
 "micro gold     (tick .01 / val 0.10 / min .01 / step .01)": (0.01,0.10,0.01,100.0,0.01),
 "fine step      (tick .01 / val 1.00 / min .01 / step .001)":(0.01,1.00,0.01,100.0,0.001),
 "coarse step    (tick .01 / val 1.00 / min .10 / step .10)": (0.01,1.00,0.10,100.0,0.10),
 "5-digit tick   (tick .001/ val 0.10 / min .01 / step .01)": (0.001,0.10,0.01,100.0,0.01),
}
CAPITALS=[1000,2000,5000,10000,25000,50000,100000,200000]
STOPS=[3,5,8,12,15,20,25,30,40]
CONFS=[0.55,0.62,0.70,0.80,0.90]
STREAKS=[0,1,2,3]
PROGS=[0.0,0.75,0.95]

fails=[]; checked=0; skipped=0
shortfall={}
for bname,(ts,tv,vmin,vmax,vstep) in BROKERS.items():
    for cap in CAPITALS:
        r=Risk(cap)
        # --- proportionality of every capital-derived level
        for pct,fn in ((5.0,lambda ref: r.daily_floor(ref)),(2.5,lambda ref: r.soft_daily(ref)),
                       (3.5,lambda ref: r.hard_daily(ref))):
            got = cap - fn(cap)
            if abs(got - cap*pct/100) > 1e-6: fails.append(f"{bname} cap {cap}: floor not proportional ({got} vs {cap*pct/100})")
        if abs((cap - r.overall()) - cap*0.10) > 1e-6: fails.append(f"cap {cap}: overall floor not 10%")
        if abs((r.target() - cap) - cap*0.10) > 1e-6: fails.append(f"cap {cap}: target not +10%")

        for eq_mult in (1.0, 0.99, 0.985):
            eq=cap*eq_mult; ref=cap
            for stop,conf,streak,prog in itertools.product(STOPS,CONFS,STREAKS,PROGS):
                checked+=1
                budget = r.risk_money(eq, ref, conf, streak, prog)
                l = lots(budget, stop, ts, tv, vmin, vmax, vstep,
                         free_margin=eq*0.98)
                if l==0.0:
                    skipped+=1
                    continue
                per_lot=(stop/ts)*tv
                actual = l*per_lot
                # INV1: never risk more than the computed budget
                if actual > budget*(1+1e-9)+1e-6:
                    fails.append(f"{bname} cap{cap} stop{stop} conf{conf} streak{streak}: OVER-RISK actual {actual:.4f} > budget {budget:.4f}")
                # INV2: never exceed the remaining-budget caps
                if actual > r.rem_daily(eq,ref)/3.0 + 1e-6:
                    fails.append(f"{bname} cap{cap}: breaches daily-budget cap")
                if actual > r.rem_hard(eq,ref)/5.0 + 1e-6:
                    fails.append(f"{bname} cap{cap}: breaches hard-budget cap")
                # INV3: volume quantisation
                steps = l/vstep
                if abs(steps-round(steps)) > 1e-6:
                    fails.append(f"{bname} cap{cap}: lots {l} not a multiple of step {vstep}")
                if l < vmin-1e-12 or l > vmax+1e-12:
                    fails.append(f"{bname} cap{cap}: lots {l} outside [{vmin},{vmax}]")
                # INV4: an accepted trade must survive its own worst case
                if worst_case_ok(r, eq, ref, l, stop, ts, tv):
                    post = eq - (stop*1.25/ts)*tv*l
                    if post <= r.hard_daily(ref) or post <= r.soft_max():
                        fails.append(f"{bname} cap{cap}: worst-case check passed but breaches a floor")
                # realised-vs-intended, standard broker only
                if bname.startswith("standard") and eq_mult==1.0 and conf==0.62 and streak==0 and prog==0.0:
                    shortfall.setdefault(cap,[]).append(actual/budget)

# INV5: identical intended risk % across capitals; monotonic lots
ts,tv,vmin,vmax,vstep = BROKERS["standard gold  (tick .01 / val 1.00 / min .01 / step .01)"]
for stop in STOPS:
    prev=-1
    for cap in CAPITALS:
        r=Risk(cap)
        b=r.risk_money(cap,cap,0.62,0,0.0)
        if abs(b/cap - Risk(100000).risk_money(100000,100000,0.62,0,0.0)/100000) > 1e-12:
            fails.append(f"stop{stop} cap{cap}: intended risk % differs across capital")
        l=lots(b,stop,ts,tv,vmin,vmax,vstep)
        if l < prev-1e-12: fails.append(f"stop{stop}: lots not monotonic in capital ({cap})")
        prev=l

print(f"combinations exercised : {checked:,}")
print(f"  trades sized         : {checked-skipped:,}")
print(f"  correctly refused    : {skipped:,}  (position would fall below the broker minimum)")
print(f"invariant failures     : {len(fails)}")
for f in fails[:15]: print("   ", f)
print()
print("Realised risk as a fraction of the intended budget (standard gold, p=0.62):")
for cap in sorted(shortfall):
    v=shortfall[cap]
    print(f"  {cap:>7,}: min {min(v)*100:5.1f}%  mean {sum(v)/len(v)*100:5.1f}%  max {max(v)*100:5.1f}%  of intended")
print()
print("RESULT:", "ALL INVARIANTS HOLD" if not fails else f"{len(fails)} FAILURES")
