#!/usr/bin/env bash
# Cross-build xemu's libraries that the kit's sysroot lacks, into this port's sysroot.
#   build-deps.sh [venv|overlay|vulkan|samplerate|pixman|glib|sdl3|all]...
# Sources in ~/xemups4-build/src/deps (scripts/seed-build-tree.sh unpacks them; with no internet in
# WSL it takes them from the Windows-side mirror, XEMU_MIRROR), builds in ~/xemups4-build/build/<name>.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
DEPS="$PSB/src/deps"
VENV="$PSB/venv"
CROSS="$PSB/ps4-cross.ini"
MIRROR="${XEMU_MIRROR:-/mnt/e/xemu-src}"
mkdir -p "$DEPS" "$PSB/build"
export PKG_CONFIG_LIBDIR="$PS4_SYSROOT/lib/pkgconfig:$PS4_SYSROOT/libdata/pkgconfig:$PS4_SYSROOT/share/pkgconfig"
unset PKG_CONFIG_PATH
# Programs the builds link besides the libraries (glib's gresource, gdbus, ... - never run): the C
# library's resolver calls libSceNet (sceNetGetDnsInfo), and libps4compat.a has the FreeBSD calls
# the C library lacks. (xemu's own link gets both from scripts/build-xemu.sh.)
export PS4_APP_LDFLAGS="-lSceNet $PS4_SYSROOT/lib/libps4compat.a"
export PS4_RT_LIB=

PIXMAN_VER=0.46.4
GLIB_VER=2.84.4

unpack() {   # unpack <archive name> <dir name> <url>
    local file="$1" dir="$2" url="$3"
    [ -d "$DEPS/$dir" ] && [ -f "$DEPS/$dir/meson.build" ] && return
    rm -rf "${DEPS:?}/$dir"
    if [ ! -f "$DEPS/$file" ]; then
        if [ -f "$MIRROR/deps/$file" ]; then cp "$MIRROR/deps/$file" "$DEPS/"; else curl -fL --retry 3 -o "$DEPS/$file" "$url"; fi
    fi
    tar -C "$DEPS" -xf "$DEPS/$file"
}

meson_build() {     # meson_build <src> <build name> <meson options...>
    local src="$1" name="$2"; shift 2
    local b="$PSB/build/$name"
    rm -rf "$b"
    "$VENV/bin/meson" setup "$b" "$src" --cross-file "$CROSS" --prefix "$PS4_SYSROOT" --libdir lib \
        --buildtype release -Ddefault_library=static --wrap-mode=nodownload "$@"
    ninja -C "$b" -j"$JOBS"
    ninja -C "$b" install
}

dep_venv() {
    if [ ! -x "$VENV/bin/meson" ]; then
        rm -rf "$VENV"
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install -q --no-index "$XEMU_SRC/python/wheels/"meson-*.whl
    fi
    "$VENV/bin/meson" --version
    bash "$XEMUPS4/toolchain/make-meson-cross.sh"
}

# libc overlay additions, libps4compat.a, stub-free libc.a (toolchain/xemu-overlay.sh)
dep_overlay() { bash "$XEMUPS4/toolchain/xemu-overlay.sh"; }

# Vulkan headers: the API the kit's RADV implements (its Mesa tree's include/vulkan). No library: RADV
# is linked into the eboot (scripts/build-xemu.sh).
dep_vulkan() {
    mkdir -p "$PS4_SYSROOT/include" "$PS4_SYSROOT/lib/pkgconfig"
    rm -rf "$PS4_SYSROOT/include/vulkan" "$PS4_SYSROOT/include/vk_video"
    cp -r "$PS4_MESA_SRC/include/vulkan" "$PS4_MESA_SRC/include/vk_video" "$PS4_SYSROOT/include/"
    local ver
    ver="$(awk '/define VK_HEADER_VERSION /{print $3}' "$PS4_SYSROOT/include/vulkan/vulkan_core.h")"
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
    unpack "pixman-$PIXMAN_VER.tar.gz" "pixman-$PIXMAN_VER" "https://cairographics.org/releases/pixman-$PIXMAN_VER.tar.gz"
    meson_build "$DEPS/pixman-$PIXMAN_VER" pixman -Dtests=disabled -Ddemos=disabled -Dgtk=disabled \
        -Dlibpng=disabled -Dopenmp=disabled -Da64-neon=disabled -Darm-simd=disabled -Dneon=disabled \
        -Dmips-dspr2=disabled -Dloongson-mmi=disabled -Dvmx=disabled -Drvv=disabled
}

dep_glib() {
    local g="$DEPS/glib-$GLIB_VER"
    unpack "glib-$GLIB_VER.tar.xz" "glib-$GLIB_VER" "https://download.gnome.org/sources/glib/${GLIB_VER%.*}/glib-$GLIB_VER.tar.xz"
    # libffi (gobject), pcre2, proxy-libintl and gvdb come from glib's wraps
    for sp in libffi proxy-libintl gvdb; do
        [ -d "$g/subprojects/$sp" ] || cp -a "$MIRROR/glib-subprojects/$sp" "$g/subprojects/$sp" 2>/dev/null || true
    done
    mkdir -p "$g/subprojects/packagecache"
    cp -n "$MIRROR/glib-packagecache/"* "$g/subprojects/packagecache/" 2>/dev/null || true
    ( cd "$g" && "$VENV/bin/meson" subprojects download libffi pcre2 proxy-libintl gvdb >/dev/null 2>&1 || true )
    # libffi's meson port lists no FreeBSD
    sed -i "s/\['darwin', 'ios', 'linux', 'android'\].contains(host_system)/['darwin', 'ios', 'linux', 'android', 'freebsd'].contains(host_system)/" \
        "$g/subprojects/libffi/meson.build"
    meson_build "$g" glib -Dtests=false -Dintrospection=disabled -Dnls=disabled \
        -Dlibmount=disabled -Dselinux=disabled -Dxattr=false -Dman-pages=disabled -Ddtrace=disabled \
        -Dsystemtap=disabled -Dsysprof=disabled -Ddocumentation=false -Dbsymbolic_functions=false \
        -Dglib_debug=disabled -Dglib_assert=false -Dglib_checks=false -Dinstalled_tests=false \
        -Dlibelf=disabled -Dfile_monitor_backend=auto -Dpcre2:jit=disabled -Dpcre2:grep=false -Dpcre2:test=false
}

# SDL3 at xemu's own revision (subprojects/sdl3.wrap) with the PS4 audio driver (port/sdl3): events,
# gamepads (the DualShock 4 comes in as a virtual joystick, ui/ps4/ps4-pad.c), audio streams. No
# video: the PS4 frontend presents through Vulkan.
dep_sdl3() {
    local src="$DEPS/SDL3"
    rm -rf "$src"
    cp -a "$XEMU_SRC/subprojects/sdl3" "$src"
    python3 "$XEMUPS4/port/sdl3/add-ps4-audio.py" "$src"
    local b="$PSB/build/sdl3"
    rm -rf "$b"
    env -u CFLAGS -u CXXFLAGS -u LDFLAGS cmake -S "$src" -B "$b" -G Ninja \
        -DCMAKE_TOOLCHAIN_FILE="$XEMUPS4/toolchain/ps4-xemu.cmake" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PS4_SYSROOT" -DCMAKE_INSTALL_LIBDIR=lib \
        -DSDL_STATIC=ON -DSDL_SHARED=OFF -DSDL_TEST_LIBRARY=OFF -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF \
        -DSDL_UNIX_CONSOLE_BUILD=ON -DSDL_VIDEO=OFF -DSDL_RENDER=OFF -DSDL_GPU=OFF -DSDL_CAMERA=OFF \
        -DSDL_DIALOG=OFF -DSDL_TRAY=OFF -DSDL_SENSOR=OFF -DSDL_POWER=OFF -DSDL_HIDAPI=ON -DSDL_HIDAPI_LIBUSB=OFF \
        -DSDL_HIDAPI_JOYSTICK=OFF -DSDL_VIRTUAL_JOYSTICK=ON -DSDL_DBUS=OFF -DSDL_IBUS=OFF -DSDL_LIBUDEV=OFF \
        -DSDL_DISKAUDIO=OFF -DSDL_PS4_AUDIO=ON \
        -DSDL_OSS=OFF -DSDL_ALSA=OFF -DSDL_JACK=OFF -DSDL_PIPEWIRE=OFF -DSDL_PULSEAUDIO=OFF \
        -DSDL_SNDIO=OFF -DSDL_LIBICONV=OFF -DSDL_USB=OFF -DSDL_LIBURING=OFF -DSDL_RPATH=OFF
    ninja -C "$b" -j"$JOBS"
    # the kit's SDL3 (the sysroot copy's) goes: headers and library from this build
    rm -rf "$PS4_SYSROOT/include/SDL3" "$PS4_SYSROOT/lib/cmake/SDL3"
    ninja -C "$b" install
    grep -q "SDL_AUDIO_DRIVER_PS4 1" "$b/include-config-release/build_config/SDL_build_config.h" 2>/dev/null ||
        grep -rq "SDL_AUDIO_DRIVER_PS4 1" "$b" --include=SDL_build_config.h ||
        { echo "SDL3 was built without the PS4 audio driver" >&2; exit 1; }
}

[ $# -eq 0 ] && set -- all
for d in "$@"; do
    if [ "$d" = all ]; then
        for x in venv overlay vulkan samplerate pixman glib sdl3; do echo "== $x"; "dep_$x"; done
    else
        echo "== $d"; "dep_$d"
    fi
done
