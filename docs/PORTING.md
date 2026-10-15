# xemu on PS4: how the port is put together, and what's left

State as of 2026-10-15 (v00.01): **builds and packages; not yet run on the console.**

## Architecture

xemu presents through SDL + desktop OpenGL 4.0 even with its Vulkan renderer (the Vulkan display
image is exported to GL), and its GUI (`ui/xui`) draws with OpenGL. The PS4 has no desktop GL, so:

| Desktop xemu | PS4 port |
|---|---|
| `ui/xemu.c`: SDL window, GL context, main loop | `ui/ps4/xemu-ps4.c`: same thread layout (QEMU on its own thread, vblank thread), system modules, `/data/xemu` defaults, BIOS found by size |
| GL compositor + `ui/xui` (ImGui on OpenGL) | `ui/ps4/ps4-present.cc`: swapchain on the **renderer's own VkDevice/queue**, blit of the display image scaled to fit, ImGui's Vulkan backend on top; `ps4-hud.cc` |
| Vulkan display → GL via external memory (`HAVE_EXTERNAL_MEMORY`) | `HAVE_SHARED_DISPLAY_IMAGE`: `hw/xbox/nv2a/pgraph/vk/ps4.c` exposes device, display image and a queue lock shared by every submit/present |
| volk loads libvulkan | `volkInitializeCustom(ps4_vk_get_instance_proc_addr())`: RADV linked in, `ui/ps4/ps4-wsi.cc` (Resonance's VideoOut WSI) adds headless surface + swapchain |
| dsp56300 Rust JIT (prebuilt per OS) | interpreter (`dsp_jit_stub.c`) |
| libpcap bridge | not available (`net/pcap-stub.c`); NAT (slirp) and UDP work |

Other source changes are PS4 guards on FreeBSD-only code (the target triple is FreeBSD, the C
library is OpenOrbis musl): thread ids, tap, serial/parallel ports, raw disk ioctls, procctl.

## Toolchain notes (things that bit)

- **OpenOrbis' libc.a has ~100 Linux calls as ENOSYS stubs** (ppoll, timerfd, inotify, epoll, ...).
  Link-test probes then "find" them: xemu would have run its main loop on a `ppoll` that always
  fails. `toolchain/trim-libc.py` makes a stub-free `libc.a` for builds; the stubs go to
  `libc_enosys.a`, linked last into the eboot only.
- `toolchain/runtime/ps4_compat.c` (`libps4compat.a`): `closefrom`, `uname`, `readlink`,
  `fstatat`, `getresuid`, ..., `res_query`, LeakSanitizer no-ops (create-fself refuses unresolved
  weak imports).
- libc overlay additions (`toolchain/xemu-overlay.sh`): `struct cmsgcred`, `SOCK_CLOEXEC`,
  `sys/event.h` (kqueue is in libkernel), and a fix for OpenOrbis' `dirent.h`, which makes both
  `d_ino` and `d_fileno` unusable.
- The link script is generated from OpenOrbis' `link.x` with Resonance's fixes (prioritized
  constructors, `.data.*`/`.tdata.*`/`.tbss.*` kept in the file image); both OELF checks
  (`check-oelf.cmake`, `check-oelf-data.py`) run after create-fself.
- `toolchain/bin/ps4-cc` / `ps4-c++` are the compilers for meson and CMake; the eboot's final link
  adds the port runtime, RADV and system libraries through `PS4_APP_LDFLAGS` (`scripts/build-xemu.sh`).

## Next steps

1. **First run on the console**: `boot-trace.log`, `xemu.log`, `crash.log`. Expected risk areas:
   - coroutines (`--with-coroutine=sigaltstack`) on the PS4's signal delivery;
   - TCG's code buffer (RWX `mmap`, routed to the system flexible pool by `--wrap=mmap`);
   - RADV features the renderer requires (`geometryShader`, `shaderTessellationAndGeometryPointSize`,
     `occlusionQueryPrecise`, `depthClamp`, `fillModeNonSolid`, `shaderClipDistance`);
   - the shared-queue presenter (the display image's layout handoff).
2. **Input**: an SDL3 joystick driver on ScePad (SDL is built without one; xemu-input.c then works
   unchanged, rumble included). Resonance's `ps4_gamepad.cpp` has the ScePad side.
3. **Audio**: an SDL3 audio driver on sceAudioOut (Resonance's `audiobackend_ps4.cpp`); SDL3 patches
   go to `patches/sdl3-ps4.patch` (applied by `build-deps.sh sdl3`).
4. **Home screen**: port Resonance's launcher (themes, covers, quick menu, settings) onto this
   presenter's ImGui; game list = XISO files in `/data/xemu/games`; `xemu_load_disc()` to start.
5. Frames drawn without the GPU (VGA framebuffer path) aren't shown yet; snapshot thumbnails are
   not made (`ps4-thumbnail.cc`).
6. Performance: TCG on the Jaguar cores is the main cost (the Xbox's 733 MHz Pentium III emulated on
   1.6 GHz Jaguar); profile with the port's sampler (`/data/xemu/profile.txt`). Later: the dsp56300
   JIT (Rust, Cranelift) for `x86_64-unknown-freebsd` against this libc.
