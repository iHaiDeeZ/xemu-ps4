#!/usr/bin/env python3
"""Checks a hook (aot/hooks/<title>.c) against the game's translated code, bit for bit, on the PC.

    python3 scripts/aot-hooktest.py <work dir> <pc hex> [--trials 3000] [--seed 1] [--nan]

Run in WSL after scripts/aot-build.py made <work dir> with the hooks. The hooked block's own
translated code (O<id>) and the blocks after it (from the same build) are linked into a Linux
program with the hook, a fake guest memory (8 MiB of RAM, every page in the flat page tables)
and a fake CPU state. Each trial fills memory and registers from a seed, runs the original from
the hooked pc until it leaves for the return address, snapshots memory and CPU state, does the
same with the hook, and compares: all of guest RAM, the integer registers, eip, eflags, the lazy
flags (cc_*), df, x87's top/status/control/tags and MXCSR. Not compared: x87 register contents
below the stack top and QEMU's ft0 (stale values nothing reads).

The test calls the hooked function the way the game does (cdecl: return address, then the
arguments on the stack); arguments are float matrices/vectors (--args), with values from tame to
denormal, huge and signed zeros; --nan adds NaNs (payloads may differ: reported, not failed).
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RT_DIR = os.path.normpath(os.path.join(HERE, '..', 'aot'))
CFLAGS = ['-O2', '-march=btver2', '-fPIC', '-fvisibility=hidden', '-ffreestanding', '-fno-builtin',
          '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-frounding-math',
          '-fno-math-errno', '-mno-red-zone', '-fno-stack-protector', '-w']

HARNESS = r'''
#define AOT_MAIN
#include "aot_abi.h"
#include "aot_gen.h"
#include "aot_rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

char *aot_env AOT_HIDDEN;
const uintptr_t *aot_frd AOT_HIDDEN;
const uintptr_t *aot_fwr AOT_HIDDEN;
uint32_t aot_csr_cur AOT_HIDDEN, aot_rent AOT_HIDDEN, aot_gen AOT_HIDDEN = 1, aot_cur[2] AOT_HIDDEN;
uint32_t aot_valid[AOT_NB_BLOCKS + 1] AOT_HIDDEN;
void *aot_imp[AOT_NB_IMPORTS] AOT_HIDDEN;
const aot_fn_t aot_fns[AOT_NB_BLOCKS + 1] AOT_HIDDEN;
const aot_ix_t aot_ix[AOT_IX_MASK + 1] AOT_HIDDEN;
aot_fn_t aot_hook_orig AOT_HIDDEN;
uint32_t aot_hook_fl AOT_HIDDEN;
int aot_hooktest_fallbacks, hk_stub_hits, hk_helper_hits;
void aot_enter(char *env, uint32_t id) { (void)env; (void)id; }

AOT_HIDDEN AOT_CC void @ORIG@(AOT_PARAMS);
AOT_HIDDEN AOT_CC void @HOOKED@(AOT_PARAMS);

#define RAM_SIZE (8u << 20)
static uint8_t *ram;
static uintptr_t *frd, *fwr;
static char envblob[1 << 17];
#define ENV (envblob + (1 << 16))

static uint64_t hk_ld(char *env, uint64_t a, uint32_t oi, uintptr_t ra)
{
    (void)env; (void)ra;
    uint64_t v = 0;
    unsigned sz = 1u << ((oi >> 4) & 3);
    if (a + sz > RAM_SIZE) { hk_helper_hits++; return 0; }
    memcpy(&v, ram + a, sz);
    return v;
}
static void hk_st(char *env, uint64_t a, uint64_t v, uint32_t oi, uintptr_t ra)
{
    (void)env; (void)ra;
    unsigned sz = 1u << ((oi >> 4) & 3);
    if (a + sz > RAM_SIZE) { hk_helper_hits++; return; }
    memcpy(ram + a, &v, sz);
}
static uint64_t hk_helper(void) { hk_helper_hits++; return 0; }

static uint64_t rng;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return (uint32_t)rng; }

static int with_nan;
static float pick_float(void)
{
    uint32_t k = rnd() % 32, u;
    float f;
    switch (k) {
    case 0: return 0.0f;
    case 1: return -0.0f;
    case 2: u = rnd() & 0x807fffffu; memcpy(&f, &u, 4); return f;            /* denormal */
    case 3: return (rnd() & 1 ? 1 : -1) * 1e30f * (1 + rnd() % 100);         /* huge */
    case 4: return (rnd() & 1 ? 1 : -1) * 1e-30f * (1 + rnd() % 100);        /* tiny */
    case 5: return (float)(int)(rnd() % 200) - 100.0f;                       /* integers */
    case 6: return 1.0f;
    case 7: if (with_nan) { u = 0x7fc00000u | (rnd() & 0x3fffff); memcpy(&f, &u, 4); return f; }
            /* fall through */
    default:
        u = (rnd() & 0x80000000u) | ((100 + rnd() % 56) << 23) | (rnd() & 0x7fffffu);
        memcpy(&f, &u, 4);
        return f;
    }
}

typedef struct { uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi, ccd, ccs, cco; } regs_t;

static regs_t setup(uint64_t seed)
{
    /* the inputs are made with float math: in the same rounding mode for both runs (the last
     * run left the guest's in MXCSR) */
    _mm_setcsr(0x1f80u);
    rng = seed * 0x9E3779B97F4A7C15ull + 1;
    for (uint32_t i = 0; i < RAM_SIZE; i += 4) {
        uint32_t v = rnd();
        memcpy(ram + i, &v, 4);
    }
    memset(envblob, 0, sizeof(envblob));
    regs_t r;
    r.eax = rnd(); r.ecx = rnd(); r.edx = rnd(); r.ebx = rnd(); r.ebp = rnd();
    r.esi = rnd(); r.edi = rnd(); r.ccd = rnd(); r.ccs = rnd(); r.cco = 1 + rnd() % 40;
    r.esp = 0x500000u + (rnd() % 0x10000u) * 4;
    /* the arguments: @NARGS@ float arrays of @ARGLEN@ bytes, each in its own spot (or the first
     * one where another is: f(x, x, y) uses) */
    uint32_t args[8];
    for (int i = 0; i < @NARGS@; i++) {
        args[i] = 0x200000u + (rnd() % 0x3000u) * 64 + (rnd() % 4) * 4;
        for (uint32_t k = 0; k < @ARGLEN@; k += 4) {
            float f = pick_float();
            memcpy(ram + args[i] + k, &f, 4);
        }
    }
    if (@NARGS@ > 1 && rnd() % 4 == 0) {
        args[0] = args[1 + rnd() % (@NARGS@ - 1)];
    }
    uint32_t ret = 0xdead0000u;
    memcpy(ram + r.esp, &ret, 4);
    for (int i = 0; i < @NARGS@; i++) {
        memcpy(ram + r.esp + 4 + 4 * i, &args[i], 4);
    }
    AOT_STM(uint32_t, ENV, 36, 0x202u);                                   /* eflags */
    AOT_STM(int32_t, ENV, AOT_OFF_DF, 1);
    AOT_STM(uint32_t, ENV, AOT_OFF_FPSTT, rnd() & 7);
    AOT_STM(uint16_t, ENV, AOT_OFF_FPUC, (uint16_t)(0x023fu | ((rnd() & 3) << 10)));
    memset(ENV + AOT_OFF_FPTAGS, 1, 8);
    AOT_STM(uint32_t, ENV, AOT_OFF_MXCSR, 0x1f80u);
    return r;
}

static uint8_t *snap_ram;
static char snap_env[2][1 << 12];

static void run(aot_fn_t f, regs_t r)
{
    aot_env = ENV;
    aot_frd = frd;
    aot_fwr = fwr;
    aot_csr_cur = 0;
    f(r.eax, r.ecx, r.edx, r.ebx, r.esp, r.ebp, r.esi, r.edi, r.ccd, r.ccs, r.cco);
}

static const struct { int off, len; const char *name; } fields[] = {
    { 0, 32, "registers" }, { AOT_OFF_EIP, 4, "eip" }, { 36, 4, "eflags" },
    { AOT_OFF_CC_DST, 4, "cc_dst" }, { AOT_OFF_CC_SRC, 4, "cc_src" }, { 48, 4, "cc_src2" },
    { AOT_OFF_CC_OP, 4, "cc_op" }, { AOT_OFF_DF, 4, "df" }, { AOT_OFF_FPSTT, 4, "fpstt" },
    { AOT_OFF_FPUS, 2, "fpus" }, { AOT_OFF_FPUC, 2, "fpuc" }, { AOT_OFF_FPTAGS, 8, "fptags" },
    { AOT_OFF_MXCSR, 4, "mxcsr" },
};

static int is_nan_word(const uint8_t *p)
{
    uint32_t u;
    memcpy(&u, p, 4);
    return (u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu);
}

int main(int argc, char **argv)
{
    int trials = argc > 1 ? atoi(argv[1]) : 3000;
    uint64_t seed0 = argc > 2 ? strtoull(argv[2], 0, 0) : 1;
    with_nan = argc > 3 && atoi(argv[3]);
    ram = aligned_alloc(4096, RAM_SIZE);
    snap_ram = malloc(RAM_SIZE);
    frd = calloc(1u << 20, sizeof(uintptr_t));
    fwr = calloc(1u << 20, sizeof(uintptr_t));
    for (uint32_t p = 0; p < RAM_SIZE >> 12; p++) {
        frd[p] = fwr[p] = (uintptr_t)ram;
    }
    for (int i = 0; i < AOT_NB_IMPORTS; i++) {
        aot_imp[i] = (void *)hk_helper;
    }
    aot_imp[AOT_HID_aot_slow_ld] = (void *)hk_ld;
    aot_imp[AOT_HID_aot_slow_st] = (void *)hk_st;
    aot_imp[AOT_HID_ldub_mmu] = aot_imp[AOT_HID_lduw_mmu] = aot_imp[AOT_HID_ldul_mmu] =
        aot_imp[AOT_HID_ldq_mmu] = (void *)hk_ld;
    aot_imp[AOT_HID_stb_mmu] = aot_imp[AOT_HID_stw_mmu] = aot_imp[AOT_HID_stl_mmu] =
        aot_imp[AOT_HID_stq_mmu] = (void *)hk_st;
    for (int i = 0; i <= AOT_NB_BLOCKS; i++) {
        aot_valid[i] = 1;
    }
    int failed = 0, nan_diffs = 0;
    for (int t = 0; t < trials; t++) {
        regs_t r = setup(seed0 + t);
        run(@ORIG@, r);
        memcpy(snap_ram, ram, RAM_SIZE);
        memcpy(snap_env[0], ENV, sizeof(snap_env[0]));
        int stubs0 = hk_stub_hits, helpers0 = hk_helper_hits;
        r = setup(seed0 + t);
        run(@HOOKED@, r);
        memcpy(snap_env[1], ENV, sizeof(snap_env[1]));
        if (hk_stub_hits || hk_helper_hits) {
            printf("trial %d: left the tested code (stubs %d/%d, helpers %d/%d)\n", t, stubs0,
                   hk_stub_hits, helpers0, hk_helper_hits);
            return 2;
        }
        int bad = 0;
        for (uint32_t i = 0; i < RAM_SIZE; i += 4) {
            if (memcmp(ram + i, snap_ram + i, 4)) {
                if (with_nan && is_nan_word(ram + i) && is_nan_word(snap_ram + i)) {
                    nan_diffs++;
                    continue;
                }
                if (bad++ < 4) {
                    uint32_t x, y;
                    memcpy(&x, snap_ram + i, 4);
                    memcpy(&y, ram + i, 4);
                    printf("trial %d: guest %06x: original %08x, hook %08x\n", t, i, x, y);
                }
            }
        }
        for (size_t k = 0; k < sizeof(fields) / sizeof(fields[0]); k++) {
            if (memcmp(snap_env[0] + fields[k].off, snap_env[1] + fields[k].off, fields[k].len)) {
                bad++;
                printf("trial %d: %s differs:", t, fields[k].name);
                for (int j = 0; j < fields[k].len; j++) {
                    printf(" %02x/%02x", (uint8_t)snap_env[0][fields[k].off + j],
                           (uint8_t)snap_env[1][fields[k].off + j]);
                }
                printf("\n");
            }
        }
        failed += bad != 0;
        if (failed >= 5) {
            break;
        }
    }
    printf("%d trials: %d failed, hook fell back %d times, %d NaN payload differences\n", trials,
           failed, aot_hooktest_fallbacks, nan_diffs);
    return failed ? 1 : 0;
}
'''


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(' '.join(cmd[:3]) + ' ...:\n' + (r.stderr or r.stdout)[:4000])
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work')
    ap.add_argument('pc')
    ap.add_argument('--trials', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--nan', action='store_true')
    ap.add_argument('--args', default='3x64', help='number x bytes of float arguments (cdecl)')
    ap.add_argument('--clang', default='clang-21')
    a = ap.parse_args()
    pc = int(a.pc, 16)
    work = os.path.abspath(os.path.expanduser(a.work))
    funcs = {}
    for line in open(os.path.join(work, 'funcs.txt')):
        p = line.split()
        if len(p) == 2:
            funcs[p[0]] = p[1]
    orig = sorted(n for n in funcs if re.match(r'O\d+_%08x$' % pc, n))
    if not orig:
        sys.exit(f'no hooked block at {pc:08x} in {work} (build with the hook first)')
    orig = orig[0]
    hooked = 'F' + orig[1:]
    # the files with the hooked block and the blocks of the same function (the next 4 KiB)
    files = {funcs[orig], 'aot_hooks.c'}
    for n, f in funcs.items():
        m = re.match(r'[FR]\d+_([0-9a-f]{8})$', n)
        if m and pc <= int(m.group(1), 16) < pc + 0x1000:
            files.add(f)
    tdir = os.path.join(work, 'hooktest')
    os.makedirs(tdir, exist_ok=True)
    inc = ['-I', work, '-I', RT_DIR]
    objs = []
    for f in sorted(files):
        src = os.path.join(work, f)
        obj = os.path.join(tdir, f[:-2] + '.o')
        flags = CFLAGS + (['-DAOT_HOOKTEST'] if f == 'aot_hooks.c' else [])
        run([a.clang] + flags + inc + ['-c', src, '-o', obj])
        objs.append(obj)
    # every block function these call that isn't linked: a stub that says so
    undef = set(run(['llvm-nm-21', '-u'] + objs).split())
    defined = set()
    for line in run(['llvm-nm-21', '--defined-only'] + objs).splitlines():
        p = line.split()
        if len(p) == 3:
            defined.add(p[2])
    stubs = sorted(s for s in undef - defined if re.match(r'([FORH]\d*_[0-9a-f]{8})$', s))
    stub_c = os.path.join(tdir, 'stubs.c')
    with open(stub_c, 'w') as f:
        f.write('#include "aot_abi.h"\n#include "aot_gen.h"\n#include "aot_rt.h"\nextern int hk_stub_hits;\n')
        for s in stubs:
            f.write(f'AOT_HIDDEN AOT_CC void {s}(AOT_PARAMS) {{ hk_stub_hits++; }}\n')
    nargs, arglen = (int(x) for x in a.args.split('x'))
    harness = (HARNESS.replace('@ORIG@', orig).replace('@HOOKED@', hooked)
               .replace('@NARGS@', str(nargs)).replace('@ARGLEN@', str(arglen)))
    h_c = os.path.join(tdir, 'harness.c')
    with open(h_c, 'w') as f:
        f.write(harness)
    exe = os.path.join(tdir, 'hooktest')
    run([a.clang, '-O1', '-march=btver2', '-w'] + inc + ['-c', stub_c, '-o', stub_c[:-2] + '.o'])
    run([a.clang, '-O1', '-march=btver2', '-w', '-frounding-math'] + inc + ['-c', h_c, '-o', h_c[:-2] + '.o'])
    run([a.clang, '-o', exe, h_c[:-2] + '.o', stub_c[:-2] + '.o'] + objs + ['-lm'])
    print(f'{orig} (translated) vs {hooked} (hook): {len(objs)} objects, {len(stubs)} stubs')
    r = subprocess.run([exe, str(a.trials), str(a.seed), '1' if a.nan else '0'], text=True,
                       capture_output=True)
    print(r.stdout, end='')
    if r.returncode:
        print(r.stderr, end='')
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
