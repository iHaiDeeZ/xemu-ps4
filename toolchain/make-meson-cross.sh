#!/usr/bin/env bash
# Writes $PSB/ps4-cross.ini: the meson cross file for PS4 dependencies and xemu. Compiles and links
# through toolchain/bin/ps4-cc / ps4-c++ (OpenOrbis CRT + libc, clang 21, libc++ 21), with
# pkg-config confined to our sysroot (and PacBrew's for the few libraries taken from there).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
BIN="$HOME/xemups4/toolchain/bin"     # space-free path to this repo (scripts/seed-build-tree.sh)
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
cmake_toolchain_file = '$HERE/ps4-xemu.cmake'

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
