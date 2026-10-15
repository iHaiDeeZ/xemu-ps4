#!/usr/bin/env bash
# Build xemu for the PS4 in ~/xemups4-build/build/xemu (after configure-xemu.sh) and make
# eboot.bin from it (~/xemups4-build/build/xemu/eboot/).
#   build-xemu.sh [ninja args...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../toolchain/env.sh"
B="$PSB/build/xemu"
MESA="$PSB/build/mesa"

# the PS4 runtime from port/ (heap, crash log, sampler; crt1.o routing all mallocs to the heap)
bash "$HERE/../toolchain/build-port.sh" >/dev/null

# The program's final link, through toolchain/bin/ps4-c++ (as Resonance's ps4-love-style.cmake):
#   - RADV on GNM, whole archives (Mesa's dispatch tables reach entry points through weak symbols)
#   - the system libraries the frontend calls
#   - malloc family to the port heap; large mmaps (TCG's code buffer) from the system flexible
#     pool; the TSC clock; threads on all cores; host names through the PS4 resolver
mesa_libs=(
    src/amd/vulkan/libvulkan_radeon.a src/amd/common/libamd_common.a
    src/amd/compiler/libaco.a src/amd/addrlib/libaddrlib.a src/vulkan/util/libvulkan_util.a
    src/compiler/spirv/libvtn.a src/compiler/nir/libnir.a src/compiler/libcompiler.a
    src/util/libxmlconfig.a src/util/libmesa_util.a src/util/libmesa_util_simd.a
    src/util/libmesa_util_clflush.a src/util/libmesa_util_clflushopt.a src/util/libparson.a
    src/util/blake3/libblake3.a src/c11/impl/libmesa_util_c11.a)
ld=("$PSB/build/port/libxemups4_port.a" -Wl,--whole-archive)
for l in "${mesa_libs[@]}"; do ld+=("$MESA/$l"); done
ld+=(-Wl,--no-whole-archive
    -lSceSysmodule -lSceSystemService -lSceUserService -lSceVideoOut -lSceAudioOut -lScePad
    -lSceNet -lSceCommonDialog -lSceImeDialog)
for fn in malloc free calloc realloc memalign __memalign pthread_once mmap clock_gettime \
          pthread_create getaddrinfo gethostbyname; do
    ld+=("-Wl,--wrap=$fn")
done
export PS4_APP_LDFLAGS="${ld[*]}"
export PS4_CRT1="$PSB/build/port/crt1.o"
export PS4_RT_LIB=
# the ENOSYS stubs toolchain/trim-libc.py took out of libc.a, for what still calls them
export PS4_APP_LDFLAGS_END="$PS4_SYSROOT/lib/libc_enosys.a"

ninja -C "$B" -j"$JOBS" "$@" qemu-system-i386

# ELF -> fake SELF. Program authority ID: the plain homebrew identity, under which RADV gets the
# 4.5 GiB of direct memory (as Resonance); auth info as love-ps4/Resonance.
PAID="${PS4_PAID:-0x3800000000000035}"
AUTHINFO="000000000000000000000000001C004000FF000000000080000000000000000000000000000000000000008000400040000000000000008000000000000000080040FFFF000000F000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
mkdir -p "$B/eboot"
OO_PS4_TOOLCHAIN="$OPENORBIS" "$OPENORBIS/bin/create-fself" -in="$B/qemu-system-i386" \
    -out="$B/eboot/xemu.oelf" --eboot "$B/eboot/eboot.bin" --paid "$PAID" --authinfo "$AUTHINFO"
cmake -DOELF="$B/eboot/xemu.oelf" -P "$HERE/../toolchain/check-oelf.cmake"
python3 "$HERE/../toolchain/check-oelf-data.py" "$B/eboot/xemu.oelf"
ls -la "$B/eboot/eboot.bin"
