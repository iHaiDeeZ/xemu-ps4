#!/usr/bin/env bash
# xemu additions to the sysroot (idempotent): declarations for libps4compat.a in the libc overlay
# and the library itself (toolchain/runtime/ps4_compat.c), also installed as libresolv.a; libc.a
# without its ENOSYS stubs (toolchain/trim-libc.py).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/env.sh"
O="$PS4_SYSROOT/libc-overlay"

if ! grep -q _XEMUPS4_UNISTD_H "$O/unistd.h"; then
    cat >> "$O/unistd.h" <<'H'
/* xemu-ps4: FreeBSD functions provided by libps4compat.a (toolchain/runtime/ps4_compat.c) */
#ifndef _XEMUPS4_UNISTD_H
#define _XEMUPS4_UNISTD_H
#ifdef __cplusplus
extern "C" {
#endif
void closefrom(int lowfd);
#ifdef __cplusplus
}
#endif
#endif
H
fi

if ! grep -q _XEMUPS4_SOCKET_H "$O/sys/socket.h"; then
    cat >> "$O/sys/socket.h" <<'H'
/* xemu-ps4: FreeBSD's SCM_CREDS message (GIO's gcredentials.c takes its FreeBSD path) */
#ifndef _XEMUPS4_SOCKET_H
#define _XEMUPS4_SOCKET_H
#ifndef SCM_CREDS
#define SCM_CREDS 0x03
#endif
/* FreeBSD 10's socket type flags: the C library's accept4 is an ENOSYS stub, and callers
   retry without them when socket() refuses them (EINVAL) */
#ifndef SOCK_CLOEXEC
#define SOCK_CLOEXEC 0x10000000
#endif
#ifndef SOCK_NONBLOCK
#define SOCK_NONBLOCK 0x20000000
#endif
#define CMGROUP_MAX 16
struct cmsgcred {
	pid_t cmcred_pid;
	uid_t cmcred_uid;
	uid_t cmcred_euid;
	gid_t cmcred_gid;
	short cmcred_ngroups;
	gid_t cmcred_groups[CMGROUP_MAX];
};
#endif
H
fi

# FreeBSD's d_ino alias for the PS4's struct dirent (d_fileno)
cat > "$O/dirent.h" <<'H'
/* xemu-ps4: the PS4's struct dirent is FreeBSD 9's (member d_fileno), but OpenOrbis' dirent.h
   then defines d_fileno as d_ino, so neither name reaches the member. FreeBSD's alias instead. */
#include_next <dirent.h>
#undef d_fileno
#ifndef d_ino
#define d_ino d_fileno
#endif
H

# whole headers OpenOrbis lacks (toolchain/overlay)
cp -r "$HERE/overlay/." "$O/"

OBJ="$PSB/build/runtime"
mkdir -p "$OBJ"
"$HERE/bin/ps4-cc" -std=gnu11 -O2 -Wall -c "$HERE/runtime/ps4_compat.c" -o "$OBJ/ps4_compat.o"
for lib in libps4compat.a libresolv.a; do
    rm -f "$PS4_SYSROOT/lib/$lib"
    "$PS4_AR" rcs "$PS4_SYSROOT/lib/$lib" "$OBJ/ps4_compat.o"
done
# libc.a without the ENOSYS stubs, ahead of OpenOrbis' on the wrappers' library path
python3 "$HERE/trim-libc.py" "$OPENORBIS/lib/libc.a" "$PS4_SYSROOT/lib/libc.a" "$PS4_SYSROOT/lib/libc_enosys.a"
# the link script for PS4 programs (toolchain/bin/ps4-cc)
python3 "$HERE/make-link-script.py" "$OPENORBIS/link.x" "$PS4_SYSROOT/lib/ps4-link.x" >/dev/null
echo "xemu overlay installed"
