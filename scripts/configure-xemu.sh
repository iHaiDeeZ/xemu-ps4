#!/usr/bin/env bash
# Configure xemu (QEMU's configure + meson) for the PS4: i386-softmmu only, the toolchain/bin
# wrappers as compilers, pkg-config confined to our sysroot, no tools/docs/guest agent. Meson's
# build.ninja goes to ~/xemups4-build/build/xemu. Run through ~/xemups4 (no space in the path).
#   configure-xemu.sh [extra configure args...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../toolchain/env.sh"
SRC="${XEMU_SRC:-$PSB/src/xemu}"
BUILD="$PSB/build/xemu"
BIN="$HOME/xemups4/toolchain/bin"

export PKG_CONFIG=pkg-config
export PKG_CONFIG_LIBDIR="$PS4_SYSROOT/lib/pkgconfig:$PS4_SYSROOT/libdata/pkgconfig:$PS4_SYSROOT/share/pkgconfig"
unset PKG_CONFIG_PATH
export AR="$PS4_AR" RANLIB="$PS4_RANLIB" NM="llvm-nm-$CLANG_VER" STRIP="llvm-strip-$CLANG_VER" \
       OBJCOPY="llvm-objcopy-$CLANG_VER" READELF="llvm-readelf-$CLANG_VER" LD="$PS4_LD"

mkdir -p "$BUILD"
cd "$BUILD"
"$SRC/configure" \
    --cross-prefix=x86_64-ps4- --cc="$BIN/ps4-cc" --cxx="$BIN/ps4-c++" --host-cc=gcc \
    --target-list=i386-softmmu \
    --extra-cflags="-DXBOX=1 -march=btver2 -Wno-error=redundant-decls" \
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
    --disable-multiprocess --disable-qom-cast-debug \
    --with-coroutine=sigaltstack --audio-drv-list=sdl \
    "$@"
