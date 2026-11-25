/*
  Simple DirectMedia Layer
  Copyright (C) 1997-2026 Sam Lantinga <slouken@libsdl.org>

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.
*/

/*
  PS4 audio driver (xemu-ps4): plays through sceAudioOut's main port at 48 kHz, 16-bit stereo; SDL
  converts the app's streams to that. sceAudioOutOutput blocks until the port has taken the previous
  buffer, which paces SDL's audio thread (as the Vita driver this follows, and the SDL2 driver of the
  Conker ports). The port's length is a multiple of 256 frames (SDL_HINT_AUDIO_DEVICE_SAMPLE_FRAMES,
  default 512 = 10.7 ms: one emulated APU frame is 256, so 512 leaves the producer a frame of slack).
  The audio thread runs at the PS4's priority 400, above every emulation thread: the PS4 gives
  threads of one priority no turns, and a late buffer is an audible gap.
*/
#include "SDL_internal.h"

#ifdef SDL_AUDIO_DRIVER_PS4

#include <stdint.h>
#include <pthread.h>

#include "../SDL_sysaudio.h"

int32_t sceAudioOutInit(void);
int32_t sceAudioOutOpen(int32_t user_id, int32_t type, int32_t index, uint32_t length, uint32_t sample_rate,
                        uint32_t param);
int32_t sceAudioOutClose(int32_t handle);
int32_t sceAudioOutOutput(int32_t handle, const void *buffer);
int scePthreadSetprio(pthread_t thread, int prio);

#define PS4AUD_BUFFERS     2
#define PS4AUD_USER_SYSTEM 0xFF   /* the system's user: sound plays whoever is signed in */
#define PS4AUD_PORT_MAIN   0
#define PS4AUD_S16_STEREO  1
#define PS4AUD_GRANULE     256    /* the port's lengths: 256 .. 2048 frames, in steps of 256 */
#define PS4AUD_PRIORITY    400

struct SDL_PrivateAudioData
{
    int32_t port;
    Uint8 *rawbuf;
    Uint8 *mixbufs[PS4AUD_BUFFERS];
    int next_buffer;
};

static bool PS4AUD_OpenDevice(SDL_AudioDevice *device)
{
    device->hidden = (struct SDL_PrivateAudioData *)SDL_calloc(1, sizeof(*device->hidden));
    if (!device->hidden) {
        return false;
    }
    device->hidden->port = -1;
    if (device->recording) {
        return SDL_SetError("No audio recording on the PS4");
    }

    device->spec.format = SDL_AUDIO_S16LE;
    device->spec.channels = 2;
    device->spec.freq = 48000;
    int frames = 512;
    const char *hint = SDL_GetHint(SDL_HINT_AUDIO_DEVICE_SAMPLE_FRAMES);
    if (hint && SDL_atoi(hint) > 0) {
        frames = SDL_atoi(hint);
    }
    frames = ((frames + PS4AUD_GRANULE - 1) / PS4AUD_GRANULE) * PS4AUD_GRANULE;
    frames = SDL_clamp(frames, PS4AUD_GRANULE, 2048);
    device->sample_frames = frames;
    SDL_UpdatedAudioDeviceFormat(device);

    device->hidden->rawbuf = (Uint8 *)SDL_aligned_alloc(64, device->buffer_size * PS4AUD_BUFFERS);
    if (!device->hidden->rawbuf) {
        return false;
    }
    SDL_memset(device->hidden->rawbuf, 0, device->buffer_size * PS4AUD_BUFFERS);
    for (int i = 0; i < PS4AUD_BUFFERS; i++) {
        device->hidden->mixbufs[i] = &device->hidden->rawbuf[i * device->buffer_size];
    }

    device->hidden->port = sceAudioOutOpen(PS4AUD_USER_SYSTEM, PS4AUD_PORT_MAIN, 0, (uint32_t)frames, 48000,
                                           PS4AUD_S16_STEREO);
    if (device->hidden->port < 0) {
        return SDL_SetError("sceAudioOutOpen failed: %08x", (unsigned)device->hidden->port);
    }
    device->hidden->next_buffer = 0;
    return true;
}

static bool PS4AUD_PlayDevice(SDL_AudioDevice *device, const Uint8 *buffer, int buffer_size)
{
    (void)buffer_size;
    return sceAudioOutOutput(device->hidden->port, buffer) >= 0;
}

static bool PS4AUD_WaitDevice(SDL_AudioDevice *device)
{
    (void)device;   /* sceAudioOutOutput blocks: nothing to wait for here */
    return true;
}

static Uint8 *PS4AUD_GetDeviceBuf(SDL_AudioDevice *device, int *buffer_size)
{
    (void)buffer_size;
    Uint8 *buf = device->hidden->mixbufs[device->hidden->next_buffer];
    device->hidden->next_buffer = (device->hidden->next_buffer + 1) % PS4AUD_BUFFERS;
    return buf;
}

static void PS4AUD_CloseDevice(SDL_AudioDevice *device)
{
    if (!device->hidden) {
        return;
    }
    if (device->hidden->port >= 0) {
        sceAudioOutOutput(device->hidden->port, NULL);  /* lets the last buffer play out */
        sceAudioOutClose(device->hidden->port);
        device->hidden->port = -1;
    }
    if (device->hidden->rawbuf) {
        SDL_aligned_free(device->hidden->rawbuf);
    }
    SDL_free(device->hidden);
    device->hidden = NULL;
}

static void PS4AUD_ThreadInit(SDL_AudioDevice *device)
{
    (void)device;
    scePthreadSetprio(pthread_self(), PS4AUD_PRIORITY);
}

static bool PS4AUD_Init(SDL_AudioDriverImpl *impl)
{
    sceAudioOutInit();  /* "already initialised" (0x8026000e) is fine */
    impl->OpenDevice = PS4AUD_OpenDevice;
    impl->PlayDevice = PS4AUD_PlayDevice;
    impl->WaitDevice = PS4AUD_WaitDevice;
    impl->GetDeviceBuf = PS4AUD_GetDeviceBuf;
    impl->CloseDevice = PS4AUD_CloseDevice;
    impl->ThreadInit = PS4AUD_ThreadInit;
    impl->OnlyHasDefaultPlaybackDevice = true;
    return true;
}

AudioBootStrap PS4AUDIO_bootstrap = {
    "ps4", "PS4 sceAudioOut", PS4AUD_Init, false, false
};

#endif /* SDL_AUDIO_DRIVER_PS4 */
