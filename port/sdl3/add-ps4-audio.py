#!/usr/bin/env python3
"""Adds the PS4 audio driver (port/sdl3/SDL_ps4audio.c) to an SDL3 source tree, idempotently.

    add-ps4-audio.py <SDL3 source dir>

CMake option SDL_PS4_AUDIO (default OFF) builds it; SDL_audio.c lists it first, so it is the
default playback driver when built in.
"""
import pathlib
import shutil
import sys

src = pathlib.Path(sys.argv[1])
here = pathlib.Path(__file__).resolve().parent


def edit(rel, anchor, text, after=True):
    p = src / rel
    s = p.read_text(encoding='utf-8')
    if text.strip() in s:
        return
    if anchor not in s:
        sys.exit(f'{rel}: anchor not found: {anchor!r}')
    s = s.replace(anchor, anchor + text if after else text + anchor, 1)
    p.write_text(s, encoding='utf-8', newline='\n')


(src / 'src/audio/ps4').mkdir(exist_ok=True)
shutil.copyfile(here / 'SDL_ps4audio.c', src / 'src/audio/ps4/SDL_ps4audio.c')

edit('include/build_config/SDL_build_config.h.cmake', '#cmakedefine SDL_AUDIO_DRIVER_VITA 1\n',
     '#cmakedefine SDL_AUDIO_DRIVER_PS4 1\n')
edit('src/audio/SDL_sysaudio.h', 'extern AudioBootStrap N3DSAUDIO_bootstrap;\n',
     'extern AudioBootStrap PS4AUDIO_bootstrap;\n')
edit('src/audio/SDL_audio.c', 'static const AudioBootStrap *const bootstrap[] = {\n',
     '#ifdef SDL_AUDIO_DRIVER_PS4\n    &PS4AUDIO_bootstrap,\n#endif\n')
edit('CMakeLists.txt', 'dep_option(SDL_DUMMYAUDIO          "Support the dummy audio driver" ON "SDL_AUDIO" OFF)\n',
     'option(SDL_PS4_AUDIO "PS4: the sceAudioOut driver (src/audio/ps4)" OFF)\n')
edit('CMakeLists.txt', '  # CheckDummyAudio/CheckDiskAudio - valid for all platforms\n',
     '  if(SDL_PS4_AUDIO)\n'
     '    set(SDL_AUDIO_DRIVER_PS4 1)\n'
     '    sdl_glob_sources("${SDL3_SOURCE_DIR}/src/audio/ps4/*.c")\n'
     '    set(HAVE_SDL_AUDIO TRUE)\n'
     '  endif()\n')
print(f'{src}: PS4 audio driver added')
