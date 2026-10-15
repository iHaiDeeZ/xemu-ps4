#!/usr/bin/env bash
# Cross-build xemu's libraries that the seeded sysroot lacks, into $PS4_SYSROOT.
#   build-deps.sh [venv|overlay|vulkan|samplerate|pixman|glib|all]...
# Sources go to ~/xemups4-build/src/deps, builds to ~/xemups4-build/build/<name>.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../toolchain/env.sh"
DEPS="$PSB/src/deps"
VENV="$PSB/venv"
CROSS="$PSB/ps4-cross.ini"
mkdir -p "$DEPS" "$PSB/build"
export PKG_CONFIG_LIBDIR="$PS4_SYSROOT/lib/pkgconfig:$PS4_SYSROOT/libdata/pkgconfig:$PS4_SYSROOT/share/pkgconfig"
unset PKG_CONFIG_PATH

PIXMAN_VER=0.46.4
GLIB_VER=2.84.4

fetch() {   # fetch <url> <dir name>
    local url="$1" dir="$2"
    [ -d "$DEPS/$dir" ] && return
    local f="$DEPS/$(basename "$url")"
    [ -f "$f" ] || curl -fL --retry 3 -o "$f" "$url"
    tar -C "$DEPS" -xf "$f"
}

meson_build() {     # meson_build <src> <build name> <meson options...>
    local src="$1" name="$2"; shift 2
    local b="$PSB/build/$name"
    rm -rf "$b"
    "$VENV/bin/meson" setup "$b" "$src" --cross-file "$CROSS" --prefix "$PS4_SYSROOT" --libdir lib \
        --buildtype release -Ddefault_library=static --wrap-mode=default "$@"
    ninja -C "$b" -j"$JOBS"
    ninja -C "$b" install
}

dep_venv() {
    [ -x "$VENV/bin/meson" ] && return
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q "$PSB/src/xemu/python/wheels/"meson-*.whl packaging
    bash "$HERE/../toolchain/make-meson-cross.sh"
}

# libc overlay additions + libps4compat.a (toolchain/xemu-overlay.sh)
dep_overlay() { bash "$HERE/../toolchain/xemu-overlay.sh"; }

# Vulkan headers (the API RADV implements: Mesa's include/vulkan, VK_HEADER_VERSION 335)
dep_vulkan() {
    local mesa_src="${MESA_SRC:-$HOME/cemups4-build/src/mesa}"
    mkdir -p "$PS4_SYSROOT/include"
    cp -r "$mesa_src/include/vulkan" "$mesa_src/include/vk_video" "$PS4_SYSROOT/include/"
    mkdir -p "$PS4_SYSROOT/lib/pkgconfig"
    local ver
    ver="$(awk '/define VK_HEADER_VERSION /{print $3}' "$PS4_SYSROOT/include/vulkan/vulkan_core.h")"
    # no library: RADV is linked into the eboot (toolchain/ps4-love-style.cmake: ps4_link_mesa)
    cat > "$PS4_SYSROOT/lib/pkgconfig/vulkan.pc" <<PC
prefix=$PS4_SYSROOT
includedir=\${prefix}/include
Name: vulkan
Description: Vulkan headers (RADV on GNM is linked into the eboot)
Version: 1.4.$ver
Cflags: -I\${includedir}
PC
}

# libsamplerate: PacBrew's PS4 build (plain C, static)
dep_samplerate() {
    local pb="$OPENORBIS/usr"
    cp "$pb/include/samplerate.h" "$PS4_SYSROOT/include/"
    cp "$pb/lib/libsamplerate.a" "$PS4_SYSROOT/lib/"
    sed -e "s|^prefix=.*|prefix=$PS4_SYSROOT|" "$pb/lib/pkgconfig/samplerate.pc" > "$PS4_SYSROOT/lib/pkgconfig/samplerate.pc"
}

dep_pixman() {
    fetch "https://cairographics.org/releases/pixman-$PIXMAN_VER.tar.gz" "pixman-$PIXMAN_VER"
    meson_build "$DEPS/pixman-$PIXMAN_VER" pixman -Dtests=disabled -Ddemos=disabled -Dgtk=disabled \
        -Dlibpng=disabled -Dopenmp=disabled -Da64-neon=disabled -Darm-simd=disabled -Dneon=disabled \
        -Dmips-dspr2=disabled -Dloongson-mmi=disabled -Dvmx=disabled -Drvv=disabled
}

dep_glib() {
    fetch "https://download.gnome.org/sources/glib/${GLIB_VER%.*}/glib-$GLIB_VER.tar.xz" "glib-$GLIB_VER"
    # libffi (gobject) and pcre2 come from glib's wraps; libffi's meson port lists no FreeBSD
    ( cd "$DEPS/glib-$GLIB_VER" && "$VENV/bin/meson" subprojects download libffi pcre2 proxy-libintl )
    sed -i "s/\['darwin', 'ios', 'linux', 'android'\].contains(host_system)/['darwin', 'ios', 'linux', 'android', 'freebsd'].contains(host_system)/"         "$DEPS/glib-$GLIB_VER/subprojects/libffi/meson.build"
    meson_build "$DEPS/glib-$GLIB_VER" glib -Dtests=false -Dintrospection=disabled -Dnls=disabled \
        -Dlibmount=disabled -Dselinux=disabled -Dxattr=false -Dman-pages=disabled -Ddtrace=disabled \
        -Dsystemtap=disabled -Dsysprof=disabled -Ddocumentation=false -Dbsymbolic_functions=false \
        -Dglib_debug=disabled -Dglib_assert=false -Dglib_checks=false -Dinstalled_tests=false \
        -Dlibelf=disabled -Dfile_monitor_backend=auto -Dpcre2:jit=disabled -Dpcre2:grep=false -Dpcre2:test=false
}

[ $# -eq 0 ] && set -- all
for d in "$@"; do
    if [ "$d" = all ]; then
        for x in venv overlay vulkan samplerate pixman glib; do echo "== $x"; "dep_$x"; done
    else
        echo "== $d"; "dep_$d"
    fi
done
