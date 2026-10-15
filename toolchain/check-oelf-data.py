#!/usr/bin/env python3
"""Fails if an initialized writable section of the OELF lies outside the file image of its PT_LOAD.

create-fself writes each data segment's file image only as far as it expects (.data); a section
after it - an orphan the linker script doesn't place (protobuf's pb_defaults in rpcs3 v01.00-01.02,
.data.* in DolphinPS4 before fdd639f) - then starts out as zeros on the console. Silent: rpcs3 hung
in protobuf's start-up loop with a black screen.

    check-oelf-data.py <file.oelf>
"""
import re
import subprocess
import sys

oelf = sys.argv[1]
readelf = "llvm-readelf-21"

segs = []
for line in subprocess.run([readelf, "-lW", oelf], capture_output=True, text=True, check=True).stdout.splitlines():
    m = re.match(r"\s*LOAD\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+)", line)
    if m and "W" in m.group(6):
        vaddr, filesz, memsz = int(m.group(2), 16), int(m.group(4), 16), int(m.group(5), 16)
        segs.append((vaddr, vaddr + filesz, vaddr + memsz))

bad = []
for line in subprocess.run([readelf, "-SW", oelf], capture_output=True, text=True, check=True).stdout.splitlines():
    m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)\s+\S+\s+(\S*)", line)
    if not m or m.group(2) != "PROGBITS" or "W" not in m.group(5):
        continue
    name, addr, size = m.group(1), int(m.group(3), 16), int(m.group(4), 16)
    if size == 0 or name.startswith(".tdata"):
        continue
    for start, file_end, mem_end in segs:
        if start <= addr < mem_end:
            if addr + size > file_end:
                bad.append(f"{name} at 0x{addr:x}+0x{size:x} ends past the segment's file image (0x{file_end:x})")
            break

if bad:
    sys.exit("check-oelf-data: " + oelf + ":\n  " + "\n  ".join(bad) +
             "\nthese sections would be zeros on the console: place them inside .data (toolchain/ps4-love-style.cmake)")
print(f"check-oelf-data: {oelf}: data sections inside the file image")
