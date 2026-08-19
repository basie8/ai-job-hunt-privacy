#!/usr/bin/env python3
"""Checks a deployed copy of the EA against MANIFEST.txt.

    python3 tools/verify_manifest.py "/path/to/MQL5/Experts/XAUUSD_FTMO"

Catches the partial copy that produces dozens of misleading compile errors.
"""
import hashlib, os, sys
ROOT='MQL5/Experts/XAUUSD_FTMO'
target=sys.argv[1] if len(sys.argv)>1 else ROOT
bad=0
for line in open(ROOT+'/MANIFEST.txt'):
    line=line.strip()
    if not line or line.startswith('#'): continue
    want,rel=line.split(None,1)
    p=rel if os.path.isabs(rel) or target==ROOT else os.path.join(target,os.path.basename(rel))
    if target==ROOT: p=rel
    if not os.path.exists(p):
        print(f"  MISSING   {rel}"); bad+=1; continue
    got=hashlib.sha256(open(p,'rb').read()).hexdigest()[:16]
    if got!=want:
        print(f"  STALE     {rel}   (expected {want}, found {got})"); bad+=1
    else:
        print(f"  ok        {rel}")
print()
print("copy matches the repository" if not bad else
      f"{bad} file(s) wrong - copy the ENTIRE XAUUSD_FTMO folder, Include/ included")
sys.exit(1 if bad else 0)
