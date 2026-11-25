# CMake toolchain for what xemu's meson build makes with CMake (glslang, volk, SPIRV-Reflect) and
# for SDL3: the toolchain/bin wrappers as compilers (ps4-kit's: OpenOrbis CRT + C library, clang 21,
# libc++ 21), FreeBSD as the system (what the code sees: __FreeBSD__ from the target triple, and
# what the PS4's kernel is), this port's sysroot as the only place to find packages.
set(CMAKE_SYSTEM_NAME FreeBSD)
set(CMAKE_SYSTEM_VERSION 9)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_CROSSCOMPILING ON)

if (DEFINED ENV{XEMUPS4})
    set(XEMUPS4 $ENV{XEMUPS4})
else ()
    set(XEMUPS4 $ENV{HOME}/xemups4)
endif ()
if (DEFINED ENV{PS4_SYSROOT})
    set(PS4_SYSROOT $ENV{PS4_SYSROOT})
else ()
    set(PS4_SYSROOT $ENV{HOME}/xemups4-build/sysroot)
endif ()
set(CMAKE_C_COMPILER ${XEMUPS4}/toolchain/bin/ps4-cc)
set(CMAKE_CXX_COMPILER ${XEMUPS4}/toolchain/bin/ps4-c++)
set(CMAKE_ASM_COMPILER ${XEMUPS4}/toolchain/bin/ps4-cc)
set(CMAKE_AR llvm-ar-21 CACHE FILEPATH "")
set(CMAKE_RANLIB llvm-ranlib-21 CACHE FILEPATH "")

set(CMAKE_FIND_ROOT_PATH ${PS4_SYSROOT})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "")
# pthreads are in libkernel, which every link through the wrappers has
set(CMAKE_HAVE_LIBC_PTHREAD 1 CACHE INTERNAL "")
set(CMAKE_THREAD_LIBS_INIT "" CACHE INTERNAL "")
set(Threads_FOUND TRUE CACHE INTERNAL "")
