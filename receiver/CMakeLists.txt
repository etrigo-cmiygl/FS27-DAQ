# The pit receiver ("Rocky"), FS27 version. Louis's FS26-RCV with the PKT line output.
# Build:  cmake -S receiver -B build-rcv -G Ninja -DPICO_BOARD=pico2 && ninja -C build-rcv
cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(PICO_BOARD pico2 CACHE STRING "Board type")

include(${CMAKE_CURRENT_LIST_DIR}/../pico_sdk_import.cmake)

project(FS27-RCV C CXX ASM)
pico_sdk_init()

# The radio drivers are the same ones the DAQ uses
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../src/gpio gpio)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../src/spi spi)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../src/lr1121 lr1121)
include_directories(${CMAKE_CURRENT_LIST_DIR}/../src/gpio)
include_directories(${CMAKE_CURRENT_LIST_DIR}/../src/spi)
include_directories(${CMAKE_CURRENT_LIST_DIR}/../src/lr1121)
include_directories(${CMAKE_CURRENT_LIST_DIR})

add_executable(FS27-RCV
    FS26-RCV_fs27.c
    lr1121_config.c
)

pico_set_program_name(FS27-RCV "FS27-RCV")
pico_set_program_version(FS27-RCV "2.0")
pico_enable_stdio_uart(FS27-RCV 0)
pico_enable_stdio_usb(FS27-RCV 1)

target_link_libraries(FS27-RCV
        pico_stdlib
        pico_multicore
        gpio
        spi
        lr1121
)
target_include_directories(FS27-RCV PRIVATE ${CMAKE_CURRENT_LIST_DIR})
pico_add_extra_outputs(FS27-RCV)
