# Translated code (ahead-of-time)

xemu translates the Xbox's x86 code while a game runs (QEMU's JIT, TCG). On the PS4's CPU that
code is too slow for most games: Halo 2 spent 85-97 % of the emulated CPU's thread in it and
in the helpers it calls. Translated code moves the translation to a PC, as Crema does for Wii U
games: the console records the blocks a game runs, a PC compiles them with clang, and the next
start of that game runs the compiled blocks.

## How to use it

1. Start the game from the library (the title ID comes from its `default.xbe`) and play: menus,
   loading, the parts you want fast. Only code that ran is recorded. The console writes it to
   `/data/xemu/aot/<title ID>/blocks-NNNN.c` (C, a few hundred MB for a big game).
2. On the PC (Windows Git Bash, with WSL's clang-21):

       scripts/aot-console.sh all <title ID> [console IP]

   fetches the recording, builds `out/aot/<title ID>.aot` (`scripts/aot-build.py`) and puts it
   on the console as `/data/xemu/aot/<title ID>.aot`.
3. Start the game again from the library: blocks found in the file run compiled. The live
   console's `aot` command (`python scripts/live.py --host <ip> aot`) shows the file, how often
   the JIT entered it and what is still recorded.

Blocks that ran for the first time after the build keep being recorded; build again later to
add them. The quick menu (L3+R3) turns **Translated code** and **Record for PC** off
(`ps4.ini`: `aot`, `aot_record`).

`aot-data/` and `out/aot/` hold the game's code as C and compiled: keep them private (they are
in `.gitignore`).

## How it works

- **Recording** (`tcg/tcg-aot.c.inc`, `accel/tcg/aot.c`): when the JIT translates a block, its
  TCG ops (QEMU's exact translation of the x86 code, after the optimizer) are also written as a
  C function body. Guest memory goes through QEMU's TLB as the JIT's code does; helpers are
  called by name; every exit stores the guest registers back.
- **Building** (`scripts/aot-build.py`, `aot/aot_rt.h`): each block becomes a function whose
  parameters are the guest registers (eax..edi, cc_dst, cc_src, cc_op) in a calling convention
  that keeps them in host registers (`preserve_none`). A direct jump to a block that is also in
  the file is a guaranteed tail call (`musttail`), so chains of blocks run without returning to
  xemu; other jumps look the target up in the file's own table. Scalar SSE float helpers
  (`mulss`, `addss`, ...) become the host's own instructions when the guest uses the default
  MXCSR. The result is a position-independent ELF object with no imports.
- **Running** (`accel/tcg/aot.c`, `target/i386/tcg/aot-i386.c`): the file is mapped into
  executable direct memory. When the JIT is about to translate a block the file has, with the
  same flags and the same code bytes (hash), it makes a one-instruction TB that calls
  `helper_aot_run`, which runs the compiled block. A block counts as valid once its TB ran;
  TLB flushes over its pages and code writes over its bytes make it go through that check
  again, so changed code falls back to the JIT.
- The file only fits the xemu build that recorded it (`aot_abi.h`'s key): after an xemu update
  that changes the CPU state's layout, record again.
