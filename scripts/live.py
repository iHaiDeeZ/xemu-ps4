#!/usr/bin/env python3
"""The xemu-ps4 live console from a PC: commands to the running emulator over TCP (ui/ps4/ps4-live.c).

    python scripts/live.py [--host 192.168.0.90] [--port 4445] <command...>
    python scripts/live.py --host 192.168.0.90            (interactive: one command per line)

Commands (the console's own "help"):
    stats                    frame rates, thread loads, main loop, TLB index (the monitor's last line)
    hmp <monitor command>    QEMU's monitor: info registers, x/64xb $eip, xp /32xw 0x..., info tlb,
                             stop, cont, system_reset, ...
    mem <hex addr> [len]     guest physical memory
    profile                  an 8 s CPU profile of the emulation threads (FTP: /data/xemu/profiles)
    dump                     every thread's call stack (FTP: /data/xemu/hang.log)
    get [key] / set <key> <value>   ps4.ini settings (and hrtf)
Several commands in one call: separate them with " ; ".
"""
import argparse
import os
import socket
import sys


def ask(sock, f, line):
    sock.sendall((line.strip() + '\n').encode())
    out = []
    for raw in f:
        text = raw.decode(errors='replace').rstrip('\r\n')
        if text == '.':
            break
        out.append(text)
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default=os.environ.get('PS4_HOST', '192.168.0.90'))
    ap.add_argument('--port', type=int, default=4445)
    ap.add_argument('command', nargs='*')
    a = ap.parse_args()
    sock = socket.create_connection((a.host, a.port), timeout=60)
    f = sock.makefile('rb')
    if a.command:
        for cmd in ' '.join(a.command).split(' ; '):
            print(ask(sock, f, cmd))
    else:
        for line in sys.stdin:
            if line.strip() in ('quit', 'exit'):
                break
            print(ask(sock, f, line))
    sock.sendall(b'quit\n')
    sock.close()


if __name__ == '__main__':
    main()
