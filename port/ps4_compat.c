// libps4compat.a: FreeBSD / glibc C library functions the PS4's C library (OpenOrbis musl +
// libkernel) lacks, for code that takes its __FreeBSD__ paths (the target triple is FreeBSD).
// Declarations: toolchain/xemu-overlay.sh adds them to the sysroot's libc overlay.
// Linked by toolchain/bin/ps4-cc into every program, and installed again as libresolv.a.
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <sys/stat.h>
#include <string.h>
#include <sys/utsname.h>
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

// uname(3): musl's is an ENOSYS stub (and gethostname is built on it). The kernel is FreeBSD 9's.
int uname(struct utsname *u)
{
    memset(u, 0, sizeof(*u));
    strcpy(u->sysname, "FreeBSD");
    strcpy(u->nodename, "ps4");
    strcpy(u->release, "9.0-PS4");
    strcpy(u->version, "PlayStation 4");
    strcpy(u->machine, "amd64");
    return 0;
}

// getresuid/getresgid: the PS4 process has one identity; libkernel has getuid and geteuid.
int getresuid(uid_t *ruid, uid_t *euid, uid_t *suid)
{
    *ruid = getuid();
    *euid = *suid = geteuid();
    return 0;
}

int getresgid(gid_t *rgid, gid_t *egid, gid_t *sgid)
{
    *rgid = getgid();
    *egid = *sgid = getegid();
    return 0;
}

// POSIX calls musl has only as ENOSYS stubs (toolchain/trim-libc.py removes those) that portable
// code calls unconditionally. The PS4's file systems hold no symbolic or hard links and one
// owner, so these answer accordingly.
ssize_t readlink(const char *path, char *buf, size_t size)
{
    (void)path; (void)buf; (void)size;
    errno = EINVAL;     // not a symbolic link
    return -1;
}

int link(const char *from, const char *to)
{
    (void)from; (void)to;
    errno = EPERM;
    return -1;
}

int symlink(const char *from, const char *to)
{
    (void)from; (void)to;
    errno = EPERM;
    return -1;
}

int chown(const char *path, uid_t owner, gid_t group)
{
    (void)path; (void)owner; (void)group;
    return 0;
}

int lchown(const char *path, uid_t owner, gid_t group)
{
    (void)path; (void)owner; (void)group;
    return 0;
}

int fchown(int fd, uid_t owner, gid_t group)
{
    (void)fd; (void)owner; (void)group;
    return 0;
}

// fstatat for paths stat() can take (absolute, or relative to the working directory)
int fstatat(int dirfd, const char *path, struct stat *st, int flags)
{
    if (dirfd != AT_FDCWD && path[0] != '/') {
        errno = ENOSYS;
        return -1;
    }
    return (flags & AT_SYMLINK_NOFOLLOW) ? lstat(path, st) : stat(path, st);
}

mode_t umask(mode_t mask)
{
    (void)mask;
    return 022;
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

// LeakSanitizer's interface: glib calls it when available (weak imports, which create-fself
// refuses unresolved). No sanitizers on the PS4.
void __lsan_ignore_object(const void *p)
{
    (void)p;
}

void __lsan_enable(void)
{
}

void __lsan_disable(void)
{
}
