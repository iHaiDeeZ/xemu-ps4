// libps4compat.a: FreeBSD / glibc C library functions the PS4's C library (OpenOrbis musl +
// libkernel) lacks, for code that takes its __FreeBSD__ paths (the target triple is FreeBSD).
// Declarations: toolchain/xemu-overlay.sh adds them to the sysroot's libc overlay.
// Linked by toolchain/bin/ps4-cc into every program, and installed again as libresolv.a.
#include <errno.h>
#include <netdb.h>
#include <unistd.h>

// closefrom(2): FreeBSD 8+ has a system call; the PS4 kernel's table has none we can rely on.
// The PS4 gives a process few descriptors, so closing the range one by one is cheap.
void closefrom(int lowfd)
{
    long max = sysconf(_SC_OPEN_MAX);
    if (max <= 0 || max > 65536)
        max = 4096;
    for (int fd = lowfd < 0 ? 0 : lowfd; fd < max; fd++)
        close(fd);
}

// The C library has no DNS resolver (host names go through the PS4's own resolver,
// port/ps4_net.cpp). GIO's resolver links against res_query; nothing in xemu looks up SRV/MX
// records, so the lookup always fails.
int res_query(const char *dname, int klass, int type, unsigned char *answer, int anslen)
{
    (void)dname; (void)klass; (void)type; (void)answer; (void)anslen;
    h_errno = NO_RECOVERY;
    return -1;
}

int res_init(void)
{
    return 0;
}
