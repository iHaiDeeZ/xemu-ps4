#!/usr/bin/env bash
# Commit the work in ~/xemups4-build/src/xemu (branch ps4) and export it as patches/xemu-ps4.patch
# against the upstream base recorded in patches/BASE.txt.
#   save-patch.sh "commit message"
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
BASE="$(awk '/^base:/{print $2}' "$XEMUPS4/patches/BASE.txt")"
git -C "$XEMU_SRC" add -A -- . ':!subprojects'
git -C "$XEMU_SRC" diff --cached --quiet ||
    git -C "$XEMU_SRC" -c user.name=xemu-ps4 -c user.email=xemu-ps4@localhost commit -q -m "${1:-PS4 port work}"
git -C "$XEMU_SRC" diff "$BASE" HEAD -- . ':!subprojects' > "$XEMUPS4/patches/xemu-ps4.patch"
echo "patches/xemu-ps4.patch: $(grep -c '^diff --git' "$XEMUPS4/patches/xemu-ps4.patch") files"
