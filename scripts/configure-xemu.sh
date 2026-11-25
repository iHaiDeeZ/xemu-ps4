#!/usr/bin/env bash
# Configure xemu (QEMU's configure + meson) for the PS4: i386-softmmu only, the toolchain/bin
# wrappers as compilers, pkg-config confined to this port's sysroot, no tools/docs/guest agent, no
# rust. Meson's build.ninja goes to ~/xemups4-build/build/xemu.
#   configure-xemu.sh [extra configure args...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
BIN="$XEMUPS4/toolchain/bin"

export PKG_CONFIG=pkg-config
export PKG_CONFIG_LIBDIR="$PS4_SYSROOT/lib/pkgconfig:$PS4_SYSROOT/libdata/pkgconfig:$PS4_SYSROOT/share/pkgconfig"
unset PKG_CONFIG_PATH
export AR="$PS4_AR" RANLIB="$PS4_RANLIB" NM="llvm-nm-$CLANG_VER" STRIP="llvm-strip-$CLANG_VER" \
       OBJCOPY="llvm-objcopy-$CLANG_VER" READELF="llvm-readelf-$CLANG_VER" LD="$PS4_LD"
# link probes see the C library's resolver and the compat library, as the final link will
export PS4_APP_LDFLAGS="-lSceNet $PS4_SYSROOT/lib/libps4compat.a"
export PS4_RT_LIB=

mkdir -p "$XEMU_BUILD"
cd "$XEMU_BUILD"
"$XEMU_SRC/configure" \
    --cross-prefix=x86_64-ps4- --cc="$BIN/ps4-cc" --cxx="$BIN/ps4-c++" --host-cc=gcc \
    --target-list=i386-softmmu \
    --extra-cflags="-DXBOX=1 -march=btver2 -Wno-error=redundant-decls -I$PS4_KIT/runtime" \
    --extra-cxxflags="-I$PS4_KIT/runtime" \
    --disable-werror --disable-docs --disable-tools --disable-guest-agent --disable-rust \
    --disable-plugins --disable-curl --disable-vnc --disable-gtk --disable-spice --enable-slirp \
    --disable-capstone --disable-keyring --disable-libudev --disable-alsa --disable-oss --disable-pa \
    --disable-pipewire --disable-jack --disable-sndio --disable-tpm --disable-vhost-user \
    --disable-vhost-net --disable-vhost-kernel --disable-vhost-vdpa --disable-linux-aio \
    --disable-linux-io-uring --disable-bpf --disable-seccomp --disable-cap-ng --disable-attr \
    --disable-libssh --disable-libnfs --disable-rbd --disable-glusterfs --disable-libiscsi \
    --disable-zstd --disable-bzip2 --disable-lzo --disable-snappy --disable-lzfse \
    --disable-gnutls --disable-nettle --disable-gcrypt --disable-crypto-afalg --disable-auth-pam \
    --disable-libusb --disable-usb-redir --disable-smartcard --disable-u2f --disable-virglrenderer \
    --disable-opengl --disable-png --disable-vte --disable-xkbcommon --disable-dbus-display \
    --disable-multiprocess --disable-qom-cast-debug --disable-download \
    --with-coroutine=sigaltstack --audio-drv-list=sdl \
    "$@"
