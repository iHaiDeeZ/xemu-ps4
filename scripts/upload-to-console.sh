#!/usr/bin/env bash
# Puts an xemu-ps4 package in the console's /data/pkg and removes this app's older packages there
# (ps4-kit's scripts/upload.sh: xemu-ps4-vXX.YY.pkg replaces the other xemu-ps4-v*.pkg).
#   scripts/upload-to-console.sh out/xemu-ps4-vXX.YY.pkg [console-ip]
# Run it from Windows (Git Bash), not from WSL: uploads sent from inside WSL were undone on the
# console. The console: the argument, PS4_HOST, or 192.168.0.90 (where /data/xemu has the BIOS,
# the hard disk image and the games).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="${PS4_KIT_WIN:-$HERE/../../ps4-kit}"
exec bash "$KIT/scripts/upload.sh" "${1:?package path}" "${2:-${PS4_HOST:-192.168.0.90}}"
