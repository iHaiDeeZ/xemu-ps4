#!/usr/bin/env python3
"""Builds a game's translated code (.aot) from the blocks xemu-ps4 recorded on the console.

    python3 scripts/aot-build.py <recording dir> [more dirs] -o <TITLE>.aot [--title 4d530064]
                                 [--jobs N] [--clang clang-21] [--work dir]

A recording dir is a copy of the console's /data/xemu/aot/<title ID>/: blocks-*.c (written by
tcg/tcg-aot.c.inc as the game ran) and aot_abi.h (the console build's env offsets). Blocks seen
in several sessions are merged; the .aot is an x86-64 position-independent shared object that
accel/tcg/aot.c maps on the console (/data/xemu/aot/<title ID>.aot).

Each block becomes a function (aot/aot_rt.h): the guest registers are parameters kept in host
registers (preserve_none), direct jumps to a block that is also translated become guaranteed
tail calls, other jumps look the target up in the file's own table.

The generated C is the game's code in another form: keep the work dir and the .aot private.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RT_DIR = os.path.normpath(os.path.join(HERE, '..', 'aot'))
LDST = ['ldub_mmu', 'lduw_mmu', 'ldul_mmu', 'ldq_mmu', 'ld16_mmu',
        'stb_mmu', 'stw_mmu', 'stl_mmu', 'stq_mmu', 'st16_mmu']
# helpers aot_rt.h runs as host SSE instructions (AOT_I_<name>; QEMU's helper when the guest's
# MXCSR isn't the default). Not in blocks that also set x87's MXCSR (AOT_SETCSR): both would
# share the host's one register within the block.
INLINE_SSE = ['addss', 'subss', 'mulss', 'divss', 'comiss', 'ucomiss', 'cvtsi2ss', 'cvttss2si']
INLINE_RE = re.compile(r'\(\([\w ]+? \(\*\)\([^()]*\)\)AOT_H\((' + '|'.join(INLINE_SSE) + r')\)\)')
MEM_RE = re.compile(r'AOT_(LD|ST)\(([^;]*)\);')
PER_FILE = 300
HEAD_RE = re.compile(r'//@aot pc=([0-9a-f]+) cs=([0-9a-f]+) fl=([0-9a-f]+) cf=([0-9a-f]+) '
                     r'sz=(\d+) ic=(\d+) h=([0-9a-f]+)')
GOTO_RE = re.compile(r'AOT_GOTO_PC\(0x([0-9a-f]+)u\)')
HELPER_RE = re.compile(r'AOT_H\((\w+)\)')
# a global the block keeps in a C variable but never changes: loaded at its start, stored back at
# every exit (the emitter took a discard for a write before v00.26: cc_src2 in most blocks)
NP_DECL_RE = re.compile(r'^ (?:uint32_t|uint64_t) g_(\w+) = AOT_LD_I(?:32|64)\((\d+)\);$', re.M)
CFLAGS = ['-O2', '-march=btver2', '-fPIC', '-fvisibility=hidden', '-ffreestanding', '-fno-builtin',
          '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-frounding-math',
          '-fno-math-errno', '-mno-red-zone', '-fno-stack-protector',
          '-fno-asynchronous-unwind-tables', '-fno-unwind-tables', '-fno-exceptions', '-w']


class Block:
    __slots__ = ('pc', 'fl', 'cf', 'size', 'icount', 'hash', 'body', 'id', 'name', 'hook')


def read_blocks(dirs):
    blocks, seen, abi = [], set(), None
    for d in dirs:
        abi_path = os.path.join(d, 'aot_abi.h')
        text = open(abi_path).read()
        if abi is None:
            abi = text
        elif text != abi:
            sys.exit(f'{d}: recorded by another xemu build than {dirs[0]}: build them separately')
        for name in sorted(os.listdir(d)):
            if not (name.startswith('blocks-') and name.endswith('.c')):
                continue
            cur, body = None, []
            for line in open(os.path.join(d, name), errors='replace'):
                if line.startswith('//@aot '):
                    m = HEAD_RE.match(line)
                    cur = None
                    if m and int(m.group(2), 16) == 0:
                        b = Block()
                        # cflags as accel/tcg/aot.c compares them: no cluster, no CF_INVALID
                        b.pc, b.fl = int(m.group(1), 16), int(m.group(3), 16)
                        b.cf = int(m.group(4), 16) & 0x00ffffff & ~0x4000
                        b.size, b.icount, b.hash = int(m.group(5)), int(m.group(6)), int(m.group(7), 16)
                        cur, body = b, []
                elif line.startswith('//@end'):
                    if cur is not None:
                        key = (cur.pc, cur.fl, cur.cf, cur.hash, cur.size)
                        if key not in seen:
                            seen.add(key)
                            cur.body = ''.join(body)
                            blocks.append(cur)
                    cur = None
                elif cur is not None:
                    body.append(line)
    return blocks, abi


def fpu_pointer_offsets(abi):
    """env offsets of x87's last instruction/operand pointers (fpop, fpcs, fpds, fpip, fpdp).

    QEMU stores them at every x87 instruction (5 stores and 2 loads); only FNSTENV, FNSAVE and
    FXSAVE read them, and Xbox games and the kernel only save and restore them. The fields follow
    fpregs[8] (16 bytes each) in CPUX86State."""
    m = re.search(r'#define AOT_OFF_FPREGS (\d+)', abi)
    if not m:
        return []
    f = int(m.group(1)) + 8 * 16
    return [f, f + 2, f + 4, f + 8, f + 16]


def simplify_body(body, fpu_ptr_re):
    """C-level clean-ups of a recorded block; returns (body, x87 stores dropped, globals freed)."""
    dropped = 0
    if fpu_ptr_re is not None:
        body, dropped = fpu_ptr_re.subn('', body)
    freed = 0
    for name, off in NP_DECL_RE.findall(body):
        if len(re.findall(r'(?<![\w.])g_%s = ' % name, body)) == 1:     # just its declaration
            body, k = re.subn(r' ?AOT_ST_I(?:32|64)\(%s, g_%s\);' % (off, name), '', body)
            freed += k > 0
    return body, dropped, freed


def read_hot(path):
    """Guest pcs to lay out first, hottest first: lines "<pc hex or F<id>_<pc>> [weight]"."""
    hot = {}
    for line in open(path):
        parts = line.split()
        if not parts or parts[0].startswith('#'):
            continue
        tok = parts[0].split('_')[-1]
        try:
            pc = int(tok, 16)
        except ValueError:
            continue
        w = float(parts[1]) if len(parts) > 1 else 1.0
        hot[pc] = hot.get(pc, 0.0) + w
    return hot


CHAIN_RE = re.compile(r'AOT_CHAIN\((F(\d+)_[0-9a-f]+), 0x([0-9a-f]+)u\)')
LABEL_RE = re.compile(r'(?<![\w])L(\d+): ;')
GOTO_L_RE = re.compile(r'goto L(\d+);')
REGION_DIST = 4096


def make_regions(blocks, max_blocks):
    """Groups of blocks (same flags) that jump directly to each other within REGION_DIST bytes:
    loops and the branches of one function. A group becomes one C function with a label per
    block (emit_region), so a jump between them is a goto: no frame, no register shuffle, values
    stay in registers across the blocks. A block that jumps to itself is a region of its own."""
    by_id = {b.id: b for b in blocks}
    parent = {b.id: b.id for b in blocks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    selfloop = set()
    for b in blocks:
        for m in CHAIN_RE.finditer(b.body):
            t = by_id.get(int(m.group(2)))
            if t is None or t.fl != b.fl or t.cf != b.cf or abs(t.pc - b.pc) > REGION_DIST:
                continue
            if b.hook or t.hook:
                continue        # a hooked block keeps its own function (emit_hooked)
            if t is b:
                selfloop.add(b.id)
                continue
            ra, rb = find(b.id), find(t.id)
            if ra != rb:
                parent[ra] = rb
    groups = collections.defaultdict(list)
    for b in blocks:
        if not b.hook:
            groups[find(b.id)].append(b)
    regions = []
    for g in groups.values():
        g.sort(key=lambda b: (b.pc, b.id))
        for i in range(0, len(g), max_blocks):
            chunk = g[i:i + max_blocks]
            if len(chunk) >= 2 or chunk[0].id in selfloop:
                regions.append(chunk)
    return regions


def emit_region(rname, r):
    """One C function for the blocks of a region: entered through each block's own function (a
    thunk that names the block in aot_rent), jumps between them as gotos (AOT_RCHAIN)."""
    members = {b.id for b in r}
    out = [f'\n/* region {rname}: {len(r)} blocks */\n'
           f'AOT_HIDDEN AOT_CC void {rname}(AOT_PARAMS)\n{{\n'
           '    char *env = aot_env;\n    uint32_t g_eip;\n'
           '    switch (aot_rent) {\n']
    out += [f'    case {i}: goto B{b.id};\n' for i, b in enumerate(r)]
    out.append('    default: __builtin_unreachable();\n    }\n')
    for b in r:
        body = LABEL_RE.sub(lambda m, b=b: f'L{b.id}_{m.group(1)}: ;', b.body)
        body = GOTO_L_RE.sub(lambda m, b=b: f'goto L{b.id}_{m.group(1)};', body)
        body = CHAIN_RE.sub(lambda m: (f'AOT_RCHAIN(B{m.group(2)}, 0x{m.group(3)}u)'
                                       if int(m.group(2)) in members else m.group(0)), body)
        out.append(f'\n/* pc {b.pc:08x} flags {b.fl:08x} size {b.size} insns {b.icount} */\n'
                   f'B{b.id}: ;\n    g_eip = 0x{b.pc:08x}u;\n'
                   f'    if (AOT_UNLIKELY(!aot_valid[{b.id}])) {{\n'
                   f'        AOT_SYNC_P();\n        return;\n    }}\n'
                   f'    {{\n#define AOT_MYFL 0x{b.fl:08x}u\n')
        out.append(body)
        out.append('#undef AOT_MYFL\n    }\n    return;\n')
    out.append('}\n')
    for i, b in enumerate(r):
        out.append(f'AOT_HIDDEN AOT_CC void {b.name}(AOT_PARAMS)\n{{\n    aot_rent = {i};\n'
                   f'    __attribute__((musttail)) return {rname}(AOT_ARGS);\n}}\n')
    return ''.join(out)


HOOK_RE = re.compile(r'^AOT_HOOK\(([0-9a-f]{8})\)', re.M)


def emit_hooked(b):
    """A block whose pc has a hook (aot/hooks/<title>.c): its own translated code as O<id>, and its
    entry (F<id>) that checks it is valid, names the fallback and runs the hook."""
    return (f'\n/* pc {b.pc:08x} flags {b.fl:08x} size {b.size} insns {b.icount}: hooked */\n'
            f'AOT_HIDDEN AOT_CC void O{b.name[1:]}(AOT_PARAMS)\n{{\n'
            f'    AOT_PROLOGUE({b.id}, 0x{b.pc:08x}u)\n#define AOT_MYFL 0x{b.fl:08x}u\n'
            f'{b.body}#undef AOT_MYFL\n}}\n'
            f'AOT_HIDDEN AOT_CC void {b.name}(AOT_PARAMS)\n{{\n'
            f'    if (AOT_UNLIKELY(!aot_valid[{b.id}])) {{\n'
            f'        char *env = aot_env;\n        uint32_t g_eip = 0x{b.pc:08x}u;\n'
            f'        AOT_SYNC_P();\n        return;\n    }}\n'
            f'    aot_hook_orig = O{b.name[1:]};\n    aot_hook_fl = 0x{b.fl:08x}u;\n'
            f'    __attribute__((musttail)) return H_{b.pc:08x}(AOT_ARGS);\n}}\n')


def ix_hash(pc, fl, mask):
    return ((((pc * 0x9E3779B1) & 0xffffffff) ^ ((fl * 0x85EBCA77) & 0xffffffff)) >> 7) & mask


def write_if_changed(path, text):
    if os.path.exists(path) and open(path).read() == text:
        return False
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--title', default='0')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--clang', default=os.environ.get('AOT_CLANG', 'clang-21'))
    ap.add_argument('--work', default=None)
    ap.add_argument('--hot', default=None,
                    help='guest pcs to place first (scripts/aot-hotblocks.py --hot-out)')
    ap.add_argument('--keep-fpu-pointers', action='store_true',
                    help="keep x87's last instruction/operand pointer stores")
    ap.add_argument('--regions', action='store_true',
                    help='compile blocks that jump to each other nearby as one function')
    ap.add_argument('--hooks', default='auto',
                    help="native versions of game functions: a C file, 'auto' (aot/hooks/<title>.c "
                         "when there is one) or 'none'")
    ap.add_argument('--region-blocks', type=int, default=48,
                    help='most blocks in one region function')
    a = ap.parse_args()

    t0 = time.time()
    blocks, abi = read_blocks(a.dirs)
    if not blocks:
        sys.exit('no blocks recorded')
    blocks.sort(key=lambda b: (b.pc, b.fl, b.cf, b.hash))
    by_target = {}
    for i, b in enumerate(blocks, 1):
        b.id = i
        b.name = f'F{i}_{b.pc:08x}'
        by_target.setdefault((b.pc, b.fl), []).append(b)
    n = len(blocks)
    print(f'{n} blocks from {len(a.dirs)} recording(s)')

    work = a.work or os.path.splitext(a.out)[0] + '.work'
    os.makedirs(work, exist_ok=True)
    write_if_changed(os.path.join(work, 'aot_abi.h'), abi)

    # the MMU index of most guest memory accesses: aot_rt.h's flat page tables are for that one
    mmus = collections.Counter()
    for b in blocks:
        for m in MEM_RE.finditer(b.body):
            args = m.group(2).split(',')
            try:
                mmus[int(args[-3]) & 15] += 1
            except (ValueError, IndexError):
                pass
    fast_mmu = mmus.most_common(1)[0][0] if mmus else 5
    print(f'guest memory accesses by MMU index: {dict(mmus)}; flat page tables for {fast_mmu}')

    # direct jumps: a tail call where exactly one block is there for those flags
    imports = list(LDST) + list(INLINE_SSE) + ['aot_slow_ld', 'aot_slow_st',
                                              f'aot_fast_rd_{fast_mmu}', f'aot_fast_wr_{fast_mmu}']
    imp_set = set(imports)
    chained = unresolved = inlined = 0
    offs = [] if a.keep_fpu_pointers else fpu_pointer_offsets(abi)
    fpu_ptr_re = re.compile(r' ?AOT_STM\(uint(?:16|32|64)_t, \(\(char \*\)env\), (?:%s), [^;]*\);'
                            % '|'.join(str(o) for o in offs)) if offs else None
    x87_dropped = freed = 0
    for b in blocks:
        b.body, k1, k2 = simplify_body(b.body, fpu_ptr_re)
        x87_dropped += k1
        freed += k2
        def goto(m, b=b):
            nonlocal chained, unresolved
            t = int(m.group(1), 16)
            cands = by_target.get((t, b.fl), [])
            if len(cands) == 1:
                chained += 1
                return f'AOT_CHAIN({cands[0].name}, 0x{t:08x}u)'
            unresolved += 1
            return 'AOT_IND()'
        b.body = GOTO_RE.sub(goto, b.body)
        for h in HELPER_RE.findall(b.body):
            if h not in imp_set:
                imp_set.add(h)
                imports.append(h)
        if 'AOT_SETCSR(' not in b.body:
            b.body, k = INLINE_RE.subn(r'AOT_I_\1', b.body)
            inlined += k
    print(f'{chained} direct jumps chained, {unresolved} looked up at run time, {len(imports)} helpers, '
          f'{inlined} SSE helper calls as host instructions, {x87_dropped} x87 pointer stores dropped, '
          f'{freed} unchanged globals no longer stored back')

    # regions: blocks that jump to each other nearby become one function (aot_rt.h AOT_RCHAIN)
    # hooks: the game's functions in native C (aot/hooks/<title>.c)
    hooks_path = None
    if a.hooks == 'auto':
        p = os.path.join(RT_DIR, 'hooks', f'{int(a.title, 16):08x}.c')
        hooks_path = p if os.path.exists(p) else None
    elif a.hooks != 'none':
        hooks_path = a.hooks
    hooks_text = open(hooks_path).read() if hooks_path else ''
    hooked = {int(x, 16) for x in HOOK_RE.findall(hooks_text)}
    for b in blocks:
        b.hook = b.pc in hooked
    if hooks_path:
        print(f'hooks: {len(hooked)} functions in {hooks_path}, '
              f'{sum(1 for b in blocks if b.hook)} blocks run them')
    regions = make_regions(blocks, a.region_blocks) if a.regions else []
    in_region = {b.id for r in regions for b in r}
    units = [r for r in regions] + [[b] for b in blocks if b.id not in in_region]
    if regions:
        print(f'regions: {len(regions)} functions of {len(in_region)} blocks '
              f'({len(in_region) / max(len(regions), 1):.1f} each), {n - len(in_region)} blocks alone')

    # layout: the hottest code first and together (fewer pages and cache lines for the code that
    # runs most), then the rest in pc order
    hot = read_hot(a.hot) if a.hot else {}
    units.sort(key=lambda u: (-max(hot.get(b.pc, 0.0) for b in u), u[0].pc))
    if hot:
        print(f'layout: {sum(1 for u in units if any(b.pc in hot for b in u))} hot units first '
              f'({len(hot)} hot pcs listed)')

    mask = 1
    while mask + 1 < 2 * n:
        mask = mask * 2 + 1
    gen = [f'/* scripts/aot-build.py: {n} blocks */',
           f'#define AOT_NB_BLOCKS {n}', f'#define AOT_IX_MASK 0x{mask:x}u',
           f'#define AOT_FAST_MMU {fast_mmu}',
           f'#define AOT_NB_IMPORTS {len(imports)}', 'enum {']
    gen += [f'    AOT_HID_{h} = {i},' for i, h in enumerate(imports)]
    gen += ['};', '#define AOT_H(n) (aot_imp[AOT_HID_##n])', '']
    write_if_changed(os.path.join(work, 'aot_gen.h'), '\n'.join(gen))

    head = '#include "aot_abi.h"\n#include "aot_gen.h"\n#include "aot_rt.h"\n\n'
    sources = []
    files, cur, cur_n = [], [], 0
    for u in units:
        if cur and cur_n + len(u) > PER_FILE:
            files.append(cur)
            cur, cur_n = [], 0
        cur.append(u)
        cur_n += len(u)
    if cur:
        files.append(cur)
    region_names = []
    funcs = []          # (function, file) for scripts/aot-hotblocks.py
    for fi, fu in enumerate(files):
        names, protos = set(), set()
        for u in fu:
            for b in u:
                names.add(b.name)
                for m in CHAIN_RE.finditer(b.body):
                    protos.add(m.group(1))
        for u in fu:
            for b in u:
                if b.hook:
                    names.add(f'H_{b.pc:08x}')
                    names.add(f'O{b.name[1:]}')
        out = [head]
        out += [f'AOT_HIDDEN AOT_CC void {p}(AOT_PARAMS);\n' for p in sorted(protos | names)]
        for u in fu:
            funcs += [(b.name, fi) for b in u]
            if len(u) == 1 and u[0].hook:
                funcs.append((f'O{u[0].name[1:]}', fi))
                out.append(emit_hooked(u[0]))
            elif len(u) == 1 and u[0].id not in in_region:
                b = u[0]
                out.append(f'\n/* pc {b.pc:08x} flags {b.fl:08x} size {b.size} insns {b.icount} */\n'
                           f'AOT_HIDDEN AOT_CC void {b.name}(AOT_PARAMS)\n{{\n'
                           f'    AOT_PROLOGUE({b.id}, 0x{b.pc:08x}u)\n#define AOT_MYFL 0x{b.fl:08x}u\n')
                out.append(b.body)
                out.append('#undef AOT_MYFL\n}\n')
            else:
                rname = f'R{len(region_names)}_{u[0].pc:08x}'
                region_names.append((rname, u))
                funcs.append((rname, fi))
                out.append(emit_region(rname, u))
        src = os.path.join(work, f'aot_{fi:04d}.c')
        write_if_changed(src, ''.join(out))
        sources.append(src)
    # stale files from a build with more of them
    for name in os.listdir(work):
        m = re.match(r'aot_(\d{4})\.[co]$', name)
        if m and int(m.group(1)) >= len(files):
            os.remove(os.path.join(work, name))
    with open(os.path.join(work, 'regions.txt'), 'w') as f:
        for rname, u in region_names:
            f.write(rname + ' ' + ' '.join(f'{b.pc:08x}' for b in u) + '\n')
    if hooks_path:
        src = os.path.join(work, 'aot_hooks.c')
        write_if_changed(src, head + f'/* {hooks_path} */\n' + hooks_text)
        sources.append(src)
        funcs += [(f'H_{pc:08x}', 'aot_hooks.c') for pc in sorted(hooked)]
    else:
        for name in ('aot_hooks.c', 'aot_hooks.o'):
            if os.path.exists(os.path.join(work, name)):
                os.remove(os.path.join(work, name))
    with open(os.path.join(work, 'funcs.txt'), 'w') as f:
        for name, fi in funcs:
            f.write(f'{name} {fi if isinstance(fi, str) else f"aot_{fi:04d}.c"}\n')

    # the tables, the entry, the header
    ix = [None] * (mask + 1)
    for b in blocks:
        h = ix_hash(b.pc, b.fl, mask)
        while ix[h] is not None:
            h = (h + 1) & mask
        ix[h] = b
    m = ['#define AOT_MAIN\n' + head]
    m += [f'AOT_HIDDEN AOT_CC void {b.name}(AOT_PARAMS);\n' for b in blocks]
    m.append('''
typedef struct {
    uint32_t pc, cs_base, flags, cflags;
    uint16_t size, icount;
    uint32_t pad;
    uint64_t hash;
} aot_entry_t;

typedef struct {
    uint64_t magic;
    uint32_t version, nb_entries;
    uint64_t abi_key;
    uint32_t title_id, nb_imports;
    const aot_entry_t *entries;
    uint32_t *valid;
    uint32_t *gen;
    void **imports;
    const char *const *import_names;
    void (*enter)(void *env, uint32_t id);
    uint32_t *cur;
    const char *built;
} aot_header_t;

char *aot_env AOT_HIDDEN;
const uintptr_t *aot_frd AOT_HIDDEN;
const uintptr_t *aot_fwr AOT_HIDDEN;
uint32_t aot_csr_cur AOT_HIDDEN;
uint32_t aot_rent AOT_HIDDEN;
aot_fn_t aot_hook_orig AOT_HIDDEN;
uint32_t aot_hook_fl AOT_HIDDEN;
uint32_t aot_valid[AOT_NB_BLOCKS + 1] AOT_HIDDEN;
uint32_t aot_gen AOT_HIDDEN = 1;
uint32_t aot_cur[2] AOT_HIDDEN;
void *aot_imp[AOT_NB_IMPORTS] AOT_HIDDEN;
''')
    m.append('static const char *const aot_imp_names[AOT_NB_IMPORTS] = {\n')
    m += [f'    "{h}",\n' for h in imports]
    m.append('};\n\nconst aot_fn_t aot_fns[AOT_NB_BLOCKS + 1] AOT_HIDDEN = {\n    0,\n')
    m += [f'    {b.name},\n' for b in blocks]
    m.append('};\n\nconst aot_ix_t aot_ix[AOT_IX_MASK + 1] AOT_HIDDEN = {\n')
    m += [f'    [{h}] = {{ 0x{b.pc:08x}u, 0x{b.fl:08x}u, {b.id}, 0 }},\n'
          for h, b in enumerate(ix) if b is not None]
    m.append('};\n\nstatic const aot_entry_t aot_entries[AOT_NB_BLOCKS + 1] = {\n    { 0 },\n')
    m += [f'    {{ 0x{b.pc:08x}u, 0, 0x{b.fl:08x}u, 0x{b.cf:08x}u, {b.size}, {b.icount}, 0, '
          f'0x{b.hash:016x}ull }},\n' for b in blocks]
    built = time.strftime('%Y-%m-%d %H:%M')
    m.append(f'''}};

/* xemu's helper_aot_run: the parameter registers from env, then the block */
AOT_HIDDEN void aot_enter(char *env, uint32_t id)
{{
    aot_env = env;
    aot_frd = (const uintptr_t *)AOT_H(aot_fast_rd_{fast_mmu});
    aot_fwr = (const uintptr_t *)AOT_H(aot_fast_wr_{fast_mmu});
    aot_csr_cur = 0;    /* not known: the JIT's code may have set MXCSR (x87's rounding) */
    aot_fns[id](AOT_LD_I32(AOT_OFF_EAX), AOT_LD_I32(AOT_OFF_ECX), AOT_LD_I32(AOT_OFF_EDX),
                AOT_LD_I32(AOT_OFF_EBX), AOT_LD_I32(AOT_OFF_ESP), AOT_LD_I32(AOT_OFF_EBP),
                AOT_LD_I32(AOT_OFF_ESI), AOT_LD_I32(AOT_OFF_EDI), AOT_LD_I32(AOT_OFF_CC_DST),
                AOT_LD_I32(AOT_OFF_CC_SRC), AOT_LD_I32(AOT_OFF_CC_OP));
}}

__attribute__((visibility("default"))) const aot_header_t aot_header = {{
    0x31544f41554d4558ull, 1, AOT_NB_BLOCKS, AOT_ABI_KEY, 0x{int(a.title, 16):08x}u, AOT_NB_IMPORTS,
    aot_entries, aot_valid, &aot_gen, aot_imp, aot_imp_names,
    (void (*)(void *, uint32_t))aot_enter, aot_cur, "{built}, {n} blocks",
}};

/* what the compiler may call for copies (the file imports nothing) */
AOT_HIDDEN void *memcpy(void *d, const void *s, size_t k)
{{
    char *o = d;
    const char *i = s;
    while (k--) {{
        *o++ = *i++;
    }}
    return d;
}}

AOT_HIDDEN void *memmove(void *d, const void *s, size_t k)
{{
    char *o = d;
    const char *i = s;
    if (o < i) {{
        while (k--) {{
            *o++ = *i++;
        }}
    }} else {{
        while (k--) {{
            o[k] = i[k];
        }}
    }}
    return d;
}}

AOT_HIDDEN void *memset(void *d, int c, size_t k)
{{
    char *o = d;
    while (k--) {{
        *o++ = (char)c;
    }}
    return d;
}}
''')
    main_src = os.path.join(work, 'aot_main.c')
    write_if_changed(main_src, ''.join(m))
    sources.append(main_src)

    # compile (only what changed) and link
    inc = ['-I', work, '-I', RT_DIR]

    def compile_one(src):
        obj = src[:-2] + '.o'
        if os.path.exists(obj) and os.path.getmtime(obj) >= os.path.getmtime(src) and \
           os.path.getmtime(obj) >= os.path.getmtime(os.path.join(RT_DIR, 'aot_rt.h')):
            return obj, None
        r = subprocess.run([a.clang] + CFLAGS + inc + ['-c', src, '-o', obj],
                           capture_output=True, text=True)
        return obj, (r.stderr if r.returncode else None)

    t1 = time.time()
    objs, failed = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for obj, err in ex.map(compile_one, sources):
            objs.append(obj)
            if err:
                failed += 1
                print(err[:4000], file=sys.stderr)
    if failed:
        sys.exit(f'{failed} file(s) failed to compile')
    print(f'compiled {len(sources)} files in {time.time() - t1:.0f} s')
    so = os.path.join(work, 'aot.so')
    r = subprocess.run([a.clang, '-shared', '-nostdlib', '-fPIC', '-Wl,-Bsymbolic', '-Wl,--no-undefined',
                        '-Wl,-z,max-page-size=0x1000', '-Wl,--hash-style=sysv', '-o', so] + objs,
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[:4000])
    readelf = a.clang.replace('clang', 'llvm-readelf')
    rel = subprocess.run([readelf, '-r', so], capture_output=True, text=True).stdout
    bad = [l for l in rel.splitlines() if 'R_X86_64_' in l and 'R_X86_64_RELATIVE' not in l]
    if bad:
        sys.exit('relocations other than relative ones:\n' + '\n'.join(bad[:20]))
    data = open(so, 'rb').read()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'wb') as f:
        f.write(data)
    print(f'{a.out}: {len(data) / 1048576:.1f} MiB, {n} blocks, sha1 {hashlib.sha1(data).hexdigest()[:12]}'
          f' ({time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
