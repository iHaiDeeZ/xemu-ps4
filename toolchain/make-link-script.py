#!/usr/bin/env python3
"""Writes the link script for PS4 programs from OpenOrbis' link.x, with Resonance's fixes
(toolchain/ps4-love-style.cmake):

- prioritized constructors (.init_array.NNN: libc++'s iostreams, QEMU's module and type
  registration through constructor attributes) collected, in priority order, and .fini_array;
- per-symbol data sections (.data.*, .tdata.*, .tbss.*: C++ statics, Mesa built with
  -fdata-sections) kept inside .data/.tls. As orphans they landed past the end of the data
  segment's file image, which create-fself cuts off, so they started out as zeros on the console.

    make-link-script.py <OpenOrbis link.x> <out>
"""
import sys

src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()


def sub(old, new):
    global s
    if old not in s:
        sys.exit(f"make-link-script: unexpected {src}: no {old!r}")
    s = s.replace(old, new)


sub("*(.init_array);",
    "KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*) SORT_BY_INIT_PRIORITY(.ctors.*)));\n"
    "\t\tKEEP(*(.init_array .ctors));\n\t}\n\n"
    "\t.fini_array : {\n"
    "\t\tKEEP(*(SORT_BY_INIT_PRIORITY(.fini_array.*) SORT_BY_INIT_PRIORITY(.dtors.*)));\n"
    "\t\tKEEP(*(.fini_array .dtors));")
for rule in (".data", ".tdata", ".tbss"):
    sub(f"*({rule})", f"*({rule} {rule}.*)")
open(dst, "w").write(s)
print(dst)
