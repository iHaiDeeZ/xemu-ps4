#!/usr/bin/env bash
# One-time: create ~/xemups4-build from copies of Resonance's build tree (libc++ 21 sysroot with the
# libc overlay and prebuilt libraries, and the RADV/GNM Mesa build), so this port never writes into
# another port's tree.
set -euo pipefail
SRC_TREE="${SRC_TREE:-$HOME/resonance-build}"
PSB="${PSB:-$HOME/xemups4-build}"
mkdir -p "$PSB/src" "$PSB/build" "$PSB/out" "$PSB/logs" "$PSB/oelf"
[ -d "$PSB/sysroot" ] || cp -a "$SRC_TREE/sysroot" "$PSB/sysroot"
# the copied pkg-config and CMake files still name the build tree they were made in
grep -rlE "/home/[^/]+/[a-z0-9]+-build/sysroot" "$PSB/sysroot/lib/pkgconfig" "$PSB/sysroot/lib/cmake" 2>/dev/null |
    xargs -r sed -i -E "s#/home/[^/]+/[a-z0-9]+-build/sysroot#$PSB/sysroot#g"
[ -d "$PSB/host-compat" ] || cp -a "$SRC_TREE/host-compat" "$PSB/host-compat"
# Mesa: the whole build directory (its static libraries are thin archives). CEMUPS4's build of
# Crema's tree (34ff87b and later): xemu runs nearly every draw through a geometry shader, and
# that tree allocates the legacy GS rings larger than programmed - with Resonance's older RADV
# the GS wrote past its rings and the PS4 ended the app on the GPU page fault.
MESA_TREE="${MESA_TREE:-$HOME/cemups4-build}"
[ -d "$PSB/build/mesa" ] || cp -a "$MESA_TREE/build/mesa" "$PSB/build/mesa"
# Space-free path to this repo: toolchain flags (linker script paths) break on "PS4 Projects".
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -e "$HOME/xemups4" ] || ln -s "$REPO" "$HOME/xemups4"
du -sh "$PSB"/* 2>/dev/null
