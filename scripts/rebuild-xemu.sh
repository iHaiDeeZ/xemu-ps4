#!/usr/bin/env bash
# Configure (if needed) + build with logs (~/xemups4-build/logs/{configure,build}.log) and an error
# summary.
#   rebuild-xemu.sh [clean|reconfigure]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$HOME/xemups4-build/build/xemu"
[ "${1:-}" = clean ] && rm -rf "$B"
if [ ! -f "$B/build.ninja" ] || [ "${1:-}" = reconfigure ]; then
    bash "$HERE/logrun.sh" configure bash "$HERE/configure-xemu.sh" || { tail -30 "$HOME/xemups4-build/logs/configure.log"; exit 1; }
fi
bash "$HERE/logrun.sh" build bash "$HERE/build-xemu.sh" -k 0
L="$HOME/xemups4-build/logs/build.log"
tail -1 "$L"; echo "errors: $(grep -c 'error:' "$L")"
grep "error:" "$L" | sed 's/.*src\/xemu\///' | sort | uniq -c | sort -rn | head -${TOP:-60}
