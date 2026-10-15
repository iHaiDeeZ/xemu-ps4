# xemu on PS4: how the port is put together, where it stands, and what's left

**State at v00.15 (2026-10-15), project paused:** xemu boots the Xbox BIOS and runs Halo 2 to its
title screen on a GoldHEN PS4 (firmware 13.52) with the DualShock 4 working, at roughly 1 frame
per second in game, with rendering errors and flicker.

## Architecture

xemu presents through SDL + desktop OpenGL 4.0 even with its Vulkan renderer (the Vulkan display
image is exported to GL), and its GUI (`ui/xui`) draws with OpenGL. The PS4 has no desktop GL, so:

| Desktop xemu | PS4 port |
|---|---|
| `ui/xemu.c`: SDL window, GL context, main loop | `ui/ps4/xemu-ps4.c`: same thread layout (QEMU on its own thread, vblank thread), system modules, `/data/xemu` defaults, BIOS found by size and checked against the MCPX 1.0 ROM, 5 s monitor |
| GL compositor + `ui/xui` (ImGui on OpenGL) | `ui/ps4/ps4-present.cc`: swapchain on the **renderer's own VkDevice/queue**, copy of the last guest frame blitted to fit, ImGui's Vulkan backend on top; `ps4-hud.cc` (overlay: FPS, GPU %, thread load; notifications; setup help) |
| Vulkan display → GL via external memory (`HAVE_EXTERNAL_MEMORY`) | `HAVE_SHARED_DISPLAY_IMAGE`: `hw/xbox/nv2a/pgraph/vk/ps4.c` exposes device, display image and a queue lock shared by every submit/present |
| volk loads libvulkan | `volkInitializeCustom(ps4_vk_get_instance_proc_addr())`: RADV linked in, `ui/ps4/ps4-wsi.cc` (Resonance's VideoOut WSI) adds headless surface + swapchain |
| SDL gamepads | `ui/ps4/ps4-pad.c`: ScePad feeds an SDL virtual gamepad (auto-bound to port 1, rumble) |
| SDL audio | SDL's dummy driver (silent) - no sceAudioOut driver yet |
| dsp56300 Rust JIT (prebuilt per OS) | interpreter (`dsp_jit_stub.c`) |
| libpcap bridge | not available (`net/pcap-stub.c`); NAT (slirp) and UDP build |

Graphics stack: xemu's Vulkan NV2A renderer → RADV (Mesa 26.0.8, Crema/DolphinPS4 PS4 port,
CEMUPS4's build, which has the legacy GS ring fix) → its GNM winsys (`port/mesa/ac_ps4_drm.c`) →
the PS4 GPU; flips through GNM + VideoOut.

## Measured at v00.15 (Halo 2 title screen, profiler on)

| | Load |
|---|---|
| Guest frame rate | 0.6-1 fps (BIOS animation: up to 24 fps) |
| Emulated CPU thread (`CPU 0/TCG`) | 18-45 % busy |
| PS4 GPU (RADV winsys timestamps) | 2-5 % busy |
| NV2A thread (`nv2a.pfifo_thread`) | 6-50 %; 78 % of its samples in a kernel wait |
| APU / DSP thread | ~30 % |
| QEMU main loop | one core (xemu busy-waits near timer deadlines without ppoll) |

**Not CPU-bound and not GPU-bound: synchronization-bound.** Neither the emulated CPU nor the GPU is
saturated; the TCG thread spends a quarter of its samples in the same kernel wait (lock/condition)
the NV2A thread sits in most of the time, and `tlb_reset_dirty` (guest VRAM dirty tracking for the
CPU/GPU hand-off) is its busiest QEMU function after the JIT. The emulated CPU, the NV2A thread
and the PS4 GPU wait on each other (render-target downloads to guest RAM, fence waits, the BQL).
Even with those stalls gone, TCG on the 1.6 GHz Jaguar will stay well below a desktop CPU: heavy
games like Halo 2 are unlikely to reach full speed; lighter ones might get closer.

**Rendering errors: geometry shaders.** xemu runs every primitive except points through a
geometry shader. The renderer's startup self-test (draw triangles through GS, read back) returns
19200 coloured pixels, all opaque, but not where expected (`VK geometry shader winding: 0, 0, 0,
0`): the readback works, the GS output on the PS4's RADV is partly wrong. With Resonance's older
RADV build the GS wrote past its rings and the PS4 killed the app (GPU page fault); CEMUPS4's
build (Crema 34ff87b, rings 4x larger) stopped the crash but not the misplacement.

## Toolchain notes (things that bit)

- **OpenOrbis' libc.a has ~100 Linux calls as ENOSYS stubs** (ppoll, timerfd, inotify, epoll,
  memfd_create, ...). Link-test probes "find" them. `toolchain/trim-libc.py` makes a stub-free
  `libc.a` for builds; the stubs go to `libc_enosys.a`, linked last into the eboot only.
- `toolchain/runtime/ps4_compat.c` (`libps4compat.a`): `closefrom`, `uname`, `readlink`,
  `fstatat`, `getresuid`, `res_query`, LeakSanitizer no-ops (create-fself refuses unresolved
  weak imports), ...
- libc overlay (`toolchain/xemu-overlay.sh`): `struct cmsgcred`, `SOCK_CLOEXEC`, `sys/event.h`,
  a fix for OpenOrbis' `dirent.h` (`d_ino`/`d_fileno`).
- Link script generated from OpenOrbis' `link.x` with Resonance's fixes; both OELF checks run.
- OpenOrbis' `freopen` calls an ENOSYS `dup3` and closes the stream: logs use `open` + `dup2`.
- The PS4 grants execute permission only at mapping time: TCG's code buffer is mapped RWX up
  front (QEMU mprotects it and `exit(1)`s otherwise), capped at 64 MiB.
- No memfd and no `/tmp`: display surfaces in plain memory, `TMPDIR=/data/xemu/tmp`.
- The renderer's ring buffers were sized for desktop drivers (~4.8 GB): ~1 GB on the PS4
  (`vk/buffer.c`), surface scale pinned to 1x.
- QEMU must keep its coroutine pool: without it every disk request mapped a 1 MiB stack through a
  ~9 ms system call.
- The display is fetched from the renderer only when the guest flips (or every 250 ms): each fetch
  flushes and waits for the renderer if the displayed surface was drawn into.
- Pad reads with bit 31 set (`0x80000000`) are "intercepted": the system holds the input.
- BIOS pairing: `mcpx_1.0.bin` needs a v1.0-era flash BIOS (kernel 3944/4034/4132/4627, e.g.
  Complex 4627); later BIOSes (e.g. 5838, v1.6 / MCPX 1.1) black-screen. The frontend checks.

## Where to pick it up

1. **Geometry shaders on RADV/GNM** (rendering errors): reproduce with the GS self-test
   (`gpuprops.c`), compare the ES->GS / GS->VS ring setup in `radv_queue.c` / the winsys with
   what GNM programs (`VGT_*_RING_SIZE`, `SPI_SHADER_PGM_*` for ES/GS on GFX7). An alternative is
   to avoid GS where xemu can (provoking vertex via `VK_EXT_provoking_vertex`, quads via index
   conversion), which also lowers GPU cost.
2. **Synchronization stalls** (speed): find what the TCG and NV2A threads wait on (sample call
   stacks, not only leaf addresses), reduce surface downloads and fence waits; replace the main
   loop's busy-wait with a precise sleep.
3. Audio: an SDL3 audio driver on sceAudioOut (Resonance's `audiobackend_ps4.cpp`).
4. Home screen: Resonance's launcher on the presenter's ImGui (game list = `/data/xemu/games`).
5. Later: the dsp56300 JIT (Rust/Cranelift) for the PS4.

## Diagnostics on the console

- `/data/xemu/boot-trace.log`: start-up, the 5 s monitor (FPS, GPU %, thread load, pad, system).
- `/data/xemu/xemu.log`: QEMU/xemu/RADV output; `crash.log` on faults (`scripts/crashlog.sh`).
- `/data/xemu/profile.txt` present: the sampler writes `samples.log` every 10 s.
- `/data/xemu/qemu-args.txt`: extra QEMU arguments, one per line (e.g. `-d in_asm -D file`).
