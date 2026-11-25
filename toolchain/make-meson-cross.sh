#!/usr/bin/env bash
# Writes $PSB/ps4-cross.ini: the meson cross file for xemu and its dependencies. Compiles and links
# through toolchain/bin/ps4-cc / ps4-c++ (ps4-kit's wrappers: OpenOrbis CRT + C library, clang 21,
# libc++ 21), pkg-config confined to this port's sysroot, CMake subprojects (glslang, volk,
# SPIRV-Reflect) with toolchain/ps4-xemu.cmake.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../scripts/env.sh"
BIN="$XEMUPS4/toolchain/bin"
mkdir -p "$PSB"
cat > "$PSB/ps4-cross.ini" <<INI
[binaries]
c = '$BIN/ps4-cc'
cpp = '$BIN/ps4-c++'
objc = '$BIN/ps4-cc'
ar = '$PS4_AR'
ranlib = '$PS4_RANLIB'
strip = 'llvm-strip-$CLANG_VER'
nm = 'llvm-nm-$CLANG_VER'
pkg-config = 'pkg-config'
cmake = 'cmake'

[properties]
needs_exe_wrapper = true
pkg_config_libdir = ['$PS4_SYSROOT/lib/pkgconfig', '$PS4_SYSROOT/libdata/pkgconfig', '$PS4_SYSROOT/share/pkgconfig']
cmake_toolchain_file = '$XEMUPS4/toolchain/ps4-xemu.cmake'

[built-in options]
c_args = ['-march=btver2']
cpp_args = ['-march=btver2']

[host_machine]
system = 'freebsd'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
INI
echo "$PSB/ps4-cross.ini"
