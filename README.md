# xemu-ps4

[xemu](https://github.com/xemu-project/xemu) (original Xbox emulator, QEMU 10.2) for jailbroken
PS4 homebrew, built in WSL Ubuntu with the Resonance / DolphinPS4 / Crema PS4 toolchain (clang 21 +
libc++ 21 on OpenOrbis). **Paused at v00.15:** boots the BIOS and runs Halo 2 to its title
screen with the DualShock 4, at about 1 fps with rendering errors; findings and next steps in
[docs/PORTING.md](docs/PORTING.md).

- Graphics: xemu's Vulkan NV2A renderer on DolphinPS4's RADV/GNM port; the PS4 frontend
  (`ui/ps4`) presents the renderer's display image on VideoOut (no OpenGL on the PS4)
- CPU: QEMU's TCG (x86 guest on the PS4's x86-64), code buffer in the system flexible pool
- DSP: xemu's interpreter (the dsp56300 JIT is a Rust library with no PS4 build yet)
- Input: the DualShock 4 (ScePad) as an SDL virtual gamepad on Xbox port 1
- UI: ImGui HUD (FPS, GPU and thread load, notifications, setup help); a home screen from
  Resonance's launcher was planned. xemu's own GUI (`ui/xui`) is desktop OpenGL + mouse and isn't built.

## On the console

| Path | What |
|---|---|
| `/data/xemu/bios` | MCPX boot ROM (512 bytes) and flash BIOS (256 KiB or 1 MiB), found by size |
| `/data/xemu/hdd/xbox_hdd.qcow2` | hard disk image |
| `/data/xemu/games` | games (XISO `.iso`) |
| `/data/xemu` | `xemu.toml`, `eeprom.bin`, `xemu.log`, `boot-trace.log`, `crash.log` |

Title ID `XEMU00001`. Install the pkg with GoldHEN's Package Installer.

## Building

```
scripts/seed-build-tree.sh        # ~/xemups4-build from Resonance's tree (sysroot, RADV Mesa build)
scripts/clone-xemu.sh             # upstream xemu at patches/BASE.txt into ~/xemups4-build/src/xemu
git -C ~/xemups4-build/src/xemu checkout -b ps4 && git -C ~/xemups4-build/src/xemu apply ~/xemups4/patches/xemu-ps4.patch
scripts/build-deps.sh             # libc overlay + stub-free libc, Vulkan headers, pixman, glib, SDL3
scripts/rebuild-xemu.sh           # configure + build + eboot.bin (logs in ~/xemups4-build/logs)
XEMU_VERSION=00.01 scripts/package-xemu.sh
scripts/save-patch.sh "message"   # commit ~/xemups4-build/src/xemu and refresh patches/xemu-ps4.patch
```

Run the scripts from WSL through `~/xemups4` (the space in "PS4 Projects" breaks linker flags).
Upload from Windows (Git Bash): `scripts/upload-to-console.sh out/xemu-ps4-vXX.YY.pkg`.

## License

GPL-2.0-or-later, as xemu/QEMU ([LICENSE](LICENSE)): `patches/xemu-ps4.patch` is a modification of
xemu, and the PS4 frontend it adds (`ui/ps4`) is part of that work. The PS4 runtime in `port/` and
the toolchain scripts come from the Resonance / DolphinPS4 / Crema ports; `port/mesa/ac_ps4_drm.c`
is the RADV winsys of the PS4 Mesa port (MIT, as Mesa); `port/third_party` keeps its own notices.
No Microsoft BIOS, boot ROM, Sony system files or games are included: supply your own.
