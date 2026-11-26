#!/usr/bin/env python3
"""The game hooker: looks inside the game running in xemu-ps4 (through the live console) and finds
where the emulated CPU's time goes, down to the game's own code.

    python scripts/hooker.py [--host 192.168.0.90] <command>

    status                      frame rate, thread loads, translated code
    exits [seconds]             why translated code returns to the emulator's main loop (aot exits)
    profile [top]               an 8 s profile of the emulated CPU, by game block: kind of code
                                (x87, SSE, integer), size, memory accesses, and the hottest blocks'
                                guest instructions; writes logs/hooker/hot-<title>.txt for
                                scripts/aot-build.py --hot
    code <addr> [len]           the game's code at a guest virtual address, disassembled
    ab <a.aot> <b.aot> [secs]   A/B timing of two builds of the running game's translated code:
                                each is uploaded and swapped in live (aot load), then measured; the
                                faster one is left loaded
    abset <key> <a> <b> [secs]  A/B timing of a live setting (ps4.ini key, e.g. gpu_blit, async_tex,
                                gpu_module, aot_direct): measured at a, then at b; the faster stays
    nv2a [clear]                the GPU side per frame: Vulkan submits and waits (finish reasons),
                                texture uploads, surface read-backs, and the image blits by shape
                                and by the way they ran (GPU copy or CPU)

The PC side runs on Windows (Git Bash Python); symbols come from WSL's llvm tools and the build's
work dir (~/xemups4-build/aot-work/<title>[-variant]): the one whose build time matches the loaded
file. Reports go to logs/hooker/ (gitignored with logs/).
"""
import argparse
import ftplib
import io
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, 'logs', 'hooker')


# --- the console ------------------------------------------------------------------------------------

class Console:
    def __init__(self, host, port=4445):
        self.host, self.port = host, port

    def ask(self, *commands):
        sock = socket.create_connection((self.host, self.port), timeout=120)
        f = sock.makefile('rb')
        out = []
        for cmd in commands:
            sock.sendall((cmd.strip() + '\n').encode())
            lines = []
            for raw in f:
                text = raw.decode(errors='replace').rstrip('\r\n')
                if text == '.':
                    break
                lines.append(text)
            out.append('\n'.join(lines))
        sock.sendall(b'quit\n')
        sock.close()
        return out if len(out) > 1 else out[0]

    def ftp(self):
        f = ftplib.FTP()
        f.connect(self.host, 2121, timeout=60)
        f.login()
        return f

    def get(self, path):
        buf = io.BytesIO()
        with self.ftp() as f:
            f.retrbinary('RETR ' + path, buf.write)
        return buf.getvalue()

    def put(self, path, local):
        with self.ftp() as f, open(local, 'rb') as src:
            f.storbinary('STOR ' + path, src, blocksize=1 << 20)

    def listdir(self, path):
        with self.ftp() as f:
            try:
                return [n.rsplit('/', 1)[-1] for n in f.nlst(path)]
            except ftplib.error_perm:
                return []


def wsl(cmd):
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    r = subprocess.run(['wsl', '-e', 'bash', '-lc', cmd], capture_output=True, text=True, env=env)
    return r.stdout + r.stderr


def to_wsl(path):
    p = os.path.abspath(path).replace('\\', '/')
    m = re.match(r'([A-Za-z]):/(.*)', p)
    return f'/mnt/{m.group(1).lower()}/{m.group(2)}' if m else p


def number(pattern, text, default=0.0):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else default


# --- what is loaded -----------------------------------------------------------------------------------

def loaded_aot(con):
    """(title, mapping address, 'built' string) of the translated code in the running xemu."""
    log = con.get('/data/xemu/xemu.log').decode(errors='replace')
    title = re.findall(r'launch: title ID ([0-9a-f]{8})', log)
    addr = re.findall(r'aot: \d+ MiB of executable \w+ memory at (0x[0-9a-f]+)', log)
    built = re.findall(r'aot: \S+: \d+ translated blocks, \d+ helpers, built ([0-9-]+ [0-9:]+)', log)
    return (title[-1] if title else None, int(addr[-1], 16) if addr else None,
            built[-1] if built else None)


def work_dir_for(title, built):
    """The WSL work dir whose aot_main.c was built at 'built' (several variants may exist)."""
    out = wsl('for d in ~/xemups4-build/aot-work/' + title + '*; do echo "$d" '
              '"$(grep -o \'built\\|[0-9][0-9][0-9][0-9]-[0-9-]* [0-9:]*, [0-9]* blocks\' '
              '"$d/aot_main.c" 2>/dev/null | tail -1)"; done')
    best = None
    for line in out.splitlines():
        parts = line.split(' ', 1)
        if len(parts) == 2 and built and built in parts[1]:
            best = parts[0]
        elif best is None and parts and parts[0].endswith(title):
            best = parts[0]
    return best


# --- commands -----------------------------------------------------------------------------------------

def cmd_status(con, a):
    print(con.ask('stats'))
    print(con.ask('aot'))


def cmd_exits(con, a):
    secs = float(a.args[0]) if a.args else 10.0
    print(con.ask('aot exits on'))
    time.sleep(secs)
    rep = con.ask('aot exits')
    con.ask('aot exits off')
    print(rep)
    save('exits', rep)


def save(kind, text):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{kind}-{time.strftime("%Y%m%d-%H%M%S")}.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n')
    print(f'\n(saved {os.path.relpath(path, REPO)})')
    return path


def guest_code(con, addr, length):
    """objdump of guest virtual memory (QEMU's memsave in the CPU's current address space)."""
    con.ask(f'hmp memsave 0x{addr:x} 0x{length:x} "/data/xemu/tmp/hooker.bin"')
    data = con.get('/data/xemu/tmp/hooker.bin')
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, 'code.bin')
    with open(tmp, 'wb') as f:
        f.write(data)
    out = wsl(f"objdump -D -b binary -m i386 --adjust-vma=0x{addr:x} '{to_wsl(tmp)}'")
    lines = [l for l in out.splitlines() if re.match(r'\s+[0-9a-f]+:', l)]
    return '\n'.join(lines)


def cmd_code(con, a):
    addr = int(a.args[0], 16)
    length = int(a.args[1], 16) if len(a.args) > 1 else 0x100
    print(guest_code(con, addr, length))


def cmd_profile(con, a):
    top = int(a.args[0]) if a.args else 30
    title, start, built = loaded_aot(con)
    if not title or not start:
        sys.exit('no translated code loaded (xemu.log has no aot mapping): start a game from the library')
    work = work_dir_for(title, built)
    print(f'title {title}, translated code at {start:#x} built {built}, symbols from {work}')
    # profile numbers restart with each run of xemu: a new profile can reuse an old file's name,
    # so the new one is the file that appeared or changed size
    before = profile_files(con)
    print(con.ask('profile'))
    time.sleep(11)
    new = None
    for _ in range(20):
        after = profile_files(con)
        cand = sorted((n for n in after if before.get(n) != after[n]),
                      key=lambda n: int(re.sub(r'\D', '', n) or 0))
        if cand:
            new = cand[-1]
            break
        time.sleep(2)
    if new is None:
        sys.exit('no new profile appeared in /data/xemu/profiles')
    os.makedirs(OUT, exist_ok=True)
    local = os.path.join(OUT, f'profile-{time.strftime("%Y%m%d-%H%M%S")}.txt')
    with open(local, 'wb') as f:
        f.write(con.get('/data/xemu/profiles/' + new))
    hot = os.path.join(OUT, f'hot-{title}.txt')
    version = re.findall(r'xemu-ps4 (v[\d.]+)', con.get('/data/xemu/xemu.log').decode(errors='replace'))
    elf = f'~/xemups4-build/oelf/{version[-1] if version else "v00.26"}.elf'
    rep = wsl(f"cd '{to_wsl(REPO)}' && python3 scripts/aot-hotblocks.py '{to_wsl(local)}' {elf} "
              f"{start:x} {work} {top} '--hot-out={to_wsl(hot)}'")
    # regions: name the member blocks
    regions = {}
    for line in wsl(f'cat {work}/regions.txt 2>/dev/null').splitlines():
        p = line.split()
        if p:
            regions[p[0]] = p[1:]
    lines = rep.splitlines()
    text = [f'profile of {title} ({new}), translated code built {built}', ''] + lines
    blocks = []
    for l in lines:
        m = re.search(r'\s(F\d+|R\d+)_([0-9a-f]{8})\s+(\d+)\s+(\d+)', l)
        if m:
            blocks.append((m.group(1) + '_' + m.group(2), int(m.group(2), 16), int(m.group(4))))
    text.append('\nthe hottest blocks in the game\'s code:')
    for name, pc, size in blocks[:min(8, len(blocks))]:
        if name.startswith('R') and name in regions:
            text.append(f'\n{name}: a region of blocks at {" ".join(regions[name])}')
            continue
        text.append(f'\n{name} ({size} bytes):')
        try:
            text.append(guest_code(con, pc, max(size, 16)))
        except Exception as e:      # an unmapped page, a slow console
            text.append(f'  (could not read: {e})')
    # the emulated CPU's and the NV2A's threads: where their time goes, who waits for what
    text.append('\nthreads:')
    text.append(wsl(f"cd '{to_wsl(REPO)}' && python3 scripts/prof-threads.py '{to_wsl(local)}' {elf} "
                    f"{start:x}").rstrip())
    out = '\n'.join(text)
    print(out)
    save('profile-report', out)
    print(f'hot list for aot-build.py --hot: {os.path.relpath(hot, REPO)}')


def profile_files(con):
    """name -> size of /data/xemu/profiles/profile_N.txt"""
    with con.ftp() as f:
        f.cwd('/data/xemu/profiles')
        lines = []
        f.retrlines('LIST', lines.append)
    files = {}
    for line in lines:
        p = line.split()
        if len(p) >= 9 and p[-1].startswith('profile_'):
            files[p[-1]] = p[4]
    return files


def cmd_nv2a(con, a):
    rep = con.ask('nv2a ' + ' '.join(a.args))
    print(rep)
    save('nv2a', rep)


def cmd_abset(con, a):
    if len(a.args) < 3:
        sys.exit('abset <key> <a> <b> [seconds]')
    key, va, vb = a.args[:3]
    secs = float(a.args[3]) if len(a.args) > 3 else 30.0
    results = []
    for v in (va, vb):
        print(f'{key} = {v}: ' + con.ask(f'set {key} {v}').strip())
        time.sleep(8)
        fl, tcg = measure(con, secs)
        print(f'  {fl:.1f} guest flips/s, emulated CPU thread {tcg:.0f}% busy')
        results.append((fl, v))
    best = max(results)
    if best[1] != vb:
        con.ask(f'set {key} {best[1]}')
    text = '\n'.join(f'{fl:6.1f} flips/s  {key} = {v}' for fl, v in results)
    text += f'\nleft at: {key} = {best[1]}'
    print(text)
    save('abset', text)


def measure(con, secs):
    """Average guest flips/s and the CPU thread's load over secs (the monitor's 5 s lines)."""
    flips, tcg = [], []
    end = time.time() + secs
    last = None
    while time.time() < end:
        s = con.ask('stats')
        if s != last:
            flips.append(number(r'guest flips ([\d.]+)/s', s))
            tcg.append(number(r'CPU 0/TCG (\d+)%', s))
            last = s
        time.sleep(5)
    if not flips:
        return 0.0, 0.0
    return sum(flips) / len(flips), sum(tcg) / len(tcg)


def cmd_ab(con, a):
    if len(a.args) < 2:
        sys.exit('ab <a.aot> <b.aot> [seconds]')
    files = a.args[:2]
    secs = float(a.args[2]) if len(a.args) > 2 else 30.0
    title, _, _ = loaded_aot(con)
    if not title:
        sys.exit('no game running from the library')
    results = []
    for path in files:
        print(f'{path}: uploading as /data/xemu/aot/{title}.aot ...')
        con.put(f'/data/xemu/aot/{title}.aot', path)
        print('  ' + con.ask('aot load').splitlines()[0])
        time.sleep(8)       # trampolines come back, caches warm
        fl, tcg = measure(con, secs)
        print(f'  {fl:.1f} guest flips/s, emulated CPU thread {tcg:.0f}% busy')
        results.append((fl, path))
    best = max(results)
    text = '\n'.join(f'{fl:6.1f} flips/s  {p}' for fl, p in results)
    if best[1] != files[-1]:
        con.put(f'/data/xemu/aot/{title}.aot', best[1])
        con.ask('aot load')
    text += f'\nleft loaded: {best[1]}'
    print(text)
    save('ab', text)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default=os.environ.get('PS4_HOST', '192.168.0.90'))
    ap.add_argument('command', choices=['status', 'exits', 'profile', 'code', 'ab', 'abset', 'nv2a'])
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    con = Console(a.host)
    {'status': cmd_status, 'exits': cmd_exits, 'profile': cmd_profile, 'code': cmd_code,
     'ab': cmd_ab, 'abset': cmd_abset, 'nv2a': cmd_nv2a}[a.command](con, a)


if __name__ == '__main__':
    main()
