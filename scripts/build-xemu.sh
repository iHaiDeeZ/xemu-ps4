#!/usr/bin/env bash
# Build xemu for the PS4 in ~/xemups4-build/build/xemu (after configure-xemu.sh) and make eboot.bin
# from it (~/xemups4-build/build/xemu/eboot/).
#   build-xemu.sh [ninja args...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
B="$XEMU_BUILD"

# Meson regenerates its build files (and reruns its CMake subprojects' compiler checks) when a
# meson.build changed: that has to happen with the configure-time link flags, not the eboot's
# below (the kit runtime's C++ made every check program fail to link).
PS4_APP_LDFLAGS="-lSceNet $PS4_SYSROOT/lib/libps4compat.a" PS4_RT_LIB= ninja -C "$B" build.ninja

# ps4-kit's runtime and presenter (port/CMakeLists.txt -> libxemups4_port.a, kit-link.env)
P="$PSB/build/port"
if [ ! -f "$P/build.ninja" ]; then
    ps4_cmake -S "$XEMUPS4/port" -B "$P" -G Ninja -DPS4_MESA_BUILD="$PS4_MESA_BUILD" -DPS4_MESA_SRC="$PS4_MESA_SRC"
fi
ninja -C "$P" >/dev/null
# shellcheck disable=SC1091
source "$P/kit-link.env"

# The program's final link, through toolchain/bin/ps4-c++ (as ps4_kit_app() links an app):
#   - the kit's runtime and presenter, whole (their __wrap_ functions must always be linked)
#   - RADV on GNM, whole archives (Mesa's dispatch tables reach entry points through weak symbols)
#   - the system libraries the frontend calls, /net's protocol libraries, the compat library
#   - the kit's --wrap list: malloc family to the kit heap, large mmaps, the TSC clock, threads on
#     the app's cores, the PS4 resolver, the file layer, one lock around stdio, exit -> the shell
mesa_libs=(
    src/amd/vulkan/libvulkan_radeon.a src/amd/common/libamd_common.a
    src/amd/compiler/libaco.a src/amd/addrlib/libaddrlib.a src/vulkan/util/libvulkan_util.a
    src/compiler/spirv/libvtn.a src/compiler/nir/libnir.a src/compiler/libcompiler.a
    src/util/libxmlconfig.a src/util/libmesa_util.a src/util/libmesa_util_simd.a
    src/util/libmesa_util_clflush.a src/util/libmesa_util_clflushopt.a src/util/libparson.a
    src/util/blake3/libblake3.a src/c11/impl/libmesa_util_c11.a)
ld=(-Wl,--whole-archive "$P/libxemups4_port.a")
for l in "${mesa_libs[@]}"; do ld+=("$PS4_MESA_BUILD/$l"); done
ld+=(-Wl,--no-whole-archive
    "$PS4_SYSROOT/lib/libsmb2.a" "$PS4_SYSROOT/lib/libnfs.a" "$PS4_SYSROOT/lib/libz.a"
    "$PS4_SYSROOT/lib/libps4compat.a"
    -lSceSysmodule -lSceSystemService -lSceUserService -lSceVideoOut -lSceAudioOut -lScePad
    -lSceNet -lSceCommonDialog -lSceImeDialog)
for fn in $PS4_KIT_WRAPS $PS4_KIT_APP_WRAPS; do ld+=("-Wl,--wrap=$fn"); done
for fn in $PS4_KIT_STDIO_WRAPS; do ld+=("-Wl,--wrap=$fn" "-Wl,--undefined=$fn"); done
export PS4_APP_LDFLAGS="${ld[*]}"
export PS4_CRT1="$PS4_KIT_CRT1"
export PS4_LINK_SCRIPT="$PS4_KIT/toolchain/ps4-link.x"
export PS4_RT_LIB=
# the ENOSYS stubs toolchain/trim-libc.py took out of libc.a, for what still calls them
export PS4_APP_LDFLAGS_END="$PS4_SYSROOT/lib/libc_enosys.a"

ninja -C "$B" -j"$JOBS" "$@" qemu-system-i386

# ELF -> fake SELF, under the plain homebrew identity (RADV gets the 4.5 GiB of direct memory)
mkdir -p "$B/eboot"
OO_PS4_TOOLCHAIN="$OPENORBIS" "$OPENORBIS/bin/create-fself" -in="$B/qemu-system-i386" \
    -out="$B/eboot/xemu.oelf" --eboot "$B/eboot/eboot.bin" --paid "$PS4_KIT_PAID" --authinfo "$PS4_KIT_AUTH_INFO"
cmake -DOELF="$B/eboot/xemu.oelf" -P "$PS4_KIT/toolchain/check-oelf.cmake"
ls -la "$B/eboot/eboot.bin"
