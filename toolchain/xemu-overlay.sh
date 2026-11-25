#!/usr/bin/env bash
# xemu's additions to this port's sysroot (idempotent), on top of the kit's libc overlay (which has
# sys/event.h and the dirent.h d_ino fix since the kit merged them from this port):
#   - declarations for libps4compat.a (port/ps4_compat.c: closefrom, uname, res_query, ...) and the
#     library itself, also installed as libresolv.a (GIO links it by name)
#   - FreeBSD's SCM_CREDS/struct cmsgcred (GIO's gcredentials.c) and SOCK_CLOEXEC/SOCK_NONBLOCK
#   - libc.a without its ENOSYS stubs (toolchain/trim-libc.py): configure and meson link probes
#     otherwise "find" ppoll, timerfd, epoll, inotify, memfd_create, ...; the stubs go to
#     libc_enosys.a, linked last into the eboot only
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../scripts/env.sh"
O="$PS4_SYSROOT/libc-overlay"

if ! grep -q _XEMUPS4_UNISTD_H "$O/unistd.h" 2>/dev/null; then
    [ -f "$O/unistd.h" ] || printf '#include_next <unistd.h>\n' > "$O/unistd.h"
    cat >> "$O/unistd.h" <<'H'
/* xemu-ps4: FreeBSD functions provided by libps4compat.a (port/ps4_compat.c) */
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

OBJ="$PSB/build/compat"
mkdir -p "$OBJ"
"$XEMUPS4/toolchain/bin/ps4-cc" -std=gnu11 -O2 -Wall -c "$XEMUPS4/port/ps4_compat.c" -o "$OBJ/ps4_compat.o"
for lib in libps4compat.a libresolv.a; do
    rm -f "$PS4_SYSROOT/lib/$lib"
    "$PS4_AR" rcs "$PS4_SYSROOT/lib/$lib" "$OBJ/ps4_compat.o"
done
# libc.a without the ENOSYS stubs, ahead of OpenOrbis' on the wrappers' library path
python3 "$HERE/trim-libc.py" "$OPENORBIS/lib/libc.a" "$PS4_SYSROOT/lib/libc.a" "$PS4_SYSROOT/lib/libc_enosys.a"
echo "xemu overlay installed"
