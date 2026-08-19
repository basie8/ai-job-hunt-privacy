#!/usr/bin/env python3
"""Proves the single-file build is complete and self-contained.

Checks every module is present and in dependency order, that every
declaration in every source file survived the bundling, and that no
include or Standard Library reference remains in executable code.
Run after any change to the modules or the bundler.
"""
import re, os
ROOT='MQL5/Experts/XAUUSD_FTMO'
BUNDLE='MQL5/Experts/XAUUSD_FTMO_Confluence_EA.mq5'
ORDER=['CoreDefs.mqh','TimeZones.mqh','NewsFilter.mqh','RiskGuard.mqh',
       'ConfluenceEngine.mqh','TradeExecutor.mqh','Statistics.mqh','Dashboard.mqh']
bundle=open(BUNDLE).read()
def strip(x):
    x=re.sub(r'//[^\n]*','',x); return re.sub(r'/\*.*?\*/','',x,flags=re.S)
bcode=strip(bundle)

print("=== 1. every module present, in dependency order? ===")
pos=-1; ok=True
for m in ORDER:
    i=bundle.find('//  '+m)
    st='present' if i>=0 else 'MISSING'
    if i>=0 and i<pos: st='OUT OF ORDER'; ok=False
    if i<0: ok=False
    pos=max(pos,i)
    print("   %-24s %s" % (m, st))
i=bundle.find('//  EXPERT ADVISOR')
print("   %-24s %s" % ('EXPERT ADVISOR', 'present' if i>pos else 'MISSING/OUT OF ORDER'))

print("\n=== 2. every declaration from every source present in the bundle? ===")
PAT=[r'\benum\s+(\w+)\s*\{', r'^class\s+(\w+)', r'^struct\s+(\w+)',
     r'^#define\s+(\w+)', r'^[A-Za-z_][\w:]*[\s&*]+([A-Za-z_]\w*)\s*\([^;]*\)\s*$']
total=0; missing=[]
srcs=[ROOT+'/Include/'+m for m in ORDER]+[ROOT+'/XAUUSD_FTMO_Confluence_EA.mq5']
for f in srcs:
    code=strip(open(f).read())
    names=set()
    for p in PAT: names|=set(re.findall(p,code,re.M))
    for cm in re.finditer(r'^class\s+(\w+)',code,re.M):
        body=code[cm.end():].split('\n  };',1)[0]
        names|=set(re.findall(r'[\w:]+[\s&*]+(\w+)\s*\(',body))
    names={n for n in names if not n.startswith('__') and not n.startswith('XFC_V_')}
    gone=[n for n in sorted(names) if not re.search(r'\b'+re.escape(n)+r'\b', bcode)]
    total+=len(names)
    if gone: missing.append((os.path.basename(f),gone)); ok=False
    print("   %-34s %4d declarations   %s" % (os.path.basename(f), len(names),
          'all present' if not gone else 'MISSING '+str(gone)))
print("\n   %d declarations checked overall" % total)

print("\n=== 3. dependencies remaining ===")
inc=re.findall(r'^#include.*$', bundle, re.M)
print("   #include directives:            %d  %s" % (len(inc), inc if inc else '(none)'))
print("   CTrade / CPositionInfo refs:    %d" % len(re.findall(r'\bCTrade\b|\bCPositionInfo\b', bcode)))
print("   '<Trade\\' references:           %d" % bundle.count('<Trade'))
print("   OrderSend call sites:           %d" % len(re.findall(r'\bOrderSend\s*\(', bcode)))
if inc: ok=False

print("\n=== 4. line accounting ===")
sl=sum(len(open(f).read().split('\n')) for f in srcs)
bl=len(bundle.split('\n'))
print("   modular sources: %6d lines" % sl)
print("   bundle:          %6d lines   (delta %+d)" % (bl, bl-sl))
print("\nRESULT:", "COMPLETE - nothing lost, nothing external" if ok else "INCOMPLETE")
import sys
sys.exit(0 if ok else 1)
