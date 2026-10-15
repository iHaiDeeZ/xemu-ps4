#!/usr/bin/env bash
# Builds the PS4 runtime from port/ (heap over dlmalloc, crash log, sampler, string/random/net
# fixes; from Resonance) into $PSB/build/port/libxemups4_port.a, and port/ps4_crt1.S (crt1.o
# routing every malloc of the process, system modules included, to that heap) into
# $PSB/build/port/crt1.o. Linked into the eboot by scripts/build-xemu.sh (PS4_APP_LDFLAGS).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
PORT="$HERE/../port"
OBJ="$PSB/build/port"
mkdir -p "$OBJ"
objs=()
for src in ps4_runtime.cpp ps4_dlmalloc.c ps4_crashlog.cpp ps4_sampler.cpp ps4_string.c ps4_random.c ps4_net.cpp; do
    o="$OBJ/${src%.*}.o"
    case "$src" in
    *.cpp) "$HERE/bin/ps4-c++" -std=c++20 -O2 -march=btver2 -c "$PORT/$src" -o "$o" ;;
    *.c) "$HERE/bin/ps4-cc" -std=gnu11 -O2 -march=btver2 -I"$PORT/third_party" -c "$PORT/$src" -o "$o" ;;
    esac
    objs+=("$o")
done
rm -f "$OBJ/libxemups4_port.a"
"$PS4_AR" rcs "$OBJ/libxemups4_port.a" "${objs[@]}"
"$PS4_CC" --target="$PS4_TARGET" -c "$PORT/ps4_crt1.S" -o "$OBJ/crt1.o"
echo "built $OBJ/libxemups4_port.a and $OBJ/crt1.o"
