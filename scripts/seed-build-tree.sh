#!/usr/bin/env bash
# One-time: the WSL build tree ~/xemups4-build and the space-free link ~/xemups4 to this repo.
# Needs ps4-kit (github.com/iHaiDeeZ/ps4-kit) set up first: ~/ps4-kit, its sysroot in
# ~/ps4kit-build/sysroot (scripts/seed-build-tree.sh there) and its RADV build
# (gpu/build-mesa.sh -> ~/ps4kit-build/build/mesa). This port's sysroot starts as a copy of the
# kit's, so what xemu adds (glib, pixman, its SDL3, a trimmed libc.a) never lands in another port's.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
[ -e "$HOME/xemups4" ] || ln -s "$REPO" "$HOME/xemups4"
source "$HERE/env.sh"
[ -d "$HOME/ps4kit-build/sysroot/lib" ] || { echo "no kit sysroot in ~/ps4kit-build/sysroot (ps4-kit's seed-build-tree.sh)" >&2; exit 1; }
[ -f "$PS4_MESA_BUILD/src/amd/vulkan/libvulkan_radeon.a" ] || { echo "no RADV build in $PS4_MESA_BUILD (ps4-kit's gpu/build-mesa.sh)" >&2; exit 1; }
mkdir -p "$PSB/src" "$PSB/build" "$PSB/out" "$PSB/logs" "$PSB/oelf"
if [ ! -d "$PS4_SYSROOT/lib" ]; then
    cp -a "$HOME/ps4kit-build/sysroot" "$PS4_SYSROOT"
    # the copied pkg-config and CMake files still name the kit's tree
    grep -rlE "/home/[^/]+/ps4kit-build/sysroot" "$PS4_SYSROOT/lib/pkgconfig" "$PS4_SYSROOT/lib/cmake" 2>/dev/null |
        xargs -r sed -i -E "s#/home/[^/]+/ps4kit-build/sysroot#$PS4_SYSROOT#g"
fi
du -sh "$PSB"/* 2>/dev/null || true
