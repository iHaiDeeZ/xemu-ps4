#!/usr/bin/env bash
# The translated-code round trip with the console (run from Windows Git Bash; the build runs in WSL):
#   aot-console.sh fetch  <title ID> [console]   /data/xemu/aot/<ID>/ -> aot-data/<ID>/
#   aot-console.sh build  <title ID>             aot-data/<ID>/ -> out/aot/<ID>.aot (scripts/aot-build.py)
#   aot-console.sh upload <title ID> [console]   out/aot/<ID>.aot -> /data/xemu/aot/<ID>.aot
#   aot-console.sh all    <title ID> [console]   the three
#   aot-console.sh list   [console]              recordings on the console
# The title ID is the XBE certificate's, 8 hex digits (the folder name xemu records into; Halo 2
# is 4d530064). aot-data/ and out/aot/ hold the game's code as C and compiled: never commit or
# share them (.gitignore).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cmd="${1:?fetch|build|upload|all|list}"
if [ "$cmd" = list ]; then
    ip="${2:-${PS4_HOST:-192.168.0.90}}"
    curl -s --max-time 20 "ftp://$ip:2121/data/xemu/aot/"
    exit 0
fi
title="${2:?title ID (8 hex digits)}"
ip="${3:-${PS4_HOST:-192.168.0.90}}"
ftp="ftp://$ip:2121/data/xemu/aot"
data="$REPO/aot-data/$title"
CR="$(printf '\r')"

fetch() {
    mkdir -p "$data"
    local names
    # the console's FTP server ends each name with CR LF
    names="$(curl -s --max-time 30 --list-only "$ftp/$title/" | tr -d "$CR")" ||
        { echo "no $ftp/$title/" >&2; exit 1; }
    for f in $names; do
        case "$f" in
            blocks-*.c|aot_abi.h)
                # sizes differ = the console wrote more since: fetch again
                local remote local_size
                remote="$(curl -s --max-time 20 -I "$ftp/$title/$f" | tr -d "$CR" | awk '/Content-Length/ {print $2}')"
                local_size="$( [ -f "$data/$f" ] && stat -c %s "$data/$f" || echo -1)"
                if [ "$remote" != "$local_size" ]; then
                    echo "fetching $f ($remote bytes)"
                    curl -s --max-time 600 -o "$data/$f" "$ftp/$title/$f"
                fi
                ;;
        esac
    done
    du -sh "$data"
}

build() {
    mkdir -p "$REPO/out/aot"
    # the work dir (generated C and objects) stays in WSL's own file system: faster than /mnt
    MSYS_NO_PATHCONV=1 wsl -e bash -lc "cd ~/xemups4 && python3 scripts/aot-build.py aot-data/$title \
        -o out/aot/$title.aot --title $title --work ~/xemups4-build/aot-work/$title"
}

upload() {
    local f="$REPO/out/aot/$title.aot"
    [ -f "$f" ] || { echo "no $f: build first" >&2; exit 1; }
    curl -s --max-time 600 -T "$f" "$ftp/$title.aot" && echo "uploaded $(basename "$f") to $ip"
}

case "$cmd" in
    fetch) fetch ;;
    build) build ;;
    upload) upload ;;
    all) fetch; build; upload ;;
    *) echo "unknown command $cmd" >&2; exit 1 ;;
esac
