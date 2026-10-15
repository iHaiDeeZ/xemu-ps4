# CMake toolchain for libraries built for xemu-ps4 (SDL3, ...): the toolchain/bin wrappers as
# compilers (OpenOrbis CRT + libc, clang 21, libc++ 21) and FreeBSD as the system, which is what
# the code sees (__FreeBSD__ from the target triple) and what the PS4 kernel is.
set(CMAKE_SYSTEM_NAME FreeBSD)
set(CMAKE_SYSTEM_VERSION 9)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_CROSSCOMPILING ON)

set(PS4_TOOLCHAIN_BIN $ENV{HOME}/xemups4/toolchain/bin)
if (DEFINED ENV{PS4_SYSROOT})
    set(PS4_SYSROOT $ENV{PS4_SYSROOT})
else ()
    set(PS4_SYSROOT $ENV{HOME}/xemups4-build/sysroot)
endif ()
set(CMAKE_C_COMPILER ${PS4_TOOLCHAIN_BIN}/ps4-cc)
set(CMAKE_CXX_COMPILER ${PS4_TOOLCHAIN_BIN}/ps4-c++)
set(CMAKE_ASM_COMPILER ${PS4_TOOLCHAIN_BIN}/ps4-cc)
set(CMAKE_AR llvm-ar-21 CACHE FILEPATH "")
set(CMAKE_RANLIB llvm-ranlib-21 CACHE FILEPATH "")
set(CMAKE_C_FLAGS_INIT "-march=btver2")
set(CMAKE_CXX_FLAGS_INIT "-march=btver2")

set(CMAKE_FIND_ROOT_PATH ${PS4_SYSROOT})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "")
