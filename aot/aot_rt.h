/*
 * xemu-ps4 translated code: what the C that xemu records (tcg/tcg-aot.c.inc) needs to
 * compile. scripts/aot-build.py includes this in every file, after the recording's
 * aot_abi.h (this build's env offsets) and its own aot_gen.h (imports, table sizes).
 *
 * The blocks are functions with the guest's registers as parameters, in a calling
 * convention that keeps them all in host registers (preserve_none) and jumps from
 * block to block with guaranteed tail calls (musttail): a chain of translated blocks
 * runs without returning to xemu. Guest memory is reached through QEMU's TLB the way
 * the JIT's code does (same table, same compare); a miss calls QEMU's slow path with
 * env brought up to date first.
 *
 * This program is free software; you can redistribute it and/or modify it under the
 * terms of the GNU General Public License as published by the Free Software
 * Foundation; either version 2 of the License, or (at your option) any later version.
 */

#ifndef AOT_RT_H
#define AOT_RT_H

#include <stdint.h>
#include <stddef.h>
#include <immintrin.h>

#define AOT_HIDDEN __attribute__((visibility("hidden")))
#define AOT_CC __attribute__((preserve_none))
#define AOT_LIKELY(x) __builtin_expect(!!(x), 1)
#define AOT_UNLIKELY(x) __builtin_expect(!!(x), 0)

/* --- vectors: storage types by size, lane types for the ops ------------------------------- */

typedef uint64_t aotv64 __attribute__((vector_size(8)));
typedef uint64_t aotv128 __attribute__((vector_size(16)));
typedef uint64_t aotv256 __attribute__((vector_size(32)));
#define AOT_LANES(b, n)                                                          \
    typedef uint##b##_t u##b##x##n __attribute__((vector_size(b / 8 * n)));    \
    typedef int##b##_t s##b##x##n __attribute__((vector_size(b / 8 * n)));
AOT_LANES(8, 8) AOT_LANES(16, 4) AOT_LANES(32, 2) AOT_LANES(64, 1)
AOT_LANES(8, 16) AOT_LANES(16, 8) AOT_LANES(32, 4) AOT_LANES(64, 2)
AOT_LANES(8, 32) AOT_LANES(16, 16) AOT_LANES(32, 8) AOT_LANES(64, 4)
#define AOT_VC128(x) ((aotv128){ (x), (x) })
#define AOT_VC256(x) ((aotv256){ (x), (x), (x), (x) })

/* --- blocks -------------------------------------------------------------------------------- */

/*
 * 11 parameters: preserve_none passes 12 in registers, and an indirect tail call needs one
 * of them free for its target (RAX); env, the same for every block, is a global instead.
 */
#define AOT_PARAMS uint32_t g_eax, uint32_t g_ecx, uint32_t g_edx, uint32_t g_ebx,          \
                   uint32_t g_esp, uint32_t g_ebp, uint32_t g_esi, uint32_t g_edi,           \
                   uint32_t g_cc_dst, uint32_t g_cc_src, uint32_t g_cc_op
#define AOT_ARGS g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi, g_cc_dst, g_cc_src, \
                 g_cc_op
typedef AOT_CC void (*aot_fn_t)(AOT_PARAMS);

/* the blob's own data (aot_main.c) */
typedef struct aot_ix {
    uint32_t pc, fl, id, pad;
} aot_ix_t;
/*
 * Set by aot_enter before any block runs, constant while blocks run: declared const so that the
 * compiler keeps them in registers across guest stores (aot_main.c, which writes them, sees them
 * without the const).
 */
#ifndef AOT_MAIN
extern char *const aot_env AOT_HIDDEN;       /* the CPU's env */
extern const uintptr_t *const aot_frd AOT_HIDDEN;   /* flat page tables: host - guest per page */
extern const uintptr_t *const aot_fwr AOT_HIDDEN;
#else
extern char *aot_env AOT_HIDDEN;
extern const uintptr_t *aot_frd AOT_HIDDEN;
extern const uintptr_t *aot_fwr AOT_HIDDEN;
#endif
extern uint32_t aot_valid[] AOT_HIDDEN;      /* nonzero: entered through its trampoline */
extern uint32_t aot_gen AOT_HIDDEN;
extern uint32_t aot_cur[2] AOT_HIDDEN;       /* the insn's pc and cc_op, for a fault */
extern void *aot_imp[] AOT_HIDDEN;           /* xemu's helpers, by name (aot_gen.h) */
extern const aot_fn_t aot_fns[] AOT_HIDDEN;
extern const aot_ix_t aot_ix[] AOT_HIDDEN;   /* (pc, flags) -> block, open addressing */
void aot_enter(char *env, uint32_t id) AOT_HIDDEN;

/* a host pc inside the blob for helpers' unwinding (accel/tcg/aot.c aot_restore_state) */
#define AOT_RA ((uintptr_t)&aot_enter)

static inline uint32_t aot_lookup(uint32_t pc, uint32_t fl)
{
    uint32_t h = (((pc * 0x9E3779B1u) ^ (fl * 0x85EBCA77u)) >> 7) & AOT_IX_MASK;
    for (;;) {
        const aot_ix_t *e = &aot_ix[h];
        if (!e->id) {
            return 0;
        }
        if (e->pc == pc && e->fl == fl && aot_valid[e->id]) {
            return e->id;
        }
        h = (h + 1) & AOT_IX_MASK;
    }
}

/* --- env ----------------------------------------------------------------------------------- */

#define AOT_LDM(T, base, off) \
    ({ T _lv; __builtin_memcpy(&_lv, (char *)(base) + (off), sizeof(T)); _lv; })
#define AOT_LDMV(T, base, off) (*(volatile T *)((char *)(base) + (off)))
#define AOT_STM(T, base, off, v) \
    do { T _sv = (T)(v); __builtin_memcpy((char *)(base) + (off), &_sv, sizeof(T)); } while (0)
#define AOT_STMV(T, base, off, v) (*(volatile T *)((char *)(base) + (off)) = (T)(v))
#define AOT_LD_I32(off) AOT_LDM(uint32_t, env, off)
#define AOT_LD_I64(off) AOT_LDM(uint64_t, env, off)
#define AOT_ST_I32(off, v) AOT_STM(uint32_t, env, off, v)
#define AOT_ST_I64(off, v) AOT_STM(uint64_t, env, off, v)

/* the parameter registers and eip to env (before an exit or anything that reads env) */
#define AOT_SYNC_P() do {                                                       \
        AOT_ST_I32(AOT_OFF_EAX, g_eax); AOT_ST_I32(AOT_OFF_ECX, g_ecx);         \
        AOT_ST_I32(AOT_OFF_EDX, g_edx); AOT_ST_I32(AOT_OFF_EBX, g_ebx);         \
        AOT_ST_I32(AOT_OFF_ESP, g_esp); AOT_ST_I32(AOT_OFF_EBP, g_ebp);         \
        AOT_ST_I32(AOT_OFF_ESI, g_esi); AOT_ST_I32(AOT_OFF_EDI, g_edi);         \
        AOT_ST_I32(AOT_OFF_CC_DST, g_cc_dst); AOT_ST_I32(AOT_OFF_CC_SRC, g_cc_src); \
        AOT_ST_I32(AOT_OFF_CC_OP, g_cc_op); AOT_ST_I32(AOT_OFF_EIP, g_eip);     \
    } while (0)

#define AOT_CUR(pc, cc) (aot_cur[0] = (pc), aot_cur[1] = (uint32_t)(cc))

/* a block starts: eip is its pc; not entered through its trampoline this generation: exit */
#define AOT_PROLOGUE(ID, PC)                                                    \
    char *env = aot_env;                                                        \
    uint32_t g_eip = (PC);                                                      \
    uint64_t aot_c = 0;                                                         \
    (void)aot_c;                                                                \
    if (AOT_UNLIKELY(!aot_valid[ID])) {                                          \
        AOT_SYNC_P();                                                           \
        return;                                                                 \
    }

#define AOT_EXIT() return
#define AOT_EXIT_REQ() return
#define AOT_BARRIER() __asm__ volatile("" ::: "memory")

/* to the block at eip: looked up (scripts/aot-build.py turns known targets into AOT_CHAIN) */
#define AOT_IND() do {                                                          \
        uint32_t _id = aot_lookup(g_eip, AOT_MYFL);                             \
        if (AOT_LIKELY(_id)) {                                                  \
            __attribute__((musttail)) return aot_fns[_id](AOT_ARGS);            \
        }                                                                       \
        AOT_SYNC_P();                                                           \
        return;                                                                 \
    } while (0)
#define AOT_CHAIN(F, PC) do {                                                   \
        if (AOT_LIKELY(g_eip == (PC))) {                                        \
            __attribute__((musttail)) return F(AOT_ARGS);                       \
        }                                                                       \
        AOT_IND();                                                              \
    } while (0)

/*
 * Regions (scripts/aot-build.py --regions): blocks that jump to each other nearby are labels B<id>
 * of one function. A jump between them is a goto; the target's own entry check (valid) still runs.
 * Entering from outside goes through the block's function, which names it in aot_rent.
 */
extern uint32_t aot_rent AOT_HIDDEN;
#define AOT_RCHAIN(B, PC) do {                                                  \
        if (AOT_LIKELY(g_eip == (PC))) {                                        \
            goto B;                                                             \
        }                                                                       \
        AOT_IND();                                                              \
    } while (0)

/* --- guest memory: QEMU's TLB, as tcg/i386/tcg-target.c.inc prepare_host_addr ---------------- */

#define AOT_TLBE(fofs, a)                                                       \
    ((char *)AOT_LDM(uintptr_t, env, (fofs) + AOT_TLBF_TABLE) +                \
     (uintptr_t)(((uint32_t)(a) >> (AOT_PAGE_BITS - AOT_TLB_ENTRY_BITS)) &     \
                 (uint32_t)AOT_LDM(uintptr_t, env, (fofs) + AOT_TLBF_MASK)))
#define AOT_HOST(e, a) ((char *)((uintptr_t)(a) + AOT_LDM(uintptr_t, (e), AOT_TLBE_ADDEND)))

typedef uint64_t (*aot_ld_fn)(char *, uint64_t, uint32_t, uintptr_t);
typedef void (*aot_st32_fn)(char *, uint64_t, uint32_t, uint32_t, uintptr_t);
typedef void (*aot_st64_fn)(char *, uint64_t, uint64_t, uint32_t, uintptr_t);
#define AOT_SLOW_LD1(a, oi) ((aot_ld_fn)AOT_H(ldub_mmu))(env, (a), (oi), AOT_RA)
#define AOT_SLOW_LD2(a, oi) ((aot_ld_fn)AOT_H(lduw_mmu))(env, (a), (oi), AOT_RA)
#define AOT_SLOW_LD4(a, oi) ((aot_ld_fn)AOT_H(ldul_mmu))(env, (a), (oi), AOT_RA)
#define AOT_SLOW_LD8(a, oi) ((aot_ld_fn)AOT_H(ldq_mmu))(env, (a), (oi), AOT_RA)
#define AOT_SLOW_ST1(a, v, oi) ((aot_st32_fn)AOT_H(stb_mmu))(env, (a), (uint32_t)(v), (oi), AOT_RA)
#define AOT_SLOW_ST2(a, v, oi) ((aot_st32_fn)AOT_H(stw_mmu))(env, (a), (uint32_t)(v), (oi), AOT_RA)
#define AOT_SLOW_ST4(a, v, oi) ((aot_st32_fn)AOT_H(stl_mmu))(env, (a), (uint32_t)(v), (oi), AOT_RA)
#define AOT_SLOW_ST8(a, v, oi) ((aot_st64_fn)AOT_H(stq_mmu))(env, (a), (uint64_t)(v), (oi), AOT_RA)

/*
 * The flat page tables (accel/tcg/cputlb.c aft_*): for the MMU index the game's code runs in
 * (AOT_FAST_MMU, aot_gen.h), one entry per 4 KiB guest page: host - guest, 0 = take the slow path.
 * A load is a shift, one load of the entry and the access, where QEMU's TLB needs two loads from
 * env, a masked compare and the addend's load. Accesses that must be aligned (cmpm has the
 * alignment bits) and other MMU indexes keep QEMU's TLB. The slow path (QEMU's helper, then the
 * table refilled) is aot_slow_ld/aot_slow_st.
 */
#define AOT_FAST_OK(oi, cmpm) (((oi) & 15) == AOT_FAST_MMU && ((cmpm) & 0xfffu) == 0)
#define AOT_NOCROSS(a, SZ) ((SZ) == 1 || ((a) & 0xfffu) <= 0x1000u - (SZ))
/*
 * The access stays in its page: aligned ones always do (one test), the rest are checked. Most
 * guest accesses are aligned; the page-offset compare costs four instructions on each.
 */
#define AOT_FITS(a, SZ) ((SZ) == 1 || AOT_LIKELY(((a) & ((SZ) - 1)) == 0) || AOT_NOCROSS(a, SZ))
typedef void (*aot_st_fn)(char *, uint64_t, uint64_t, uint32_t, uintptr_t);
#define AOT_SLOW_LD(a, oi) ((aot_ld_fn)AOT_H(aot_slow_ld))(env, (a), (oi), AOT_RA)
#define AOT_SLOW_ST(a, v, oi) ((aot_st_fn)AOT_H(aot_slow_st))(env, (a), (uint64_t)(v), (oi), AOT_RA)

#define AOT_LD(dst, T, a, SZ, LT, fofs, adj, cmpm, oi, pc, cc) do {             \
        uint32_t _a = (uint32_t)(a);                                            \
        if (AOT_FAST_OK(oi, cmpm)) {                                            \
            uintptr_t _t = aot_frd[_a >> 12];                                   \
            if (AOT_LIKELY(_t != 0 && AOT_FITS(_a, SZ))) {                   \
                LT _v;                                                          \
                __builtin_memcpy(&_v, (char *)(_t + _a), SZ);                   \
                dst = (T)_v;                                                    \
            } else {                                                            \
                AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                   \
                dst = (T)(LT)AOT_SLOW_LD(_a, oi);                               \
            }                                                                   \
        } else {                                                                \
            char *_e = AOT_TLBE(fofs, _a);                                      \
            if (AOT_LIKELY(AOT_LDM(uint32_t, _e, AOT_TLBE_READ) == ((_a + (adj)) & (cmpm)))) { \
                LT _v;                                                          \
                __builtin_memcpy(&_v, AOT_HOST(_e, _a), SZ);                    \
                dst = (T)_v;                                                    \
            } else {                                                            \
                AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                   \
                dst = (T)(LT)AOT_SLOW_LD##SZ(_a, oi);                           \
            }                                                                   \
        }                                                                       \
    } while (0)

#define AOT_ST(val, a, SZ, ST, fofs, adj, cmpm, oi, pc, cc) do {                \
        uint32_t _a = (uint32_t)(a);                                            \
        ST _v = (ST)(val);                                                      \
        if (AOT_FAST_OK(oi, cmpm)) {                                            \
            uintptr_t _t = aot_fwr[_a >> 12];                                   \
            if (AOT_LIKELY(_t != 0 && AOT_FITS(_a, SZ))) {                   \
                __builtin_memcpy((char *)(_t + _a), &_v, SZ);                   \
            } else {                                                            \
                AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                   \
                AOT_SLOW_ST(_a, _v, oi);                                        \
            }                                                                   \
        } else {                                                                \
            char *_e = AOT_TLBE(fofs, _a);                                      \
            if (AOT_LIKELY(AOT_LDM(uint32_t, _e, AOT_TLBE_WRITE) == ((_a + (adj)) & (cmpm)))) { \
                __builtin_memcpy(AOT_HOST(_e, _a), &_v, SZ);                    \
            } else {                                                            \
                AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                   \
                AOT_SLOW_ST##SZ(_a, _v, oi);                                    \
            }                                                                   \
        }                                                                       \
    } while (0)

#define AOT_LD128(lo, hi, a, fofs, adj, cmpm, oi, pc, cc) do {                  \
        uint32_t _a = (uint32_t)(a);                                            \
        char *_e = AOT_TLBE(fofs, _a);                                          \
        if (AOT_LIKELY(AOT_LDM(uint32_t, _e, AOT_TLBE_READ) == ((_a + (adj)) & (cmpm)))) { \
            uint64_t _v[2];                                                     \
            __builtin_memcpy(_v, AOT_HOST(_e, _a), 16);                         \
            lo = _v[0];                                                         \
            hi = _v[1];                                                         \
        } else {                                                                \
            AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                       \
            unsigned __int128 _r = ((unsigned __int128 (*)(char *, uint64_t, uint32_t, uintptr_t)) \
                                    AOT_H(ld16_mmu))(env, _a, (oi), AOT_RA);    \
            lo = (uint64_t)_r;                                                  \
            hi = (uint64_t)(_r >> 64);                                          \
        }                                                                       \
    } while (0)

#define AOT_ST128(lo, hi, a, fofs, adj, cmpm, oi, pc, cc) do {                  \
        uint32_t _a = (uint32_t)(a);                                            \
        uint64_t _v[2] = { (uint64_t)(lo), (uint64_t)(hi) };                    \
        char *_e = AOT_TLBE(fofs, _a);                                          \
        if (AOT_LIKELY(AOT_LDM(uint32_t, _e, AOT_TLBE_WRITE) == ((_a + (adj)) & (cmpm)))) { \
            __builtin_memcpy(AOT_HOST(_e, _a), _v, 16);                         \
        } else {                                                                \
            AOT_SYNC_P(); AOT_SYNC_NP(); AOT_CUR(pc, cc);                       \
            unsigned __int128 _w = (unsigned __int128)_v[1] << 64 | _v[0];      \
            ((void (*)(char *, uint64_t, unsigned __int128, uint32_t, uintptr_t)) \
             AOT_H(st16_mmu))(env, _a, _w, (oi), AOT_RA);                       \
        }                                                                       \
    } while (0)

/* --- integers ------------------------------------------------------------------------------ */

static inline uint32_t AOT_ROTL32(uint32_t a, uint32_t b) { b &= 31; return (a << b) | (a >> ((32 - b) & 31)); }
static inline uint32_t AOT_ROTR32(uint32_t a, uint32_t b) { b &= 31; return (a >> b) | (a << ((32 - b) & 31)); }
static inline uint64_t AOT_ROTL64(uint64_t a, uint64_t b) { b &= 63; return (a << b) | (a >> ((64 - b) & 63)); }
static inline uint64_t AOT_ROTR64(uint64_t a, uint64_t b) { b &= 63; return (a >> b) | (a << ((64 - b) & 63)); }

/* --- xemu's x87 on host SSE (tcg/i386/tcg-target.c.inc, the FP ops) -------------------------- */

/*
 * The host MXCSR as translated code last set it, 0 when not known (aot_enter: the JIT's code ran
 * in between). Blocks with x87 code set it from the guest's control word (xemu's flcr) at their
 * first FP op; the inline SSE ops want 0x1F80. Only a change costs an LDMXCSR (slow on Jaguar):
 * x87 blocks in a row with the same rounding share one. Nothing else in xemu writes the host
 * MXCSR (its hard-FPU helpers compute under it).
 */
extern uint32_t aot_csr_cur AOT_HIDDEN;
#define AOT_SETCSR(v) do {                                                      \
        const uint32_t _csr = (uint32_t)(v);                                    \
        if (AOT_UNLIKELY(_csr != aot_csr_cur)) {                                \
            _mm_setcsr(_csr);                                                   \
            aot_csr_cur = _csr;                                                 \
        }                                                                       \
    } while (0)

static inline float AOT_LD80_F32(const char *p) { long double x; __builtin_memcpy(&x, p, 10); return (float)x; }
static inline double AOT_LD80_F64(const char *p) { long double x; __builtin_memcpy(&x, p, 10); return (double)x; }
static inline void AOT_ST80(char *p, long double x) { __builtin_memcpy(p, &x, 10); }

/* comiss/comisd, then the host's flags (pushf), as the backend */
static inline uint32_t AOT_COMISS(float a, float b)
{
    uint64_t f;
    __asm__ volatile("comiss %2, %1\n\tpushfq\n\tpopq %0" : "=r"(f) : "x"(a), "x"(b) : "cc");
    return (uint32_t)f;
}
static inline uint32_t AOT_COMISD(double a, double b)
{
    uint64_t f;
    __asm__ volatile("comisd %2, %1\n\tpushfq\n\tpopq %0" : "=r"(f) : "x"(a), "x"(b) : "cc");
    return (uint32_t)f;
}

static inline float AOT_FSIN32(float a) { long double x = a; __asm__("fsin" : "+t"(x)); return (float)x; }
static inline double AOT_FSIN64(double a) { long double x = a; __asm__("fsin" : "+t"(x)); return (double)x; }
static inline float AOT_FCOS32(float a) { long double x = a; __asm__("fcos" : "+t"(x)); return (float)x; }
static inline double AOT_FCOS64(double a) { long double x = a; __asm__("fcos" : "+t"(x)); return (double)x; }

/* conversions that round as MXCSR says (cvtss2si, not C's truncation) */
static inline uint32_t AOT_CVTSS2SI(float a) { return (uint32_t)_mm_cvtss_si32(_mm_set_ss(a)); }
static inline uint64_t AOT_CVTSS2SI64(float a) { return (uint64_t)_mm_cvtss_si64(_mm_set_ss(a)); }
static inline uint32_t AOT_CVTSD2SI(double a) { return (uint32_t)_mm_cvtsd_si32(_mm_set_sd(a)); }
static inline uint64_t AOT_CVTSD2SI64(double a) { return (uint64_t)_mm_cvtsd_si64(_mm_set_sd(a)); }

/* --- SSE scalar helpers as host instructions (scripts/aot-build.py swaps the calls) ------------
 *
 * QEMU computes these with softfloat (target/i386/ops_sse.h) behind a helper call and a sync of
 * every guest register around it. The host's own SSE gives the same results bit for bit when
 * it rounds the same way: these run the instruction (inline asm keeps the operand order, which
 * decides the NaN returned when both inputs are NaNs) when the guest's MXCSR is the default
 * (round to nearest, no flush-to-zero, no denormals-are-zero) with the host's MXCSR set to
 * 0x1F80, and call QEMU's helper otherwise. The guest's MXCSR exception flags are not updated
 * (QEMU raises no SIMD exceptions; games don't read the sticky flags). */

#define AOT_SSE_CSR() AOT_SETCSR(0x1F80u)
#define AOT_GUEST_CSR_DEFAULT(e) ((AOT_LDM(uint32_t, (e), AOT_OFF_MXCSR) & 0xE040u) == 0)

typedef void (*aot_sse3_fn)(uintptr_t, uintptr_t, uintptr_t, uintptr_t);
typedef void (*aot_sse2_fn)(uintptr_t, uintptr_t, uintptr_t);

/* lanes 1..3 of v into d (the scalar op leaves d's upper lanes as v's) */
static inline void aot_ss_upper(uintptr_t d, uintptr_t v)
{
    if (d != v) {
        uint32_t u[3];
        __builtin_memcpy(u, (char *)v + 4, 12);
        __builtin_memcpy((char *)d + 4, u, 12);
    }
}

#define AOT_SS_OP(NAME, INSN)                                                   \
    static inline void AOT_I_##NAME(uintptr_t envp, uintptr_t d, uintptr_t v, uintptr_t s) \
    {                                                                           \
        char *e = (char *)envp;                                                 \
        if (AOT_LIKELY(AOT_GUEST_CSR_DEFAULT(e))) {                             \
            float a = AOT_LDM(float, v, 0), b = AOT_LDM(float, s, 0);          \
            AOT_SSE_CSR();                                                      \
            __asm__(INSN " %1, %0" : "+x"(a) : "x"(b));                         \
            aot_ss_upper(d, v);                                                 \
            AOT_STM(float, d, 0, a);                                            \
        } else {                                                                \
            ((aot_sse3_fn)AOT_H(NAME))(envp, d, v, s);                          \
        }                                                                       \
    }
AOT_SS_OP(addss, "addss")
AOT_SS_OP(subss, "subss")
AOT_SS_OP(mulss, "mulss")
AOT_SS_OP(divss, "divss")

/* comiss/ucomiss: CC_SRC = ZF/PF/CF as the comparison says, CC_OP = CC_OP_EFLAGS (0) */
static inline uint32_t aot_comis_flags(float a, float b)
{
    if (a != a || b != b) {
        return 0x0040 | 0x0004 | 0x0001;
    }
    return a < b ? 0x0001 : a == b ? 0x0040 : 0;
}
#define AOT_COMIS_OP(NAME)                                                      \
    static inline void AOT_I_##NAME(uintptr_t envp, uintptr_t d, uintptr_t s)  \
    {                                                                           \
        char *e = (char *)envp;                                                 \
        if (AOT_LIKELY(AOT_GUEST_CSR_DEFAULT(e))) {                             \
            AOT_STM(uint32_t, e, AOT_OFF_CC_SRC,                                \
                    aot_comis_flags(AOT_LDM(float, d, 0), AOT_LDM(float, s, 0))); \
            AOT_STM(uint32_t, e, AOT_OFF_CC_OP, 0);                             \
        } else {                                                                \
            ((aot_sse2_fn)AOT_H(NAME))(envp, d, s);                             \
        }                                                                       \
    }
AOT_COMIS_OP(comiss)
AOT_COMIS_OP(ucomiss)

static inline void AOT_I_cvtsi2ss(uintptr_t envp, uintptr_t d, uint32_t val)
{
    char *e = (char *)envp;
    if (AOT_LIKELY(AOT_GUEST_CSR_DEFAULT(e))) {
        float f;
        AOT_SSE_CSR();
        __asm__("cvtsi2ss %1, %0" : "=x"(f) : "r"((int32_t)val));
        AOT_STM(float, d, 0, f);
    } else {
        ((void (*)(uintptr_t, uintptr_t, uint32_t))AOT_H(cvtsi2ss))(envp, d, val);
    }
}

/* truncation: the rounding mode doesn't matter; NaN and overflow give 0x80000000 as QEMU's */
static inline int32_t AOT_I_cvttss2si(uintptr_t envp, uintptr_t s)
{
    char *e = (char *)envp;
    if (AOT_LIKELY(AOT_GUEST_CSR_DEFAULT(e))) {
        int32_t r;
        __asm__("cvttss2si %1, %0" : "=r"(r) : "x"(AOT_LDM(float, s, 0)));
        return r;
    }
    return ((int32_t (*)(uintptr_t, uintptr_t))AOT_H(cvttss2si))(envp, s);
}

static inline uint32_t AOT_F2U(float f) { uint32_t u; __builtin_memcpy(&u, &f, 4); return u; }
static inline float AOT_U2F(uint32_t u) { float f; __builtin_memcpy(&f, &u, 4); return f; }
static inline uint64_t AOT_D2U(double d) { uint64_t u; __builtin_memcpy(&u, &d, 8); return u; }
static inline double AOT_U2D(uint64_t u) { double d; __builtin_memcpy(&d, &u, 8); return d; }

/* --- hooks: a game's own functions replaced by C written for the PS4 (aot/hooks/<title>.c) ------
 *
 * scripts/aot-build.py --hooks: the block at a hooked pc becomes "valid? then the hook"; the
 * block's translated code stays as the fallback (aot_hook_orig) for whatever the hook doesn't
 * take on - memory that isn't plain RAM in the flat page tables, overlapping arguments, unusual
 * CPU state. A hook does all that the guest function does (memory, registers, flags, x87 state,
 * the return) so that the game can't tell: scripts/aot-hooktest.py runs the hook and the
 * translated original on the same inputs and compares guest memory and CPU state bit for bit.
 * Only the first block's code is checked (its trampoline's hash): hook functions that the game
 * doesn't rewrite.
 */
extern aot_fn_t aot_hook_orig AOT_HIDDEN;      /* the hooked block's own translated code */
extern uint32_t aot_hook_fl AOT_HIDDEN;        /* its flags (the return's lookup) */

/* CPUX86State fields after the ones aot_abi.h names (QEMU's layout: df follows cc_op; fpus and
 * fpuc follow fpstt, then fptags[8]) */
#define AOT_OFF_DF (AOT_OFF_CC_OP + 4)
#define AOT_OFF_FPUS (AOT_OFF_FPSTT + 4)
#define AOT_OFF_FPUC (AOT_OFF_FPSTT + 6)
#define AOT_OFF_FPTAGS (AOT_OFF_FPSTT + 8)

/* a host pointer to guest [a, a + len) when it is in one page of plain RAM (writes: one the flat
 * write table maps, i.e. no code or dirty tracking on it), else NULL */
static inline void *aot_hptr(uint32_t a, uint32_t len, int write)
{
    if (len == 0 || (a & 0xfffu) + len > 0x1000u) {
        return 0;
    }
    const uintptr_t t = (write ? aot_fwr : aot_frd)[a >> 12];
    return t ? (void *)(t + a) : 0;
}

static inline int aot_overlap(uint32_t a, uint32_t alen, uint32_t b, uint32_t blen)
{
    return a < b + blen && b < a + alen;
}

/* guest memory through host pointers (any alignment; scripts/hookgen.py's hooks) */
static inline float aot_hk_ldf(const uint8_t *p) { float f; __builtin_memcpy(&f, p, 4); return f; }
static inline double aot_hk_ldd(const uint8_t *p) { double d; __builtin_memcpy(&d, p, 8); return d; }
static inline void aot_hk_stf(uint8_t *p, float f) { __builtin_memcpy(p, &f, 4); }
static inline void aot_hk_std(uint8_t *p, double d) { __builtin_memcpy(p, &d, 8); }
static inline uint32_t aot_hk_ld32(const uint8_t *p) { uint32_t v; __builtin_memcpy(&v, p, 4); return v; }
static inline void aot_hk_st32(uint8_t *p, uint32_t v) { __builtin_memcpy(p, &v, 4); }

#define AOT_HOOK(PC) AOT_HIDDEN AOT_CC void H_##PC(AOT_PARAMS)
#define AOT_HOOK_BEGIN(PC)                                                      \
    char *env = aot_env;                                                        \
    uint32_t g_eip = 0x##PC##u;                                                 \
    (void)env
/* the game's own code does it (scripts/aot-hooktest.py counts these: a test must reach the hook) */
#ifdef AOT_HOOKTEST
extern int aot_hooktest_fallbacks;
#define AOT_HOOKTEST_COUNT() (aot_hooktest_fallbacks++)
#else
#define AOT_HOOKTEST_COUNT() ((void)0)
#endif
#define AOT_HOOK_FALLBACK() do {                                                \
        AOT_HOOKTEST_COUNT();                                                   \
        __attribute__((musttail)) return aot_hook_orig(AOT_ARGS);               \
    } while (0)
/* back to the game at RET with the registers as the hook left them */
#define AOT_HOOK_RETURN(RET) do {                                               \
        g_eip = (RET);                                                          \
        const uint32_t _id = aot_lookup(g_eip, aot_hook_fl);                    \
        if (AOT_LIKELY(_id)) {                                                  \
            __attribute__((musttail)) return aot_fns[_id](AOT_ARGS);            \
        }                                                                       \
        AOT_SYNC_P();                                                           \
        return;                                                                 \
    } while (0)

#endif
