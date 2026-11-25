# xemu-ps4 build settings: ps4-kit's toolchain (clang 21 + libc++ 21 on the OpenOrbis C runtime,
# RADV on GNM) with this port's own build tree and sysroot. Source it from the other scripts.
#
#   ~/xemups4          space-free link to this repo (linker flags break on "PS4 Projects")
#   ~/ps4-kit          the kit (github.com/iHaiDeeZ/ps4-kit): toolchain, runtime, Mesa patches
#   ~/xemups4-build    sources, builds, sysroot (a copy of the kit's + glib, pixman, SDL3, ...)
#   ~/ps4kit-build     the kit's RADV build (gpu/build-mesa.sh), linked into the eboot

export XEMUPS4="${XEMUPS4:-$HOME/xemups4}"
export PS4_KIT="${PS4_KIT:-$HOME/ps4-kit}"
export PSB="${PSB:-$HOME/xemups4-build}"
export PS4_SYSROOT="${PS4_SYSROOT:-$PSB/sysroot}"
export PS4_MESA_BUILD="${PS4_MESA_BUILD:-$HOME/ps4kit-build/build/mesa}"
export PS4_MESA_SRC="${PS4_MESA_SRC:-$HOME/ps4kit-build/src/mesa}"
# shellcheck disable=SC1091
source "$PS4_KIT/toolchain/env.sh"
export XEMU_SRC="${XEMU_SRC:-$PSB/src/xemu}"
export XEMU_BUILD="${XEMU_BUILD:-$PSB/build/xemu}"
