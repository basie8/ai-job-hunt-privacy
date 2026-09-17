#!/bin/sh
# Rebuild AURUM-bridge.zip, the Windows kit the user downloads.
#
# The kit deliberately does NOT contain the project: SETUP.bat runs `git init`
# plus `git remote add`, and the bridge pushes with git plumbing, so a folder
# holding only the script, a data directory and a .git is enough. Covered by
# tests_gold/test_sync.py::test_the_bridge_works_from_a_repo_holding_no_project_files
set -eu
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
OUT=${1:-$ROOT/AURUM-bridge.zip}
STAGE=$(mktemp -d)/AURUM-bridge
mkdir -p "$STAGE"

cp "$ROOT/gold_trader/bridge/mt5_export.py"            "$STAGE/"
cp "$ROOT/gold_trader/bridge/windows_kit/"*.bat        "$STAGE/"
cp "$ROOT/gold_trader/bridge/windows_kit/README.txt"   "$STAGE/"
cp "$ROOT/docs/INSTALL.md"                             "$STAGE/"
cp "$ROOT/gold_trader/examples/calendar.example.json"  "$STAGE/"

# Windows tools expect CRLF in .bat and .txt.
for f in "$STAGE"/*.bat "$STAGE/README.txt"; do
  sed -i 's/\r$//; s/$/\r/' "$f"
done

rm -f "$OUT"
(cd "$(dirname "$STAGE")" && zip -q -r "$OUT" AURUM-bridge)
echo "wrote $OUT"
unzip -l "$OUT" | tail -n +4 | head -n -2
