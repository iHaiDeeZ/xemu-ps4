/* xemu-ps4: FreeBSD 9's <sys/event.h> (kqueue/kevent are in the PS4's libkernel; OpenOrbis has no
   header for them). */
#ifndef _XEMUPS4_SYS_EVENT_H
#define _XEMUPS4_SYS_EVENT_H
#include <stdint.h>
#include <sys/types.h>
#include <time.h>

#define EVFILT_READ     (-1)
#define EVFILT_WRITE    (-2)
#define EVFILT_AIO      (-3)
#define EVFILT_VNODE    (-4)
#define EVFILT_PROC     (-5)
#define EVFILT_SIGNAL   (-6)
#define EVFILT_TIMER    (-7)
#define EVFILT_FS       (-9)
#define EVFILT_LIO      (-10)
#define EVFILT_USER     (-11)
#define EVFILT_SYSCOUNT 11

#define EV_SET(kevp_, a, b, c, d, e, f) do {  \
    struct kevent *kevp = (kevp_);            \
    (kevp)->ident = (a);                      \
    (kevp)->filter = (b);                     \
    (kevp)->flags = (c);                      \
    (kevp)->fflags = (d);                     \
    (kevp)->data = (e);                       \
    (kevp)->udata = (f);                      \
} while (0)

struct kevent {
    uintptr_t ident;
    short filter;
    unsigned short flags;
    unsigned int fflags;
    intptr_t data;
    void *udata;
};

#define EV_ADD      0x0001
#define EV_DELETE   0x0002
#define EV_ENABLE   0x0004
#define EV_DISABLE  0x0008
#define EV_ONESHOT  0x0010
#define EV_CLEAR    0x0020
#define EV_RECEIPT  0x0040
#define EV_DISPATCH 0x0080
#define EV_SYSFLAGS 0xF000
#define EV_FLAG1    0x2000
#define EV_EOF      0x8000
#define EV_ERROR    0x4000

#define NOTE_FFNOP      0x00000000
#define NOTE_FFAND      0x40000000
#define NOTE_FFOR       0x80000000
#define NOTE_FFCOPY     0xc0000000
#define NOTE_FFCTRLMASK 0xc0000000
#define NOTE_FFLAGSMASK 0x00ffffff
#define NOTE_TRIGGER    0x01000000
#define NOTE_LOWAT      0x0001
#define NOTE_DELETE     0x0001
#define NOTE_WRITE      0x0002
#define NOTE_EXTEND     0x0004
#define NOTE_ATTRIB     0x0008
#define NOTE_LINK       0x0010
#define NOTE_RENAME     0x0020
#define NOTE_REVOKE     0x0040
#define NOTE_EXIT       0x80000000
#define NOTE_FORK       0x40000000
#define NOTE_EXEC       0x20000000

#ifdef __cplusplus
extern "C" {
#endif
int kqueue(void);
int kevent(int kq, const struct kevent *changelist, int nchanges, struct kevent *eventlist,
           int nevents, const struct timespec *timeout);
#ifdef __cplusplus
}
#endif
#endif
