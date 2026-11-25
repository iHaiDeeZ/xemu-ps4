#!/usr/bin/env bash
# Upstream xemu at the base in patches/BASE.txt into ~/xemups4-build/src/xemu, with the meson
# subprojects the PS4 build uses, then the PS4 patch on a branch "ps4".
#   clone-xemu.sh              clone + subprojects + patch
#   clone-xemu.sh --no-patch   clone + subprojects only
# Offline (WSL without internet): XEMU_MIRROR (default /mnt/e/xemu-src) holds a bare clone
# (xemu.git), subprojects/<name> checkouts and packagecache/ archives fetched from Windows.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
BASE="$(awk '/^base:/{print $2}' "$XEMUPS4/patches/BASE.txt")"
MIRROR="${XEMU_MIRROR:-/mnt/e/xemu-src}"
mkdir -p "$PSB/src"
if [ ! -d "$XEMU_SRC/.git" ]; then
    if [ -d "$MIRROR/xemu.git" ]; then
        git clone -q "file://$MIRROR/xemu.git" "$XEMU_SRC"
        git -C "$XEMU_SRC" remote set-url origin https://github.com/xemu-project/xemu.git
    else
        git clone -q https://github.com/xemu-project/xemu.git "$XEMU_SRC"
    fi
fi
cd "$XEMU_SRC"
git checkout -q "$BASE"
git log -1 --format='base: %h %ci %s'

# meson subprojects: from the mirror when there, else meson downloads them at configure time
SUBPROJECTS="SPIRV-Reflect VulkanMemoryAllocator genconfig glslang imgui implot keycodemapdb nlohmann_json
             nv2a_vsh_cpu slirp tomlplusplus volk berkeley-softfloat-3 berkeley-testfloat-3 sdl3"
for s in $SUBPROJECTS; do
    if [ ! -e "subprojects/$s" ] && [ -d "$MIRROR/subprojects/$s" ]; then
        cp -a "$MIRROR/subprojects/$s" "subprojects/$s"
    fi
done
mkdir -p subprojects/packagecache
[ -d "$MIRROR/packagecache" ] && cp -n "$MIRROR/packagecache/"* subprojects/packagecache/ 2>/dev/null || true
# wrap-git checkouts made outside meson lack the overlay (patch_directory) meson copies in itself
for s in berkeley-softfloat-3 berkeley-testfloat-3; do
    [ -d "subprojects/$s" ] && cp -rn "subprojects/packagefiles/$s/." "subprojects/$s/" 2>/dev/null || true
done

if [ "${1:-}" != --no-patch ]; then
    git checkout -q -B ps4 "$BASE"
    git apply --index "$XEMUPS4/patches/xemu-ps4.patch"
    git -c user.name=xemu-ps4 -c user.email=xemu-ps4@localhost commit -q -m "xemu-ps4: the PS4 port"
    git log -1 --format='%h %s'
fi
