# libxemups4_port.a: ps4-kit's runtime (heap, crash log, sampler and profilers, file layer, DNS,
# /net shares) and its Vulkan presenter on VideoOut (gpu/ps4_vk_wsi.cpp), for xemu's meson-built
# program. scripts/build-xemu.sh links it whole and reads kit-link.env (written below) for the
# kit's crt1.o, link script and --wrap lists, so the program links as ps4_kit_app() would link it.
cmake_minimum_required(VERSION 3.20)
project(xemups4_port C CXX ASM)

if (DEFINED ENV{PS4_KIT})
    set(PS4_KIT $ENV{PS4_KIT})
else ()
    set(PS4_KIT $ENV{HOME}/ps4-kit)
endif ()
include(${PS4_KIT}/ps4-kit.cmake)

# crash.log, boot-trace.log, profiles: /data/xemu (the frontend also sets PS4_DIAG_DATA_DIR)
target_compile_definitions(ps4kit_runtime PRIVATE PS4_KIT_DATA_DIR="/data/xemu")

add_library(xemups4_port STATIC $<TARGET_OBJECTS:ps4kit_runtime> ${PS4_KIT_DIR}/gpu/ps4_vk_wsi.cpp)
target_include_directories(xemups4_port PRIVATE ${PS4_KIT_DIR}/gpu ${PS4_KIT_DIR}/runtime ${PS4_MESA_SRC}/include)
target_compile_features(xemups4_port PRIVATE cxx_std_20)
target_compile_options(xemups4_port PRIVATE -O2)

string(REPLACE ";" " " _wraps "${PS4_KIT_WRAPS}")
string(REPLACE ";" " " _app_wraps "${PS4_KIT_APP_WRAPS}")
string(REPLACE ";" " " _stdio_wraps "${PS4_KIT_STDIO_WRAPS}")
file(WRITE ${CMAKE_BINARY_DIR}/kit-link.env
     "PS4_KIT_CRT1=${PS4_CRT1}\n"
     "PS4_KIT_LINK_SCRIPT=${PS4_LINK_SCRIPT}\n"
     "PS4_KIT_WRAPS=\"${_wraps}\"\n"
     "PS4_KIT_APP_WRAPS=\"${_app_wraps}\"\n"
     "PS4_KIT_STDIO_WRAPS=\"${_stdio_wraps}\"\n"
     "PS4_KIT_PAID=${PS4_PAID}\n"
     "PS4_KIT_AUTH_INFO=${PS4_AUTH_INFO}\n")
