/*
 * Crash Bandicoot: The Wrath of Cortex (USA), XBE title ID 56550003: game functions in native C
 * (scripts/aot-build.py --hooks; aot/aot_rt.h "hooks").
 *
 * Under xemu every x87 instruction is one host SSE operation on doubles (its "hard FPU"), rounded
 * as the guest's control word says: a float times a float is exact in a double, so these give
 * the same bits as the game's code when they do the same additions in the same order. Each was
 * checked against the translated original by scripts/aot-hooktest.py.
 *
 * Not the game's code: the operations it performs, written out.
 */

#define CRASH_MTX_TMP 0x001a3b48u   /* MtxMul's static result buffer (16 floats) */

/*
 * 0x000a1380 MtxMul(float dst[16], const float a[16], const float b[16]): dst = a * b for affine
 * 4x4 matrices (rows: x, y, z axes with 0 in the 4th column, then the translation and 1). The
 * game builds the product in CRASH_MTX_TMP, then copies it (rep movsd), so dst may be a or b.
 * Profiled at ~2.5 % of the emulated CPU's time in gameplay.
 */
AOT_HOOK(000a1380)
{
    AOT_HOOK_BEGIN(000a1380);
    const uint32_t *sp = (const uint32_t *)aot_hptr(g_esp, 16, 0);
    if (!sp || AOT_LDM(int32_t, env, AOT_OFF_DF) != 1) {
        AOT_HOOK_FALLBACK();
    }
    const uint32_t ret = sp[0], dst = sp[1], pa = sp[2], pb = sp[3];
    const float *a = (const float *)aot_hptr(pa, 64, 0);
    const float *b = (const float *)aot_hptr(pb, 64, 0);
    float *t = (float *)aot_hptr(CRASH_MTX_TMP, 64, 1);
    float *d = (float *)aot_hptr(dst, 64, 1);
    uint32_t *push = (uint32_t *)aot_hptr(g_esp - 8, 8, 1);
    /*
     * The game interleaves its reads of a and b with its writes (the buffer, the two pushes):
     * when they could meet, or the copy could overlap the buffer, its own code runs.
     */
    if (!a || !b || !t || !d || !push ||
        aot_overlap(pa, 64, CRASH_MTX_TMP, 64) || aot_overlap(pb, 64, CRASH_MTX_TMP, 64) ||
        aot_overlap(dst, 64, CRASH_MTX_TMP, 64) || aot_overlap(pa, 64, g_esp - 8, 8) ||
        aot_overlap(pb, 64, g_esp - 8, 8) || aot_overlap(dst, 64, g_esp - 8, 12)) {
        /* (the copy comes before the pops and the return read the stack) */
        AOT_HOOK_FALLBACK();
    }

    /* x87's rounding control in the host's MXCSR, as xemu's flcr sets it */
    AOT_SETCSR(((uint32_t)AOT_LDM(uint16_t, env, AOT_OFF_FPUC) & 0xc00u) << 3 | 0x1f80u);

#define A(i) ((double)a[i])
#define B(i) ((double)b[i])
    /* each line: the game's three products added in its order, then (translation) + b[12..14] */
    float r[16];
    r[0] = (float)((A(1) * B(4) + A(0) * B(0)) + B(8) * A(2));
    r[1] = (float)((B(1) * A(0) + A(1) * B(5)) + B(9) * A(2));
    r[2] = (float)((B(10) * A(2) + A(1) * B(6)) + B(2) * A(0));
    r[3] = 0.0f;
    r[4] = (float)((A(5) * B(4) + A(4) * B(0)) + A(6) * B(8));
    r[5] = (float)((A(4) * B(1) + A(5) * B(5)) + A(6) * B(9));
    r[6] = (float)((B(10) * A(6) + A(5) * B(6)) + B(2) * A(4));
    r[7] = 0.0f;
    r[8] = (float)((A(10) * B(8) + B(4) * A(9)) + A(8) * B(0));
    r[9] = (float)((A(10) * B(9) + B(5) * A(9)) + A(8) * B(1));
    r[10] = (float)((A(10) * B(10) + A(8) * B(2)) + A(9) * B(6));
    r[11] = 0.0f;
    r[12] = (float)(((A(13) * B(4) + A(12) * B(0)) + A(14) * B(8)) + B(12));
    r[13] = (float)(((A(12) * B(1) + A(13) * B(5)) + A(14) * B(9)) + B(13));
    r[14] = (float)(((B(10) * A(14) + A(13) * B(6)) + B(2) * A(12)) + B(14));
    r[15] = 1.0f;
#undef A
#undef B
    __builtin_memcpy(t, r, 64);
    __builtin_memcpy(d, r, 64);

    /* the two pushes it leaves below the stack, its two x87 stack slots popped (empty), and the
     * registers as its pops, rep movsd and return leave them */
    const uint32_t top = AOT_LDM(uint32_t, env, AOT_OFF_FPSTT);
    AOT_STM(uint8_t, env, AOT_OFF_FPTAGS + ((top - 1) & 7), 1);
    AOT_STM(uint8_t, env, AOT_OFF_FPTAGS + ((top - 2) & 7), 1);
    push[1] = g_esi;
    push[0] = g_edi;
    g_eax = pb;
    g_ecx = 0;
    g_esp += 4;
    AOT_HOOK_RETURN(ret);
}
