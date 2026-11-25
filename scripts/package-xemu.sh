#!/usr/bin/env bash
# Package the PS4 xemu build (after build-xemu.sh) as XEMU00001 with ps4-kit's make-pkg.sh
# (IV0000-XEMU00001_00-XEMUPS4000000000.pkg: the IDs stay, so an update installs over earlier
# builds and keeps /data/xemu). Copies it to out/xemu-ps4-vXX.YY.pkg in this repo (older ones there
# are kept) and keeps the build's symbols in ~/xemups4-build/oelf/vXX.YY.elf for crash logs.
#   XEMU_VERSION=00.16 package-xemu.sh
# The console gets the package from Windows (Git Bash): scripts/upload-to-console.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
B="$XEMU_BUILD"
EBOOT="$B/eboot/eboot.bin"
VERSION="${XEMU_VERSION:?XEMU_VERSION=XX.YY}"

[ -f "$EBOOT" ] || { echo "missing $EBOOT: build first" >&2; exit 1; }
[[ "$VERSION" =~ ^[0-9][0-9]\.[0-9][0-9]$ ]] || { echo "version must look like 00.16" >&2; exit 1; }
STAGE="$PSB/build/xemu-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/sce_sys"
cp "$EBOOT" "$STAGE/eboot.bin"
cp "$XEMUPS4/sce_sys/icon0.png" "$XEMUPS4/sce_sys/pic1.png" "$STAGE/sce_sys/"
echo "$VERSION" > "$STAGE/version.txt"
PKG="$(NO_RIGHT_SPRX=1 PSB="$HOME/ps4kit-build" bash "$PS4_KIT/scripts/make-pkg.sh" "$STAGE" XEMU00001 "xemu" "$VERSION" XEMUPS4 "$PSB/out" | tail -1)"
ls -la "$PKG"
mkdir -p "$XEMUPS4/out"
NAME="xemu-ps4-v$VERSION.pkg"
cp "$PKG" "$XEMUPS4/out/$NAME"
mkdir -p "$PSB/oelf"
cp "$B/eboot/xemu.oelf" "$PSB/oelf/v$VERSION.oelf"
cp "$B/qemu-system-i386" "$PSB/oelf/v$VERSION.elf"
echo "out/$NAME"
