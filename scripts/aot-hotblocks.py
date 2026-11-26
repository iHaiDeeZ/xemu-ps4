#!/usr/bin/env python3
"""Hot translated blocks of a ps4-kit burst profile, with what kind of guest code they are.

    aot-hotblocks.py profile_N.txt v00.XX.elf aot_start_hex aot-work/<title> [top] [--hot-out F]

aot_start: xemu.log's "aot: N MiB of executable ... memory at 0x..."; aot-work/<title> holds the
build's aot.so and aot_NNNN.c (scripts/aot-console.sh). Each sampled block's C is classified:
x87 (80-bit register loads/stores), SSE helpers, memory accesses, helper calls; the totals say how
much of the guest CPU thread's time each kind of code takes.
"""
import collections
import os
import re
import subprocess
import sys

args = [x for x in sys.argv[1:] if not x.startswith('--hot-out=')]
hot_out = next((x.split('=', 1)[1] for x in sys.argv[1:] if x.startswith('--hot-out=')), None)
prof, elf, aot_start, work = args[0], args[1], int(args[2], 16), args[3]
top = int(args[4]) if len(args) > 4 else 40
so = os.path.join(work, 'aot.so')

# --- samples of the guest CPU thread -------------------------------------------------------------
leaves = collections.Counter()
inside = False
total = 0
for ln in open(prof, encoding='utf-8', errors='replace'):
    m = re.match(r'thread \d+ "([^"]*)"', ln)
    if m:
        inside = m.group(1) == 'CPU 0/TCG'
        continue
    if not inside:
        continue
    m = re.match(r'\s+(\d+) (.*)$', ln.rstrip('\n'))
    if not m:
        if ln.startswith('code ') or ln.startswith('thread'):
            inside = False
        continue
    n = int(m.group(1))
    total += n
    leaves[m.group(2).split(' < ')[0].strip()] += n

aot_addrs = {}
for k, n in leaves.items():
    if k.startswith('abs '):
        a = int(k.split()[1], 16)
        if aot_start <= a < aot_start + (1 << 30):
            aot_addrs[a - aot_start] = aot_addrs.get(a - aot_start, 0) + n
r = subprocess.run(['llvm-symbolizer-21', '--obj=' + so, '--functions=linkage', '--no-inlines',
                    '--output-style=GNU'],
                   input='\n'.join(hex(a) for a in sorted(aot_addrs)) + '\n', capture_output=True,
                   text=True)
out = r.stdout.splitlines()
by_block = collections.Counter()
for i, a in enumerate(sorted(aot_addrs)):
    by_block[out[2 * i] if 2 * i < len(out) else '?'] += aot_addrs[a]

# --- each block's C ------------------------------------------------------------------------------
src_cache = {}
# function -> file (scripts/aot-build.py writes funcs.txt since v00.26; before: 300 blocks a file)
func_file = {}
try:
    for line in open(os.path.join(work, 'funcs.txt')):
        p = line.split()
        if len(p) == 2:
            func_file[p[0]] = p[1]
except OSError:
    pass


def block_c(name):
    m = re.match(r'([FR])(\d+)_([0-9a-f]{8})$', name)
    if not m:
        return None
    if name in func_file:
        path = os.path.join(work, func_file[name])
    elif m.group(1) == 'F':
        path = os.path.join(work, 'aot_%04d.c' % (int(m.group(2)) // 300))
    else:
        return None
    if path not in src_cache:
        try:
            src_cache[path] = open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            src_cache[path] = ''
    s = src_cache[path]
    i = s.find('AOT_CC void %s(AOT_PARAMS)\n{' % name)
    if i < 0:
        return None
    j = s.find('\n}\n', i)
    head = s.rfind('/* pc ', 0, i) if name[0] == 'F' else i
    return s[head if head >= 0 else i:j]


def kinds(c):
    k = []
    if 'AOT_LD80' in c or 'AOT_ST80' in c:
        k.append('x87')
    if re.search(r'AOT_H\((add|sub|mul|div|min|max|sqrt|cvt|comi|ucomi)', c) or 'AOT_I_' in c:
        k.append('sse')
    if 'AOT_SETCSR' in c:
        k.append('setcsr')
    nld = c.count('AOT_LD(') + c.count('AOT_LD128(')
    nst = c.count('AOT_ST(') + c.count('AOT_ST128(')
    calls = len(re.findall(r'AOT_H\(', c))
    return k, nld, nst, calls


kind_t = collections.Counter()
rows = []
for name, n in by_block.most_common():
    c = block_c(name)
    if c is None:
        kind_t['(runtime: ' + name + ')'] += n
        continue
    k, nld, nst, calls = kinds(c)
    sizes = [(int(x), int(y)) for x, y in re.findall(r'size (\d+) insns (\d+)', c)]
    size, insns = (sum(s for s, _ in sizes), sum(i for _, i in sizes)) if sizes else (0, 0)
    for x in k or ['integer']:
        kind_t[x] += n
    rows.append((n, name, insns, size, nld, nst, calls, ','.join(k) or 'integer'))

if hot_out:
    # for scripts/aot-build.py --hot: guest pc and samples, added to what the file already has
    prev = {}
    if os.path.exists(hot_out):
        for line in open(hot_out):
            p = line.split()
            if len(p) >= 2:
                prev[p[0]] = prev.get(p[0], 0) + float(p[1])
    regions = {}
    try:
        for line in open(os.path.join(work, 'regions.txt')):
            p = line.split()
            if p:
                regions[p[0]] = p[1:]
    except OSError:
        pass
    for name, n in by_block.items():
        m = re.match(r'F\d+_([0-9a-f]{8})$', name)
        if m:
            prev[m.group(1)] = prev.get(m.group(1), 0) + n
        elif name in regions:
            # a region's samples, spread over its blocks: they stay together in the layout
            for pc in regions[name]:
                prev[pc] = prev.get(pc, 0) + n / len(regions[name])
    with open(hot_out, 'w') as f:
        for pc, n in sorted(prev.items(), key=lambda kv: -kv[1]):
            f.write('%s %g\n' % (pc, n))

aot_total = sum(aot_addrs.values())
print('guest CPU thread: %d samples, %d in translated code (%.1f%%)' %
      (total, aot_total, 100.0 * aot_total / max(total, 1)))
print('translated code by kind (a block can count in more than one):')
for k, n in kind_t.most_common():
    print('  %6.2f%%  %s' % (100.0 * n / max(total, 1), k))
print('\n  %%thread samples block                    insns bytes loads stores calls kind')
for n, name, insns, size, nld, nst, calls, k in rows[:top]:
    print('  %6.2f%% %6d  %-24s %5d %5d %5d %6d %5d  %s' %
          (100.0 * n / total, n, name, insns, size, nld, nst, calls, k))
