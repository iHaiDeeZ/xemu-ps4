#!/usr/bin/env python3
"""Writes a hook (aot/hooks/<title>.c) for a straight-line x87 game function, from its code.

    python scripts/hookgen.py <code dump> <base hex> <function hex> [--name Text]

<code dump> is guest memory saved from <base> (scripts/hooker.py code, or the live console's
`hmp memsave`). The function is read from its address to its `ret` and executed symbolically:
x87 loads, arithmetic and stores, integer moves, push/pop, `rep movsd` and the return become C in
the same order, x87 values as doubles (what xemu's hard FPU computes), guest memory through host
pointers that alias exactly as the guest addresses do. So the hook does what the game's code does
for any arguments; it gives the game's own code the call (fallback) when an accessed range isn't
plain RAM in one page, or the direction flag is set. Anything else in the function (branches,
calls, flag-setting arithmetic, other x87 ops) stops the generator.

Check the output with scripts/aot-hooktest.py before shipping it.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import os

REGS = ['eax', 'ecx', 'edx', 'ebx', 'esp', 'ebp', 'esi', 'edi']


class Unsupported(Exception):
    pass


def disassemble(dump, base, start):
    """(address, raw bytes, Intel-syntax text) from start to the first ret."""
    r = subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'i386', '-M', 'intel',
                        f'--adjust-vma=0x{base:x}', f'--start-address=0x{start:x}',
                        f'--stop-address=0x{start + 0x2000:x}', dump],
                       capture_output=True, text=True)
    out = []
    pending = None
    for line in r.stdout.splitlines():
        m = re.match(r'\s+([0-9a-f]+):\t([0-9a-f ]+)\t(.*)$', line)
        if m:
            if pending:
                out.append(pending)
            pending = [int(m.group(1), 16), bytes.fromhex(m.group(2).replace(' ', '')),
                       m.group(3).strip()]
            if pending[2].startswith('ret'):
                out.append(pending)
                return out
            continue
        m = re.match(r'\s+([0-9a-f]+):\t([0-9a-f ]+)$', line)      # continuation bytes
        if m and pending:
            pending[1] += bytes.fromhex(m.group(2).replace(' ', ''))
    raise Unsupported('no ret within 8 KiB')


class Gen:
    def __init__(self):
        self.regs = {r: f'g_{r}' for r in REGS}
        self.sp = 0                 # esp - entry esp
        self.fp = []                # x87 stack, top last: C double variables
        self.maxdepth = 0
        self.ntmp = 0
        self.body = []
        self.stack_lo, self.stack_hi = 0, 0
        self.bases = {}             # guest address expression -> [lo, hi, write]
        self.args = {}              # entry stack offset -> variable
        self.uses_rep = False
        self.ret = None

    def tmp(self, kind='double'):
        self.ntmp += 1
        return f'x{self.ntmp}' if kind == 'double' else f'v{self.ntmp}'

    # --- memory operands --------------------------------------------------------------------------
    def operand(self, text, size, write):
        """A memory operand -> C expression of its host address (bases checked at the top)."""
        m = re.search(r'\[([^\]]+)\]', text)
        if m:
            expr = m.group(1).replace(' ', '')
            if ':' in expr:
                expr = expr.split(':', 1)[1]
            m2 = re.fullmatch(r'(e[a-z]{2})(?:([+-])0x([0-9a-f]+))?', expr)
            if not m2:
                raise Unsupported(f'address {expr}')
            reg, sign, disp = m2.group(1), m2.group(2), m2.group(3)
            d = int(disp, 16) if disp else 0
            if sign == '-':
                d = -d
            if reg == 'esp':
                off = self.sp + d
                self.stack_lo = min(self.stack_lo, off)
                self.stack_hi = max(self.stack_hi, off + size)
                if write and off >= 0:
                    raise Unsupported('stores above the entry stack pointer')
                return f'(S + {off})'
            base = self.regs[reg]
            if not re.fullmatch(r'(g_e[a-z]{2}|a\d+)', base):
                raise Unsupported(f'base {reg} = {base} (not an argument or entry register)')
            b = self.bases.setdefault(base, [d, d + size, False])
            b[0], b[1] = min(b[0], d), max(b[1], d + size)
            b[2] |= write
            return f'(P_{base} + {d})'
        m = re.search(r'ds:0x([0-9a-f]+)', text)
        if m:
            addr = int(m.group(1), 16)
            key = f'0x{addr & ~0xfff:08x}u'
            b = self.bases.setdefault(key, [addr & 0xfff, (addr & 0xfff) + size, False])
            b[0], b[1] = min(b[0], addr & 0xfff), max(b[1], (addr & 0xfff) + size)
            b[2] |= write
            return f'(P_{key[:-1]} + {addr & 0xfff})'
        raise Unsupported(f'operand {text}')

    def emit(self, line):
        self.body.append('    ' + line)

    # --- x87 ---------------------------------------------------------------------------------------
    def push(self, expr):
        t = self.tmp()
        self.emit(f'double {t} = {expr};')
        self.fp.append(t)
        self.maxdepth = max(self.maxdepth, len(self.fp))

    def st(self, i):
        if i >= len(self.fp):
            raise Unsupported('x87 stack underflow (values from before the call)')
        return self.fp[-1 - i]

    def set_st(self, i, expr):
        t = self.tmp()
        self.emit(f'double {t} = {expr};')
        self.fp[-1 - i] = t

    def pop(self):
        self.fp.pop()

    def load_fp(self, text):
        if 'DWORD PTR' in text:
            return f'(double)aot_hk_ldf({self.operand(text, 4, False)})'
        if 'QWORD PTR' in text:
            return f'aot_hk_ldd({self.operand(text, 8, False)})'
        raise Unsupported(f'x87 operand {text}')

    def x87(self, raw, text):
        mnem = text.split()[0]
        ops = text[len(mnem):].strip()
        op0 = raw[0]
        # register forms by opcode (Intel SDM; QEMU's fp_arith_ST0_FT0 / STN_ST0 agree)
        if op0 in (0xd8, 0xdc, 0xde) and raw[1] >= 0xc0:
            i, kind = raw[1] & 7, (raw[1] >> 3) & 7
            a, b = (0, i) if op0 == 0xd8 else (i, 0)          # destination, source
            d, s = self.st(a), self.st(b)
            expr = {0: f'{d} + {s}', 1: f'{d} * {s}'}.get(kind)
            if op0 == 0xd8:
                expr = expr or {4: f'{d} - {s}', 5: f'{s} - {d}', 6: f'{d} / {s}', 7: f'{s} / {d}'}[kind]
            else:
                # DC/DE: E0 = ST(i) = ST0 - ST(i), E8 = ST(i) - ST0, F0 = ST0 / ST(i), F8 = ST(i) / ST0
                expr = expr or {4: f'{s} - {d}', 5: f'{d} - {s}', 6: f'{s} / {d}', 7: f'{d} / {s}'}[kind]
            if kind in (2, 3):
                raise Unsupported('fcom')
            self.set_st(a, expr)
            if op0 == 0xde:
                self.pop()
            return
        if op0 == 0xd9 and raw[1] >= 0xc0:
            sub = raw[1]
            if 0xc0 <= sub <= 0xc7:
                self.push(self.st(sub & 7))
            elif 0xc8 <= sub <= 0xcf:
                i = sub & 7
                self.fp[-1], self.fp[-1 - i] = self.fp[-1 - i], self.fp[-1]
            elif sub == 0xe0:
                self.set_st(0, f'-{self.st(0)}')
            elif sub == 0xe1:
                self.set_st(0, f'__builtin_fabs({self.st(0)})')
            elif sub == 0xe8:
                self.push('1.0')
            elif sub == 0xee:
                self.push('0.0')
            else:
                raise Unsupported(text)
            return
        if op0 == 0xdd and raw[1] >= 0xc0:
            sub = raw[1]
            if 0xd8 <= sub <= 0xdf:            # fstp st(i)
                i = sub & 7
                self.fp[-1 - i] = self.st(0)
                self.pop()
            elif 0xd0 <= sub <= 0xd7:          # fst st(i)
                self.fp[-1 - (sub & 7)] = self.st(0)
            else:
                raise Unsupported(text)
            return
        # memory forms
        if mnem == 'fld':
            self.push(self.load_fp(ops))
        elif mnem in ('fadd', 'fmul', 'fsub', 'fsubr', 'fdiv', 'fdivr'):
            v = self.load_fp(ops)
            s = self.st(0)
            expr = {'fadd': f'{s} + {v}', 'fmul': f'{s} * {v}', 'fsub': f'{s} - {v}',
                    'fsubr': f'{v} - {s}', 'fdiv': f'{s} / {v}', 'fdivr': f'{v} / {s}'}[mnem]
            self.set_st(0, expr)
        elif mnem in ('fst', 'fstp'):
            if 'DWORD PTR' in ops:
                self.emit(f'aot_hk_stf({self.operand(ops, 4, True)}, (float){self.st(0)});')
            elif 'QWORD PTR' in ops:
                self.emit(f'aot_hk_std({self.operand(ops, 8, True)}, {self.st(0)});')
            else:
                raise Unsupported(text)
            if mnem == 'fstp':
                self.pop()
        else:
            raise Unsupported(text)

    # --- integer ---------------------------------------------------------------------------------
    def integer(self, raw, text):
        mnem = text.split()[0]
        ops = text[len(mnem):].strip()
        if mnem == 'push':
            if ops not in REGS:
                raise Unsupported(text)
            self.sp -= 4
            self.emit(f'aot_hk_st32({self.operand("[esp]", 4, True)}, {self.regs[ops]});')
            return
        if mnem == 'pop':
            if ops not in REGS:
                raise Unsupported(text)
            v = self.tmp('u32')
            self.emit(f'const uint32_t {v} = aot_hk_ld32({self.operand("[esp]", 4, False)});')
            self.regs[ops] = v
            self.sp += 4
            return
        if mnem == 'mov':
            dst, src = [x.strip() for x in ops.split(',', 1)]
            if dst in REGS and dst != 'esp':
                if src in REGS:
                    self.regs[dst] = self.regs[src]
                elif re.fullmatch(r'0x[0-9a-f]+', src):
                    self.regs[dst] = f'0x{int(src, 16):08x}u'
                elif 'DWORD PTR' in src:
                    m = re.fullmatch(r'DWORD PTR \[esp(?:\+0x([0-9a-f]+))?\]', src)
                    if m:       # an argument (the stack above entry esp isn't written)
                        off = self.sp + (int(m.group(1), 16) if m.group(1) else 0)
                        if off < 0:
                            raise Unsupported('reload from below the entry stack')
                        self.stack_hi = max(self.stack_hi, off + 4)
                        self.args.setdefault(off, f'a{off}')
                        self.regs[dst] = f'a{off}'
                    else:
                        v = self.tmp('u32')
                        self.emit(f'const uint32_t {v} = aot_hk_ld32({self.operand(src, 4, False)});')
                        self.regs[dst] = v
                else:
                    raise Unsupported(text)
                return
            if 'DWORD PTR' in dst:
                if src in REGS:
                    val = self.regs[src]
                elif re.fullmatch(r'0x[0-9a-f]+', src):
                    val = f'0x{int(src, 16):08x}u'
                else:
                    raise Unsupported(text)
                self.emit(f'aot_hk_st32({self.operand(dst, 4, True)}, {val});')
                return
            raise Unsupported(text)
        if mnem == 'lea':
            dst, src = [x.strip() for x in ops.split(',', 1)]
            m = re.fullmatch(r'\[(e[a-z]{2})([+-])0x([0-9a-f]+)\]', src.replace(' ', ''))
            if not m or dst not in REGS or dst == 'esp':
                raise Unsupported(text)
            d = int(m.group(3), 16) * (1 if m.group(2) == '+' else -1)
            self.regs[dst] = f'({self.regs[m.group(1)]} + 0x{d & 0xffffffff:x}u)'
            return
        if text.startswith('rep movs DWORD PTR es:[edi],DWORD PTR ds:[esi]'):
            n = self.regs['ecx']
            if not re.fullmatch(r'0x[0-9a-f]+u', n):
                raise Unsupported('rep movsd with a count not known')
            count = int(n[:-1], 16)
            src, dst = self.regs['esi'], self.regs['edi']
            self.uses_rep = True
            for base, name in ((src, 'esi'), (dst, 'edi')):
                pass
            s_host = self.base_ptr(src, 4 * count, False)
            d_host = self.base_ptr(dst, 4 * count, True)
            self.emit(f'for (int i = 0; i < {count}; i++) {{')
            self.emit(f'    aot_hk_st32({d_host} + 4 * i, aot_hk_ld32({s_host} + 4 * i));')
            self.emit('}')
            self.regs['esi'] = f'({src} + 0x{4 * count:x}u)'
            self.regs['edi'] = f'({dst} + 0x{4 * count:x}u)'
            self.regs['ecx'] = '0x00000000u'
            return
        if mnem == 'ret' and ops == '':
            self.ret = self.tmp('u32')
            self.emit(f'const uint32_t {self.ret} = aot_hk_ld32({self.operand("[esp]", 4, False)});')
            self.sp += 4
            return
        if mnem == 'nop':
            return
        raise Unsupported(text)

    def base_ptr(self, expr, size, write):
        if re.fullmatch(r'0x[0-9a-f]+u', expr):
            addr = int(expr[:-1], 16)
            key = f'0x{addr & ~0xfff:08x}u'
            b = self.bases.setdefault(key, [addr & 0xfff, (addr & 0xfff) + size, False])
            b[0], b[1] = min(b[0], addr & 0xfff), max(b[1], (addr & 0xfff) + size)
            b[2] |= write
            return f'(P_{key[:-1]} + {addr & 0xfff})'
        if not re.fullmatch(r'(g_e[a-z]{2}|a\d+)', expr):
            raise Unsupported(f'copy through {expr}')
        b = self.bases.setdefault(expr, [0, size, False])
        b[0], b[1] = min(b[0], 0), max(b[1], size)
        b[2] |= write
        return f'(P_{expr} + 0)'


def generate(dump, base, start, name):
    insns = disassemble(dump, base, start)
    g = Gen()
    for addr, raw, text in insns:
        if raw[0] in (0xd8, 0xd9, 0xda, 0xdb, 0xdc, 0xdd, 0xde, 0xdf):
            g.x87(raw, text)
        else:
            g.integer(raw, text)
    if g.fp:
        raise Unsupported(f'x87 stack not balanced ({len(g.fp)} left)')
    end = insns[-1][0] + len(insns[-1][1])
    pc = f'{start:08x}'
    lines = [f'/*', f' * 0x{pc} {name}: scripts/hookgen.py from the game\'s code at '
                    f'0x{start:x}..0x{end:x} ({len(insns)} instructions)', ' */',
             f'AOT_HOOK({pc})', '{', f'    AOT_HOOK_BEGIN({pc});']
    lo, hi = g.stack_lo, g.stack_hi
    lines.append(f'    uint8_t *S0 = (uint8_t *)aot_hptr(g_esp - {-lo}u, {hi - lo}, 1);')
    cond = ['!S0']
    if g.uses_rep:
        cond.append(f'AOT_LDM(int32_t, env, AOT_OFF_DF) != 1')
    lines.append(f'    if ({" || ".join(cond)}) {{')
    lines.append('        AOT_HOOK_FALLBACK();')
    lines.append('    }')
    lines.append(f'    uint8_t *const S = S0 + {-lo};')
    for off, var in sorted(g.args.items()):
        lines.append(f'    const uint32_t {var} = aot_hk_ld32(S + {off});')
    checks = []
    for key, (blo, bhi, w) in g.bases.items():
        if key.startswith('0x'):
            page = key[:-1]
            lines.append(f'    uint8_t *const P_{page}0 = (uint8_t *)aot_hptr({key} + {blo}, {bhi - blo}, {int(w)});')
            lines.append(f'    uint8_t *const P_{page} = P_{page}0 - {blo};')
            checks.append(f'!P_{page}0')
        else:
            lines.append(f'    uint8_t *const P_{key}0 = (uint8_t *)aot_hptr({key} + {blo}u, {bhi - blo}, {int(w)});')
            lines.append(f'    uint8_t *const P_{key} = P_{key}0 - {blo};')
            checks.append(f'!P_{key}0')
    if checks:
        lines.append(f'    if ({" || ".join(checks)}) {{')
        lines.append('        AOT_HOOK_FALLBACK();')
        lines.append('    }')
    lines.append('    AOT_SETCSR(((uint32_t)AOT_LDM(uint16_t, env, AOT_OFF_FPUC) & 0xc00u) << 3 | 0x1f80u);')
    lines += g.body
    lines.append('    const uint32_t top = AOT_LDM(uint32_t, env, AOT_OFF_FPSTT);')
    for k in range(1, g.maxdepth + 1):
        lines.append(f'    AOT_STM(uint8_t, env, AOT_OFF_FPTAGS + ((top - {k}) & 7), 1);')
    for r in REGS:
        if r != 'esp' and g.regs[r] != f'g_{r}':
            lines.append(f'    g_{r} = {g.regs[r]};')
    lines.append(f'    g_esp += {g.sp};')
    lines.append(f'    AOT_HOOK_RETURN({g.ret});')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dump')
    ap.add_argument('base')
    ap.add_argument('functions', nargs='+')
    ap.add_argument('--name', default='')
    a = ap.parse_args()
    ok = 0
    for f in a.functions:
        try:
            print(generate(a.dump, int(a.base, 16), int(f, 16), a.name))
            ok += 1
        except Unsupported as e:
            print(f'/* 0x{int(f, 16):08x}: not generated: {e} */\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
