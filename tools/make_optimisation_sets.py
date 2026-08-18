#!/usr/bin/env python3
"""Generates staged Strategy Tester optimisation .set files from the EA source.

Parsing the inputs out of the .mq5 rather than hand-writing the files means
names and defaults cannot drift out of sync with the code.

DESIGN: why staged files and not one big sweep
----------------------------------------------
Optimising every interesting parameter at once is combinatorially impossible
and statistically worthless. Sweeping just the 11 confluence weights at 5
values each is 48 million passes, and any "best" result from it is a curve
fit to noise. Instead each stage optimises a small group that shares a
purpose, in order of how much the outcome depends on it, and each stage's
winner is frozen into the next.
"""
import re, os, sys, math

EA   = 'MQL5/Experts/XAUUSD_FTMO/XAUUSD_FTMO_Confluence_EA.mq5'
INC  = 'MQL5/Experts/XAUUSD_FTMO/Include'
OUT  = 'MQL5/Presets'

# ---------------------------------------------------------------- enums
TIMEFRAME = {  # ENUM_TIMEFRAMES has non-contiguous values - see docs
 'PERIOD_M1':1,'PERIOD_M5':5,'PERIOD_M15':15,'PERIOD_M30':30,
 'PERIOD_H1':16385,'PERIOD_H2':16386,'PERIOD_H4':16388,'PERIOD_D1':16408,
}

def parse_custom_enums():
    """Read our own enums so their integer values are never guessed."""
    vals={}
    for fn in os.listdir(INC):
        src=open(os.path.join(INC,fn)).read()
        for m in re.finditer(r'enum\s+(\w+)\s*\{(.*?)\}', src, re.S):
            body=re.sub(r'//[^\n]*','',m.group(2))
            nxt=0
            for item in body.split(','):
                item=item.strip()
                if not item: continue
                if '=' in item:
                    name,v=item.split('=',1)
                    nxt=int(v.strip()); name=name.strip()
                else:
                    name=item.split()[0]
                vals[name]=nxt; nxt+=1
    return vals

ENUMS = parse_custom_enums(); ENUMS.update(TIMEFRAME)

# ---------------------------------------------------------------- inputs
def parse_inputs():
    out=[]
    for line in open(EA):
        m=re.match(r'^input\s+(\S+)\s+(\w+)\s*=\s*([^;]+);', line)
        if not m: continue
        typ,name,default = m.group(1), m.group(2), m.group(3).strip()
        if typ=='group': continue
        out.append((typ,name,default.strip('"')))
    return out

INPUTS = parse_inputs()
TYPES  = {n:t for t,n,_ in INPUTS}
DEFAULTS = {n:d for _,n,d in INPUTS}

def literal(name):
    """Default rendered the way a .set file needs it."""
    t,d = TYPES[name], DEFAULTS[name]
    if t.startswith('ENUM_'):
        if d not in ENUMS: raise SystemExit(f"unknown enum constant {d} for {name}")
        return str(ENUMS[d])
    if t=='bool':   return d
    if t=='string': return d
    return d

# ---------------------------------------------------------------- stages
# (name, {param: (start, step, stop)}, rationale)
STAGES = [
 ("Stage1_Signal", {
    'InpScoreThreshold' : (62, 2, 82),
    'InpDominanceMargin': (18, 2, 40),
    'InpAdxMin'         : (16, 2, 30),
  }, "The signal gate. Everything downstream is shaped by which bars qualify, "
     "so this is optimised first and on the widest data."),

 ("Stage2_Exits", {
    'InpSlAtrMult'   : (0.8, 0.2, 2.0),
    'InpTp2R'        : (1.5, 0.25, 3.5),
    'InpTrailStartR' : (0.8, 0.2, 2.0),
    'InpTrailAtrMult': (0.8, 0.2, 2.4),
  }, "Exit geometry, and the stage that matters most right now. A backtest "
     "showed every winner exiting at breakeven behind its partial and NO runner "
     "reaching a 3R target - a 3R target measured against a 1.6 ATR stop needs "
     "4.8 ATR of favourable excursion, which M15 gold rarely delivers. These "
     "ranges deliberately reach into shorter stops and nearer targets."),

 ("Stage3_Volatility", {
    'InpAtrMinRelative' : (0.3, 0.1, 1.0),
    'InpAtrMaxRelative' : (1.5, 0.25, 4.0),
    'InpMaxExtensionAtr': (1.4, 0.3, 3.2),
  }, "The volatility regime filter, in RELATIVE mode - ATR against its own "
     "long-run average. The old absolute dollar band is what silently switched "
     "the EA off for eight months of a backtest when gold re-rated; a relative "
     "band cannot do that. Widen these only if the veto histogram shows ATR "
     "rejections dominating."),

 ("Stage4_EntryQuality", {
    'InpVolumeFactor' : (0.9, 0.1, 1.5),
    'InpSwingLookback': (8, 2, 20),
    'InpPartialPct'   : (30, 10, 70),
    'InpTp1R'         : (0.8, 0.2, 1.6),
  }, "Entry confirmation and how the position is scaled out."),

 ("Stage5_Cadence", {
    'InpMinMinutesBetween': (15, 15, 120),
    'InpMaxTradesPerDay'  : (1, 1, 5),
  }, "Trade cadence. Run last - it interacts with the FTMO minimum trading "
     "days and the daily-quota behaviour, not with the edge itself."),
]

# Timeframes cannot be swept: ENUM_TIMEFRAMES values are not contiguous
# (M30=30 but H1=16385), so a step would iterate thousands of invalid values.
# They are compared as discrete runs instead. ATR bounds scale with sqrt(time).
EXIT_RUNS = [
 ("Exit_A_Scaled",  {'InpUsePartial':'true',  'InpPartialPct':'40', 'InpTp1R':'1.0',
                     'InpTp2R':'2.2', 'InpSlAtrMult':'1.10', 'InpTrailStartR':'1.05',
                     'InpTrailAtrMult':'1.2', 'InpBreakevenLockR':'0.05'},
  "Scaled exit, retuned. 40% off at 1R, runner to 2.2R, trail engages right "
  "after the partial so the runner is not left sitting at breakeven."),

 ("Exit_B_Runner",  {'InpUsePartial':'false', 'InpTp1R':'1.0', 'InpTp2R':'2.5',
                     'InpSlAtrMult':'1.10', 'InpTrailStartR':'1.0',
                     'InpTrailAtrMult':'1.5', 'InpBreakevenLockR':'0.05'},
  "No scale-out at all. The whole position runs behind a trail. Removes the "
  "drag of always banking half the trade at 1R, which is what capped the "
  "average win at 0.5R in the backtest."),

 ("Exit_C_Tight",   {'InpUsePartial':'true',  'InpPartialPct':'50', 'InpTp1R':'0.8',
                     'InpTp2R':'1.8', 'InpSlAtrMult':'0.90', 'InpTrailStartR':'0.85',
                     'InpTrailAtrMult':'1.0', 'InpBreakevenLockR':'0.05'},
  "Tight and fast. Nearer targets and a shorter stop, betting that a higher "
  "hit rate beats a larger but rarely-reached target."),
]

TF_RUNS = [
 ("TF_M5",  'PERIOD_M5',  'PERIOD_M30', 'PERIOD_H4'),
 ("TF_M15", 'PERIOD_M15', 'PERIOD_H1',  'PERIOD_H4'),
 ("TF_M30", 'PERIOD_M30', 'PERIOD_H4',  'PERIOD_D1'),
]

# Never optimised, and the file says why.
LOCKED = {
 'InpRiskPercent':'risk is a decision, not a fitted parameter - optimising it only finds the largest number',
 'InpSoftDailyLossPct':'FTMO compliance guard', 'InpHardDailyLossPct':'FTMO compliance guard',
 'InpSoftTotalLossPct':'FTMO compliance guard', 'InpHardTotalLossPct':'FTMO compliance guard',
 'InpFtmoDailyLossPct':'the rule itself', 'InpFtmoMaxLossPct':'the rule itself',
 'InpNewsMinutesBefore':'compliance, not performance', 'InpNewsMinutesAfter':'compliance, not performance',
}
WEIGHTS = [n for _,n,_ in INPUTS if n.startswith('InpW')]

def fmt(v):
    return f"{v:g}"

def write_set(path, header, opt, overrides):
    lines=[]
    for h in header.split('\n'):
        lines.append('; '+h if h else ';')
    lines.append(';')
    for typ,name,_ in INPUTS:
        if name in opt:
            start,step,stop = opt[name]
            val = overrides.get(name, literal(name))
            # keep the seed value inside the swept range
            try:
                fv=float(val)
                if not (float(start) <= fv <= float(stop)): val=fmt(start)
            except ValueError: pass
            lines.append(f"{name}={val}||{fmt(start)}||{fmt(step)}||{fmt(stop)}||Y")
        else:
            lines.append(f"{name}={overrides.get(name, literal(name))}")
    open(path,'w').write('\n'.join(lines)+'\n')

def passes(opt):
    n=1
    for start,step,stop in opt.values():
        n *= int(round((stop-start)/step))+1
    return n

os.makedirs(OUT, exist_ok=True)
print("Generated optimisation sets\n")
total=0
frozen={}
for i,(name,opt,why) in enumerate(STAGES, 1):
    p=passes(opt); total+=p
    hdr = (f"XAUUSD FTMO Confluence EA - OPTIMISATION {name}\n"
           f"\n{why}\n\n"
           f"Optimising {len(opt)} parameter(s), {p:,} passes.\n"
           "Sweeps only the lines ending ||Y. Everything else is fixed at the\n"
           "value shown, including every risk and compliance setting.\n"
           "\nRun order matters: freeze this stage's winner into the next stage's\n"
           "file before running it.")
    write_set(f"{OUT}/Optimise_{name}.set", hdr, opt, frozen)
    rng=", ".join(f"{k.replace('Inp','')} {v[0]}->{v[2]}" for k,v in opt.items())
    print(f"  Optimise_{name}.set   {p:>6,} passes   {rng}")

print()
for name,tf,mid,hi in TF_RUNS:
    hdr=(f"XAUUSD FTMO Confluence EA - TIMEFRAME COMPARISON {name}\n\n"
         "ENUM_TIMEFRAMES values are not contiguous (M30=30, H1=16385), so a\n"
         "step-based sweep would iterate thousands of invalid values. Timeframes\n"
         "are therefore compared as discrete single runs, not optimised.\n\n"
         "No ATR bounds are set here. In RELATIVE mode the band is ATR against\n"
         "its own average, which is dimensionless - it needs no rescaling when\n"
         "the timeframe changes, and none when the gold price changes either.\n"
         "That is the whole reason relative mode is the default.")
    write_set(f"{OUT}/Compare_{name}.set", hdr, {},
              {'InpTfTrade':str(ENUMS[tf]), 'InpTfMid':str(ENUMS[mid]),
               'InpTfHigh':str(ENUMS[hi])})
    print(f"  Compare_{name}.set     single run   {tf[7:]}/{mid[7:]}/{hi[7:]}"
          f"  (relative ATR band, no rescaling needed)")

for name,ov,why in EXIT_RUNS:
    hdr=(f"XAUUSD FTMO Confluence EA - EXIT STRUCTURE {name}\n\n{why}\n\n"
         "Single run, not an optimisation. Run all three Exit_* files over the\n"
         "same period and compare profit factor and the payoff ratio (avg win\n"
         "divided by avg loss). The payoff is the number that was broken:\n"
         "the backtest delivered 0.50 where roughly 1.6 is needed at a 46%\n"
         "win rate.")
    write_set(f"{OUT}/Compare_{name}.set", hdr, {}, ov)
    print(f"  Compare_{name}.set  single run   {why.split('.')[0]}")
print()

print(f"\ntotal optimisation passes across all stages: {total:,}")
print(f"locked from optimisation: {len(LOCKED)} risk/compliance inputs, "
      f"{len(WEIGHTS)} confluence weights")
print("\ndegrees of freedom:")
for name,opt,_ in STAGES:
    need=len(opt)*40
    print(f"  {name:<20} {len(opt)} params -> want >= {need} trades in the sample")
