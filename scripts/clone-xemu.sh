#!/usr/bin/env bash
# Clone upstream xemu (with submodules) into the WSL build tree at the base in patches/BASE.txt and
# link the repo space-free.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ln -sfn "/mnt/e/PS4 Projects/xemu-ps4" "$HOME/xemups4"
BASE="$(awk '/^base:/{print $2}' "$HERE/../patches/BASE.txt")"
mkdir -p "$HOME/xemups4-build/src" "$HOME/xemups4-build/logs"
cd "$HOME/xemups4-build/src"
[ -d xemu ] || git clone --recursive https://github.com/xemu-project/xemu.git xemu
cd xemu
git checkout -q "$BASE" 2>/dev/null || true
git log -1 --format='%h %ci %s'
