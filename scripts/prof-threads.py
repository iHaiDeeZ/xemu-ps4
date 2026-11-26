#!/usr/bin/env python3
"""Where a ps4-kit burst profile's threads spend their time: leaf functions and the stacks of
their waits, symbolized from the build's ELF (WSL: llvm-symbolizer-21).

    prof-threads.py profile_N.txt v00.XX.elf aot_start_hex ["thread name" ...] [--depth N]

aot_start_hex: where the translated code is mapped (0 if none); samples there count as
"[translated code]". Without thread names: the emulated CPU and the NV2A's thread.
"""
import collections
import re
import subprocess
import sys

args = [x for x in sys.argv[1:] if not x.startswith('--depth=')]
depth = next((int(x.split('=', 1)[1]) for x in sys.argv[1:] if x.startswith('--depth=')), 10)
prof, elf, aot_start = args[0], args[1], int(args[2], 16)
wanted = args[3:] or ['CPU 0/TCG', 'nv2a.pfifo_thread']

threads = collections.defaultdict(list)     # name -> [(count, [frames])]
busy = {}
current = None
for ln in open(prof, encoding='utf-8', errors='replace'):
    m = re.match(r'thread \d+ "([^"]*)": .*?([\d.]+)% busy', ln)
    if m:
        current = m.group(1) if m.group(1) in wanted else None
        if current:
            busy[current] = float(m.group(2))
        continue
    if ln.startswith('thread ') or ln.startswith('code '):
        current = None
        continue
    if current:
        m = re.match(r'\s+(\d+) (.*)$', ln.rstrip('\n'))
        if m:
            threads[current].append((int(m.group(1)), [f.strip() for f in m.group(2).split(' < ')]))

addrs = set()
for stacks in threads.values():
    for _, fr in stacks:
        for i, f in enumerate(fr):
            if f.startswith('elf '):
                addrs.add(int(f.split()[1], 16) - (1 if i else 0))   # return addresses: the call
addrs = sorted(addrs)
r = subprocess.run(['llvm-symbolizer-21', '--obj=' + elf, '--functions=linkage', '--no-inlines',
                    '--output-style=GNU'], input='\n'.join(hex(a) for a in addrs) + '\n',
                   capture_output=True, text=True)
out = r.stdout.splitlines()
name = {a: out[2 * i] if 2 * i < len(out) else '?' for i, a in enumerate(addrs)}


def fname(f, i):
    if f.startswith('elf '):
        return name[int(f.split()[1], 16) - (1 if i else 0)]
    if f.startswith('abs '):
        a = int(f.split()[1], 16)
        return '[translated code]' if aot_start and aot_start <= a < aot_start + (1 << 30) else '[jit]'
    if f.startswith('mod '):
        return f.split()[1].split('+')[0] + (' wait' if f.endswith('wait') else '')
    return f.split()[0]


for t in wanted:
    stacks = threads.get(t)
    if not stacks:
        continue
    total = sum(n for n, _ in stacks)
    leaf = collections.Counter()
    waits = collections.Counter()
    for n, fr in stacks:
        names = [fname(f, i) for i, f in enumerate(fr)]
        leaf[names[0]] += n
        if names[0].endswith(' wait'):
            # the waiting function: skip the kernel module frames and one runtime lock frame
            waits[' < '.join(names[1:depth])] += n
    print(f'\n== {t}: {busy.get(t, 0):.0f}% busy, {total} samples')
    print('  leaf functions:')
    for k, v in leaf.most_common(14):
        print(f'    {100 * v / total:5.1f}%  {k}')
    if waits:
        print('  waits (who waits):')
        for k, v in waits.most_common(10):
            print(f'    {100 * v / total:5.1f}%  {k[:230]}')
