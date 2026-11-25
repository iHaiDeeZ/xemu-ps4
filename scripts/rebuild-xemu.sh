#!/usr/bin/env bash
# Configure (if needed) + build with logs (~/xemups4-build/logs/{configure,build}.log) and an error
# summary.
#   rebuild-xemu.sh [clean|reconfigure]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
B="$XEMU_BUILD"
[ "${1:-}" = clean ] && rm -rf "$B" "$PSB/build/port"
if [ ! -f "$B/build.ninja" ] || [ "${1:-}" = reconfigure ]; then
    bash "$HERE/logrun.sh" configure bash "$HERE/configure-xemu.sh" || { tail -30 "$PSB/logs/configure.log"; exit 1; }
fi
bash "$HERE/logrun.sh" build bash "$HERE/build-xemu.sh" -k 0
rc=$?
L="$PSB/logs/build.log"
tail -1 "$L"; echo "errors: $(grep -c 'error:' "$L")"
grep "error:" "$L" | sed 's/.*src\/xemu\///' | sort | uniq -c | sort -rn | head -"${TOP:-60}"
exit $rc
