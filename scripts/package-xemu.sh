#!/usr/bin/env bash
# Package the PS4 xemu build (after build-xemu.sh) as XEMU00001
# (IV0000-XEMU00001_00-XEMUPS4000000000.pkg: the IDs stay, so an update installs over earlier
# builds and keeps /data/xemu).
#   XEMU_VERSION=00.01 package-xemu.sh
# Older builds are deleted from out/. The console gets the package from Windows with
# scripts/upload-to-console.sh (uploads sent from WSL were lost on the console).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/ps4-env.sh"
B="$PS4_BUILD_ROOT/build/xemu"
EBOOT="$B/eboot/eboot.bin"
VERSION="${XEMU_VERSION:-00.01}"

[ -f "$EBOOT" ] || { echo "missing $EBOOT: build first" >&2; exit 1; }
[[ "$VERSION" =~ ^[0-9][0-9]\.[0-9][0-9]$ ]] || { echo "version must look like 00.01" >&2; exit 1; }
STAGE="$PS4_BUILD_ROOT/build/xemu-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/sce_sys"
cp "$EBOOT" "$STAGE/eboot.bin"
cp "$HERE/../sce_sys/icon0.png" "$HERE/../sce_sys/pic1.png" "$STAGE/sce_sys/"
echo "$VERSION" > "$STAGE/version.txt"
# PkgTool's pkg_build crashes ("Sequence contains no elements") on empty folders.
find "$STAGE" -type d -empty -delete
# Vulkan (RADV on GNM) runs under the plain homebrew identity (4.5 GiB of direct memory).
PKG="$(SFO_STYLE=plain NO_RIGHT_SPRX=1 DOLPHIN_PS4_MODULES_DIR=/nonexistent "$HERE/make-pkg.sh" "$STAGE" XEMU00001 "xemu" "$VERSION" XEMUPS4 "$PS4_BUILD_ROOT/out" | tail -1)"
ls -la "$PKG"
# a copy next to the repo (E:\PS4 Projects\xemu-ps4\out), easy to find from Windows; *.pkg is ignored by git
mkdir -p "$HERE/../out"
NAME="xemu-ps4-v$VERSION.pkg"
cp "$PKG" "$HERE/../out/$NAME"
find "$HERE/../out" -maxdepth 1 -name '*.pkg' ! -name "$NAME" -print -delete | sed 's|^|removed old |'
# Keep the symbols of every packaged build: crash logs must be symbolized against the exact binary.
mkdir -p "$PS4_BUILD_ROOT/oelf"
cp "$B/eboot/xemu.oelf" "$PS4_BUILD_ROOT/oelf/v$VERSION.oelf"
cp "$B/qemu-system-i386" "$PS4_BUILD_ROOT/oelf/v$VERSION.elf"
echo "out/$NAME"
