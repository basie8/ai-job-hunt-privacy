#!/usr/bin/env python3
"""Static audit for the XAUUSD FTMO EA. No compiler available, so this
enforces what a compiler and a careful reviewer would catch."""
import re, glob, os, sys, collections

ROOT='MQL5/Experts/XAUUSD_FTMO'
FILES=sorted(glob.glob(ROOT+'/**/*.mq*',recursive=True))
MAIN=ROOT+'/XAUUSD_FTMO_Confluence_EA.mq5'

issues=collections.defaultdict(list)
def flag(cat,msg): issues[cat].append(msg)

def strip_code(src):
    """remove comments and string/char literals, preserving line count"""
    out=[];i=0;n=len(src)
    while i<n:
        c=src[i]
        if c=='/' and i+1<n and src[i+1]=='/':
            while i<n and src[i]!='\n': i+=1
        elif c=='/' and i+1<n and src[i+1]=='*':
            i+=2
            while i+1<n and not(src[i]=='*' and src[i+1]=='/'):
                if src[i]=='\n': out.append('\n')
                i+=1
            i+=2
        elif c=='"':
            i+=1
            while i<n and src[i]!='"': i+= 2 if src[i]=='\\' else 1
            i+=1; out.append('""')
        elif c=="'":
            i+=1
            while i<n and src[i]!="'": i+= 2 if src[i]=='\\' else 1
            i+=1; out.append("''")
        else:
            out.append(c); i+=1
    return ''.join(out)

SRC={f:open(f).read() for f in FILES}
CODE={f:strip_code(s) for f,s in SRC.items()}
ALLCODE='\n'.join(CODE.values())
ALLSRC='\n'.join(SRC.values())

# ---------- 1. placeholders / stubs ----------
PLACEHOLDER=re.compile(r'\b(TODO|FIXME|XXX|HACK|PLACEHOLDER|STUB|NOT[ _]IMPLEMENTED|TBD|<[a-z]+ here>|\.\.\.)\b',re.I)
for f,s in SRC.items():
    for ln,line in enumerate(s.split('\n'),1):
        if PLACEHOLDER.search(line):
            flag('placeholder',f"{f}:{ln}: {line.strip()[:90]}")

# empty function bodies  ->  something(){ }  or { return; }
for f,s in CODE.items():
    for m in re.finditer(r'(\w+)\s*\([^;{)]*\)\s*(?:const\s*)?\{\s*\}',s):
        if m.group(1) not in ('if','for','while','switch','catch'):
            flag('placeholder',f"{f}: empty body for {m.group(1)}()")

# ---------- 2. brace / paren balance ----------
for f,s in CODE.items():
    d={'{':0,'(':0,'[':0};pairs={'}':'{',')':'(',']':'['}
    for c in s:
        if c in d: d[c]+=1
        elif c in pairs: d[pairs[c]]-=1
    for k,v in d.items():
        if v: flag('balance',f"{f}: '{k}' unbalanced by {v:+d}")

# ---------- 3. non-ASCII ----------
for f,s in SRC.items():
    for ln,line in enumerate(s.split('\n'),1):
        if any(ord(ch)>127 for ch in line):
            flag('encoding',f"{f}:{ln}: non-ASCII")

# ---------- 4. inputs declared vs used ----------
inputs=re.findall(r'^input\s+(\S+)\s+(\w+)\s*=\s*([^;]+);',SRC[MAIN],re.M)
input_names=[n for _,n,_ in inputs]
dups=[n for n,c in collections.Counter(input_names).items() if c>1]
for d in dups: flag('inputs',f"duplicate input name: {d}")

for typ,name,default in inputs:
    # count uses outside the declaration line
    uses=len(re.findall(r'\b'+re.escape(name)+r'\b',ALLCODE))
    if uses<=1:
        flag('inputs',f"UNUSED input: {name} (declared, never referenced)")

# ---------- 5. class methods declared vs defined ----------
for f,s in SRC.items():
    for cm in re.finditer(r'^class\s+(\w+)',s,re.M):
        c=cm.group(1)
        body=s[cm.end():]
        body=body.split('\n  };',1)[0]
        decls=set(re.findall(r'^\s+(?:static\s+|virtual\s+)?[\w:]+[\s&*]+(\w+)\s*\([^;{]*\)\s*(?:const\s*)?;',body,re.M))
        defs=set(re.findall(r'^[\w:]+[\s&*]+'+c+r'::(\w+)\s*\(',s,re.M))
        defs|=set(re.findall(r'^'+c+r'::(\w+)\s*\(',s,re.M))
        inline=set(re.findall(r'\b(\w+)\s*\([^;{]*\)\s*(?:const\s*)?\{',body))
        miss=decls-defs-inline
        for m in miss: flag('methods',f"{f}: {c}::{m}() declared but not defined")

# ---------- 6. free functions defined but never called ----------
EVENTS={'OnInit','OnDeinit','OnTick','OnTimer','OnTradeTransaction','OnChartEvent','OnTester','OnTrade','OnBookEvent'}
freefn=set()
for f,s in SRC.items():
    for m in re.finditer(r'^(?:[\w]+\s+)+?(\w+)\s*\([^;{]*\)\s*$',s,re.M):
        pass
    for m in re.finditer(r'^([A-Za-z_][\w]*)\s+([A-Za-z_]\w*)\s*\(([^;{]*)\)\s*\n?\s*\{',s,re.M):
        rt,name=m.group(1),m.group(2)
        if '::' in m.group(0): continue
        if rt in ('return','else','if','while','for','switch'): continue
        freefn.add(name)
for fn in sorted(freefn):
    if fn in EVENTS: continue
    calls=len(re.findall(r'\b'+re.escape(fn)+r'\s*\(',ALLCODE))
    if calls<=1:
        flag('deadcode',f"function defined but never called: {fn}()")

# ---------- 7. preset keys, and optimisation ranges ----------
valid=set(input_names)
# never sweep these - risk is a decision, and the guards are the FTMO rules
NEVER_SWEEP = {n for n in input_names
               if n.startswith('InpW')
               or n in {'InpRiskPercent','InpFixedLot','InpSoftDailyLossPct','InpHardDailyLossPct',
                        'InpSoftTotalLossPct','InpHardTotalLossPct','InpFtmoDailyLossPct',
                        'InpFtmoMaxLossPct','InpNewsMinutesBefore','InpNewsMinutesAfter',
                        'InpProfitTargetPct','InpInitialCapital','InpMagic'}}

for pf in sorted(glob.glob('MQL5/Presets/*.set')):
    seen=set(); total_passes=1; swept=0
    for ln,line in enumerate(open(pf).read().split('\n'),1):
        line=line.strip()
        if not line or line.startswith(';'): continue
        if '=' not in line:
            flag('presets',f"{pf}:{ln}: malformed line '{line}'"); continue
        k,v = line.split('=',1)
        k=k.strip()
        if k not in valid: flag('presets',f"{pf}:{ln}: '{k}' is not an EA input")
        if k in seen: flag('presets',f"{pf}:{ln}: duplicate key '{k}'")
        seen.add(k)

        if '||' not in v: continue
        parts=v.split('||')
        if len(parts)!=5:
            flag('presets',f"{pf}:{ln}: '{k}' has {len(parts)} ||-fields, expected 5"); continue
        val,start,step,stop,en = [x.strip() for x in parts]
        if en not in ('Y','N'):
            flag('presets',f"{pf}:{ln}: '{k}' enable flag is '{en}', expected Y or N")
        if en!='Y': continue
        swept+=1
        if k in NEVER_SWEEP:
            flag('presets',f"{pf}:{ln}: '{k}' must never be optimised (risk/compliance/weight)")
        try:
            fs,fp,fe,fv = float(start),float(step),float(stop),float(val)
        except ValueError:
            flag('presets',f"{pf}:{ln}: '{k}' has non-numeric range fields"); continue
        if fp<=0:
            flag('presets',f"{pf}:{ln}: '{k}' step is {fp}, must be > 0")
            continue
        if fs>fe:
            flag('presets',f"{pf}:{ln}: '{k}' start {fs} exceeds stop {fe}")
            continue
        if not (fs-1e-9 <= fv <= fe+1e-9):
            flag('presets',f"{pf}:{ln}: '{k}' seed value {fv} is outside its swept range {fs}..{fe}")
        steps=int(round((fe-fs)/fp))+1
        if steps>200:
            flag('presets',f"{pf}:{ln}: '{k}' sweeps {steps} values - step is probably too small")
        total_passes*=steps
    if swept and total_passes>60000:
        flag('presets',f"{pf}: {total_passes:,} passes across {swept} swept parameters "
                       f"- split this into more stages")

# ---------- 8. include graph ----------
for f,s in SRC.items():
    for inc in re.findall(r'#include\s+"([^"]+)"',s):
        target=os.path.normpath(os.path.join(os.path.dirname(f),inc))
        if not os.path.exists(target):
            flag('includes',f"{f}: missing include '{inc}'")
    guards=re.findall(r'#ifndef\s+(\w+)',s)
    if f.endswith('.mqh') and not guards:
        flag('includes',f"{f}: no include guard")

# ---------- 9. generated .set files must not have drifted ----------
import subprocess
_r=subprocess.run(['python3','tools/make_optimisation_sets.py','--check'],
                  capture_output=True, text=True)
if _r.returncode!=0:
    for _l in _r.stdout.strip().split('\n'):
        if _l.strip().startswith('MQL5/'):
            flag('presets', f"{_l.strip()} is stale - regenerate with "
                            f"tools/make_optimisation_sets.py")

# ---------- report ----------
order=['placeholder','balance','encoding','inputs','methods','deadcode','presets','includes']
total=0
for cat in order:
    lst=issues.get(cat,[])
    total+=len(lst)
    status='PASS' if not lst else f'{len(lst)} FINDING(S)'
    print(f"[{status:>14}] {cat}")
    for m in lst: print(f"                 - {m}")
print(f"\nTOTAL FINDINGS: {total}")
sys.exit(1 if total else 0)
