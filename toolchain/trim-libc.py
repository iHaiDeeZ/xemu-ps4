#!/usr/bin/env python3
"""Writes a copy of OpenOrbis' libc.a without its ENOSYS stubs.

The OpenOrbis C library is musl with the Linux-only calls (ppoll, timerfd, inotify, epoll,
setns, ...) compiled as stubs that set errno = ENOSYS and fail. Build systems probing with
link tests (meson's has_function, CMake's check_symbol_exists) then believe the PS4 has them,
and xemu would e.g. run its main loop on ppoll. Without the stubs those probes fail and any
remaining use shows up as a link error.

    trim-libc.py <libc.a in> <libc.a out> [<stubs.a out>]

The removed members also go to <stubs.a out> (minus those libps4compat.a implements): the app's
final link takes them last, as OpenOrbis' libc would have provided them (Mesa's and QEMU's
fallbacks call them and cope with ENOSYS).
"""
import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile

LLVM = os.environ.get("CLANG_VER", "21")
# Stubs other libc members call (freopen -> __dup3, utime -> utimensat) or that sit next to
# functions the rest of libc needs (the thread-list lock): kept, still failing with ENOSYS.
# uname (gethostname) has a real implementation in libps4compat.a instead.
KEEP = {"membarrier.lo", "mremap.lo", "dup3.lo", "utimensat.lo"}
# implemented for real in libps4compat.a (toolchain/runtime/ps4_compat.c)
COMPAT = {"uname.lo", "readlink.lo", "link.lo", "symlink.lo", "chown.lo", "lchown.lo",
          "fchown.lo", "fstatat.lo", "umask.lo"}


def stub_members(lib):
    out = subprocess.run([f"llvm-objdump-{LLVM}", "-dr", "--no-show-raw-insn", lib],
                         capture_output=True, text=True, check=True).stdout
    member = func = None
    bodies = {}
    for line in out.splitlines():
        m = re.match(r"^\S+\((\S+)\):\s+file format", line)
        if m:
            member = m.group(1)
            continue
        m = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
        if m:
            func = (member, m.group(1))
            bodies[func] = []
            continue
        if func and re.match(r"^\s*[0-9a-f]+:", line):
            bodies[func].append(line)
    stubs = collections.defaultdict(set)
    for (mem, name), body in bodies.items():
        text = "\n".join(body)
        if "$0x4e" in text and "___errno_location" in text and len(body) <= 8:  # ENOSYS = 78
            stubs[mem].add(name)
    return {m for m in stubs if m not in KEEP}


def main():
    src, dst = sys.argv[1], sys.argv[2]
    drop = stub_members(src)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    subprocess.run([f"llvm-ar-{LLVM}", "d", tmp, *sorted(drop)], check=True)
    os.replace(tmp, dst)
    print(f"{dst}: {len(drop)} stub members removed")
    if len(sys.argv) > 3:
        stubs = sys.argv[3]
        with tempfile.TemporaryDirectory() as d:
            members = sorted(drop - COMPAT)
            subprocess.run([f"llvm-ar-{LLVM}", "x", os.path.abspath(src), *members], cwd=d, check=True)
            if os.path.exists(stubs):
                os.remove(stubs)
            subprocess.run([f"llvm-ar-{LLVM}", "rcs", stubs, *[os.path.join(d, m) for m in members]],
                           check=True)
        print(f"{stubs}: {len(members)} ENOSYS stubs for the final link")


if __name__ == "__main__":
    main()
